# Data Sources, Scientific Literature, and Software

All external datasets, peer-reviewed studies, and open-source libraries used by **Napas Gambut** (*Peat's Breath*), together with their licences and attributions.

---

## 1. NASA Earth Observation Datasets

| Dataset | Product / Endpoint | Use in Napas Gambut | Licence / Policy | Reference |
| --- | --- | --- | --- | --- |
| **NASA-ISRO NISAR L2 GCOV** | `NISAR_L2_GCOV` (20 m UTM L-band Geocoded Covariance, 20 MHz dual-pol `HHHH`/`HVHV`) via ASF Vertex | Primary 12-day radar backscatter time series, double-difference drying index, speckle/noise floor (`pipeline/00_census.py`–`04_stats.py`) | NASA Earthdata Open Data | [ASF NISAR GCOV Guide](https://nisar-docs.asf.alaska.edu/gcov/) · [Known Issues](https://nisar-docs.asf.alaska.edu/nisar-known-issues/) |
| **NASA-ISRO NISAR L2 SME2 (Provisional)** | `NISAR_L2_SME2` (200 m EASE-Grid 2.0 `EPSG:6933` Soil Moisture) via ASF Vertex | Provisional soil-moisture consistency cross-check (`pipeline/05b_soil_moisture.py`, masked where `VWC > 5 kg/m²`, rain, or invalid QA) | NASA Earthdata Open Data | [ASF NISAR SME2 Guide](https://nisar-docs.asf.alaska.edu/sme2/) |
| **NASA-ISRO NISAR L2 GUNW** | `NISAR_L2_GUNW` (80 m unwrapped interferogram) | Planned L-band coherence / subsidence extension (`pipeline/05_coherence.py`; omitted cleanly when no pairs available) | NASA Earthdata Open Data | [ASF NISAR GUNW Guide](https://nisar-docs.asf.alaska.edu/gunw/) · [Level 2 Docs](https://nisar-docs.asf.alaska.edu/level2) |
| **NASA FIRMS Active Fires** | `VIIRS_NOAA20_NRT`, `VIIRS_NOAA20_SP`, `VIIRS_NOAA21_NRT`, `VIIRS_NOAA21_SP` (375 m VIIRS Area API) | Direct & adjacent interval fire detections (`pipeline/06_context_tabular.py`), state transitions (`07_states.py`), and `fire_agreement` check | NASA Earthdata Open Data (Public Domain) | [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) |
| **NASA GIBS / Worldview True Color** | `VIIRS_SNPP_CorrectedReflectance_TrueColor`, `MODIS_Terra_CorrectedReflectance_TrueColor`, `MODIS_Aqua_CorrectedReflectance_TrueColor` WMS (`EPSG:4326`) | Haze-vs-radar Reveal imagery (`pipeline/06_context_visuals.py`) | NASA Earthdata Open Data | [NASA Worldview / GIBS](https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi) |
| **MODIS Burned Area Monthly** | `MODIS/061/MCD64A1` (500 m monthly burned area, Collection 6.1) | External burn-scar cross-check `burned_matches_modis` (`pipeline/scorecard_tests.py`) | NASA EOSDIS / LP DAAC Open Data | [NASA LP DAAC](https://lpdaac.usgs.gov/) |

---

## 2. Ancillary Geospatial, Weather, and Cross-Check Datasets

| Dataset | Coverage / Version | Use in Napas Gambut | Licence & Required Attribution | Reference |
| --- | --- | --- | --- | --- |
| **ESA WorldCover 10 m** | 2021 `v200` Cloud-Optimized GeoTIFFs (`s3://esa-worldcover/v200/2021/map`) | Per-cell tree-cover share (class 10) and built-up share (class 50) aggregated via `numpy.bincount` (`pipeline/03_grid.py`) | **CC BY 4.0** — © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium | [ESA WorldCover Data Access](https://esa-worldcover.org/en/data-access) |
| **Global Forest Watch — Indonesia Peat Lands** | 2003–2006 / 1:250,000 vector polygons | `peat_fraction` per 500 m cell via UTM 49S polygon intersection (`pipeline/03_grid.py`) | **CC BY 4.0** — World Resources Institute / Global Forest Watch (listed via Mandum Rimba & GFW Open Data) | [GFW Dataset](https://data.globalforestwatch.org/datasets/d52e0e67ad21401cbf3a2c002599cf58_10) · [Mandum Rimba Sources](https://www.mandumrimba.org/id/sumber-data) |
| **Global Forest Watch — Indonesia Concessions** | Oil-palm and wood-fibre concession polygons | `concession_fraction` per 500 m cell (`pipeline/03_grid.py`) | **CC BY 4.0** — World Resources Institute / Global Forest Watch | [Global Forest Watch](https://www.globalforestwatch.org/) |
| **OpenStreetMap Waterways** | `waterway=canal\|drain\|ditch\|river` via Overpass API / Geofabrik `.osm.pbf` | Canal density per cell (`03_grid.py`), `context_features.geojson`, and 1 km buffer canal-blocking ranking (`pipeline/canal_ranking.py`) | **ODbL 1.0** — © OpenStreetMap contributors | [OpenStreetMap Copyright](https://www.openstreetmap.org/copyright) |
| **BRGM PRIMS** | Peatland Restoration Information and Monitoring System (ArcGIS FeatureServer `7PROV_PHU_CRITICAL`) | Canal-blocking dam points and `nearest_dam_m` distance (`<= 1 km` rewetted rule in `03_grid.py`; no points were retrieved for the 2026 study box, so no cell is classed rewetted) | BRGM Indonesia public restoration portal terms | [BRGM PRIMS](https://en.prims.brg.go.id/) · [FeatureServer](https://services6.arcgis.com/R04lBEmHupGfIw1K/ArcGIS/rest/services/7PROV_PHU_CRITICAL/FeatureServer/0) |
| **Copernicus Sentinel-1 GRD** | C-band IW (`COPERNICUS/S1_GRD` / ASF HyP3 RTC) | Multi-frequency C-band vs L-band drying direction check `cband_same_direction` (`pipeline/scorecard_tests.py`) | Copernicus Data Policy (Free & Open, attribution required) | [ESA Sentinel-1](https://www.esa.int/cs/articles/about-us/directorates/earth-observation-programmes/copernicus/sentinel-1/facts-and-figures) · [EE S1_GRD](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD) · [ASF HyP3 SDK](https://hyp3-docs.asf.alaska.edu/using/sdk/) |
| **Open-Meteo Historical Weather API** | Daily `precipitation_sum` (ERA5-family reanalysis, study box centre) | 12-day interval precipitation totals and `rain_return_mm` recovery checks (`pipeline/06_context_tabular.py`) | **CC BY 4.0** (Open-Meteo / Copernicus ERA5) | [Open-Meteo Archive API](https://archive-api.open-meteo.com/v1/archive) |
| **Natural Earth 1:110m Physical** | Simplified continental coastlines | Basis for the static inline SVG world outline bundled in [`World.tsx`](../src/screens/World.tsx) (zero runtime fetches) | **Public Domain** | [Natural Earth](https://www.naturalearthdata.com/) |

---

## 3. Scientific Literature & Regional Context

1. **Castro et al. (2026)** — Digitized tropical peatland canal blocks (3,840 blocks), 250 m rewetting radius benchmark, and MODIS `MCD64A1` burned-area evaluation. *iScience*, 2026 ([Article](https://www.cell.com/iscience/fulltext/S2589-0042(26)01416-1)).
2. **Jaenicke et al. (2011)** — L-band SAR backscatter response after canal blocking and peatland restoration in Central Kalimantan (including the +3.7 to ~6 dB post-fire HH backscatter behavior noted in PALSAR studies).
3. **Uhde et al. (2026)** — L-band HH SAR sensitivity to tropical peatland water-table level. *Remote Sensing of Environment*, 2026 ([PDF](https://rainfor.org/wp-content/uploads/sites/129/2026/05/1-s2.0-S0034425726001124-main.pdf)).
4. **Hoyt et al. (2020)** — Widespread tropical peatland subsidence across Southeast Asia measured from L-band SAR interferometry ([NSF PAR](https://par.nsf.gov/servlets/purl/10174385)).
5. **Zhou et al. (2019)** — Tropical peatland subsidence and moisture dynamics with and without restoration. *Remote Sensing*, 11(21), 2592 ([DOI](https://doi.org/10.3390/rs11212592)).
6. **BMKG (7 September 2026)** — Indonesian Meteorology, Climatology, and Geophysical Agency seasonal warning on El Niño impact and forest/peatland fire control (*karhutla*) during the 2026 dry season ([BMKG Release](https://www.bmkg.go.id/berita/utama/dampak-el-nino-masih-perlu-diwaspadai-bmkg-perkuat-dukungan-pengendalian-karhutla)).
7. **ASF NISAR Cookbooks** — GCOV streaming subsetting and power-before-decibels fixed-geometry time-series methodology ([Search & Stream](https://asfopensarlab.github.io/NISAR_Cookbook/notebooks/search-stream-nisar-gcov-asf-search) · [Time Series Example](https://asfopensarlab.github.io/NISAR_Cookbook/notebooks/nisar-gcov-time-series-example)).
8. **NASA Earthdata Outage Notice** — NISAR provisional data production pause notice (23 Oct – 6 Nov 2026) documented in pipeline provenance and timeline design ([Earthdata Alert](https://www.earthdata.nasa.gov/data/alerts-outages/nisar-provisional-data-production-paused-oct.-23-nov.-6-2026)).

---

## 4. Open-Source Software & Runtime Stack

- **Frontend (`package.json`):** [React](https://react.dev/) 19, [TypeScript](https://www.typescriptlang.org/), [Vite](https://vite.dev/), [MapLibre GL JS](https://maplibre.org/), [Zod](https://zod.dev/), [`d3-scale`](https://d3js.org/d3-scale), [`d3-shape`](https://d3js.org/d3-shape), [Vitest](https://vitest.dev/), [`jsdom`](https://github.com/jsdom/jsdom).
- **Pipeline (`pipeline/requirements.txt`):** NumPy, Pandas, SciPy, scikit-learn, Xarray, Zarr, Numcodecs, PyArrow, fsspec, s3fs, h5py, h5netcdf, Rasterio, Rioxarray, GeoPandas, Shapely, pyproj, osmium, `asf_search`, `earthaccess`, Requests, Pillow, Matplotlib, PyYAML, `python-dotenv`, Certifi.
