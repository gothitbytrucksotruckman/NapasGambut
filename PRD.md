# Build brief: Peat's Breath (Napas Gambut) frontend prototype

You are building the frontend prototype of **Peat's Breath (Napas Gambut)**, an entry for the NASA Space Apps Challenge 2026, challenge "Dancing with the SARs". Read this whole brief before writing any code. When the brief and your own preferences disagree, follow the brief. When something here is ambiguous, ask before guessing.

---

## 1. What you are building

A static web app that tells the story of one Indonesian peat landscape through the 2026 El Niño drought, as seen by the NISAR L-band radar satellite. The landscape is divided into 500 m cells. For each cell and each 12-day radar pass, the app shows whether the peat was stable, drying, burning, burned or re-wetting.

**Who it is for**

- Primary: peat restoration staff and village fire brigades deciding where to block canals before the next dry season.
- Secondary: judges, journalists, teachers and the public.

**What it is not**

- No backend and no server. The app only reads static files.
- No science in the browser. Every number on screen is precomputed in the data bundle.

**This prototype uses simulated data.** You will write a seeded generator script that produces a realistic but fake data bundle. Its file formats are exactly the ones the real NISAR pipeline will produce later. Replacing the mock files with real ones must require **zero code changes**.

---

## 2. Non-negotiable rules

1. **The data contract in section 5 is fixed.** Do not rename, add or remove fields without asking. If you think a change is needed, propose it and wait.
2. **The app never recomputes science.** It reads, looks up, filters and draws. Thresholds, states, rankings and statistics all come from the bundle.
3. **Simulated data is always labelled.** When `manifest.data_kind` is `"mock"`, every screen shows a persistent, visible "Simulated data" badge. The Method screen explains that the numbers are generated, not measured. This must never be removable by a UI toggle.
4. **Do not invent library APIs.** Before using any function, prop or option from a third-party library, check the installed package's type definitions in `node_modules` or its official docs. If you cannot confirm something exists, say so and pick a verified alternative.
5. **No runtime network calls** except basemap tiles. Everything else loads from the bundle path.
6. **Determinism.** The generator with the same seed must produce byte-identical files.
7. **Commit after each milestone** in section 13, with a clear message. Run the build and the tests before each commit.

---

## 3. Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Build and dev server | Vite | Fast; outputs a plain static site |
| Language | TypeScript, strict mode | The data contract becomes compile-time types |
| UI | React | Team familiarity; component model fits the screens |
| Map | MapLibre GL JS | Open source, no access token, handles 6,000+ polygons and image overlays |
| Charts | Plain SVG with `d3-scale` and `d3-shape` | Full control over the pulse card's layered chart; small bundle |
| Runtime validation | `zod` | Validates the bundle against the contract at load time |
| Tests | Vitest | Same toolchain as Vite |
| Mock generator | TypeScript run with `tsx`, plus `pngjs` for images | One toolchain for the whole frontend team |
| Hosting | GitHub Pages via GitHub Actions | Free, static, public link that needs no sign-in |

Use current stable versions. Pin exact versions in `package.json`. Verify every library's current API from its installed types before use.

**Basemap:** use a raster basemap that needs no API key, show its required attribution, and check its usage terms. Add a "No basemap" option. If no suitable keyless source works, ship with no basemap and a plain background. The cells carry the story without it.

---

## 4. Repository layout

```text
napas-gambut/
  README.md
  LICENSE                     MIT
  package.json
  vite.config.ts
  tsconfig.json
  .github/workflows/deploy.yml
  docs/
    data-contract.md          section 5 of this brief, kept in sync with src/contract
    method.md                 the plain-language method text shown in the app
  scripts/
    mock/
      generate.ts             entry point: npm run mock
      rng.ts                  seeded random number generator
      landscape.ts            cells, classes, canals, dams, river, town
      season.ts               drought curve, rain, dates
      signals.ts              HH, HV, coherence, fires
      states.ts               the state rules (section 6.6)
      scorecard.ts            class statistics, rankings, tests
      images.ts               radar and smoke PNGs
  public/
    bundle/                   generated output; committed so the deployed site works
  src/
    contract/                 TypeScript types + zod schemas for every bundle file
    data/                     loader, id-to-index maps, selectors
    state/                    app state and URL sync
    i18n/                     en.ts, id.ts
    screens/                  Reveal, SeasonMap, PulseCard, Scorecard, Method, (stretch) World
    components/               Timeline, Legend, Badge, LayerSwitch, Divider, etc.
    styles/                   tokens and global styles
  tests/
```

