# Napas Gambut — Team Trello Cards (Tracks A–E)

> **Before Starting (5-Minute Team Sync):** Lock Contract 0.2's two optional JSON fields together:
> - `scorecard.json` → optional `rankings.canals`
> - `context_features.geojson` → optional `properties.id`
>
> Every Python module runs against existing/mock `data/` outputs, and every frontend task runs against `public/bundle/`—so **all 4 teammates start immediately with zero waiting** until final wiring.

---

## List 1 · Person 1 — Real Land Map & Geospatial Classification (`Track A`)

**Role Summary (IT):** GIS Data Engineer  
**Runs On:** Existing study bounding box & grid coordinates (`data/gcov_cube.zarr`, `config.yaml`) · **Dependencies:** None (start immediately)

### Card 1.1 — Fetch Real Canals, Dams, Peat & Concessions (`03_grid.py` Part 1)
**Labels:** `Track A` · `Python / GeoPandas` · **Owns:** `pipeline/03_grid.py` (vector ingestion)

**Your Job (Plain IT Terms):**
Replace rough placeholder map polygons with real geography. You query public geospatial REST APIs (Overpass and ArcGIS) and vector shapefiles, reproject every coordinate into a single metric coordinate system (`EPSG:32749` so distances are in meters, not degrees), and compute spatial intersections (`overlay` and `sjoin_nearest`) for every 500 m square.

**Checklist:**
- [ ] Fetch OSM canals (`waterway=canal|drain|ditch`) via Overpass API (with Geofabrik `.osm.pbf` + `osmium` fallback) and fail loudly (`RuntimeError`) if unreachable instead of generating fake grids.
- [ ] Load GFW Indonesia peat lands and GFW oil palm / wood-fibre concessions (`geopandas`), reprojecting to UTM 49S (`EPSG:32749`).
- [ ] Query BRGM PRIMS ArcGIS REST service (`f=geojson`, paged by `resultOffset` in steps of 2000) for canal-block dam points (or log fallback and set `nearest_dam_m = None` if unavailable).

<details>
<summary>AI Coding Prompt (Copy & Paste)</summary>

```text
Update `pipeline/03_grid.py` (Part 1: vector ingestion) using `geopandas`, `shapely`, `requests`, and `config.yaml` in CRS `EPSG:32749` (UTM 49S):
1. Canals: Query OpenStreetMap Overpass API for `way["waterway"~"canal|drain|ditch"]` inside `study_box` (with fallback to a local `.osm.pbf` extract via `osmium` if provided). Compute canal density per 500 m cell (total canal length within a 1 km radius divided by circle area). If no real canal source is reachable, raise a RuntimeError and exit—never generate synthetic canals.
2. Peat & Concessions: Load GFW Indonesia peat lands and GFW oil palm / wood-fibre concessions GeoJSON/shapefiles, reproject to `EPSG:32749`, and compute `peat_fraction` and `concession_fraction` per cell using `gpd.overlay(cells, layer, how='intersection')` area divided by cell area.
3. Canal Blocks (PRIMS): Query BRGM PRIMS ArcGIS feature service with `f=geojson` and pagination (`resultOffset` in steps of 2000). If reachable, compute distance from each cell centroid to nearest dam using `gpd.sjoin_nearest`. If unreachable, log a warning and set `nearest_dam_m = None`.
```

</details>

---

### Card 1.2 — ESA WorldCover 10 m Raster & Priority Classifier (`03_grid.py` Part 2)
**Labels:** `Track A` · `Raster / NumPy` · **Owns:** `pipeline/03_grid.py`, `data/grid_provenance.json`

**Your Job (Plain IT Terms):**
Perform high-speed raster-to-vector aggregation. Each 500 m cell holds ~2,500 tiny 10 m pixels from ESA's land-cover map. Instead of slow nested `for` loops, map every pixel to its cell ID and use `numpy.bincount` ($O(N)$ histogram) to compute exact tree and building shares, then apply the deterministic 6-rule `if/elif` classifier and save provenance.

**Checklist:**
- [ ] Stream ESA WorldCover 2021 v200 10 m tiles from anonymous `s3://esa-worldcover/v200/2021/map` using `rioxarray` (no sign-in required) and align to `EPSG:32749`.
- [ ] Compute per-cell class shares using fast `numpy.bincount` (`tree_cover_pct` for class 10, `built_up_share` for class 50).
- [ ] Apply the 6-rule first-match-wins priority classifier, omit unmatched cells (no `"other"` class), and write `data/grid_provenance.json` + CC BY 4.0 attributions for `manifest.sources`.

