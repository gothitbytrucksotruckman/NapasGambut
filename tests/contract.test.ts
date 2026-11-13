import { describe, expect, it } from 'vitest';
import { CellsSchema, ManifestSchema, SeriesSchema, STATE } from '../src/contract';

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

  it('rejects an unknown schema_version', () => {
    expect(ManifestSchema.safeParse({ ...minimalManifest, schema_version: '0.2' }).success).toBe(false);
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