Scripts in `package.json`: `dev`, `build`, `preview`, `test`, `mock`, `typecheck`.

---

## 5. Data contract

The bundle is a folder of files. The app loads it from `import.meta.env.VITE_BUNDLE_URL`, defaulting to `${BASE_URL}bundle/`. Write these types in `src/contract/`, write matching zod schemas, and copy this section into `docs/data-contract.md`.

### 5.1 Conventions

- Dates are ISO strings `YYYY-MM-DD`, ascending.
- Coordinates are longitude, latitude in EPSG:4326.
- A missing value is `null`, never `NaN`, `-9999` or an empty string.
- `hh` and `hv` in `series.json` are **tenths of a decibel**, as integers. `-23` means -2.3 dB.
- `coh` is coherence × 100, as an integer from 0 to 100.
- Per-interval arrays (`coh`, `fires`, interval rain) have one fewer entry than `dates`. Entry `k` describes the gap between `dates[k]` and `dates[k+1]`.
- Cell ids look like `r012c034` (row 12, column 34, zero-padded to three digits).
- The `cells` array in `series.json` is the authoritative order. The app builds an id-to-index map and never assumes `cells.geojson` uses the same order.

### 5.2 State codes

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

### 5.3 Cell classes

| Id | English label | Role |
| --- | --- | --- |
| `drained` | Drained peat | Main subject; canal-dense |
| `rewetted` | Rewetted peat | Drained peat with canal dams |
| `plantation` | Plantation on peat | Separate class; harvest cycles confound |
| `intact_forest` | Intact peat swamp forest | The "radar barely sees it" case |
| `reference_forest` | Reference forest (mineral soil) | Calibration reference; should not change |
| `settlement` | Settlement | Built-up control; should not change |

### 5.4 `manifest.json`

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

### 5.5 `cells.geojson`

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

### 5.6 `context_features.geojson`

A `FeatureCollection` of map context drawn above or below the cells.

```ts
interface ContextFeatureProperties {
  kind: "canal" | "river" | "dam" | "town";
  name_en: string | null;
  name_id: string | null;
}
```

Canals and the river are `LineString`; dams and the town are `Point`.

### 5.7 `series.json`

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

### 5.8 `context.json`

```ts
interface Context {
  dates: string[];
  rain_3day_mm: (number | null)[];          // per date: rain in the 3 days before the pass
  rain_interval_mm: (number | null)[];      // per interval
  fires_region: number[];                   // per interval: detections in the whole study area
  quality: ("ok" | "dropped")[];            // per date
}
```

### 5.9 `scorecard.json`

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

### 5.10 `images/`

- `radar_YYYY-MM-DD.png`: one greyscale picture per date, the same pixel size for every date.
- `reveal_optical.png` and `reveal_radar.png`: the opening pair, same date and same extent.
- All images cover `manifest.images.bounds`. Corner order is top-left, top-right, bottom-right, bottom-left, each as `[lon, lat]`. Verify that this matches MapLibre's image-source coordinate order before relying on it.

### 5.11 Size budget

Everything except images: under 6 MB. Images: under 10 MB in total.

---

## 6. Mock data generator

`npm run mock` writes the full bundle to `public/bundle/`. The default seed is `20261114`; `--seed N` overrides it. Use a small seeded generator such as mulberry32 for all randomness; never call `Math.random()`.

The goal is data that **behaves like the real thing**, including its noise and its honest null results, so the frontend is designed for reality, not a perfect demo.

### 6.1 Study area and grid

- Grid: 80 × 80 cells of 500 m, about 40 km × 40 km.
- Placeholder box near Pulang Pisau, Central Kalimantan: west 113.90, south -2.95, east 114.26, north -2.59. Use 0.0045° per cell in both directions. These coordinates are **approximate placeholders**; the real pipeline will supply the real ones.
- `study_area.name_en`: "Central Kalimantan peat landscape (simulated)". Do not name real villages or companies anywhere in mock data. Call the town "Town (simulated)".

### 6.2 Landscape

Build it procedurally from the seed:

