// Data contract, PRD section 5. Mirrored in docs/data-contract.md; change both together.
import { z } from 'zod';

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'expected YYYY-MM-DD');
const cellId = z.string().regex(/^r\d{3}c\d{3}$/, 'expected a cell id like r012c034');
const lonLat = z.tuple([z.number(), z.number()]);

export const STATE = {
  no_data: 1,
  fire_radar: 2,
  fire_silent: 3,
  burned: 4,
  rewetting: 5,
  deep_drying: 6,
  drying: 7,
  stable: 8,
} as const;
export type StateKey = keyof typeof STATE;
export type StateCode = (typeof STATE)[StateKey];

export const CLASS_IDS = ['drained', 'rewetted', 'plantation', 'intact_forest', 'reference_forest', 'settlement'] as const;
export type ClassId = (typeof CLASS_IDS)[number];

// Schema 0.2: land cover as the radar land model sees it (coarser than CLASS_IDS).
export const COVER_IDS = ['forest', 'degraded', 'plantation', 'built'] as const;
export type CoverId = (typeof COVER_IDS)[number];

export const BUNDLE_FILES = {
  manifest: 'manifest.json',
  cells: 'cells.geojson',
  contextFeatures: 'context_features.geojson',
  series: 'series.json',
  context: 'context.json',
  scorecard: 'scorecard.json',
} as const;

// 5.4
export const ManifestSchema = z.object({
  schema_version: z.enum(['0.1', '0.2']),
  data_kind: z.enum(['mock', 'nisar']),
  generated_at: z.string(),
  generator: z.object({ name: z.string(), version: z.string(), seed: z.number().nullable() }),
  study_area: z.object({
    name_en: z.string(),
    name_id: z.string(),
    bbox: z.tuple([z.number(), z.number(), z.number(), z.number()]),
    cell_size_m: z.number(),
  }),
  geometry: z.object({
    track: z.number().nullable(),
    frame: z.number().nullable(),
    direction: z.enum(['A', 'D']).nullable(),
  }),
  dates: z.array(isoDate).min(1),
  dropped_dates: z.array(z.object({ date: isoDate, reason_en: z.string(), reason_id: z.string() })),
  scenes: z.array(z.object({ date: isoDate, name: z.string(), version: z.string() })),
  thresholds: z.object({
    sigma_db: z.array(z.number().nullable()),
    change_k: z.number(),
    headline_k: z.number(),
    deep_k: z.number(),
    rain_return_mm: z.number(),
  }),
  classes: z.array(z.object({ id: z.string(), label_en: z.string(), label_id: z.string() })),
  states: z.array(z.object({ code: z.number().int(), key: z.string(), label_en: z.string(), label_id: z.string() })),
  images: z.object({
    bounds: z.tuple([lonLat, lonLat, lonLat, lonLat]),
    radar: z.array(z.object({ date: isoDate, file: z.string() })),
    reveal: z.object({ date: isoDate, optical_file: z.string(), radar_file: z.string() }),
  }),
  sources: z.array(z.object({ name: z.string(), url: z.string(), role_en: z.string(), role_id: z.string() })),
  // 0.2. used = cells.class came from the radar land model; simulated = mock bundle, no model trained.
  land_model: z
    .object({
      status: z.enum(['used', 'not_used', 'simulated']),
      version: z.string(),
      confidence_level: z.number(),
      reason_en: z.string().nullable(),
      reason_id: z.string().nullable(),
    })
    .optional(),
});
export type Manifest = z.infer<typeof ManifestSchema>;

// 5.5
export const CellPropertiesSchema = z.object({
  id: cellId,
  row: z.number().int(),
  col: z.number().int(),
  class: z.enum(CLASS_IDS),
  canal_density_km_per_km2: z.number(),
  tree_cover_pct: z.number().min(0).max(100),
  n_pixels: z.number().int(),
  centroid: lonLat,
  // 0.2. The radar's conformal class set at manifest.land_model.confidence_level; [] = the radar can't tell.
  cover_set: z.array(z.enum(COVER_IDS)).optional(),
  // 0.2. Only on flagged cells: what the older map says where the radar confidently disagrees (the radar's class is cover_set[0]).
  map_check: z.enum(COVER_IDS).optional(),
});
export type CellProperties = z.infer<typeof CellPropertiesSchema>;

const CellFeatureSchema = z.object({
  type: z.literal('Feature'),
  geometry: z.object({ type: z.literal('Polygon'), coordinates: z.array(z.array(lonLat)) }),
  properties: CellPropertiesSchema,
});
export type CellFeature = z.infer<typeof CellFeatureSchema>;

