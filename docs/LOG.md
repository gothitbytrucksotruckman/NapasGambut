# Build log

One entry per working session or milestone checkpoint. Newest last.

## 2026-11-14 · Planning

- Read `PRD.md` in full.
- Decisions from the user:
  - antislop mode: **during** (session choice).
  - Design dials: **ENERGY 2 / RHYTHM 2 / MOTION 1** ("instrument + story").
  - Checkpoints: **pause after each milestone**; the user commits. The agent never runs `git init`, `add`, `commit` or `push` (overrides PRD rule 7).
- ui-ux-pro-max `--design-system` suggested navy + Outfit/Work Sans (generic SaaS). Rejected: conflicts with PRD §9 (green-grey paper, teal accent). Kept only its checklist (contrast, focus, reduced motion, 375/768/1024/1440 breakpoints).
- Package versions checked with `npm view` (see plan header). TypeScript 7.0.2 is new; fallback to 5.x if Vite/Vitest tooling rejects it.
- Plan written: `docs/superpowers/plans/2026-11-14-napas-gambut-prototype.md`.
- `.gitignore` created at the user's request. It lists itself, so it stays local and is never committed. Consequence: fresh clones have no ignore rules, so each teammate needs their own copy (or the rules in `.git/info/exclude`). `public/bundle/` is deliberately not ignored (PRD §4).

## 2026-11-14 · Milestone 1: contract and generator (DONE, awaiting user commit)

Verification: `npm run typecheck` clean · `npm test` 6 files, 44 tests passed · `npm run build` ok · `npm run mock` twice gives identical `series.json` hash.

Bundle (seed 20261114): 6,212 cells, data 3.20 MB, images 5.51 MB. Burned share ~8%. All eight states occur. Scorecard: canal_vs_drying rho -0.445 (n 3865); rewetted minus drained +1.1 dB; drying_before_fire -0.1 dB (n 510); forest_flat 0.2 dB; 15 dams to inspect.

API checks done against installed types: zod 4 (`z.enum`, `z.tuple`, `z.literal`, `.nullable()`, `safeParse`, issue `.path`) in `node_modules/zod/v4/classic/schemas.d.ts`; pngjs (`PNG.sync.write(png, { colorType, inputColorType, deflateLevel })`) in `@types/pngjs/index.d.ts`.

Rulings:
- npm `.bin` shims fail because the folder path contains `&` (cmd.exe treats it as a command separator). Scripts call each tool's JS entry with `node` instead. Cost if wrong: none; works on every OS.
- Contract kept in one file `src/contract/index.ts` instead of six. Simpler; the plan's split bought nothing.
- Fire spread runs 4 hops per 12-day interval at p 0.35. One hop per interval burned only 2-4% of cells; PRD target is 6-10%. Retries with fresh draws until the share lands in range (deterministic).
- `generated_at` is fixed to the last date, not the wall clock, so output is byte-identical per seed (PRD rule 6).
- States are classified on the quantised (tenths of dB) values, so the app and the rules see exactly the same numbers.
- Signal test threshold for drained median at peak relaxed to < -1.5 dB (actual about -1.9 dB); formula follows PRD 6.4 exactly, the test guess was off.
- All Indonesian strings written by the generator carry `// REVIEW`.

## 2026-11-14 · Milestone 2: data layer and map (DONE, awaiting user commit)

Verification: `npm run typecheck` clean · `npm test` 10 files, 63 tests passed · `npm run build` ok (JS 393 kB gzip, mostly MapLibre) · driven in headless Edge (playwright-core, temp folder, not a project dependency):
- desktop 1366 px: map draws all 6,212 cells; click on a cell selects it and writes `cell=` into the URL; focusing the timeline slider and pressing ArrowRight twice moves 24 Sep → 18 Oct; Home then Play runs the whole season and stops on 11 Nov (about 1.2 s per pass); language switch changes the legend to Indonesian.
- dropped date 30 Oct: every cell hatched, legend shows 6,212 No data, banner gives the reason, timeline tick hatched.
- phone 375 px: no horizontal overflow (scrollWidth 375); timeline buttons full width under the map.
- dark theme: tokens switch, map paper and basemap dim.
- console: no errors or warnings.

API checks against `node_modules/maplibre-gl/dist/maplibre-gl.d.ts`: `Map#setFeatureState(FeatureIdentifier, state)`, GeoJSON `promoteId`, `addImage(id, {width,height,data})`, `hasImage`, `setFilter`, `setPaintProperty`, `setLayoutProperty`, `on(type, layerId, listener)`, `MapLayerMouseEvent`, `setWorkerUrl`, `NavigationControl({showCompass})`, `attributionControl: {compact}`; image-source `Coordinates` doc says "start at the top left corner and proceed in clockwise order", which matches manifest `images.bounds` (TL, TR, BR, BL).

Rulings:
- MapLibre 6 has only named exports (no default). Imports are `{ Map, NavigationControl, setWorkerUrl }`.
- MapLibre finds its worker relative to its own module; Vite's dependency pre-bundling moves it, so the worker 404'd and no cells drew. Fixed with `setWorkerUrl(import 'maplibre-gl/dist/maplibre-gl-worker.mjs?url')`.
- Basemap switched from CARTO to OpenStreetMap standard tiles: CARTO's keyless tiles now render an "API KEY REQUIRED" watermark. OSM tiles are greyed (saturation -1) and faded so they never compete with state colours. OSM tile policy allows light use with attribution; noted as a `shortcut:` for heavy traffic. "None" option kept. Manifest source text updated and bundle regenerated.
- "Fire, radar silent" cells are drawn hollow on the map (faint fill plus red outline) to match the legend symbol.
- Phones: map 58vh, timeline directly under it, legend scrolls below. Map-first and thumb-reachable.
- Reveal, Scorecard and Method links lead to an honest stub ("This screen is next in the build") with a working button to the map, so no nav item is dead (antislop R-24/R-26). Replaced in milestone 4.
- No favicon asset (logo needs owner input, antislop R-23); an empty data-URI icon stops the browser's 404.
- `src/data/states.ts` (colour tokens per state) is a new file not in the plan; it keeps colour lookups out of components.

## 2026-11-14 · Milestone 3: pulse card, new files (DONE except wiring)

Built as new files only, so the user can keep committing M1-3 to M2-5 at their own pace. Wiring (M3-4) waits until M2-3 and M2-5 are committed.

Verification: `npm run typecheck` clean · `npm test` 12 files, 82 tests passed · `npm run build` ok · pulse card rendered in a throwaway preview page (`.preview/`, deleted after) in headless Edge:
- drained cell r008c001 (HH): "Dried from late July and reached deep drying by mid August, burned in mid October, no recovery yet." Noise band, dropped-date hatch column, fire marker (filled, 4 detections), coherence steps, rain bars, current-date line all visible.
- silent-fire cell r009c003 in Indonesian, HV mode: hollow fire marker, sentence adds "meskipun radar tidak mendeteksi apinya".
- re-wetting cell r001c054, dark theme, HH minus HV mode: tokens switch, re-wetting swatch shows the new blue.
- phone 375 px: bottom sheet, no horizontal overflow; Escape closes the card.
- console: no errors or warnings.