| Feature | How to make it | Approximate share of cells |
| --- | --- | --- |
| River | A meandering line running roughly north to south in the western third; cells within 300 m of it are water and excluded | 3% excluded |
| Canal grid | Straight canals about every 2.5 km in both directions across the western two-thirds, plus two diagonal canals | n/a |
| Drained peat | Canal-dense land in the western two-thirds | 40% |
| Rewetted peat | One contiguous block inside the drained area, with 15 to 25 dam points placed on its canals | 8% |
| Plantation | One rectangular block in the south-west | 12% |
| Intact peat swamp forest | A dome in the eastern third, with almost no canals | 30% |
| Reference forest | A strip along the north-west edge, outside the peat | 5% |
| Settlement | A small cluster beside the river | 0.5% |

- `canal_density_km_per_km2`: canal length inside a 1 km radius of the centroid, divided by the circle's area.
- `tree_cover_pct`: high for forests (80 to 95), mid for plantation (50 to 70), low for drained (5 to 30), lowest for settlement.
- `n_pixels`: 625 for most cells; 300 to 600 for cells clipped by the river or the box edge.

### 6.3 Season

Dates every 12 days from 2026-06-20: 06-20, 07-02, 07-14, 07-26, 08-07, 08-19, 08-31, 09-12, 09-24, 10-06, 10-18, 10-30, 11-11 (13 dates).

- **Dropped date:** 2026-10-30, reason "Simulated quality failure: partial coverage". All its radar values (`hh`, `hv`, and the coherence of the intervals touching it) are `null` and its state is `1`. Rain and fire counts still exist, because they come from other satellites. This exercises the gap handling.
- **Drought curve** `s(t)` from 0 to 1: about 0.15 on 06-20, rising smoothly to about 1.0 around 10-06, staying near 1.0 through 10-18, then falling to about 0.45 by 11-11 after rain returns.
- **Rain:** 3-day totals mostly 0 to 15 mm from June to mid-October; first heavy rain in the 10-18 to 10-30 interval; 40 to 90 mm 3-day totals afterwards. `rain_return_mm` = 50.

### 6.4 Signals

Add spatially smooth noise (blur a random field over neighbouring cells) plus independent per-cell noise, so neighbouring cells look related but not identical.

**HH drying index**, in dB before converting to tenths:

`D = -A(class) × s(t) × (0.6 + 0.8 × canalFactor) + noise`

| Class | A (dB) |
| --- | --- |
| drained | 2.6 |
| plantation | 1.6 |
| rewetted | 1.1 |
| intact_forest | 0.25 |
| reference_forest | 0 |
| settlement | 0 |

- `canalFactor` = the cell's canal density scaled to 0 to 1 across all cells.
- Per-cell noise standard deviation 0.25 dB; settlement 0.15 dB.
- About 5% of rewetted cells behave like drained cells (A = 2.6). They are the "dams to inspect".
- `D` at the first date is exactly 0.

**HV index:** `-0.3 × A × s(t) + noise`, plus a persistent drop of 3 to 5 dB from the fire interval onward in burned cells where the radar agrees.

**Coherence per interval**, 0 to 100, with noise of about ±5:

| Class | Base |
| --- | --- |
| settlement | 75 |
| drained | 55 |
| rewetted | 50 |
| plantation | 40 |
| intact_forest | 30 |
| reference_forest | 25 |

Add `+10 × s` in the dry season. Drop to 8 to 15 in an interval with fire. After a burn, stay near 40. Drop by about 15 in the first interval with heavy rain.

**Fires:**

- Fires happen only in the intervals from 08-07 to 10-18.
- Hazard per cell and interval ∝ `s³ × (0.3 + canalFactor) × classFactor`. Class factors: drained 1.0, plantation 0.6, rewetted 0.5, intact_forest 0.2, reference_forest 0, settlement 0.
- Pick about 8 ignition cells weighted by hazard, then spread to neighbours with probability 0.35 per interval for 1 to 2 intervals.
- Target: 6 to 10% of cells burn. Each burning cell gets 1 to 6 detections in its fire interval.
- Radar agrees with probability 0.65 in drained and plantation cells and 0.8 in forest cells. Otherwise the radar is silent: no HV drop, and coherence drops only to 30 to 40.

### 6.5 Noise floor and thresholds

