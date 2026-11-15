# Napas Gambut (*Peat's Breath*)

An interactive 12-day L-band radar peatland monitor built for **NASA Space Apps Challenge (*Dancing with SARs*)**.

**Napas Gambut** tracks tropical peat drying, rewetting, subsidence, and post-fire silence across a 500 m grid in Central Kalimantan, Indonesia (`study_box: [113.75, -2.25, 114.25, -1.75]`), comparing L-band SAR change against a stable mineral-soil dense forest reference and local noise floor before haze hides fires from optical cameras.

The architecture separates offline computation from browser delivery:
- **Python pipeline ([`pipeline/`](pipeline/))** — ingests heavy HDF5/Zarr SAR data, WorldCover tiles, GFW peat/concession polygons, OpenStreetMap canals, NASA FIRMS fire detections, rainfall, and multi-sensor self-checks, exporting a compact static bundle.
- **Static React + MapLibre web app ([`src/`](src/))** — renders the static JSON/GeoJSON/PNG bundle client-side with zero runtime backend calls, full English/Indonesian (`EN` / `ID`) localisation, and an offline Service Worker ([`public/sw.js`](public/sw.js)).

---

## Quick Start (Web App)

Requires **Node.js >= 20** and `npm`.

```bash
# 1. Install frontend dependencies
npm install

# 2. Generate the deterministic Contract 0.2 simulated bundle in public/bundle/
npm run mock

# 3. Validate the active bundle against the Zod schema & image guards
npm run check-bundle

# 4. Run unit, contract, reading-level, and i18n tests
npm test

# 5. Typecheck and build the static bundle for deployment
npm run typecheck
npm run build

# 6. Start the local dev server (or preview the built dist/)
npm run dev
npm run preview
```

---

## Python Pipeline Setup & Stages

Requires **Python 3.11+**. Pinned dependencies live in [`pipeline/requirements.txt`](pipeline/requirements.txt):

```bash
python -m venv .venv
# Activate your virtualenv, then install pinned packages:
pip install -r pipeline/requirements.txt
```

Pipeline settings (bounding boxes, UTM cell sizes, `2σ / 3σ / 4σ` thresholds, `50 mm` rain-return threshold, noise floor limit `0.50 dB`, and output paths) are configured in [`config.yaml`](config.yaml).

### Stage Overview

| Stage / Module | Responsibility |
| --- | --- |
| [`pipeline/00_census.py`](pipeline/00_census.py) | Query ASF catalog for `NISAR_L2_GCOV` scenes on a locked track, frame, direction, and mode (`2005`, `DH`). |
| [`pipeline/01_fetch.py`](pipeline/01_fetch.py) | Stream/subset `HHHH`, `HVHV`, `mask`, and `numberOfLooks` layers into `data/gcov_cube.zarr`. |
| [`pipeline/02_quality.py`](pipeline/02_quality.py) | Scene quality gating, reference stability check, and valid-date filtering (`data/qc_report.json`). |
| [`pipeline/03_grid.py`](pipeline/03_grid.py) | Build 500 m UTM 49S (`EPSG:32749`) grid from OSM waterways, GFW peat & concessions, BRGM PRIMS dams, and ESA WorldCover 10 m (`data/grid_cells.parquet`, `data/grid_provenance.json`). |
| [`pipeline/04_stats.py`](pipeline/04_stats.py) | Linear-power spatial block averaging before dB conversion, forest-reference double differencing (`D_ct`), speckle error, and empirical MAD noise floor (`σ_t`). |
| [`pipeline/05_coherence.py`](pipeline/05_coherence.py) | Experimental L-band InSAR coherence (`NISAR_L2_GUNW`) extension; remains empty when no valid pairs exist. |
| [`pipeline/05b_soil_moisture.py`](pipeline/05b_soil_moisture.py) | Provisional `NISAR_L2_SME2` (200 m EASE-Grid 2.0) soil-moisture ingestion and quality/VWC masking (`data/sme2_cells.parquet`, `data/sme2_report.json`). |
| [`pipeline/06_context_tabular.py`](pipeline/06_context_tabular.py) | NASA FIRMS VIIRS 375 m interval fire joins (including 187.5 m adjacency buffer) and Open-Meteo ERA5 rainfall totals. |
| [`pipeline/06_context_visuals.py`](pipeline/06_context_visuals.py) | NASA GIBS/Worldview true-color optical imagery vs L-band SAR PNGs for the Reveal swipe comparison. |
| [`pipeline/07_states.py`](pipeline/07_states.py) | Priority state classifier (`drying`, `deep_drying`, `burning_or_scar`, `fire_radar_silent`, `rewetted`, `steady`, `no_data`). |
| [`pipeline/canal_ranking.py`](pipeline/canal_ranking.py) | Rank top 20 drainage canals for canal-blocking intervention within a 1 km peat cell buffer (`--self-test` supported). |
| [`pipeline/scorecard_tests.py`](pipeline/scorecard_tests.py) | Scientific self-checks (`reference_steady`, `split_half_null`, `fire_agreement`, `size_sensitivity`) and multi-sensor cross-checks (`soil_moisture_agrees`, `cband_same_direction`, `burned_matches_modis`). |
| [`pipeline/08_export.py`](pipeline/08_export.py) | Enforce verification guards (blocks missing provenance/dry-run outputs unless `--allow-unverified` is passed explicitly) and export the static bundle (`--self-test` supported). |

