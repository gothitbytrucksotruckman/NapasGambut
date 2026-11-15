// Entry point: npm run mock [-- --seed N] [--out DIR]. Writes the full bundle (PRD 5) deterministically.
import { createHash } from 'node:crypto';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  BUNDLE_FILES, CellsSchema, ContextFeaturesSchema, ContextSchema, ManifestSchema, ScorecardSchema, SeriesSchema, STATE,
  type ClassId, type CoverId, type Manifest,
} from '../../src/contract';
import { droppedPng, opticalHazePng, radarPng } from './images';
import { BBOX, buildLandscape, canalId, GRID } from './landscape';
import { mulberry32, type Rng } from './rng';
import { buildScorecard, mockFireRisk } from './scorecard';
import { DATES, DROPPED_DATE, DROPPED_INDEX, RAIN_RETURN_MM, simulateRain } from './season';
import { simulateSignals } from './signals';
import { classifyCell } from './states';
import { mad, round } from './stats';

export const DEFAULT_SEED = 20261114;
export const GENERATOR_VERSION = '0.1.0';
const REVEAL_DATE = '2026-09-24';
const K = { change: 2, headline: 3, deep: 4 };

const STATE_LABELS: [keyof typeof STATE, string, string][] = [
  ['no_data', 'No data', 'Tidak ada data'],
  ['fire_radar', 'Fire, radar agrees', 'Api, radar mendeteksi'],
  ['fire_silent', 'Fire, radar silent', 'Api, radar tidak mendeteksi'],
  ['burned', 'Burned', 'Terbakar'],
  ['rewetting', 'Re-wetting', 'Membasah kembali'],
  ['deep_drying', 'Deep drying', 'Mengering parah'],
  ['drying', 'Drying', 'Mengering'],
  ['stable', 'Stable', 'Stabil'],
];
const CLASS_LABELS = [
  ['drained', 'Drained peat', 'Gambut terdrainase'],
  ['rewetted', 'Rewetted peat', 'Gambut yang dibasahi kembali'],
  ['plantation', 'Plantation on peat', 'Perkebunan di atas gambut'],
  ['intact_forest', 'Intact peat swamp forest', 'Hutan rawa gambut utuh'],
  ['reference_forest', 'Reference forest (mineral soil)', 'Hutan acuan (tanah mineral)'],
  ['settlement', 'Settlement', 'Permukiman'],
] as const;

const BASE_COVER: Record<ClassId, CoverId> = {
  drained: 'degraded', rewetted: 'degraded', plantation: 'plantation',
  intact_forest: 'forest', reference_forest: 'forest', settlement: 'built',
};
// The class each cover is usually confused with; degraded's partner is taken as forest.
const CONFUSED: Record<CoverId, CoverId> = { forest: 'degraded', plantation: 'degraded', built: 'degraded', degraded: 'forest' };

/** Simulated land-model output (schema 0.2): ~3% empty sets, ~8% two-class sets, ~2% of single sets flagged by map_check. */
export function simulateCoverSets(rng: Rng, classes: ClassId[]): { cover_set: CoverId[]; map_check?: CoverId }[] {
  return classes.map((cls) => {
    const base = BASE_COVER[cls], u = rng(), v = rng();
    if (u < 0.03) return { cover_set: [] };
    if (u < 0.11) return { cover_set: [base, CONFUSED[base]] };
    return v < 0.02 ? { cover_set: [base], map_check: CONFUSED[base] } : { cover_set: [base] };
  });
}

