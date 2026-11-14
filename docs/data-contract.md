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
  schema_version: "0.1";
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