Run module self-tests locally:

```bash
python pipeline/canal_ranking.py --self-test
python pipeline/08_export.py --self-test
```

---

## Regenerating Mock Data vs. Swapping in Real Data

- **Simulated mock bundle (frontend development & rehearsal):**
  ```bash
  npm run mock
  npm run check-bundle
  ```
  Generates deterministic Contract `0.2` files directly into `public/bundle/` with `manifest.meta.is_mock: true` (rendering the **"Simulated data"** / **"Data simulasi"** banner in the UI so simulated numbers are never mistaken for satellite observations).

- **Verified real pipeline bundle:**
  1. Ensure `.env` contains required Earthdata / FIRMS credentials (`EARTHDATA_TOKEN`, `FIRMS_MAP_KEY`) and real NISAR scenes are processed through stages `00`–`07` + `canal_ranking.py` + `scorecard_tests.py`.
  2. Export without `--allow-unverified`:
     ```bash
     python pipeline/08_export.py
     ```
  3. Copy the exported bundle directory (configured by `bundle_dir` in [`config.yaml`](config.yaml), default `bundle/`) into `public/bundle/` so Vite serves it.
  4. Verify strict schema compliance and ensure `is_mock` is `false` before deployment:
     ```bash
     npm run check-bundle
     npm run build
     ```

---

## Data Contract & Documentation

- **Contract specification:** [`docs/data-contract.md`](docs/data-contract.md) (Contract `0.1` and backwards-compatible `0.2`, adding optional `properties.id` on `context_features.geojson` canals and optional `rankings.canals` on `scorecard.json`)
- **Runtime Zod schemas:** [`src/contract/index.ts`](src/contract/index.ts)
- **Scientific method & design notes:** [`docs/method.md`](docs/method.md)
- **Full datasets, licences & citations:** [`docs/sources.md`](docs/sources.md)
- **Build log & provenance notes:** [`docs/LOG.md`](docs/LOG.md)

---

## Manual Verification Checklist

Before final submission, verify these interactions in a clean Incognito/Private browser window:

1. **Keyboard navigation:** Tab through top nav (`Reveal`, `Season map`, `Scorecard`, `Method`, `Global peat`), language toggle (`EN` / `ID`), timeline pass controls, canal list items, and pulse-card `HH` / `HV` / `HH-HV` buttons; confirm visible focus rings and `Enter`/`Space` activation.
2. **Reduced motion:** Enable OS/browser `prefers-reduced-motion: reduce`; verify reveal curtain swipe, map camera transitions, and timeline scrubbing operate cleanly without jarring animation.
3. **Offline PWA reload:** Visit every screen and scrub through dates once online, then switch browser DevTools Network to **Offline** and reload; verify cached bundle files, map controls, and all 5 screens render via [`public/sw.js`](public/sw.js).
4. **Hollow "fire, radar silent" symbol check:** Inspect burned cells under `fire_radar_silent` in Map & Pulse views and confirm hollow outlines + explicit uncertainty note appear distinctly rather than impersonating solid confirmed fire alerts or `steady` ground.
5. **Mobile viewport (`375x812`):** Confirm responsive tables scroll cleanly without horizontal page overflow, nav tabs fit cleanly, and all interactive buttons maintain minimum touch target size.
6. **Clean bundle check:** Verify `npm run check-bundle` exits `0` with zero missing dates or malformed coordinates.

---

## Space Apps AI-Use Disclosure (Copy-Ready)

> **Use of Artificial Intelligence:** Generative AI coding assistants were used during development of Napas Gambut to accelerate software engineering boilerplate across the TypeScript/React/MapLibre frontend, Zod schema validation tests, bilingual (`EN`/`ID`) translation drafting (flagged for human review), Python data-pipeline refactoring, and documentation formatting. All physical SAR formulas (linear-power block averaging prior to dB conversion, forest-reference double differencing, empirical MAD noise floors), threshold parameters, data provenance guards (`--allow-unverified` gate and honest `Simulated data` labeling), scientific citations, and live/test outputs were specified, reviewed, and verified by the team against primary NASA/ASF documentation and peer-reviewed literature. No synthetic outputs are presented as real satellite measurements.

---

## Licence

Released under the [MIT License](LICENSE). External datasets remain subject to their respective licences listed in [`docs/sources.md`](docs/sources.md) (including ESA WorldCover CC BY 4.0, Global Forest Watch CC BY 4.0, OpenStreetMap ODbL 1.0, and NASA Earthdata Open Data policies).