<details>
<summary>AI Coding Prompt (Copy & Paste)</summary>

```text
Complete `pipeline/03_grid.py` (Part 2: ESA WorldCover raster classification & provenance):
1. Open the ESA WorldCover 2021 v200 Cloud-Optimized GeoTIFF tile(s) covering `study_box` directly from `s3://esa-worldcover/v200/2021/map` (anonymous S3 access) using `rioxarray.open_rasterio`, clip to `study_box`, and reproject/align to `EPSG:32749`.
2. Map each 10 m pixel to its 500 m cell index and use `numpy.bincount` to compute pixel shares for tree cover (class 10) and built-up (class 50). Store `tree_cover_pct = tree_share * 100`.
3. Classify every cell using these exact first-match-wins rules (thresholds read from `config.yaml`):
   - `settlement`: `built_up_share >= settlement_min_share` (0.5)
   - `reference_forest`: inside `reference_forest_box` AND `peat_fraction == 0` AND `tree_share >= ref_forest_min_tree` (0.9)
   - `rewetted`: `peat_fraction >= 0.5` AND `nearest_dam_m <= 250` (skip rule if PRIMS dams unavailable)
   - `plantation`: `peat_fraction >= 0.5` AND `concession_fraction >= 0.5`
   - `intact_forest`: `peat_fraction >= 0.5` AND `tree_share >= intact_min_tree` (0.8) AND `canal_density < drained_canal_threshold`
   - `drained`: `peat_fraction >= 0.5` AND `canal_density >= drained_canal_threshold`
   - Drop any cell matching none of the rules (do NOT create an "other" class).
