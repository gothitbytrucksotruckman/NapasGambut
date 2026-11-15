// Loads the bundle (PRD 7.1): fetch all files in parallel, validate each, cross-check alignment.
import type { z } from 'zod';
import {
  BUNDLE_FILES, CellsSchema, ContextFeaturesSchema, ContextSchema, ManifestSchema, ScorecardSchema, SeriesSchema,
  type CellFeature, type Cells, type Context, type ContextFeatures, type Manifest, type Scorecard, type Series,
} from '../contract';

export class BundleError extends Error {
  constructor(readonly file: string, readonly field: string, readonly detail: string) {
    super(`${file}${field ? ` → ${field}` : ''}: ${detail}`);
    this.name = 'BundleError';
  }
}

export interface Bundle {
  manifest: Manifest;
  cells: Cells;
  contextFeatures: ContextFeatures;
  series: Series;
  context: Context;
  scorecard: Scorecard;
  idx: { cell: Map<string, number>; feature: Map<string, CellFeature>; date: Map<string, number> };
  imageUrl: (file: string) => string;
}

/** zod path ['hh', 3, 0] → "hh[3][0]" */
const fieldOf = (path: PropertyKey[]) =>
  path.reduce<string>((s, p) => (typeof p === 'number' ? `${s}[${p}]` : s ? `${s}.${String(p)}` : String(p)), '');

async function fetchJson(base: string, file: string, fetchFn: typeof fetch): Promise<unknown> {
  let res: Response;
  try {
    res = await fetchFn(base + file);
  } catch (e) {
    throw new BundleError(file, '', `could not be fetched (${(e as Error).message})`);
  }
  if (!res.ok) throw new BundleError(file, '', `HTTP ${res.status}`);
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new BundleError(file, '', 'is not valid JSON');
  }
}

function validate<S extends z.ZodType>(file: string, schema: S, raw: unknown): z.infer<S> {
  const r = schema.safeParse(raw);
  if (r.success) return r.data;
  const issue = r.error.issues[0];
  throw new BundleError(file, fieldOf(issue.path), issue.message);
}

export async function loadBundle(baseUrl: string, fetchFn: typeof fetch = fetch): Promise<Bundle> {
  const base = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`;
  const f = BUNDLE_FILES;
  const [m, c, cf, s, ctx, sc] = await Promise.all(
    [f.manifest, f.cells, f.contextFeatures, f.series, f.context, f.scorecard].map((file) => fetchJson(base, file, fetchFn)),
  );
  const manifest = validate(f.manifest, ManifestSchema, m);
  const cells = validate(f.cells, CellsSchema, c);
  const contextFeatures = validate(f.contextFeatures, ContextFeaturesSchema, cf);
  const series = validate(f.series, SeriesSchema, s);
  const context = validate(f.context, ContextSchema, ctx);
  const scorecard = validate(f.scorecard, ScorecardSchema, sc);

  // Alignment checks the schemas cannot express.
  const T = manifest.dates.length;
  const same = (a: string[]) => a.length === T && a.every((d, i) => d === manifest.dates[i]);
  if (!same(series.dates)) throw new BundleError(f.series, 'dates', 'must equal manifest.dates');
  if (!same(context.dates)) throw new BundleError(f.context, 'dates', 'must equal manifest.dates');
  if (manifest.thresholds.sigma_db.length !== T) throw new BundleError(f.manifest, 'thresholds.sigma_db', `needs ${T} entries`);
  const n = series.cells.length;
  const perDate = ['hh', 'hv', 'state'] as const, perInterval = ['coh', 'fires'] as const;
  for (const key of [...perDate, ...perInterval]) {
    const want = (perDate as readonly string[]).includes(key) ? T : T - 1;
    const rows = series[key];
    if (rows.length !== n) throw new BundleError(f.series, key, `has ${rows.length} rows, expected ${n} (one per cell)`);
    rows.forEach((row, i) => {
      if (row.length !== want) throw new BundleError(f.series, `${key}[${i}]`, `has ${row.length} entries, expected ${want}`);
    });
  }
  for (const key of ['rain_3day_mm', 'quality'] as const)
    if (context[key].length !== T) throw new BundleError(f.context, key, `needs ${T} entries`);
  for (const key of ['rain_interval_mm', 'fires_region'] as const)
    if (context[key].length !== T - 1) throw new BundleError(f.context, key, `needs ${T - 1} entries`);

  // Schema 0.2 cross-file rules.
  const passed = scorecard.fire_risk?.status === 'passed';
  if (passed !== scorecard.tests.some((t) => t.id === 'fire_risk_capture'))
    throw new BundleError(f.scorecard, passed ? 'tests' : 'fire_risk.status',
      'a fire_risk_capture test must be present exactly when fire_risk.status is passed');
  const lmStatus = manifest.land_model?.status;
  cells.features.forEach(({ properties: p }, i) => {
    if ((p.cover_set || p.map_check) && lmStatus !== 'used' && lmStatus !== 'simulated')
      throw new BundleError(f.manifest, 'land_model.status', `must be used or simulated when cells carry cover_set or map_check (features[${i}])`);
    if (p.map_check && p.cover_set?.length !== 1)
      throw new BundleError(f.cells, `features[${i}].properties.cover_set`, 'must hold exactly one class when map_check is set');
  });

  const cell = new Map(series.cells.map((id, i) => [id, i]));
  const feature = new Map<string, CellFeature>();
  for (const ft of cells.features) if (cell.has(ft.properties.id)) feature.set(ft.properties.id, ft);
  const date = new Map(manifest.dates.map((d, i) => [d, i]));

  return {
    manifest, cells, contextFeatures, series, context, scorecard,
    idx: { cell, feature, date },
    imageUrl: (file) => base + file,
  };
}