export const CellsSchema = z.object({ type: z.literal('FeatureCollection'), features: z.array(CellFeatureSchema) });
export type Cells = z.infer<typeof CellsSchema>;

// 5.6
const ContextPropsSchema = z.object({
  id: z.string().min(1).optional(),
  kind: z.enum(['canal', 'river', 'dam', 'town']),
  name_en: z.string().nullable(),
  name_id: z.string().nullable(),
});
export const ContextFeaturesSchema = z.object({
  type: z.literal('FeatureCollection'),
  features: z.array(
    z.object({
      type: z.literal('Feature'),
      geometry: z.union([
        z.object({ type: z.literal('LineString'), coordinates: z.array(lonLat) }),
        z.object({ type: z.literal('Point'), coordinates: lonLat }),
      ]),
      properties: ContextPropsSchema,
    }),
  ),
});
export type ContextFeatures = z.infer<typeof ContextFeaturesSchema>;

// 5.7
const intOrNull = z.number().int().nullable();
export const SeriesSchema = z.object({
  dates: z.array(isoDate),
  cells: z.array(cellId),
  hh: z.array(z.array(intOrNull)),
  hv: z.array(z.array(intOrNull)),
  coh: z.array(z.array(z.number().int().min(0).max(100).nullable())),
  fires: z.array(z.array(z.number().int().min(0).nullable())),
  state: z.array(z.array(z.number().int().min(1).max(8))),
});
export type Series = z.infer<typeof SeriesSchema>;

// 5.8
export const ContextSchema = z.object({
  dates: z.array(isoDate),
  rain_3day_mm: z.array(z.number().nullable()),
  rain_interval_mm: z.array(z.number().nullable()),
  fires_region: z.array(z.number()),
  quality: z.array(z.enum(['ok', 'dropped'])),
});
export type Context = z.infer<typeof ContextSchema>;

// 5.9
export const CanalRankingSchema = z.object({
  canal: z.string().min(1),
  name_en: z.string(),
  name_id: z.string(),
  length_km: z.number(),
  n_cells: z.number().int().positive(),
  median_min_hh_db: z.number(),
  n_burned_cells: z.number().int().nonnegative(),
});
export type CanalRanking = z.infer<typeof CanalRankingSchema>;

// 0.2: a hindcast of one season at one site; quintile 1 = lowest HV index.
const FireRiskSchema = z.object({
  status: z.enum(['passed', 'not_passed', 'not_run']),
  test_dates: z.array(isoDate),
  model_pr_auc: z.number().nullable(),
  model_pr_auc_ci: z.tuple([z.number(), z.number()]).nullable(),
  best_baseline: z.object({ id: z.enum(['B1', 'B2', 'B3']), pr_auc: z.number() }).nullable(),
  lift: z.array(
    z.object({
      quintile: z.number().int().min(1).max(5),
      n: z.number().int(),
      fires: z.number().int(),
      rate: z.number().min(0).max(1),
    }),
  ),
});

export const ScorecardSchema = z.object({
  by_class: z.array(
    z.object({
      class: z.string(),
      n_cells: z.number().int(),
      median_min_hh_db: z.number(),
      p25_min_hh_db: z.number(),
      p75_min_hh_db: z.number(),
      share_burned: z.number().min(0).max(1),
      median_passes_to_recovery: z.number().nullable(),
    }),
  ),
  rankings: z.object({
    fastest_drying: z.array(
      z.object({ cell: cellId, class: z.string(), min_hh_db: z.number(), date_of_min: isoDate }),
    ),
    dams_to_inspect: z.array(z.object({ cell: cellId, min_hh_db: z.number(), gap_vs_drained_median_db: z.number() })),
    canals: z.array(CanalRankingSchema).max(20).optional(),
  }),
  // 0.2 adds ids: fire_risk_capture (only when fire_risk.status is passed),
  // land_model_coverage and map_out_of_date (only when manifest.land_model.status is used).
  tests: z.array(
    z.object({
      id: z.string(),
      name_en: z.string(),
      name_id: z.string(),
      statistic: z.string(),
      value: z.number(),
      n: z.number().int(),
      note_en: z.string(),
      note_id: z.string(),
    }),
  ),
  fire_risk: FireRiskSchema.optional(),
});
export type Scorecard = z.infer<typeof ScorecardSchema>;