export function generateBundle(seed: number): Map<string, Buffer> {
  const land = buildLandscape(mulberry32(seed));
  const rain = simulateRain(mulberry32(seed + 1));
  const sig = simulateSignals(mulberry32(seed + 2), land);
  const T = DATES.length;
  const dropped = DATES.map((d) => d === DROPPED_DATE);

  // Noise floor per date from reference forest (PRD 6.5).
  const refIdx = land.cells.map((c, i) => (c.cls === 'reference_forest' ? i : -1)).filter((i) => i >= 0);
  const sigma = DATES.map((_, t) =>
    t === 0 || dropped[t] ? null : round(1.4826 * mad(refIdx.map((i) => sig.D[i][t]!)), 3),
  );

  // Quantise first, then classify on the quantised values, so the app and the rules see the same numbers.
  const tenths = (v: number | null) => (v === null ? null : Math.round(v * 10));
  const hh = sig.D.map((r) => r.map(tenths));
  const hv = sig.hv.map((r) => r.map(tenths));
  const coh = sig.coh.map((r) => r.map((v) => (v === null ? null : Math.round(v))));
  const Ddb = hh.map((r) => r.map((v) => (v === null ? null : v / 10)));
  const state = land.cells.map((c, i) =>
    classifyCell({
      D: Ddb[i],
      hv: hv[i].map((v) => (v === null ? null : v / 10)),
      coh: coh[i],
      fires: sig.fires[i],
      nPixels: c.nPixels,
      dropped,
      sigma,
      rainInterval: rain.rainInterval,
      k: { change: K.change, deep: K.deep, rainReturn: RAIN_RETURN_MM },
    }),
  );

  const peakIndex = DATES.indexOf('2026-10-06');
  const scorecard = { ...buildScorecard({ land, D: Ddb, states: state, dates: DATES, peakIndex }), fire_risk: mockFireRisk(hv, sig.fires, DATES, dropped) };
  const covers = simulateCoverSets(mulberry32(seed + 101), land.cells.map((c) => c.cls));

  const imgFile = (d: string) => `images/radar_${d}.png`;
  const [w, s, e, n] = BBOX;
  const manifest: Manifest = {
    schema_version: '0.2',
    data_kind: 'mock',
    generated_at: `${DATES[T - 1]}T00:00:00Z`, // fixed, not wall clock, so output is byte-identical per seed
    generator: { name: 'napas-gambut-mock', version: GENERATOR_VERSION, seed },
    study_area: {
      name_en: 'Central Kalimantan peat landscape (simulated)',
      name_id: 'Lanskap gambut Kalimantan Tengah (simulasi)',
      bbox: BBOX,
      cell_size_m: 500,
    },
    geometry: { track: null, frame: null, direction: null },
    dates: DATES,
    dropped_dates: [
      {
        date: DROPPED_DATE,
        reason_en: 'Simulated quality failure: partial coverage',
        reason_id: 'Kegagalan kualitas simulasi: cakupan sebagian', // REVIEW
      },
    ],
    scenes: [],
    thresholds: { sigma_db: sigma, change_k: K.change, headline_k: K.headline, deep_k: K.deep, rain_return_mm: RAIN_RETURN_MM },
    classes: CLASS_LABELS.map(([id, label_en, label_id]) => ({ id, label_en, label_id })),
    states: STATE_LABELS.map(([key, label_en, label_id]) => ({ code: STATE[key], key, label_en, label_id })),
    images: {
      bounds: [[w, n], [e, n], [e, s], [w, s]],
      radar: DATES.map((date) => ({ date, file: imgFile(date) })),
      reveal: { date: REVEAL_DATE, optical_file: 'images/reveal_optical.png', radar_file: 'images/reveal_radar.png' },
    },
    sources: [
      {
        name: 'NISAR L-band SAR (NASA-ISRO), via ASF DAAC',
        url: 'https://asf.alaska.edu/nisar/',
        role_en: 'Planned radar source. Not used in this simulated bundle.',
        role_id: 'Sumber radar yang direncanakan. Tidak dipakai dalam paket simulasi ini.', // REVIEW
      },
      {
        name: 'NASA FIRMS active fire data',
        url: 'https://firms.modaps.eosdis.nasa.gov/',
        role_en: 'Planned fire detection source. Fire counts here are simulated.',
        role_id: 'Sumber deteksi api yang direncanakan. Jumlah api di sini adalah simulasi.', // REVIEW
      },
      {
        name: 'CHIRPS rainfall',
        url: 'https://www.chc.ucsb.edu/data/chirps',
        role_en: 'Planned rainfall source. Rain values here are simulated.',
        role_id: 'Sumber curah hujan yang direncanakan. Nilai hujan di sini adalah simulasi.', // REVIEW
      },
      {
        name: 'OpenStreetMap',
        url: 'https://www.openstreetmap.org/copyright',
        role_en: 'Basemap tiles (optional, greyed behind the cells).',
        role_id: 'Ubin peta dasar (opsional, dibuat abu-abu di belakang sel).', // REVIEW
      },
    ],
    land_model: {
      status: 'simulated',
      version: 'mock',
      confidence_level: 0.9,
      reason_en: 'Simulated bundle: the class sets are generated by the script; no land model was trained.',
      reason_id: 'Bundel simulasi: himpunan kelas dibuat oleh skrip; tidak ada model tutupan lahan yang dilatih.', // REVIEW
    },
  };

  const half = GRID.deg / 2;
  const cells = {
    type: 'FeatureCollection' as const,
    features: land.cells.map((c, i) => {
      const [x, y] = c.centroid;
      const r5 = (v: number) => Math.round(v * 1e5) / 1e5;
      return {
        type: 'Feature' as const,
        geometry: {
          type: 'Polygon' as const,
          coordinates: [[[r5(x - half), r5(y + half)], [r5(x + half), r5(y + half)], [r5(x + half), r5(y - half)], [r5(x - half), r5(y - half)], [r5(x - half), r5(y + half)]]],
        },
        properties: {
          id: c.id, row: c.row, col: c.col, class: c.cls,
          canal_density_km_per_km2: c.canalDensity, tree_cover_pct: c.treeCover, n_pixels: c.nPixels, centroid: c.centroid,
          ...covers[i],
        },
      };
    }),
  };

  const props = (
    kind: 'canal' | 'river' | 'dam' | 'town',
    name_en: string | null = null,
    name_id: string | null = null,
    id?: string,
  ) => (id ? { id, kind, name_en, name_id } : { kind, name_en, name_id });
  const contextFeatures = {
    type: 'FeatureCollection' as const,
    features: [
      ...land.canals.map((coordinates, idx) => ({
        type: 'Feature' as const,
        geometry: { type: 'LineString' as const, coordinates },
        properties: props('canal', `Canal #${idx + 1}`, `Kanal #${idx + 1}`, canalId(idx)),
      })),
      { type: 'Feature' as const, geometry: { type: 'LineString' as const, coordinates: land.river }, properties: props('river', 'River (simulated)', 'Sungai (simulasi)') },
      ...land.dams.map((coordinates) => ({ type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates }, properties: props('dam') })),
      { type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: land.town }, properties: props('town', 'Town (simulated)', 'Kota (simulasi)') },
    ],
  };

  const series = { dates: DATES, cells: land.cells.map((c) => c.id), hh, hv, coh, fires: sig.fires, state };
  const context = {
    dates: DATES,
    rain_3day_mm: rain.rain3day,
    rain_interval_mm: rain.rainInterval,
    fires_region: DATES.slice(1).map((_, k) => sig.fires.reduce((a, row) => a + row[k], 0)),
    quality: DATES.map((d) => (d === DROPPED_DATE ? 'dropped' : 'ok')) as ('ok' | 'dropped')[],
  };

  const out = new Map<string, Buffer>();
  const json = (name: string, v: unknown) => out.set(name, Buffer.from(JSON.stringify(v)));
  json(BUNDLE_FILES.manifest, manifest);
  json(BUNDLE_FILES.cells, cells);
  json(BUNDLE_FILES.contextFeatures, contextFeatures);
  json(BUNDLE_FILES.series, series);
  json(BUNDLE_FILES.context, context);
  json(BUNDLE_FILES.scorecard, scorecard);

  const imgRng = mulberry32(seed + 3);
  DATES.forEach((d, t) => {
    out.set(imgFile(d), t === DROPPED_INDEX ? droppedPng() : radarPng(imgRng, land, Ddb.map((r) => r[t])));
  });
  const revealT = DATES.indexOf(REVEAL_DATE);
  out.set('images/reveal_radar.png', out.get(imgFile(REVEAL_DATE))!);
  const revealFires = land.cells.map((_, i) => i).filter((i) => {
    const k = sig.fireInterval.get(i);
    return k !== undefined && k <= revealT - 1 && k >= revealT - 3;
  });
  out.set('images/reveal_optical.png', opticalHazePng(mulberry32(seed + 4), land, revealFires));

  checkBundle(out);
  return out;
}