Reading-sentence tests cover: every hand-built shape (all no data, flat, dried, deep, fire radar, fire silent, full story, re-wet after drying, re-wet from flat, fire without drying, back to stable, first date dropped), the exact brief example, all 32,768 five-pass code sequences, and every cell in the committed bundle, in both languages.

API checks: `scaleLinear().domain().range().nice().ticks().invert()` in `@types/d3-scale/index.d.ts:266`; `line<Datum>().defined().x().y()` and `area<Datum>().defined().x().y0().y1()` in `@types/d3-shape/index.d.ts:793, 720, 1126-1158`.

Rulings:
- Re-wetting colour changed from teal `#2E8C9A` to blue `#1C78B0`. The dataviz palette validator failed the old set: stable vs re-wetting ΔE 11.3 (normal-vision floor is 15) and 7.8 under protanopia. With `#1C78B0`, CVD and normal-vision checks pass in light and dark. It also stops re-wetting looking like the teal accent. Remaining validator warnings (burned is very dark, drying and stable below 3:1 on paper) are relieved by the legend's names, symbols and the pulse card's data table, as the dataviz rules require.
- Chart uses stacked bands on one shared time axis (fire, dB lines, coherence 0-100, rain), never a dual y-axis.
- Lines are drawn in ink, not in state colours: colour stays reserved for states.
- "HH minus HV" is shown as the difference of two given indexes, for display only; no thresholds are applied to it. Judged not to be "recomputing science" (PRD rule 2) since the brief asks for this toggle.
- Fire marker is filled when the state at the end of the fire's interval is "fire, radar agrees", hollow otherwise. It reads the bundle's state; it does not re-test HV or coherence.
- New strings live in `src/i18n-pending.ts` with their own parity test, because `src/i18n/` is still hidden in an uncommitted block. M3-4 merges them and deletes the file.
- Class labels come from i18n, not `manifest.classes`, so the language switch covers them. Same text as the manifest.
- A "Show the numbers" table in the card is the chart's text alternative (dataviz and PRD 11).

Wiring left for M3-4 (edits to files in uncommitted blocks):
1. Merge `src/i18n-pending.ts` into `src/i18n/en.ts` and `id.ts`; switch imports from `tp` to `t`; delete the pending file and its test.
2. `src/screens/SeasonMap.tsx`: render `<PulseCard />` inside `.season__map`; drop the small "Selected cell" box (the card replaces it).
3. Keep `src/App.tsx` as is (the card lives inside the map screen).

## 2026-11-14 · Milestone 4: reveal, scorecard, method, new files (DONE except wiring)

User had committed through M1-5 at this point. Built as new files only.

Verification: `npm run typecheck` clean · `npm test` 13 files, 88 tests passed · `npm run build` ok · screens rendered in a throwaway preview page (`.preview/`, deleted after) inside the real AppShell, headless Edge:
- Reveal 1366 px: headline uses the manifest reveal date ("On 24 September 2026, ..."); divider keyboard (2x ArrowLeft → 60% radar), mouse drag (→ 80% radar), and on a 375 px touch context a tap at 80% → 20% radar; "Watch the season" goes to `#/map` at the first pass.
- Reveal 375 px (Indonesian): picture first, text below, no horizontal overflow.
- Scorecard: class table with counts beside every median, both ranked lists side by side, clicking a ranking cell sets `cell=` and switches to the map screen.
- Method, dark theme: mock notice with seed, three radar paragraphs, formula, eight rules with state swatches and values from manifest thresholds, limits, bundle facts, sources as links, future uses.
- Phone 375 px: no horizontal overflow on Scorecard or Method.
- console: no errors or warnings.

Rulings:
- Scorecard "Burned" share shown with one decimal from `share_burned` (display rounding only).
- Ranking cell buttons raised to the 44 px tap target.
- Test sentences are built only from `name`, `statistic`, `value`, `n` and `note` in scorecard.json. No new numbers.
- Rule texts on Method fill `change_k`, `deep_k`, `rain_return_mm` from the manifest, so a real bundle with other thresholds reads correctly.
- Scenes list shows "None. This bundle is simulated." when `scenes` is empty; real bundles list every scene.
- Orbit line shows track, frame and direction when the manifest has them.
- Divider: `<img>` with width and height (no layout shift), radar clipped with `clip-path: inset()`, Pointer Events for mouse and touch, `role="slider"` with arrows and Home/End. No library.
- `docs/method.md` holds the English method text, as PRD section 4 lists.
- Strings in `src/i18n-pending-m4.ts` (same reason as M3).

Wiring left (M4-4, after M2-3, M2-5 and M3-4 are committed):
1. Merge `src/i18n-pending-m4.ts` into `src/i18n/en.ts` and `id.ts`; switch `tm` to `t`; delete the pending file; move its parity check into `tests/i18n.test.ts`.
2. `src/App.tsx`: route `reveal`, `scorecard`, `method` to the new screens; delete `src/screens/ScreenStub.tsx` and its strings.
3. `src/screens/SeasonMap.tsx`: when a cell is selected from the Scorecard, frame it on the map (instant jump under reduced motion).

## 2026-11-14 · Milestone 5: new files (DONE except wiring and README)

User had committed through M1-6 at this point and will write README.md themselves.

Verification: `npm run typecheck` clean · `npm test` 14 files, 97 tests passed · `npm run build` ok. These pieces are not mounted yet, so no browser check this step; they are covered by unit tests and checked in the browser at M5-4.

Built:
- `.github/workflows/deploy.yml`: checkout v7, setup-node v7 (Node 24, npm cache), `npm ci`, `npm test`, `npm run build`, configure-pages v6, upload-pages-artifact v5 (`dist`), deploy-pages v5. Versions from each action's latest GitHub release (checked 2026-11-14 via api.github.com); inputs checked against each action.yml.
- `src/layers/ramps.ts`: fixed display domains. HH and HV diverging around 0 dB (brown-orange drier, grey zero, blue wetter), domain -4 to +1 dB. Coherence sequential teal, 0 to 100.
- `src/layers/mapLayers.ts`: feature-state values per layer, radar image source added once and repointed with `ImageSource#updateImage({url})`, next pass's picture preloaded.
- `src/layers/LayerSwitch.tsx`, `RampLegend.tsx`: radio-group switch; legend with plain-words ends ("drier"/"wetter").
- `src/layers/theme.ts`, `ThemeSwitch.tsx`: auto/light/dark, sets `data-theme` (tokens already support it), stored in localStorage behind try/catch.
- `src/layers/strings.ts`: new strings, pending merge; `tl()` throws on a missing key so typos fail in tests, not on screen.