4. Write `data/grid_provenance.json` documenting exact dataset names, versions, and CC BY 4.0 licences so `08_export.py` can populate `manifest.sources` without `--allow-unverified`. Print class cell counts and spot-check 10 cells.
```

</details>

---

## List 2 · Person 2 — Statistical Self-Checks & Satellite Cross-Checks (`Track C`)

**Role Summary (IT):** Scientific QA & Multi-Sensor Validation Engineer  
**Runs On:** Existing `data/` outputs + ASF / Earth Engine over `study_box` · **Dependencies:** None (start immediately)

### Card 2.1 — Automated Pipeline Self-Checks (`pipeline/scorecard_tests.py` Part 1)
**Labels:** `Track C1` · `Python / SciPy` · **Owns:** `pipeline/scorecard_tests.py`

**Your Job (Plain IT Terms):**
Write automated scientific unit tests for the radar math. Before judges trust the drying map, your code proves its own accuracy: unburned forest stays steady between passes (`reference_steady`), a 50/50 split on reference forest validates (`split_half_null`), fire labels agree (`fire_agreement`), and zooming out from 500 m to 1,000 m keeps the same trend (`size_sensitivity`).

**Checklist:**
- [ ] Expose `compute_all_tests(config, data_dir)` formatted as `{id, name, statistic, value, n, note}` for `scorecard.tests` (omit missing tests; never emit `0`).
- [ ] Implement Checks 3 (`reference_steady`) and 4 (`split_half_null` with seed `42`, target ~0.95).
- [ ] Implement Checks 8 (`fire_agreement` on states `2` or `3`) and 10 (`size_sensitivity` at `1000` m if `cell_stats_1000m.parquet` exists).

<details>
<summary>AI Coding Prompt (Copy & Paste)</summary>

```text
Create `pipeline/scorecard_tests.py` exposing `compute_all_tests(config, data_dir)` that returns a list of dicts matching `scorecard.tests` schema: `{"id": str, "name": str, "statistic": str, "value": float, "n": int, "note": str}`. Omit any test whose input file is missing (never emit 0 for missing data).
Implement the 4 internal self-checks (C1):
1. `reference_steady` (Check 3): From `cell_stats.parquet`, compute median raw `g_hh` (dB) of `reference_forest` cells per date; report the max absolute jump between consecutive passes (`dB`), `n` = number of reference cells.
2. `split_half_null` (Check 4): Using a fixed random seed (`42`), split `reference_forest` cells 50/50 into Group A and Group B. Recompute `D_hh` for Group B using Group A's median as reference, and report the fraction of Group B cell-dates within `[-2*sigma_db, +2*sigma_db]` (target ~0.95).
3. `fire_agreement` (Check 8): From `states.parquet`, among all cell-dates in a fire state (`2` or `3`), report the fraction where radar agreed (`state == 2`).
4. `size_sensitivity` (Check 10): If a 1000 m run output exists (`cell_stats_1000m.parquet`), compute Spearman rank correlation between `canal_density` and season-min `D_hh` and report `1.0` (or correlation value) noting whether the negative sign matches the 500 m run.
```

</details>

---

### Card 2.2 — NISAR SME2 Soil Moisture, Sentinel-1 & MODIS Cross-Checks (`05b_soil_moisture.py` + `scorecard_tests.py` Part 2)
**Labels:** `Track C2–C4` · `Multi-Sensor NASA/ESA` · **Owns:** `pipeline/05b_soil_moisture.py`, `pipeline/scorecard_tests.py`

**Your Job (Plain IT Terms):**
Perform multi-sensor cross-validation—like checking three independent monitoring logs to confirm an alert isn't a false alarm. Pull NISAR's 200 m soil moisture (`SME2`), European Sentinel-1 C-band radar, and NASA MODIS burn scars (`MCD64A1`), then test whether all three point in the same direction as the main L-band radar signal.

**Checklist:**
- [ ] Write `pipeline/05b_soil_moisture.py` to fetch provisional NISAR `SME2` (200 m EASE-Grid 2.0) on matching track/dates, mask veg `> 5 kg/m²` or rain, reproject to `EPSG:32749`, and save `data/sme2_cells.parquet`.
- [ ] Add `soil_moisture_agrees` (C2 Spearman correlation on open `drained` peat) and `cband_same_direction` (C3 Sentinel-1 via ASF HyP3 RTC or Earth Engine `COPERNICUS/S1_GRD`).
- [ ] Add `burned_matches_modis` (C4 monthly `MODIS/061/MCD64A1` burned area vs bundle states 2, 3, or 4), gracefully skipping any unavailable check.

<details>
<summary>AI Coding Prompt (Copy & Paste)</summary>

```text
1. Create `pipeline/05b_soil_moisture.py`: Search `asf_search` for provisional NISAR `SME2` (200 m EASE-Grid 2.0) products matching our track and GCOV dates over `study_box`. Print HDF5 groups on the first file to verify dataset paths (DSG/PMI/TSR estimates + vegetation/rain quality flags). Stream via `fsspec` + `h5netcdf`, mask flagged pixels (dense vegetation > 5 kg/m² or rain), reproject to `EPSG:32749` with `rioxarray`, average per 500 m cell, and save `data/sme2_cells.parquet`.
2. Extend `pipeline/scorecard_tests.py` with three cross-check tests (gracefully skipping any test if its data is unavailable):
   - `soil_moisture_agrees` (C2): Spearman correlation between peak-drought `D_hh` and change in unflagged SME2 soil moisture since pass 1 across open `drained` peat cells. Note clearly that SME2 is provisional and used as a consistency check.
   - `cband_same_direction` (C3): Compare early-season vs peak-drought Sentinel-1 C-band double-difference backscatter (from ASF HyP3 RTC `gamma0` or Earth Engine `COPERNICUS/S1_GRD`) against NISAR `D_hh` on open `drained` cells; report fraction of cells changing in the same sign, noting both median dB shifts.
   - `burned_matches_modis` (C4): Using monthly 500 m `MODIS/061/MCD64A1` burn dates over the study months, report the fraction of bundle burned cells (states 2, 3, or 4) also flagged burned by MODIS, and include the reverse share in `note`.
```

</details>

---

## List 3 · Person 3 — App UX Upgrades, Code Splitting & Offline Mode (`Track B + D2`)

**Role Summary (IT):** Frontend UX, Data Visualization & Web Performance Engineer  
**Runs On:** `src/` and `public/` against existing `public/bundle/` · **Dependencies:** None (zero Python dependency)

### Card 3.1 — 3-Day Rain Column, Fire Curve & Empty Coherence Handling (`Track B1–B3`)
**Labels:** `Track B1–B3` · `React 19 / TypeScript / Vitest` · **Owns:** `PulseCard.tsx`, `Timeline.tsx`, `LayerSwitch.tsx`, `PulseChart.tsx`, `selectors.ts`, `hash.ts`, `i18n/`

**Your Job (Plain IT Terms):**
Implement defensive frontend engineering and clean SVG visualization. Expose the 3-day rain values and a fire-count bar curve on the timeline, and ensure an empty/all-null coherence dataset never shows a broken UI—instead, `hasCoherence(bundle)` disables the radio option with a 1-line explanation and safely redirects `#layer=coh` hashes back to `state`.