Compute `sigma_db` per date exactly as the real method does:

`sigma_t = 1.4826 × median absolute deviation of D across reference_forest cells at date t`

Store `null` for `dates[0]` and for the dropped date. `change_k = 2`, `headline_k = 3`, `deep_k = 4`.

### 6.6 State rules

Implement in `scripts/mock/states.ts` as a pure function with unit tests. For each cell and date, first match wins:

1. `no_data`: the date is dropped, or the cell's `n_pixels` is under 313 (half of 625).
2. `fire_radar`: fire detected in the interval ending at this date, and (HV fell by more than `change_k × sigma` since the previous date, or coherence for that interval is under 20).
3. `fire_silent`: fire detected in the interval ending at this date, with neither radar sign.
4. `burned`: the cell was in state 2 or 3 at any earlier date.
5. `rewetting`: rain has returned (any interval so far with `rain_interval_mm ≥ rain_return_mm`), and `D` has risen by more than `change_k × sigma` above the cell's lowest earlier `D`.
6. `deep_drying`: `D < -deep_k × sigma`.
7. `drying`: `D < -change_k × sigma`.
8. `stable`: everything else.

At `dates[0]` every valid cell is `stable`.

### 6.7 Scorecard

Compute from the generated series, exactly as section 5.9 describes. Include these tests, computed honestly on the mock data:

| Id | Name | Statistic |
| --- | --- | --- |
| `canal_vs_drying` | More canals, more drying | Spearman rank correlation between canal density and minimum HH index, over drained, rewetted and plantation cells |
| `rewetted_vs_drained` | Rewetted cells dry less | Difference in median minimum HH index (rewetted minus drained), with both counts |
| `drying_before_fire` | Drying comes before fire | Median HH index on the pass before the fire, burned cells minus unburned cells on the same dates |
| `forest_flat` | Intact forest shows little signal | Median absolute HH index of intact forest at peak drought |

Every `note_en` must say the result is descriptive and computed on simulated data.

### 6.8 Images

- Radar pictures: 8 × 8 pixels per cell (640 × 640). Base brightness by class (forest brighter, open drained darker, water black), shifted by the cell's HH index, plus per-pixel speckle so it looks like a real radar image. Dropped date: write a mostly-blank image with a diagonal hatch.
- Reveal pair at 09-24: the radar picture for that date, and an "optical" picture of the same extent covered in a brown-grey haze, with denser plumes drifting from the fire cells of that interval. A few darker patches of ground may show through. It should be obvious at a glance that the optical view is blocked.
- Draw a small "SIMULATED" watermark in a corner of every generated image.

### 6.9 Generator checks

The script fails loudly if:

- any output does not validate against the zod schemas,
- array lengths disagree with `dates` or with the cell count,
- the burned share is outside 4 to 12%,
- non-image files exceed 6 MB.

---

## 7. App architecture

### 7.1 Data layer (`src/data/`)

- `loadBundle(baseUrl)` fetches all files in parallel, validates each with zod, and returns one typed `Bundle` object.
- On validation failure, show a full-screen error naming the file and the field that failed, so the real-data team can fix their output quickly.
- Build lookups once: cell id to index, cell id to feature, date to index.
- Selectors are pure functions: `cellSeries(id)`, `statesAtDate(i)`, `countsByState(i)`, etc. Screens never index raw arrays directly.

### 7.2 App state (`src/state/`)

| State | Type | Changes by |
| --- | --- | --- |
| `screen` | `"reveal" | "map" | "scorecard" | "method" | "world"` | Navigation |
| `dateIndex` | number | Scrubber, play, arrow keys |
| `selectedCell` | string or null | Map click, ranking click |
| `layer` | `"state" | "hh" | "hv" | "coh" | "radar"` | Layer switch |
| `playing` | boolean | Play button, Space key |
| `lang` | `"en" | "id"` | Language switch |

Keep `screen`, `dateIndex` (as the date string), `selectedCell`, `layer` and `lang` in the URL hash so any view can be shared as a link. GitHub Pages serves static files, so use hash-based state, not path routing.

### 7.3 Swapping in real data

Document in the README:

1. Run the real pipeline; it writes the same files.
2. Replace `public/bundle/` with its output, or set `VITE_BUNDLE_URL` to another folder.
3. Rebuild. When `data_kind` is `"nisar"`, the "Simulated data" badge disappears and the Method screen lists the real scenes.

