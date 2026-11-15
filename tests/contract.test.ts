import { describe, expect, it } from 'vitest';
import { CellsSchema, ContextFeaturesSchema, ManifestSchema, ScorecardSchema, SeriesSchema, STATE } from '../src/contract';

export const minimalManifest = {
  schema_version: '0.1',
  data_kind: 'mock',
  generated_at: '2026-11-11T00:00:00Z',
  generator: { name: 'napas-gambut-mock', version: '0.1.0', seed: 1 },
  study_area: { name_en: 'x', name_id: 'x', bbox: [113.9, -2.95, 114.26, -2.59], cell_size_m: 500 },
  geometry: { track: null, frame: null, direction: null },
  dates: ['2026-06-20', '2026-07-02'],
  dropped_dates: [],
  scenes: [],
  thresholds: { sigma_db: [null, 0.2], change_k: 2, headline_k: 3, deep_k: 4, rain_return_mm: 50 },
  classes: [{ id: 'drained', label_en: 'Drained peat', label_id: 'Gambut terdrainase' }],
  states: [{ code: 1, key: 'no_data', label_en: 'No data', label_id: 'Tidak ada data' }],
  images: {
    bounds: [[113.9, -2.59], [114.26, -2.59], [114.26, -2.95], [113.9, -2.95]],
    radar: [{ date: '2026-06-20', file: 'images/radar_2026-06-20.png' }],
    reveal: { date: '2026-06-20', optical_file: 'images/reveal_optical.png', radar_file: 'images/reveal_radar.png' },
  },
  sources: [],
};

describe('contract schemas', () => {
  it('accepts a minimal valid manifest', () => {
    expect(ManifestSchema.safeParse(minimalManifest).success).toBe(true);
  });

  it('accepts schema_version 0.1 and 0.2 and rejects unknown versions', () => {
    expect(ManifestSchema.safeParse({ ...minimalManifest, schema_version: '0.1' }).success).toBe(true);
    expect(ManifestSchema.safeParse({ ...minimalManifest, schema_version: '0.2' }).success).toBe(true);
    expect(ManifestSchema.safeParse({ ...minimalManifest, schema_version: '0.3' }).success).toBe(false);
  });

  it('allows optional canal id on context features and optional rankings.canals on scorecard', () => {
    const cf = {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: { type: 'LineString', coordinates: [[114.0, -2.0], [114.01, -2.0]] }, properties: { kind: 'canal', name_en: null, name_id: null } },
        { type: 'Feature', geometry: { type: 'LineString', coordinates: [[114.0, -2.01], [114.01, -2.01]] }, properties: { id: 'osm:123456', kind: 'canal', name_en: 'Canal A', name_id: 'Kanal A' } },
      ],
    };
    expect(ContextFeaturesSchema.safeParse(cf).success).toBe(true);

    const baseScorecard = {
      by_class: [],
      rankings: { fastest_drying: [], dams_to_inspect: [] },
      tests: [],
    };
    expect(ScorecardSchema.safeParse(baseScorecard).success).toBe(true);
    const v2Scorecard = {
      ...baseScorecard,
      rankings: {
        ...baseScorecard.rankings,
        canals: [{ canal: 'osm:123456', name_en: 'Canal A', name_id: 'Kanal A', length_km: 1.1, n_cells: 4, median_min_hh_db: -2.4, n_burned_cells: 1 }],
      },
    };
    expect(ScorecardSchema.safeParse(v2Scorecard).success).toBe(true);
  });

  it('rejects NaN in series values', () => {
    const s = { dates: ['2026-06-20'], cells: ['r000c000'], hh: [[NaN]], hv: [[0]], coh: [[]], fires: [[]], state: [[8]] };
    expect(SeriesSchema.safeParse(s).success).toBe(false);
  });

  it('rejects cell ids without three-digit padding', () => {
    const s = { dates: ['2026-06-20'], cells: ['r12c34'], hh: [[0]], hv: [[0]], coh: [[]], fires: [[]], state: [[8]] };
    expect(SeriesSchema.safeParse(s).success).toBe(false);
  });

  it('rejects a cell feature with an unknown class', () => {
    const fc = {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
        properties: { id: 'r000c000', row: 0, col: 0, class: 'swamp', canal_density_km_per_km2: 0, tree_cover_pct: 0, n_pixels: 625, centroid: [0, 0] },
      }],
    };
    expect(CellsSchema.safeParse(fc).success).toBe(false);
  });

  it('exposes the eight state codes in rule order', () => {
    expect(Object.values(STATE)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });
});