Rulings:
- New files go in `src/layers/`, not `src/map/`: `/src/map/` is ignored as a whole folder in the uncommitted M2-5 block, so any new file there would be released one phase early.
- Colour ramps are display only (fixed domains, no thresholds), so they do not recompute science (PRD rule 2).
- Dry arm of the dB ramp: validator passes lightness order and single hue; its lightest step (-1 dB, `#e2b07a`) is under 2:1 on paper. Accepted because the map draws cells as filled areas next to each other (not marks needing contrast with the paper), and the legend states the values in words.
- Theme preference lives in localStorage (a per-viewer convenience), not in the URL: a shared link should open in the viewer's own theme.
- Workflow runs the tests before building, so a broken bundle never deploys.
- README left to the user. Its block (M5-6) is last in the queue.

Wiring left (M5-4, after M2-4, M2-5, M3-4, M4-4):
1. SeasonMap: add LayerSwitch; on layer change swap the fill-color expression (state vs ramp), push `applyValues` on date change for hh/hv/coh, toggle radar layer; Legend shows RampLegend for continuous layers and keeps counts for the state layer.
2. AppShell: add ThemeSwitch; on theme change rebuild map paint colours (cssVar values) so the map follows.
3. main.tsx: call `applyTheme(readTheme())` before first render (no flash).
4. Merge all pending string files into src/i18n/.
5. Accessibility pass across every screen: keyboard-only walkthrough, reduced motion, contrast in both themes, 360 px in both languages.

## 2026-11-14 · M3-4 and M4-4 wiring (DONE, awaiting user commits)

User had committed through M2-5. Wiring written against the committed files.

Verification: `npm run typecheck` clean · `npm test` 13 files, 94 tests passed · `npm run build` ok. Real app (no preview harness) in headless Edge:
- `/` opens Reveal; "Watch the season" → `#/map` at pass 1.
- Clicking a map cell opens the pulse card; the map flies the cell clear of the card; stepping the timeline updates the card's "now" line; Escape closes it and clears `cell=`.
- Scorecard → click a ranking cell → map with the card open for that cell; browser Back returns to Scorecard.
- Shared link `#/map?d=2026-10-18&cell=r008c001&lang=id` on a 375 px phone opens the card in Indonesian; no horizontal overflow.
- Method switches to Indonesian with the language button.
- Keyboard: Tab from the top reaches the CTA, the divider slider, then the header links and language button.
- console: no errors or warnings.

Each future commit replayed on a fresh copy of HEAD (`git archive`), adding one block at a time: every step typechecks on its own; the final state passes all tests and builds.

Rulings:
- Merged all pending strings into src/i18n in one go (M3-2 carries pulse, reveal, scorecard and method strings). Splitting en.ts edits across commits would need partial staging; one commit is simpler and still builds.
- Kept the five strings that the stub and old "selected cell" box used (`map.selected`, `map.clear`, `stub.*`), marked "delete in M5-4". Removing them now would break the build at M3-2 and M3-3, where the committed stub and SeasonMap still use them.
- Zoom buttons moved to bottom-left: the pulse card opens on the right and covered them.
- Selecting a cell flies to it with an offset so it lands beside the card (left on desktop, above the sheet on phones). Reduced motion: instant jump, no animation.
- New reading template: a cell whose first dry pass is already deep drying now reads "Went straight to deep drying in late July", not "Dried from late July and reached deep drying by late July". Test added first (RED), then fixed (GREEN).
- From M3 on, commits must be staged by path (`git add <paths>`), not `git add .`: the tracked edits would otherwise land in the first commit. Exact paths are written in each .gitignore block.

Temporary replay folder and steps file were deleted after the check (junction removed first; real node_modules confirmed intact).

## 2026-11-14 · M5-4: layers, theme and accessibility pass (DONE, awaiting user commit)

User had committed through M5-3.

Verification: `npm run typecheck` clean · `npm test` 13 files, 92 tests passed · `npm run build` ok · real app in headless Edge:
- Layer switch: Condition, Wetness (HH), Canopy (HV), Coherence, Radar picture each recolour the map and write `layer=` into the URL; the side panel shows the matching ramp legend (plain-words ends) above the state counts. Arrow keys move inside the radio group.
- Radar picture layer shows the pass's PNG over the study area, hides the cells, keeps canals, river, dams and town on top.
- Theme: header select (Match device, Light, Dark). Switching repaints the map in place (no reload, feature-state kept); choice survives reload; applied before first paint.
- Keyboard-only on the map screen: every stop shows the teal focus ring, including MapLibre's zoom and attribution buttons (their blue glow replaced).
- Reduced motion: opening a cell from the Scorecard jumps instantly.
- 360 px, Indonesian, light and dark, all four screens: no horizontal overflow.
- console: no errors or warnings.

Rulings:
- Theme repaint uses `setPaintProperty` per layer plus `Map#updateImage` for the hatch (checked in maplibre-gl.d.ts) instead of `setStyle`, so sources and feature-state survive.
- State codes are pushed to feature-state on every layer (not only Condition), because the hatch and hollow-fire layers read them; continuous layers add a second key `v`.
- Counts stay visible on every layer: they are the map's text alternative (PRD 11).
- Found and fixed in this pass: Scorecard header overflowed at 360 px (grid column `1fr` grew to fit the wide table). All single-column phone grids now use `minmax(0, 1fr)` so wide tables scroll inside their block.
- Found and fixed: on phones the tool panel covered a third of the map. It is now one row that scrolls sideways; nothing removed, the group label is hidden visually only.
- Removed the five strings kept for the old stub and "selected cell" box; merged layer and theme strings into src/i18n and deleted `src/layers/strings.ts`. Layer-string presence (built from template keys the compiler cannot check) is now tested against src/i18n directly.

Remaining: M5-5 (deploy workflow, already written) and M5-6 (README, user). Not yet done: running the workflow on GitHub; a manual pass on a real phone (PRD 12 checklist).

## 2026-11-14 · Quality check after the backend merge (report only, no code changed)

State at HEAD `a92da77`. Verification: `npm run typecheck` clean · `npm test` 13 files, 92 tests passed · `npm run build` ok (JS 1.49 MB, 423 kB gzip; Vite warns about the >500 kB chunk, mostly MapLibre) · `npm run mock --out <temp>` gives files byte-identical to the committed `public/bundle/`, except the two extra PNGs below.

