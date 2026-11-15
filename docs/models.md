# The two models

Napas Gambut adds two small machine-learning steps to the pipeline. Both run in Python before the export, and the app only displays what they write into the bundle (data contract 0.2, see `docs/data-contract.md`). Neither has run on real NISAR data yet: every number below comes from simulated tables and says only that the code works.

| Model | Stage | What it gives the app |
| --- | --- | --- |
| Land cover from radar ("Model A") | `pipeline/04b_landclass_features.py`, `pipeline/04c_landclass.py` | Each cell's land type (only if the model passes its checks), the set of covers the radar cannot rule out, and a "worth checking on the ground" flag |
| Fire-risk hindcast | `pipeline/07b_fire_risk.py` | A test of whether a small model ranks burned cells better than three simple rules, and a table of fire rate by HV radar index |

## Running them

Stage order: `03_grid → 04_stats → 04b_landclass_features → 04c_landclass → 05_coherence → 06_context_tabular → 06_context_visuals → 07_states → 07b_fire_risk → 08_export`.

```bash
py pipeline/04b_landclass_features.py
py pipeline/04c_landclass.py
py pipeline/07b_fire_risk.py
py pipeline/08_export.py
```

Every new stage has an offline check that needs no data files: `py pipeline/<stage>.py --self-test`.

Python packages beyond the existing pipeline: `scikit-learn==1.9.1`, `mapie==1.6.0`, `cleanlab==2.9.0` (install with `py -m pip install`). GLCM texture is written in numpy, so scikit-image is not needed.

## Land cover from radar

- **Features** (per 500 m cell, from the radar cube): season median HH and HV, HH minus HV, how HV varies over the season, how HV varies inside the cell, GLCM texture of the season-median HV image (contrast, homogeneity, entropy; 16 levels), and distance to the nearest river. Canal density and any HH drying statistic are left out on purpose: the classes feed the canal and drying checks, so using them would be circular.
- **Labels:** four cover classes (forest, cleared or degraded land, plantation, built-up) from the stage-03 maps: ESA WorldCover 2021 and GFW concessions. Only cells where one class fills at least 80% of the cell and both maps agree are used for training.
- **Validation:** whole 5 km blocks are split first: 20% calibration, 20% held-out check, 60% training. Accuracy is cross-validated by block (5 folds).
- **Class sets:** MAPIE split conformal sets at 90%, calibrated on all calibration cells against the map labels. "90%" therefore means agreement with the 2021 maps, not with the ground. Because the maps have errors, sets with two classes are common and empty sets ("radar can't tell") are rare.
- **Worth checking:** cleanlab finds cells whose map label the radar confidently disputes (out-of-fold probabilities); only cells with a one-class set are flagged.
- **Used or not:** the export uses the model's classes only if block-CV accuracy is at least 0.75, coverage on the held-out blocks is at least 0.87, and every cover class has at least 20 clean training cells. Otherwise the map classes stay and the bundle says why. Reference-forest cells are always chosen by the maps, never by the radar.
- **From cover to land type:** stage 03's own rules (peat map, canals, dams), with the radar's cover in place of the map's.

## Fire-risk hindcast

- **One row** per cell and radar pass: did the cell have a VIIRS fire before the next pass? Rows stop after a cell's first fire.
- **Features, all known at the pass:** HV radar index and its change since the previous pass, canal density, distance to the nearest earlier fire (capped at 30 km), interval length (36 days across the Jul–Aug data gap), land cover. Regional rain is not used: it is one value per pass and added no ranking skill on the simulated table.
- **Model:** L2 logistic regression, penalty chosen by 5-fold cross-validation grouped by 5 km block.
- **Test:** the last two passes, never seen in training. Three simple rules to beat: B1 a fire within 2 km in the interval just ended, B2 rank by HV radar index, B3 both together. Scores: PR-AUC, share of fires caught in the top 10% of cells per pass, Brier score, and 95% intervals from 1,000 resamples of 5 km blocks.
- **Bar:** the model counts only if the low end of its 95% interval is above the best rule. If it is, the scorecard gets a `fire_risk_capture` check. If not, the app shows only the table and says the model did not beat the simple rule. On the simulated table it does not pass, which is the expected, honest outcome.
- **Wording:** "hindcast, 2026 season, one site". It ranks cells; it is not a forecast.

## Guards in the export

`08_export.py` refuses to write a real bundle when:
- the radar cube is not marked as streamed live from ASF (`01_fetch.py` writes `data_source`; dry-run cubes are marked `synthetic_dry_run`);
- the land-model report and `data/grid_provenance.json` disagree about where the classes came from;
- any of the earlier stand-ins remain (fallback canals, rule-of-thumb classes, the coherence proxy, a synthetic smoke picture).

`--allow-unverified` still writes a local test bundle labelled simulated.

## Reference runs on simulated data

`ml/mock/` holds simulated tables, and `ml/Lancdclass/` and `ml/Firerisk/` hold the team's Colab outputs on them. The self-tests of `04c_landclass.py` and `07b_fire_risk.py` compare against those outputs. These numbers prove the code runs; they are not results and never go in the app or the pitch.
