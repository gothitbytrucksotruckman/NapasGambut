# Napas Gambut (*Peat's Breath*)

**When smoke hides the peat, NISAR still sees it.**

An interactive 12-day L-band radar peatland monitor built by **Team Betelgeuse** for the **NASA Space Apps Challenge 2026** (*Dancing with the SARs*).

**Live app:** https://gothitbytrucksotruckman.github.io/NapasGambut/ (English and Bahasa Indonesia, works offline after the first visit)

## The problem

Peatlands cover 3–4% of Earth's land but store up to a third of its soil carbon ([UNEP Global Peatlands Assessment, 2022](https://www.unep.org/en/news-and-stories/press-release/global-assessment-reveals-huge-potential-peatlands-climate-solution)). When drained peat dries out it burns below the surface. In 2015, Indonesia lost 2.6 million ha to fire and US$16.1 billion; about a third of the burned area was peat, which made most of the haze ([World Bank, *The Cost of Fire*, 2016](https://doi.org/10.1596/23840)).

Peat-restoration staff and village fire brigades decide which canals to block before the next dry spell. Under smoke and cloud, optical satellites cannot show them where the peat is drying.

## What Napas Gambut does

**Napas Gambut** tracks tropical peat drying, re-wetting, burning, and fires the radar misses across a 500 m grid in Central Kalimantan, Indonesia (`study_box: [113.75, -2.25, 114.25, -1.75]`). It compares L-band SAR change against dense forest on mineral (non-peat) soil and that forest's own noise floor, and labels a cell only when its change is larger than that noise. Because L-band radar sees through haze, it keeps working when smoke hides the ground from optical cameras. It measures a relative wetness signal, not water-table depth or subsidence.

The app has five screens:

1. **Smoke and radar**: a swipe between a smoky true-colour image and the radar view of the same day.
2. **Season map**: plays every 12-day pass; each 500 m cell is coloured by its state, and a pulse card per cell shows its wetness against the noise band, rain, coherence and fires.
3. **Scorecard**: results by land type, where to block canals first, which dams to inspect, and the self-checks.
4. **Method**: the method in plain language, its limits, and the use of AI.
5. **Global peat**: the world's large tropical peatlands NISAR passes over every 12 days.

## Status (15 Nov 2026)

- The live app shows a **simulated season**, labelled "Simulated data" on every screen. No simulated number is presented as a measurement.
- Real data so far: two NISAR GCOV passes (22 Jun and 4 Jul 2026) streamed from ASF, and the real 500 m grid (OSM canals, GFW peat and concessions, ESA WorldCover).
- The pipeline stages pass their self-tests on simulated inputs. `08_export.py` will not write a real bundle until every kept pass is live data, so the app switches to real data with no code changes once the remaining passes are streamed.

## NASA data used

| Dataset | Role |
| --- | --- |
| NISAR L2 GCOV (NASA-ISRO, via ASF DAAC) | Core signal: 12-day L-band HH/HV backscatter |
| NASA FIRMS VIIRS 375 m active fires | Fire detections joined to each cell and pass |
| NASA GIBS VIIRS true colour | The smoke image on the Smoke and radar screen |
| NISAR L2 SME2 soil moisture (provisional) | Cross-check only; skipped when it can't be streamed |
| NISAR L2 GUNW | Coherence; empty when no interferometric pairs exist |
| MODIS MCD64A1 burned area | Burn-scar cross-check |

Other data: ESA WorldCover 2021, Global Forest Watch peat and concessions, OpenStreetMap waterways, BRGM PRIMS, Open-Meteo ERA5 rainfall, Copernicus Sentinel-1, Natural Earth. Full list, licences and citations: [`docs/sources.md`](docs/sources.md).

## Architecture

Offline computation is kept apart from the browser:

- **Python pipeline ([`pipeline/`](pipeline/))**: ingests HDF5/Zarr SAR data, WorldCover tiles, GFW peat and concession polygons, OpenStreetMap canals, NASA FIRMS fire detections, rainfall and cross-check sensors, and exports a compact static bundle.
- **Static React + MapLibre web app ([`src/`](src/))**: renders the JSON/GeoJSON/PNG bundle client-side with no runtime backend calls (only optional basemap tiles), full English/Indonesian localisation, and an offline service worker ([`public/sw.js`](public/sw.js)). The app never recomputes science; every number comes from the bundle.

---

## Quick Start (Web App)

Requires **Node.js >= 20** and `npm` (the deploy workflow uses Node 24).

```bash
# 1. Install frontend dependencies
npm install

# 2. Generate the deterministic Contract 0.2 simulated bundle in public/bundle/
npm run mock

# 3. Validate the active bundle against the Zod schema & image guards
npm run check-bundle

# 4. Run unit, contract, reading-level, and i18n tests
npm test

# 5. Typecheck and build the static site for deployment
npm run typecheck
npm run build

# 6. Start the local dev server (or preview the built dist/)
npm run dev
npm run preview
```