/** PRD 6.9: fail loudly on any contract or budget violation. */
export function checkBundle(files: Map<string, Buffer>) {
  const parse = <T>(name: string, schema: { safeParse: (v: unknown) => { success: boolean; data?: T; error?: { issues: { path: PropertyKey[]; message: string }[] } } }) => {
    const r = schema.safeParse(JSON.parse(files.get(name)!.toString()));
    if (!r.success) {
      const i = r.error!.issues[0];
      throw new Error(`${name}: ${i.path.join('.')} ${i.message}`);
    }
    return r.data as T;
  };
  const m = parse<Manifest>(BUNDLE_FILES.manifest, ManifestSchema);
  const cells = parse<{ features: unknown[] }>(BUNDLE_FILES.cells, CellsSchema);
  parse(BUNDLE_FILES.contextFeatures, ContextFeaturesSchema);
  const s = parse<{ dates: string[]; cells: string[]; hh: unknown[][]; hv: unknown[][]; coh: unknown[][]; fires: unknown[][]; state: number[][] }>(BUNDLE_FILES.series, SeriesSchema);
  const ctx = parse<{ dates: string[]; rain_3day_mm: unknown[]; rain_interval_mm: unknown[]; fires_region: unknown[]; quality: unknown[] }>(BUNDLE_FILES.context, ContextSchema);
  parse(BUNDLE_FILES.scorecard, ScorecardSchema);

  const T = m.dates.length, n = s.cells.length;
  const fail = (msg: string) => { throw new Error(`bundle check failed: ${msg}`); };
  if (JSON.stringify(s.dates) !== JSON.stringify(m.dates)) fail('series.dates differs from manifest.dates');
  if (JSON.stringify(ctx.dates) !== JSON.stringify(m.dates)) fail('context.dates differs from manifest.dates');
  if (cells.features.length !== n) fail(`cells.geojson has ${cells.features.length} features, series has ${n} cells`);
  if (m.thresholds.sigma_db.length !== T) fail('thresholds.sigma_db length');
  for (const [key, len] of [['hh', T], ['hv', T], ['state', T], ['coh', T - 1], ['fires', T - 1]] as const) {
    const arr = s[key];
    if (arr.length !== n) fail(`series.${key} has ${arr.length} rows, expected ${n}`);
    arr.forEach((row, i) => { if (row.length !== len) fail(`series.${key}[${i}] has ${row.length} entries, expected ${len}`); });
  }
  if (ctx.rain_3day_mm.length !== T || ctx.quality.length !== T) fail('context per-date arrays length');
  if (ctx.rain_interval_mm.length !== T - 1 || ctx.fires_region.length !== T - 1) fail('context per-interval arrays length');

  const burned = s.state.filter((row) => row.some((v) => v === STATE.fire_radar || v === STATE.fire_silent)).length / n;
  if (burned < 0.04 || burned > 0.12) fail(`burned share ${(burned * 100).toFixed(1)}% outside 4-12%`);

  let jsonBytes = 0, imgBytes = 0;
  for (const [name, buf] of files) name.endsWith('.png') ? (imgBytes += buf.length) : (jsonBytes += buf.length);
  if (jsonBytes > 6e6) fail(`non-image files are ${(jsonBytes / 1e6).toFixed(2)} MB, over 6 MB`);
  if (imgBytes > 10e6) fail(`images are ${(imgBytes / 1e6).toFixed(2)} MB, over 10 MB`);
}

export const sha256 = (b: Buffer) => createHash('sha256').update(b).digest('hex');

function main() {
  const args = process.argv.slice(2);
  const arg = (flag: string) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : undefined; };
  const seed = Number(arg('--seed') ?? DEFAULT_SEED);
  if (!Number.isInteger(seed)) throw new Error('--seed must be an integer');
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const outDir = resolve(arg('--out') ?? join(root, 'public/bundle'));

  const files = generateBundle(seed);
  rmSync(outDir, { recursive: true, force: true });
  let json = 0, img = 0;
  for (const [name, buf] of files) {
    mkdirSync(dirname(join(outDir, name)), { recursive: true });
    writeFileSync(join(outDir, name), buf);
    name.endsWith('.png') ? (img += buf.length) : (json += buf.length);
  }
  console.log(`seed ${seed}: wrote ${files.size} files to ${outDir}`);
  console.log(`  data ${(json / 1e6).toFixed(2)} MB, images ${(img / 1e6).toFixed(2)} MB`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