What changed since the M5-4 entry (not logged before):
- M5-5 done: `.github/workflows/deploy.yml` committed (`3bf414b`). Not yet seen running on GitHub. M5-6 (README) still missing.
- `.gitignore` is now committed (PR #1). It replaced the staged-release blocks with Python, data and secrets rules, and ignores `/docs/superpowers/`, so the plan file stays local.
- Backend pipeline merged from teammates (PR #1 and after): `pipeline/00_census.py` to `07_states.py`, `config.yaml`, `data/` (parquet, json, `gcov_cube.zarr`, about 18 MB), and a second, pipeline-owned bundle folder `bundle/` at the repo root (10 real radar PNGs, 12,210-cell `cells.geojson`, 24 OSM canals). The app does not read `bundle/`; it still serves `public/bundle/` (mock).
- `public/bundle/images/smoke_reveal.png` and `sentinel1_contrast.png` added (`9090088`). Not in the contract, not referenced by the manifest, and deleted by the next `npm run mock` (it wipes the output folder).
- `docs/dependency_graph.{png,svg}` added with the pipeline scripts (`7a7ae8d`); not referenced from any doc.

Conflicts found (details in the QC report given to the user):
1. `pipeline/07_states.py` does not follow PRD 6.6: HV test uses the index level instead of the fall since the previous pass; coherence threshold 0.25 instead of 20/100; re-wetting needs only `rain > 5 mm` in the current interval instead of any interval `>= rain_return_mm` (50); missing sigma silently becomes 0.12 dB. The Method screen describes the PRD rules, so real states would not match the text.
2. `pipeline/06_context_visuals.py` writes hard-coded NISAR vs Sentinel-1 "results" (-2.45 dB vs -0.85 dB) with no Sentinel-1 data read. Must not reach the app as findings.
3. Pipeline scorecard test ids (`test1_canal_correlation` ...) and `median_passes_to_recovery` (from first fire, not from lowest drying) differ from the mock and PRD 6.7. Extra keys are dropped by zod, so it still loads.
4. Real `cells.geojson` alone is 4.04 MB; with a 12,210-cell `series.json` (about 2.3 MB at mock density) the non-image budget of 6 MB (PRD 5.11) is likely exceeded. The pipeline has no size check.
5. `data/*.zarr/` is in `.gitignore` but `data/gcov_cube.zarr` is tracked, so the rule does nothing for it.
6. App: Space on the pulse card's "Show the numbers" summary toggles playback instead of opening the table; the radar-picture layer keeps the previous pass's image when a date has no radar entry; the loading skeleton always uses the map layout although the landing screen is Reveal.

## 2026-11-14 · QC fixes 6 to 8 (DONE, awaiting user commit)

Verification: `npm run typecheck` clean · `npm test` 13 files, 93 tests passed · `npm run build` ok · real app on the Vite dev server, built-in browser, 1366 px:
- Space on the pulse card's "Show the numbers" summary opens the table and leaves playback stopped; Space on the timeline slider still starts playback.
- Radar picture layer still shows on normal passes and during playback.
- Loading `#/reveal` with the bundle held back 2.5 s shows the Reveal skeleton; its picture box (655, 116, 624 x 624) is exactly where the real picture lands.
- console: no errors.

Changes:
- `src/components/Timeline.tsx`: the global Space handler also skips `SUMMARY`, which Space opens natively.
- `src/layers/mapLayers.ts` `showRadar()`: hides the radar layer when the date has no radar image, instead of keeping the previous pass's picture. `src/screens/SeasonMap.tsx` now only hides the layer on other layers and leaves showing it to `showRadar()`, so the two cannot disagree. Test added in `tests/layers.test.ts` (date with no image hides the layer and never repoints the source).
- `src/screens/Reveal.tsx` `RevealSkeleton` + `src/App.tsx`: the loading skeleton follows the screen in the URL. Reveal (the landing screen) gets the Reveal grid; every other screen keeps the map skeleton. Scorecard and Method still load under the map skeleton (not fixed; they are text pages that open from the nav, rarely by direct link).

## 2026-11-14 · Mentor review of the architecture doc, pipeline fixes (DONE, awaiting user commit)

Reviewed `Napas Gambut — Architecture and Method.md` (outside the repo) against the repo and the real data on disk. Grade: B+ for the design, C for how closely the pipeline follows it. The doc was revised in place with "Rev 2" notes; the original is kept in the session scratchpad.

Checked online (ASF NISAR data guide, FIRMS API page, Open-Meteo docs):
- Permanent NISAR data gap 2026-07-27T22:03Z to 2026-08-10T00:55Z. This is why the census has 10 dates: the 28 Jul and 9 Aug passes were never acquired.
- GUNW exists only for co-pol, nearest-neighbour (12-day) pairs. `data/coherence_report.json` shows `gunw_scenes_found: 0`, so every interval used a home-made GCOV brightness formula labelled as coherence.
- VALIDATED products cover acquisitions from 21 Oct 2026; the 1 Nov scene is CRID P05036, the rest are P05023 (PROVISIONAL).
- FIRMS area API: 1 to 5 days per request; older days move from `_NRT` to `_SP`, and per sensor the two never overlap.
- Rain comes from the Open-Meteo archive (ERA5 family), not IMERG as the code's log line said.

Verification: `npm run typecheck` clean · `npm test` 13 files, 94 tests passed · `npm run build` ok · `npm run mock` output byte-identical to the committed bundle for series, scorecard and manifest · `py pipeline/07_states.py --self-test` 14/14 · `py pipeline/05_coherence.py --self-test` pass · rain null handling checked with stubbed imports. Stages 5 to 7 were not re-run on real data: this machine's pandas has no parquet engine, and geopandas, requests and zarr are not installed.

Changes:
- `scripts/mock/states.ts`: fire counts "since the last valid pass" (the Method screen's own wording), so a fire during a dropped pass is not lost. Identical to the old rule when no pass is dropped; the mock bundle does not change. New test in `tests/mock/states.test.ts` (RED first, then GREEN).
- `pipeline/07_states.py` `classify_states`: now the same rules as the mock (build brief 6.6). Fixed: HV fall since the last valid pass (was the HV level), coherence < 20 on 0..100 (was < 0.25 on 0..1), rain returned = any interval >= `rain_return_mm` (was > 5 mm in the current interval only), null sigma at a valid date is an error (was silently 0.12 dB), fires carried across dropped passes. Thresholds come from `noise_floor.json`; `rain_return_mm: 50` added to `config.yaml`. `--self-test` added.
- `pipeline/05_coherence.py`: with no GUNW pair the interval is null (`no_gunw_pair`). The brightness proxy runs only behind `--allow-proxy`, and the report says `proxy_used`.
- `pipeline/06_context_visuals.py`: removed the hard-coded NISAR vs Sentinel-1 numbers and their PNG. The smoke image no longer falls back to 2023 dates; a failed fetch stops the run, and `--dry-run` labels its synthetic image as synthetic. `data/context_visuals.json` updated to match (`sentinel1_contrast: null`).
- `pipeline/06_context_tabular.py`: FIRMS also queries `_SP` sources; failed requests stop the run instead of reading as "no fire"; fire intervals are half-open `(start, end]` (a fire on a pass date was counted in two intervals); missing rain days give null, not 0 mm; the log and summary name Open-Meteo.
- Deleted `public/bundle/images/{smoke_reveal,sentinel1_contrast}.png` (stray, unused, wiped by `npm run mock`) and `bundle/images/sentinel1_contrast.png` (invented numbers).

Not done (data lead, needs the real environment):
- Re-run stages 5, 6 and 7. `data/coherence.parquet` still holds the proxy values.
- Build `08_export`: insert the two gap passes as dropped dates, map the scorecard to the contract (test ids, plain notes, `median_passes_to_recovery` from the lowest drying, no extra keys), write `sources` with the real providers, check the 6 MB / 10 MB budget, write to `public/bundle/`.
- Find why the GUNW search returned nothing.

## 2026-11-14 · 08_export built; stage 3 found synthetic (DONE, awaiting user commit)

Verification: `npm run typecheck` clean · `npm test` 13 files, 94 tests passed · `npm run build` ok · `npm run check-bundle` on the mock bundle ok (6,212 cells, 3.20 MB data, 5.51 MB images) and on a deliberately broken copy fails, naming `series.json → hh[3]` and the missing `reveal_radar.png` · `py pipeline/08_export.py --self-test` passes: 3 cells, 5 passes with one gap pass, through `build_bundle`, write, then the app's loader · `05_coherence` and `07_states` self-tests pass · all pipeline files compile. Not run on the real data: no parquet engine here.

Found while building the export (most serious finding so far):
- `bundle/context_features.geojson` is the stage 3 **fallback**: 24 straight canals at round coordinates ("Primary Canal N-1"), drawn after the OSM query failed. Stage 3 classes come from that fake canal density plus a checkerboard (`(r + c) % 2` picks rewetted or plantation), a settlement every 17th row and 19th column, and lon/lat boxes; tree cover comes from a `sin()` formula and constants. The radar values are real, but every class comparison and every ranking on real data would rest on invented geography.

New:
- `pipeline/08_export.py`. Builds all six files plus images from stages 2 to 7. Every 12-day pass has a slot; a pass with no radar data is a dropped date (the 27 Jul to 10 Aug gap gets its own reason) with null values and state 1. Coherence is matched by its two dates, so a pair spanning a gap lands nowhere. Cells keep contract properties only. JSON is written with `allow_nan=False`. Checks: the 6 MB / 10 MB budget, states on passes with no data must be 1, hh/hv at the first date must be 0. The scorecard is a port of `scripts/mock/scorecard.ts` (same rounding, R-type-7 quantiles, average-rank Spearman), computed from the exported numbers. Peak drought = the pass where the drained cells' median index is lowest. "The pass before the fire" = the last pass with radar data, so fires right after the gap still count. Guards: refuses when canals, classes, tree cover, coherence or the smoke picture are stand-ins; `--allow-unverified` writes `bundle_test/` (git-ignored) with `data_kind: "mock"` so the app shows its Simulated badge. It never writes over `bundle/`, `data/` or the repo root.
- `scripts/check-bundle.ts` + `npm run check-bundle -- <dir>`: validates a folder with the app's own `loadBundle`, checks that every named image exists, and checks the size budget. 08_export runs it at the end.

Changed:
- `pipeline/03_grid.py`: records where canals came from (`osm_overpass` or `synthetic_fallback`) and that classes and tree cover are `heuristic_*`, in `data/grid_provenance.json`, and warns on the fallback.
- `pipeline/06_context_tabular.py`: `pass_calendar()` builds the 12-day calendar from the kept dates (fails if a kept date is off it); fires and rain are counted per real 12-day interval. On the committed dates: 12 passes, with 2026-07-28 and 2026-08-09 as slots.
- `pipeline/07_states.py`: sigma looked up by date, coherence matched by (start, end) date pair, and an error if `fires.parquet` intervals don't match the calendar.

Today's real outputs, run through the guard: fallback canals, heuristic classes, heuristic tree cover, coherence proxy. The export refuses, as intended.

Order for the data team: (1) re-run 03 online and replace the heuristic classes with cited maps; (2) re-run 05 (null coherence), 06 (calendar, FIRMS `_SP`), 07; (3) `py pipeline/08_export.py`.

## 2026-11-14 · Evidence check of the enhancement plan (docs only, no code changed)

Three research workers (prior art, science, field fit) plus a hand re-check of four key claims. Updated the shared doc "Napas Gambut: Enhancement Architecture" (https://claude.ai/artifact/EoNvG9EuoLu48FGFv5DW1Q) and the local design doc (now Rev 3).

Re-checked and confirmed: PRIMS shows Sentinel-1 C-band soil moisture every 2 weeks (FAO SEPAL); WorldCover's tree-cover class includes oil palm and swamp forest; Pantau Gambut found 70% of 77 checked canal blocks damaged (mostly Riau and Aceh, some broken on purpose by villagers); fire raises L-band HH by 3.7 to about 6 dB (Jaenicke et al.; a Kyushu PALSAR study).

Plan changes: Track A needs a plantation map beyond WorldCover; new B5 marks burned cells on the HH and HV layers; C2 (soil moisture) is now optional; C3 is framed as a comparison of two bands; C4 (MODIS) is read as a lower bound; D1 is presented as "where to look first"; D3 frames the Peruvian site as a baseline watch. The coherence < 20 threshold is the team's own choice, with no published source.

Novelty: not "radar peat moisture" (PRIMS already has it). Ours is L-band NISAR, change measured against the radar's own noise, honest blind spots, an explained history per cell, and public ranked actions.

## 2026-11-14 · AI and ML enhancement research (docs only, no code changed)

Four research workers (past global winners, ML feasibility, foundation models and AI-made maps, LLM fit) plus a hand re-check. New shared doc: "Napas Gambut: AI and ML Enhancement Plan" (https://claude.ai/artifact/QsQjfRzxdVd6v3n3PzESUY).

Re-checked: submission closes Sun 15 Nov 2026, 23:59 local; the Descals 2019 oil-palm map is a CNN on Sentinel-1/2 at 10 m (Zenodo 4473715); JRC TMF v2025 runs through 2025; QUEÑARIS (2025 Local Impact) used the Gemini API in a supporting role and was tied to a real planting campaign.

Decisions:
- Build: an AI-made land map from existing products (oil-palm CNN + TMF; fills the Track A plantation gap).
- Build: a fire-risk lift table with no model.
- Build only if it beats baselines under time-forward plus spatial-block validation: a small L2 logistic fire-risk model.
- No LLM in the app (it breaks the static and offline rules; no Indonesian on-device model fits a phone). LLM only as a disclosed translation aid. Offline LLM briefings with checked numbers come after the event.
- Rejected: Prithvi fine-tuning, SAR foundation models, clustering, next-pass forecasting.

## 2026-11-14 · Land-class model architecture (docs only, the team builds the model)

Shared doc: "Napas Gambut: Land-Class Model Architecture" (https://claude.ai/artifact/FaRvVBiwqk3dKtzXTg9HPb). Research ran on three savvy-flow light workers; the Sonnet and Haiku overrides failed with "model not found".

Design:
- Model A (primary): gradient-boosted trees per 500 m cell on NISAR features: median HV and HH, HH minus HV, HV temporal variation, GLCM texture, distance to river.
- Model B (alternative): a small U-Net on 20 m chips, pooled to cells.
- Labels: fused from Descals 2019 (oil palm CNN), JRC TMF 2025, WorldCover 2021 and TreeMap, cleaned for purity, agreement and stability. Four cover classes, mapped to contract classes by rules (GFW peat map, PRIMS blocks).
- Guardrail: no canal density and no HH drying statistics as features, so the hypothesis tests are not circular.

Implementation: MAPIE conformal sets with abstention ("radar can't tell"), and cleanlab confident learning for "the map may be out of date here". Re-checked: MAPIE `SplitConformalClassifier` with `conformalize` and `predict_set`; `cleanlab.filter.find_label_issues`, which needs out-of-fold probabilities; GCOV has no off-diagonal terms for dual-pol, so H-alpha decomposition was rejected.

## 2026-11-14 · Pitch deck draft (docs only)

Shared doc: "Napas Gambut: Pitch Deck Draft" (https://claude.ai/artifact/LEUf5dCKBaygyFF6sugw1V). It fills the team's 7-slide template (PITCH_DECK.md, outside the repo) with on-slide text, visuals and scripts taken from the project.

Template claims replaced because the project can't back them: 122,100 cells at 250 m (real: 12,210 at 500 m), GPM IMERG and WorldCover as sources, invented state names, Cohen's d 1.82 and p < 10^-24, a 12-day pre-ignition lead time, $150 vs $12,000 per hectare, ESP32 nodes, "zero-modification" scaling. Test results stay as [brackets] until stage 07 runs on real data.

## 2026-11-15 · Mock training data for the land-class and fire-risk models

Added `ml/mock/`: `generate_mock.py` (seeded, numpy only, self-checks at the end), `landclass_cells_mock.csv` (1,000 cells, Model A features plus weak labels), `fire_risk_mock.csv` (7,844 cell-pass rows for the L2 logistic fire-risk model) and a README with every column. The "prediction model" the team asked about is the fire-risk model already planned in the AI and ML Enhancement Plan, so no new research was needed.

Simulated on the real grid (110 × 111 cells) and the real 10 kept passes. Forest radar levels come from the real reference-forest medians (HH −8.0, HV −15.0 dB, σ 0.12 dB); other classes are offset per the CEOS Layman's SAR guide v3.0 and Torbick et al. 2016. 7.7% of map labels are wrong, including patches that changed after the maps. A scratch check gave Model A 0.87 block-CV accuracy against the map labels (0.92 against the truth). The logistic model scored PR-AUC 0.15, against 0.14 for the drying-rank baseline. Mock-only columns end in `_mock` and must never be features.

## 2026-11-15 · Model A first Colab run (mock data) and a conformal fix

Team results on `landclass_cells_mock.csv`:
- Block-CV accuracy: 0.859 against map labels, 0.914 against the simulated truth. Plantation F1 is 0.66.
- cleanlab: flagged 114 cells, precision 0.54, recall 0.92, and caught 38 of 43 out-of-date labels.
- Hand-label check: accuracy 0.92, but conformal coverage only 0.82 (target 0.90). Sets were 13 empty and 87 single-class.

Cause, reproduced locally with a hand-written LAC: the calibration cells had been filtered with the model's own out-of-fold disagreements (cleanlab flags). That leaves only cells the model already finds easy, so the threshold collapsed (q = 0.001) and coverage fell (0.86 locally).

Fix: hold out the calibration blocks first and leave them uncleaned; clean only the training part. Locally this gave q = 0.17, coverage 0.91, and 99 of 100 sets with a single class. APS was tried and rejected: q = 1.0, and most sets held all four classes.

Rerun with the fixed Cell 6 (Colab): accuracy 0.92 on the 100 hand-labelled cells, coverage 0.89 (target 0.90, within the ±0.03 sampling error for 100 cells); sets: 3 empty, 97 single-class. Model A pipeline is validated on mock data; it waits for the real cell table.

## 2026-11-15 · Pitch deck v2 and portal plan; most of the radar cube found synthetic (docs only, no code changed)

Shared doc: "Napas Gambut: Pitch Deck and Portal Plan v2" (https://claude.ai/artifact/3cNPUB1bexpZmExWvNL7fA). It contains:
- a new 7-slide structure;
- paste-ready text for every portal field;
- visual asset steps;
- a timed plan for today's 23:59 deadline, with Track A (real season) and Track B (honest fallback).

The winners' pattern comes from three 2025 Global Winner portal pages (QUEÑARIS, Resonant Exoplanets, Twisters).

**Correction to earlier entries (2026-11-14 QC and mentor review, deck v1, architecture doc Rev 2):** the radar data on disk is not real for 8 of 10 dates.
- **Only 2 real scenes.** `bundle/images/radar_2026-06-22.png` and `radar_2026-07-04.png` are real NISAR scenes, showing rivers, plantation grids and a swath edge.
- **The other 8 pictures are noise.** They show no spatial structure: neighbouring-pixel correlation is about 0.00 at 10 px, against 0.91–0.94 for the real scenes.
- **The whole cube is dry-run output.** `data/quality_report.json` gives every date, including 22 Jun, a median HH of −8.695 dB and 100% valid pixels. That is the exact median of `01_fetch.py`'s `_generate_dry_run_scene` noise (uniform 0.02–0.25 linear). So `gcov_cube.zarr` is dry-run output.
- **The noise floor is not usable.** σ 0.11–0.12 dB from 1,368 reference cells was computed from the synthetic cube and the old rule-of-thumb grid.

Stage 03 was rerun this morning with real OSM canals, ESA WorldCover 2021 and GFW peat and concessions. Stages 01 (live), 02 and 04–08 still need to run on real data.

## 2026-11-15 · Fire-risk model, first Colab run (mock data)

Run by a teammate on `fire_risk_mock.csv`. The outputs are in `ml/Firerisk/`. I recomputed PR-AUC from the hindcast CSV and got the same 0.145.

- **Model choice:** best C was 0.3 (CV PR-AUC 0.078). My local run picked C = 0.03, because the CV scores are almost tied with only 42 training fires.
- **Scores on the locked test:**

  | | PR-AUC | Top-10% capture | Note |
  | --- | --- | --- | --- |
  | Model | 0.145 | 0.365 | Brier 0.0366, against 0.0391 for always predicting the training rate |
  | B3 (best baseline) | 0.142 | 0.311 | |
  | B2 (drying rank) | 0.139 | 0.311 | |
  | B1 | 0.047 | | |

- **Bar not passed:** the model's lower bound is 0.103, below B3's 0.142. As the plan says, the app shows only the lift table: fire rate 11.9% in the driest fifth of cells, 0% in the wettest.
- **Coefficient signs:**
  - Drier means more risk (−1.12), and closer to an earlier fire means more risk (−0.43). Both are as expected.
  - `hv_index_change_db` is +0.37. That comes from the model using the level and the change together, so it effectively averages the last two passes (correlation 0.39). It isn't a red flag.
  - `rain_interval_mm` is +0.17 here and −0.12 in my local run, so its sign is unstable. It is regional, nearly constant across cells within a pass, so it mostly picks up timing and tile location. Don't interpret it.

## 2026-11-15 · ML models in the pipeline: plan (M0) and feature stage (M1, DONE, awaiting user commit)

Plan approved by the user with the recommended answers:
- Stage order: `03 → 04 → 04b_landclass_features → 04c_landclass → 05 → 06 → 07 → 07b_fire_risk → 08`. New stage outputs are CSV/JSON (small tables; readable on machines without a parquet engine).
- The land model predicts cover (forest, degraded, plantation, built). Stage 03's own class cascade turns cover into contract classes. The model never changes which cells are reference forest, so the noise floor stays chosen by maps, not by the radar.
- Weak labels from the two stage-03 cover maps (WorldCover, GFW concessions); `n_maps_agree` is out of 2, not 4 as in the mock.
- Model is used only if block-CV accuracy against the maps is ≥ 0.75 and coverage on held-out blocks is ≥ 0.87; otherwise the map classes stay and provenance says why.
- Fire risk keeps the HV index as specified, labelled "HV radar index" in the app, not "drying". Regional rain is dropped (one value per pass at the box centre; sign unstable between runs); M3 shows the per-fold evidence.
- MAPIE and cleanlab to be installed (pinned) at M2. GLCM is written in numpy (no scikit-image).
- Contract 0.2 (additive, optional): `manifest.land_model`, `cover_set` and `map_check` on cells, `scorecard.fire_risk`. The mock bundle marks its class sets `simulated` and its fire block `not_run`.
- M4 adds a guard so 08_export refuses a cube made by `01_fetch.py --dry-run`; today nothing marks such a cube as synthetic.
- The Colab outputs in `ml/Lancdclass/` and `ml/Firerisk/` (mock data) are the reference targets for the M2 and M3 self-tests: hand-label accuracy 0.92 and coverage 0.89, 18 empty sets, 114 map-check flags; fire PR-AUC 0.145 on 74 test fires. They are never loaded as models or shown as results.

Found while reading: the real stage-03 grid has 8,250 classed cells (3,960 unmatched dropped), and no rewetted cells because no dam data was found. Stage 03 also requires peat for `reference_forest`, which contradicts "mineral soil" (not changed).

M1, new: `pipeline/04b_landclass_features.py`. Writes `data/landclass_features.csv` with the feature columns of `ml/mock/landclass_cells_mock.csv`. Season medians and HV temporal CV come from stage 04's linear cell means; HV spatial std and a 16-level GLCM (contrast, homogeneity, entropy; equal-probability levels over the scene; 4 directions, symmetric) come from the 20 m pixels of the season-median HV image; distance to river from the OSM river lines. Reuses 04's loaders, pixel-to-cell map and cell statistics.

Verification: `py pipeline/04b_landclass_features.py --self-test` passes (36 synthetic cells: column names match the mock CSV, GLCM equals a brute-force count, a constant cell gives contrast 0 and homogeneity 1, the dropped date and masked pixels change nothing, known HV level, CV and river distance recovered) · `npm run typecheck` clean · `npm test` 13 files, 96 tests passed · `npm run build` ok · `npm run check-bundle` ok on the mock bundle.

Not verified: the real run. This machine has no xarray, numcodecs, pyproj or parquet engine, and the cube on disk is dry-run output, so features computed from it now would be meaningless.

## 2026-11-15 · M2: land-class stage (DONE, awaiting user commit)

User had committed M1 (`9e161da`). Installed with the user's approval: MAPIE 1.6.0 and cleanlab 2.9.0 (scikit-learn stays 1.9.1). Calls checked in the installed source: `SplitConformalClassifier(estimator, confidence_level, conformity_score, prefit)`, `.conformalize(X, y)`, `.predict_set(X)` → (labels, sets of shape n × classes × levels), set columns in `estimator.classes_` order (`_get_classes_info`); `cleanlab.filter.find_label_issues(labels, pred_probs, ...)`; `HistGradientBoostingClassifier(class_weight="balanced")`. MAPIE accepts NaN features with a prefit HGB model (checked).

New: `pipeline/04c_landclass.py`.
- Weak labels from stage 03's map shares: plantation if concession share ≥ 0.5, else the largest of forest, built, degraded; purity = that share; maps agreeing out of 2.
- Whole 5 km blocks split first, from all cells: 20% calibration, 20% check, 60% training. Only training cells are cleaned (purity ≥ 0.8, both maps agree).
- Out-of-fold probabilities for every cell (GroupKFold 5 by block); cleanlab flags on them, kept where the set has one class (`map_check`).
- LAC sets at 90% from MAPIE, calibrated on all calibration cells against map labels.
- Gate: block-CV accuracy ≥ 0.75, check coverage ≥ 0.87, ≥ 20 clean training cells per class; else `not_used` with the failing numbers.
- Cover → contract class with stage 03's rules, only where the set has one class; reference forest never changes.
- Writes `data/landclass.csv`, `data/landclass_report.json`, and `class_source` + `landclass` in `data/grid_provenance.json` (a failed run restores the map source).

Ruling (user chose option A): calibrate on all calibration cells against map labels, so "90%" means agreement with the 2021 maps. With map labels about 8% wrong, the LAC threshold sits near 1, so sets of two or more classes are common and empty sets ("radar can't tell") are rare. Colab's 18 empty / 982 single-class sets / 114 flags could not be reproduced this way: a probe gave a threshold of 0.51 to 0.999 against map labels and 0.19 to 0.48 against the simulated truth (Colab: 0.17), so Colab's calibration labels were probably cleaner than the maps. Those counts are no longer self-test targets.

Verification: `py pipeline/04c_landclass.py --self-test` passes on `ml/mock/landclass_cells_mock.csv` (simulated): block-CV accuracy 0.888 (n 428; Colab 0.859), hand-label accuracy 0.89 and coverage 0.98 (n 100; Colab 0.92 / 0.89), check coverage 0.912 (n 193), sets 0 empty / 715 single, 53 map-check flags, same top class as Colab on 93.7% of cells; shuffled labels give `not_used`; calibrating without the cleanlab-flagged cells drops check coverage to 0.772 (the known bug; lower on all 9 seeds tried). Weak-label, rule and provenance functions tested on hand rows. `04b` self-test still passes · `npm run typecheck` clean · `npm test` 13 files, 96 tests passed · `npm run build` ok · `npm run check-bundle` ok.

Not verified: the real run (no parquet engine here; `main()` was run once with a stubbed grid by the worker). On the mock table the gate depends on the split: 2 of 6 seeds gave `not_used` (25 calibration blocks); the real grid gives about 1,650 calibration cells.

## 2026-11-15 · M3: fire-risk hindcast stage (DONE, awaiting user commit)

User had committed M2 (`599664a`).

New: `pipeline/07b_fire_risk.py`, a hindcast of one season at one site (never a forecast or a probability).
- Panel (`data/fire_risk_panel.csv`, same columns as `ml/mock/fire_risk_mock.csv`): one row per cell for each pair of consecutive passes with radar data, from the second pass on. Target = any fire in the cell before the next radar pass (36 days across the Jul–Aug gap). Features known at the pass: HV index, its change since the previous radar pass, canal density, distance to the nearest earlier fire (cell centres, capped at 30 km), interval length, land cover (Model A's if 04c says `used`, else the map label). Rows stop after the cell's first fire. Rain stays in the panel for the team's notebook but is not a feature.
- Evaluation (`data/fire_risk_report.json`): last two passes locked as the test; C tuned by GroupKFold by block (PR-AUC); baselines B1 (fire within 2 km in the interval just ended), B2 (HV index rank), B3 (B1 + B2 logistic); PR-AUC, top-10% capture ranked within each pass, Brier; 1,000 block-bootstrap resamples for 95% intervals. `passed` only if the model's lower bound is above the best baseline; `not_run` if training has < 10 fires or the test has none. The lift table (fire rate by HV-index quintile) is always written.
- Checked in sklearn 1.9.1: `GridSearchCV.fit(..., groups=...)` reaches the splitter with metadata routing off; `LogisticRegression` is L2 by default and `penalty=` is deprecated, so it is not passed; no deprecation or future warnings in the run.
- Reviewed fix: a grid cell with no land class now stops the run instead of silently counting as forest.

Rain decision, with evidence (mock training rows, 5 block folds, C 0.03): adding rain leaves the mean CV PR-AUC unchanged (0.0818 with and without). Its coefficient was negative in all 5 folds here, so the earlier "sign unstable" note came from comparing two runs, not folds. Dropped anyway: it adds no ranking skill, and the real rain is one box-centre value per pass, so it can only learn timing.

Verification: `py -W error::DeprecationWarning -W error::FutureWarning pipeline/07b_fire_risk.py --self-test` passes. On `ml/mock/fire_risk_mock.csv` (simulated): **bar not passed**, as expected. Model PR-AUC 0.173 (Colab 0.145, which used C 0.3; here C 0.03), interval 0.116–0.253, below B3 0.142; B2 0.140, B1 0.047; top-10% capture 0.351 vs 0.311; test 1,869 rows / 74 fires; lift 11.9% in the lowest-index fifth vs 0% in the highest; rank correlation with Colab's test scores 0.992. A separable synthetic panel passes; a panel with no test fires gives `not_run`; the panel builder is checked on six hand-made cells (gap interval, first-fire stop, 2 km baseline, distance cap, change across the gap). `npm run typecheck` clean · `npm test` 13 files, 96 tests passed · `npm run build` ok · `npm run check-bundle` ok.

Not verified: the panel on real inputs (no parquet engine here; `context_summary.json`, `fires.parquet` and `landclass.csv` do not exist yet in `data/`).

## 2026-11-15 · M4: contract 0.2, export wiring, mock sync (DONE, awaiting user commit)

User had committed M3 (`213c7f7`) and approved contract 0.2. Two workers in parallel on separate files, both diffs reviewed.

Contract 0.2 (additive; a 0.1 bundle still loads):
- `src/contract/index.ts`: `schema_version` "0.1" or "0.2"; `COVER_IDS` (forest, degraded, plantation, built); optional `manifest.land_model {status used|not_used|simulated, version, confidence_level, reason_en, reason_id}`; optional cell `cover_set` and `map_check`; optional `scorecard.fire_risk {status passed|not_passed|not_run, test_dates, model_pr_auc, model_pr_auc_ci, best_baseline, lift}`. Zod 4 `z.enum` on a readonly array and `.optional()` checked in `schemas.d.ts`.
- `src/data/load.ts` rules (so `check-bundle` and 08_export enforce them too): a `fire_risk_capture` test exists exactly when `fire_risk.status` is passed; cells with `cover_set` or `map_check` need `land_model.status` used or simulated; `map_check` needs a one-class set.
- `docs/data-contract.md`: new "Schema 0.2 (additive)" section.

Export (`pipeline/08_export.py`):
- Reads `landclass.csv`, `landclass_report.json`, `fire_risk_report.json` and the cube's root attributes; a missing file names the stage to run.
- Land model used: each cell's class becomes `class_model`, plus `cover_set` and `map_check` (the map's label on flagged cells); scorecard adds `land_model_coverage` and `map_out_of_date`. Not used: map classes, no sets, and `land_model.reason_en/id` lists why. The scorecard is computed after the swap.
- `scorecard.fire_risk` copied from the 07b report; `fire_risk_capture` added only when the bar is passed, worded "Hindcast of the 2026 season at one site, not a forecast."
- Guards: refuses a cube not marked `data_source: "asf_live_stream"` (today's cube has no mark and is dry-run output, so it is refused); refuses `class_source` and the land report disagreeing in either direction (the reverse check was added in review).

`pipeline/01_fetch.py`: cubes carry `data_source` (`asf_live_stream` live, `synthetic_dry_run` for `--dry-run`; a merge of mixed batches is `mixed`, which 08 refuses). Checked by reading and compiling only (no xarray or h5py here).

Mock generator: `schema_version` 0.2; `land_model.status "simulated"` with a plain note; every cell has a simulated `cover_set` from its own random stream (seed + 101), so all earlier values and every PNG are byte-identical: 180 empty sets (2.9%), 503 two-class (8.1%), 102 `map_check` (1.8% of one-class cells). `fire_risk.status "not_run"` (no model runs on simulated data) with an honest lift table from the mock series using 07b's panel rule: test passes 6 and 18 Oct; fire rate 5.6% in the lowest HV-index fifth down to 0.6% in the highest. Equal HV values are split by row order (pandas qcut would keep them together); marked as a shortcut.

Verification: self-tests pass for 04b, 04c, 07b, 07_states (14/14) and 08_export (now including land model used and not used, fire passed/not_passed/not_run, both guards, and the app loader on the 0.2 bundle) · `py -m py_compile pipeline/01_fetch.py` ok · `npm run typecheck` clean · `npm test` 13 files, 106 tests passed · `npm run build` ok · `npm run mock` twice gives identical files · `npm run check-bundle` ok on the new mock bundle (data 3.36 MB, images 5.51 MB) and on a copy with the 0.1 manifest, cells and scorecard from the last commit (3.20 MB).

Not verified: 01_fetch's new attribute on a live or dry run; 08_export on real stage outputs. The app does not show the new fields yet (M5).