---

## 8. Screens

### 8.1 Reveal (landing)

- Full-width image comparison: the optical haze picture on the left, the radar picture on the right, with a draggable vertical divider. Build the divider yourself with CSS clipping; no library.
- Headline: "On 24 September 2026, smoke hid the ground. Radar still saw it." Use the reveal date from the manifest, not a hard-coded string.
- One sentence under it explaining that radar makes its own signal and passes through smoke and cloud.
- Button: "Watch the season" goes to the map.
- The divider must work with mouse, touch and keyboard (left and right arrows move it).

### 8.2 Season map

- MapLibre map fitted to `study_area.bbox`.
- Cells as a fill layer, coloured by the current layer at the current date. Recolour on date change without rebuilding the source. Feature-state or an equivalent verified MapLibre mechanism is fine; confirm the API from the installed types.
- Context features: canals as thin lines, the river, dams as small markers, the town as a labelled point.
- "Radar picture" layer: the date's radar PNG as an image overlay. Preload the next date's image.
- **Timeline** along the bottom: one tick per date, the dropped date visibly marked, play and pause, step back and forward. Playback at about one pass per 1.2 seconds.
- **Legend** for the current layer. State colours always come with a name and, on the pulse card, a symbol.
- **Live counts** beside the legend: how many cells are in each state at this date.
- Clicking a cell opens its pulse card in a side panel (bottom sheet on phones) without leaving the map.

### 8.3 Pulse card

One chart with one shared time axis:

- HH index as a line, with a shaded band at ±`change_k × sigma` so readers see what counts as noise.
- HV index as a second line.
- Coherence as steps between dates, on its own small axis.
- Interval rain as bars along the bottom.
- Fire detections as markers along the top, in the interval they happened.
- Dropped date shown as a gap, not a line through it.
- A vertical marker at the current date, kept in sync with the timeline.

Below the chart:

- The cell's class, canal density, tree cover and pixel count.
- A one-sentence reading built from fixed templates over the cell's state sequence. Examples: "Dried steadily from July, burned in mid-September, no recovery yet." / "Stayed within the noise all season." No language model; templates only, in both languages.
- A toggle switching the main line between HH, HV and HH minus HV, each with a two-line explanation and a small sketch of the scattering mechanism (ground and water for HH, leaves and branches for HV).
- "Copy link to this cell" button.

### 8.4 Scorecard

- A compact table per class from `scorecard.by_class`: count, median lowest drying with its spread, share burned, passes to recovery. Show counts next to every median.
- Two ranked lists side by side:
  - "Where to block canals first": `rankings.fastest_drying`.
  - "Dams to inspect": `rankings.dams_to_inspect`.
- Clicking a row flies the map to that cell and opens its pulse card.
- The four tests from `scorecard.tests`, each as one plain sentence with its number and count, plus the note.

### 8.5 Method and limits

- How the radar works, in three short paragraphs with the analogies: the radar as a bat listening to its own echo; wet ground shining like a wet road under headlights; HH listening to the floor and HV to the furniture.
- How a state is decided: the eight rules, in plain words.
- What radar cannot tell you: a wetness index, not a water depth in metres; little signal under dense forest; low-intensity fires the radar may not see.
- From the manifest: scenes used, thresholds, dropped dates with reasons, data kind, generator and seed.
- Sources from `manifest.sources`, as links.
- Future NISAR applications: a full-year record, a 12-day dry-season watch, other tropical peat regions, S-band alongside L-band.

### 8.6 Stretch: World

A simple world map with approximate markers for major tropical peatland regions (Southeast Asia, the Congo Basin's Cuvette Centrale, the Peruvian Amazon's Pastaza-Marañón basin). One line each on what a 12-day NISAR watch would offer. Label the markers as approximate. Only build this after everything in milestone 5 is done.

---

## 9. Visual direction

- The feeling is a **field instrument**: calm, precise, readable outdoors on a phone. Not a sci-fi dashboard, not a generic SaaS page. Avoid purple-blue gradients, glowing neon and glassmorphism.
- Neutral background with a slight green-grey tint; one accent colour (deep teal, the radar colour) used sparingly for interactive elements.
- State colours, designed together and checked for colour-blind safety:
  - stable: muted grey-green
  - drying: amber
  - deep drying: burnt orange
  - fire, radar agrees: strong red, with a filled symbol
  - fire, radar silent: red outline, hollow symbol
  - burned: charcoal brown
  - re-wetting: blue-teal
  - no data: light grey with a diagonal hatch
