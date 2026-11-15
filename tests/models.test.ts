import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { CellProperties, Manifest, Scorecard } from '../src/contract';
import { coverView, fireRiskView, landCoverageTest } from '../src/data/models';
import { en } from '../src/i18n/en';

const sc: Scorecard = JSON.parse(readFileSync(join(__dirname, '../public/bundle/scorecard.json'), 'utf8'));

const cell = (extra: Partial<CellProperties> = {}): CellProperties => ({
  id: 'r000c000', row: 0, col: 0, class: 'drained', canal_density_km_per_km2: 1, tree_cover_pct: 10, n_pixels: 625,
  centroid: [0, 0], ...extra,
});
const lm = (status: 'used' | 'not_used' | 'simulated'): Manifest['land_model'] =>
  ({ status, version: 'x', confidence_level: 0.9, reason_en: null, reason_id: null });

describe('coverView', () => {
  it('sorts one, several and cant_tell', () => {
    expect(coverView(cell({ cover_set: ['plantation'] }), lm('used'))).toEqual({ kind: 'one', covers: ['plantation'], mapCheck: null, simulated: false });
    expect(coverView(cell({ cover_set: ['forest', 'degraded'] }), lm('used'))?.kind).toBe('several');
    expect(coverView(cell({ cover_set: [] }), lm('used'))?.kind).toBe('cant_tell');
  });
  it('pairs the map class with the radar class and flags simulated bundles', () => {
    const v = coverView(cell({ cover_set: ['degraded', 'forest'], map_check: 'forest' }), lm('simulated'));
    expect(v?.mapCheck).toEqual({ map: 'forest', radar: 'degraded' });
    expect(v?.simulated).toBe(true);
  });
  it('is null for a 0.1 cell and when the land model was not used', () => {
    expect(coverView(cell(), undefined)).toBeNull();
    expect(coverView(cell(), lm('used'))).toBeNull();
    expect(coverView(cell({ cover_set: ['forest'] }), lm('not_used'))).toBeNull();
  });
});

describe('fireRiskView', () => {
  it('is null when absent', () => expect(fireRiskView(undefined)).toBeNull());
  it('passes through status, rows, model and baseline', () => {
    const v = fireRiskView({
      status: 'not_passed', test_dates: ['2026-10-06'], model_pr_auc: 0.2, model_pr_auc_ci: [0.1, 0.3],
      best_baseline: { id: 'B2', pr_auc: 0.25 }, lift: [{ quintile: 1, n: 10, fires: 1, rate: 0.1 }],
    });
    expect(v).toEqual({
      status: 'not_passed', testDates: ['2026-10-06'], rows: [{ quintile: 1, n: 10, fires: 1, rate: 0.1 }],
      model: { prAuc: 0.2, lo: 0.1, hi: 0.3 }, baseline: { id: 'B2', prAuc: 0.25 },
    });
  });
  it('reads the mock scorecard', () => {
    const v = fireRiskView(sc.fire_risk);
    expect(v?.status).toBe('not_run');
    expect(v?.rows).toHaveLength(5);
    expect(v?.model).toBeNull();
    expect(v?.baseline).toBeNull();
  });
  it('finds the land coverage test only when present', () => {
    expect(landCoverageTest(sc.tests)).toBeNull();
    const t = { id: 'land_model_coverage', name_en: '', name_id: '', statistic: '', value: 0.9, n: 1, note_en: '', note_id: '' };
    expect(landCoverageTest([t])).toBe(t);
  });
});

describe('fire-risk copy', () => {
  it('never says probability or forecast, except "not a forecast"', () => {
    for (const v of Object.values(en)) {
      expect(v).not.toMatch(/probabilit/i);
      expect(v.replaceAll('not a forecast', '')).not.toMatch(/forecast/i);
    }
  });
  it('labels the hindcast as one season at one site', () => {
    expect(en['score.fire']).toContain('hindcast, 2026 season, one site');
  });
});
