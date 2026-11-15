# Mock training data for the two planned models

**Simulated, not measured.** Use these tables to build and test the model code before the real pipeline tables exist. Never report a number trained on them as a result.

Regenerate with `py ml/mock/generate_mock.py` (seed 20261114; the output is byte-identical on every run). The script ends with self-checks on shape, realism ranges and leakage.

| File | Model | Rows | One row is |
| --- | --- | --- | --- |
| `landclass_cells_mock.csv` | Land-class Model A (gradient-boosted trees) | 1,000 | one 500 m cell |
| `fire_risk_mock.csv` | Fire-risk L2 logistic model | 7,844 | one cell at one pass, predicting the next interval |

Both tables share `cell_id` and `block_id`, so they join. The fire table has more than 1,000 rows on purpose. Fires are rare (about 1.5% of rows), and 1,000 rows would hold only about 15 fires, too few to fit or test anything.

## How it was simulated

- **Grid and dates are real:**
  - the study grid of 110 × 111 cells of 500 m, from `config.yaml`;
  - the 10 kept NISAR passes from `data/kept_dates.json`, including the 36-day gap between 16 July and 21 August.
- **Radar levels are anchored to sources:**
  - Forest uses the real reference-forest medians in `data/noise_floor.json` (HH −8.0 dB, HV −15.0 dB, noise 0.12 dB).
  - The other classes are offset using the [CEOS Layman's SAR Interpretation Guide v3.0](https://ceos.org/ard/files/Laymans_SAR_Interpretation_Guide_3.0.pdf): PALSAR-2 L-band oil palm at HH −7.2 / HV −14.6 dB, secondary growth at HH −10.9 / HV −18.5 dB.
  - [Torbick et al. 2016](https://doi.org/10.3390/rs8030236) is the source for plantation HV sitting below natural forest.
- **The landscape is invented:**
  - Land classes are Voronoi patches, mostly forest west of a river line and degraded or plantation land east of it.
  - The town sits near Palangka Raya's position.
  - Rain follows a dry El Niño pattern: almost none from August to October, then rain returns late October.
  - Drying follows a simple water deficit.
  - Fires depend on dryness, canals, class and fires nearby in the last interval.
  - A fire lowers HV and raises HH by 1 to 4 dB in the passes after it.
- **The older maps are wrong in realistic ways:**
  - Some patches were cleared after the 2021 maps, so they are labelled forest while the radar shows degraded land.
  - Some patches were planted after the 2019 palm map.
  - About 4% of the remaining cells are confused at random.
  - Overall, 7.7% of map labels are wrong.

**What the planned models score on it** (a scratch check, not saved):

- **Land class:** with 5-fold `GroupKFold` by `block_id`, Model A scores 0.87 accuracy against the map labels and 0.92 against the truth. Plantation is the hard class.
- **Fire risk:** trained on passes up to 26 September and tested on 8 and 20 October, the logistic model's PR-AUC is 0.15. The baselines score 0.14 (drying rank) and 0.05 (fire within 2 km), against a base rate of 0.04.

That is close to the result the plan warns about: the model barely beats the drying-rank baseline. The real data may do the same.

**In the pipeline:** both models now run as pipeline stages (`pipeline/04b_landclass_features.py`, `pipeline/04c_landclass.py`, `pipeline/07b_fire_risk.py`; see `docs/models.md`). Their `--self-test` runs on these two tables and compares with the team's Colab outputs in `ml/Lancdclass/` and `ml/Firerisk/`. Those outputs and the `.joblib` files were made on simulated data with another scikit-learn version; the pipeline retrains instead of loading them.

## `landclass_cells_mock.csv`

| Column | Meaning |
| --- | --- |
| `cell_id` | `rRRRcCCC`, the same scheme as the app bundle |
| `block_id` | 5 km spatial block (10 × 10 cells); use as `groups` in `GroupKFold` |
| `lon`, `lat` | Cell centre, approximate (WGS84) |
| `median_hh_db`, `median_hv_db` | Median γ⁰ over the 10 passes, dB |
| `hh_minus_hv_db` | `median_hh_db − median_hv_db` |
| `hv_temporal_cv` | Std ÷ mean of linear HV over the passes |
| `hv_spatial_std_db` | Std of 20 m HV pixels inside the cell, dB |
| `glcm_contrast`, `glcm_homogeneity`, `glcm_entropy` | GLCM texture of HV, 16 levels (entropy in nats, at most ln 256) |
| `dist_river_m` | Distance to the river line, m |
| `label_map` | Weak label fused from the older maps: `forest`, `degraded`, `plantation`, `built`. **Training target** |
| `label_purity` | Share of the cell's map pixels that agree with `label_map` (filter at ≥ 0.8) |
| `n_maps_agree` | How many of the 4 source maps agree with `label_map` |
| `hand_label` | Hand-checked class for 100 cells; empty otherwise. Use only for the final check |
| `true_class_mock` | **Mock only.** The simulated truth. Never a feature or a target; use it to score the models and the cleaning step |
| `label_is_wrong_mock` | **Mock only.** 1 if `label_map ≠ true_class_mock` |
| `map_out_of_date_mock` | **Mock only.** 1 if the label is wrong because the land changed after the maps. Confident learning should flag these |

`built` cells are over-sampled (all 60 in the sample) so the class has enough rows. Canal density is not in this table: the design keeps it out of Model A so the canal hypothesis test stays fair.

## `fire_risk_mock.csv`

Features come from pass `pass_date`. The target is a fire detection in the interval that ends at `target_interval_end`. A cell's rows stop after its first fire, and nothing from the target interval is used as a feature.

| Column | Meaning |
| --- | --- |
| `cell_id`, `block_id` | As above |
| `pass_date` | The pass the features come from |
| `target_interval_end` | The pass that closes the predicted interval |
| `target_interval_days` | 12, or 36 across the data gap (more time, more chance of fire) |
| `land_class` | The map label (stands in for Model A's output) |
| `canal_density_km_per_km2` | Canal length per km² |
| `hv_index_db` | HV drying index at `pass_date`: change since 22 June against the reference forest, dB (negative = drier) |
| `hv_index_change_db` | Change in `hv_index_db` since the previous kept pass |
| `dist_prior_fire_km` | Distance to the nearest earlier fire anywhere in the box, capped at 30 km (30 = none). Take the log before fitting |
| `rain_interval_mm` | Rain in the interval ending at `pass_date` (ERA5-scale, 2 × 2 tiles) |
| `fire_within_2km_interval` | 1 if a fire was detected within about 2 km in the interval ending at `pass_date`. Baseline B1 |
| `fire_next_interval` | **Target.** 1 if a fire was detected in the cell in the next interval |

Suggested split, following the AI and ML Enhancement Plan:
- **Locked test:** the last two pass dates (8 and 20 October).
- **Training:** everything earlier, with `GroupKFold` by `block_id` inside it.
- **Scoring:** PR-AUC and top-10% capture, never accuracy.

## What this data cannot do

- **Model B (the U-Net)** needs 20 m image chips, not cell rows, so it can't be trained from these files.
- **The class signatures are plausible but invented.** Tune hyperparameters on the real table, not this one.