- Define all colours, spacing and type sizes as CSS custom properties in `src/styles/tokens.css`. Support light and dark themes from the same tokens.
- Typography: one clean sans-serif for UI and a condensed or tabular variant for numbers. Numbers in tables use tabular figures.
- Map first. On desktop the map takes most of the screen; on phones the timeline stays reachable with one thumb.

---

## 10. Copy and language

- Title: **Peat's Breath**, subtitle **Napas Gambut**.
- Every visible string lives in `src/i18n/en.ts` and `src/i18n/id.ts`, with the same keys. No string literals in components.
- English is the default. A native Indonesian speaker on the team will review the Indonesian file; mark any Indonesian you are unsure of with a `// REVIEW` comment.
- Write for a village fire brigade first and a scientist second. Say "radar wetness index" on screen; keep the formula on the Method screen.
- Never call mock values "measured", "observed" or "detected by NISAR". Use "simulated" while `data_kind` is `"mock"`.

---

## 11. Accessibility and performance

- Every interactive element is reachable and usable by keyboard, with a visible focus ring.
- Keyboard: left and right arrows step dates when the timeline has focus; Space toggles play.
- Colour is never the only signal: states have names in the legend and symbols on the pulse card.
- Respect `prefers-reduced-motion`: no animated transitions, and map fly-to becomes an instant jump.
- The map has a text alternative: the live state counts and the selected cell's reading.
- Contrast meets WCAG AA for text in both themes.
- Total download before images under 6 MB. The first screen is readable within a few seconds on mobile data.
- No layout shift when the bundle finishes loading: show a skeleton with the final layout.

---

## 12. Tests

With Vitest:

1. **Determinism:** running the generator twice with the same seed produces identical file hashes.
2. **Contract:** every generated file validates against its zod schema; array lengths line up.
3. **State rules:** hand-written cell sequences that hit each of the eight rules, including the ordering (for example, a cell that is both drying and has a fire must be a fire state).
4. **Loader:** a deliberately broken bundle produces a readable error naming the file and field.
5. **Templates:** the reading sentence generator returns a sentence for every possible state sequence shape you can construct from the rules.

Also add a manual checklist to the README: the reveal divider works on a phone; playback runs to the end; the dropped date shows as a gap; a shared link reopens the same cell and date; switching language changes every visible string.

---

## 13. Build order

Work in these milestones. After each one: run `npm run typecheck`, `npm test` and `npm run build`, then commit.

| Milestone | Delivers |
| --- | --- |
| 1. Contract and generator | Types, zod schemas, `docs/data-contract.md`, the full mock generator, its checks and tests, a committed `public/bundle/` |
| 2. Data layer and map | Loader with error screen, app state with URL sync, season map with the state layer, timeline with play, legend with counts |
| 3. Pulse card | The layered chart, reading sentence, HH/HV/ratio toggle, copy link |
| 4. Reveal, scorecard, method | The three remaining screens, the "Simulated data" badge everywhere |
| 5. Polish and ship | Both languages, light and dark themes, accessibility pass, other map layers, GitHub Pages deployment with the public link in the README |
| 6. Stretch | World screen; any extra polish the team asks for |

**The minimum demo is milestones 1 to 4.** If time is short, ship that and stop.

---

## 14. Definition of done

- `npm run mock && npm run build` works from a fresh clone.
- The deployed site opens without sign-in and shows the "Simulated data" badge.
- A judge who only looks at the first screen for ten seconds understands the idea.
- Replacing `public/bundle/` with any contract-valid bundle changes the content and nothing breaks.
- The README explains: what the project is, how to run it, how to regenerate mock data, how to swap in real data, the data contract location, sources, licence, and how AI tools were used to build it.

---

## 15. When you are unsure

- If a library API might not exist, check the installed types or docs, and tell me what you checked.
- If the brief seems to conflict with itself, stop and ask.
- If a requirement looks too expensive for the time, say so and propose the smallest version that keeps the story intact.
