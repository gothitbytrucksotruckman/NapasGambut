<!-- Copied from PRD.md section 5. Keep in sync with src/contract/index.ts. -->

# Data contract

The bundle is a folder of files. The app loads it from `import.meta.env.VITE_BUNDLE_URL`, defaulting to `${BASE_URL}bundle/`. Write these types in `src/contract/`, write matching zod schemas, and copy this section into `docs/data-contract.md`.

## 5.1 Conventions

- Dates are ISO strings `YYYY-MM-DD`, ascending.
- Coordinates are longitude, latitude in EPSG:4326.
- A missing value is `null`, never `NaN`, `-9999` or an empty string.
- `hh` and `hv` in `series.json` are **tenths of a decibel**, as integers. `-23` means -2.3 dB.
- `coh` is coherence × 100, as an integer from 0 to 100.
- Per-interval arrays (`coh`, `fires`, interval rain) have one fewer entry than `dates`. Entry `k` describes the gap between `dates[k]` and `dates[k+1]`.
- Cell ids look like `r012c034` (row 12, column 34, zero-padded to three digits).
- The `cells` array in `series.json` is the authoritative order. The app builds an id-to-index map and never assumes `cells.geojson` uses the same order.

## 5.2 State codes

State is checked in this order; the first matching rule wins (the generator applies these rules; the app only displays them).

| Code | Key | English label | Indonesian label (team to review) |
| --- | --- | --- | --- |
| 1 | `no_data` | No data | Tidak ada data |
| 2 | `fire_radar` | Fire, radar agrees | Api, radar mendeteksi |
| 3 | `fire_silent` | Fire, radar silent | Api, radar tidak mendeteksi |
| 4 | `burned` | Burned | Terbakar |
| 5 | `rewetting` | Re-wetting | Membasah kembali |
| 6 | `deep_drying` | Deep drying | Mengering parah |
| 7 | `drying` | Drying | Mengering |
| 8 | `stable` | Stable | Stabil |

## 5.3 Cell classes

| Id | English label | Role |
| --- | --- | --- |
| `drained` | Drained peat | Main subject; canal-dense |
| `rewetted` | Rewetted peat | Drained peat with canal dams |
| `plantation` | Plantation on peat | Separate class; harvest cycles confound |
| `intact_forest` | Intact peat swamp forest | The "radar barely sees it" case |
| `reference_forest` | Reference forest (mineral soil) | Calibration reference; should not change |
| `settlement` | Settlement | Built-up control; should not change |

## 5.4 `manifest.json`

```ts
interface Manifest {
  schema_version: "0.1" | "0.2";
  data_kind: "mock" | "nisar";
  generated_at: string;                 // ISO date-time
  generator: { name: string; version: string; seed: number | null };
  study_area: {
    name_en: string;
    name_id: string;
    bbox: [number, number, number, number];   // west, south, east, north
    cell_size_m: number;
  };
  geometry: { track: number | null; frame: number | null; direction: "A" | "D" | null };
  dates: string[];
  dropped_dates: { date: string; reason_en: string; reason_id: string }[];
  scenes: { date: string; name: string; version: string }[];
  thresholds: {
    sigma_db: (number | null)[];        // per date; null for dropped dates and dates[0]
    change_k: number;                   // 2
    headline_k: number;                 // 3
    deep_k: number;                     // 4
    rain_return_mm: number;             // interval rain that counts as "rain returned"
  };
  classes: { id: string; label_en: string; label_id: string }[];
  states: { code: number; key: string; label_en: string; label_id: string }[];
  images: {
    bounds: [[number, number], [number, number], [number, number], [number, number]]; // see 5.10
    radar: { date: string; file: string }[];
    reveal: { date: string; optical_file: string; radar_file: string };
  };
  sources: { name: string; url: string; role_en: string; role_id: string }[];
}
```

Dropped dates **stay in `dates`**. Their values are `null` and their state is `1`. This keeps every array aligned.

## 5.5 `cells.geojson`

A GeoJSON `FeatureCollection` of `Polygon` features, one per cell. Water cells are not included.

```ts
interface CellProperties {
  id: string;                    // "r012c034"
  row: number;
  col: number;
  class: "drained" | "rewetted" | "plantation" | "intact_forest" | "reference_forest" | "settlement";
  canal_density_km_per_km2: number;
  tree_cover_pct: number;        // 0 to 100
  n_pixels: number;              // valid 20 m pixels in the cell; 625 when full
  centroid: [number, number];
}
```

## 5.6 `context_features.geojson`

A `FeatureCollection` of map context drawn above or below the cells.

```ts
interface ContextFeatureProperties {
  id?: string;                           // Contract 0.2 optional feature id (e.g. "osm:123456")
  kind: "canal" | "river" | "dam" | "town";
  name_en: string | null;
  name_id: string | null;
}
```

Canals and the river are `LineString`; dams and the town are `Point`.

## 5.7 `series.json`

```ts
interface Series {
  dates: string[];               // identical to manifest.dates
  cells: string[];               // cell ids; authoritative order
  hh: (number | null)[][];       // [cell][date], tenths of dB, drying index
  hv: (number | null)[][];       // [cell][date], tenths of dB, cross-pol index
  coh: (number | null)[][];      // [cell][interval], 0 to 100
  fires: (number | null)[][];    // [cell][interval], detections in the interval
  state: number[][];             // [cell][date], codes from 5.2
}
```