Pushing to `main` builds and publishes the site to GitHub Pages ([`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)).

---

## Python Pipeline Setup & Stages

Requires **Python 3.11+**. Pinned dependencies live in [`pipeline/requirements.txt`](pipeline/requirements.txt):

```bash
python -m venv .venv
# Activate your virtualenv, then install pinned packages:
pip install -r pipeline/requirements.txt
```

Pipeline settings (bounding box, UTM cell size, `2σ / 3σ / 4σ` thresholds, `50 mm` rain-return threshold, noise floor limit `0.50 dB`, and output paths) are configured in [`config.yaml`](config.yaml).

### Stage Overview

| Stage / Module | Responsibility |
| --- | --- |
| [`pipeline/00_census.py`](pipeline/00_census.py) | Query the ASF catalogue for `NISAR_L2_GCOV` scenes on a locked track, frame, direction, and mode (`2005`, `DH`). |
| [`pipeline/01_fetch.py`](pipeline/01_fetch.py) | Stream/subset `HHHH`, `HVHV`, `mask`, and `numberOfLooks` layers into `data/gcov_cube.zarr`, marking the cube `asf_live_stream` or `synthetic_dry_run`. |
| [`pipeline/02_quality.py`](pipeline/02_quality.py) | Scene quality gating, reference stability check, and valid-date filtering (`data/quality_report.json`, alias `data/qc_report.json`). |
| [`pipeline/03_grid.py`](pipeline/03_grid.py) | Build the 500 m UTM 49S (`EPSG:32749`) grid from OSM waterways, GFW peat & concessions, BRGM PRIMS canal blocks when available (none found for this box yet, so no cell is classed "rewetted"), and ESA WorldCover 10 m. Reference cells are dense forest on mineral soil; if too few exist, `reference_soil` in `data/grid_provenance.json` says so and the export relabels them (`data/grid_cells.parquet`, `data/grid_provenance.json`). |
| [`pipeline/04_stats.py`](pipeline/04_stats.py) | Linear-power spatial block averaging before dB conversion, forest-reference double differencing (`D_ct`), speckle error, and empirical MAD noise floor (`σ_t`). |
| [`pipeline/04b_landclass_features.py`](pipeline/04b_landclass_features.py) | Per-cell radar features (seasonal statistics, HV texture, distance to river) for the land-cover model. |
| [`pipeline/04c_landclass.py`](pipeline/04c_landclass.py) | Land-cover model: trained on map labels, gives each cell a conformal set of classes (empty = "radar can't tell"), flags cells whose 2021 map label looks out of date; a gate decides whether the export may use it. |
| [`pipeline/05_coherence.py`](pipeline/05_coherence.py) | Experimental L-band InSAR coherence (`NISAR_L2_GUNW`) extension; remains empty when no valid pairs exist. |
| [`pipeline/05b_soil_moisture.py`](pipeline/05b_soil_moisture.py) | Provisional `NISAR_L2_SME2` (200 m EASE-Grid 2.0) soil-moisture ingestion and quality/VWC masking (`data/sme2_cells.parquet`, `data/sme2_report.json`). |
| [`pipeline/06_context_tabular.py`](pipeline/06_context_tabular.py) | NASA FIRMS VIIRS 375 m interval fire joins (including a 187.5 m adjacency buffer) and Open-Meteo ERA5 rainfall totals. |
| [`pipeline/06_context_visuals.py`](pipeline/06_context_visuals.py) | NASA GIBS/Worldview true-colour optical imagery vs L-band SAR PNGs for the Smoke and radar swipe. |
| [`pipeline/07_states.py`](pipeline/07_states.py) | Rule-based state classifier, first matching rule wins: no data, fire (radar agrees), fire (radar silent), burned, re-wetting, deep drying, drying, stable. |
| [`pipeline/07b_fire_risk.py`](pipeline/07b_fire_risk.py) | Fire-risk hindcast (2026 season, one site): a logistic model scored against simple baselines; shown only if it beats them. It is not a forecast. |
| [`pipeline/canal_ranking.py`](pipeline/canal_ranking.py) | Rank the top 20 drainage canals for canal blocking within a 1 km peat cell buffer (`--self-test` supported). |
| [`pipeline/scorecard_tests.py`](pipeline/scorecard_tests.py) | Scientific self-checks (`reference_steady`, `split_half_null`, `fire_agreement`, `size_sensitivity`) and multi-sensor cross-checks (`soil_moisture_agrees`, `cband_same_direction`, `burned_matches_modis`). |
| [`pipeline/08_export.py`](pipeline/08_export.py) | Enforce verification guards (refuses dry-run or unmarked cubes unless `--allow-unverified` is passed explicitly) and export the static bundle (`--self-test` supported). |

Run module self-tests locally:

```bash
python pipeline/canal_ranking.py --self-test
python pipeline/08_export.py --self-test
```

Model details (features, labels, validation, gates): [`docs/models.md`](docs/models.md).

---

## Regenerating Mock Data vs. Swapping in Real Data

- **Simulated mock bundle (frontend development & rehearsal):**
  ```bash
  npm run mock
  npm run check-bundle
  ```
  Generates deterministic Contract `0.2` files directly into `public/bundle/` with `manifest.data_kind: "mock"`, which shows the **"Simulated data"** / **"Data simulasi"** badge on every screen so simulated numbers are never mistaken for satellite observations.

- **Verified real pipeline bundle:**
  1. Ensure `.env` contains the Earthdata and FIRMS credentials (`EARTHDATA_TOKEN`, `FIRMS_MAP_KEY`) and real NISAR scenes are processed through stages `00`–`07b`, `canal_ranking.py` and `scorecard_tests.py`.
  2. Export without `--allow-unverified`:
     ```bash
     python pipeline/08_export.py
     ```
  3. Copy the exported bundle directory (configured by `bundle_dir` in [`config.yaml`](config.yaml), default `bundle/`) into `public/bundle/` so Vite serves it.
  4. Check the schema and confirm `manifest.data_kind` is `"nisar"` before deployment:
     ```bash
     npm run check-bundle
     npm run build
     ```

---

## Data Contract & Documentation

- **Contract specification:** [`docs/data-contract.md`](docs/data-contract.md). Contract `0.2` is additive over `0.1`: optional canal ids and canal rankings, the land model status, per-cell `cover_set` and `map_check`, and the fire-risk hindcast.
- **Runtime Zod schemas:** [`src/contract/index.ts`](src/contract/index.ts)
- **Scientific method & design notes:** [`docs/method.md`](docs/method.md)
- **Models:** [`docs/models.md`](docs/models.md)
- **Full datasets, licences & citations:** [`docs/sources.md`](docs/sources.md)
- **Build log & provenance notes:** [`docs/LOG.md`](docs/LOG.md)

---

## Manual Verification Checklist

Before final submission, verify these interactions in a clean Incognito/Private browser window:

1. **Keyboard navigation:** Tab through the top nav (`Smoke and radar`, `Season map`, `Scorecard`, `Method`, `Global peat`), the language button (`Bahasa Indonesia` / `English`), timeline pass controls, canal list items, and pulse-card `HH` / `HV` / `HH minus HV` buttons; confirm visible focus rings and `Enter`/`Space` activation.
2. **Reduced motion:** Enable OS/browser `prefers-reduced-motion: reduce`; verify the reveal swipe, map camera transitions, and timeline scrubbing work without jarring animation.
3. **Offline reload:** Visit every screen and scrub through dates once online, then switch browser DevTools Network to **Offline** and reload; verify cached bundle files, map controls, and all 5 screens render via [`public/sw.js`](public/sw.js).
4. **Hollow "fire, radar silent" symbol:** Inspect cells in the "Fire, radar silent" state on the map and in the pulse card and confirm the hollow ring and its uncertainty note appear distinctly, not like a solid confirmed fire or a stable cell.
5. **Mobile viewport (`375x812`):** Confirm tables scroll without horizontal page overflow, nav tabs fit, and all buttons keep a usable touch target size.
6. **Clean bundle check:** Verify `npm run check-bundle` exits `0` with zero missing dates or malformed coordinates.

---

## Space Apps AI-Use Disclosure (Copy-Ready)

> **Use of Artificial Intelligence:** Generative AI coding assistants were used during development of Napas Gambut to accelerate software engineering boilerplate across the TypeScript/React/MapLibre frontend, Zod schema validation tests, bilingual (`EN`/`ID`) translation drafting (flagged for human review), Python data-pipeline refactoring, and documentation formatting. All physical SAR formulas (linear-power block averaging prior to dB conversion, forest-reference double differencing, empirical MAD noise floors), threshold parameters, data provenance guards (`--allow-unverified` gate and honest `Simulated data` labeling), scientific citations, and live/test outputs were specified, reviewed, and verified by the team against primary NASA/ASF documentation and peer-reviewed literature. No synthetic outputs are presented as real satellite measurements. The app uses two small machine-learning models (scikit-learn gradient-boosted trees with MAPIE conformal sets and cleanlab, and a logistic fire-risk hindcast); their training labels and limits are on the app's Method screen. No language model runs in the app.

---

## Team Betelgeuse

M. Rafli P. P. · Immenuel E. K. · Vicky S. P. · Rangga D. P. C. A. · M. Salman

## Licence

Released under the [MIT License](LICENSE). External datasets remain subject to their respective licences listed in [`docs/sources.md`](docs/sources.md) (including ESA WorldCover CC BY 4.0, Global Forest Watch CC BY 4.0, OpenStreetMap ODbL 1.0, and NASA Earthdata Open Data policies).