**Checklist:**
- [ ] **B1:** Display numeric `context.rain_3day_mm[t]` in `PulseCard.tsx`'s data table and `Timeline.tsx`'s hover/focus tooltip (plain mm number only—no threshold badge).
- [ ] **B2:** Render a plain SVG fire bar curve (`context.fires_region`, `d3.scaleLinear`, `aria-hidden="true"`) beneath `Timeline.tsx`'s pass ruler.
- [ ] **B3:** Export `hasCoherence(bundle)` in `src/data/selectors.ts`; when false, disable Coherence radio in `LayerSwitch.tsx` with a 1-line explanation, show `"Not in this bundle"` on `PulseChart.tsx`'s coherence strip, fall back `layer=coh` to `state` in `src/state/hash.ts`, add `en.ts`/`id.ts` strings (`// REVIEW`), and add Vitest unit tests.

<details>
<summary>AI Coding Prompt (Copy & Paste)</summary>

```text
Implement Track B1, B2, and B3 in our React 19 + TypeScript + Vite 8 + plain SVG (`d3-scale`) frontend without changing the data contract:
1. B1 (`src/components/PulseCard.tsx` & `src/components/Timeline.tsx`): Render `context.rain_3day_mm[t]` (already validated in bundle) as a column in the PulseCard data table and inside the Timeline hover/focus tooltip. Show the numeric mm value only—do not add a "rainy" threshold flag.
2. B2 (`src/components/Timeline.tsx`): Under the pass date ruler, draw a lightweight plain SVG bar series using `context.fires_region` scaled with `d3.scaleLinear` against the bundle's max regional fire count. Add `aria-hidden="true"` since counts are already exposed accessibly.
3. B3 (`src/data/selectors.ts`, `src/components/LayerSwitch.tsx`, `src/components/PulseChart.tsx`, `src/state/hash.ts`):
   - Export `hasCoherence(bundle): boolean` returning `true` iff `series.coh` contains at least one non-null number.
   - When `hasCoherence(bundle)` is `false`: disable the Coherence radio button in `LayerSwitch.tsx` with a concise 1-line reason, display `"Not in this bundle"` in `PulseChart.tsx`'s coherence band, and make `parseHash` in `hash.ts` fall back from `layer=coh` to `state`.
4. Add bilingual strings to `src/i18n/en.ts` and `src/i18n/id.ts` (mark new Indonesian strings with `// REVIEW`), and add Vitest unit tests covering `hasCoherence` on an all-null bundle and `layer=coh` hash fallback.
```

</details>

---

### Card 3.2 — Lazy-Load MapLibre & Offline Field Service Worker (`Track B4 + D2`)
**Labels:** `Track B4 + D2` · `Code Splitting / PWA Offline` · **Owns:** `src/App.tsx`, `src/main.tsx`, `public/sw.js`

**Your Job (Plain IT Terms):**
Optimize initial load speed and zero-signal field reliability. Splitting `SeasonMap` via `React.lazy` keeps heavy MapLibre code out of the opening screen bundle while prefetching it in the background after `Reveal` mounts. Then your ~40-line Service Worker caches app files and `bundle/*` so field crews in remote peatlands with zero connectivity can open the app and inspect every cell.

**Checklist:**
- [ ] **B4:** Wrap `SeasonMap` in `React.lazy` + `Suspense` (`SeasonMapSkeleton`) inside `src/App.tsx`, prefetching in `useEffect` right after `Reveal` paints, and verify zero MapLibre code in the initial entry chunk via `npm run build`.
- [ ] **D2:** Write ~40-line dependency-free `public/sw.js` (precaches core assets on `install`, purges old caches on `activate`, serves same-origin app assets & `bundle/*` cache-first, and ignores external basemap tiles).
- [ ] Register `./sw.js` using a relative URL in `src/main.tsx` so GitHub Pages `base: './'` sub-paths work cleanly.

<details>
<summary>AI Coding Prompt (Copy & Paste)</summary>

```text
Implement Track B4 (code splitting) and Track D2 (offline service worker):
1. B4 (`src/App.tsx`): Convert `SeasonMap` to `const SeasonMap = React.lazy(() => import('./screens/SeasonMap'))` wrapped in `<Suspense fallback={<SeasonMapSkeleton />}>`. Trigger `import('./screens/SeasonMap')` inside a `useEffect` after `Reveal` mounts so the map chunk prefetches in the background while keeping MapLibre completely out of the initial entry chunk. Verify chunk separation with `npm run build`.
2. D2 (`public/sw.js` & `src/main.tsx`):
   - Create a dependency-free ~40-line service worker at `public/sw.js` using a versioned cache name (e.g., `napas-gambut-v1`).
   - On `install`, precache `./`, `./index.html`, and core static assets; on `activate`, purge older cache versions.
   - On `fetch`, use a cache-first strategy for same-origin app assets and `bundle/*` files, but NEVER cache external basemap tiles (e.g., OpenStreetMap / Carto tile URLs—let those fail gracefully offline).
   - Register `./sw.js` using a relative URL in `src/main.tsx` so it works cleanly under GitHub Pages `base: './'` sub-paths.
```

</details>

---

## List 4 · Person 4 — Contract 0.2 Canal Ranking, World Screen & Submission (`Track D1, D3 + E`)

**Role Summary (IT):** Schema Architect, Spatial Ranking & Packaging Lead  
**Runs On:** Isolated files (`src/contract/`, `Scorecard.tsx`, `World.tsx`, `pipeline/canal_ranking.py`, `docs/`) · **Dependencies:** Quick 5-min sync on Contract 0.2 optional fields

### Card 4.1 — Contract 0.2 Canal Ranking ("Block This Canal First") (`Track D1`)
**Labels:** `Track D1` · `Zod Contract 0.2 + Spatial Join` · **Owns:** `src/contract/`, `pipeline/make_fake_bundle.py`, `pipeline/canal_ranking.py`, `src/screens/Scorecard.tsx`

**Your Job (Plain IT Terms):**
Deliver an additive schema upgrade (`0.1 → 0.2`) and spatial prioritization. Field teams block specific named canals—not abstract 500 m squares. Making the new fields `.optional()` in Zod preserves backwards compatibility with v0.1 bundles, while v0.2 bundles populate a ranked "Block this canal first" list that filters and zooms MapLibre straight to the selected canal.

**Checklist:**
- [ ] Add optional Contract 0.2 fields (`manifest.schema_version`: `"0.1" | "0.2"`, optional `context_features.geojson` `properties.id`, optional `scorecard.json` `rankings.canals` up to 20 items) to Zod schemas + `pipeline/make_fake_bundle.py` + loader tests verifying both 0.1 and 0.2.
- [ ] Write `pipeline/canal_ranking.py` exposing `rank_canals(cells_gdf, cell_stats_df, states_df, canals_gdf)` using a 1000 m buffer + `gpd.sjoin`, sorted by lowest `median_min_hh_db`.
- [ ] Add the third ranked list ("Block this canal first") in `src/screens/Scorecard.tsx` so clicking a canal filters the MapLibre canals layer (`setFilter`) and fits bounds to its geometry.

<details>
<summary>AI Coding Prompt (Copy & Paste)</summary>

```text
Implement Track D1 ("Block this canal first" — Contract 0.2, backwards-compatible with 0.1):
1. Contract & Mock (`src/contract/`, `pipeline/make_fake_bundle.py`):
   - Update Zod schemas so `manifest.schema_version` accepts `"0.1" | "0.2"`, `context_features.geojson` features allow optional `properties.id` (e.g. `"osm:123456"`), and `scorecard.json` allows optional `rankings.canals` (array of up to 20 objects: `{ canal: string, name_en: string, name_id: string, length_km: number, n_cells: number, median_min_hh_db: number, n_burned_cells: number }`).
   - Update `make_fake_bundle.py` to emit `schema_version: "0.2"` with mock canal IDs and `rankings.canals`, and add loader tests verifying both 0.1 and 0.2 bundles pass validation.
2. Pipeline Helper (`pipeline/canal_ranking.py`):
   - Expose `rank_canals(cells_gdf, cell_stats_df, states_df, canals_gdf)` for `08_export.py`: buffer each OSM canal way by 1000 m, spatially join (`gpd.sjoin`) peat cells inside the buffer, compute each canal's `length_km`, `n_cells`, `median_min_hh_db` (rounded to 1 decimal), and `n_burned_cells`, and return the top 20 sorted by lowest `median_min_hh_db`.
3. UI (`src/screens/Scorecard.tsx`):
   - When `scorecard.rankings.canals` is present, render a third ranked list ("Block this canal first"). Clicking a canal highlights it on the MapLibre canals layer via `setFilter` and fits map bounds to its geometry.
```

</details>

---

### Card 4.2 — Stretch World Screen & Full Submission Package (`Track D3 + Track E`)
**Labels:** `Track D3 + E` · `Packaging + CC BY 4.0 + Stretch SVG` · **Owns:** `pipeline/requirements.txt`, `docs/sources.md`, `README.md`, `src/screens/World.tsx`

**Your Job (Plain IT Terms):**
Handle reproducible DevOps packaging, dataset attribution compliance, and global-scale storytelling. Pinned dependencies ensure the pipeline runs cleanly on any machine, `docs/sources.md` satisfies CC BY 4.0 and paper citations + Space Apps AI-use disclosure, and the static Natural Earth SVG `World` screen demonstrates how 12-day NISAR monitoring scales to Congo and Amazon peatlands with zero extra network calls.

**Checklist:**
- [ ] Pin all Python dependencies in `pipeline/requirements.txt` (`xarray`, `rioxarray`, `h5netcdf`, `zarr`, `fsspec`, `asf-search`, `geopandas`, `shapely`, `osmnx`, `scipy`, `pandas`, `numpy`, `pyyaml`, `requests`).
- [ ] Write `docs/sources.md` and `README.md` (setup/run, mock vs real swap, data contract path, CC BY 4.0 dataset licences, 5 cited papers, and Space Apps AI-use disclosure).
- [ ] *(Stretch goal)* Build `src/screens/World.tsx` with a bundled static Natural Earth SVG world outline and 3 `"Approximate"` peat markers (Southeast Asia, Cuvette Centrale Congo Basin, Pastaza-Marañón Peruvian Amazon) wired into `SCREENS` (`hash.ts`), `App.tsx`, and nav bar with bilingual `en.ts`/`id.ts` notes.

<details>
<summary>AI Coding Prompt (Copy & Paste)</summary>

```text
1. Create `pipeline/requirements.txt` with pinned versions for all pipeline packages (`xarray`, `rioxarray`, `h5netcdf`, `zarr`, `fsspec`, `asf-search`, `geopandas`, `shapely`, `osmnx`, `scipy`, `pandas`, `numpy`, `pyyaml`, `requests`).
2. Create `docs/sources.md` and update `README.md` to cover: project overview, setup/run instructions, how to regenerate mock data vs swap real data, data contract location, all datasets with licences (ESA WorldCover 2021 v200 CC BY 4.0, GFW Indonesia Peatlands CC BY 4.0, GFW Concessions CC BY 4.0, NASA NISAR GCOV/SME2, NASA FIRMS, NASA Worldview, GPM IMERG/Open-Meteo, Sentinel-1, MODIS MCD64A1), cited papers (Castro et al. 2026, Jaenicke et al. 2011, Uhde et al. 2026, Hoyt et al. 2020, Zhou et al. 2019), and a clear AI-use disclosure note ready to paste into the Space Apps submission form.
3. Build `src/screens/World.tsx` (stretch goal): render a bundled static SVG world map outline (derived from public-domain Natural Earth data, zero runtime fetch) with 3 markers labelled `"Approximate"` for Southeast Asia, Cuvette Centrale (Congo Basin), and Pastaza-Marañón (Peruvian Amazon), each showing a 1-line bilingual note (`en.ts` / `id.ts`) on what a 12-day NISAR watch offers. Wire `world` into `SCREENS` (`src/state/hash.ts`), `App.tsx`, and the navigation bar.
```

</details>

---

## Final Integration & Merge Order

Once all 4 teammates complete their independent cards:

1. **Merge P3 + P4 frontend PRs** (`src/` and `public/sw.js`) → run `npm test && npm run build` and verify the `Reveal` chunk contains zero MapLibre code.
2. **Import P2's `compute_all_tests` and P4's `rank_canals` into `pipeline/08_export.py`**, then run P1's `03_grid.py` through `08_export.py`.
3. **Run `npm run check-bundle`** to verify `08_export.py` passes without `--allow-unverified` and the `"Simulated data"` badge disappears on the live site.