`hh[c][0]` and `hv[c][0]` are always `0`: the index is change since the first date, relative to the reference forest.

## 5.8 `context.json`

```ts
interface Context {
  dates: string[];
  rain_3day_mm: (number | null)[];          // per date: rain in the 3 days before the pass
  rain_interval_mm: (number | null)[];      // per interval
  fires_region: number[];                   // per interval: detections in the whole study area
  quality: ("ok" | "dropped")[];            // per date
}
```

## 5.9 `scorecard.json`

```ts
interface Scorecard {
  by_class: {
    class: string;
    n_cells: number;
    median_min_hh_db: number;               // median over cells of each cell's lowest HH index, in dB
    p25_min_hh_db: number;
    p75_min_hh_db: number;
    share_burned: number;                   // 0 to 1
    median_passes_to_recovery: number | null;
  }[];
  rankings: {
    fastest_drying: {                       // top 20 drained or plantation cells, lowest minimum first
      cell: string; class: string; min_hh_db: number; date_of_min: string;
    }[];
    dams_to_inspect: {                      // rewetted cells whose minimum fell below the drained median
      cell: string; min_hh_db: number; gap_vs_drained_median_db: number;
    }[];
    canals?: {                              // Contract 0.2 optional: top 20 canals sorted by lowest median_min_hh_db
      canal: string;
      name_en: string;
      name_id: string;
      length_km: number;
      n_cells: number;
      median_min_hh_db: number;
      n_burned_cells: number;
    }[];
  };
  tests: {
    id: string;
    name_en: string;
    name_id: string;
    statistic: string;                      // e.g. "Spearman rank correlation"
    value: number;
    n: number;
    note_en: string;
    note_id: string;
  }[];
}
```

## 5.10 `images/`

- `radar_YYYY-MM-DD.png`: one greyscale picture per date, the same pixel size for every date.
- `reveal_optical.png` and `reveal_radar.png`: the opening pair, same date and same extent.
- All images cover `manifest.images.bounds`. Corner order is top-left, top-right, bottom-right, bottom-left, each as `[lon, lat]`. Verify that this matches MapLibre's image-source coordinate order before relying on it.

## 5.11 Size budget

Everything except images: under 6 MB. Images: under 10 MB in total.

## Schema 0.2 (additive)

`schema_version` may be `"0.1"` or `"0.2"`. Every field below is optional, so a 0.1 bundle is still a valid 0.2 bundle. The mock generator writes `"0.2"`.

### Land cover ids

```ts
type CoverId = "forest" | "degraded" | "plantation" | "built";
```

These are the classes the radar land model predicts. They are coarser than the cell classes in 5.3.

### `manifest.json`

```ts
interface Manifest {
  // ...all 0.1 fields...
  land_model?: {
    status: "used" | "not_used" | "simulated";
    version: string;
    confidence_level: number;            // e.g. 0.9; the level the class sets are built at
    reason_en: string | null;
    reason_id: string | null;
  };
}
```

- `used`: `cells.class` came from the radar land model.
- `not_used`: `cells.class` did not come from the land model; `reason_en` and `reason_id` say why.
- `simulated`: a mock bundle. No model was trained; the class sets are made up by the script.

### `cells.geojson`

```ts
interface CellProperties {
  // ...all 0.1 fields...
  cover_set?: CoverId[];   // the radar's conformal class set at land_model.confidence_level
  map_check?: CoverId;     // only on flagged cells
}
```

- `cover_set` lists every class the radar cannot rule out at the stated confidence level. The first entry is the radar's class. An empty array means the radar can't tell.
- `map_check` is present only where the radar confidently disagrees with the older land cover map. It holds what the older map says. The radar's class is `cover_set[0]`.

### `scorecard.json`

```ts
interface Scorecard {
  // ...all 0.1 fields...
  fire_risk?: {
    status: "passed" | "not_passed" | "not_run";
    test_dates: string[];                     // pass dates held out for the test
    model_pr_auc: number | null;
    model_pr_auc_ci: [number, number] | null;
    best_baseline: { id: "B1" | "B2" | "B3"; pr_auc: number } | null;
    lift: {
      quintile: number;                       // 1 to 5; 1 = lowest HV index
      n: number;                              // test rows in the quintile
      fires: number;                          // rows with a fire in the next interval
      rate: number;                           // fires / n, 0 to 1
    }[];
  };
}
```

`fire_risk` is a hindcast of one season at one site. It says whether a low HV index came before fire in that season. It is not a forecast.

`tests` keeps its 0.1 shape. Three new ids may appear:

- `fire_risk_capture`, only when `fire_risk.status` is `passed`.
- `land_model_coverage` and `map_out_of_date`, only when `land_model.status` is `used`.

### Rules the loader checks

- A `fire_risk_capture` test is present exactly when `fire_risk.status` is `passed`.
- If any cell has `cover_set` or `map_check`, `land_model.status` must be `used` or `simulated`.
- A cell with `map_check` has a `cover_set` of exactly one class.

### What the mock writes

`land_model.status` is `simulated`. Every cell gets a `cover_set`: about 3% empty, about 8% with two classes, the rest with one. About 2% of the one-class cells get a `map_check`. `fire_risk.status` is `not_run`, with no model scores; `test_dates` and `lift` are computed from the simulated series with the same row rule as `pipeline/07b_fire_risk.py`. The mock writes none of the three new tests.
