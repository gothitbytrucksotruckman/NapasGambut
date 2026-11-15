import { describe, expect, it } from 'vitest';
import { PNG } from 'pngjs';
import { DEFAULT_SEED, generateBundle, sha256 } from '../../scripts/mock/generate';
import { CellsSchema, ManifestSchema, ScorecardSchema, SeriesSchema, STATE } from '../../src/contract';

const a = generateBundle(DEFAULT_SEED);
const json = (name: string) => JSON.parse(a.get(name)!.toString());

describe('generator', () => {
  it('is byte-identical for the same seed', () => {
    const b = generateBundle(DEFAULT_SEED);
    expect([...b.keys()]).toEqual([...a.keys()]);
    for (const [k, v] of a) expect(sha256(b.get(k)!), k).toBe(sha256(v));
  });

  it('writes contract-valid files with aligned arrays', () => {
    const m = ManifestSchema.parse(json('manifest.json'));
    const s = SeriesSchema.parse(json('series.json'));
    expect(m.dates).toHaveLength(13);
    expect(s.hh.every((r) => r.length === 13)).toBe(true);
    expect(s.coh.every((r) => r.length === 12)).toBe(true);
    expect(m.thresholds.sigma_db[0]).toBeNull();
    expect(m.thresholds.sigma_db[11]).toBeNull();
    expect(s.state.every((r) => r[11] === STATE.no_data)).toBe(true);
  });

  it('produces every state at least once somewhere in the season', () => {
    const s = SeriesSchema.parse(json('series.json'));
    const seen = new Set(s.state.flat());
    expect([...seen].sort()).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it('builds a scorecard whose notes say simulated and descriptive', () => {
    const sc = ScorecardSchema.parse(json('scorecard.json'));
    expect(sc.tests.map((t) => t.id)).toEqual(['canal_vs_drying', 'rewetted_vs_drained', 'drying_before_fire', 'forest_flat']);
    for (const t of sc.tests) expect(t.note_en).toMatch(/simulated/i);
    for (const t of sc.tests) expect(t.note_en).toMatch(/descriptive/i);
    expect(sc.rankings.fastest_drying.length).toBe(20);
    expect(sc.rankings.dams_to_inspect.length).toBeGreaterThan(0);
    expect(sc.rankings.canals?.length).toBe(20);
  });

  it('labels the 0.2 land model fields as simulated and gives every cell a cover set', () => {
    const m = ManifestSchema.parse(json('manifest.json'));
    expect(m.schema_version).toBe('0.2');
    expect(m.land_model?.status).toBe('simulated');
    const props = CellsSchema.parse(json('cells.geojson')).features.map((f) => f.properties);
    expect(props.every((p) => Array.isArray(p.cover_set))).toBe(true);
    const share = (k: number) => k / props.length;
    expect(share(props.filter((p) => p.cover_set!.length === 0).length)).toBeGreaterThan(0.015);
    expect(share(props.filter((p) => p.cover_set!.length === 0).length)).toBeLessThan(0.045);
    expect(share(props.filter((p) => p.cover_set!.length === 2).length)).toBeGreaterThan(0.06);
    expect(share(props.filter((p) => p.cover_set!.length === 2).length)).toBeLessThan(0.1);
    const flagged = props.filter((p) => p.map_check);
    expect(flagged.every((p) => p.cover_set!.length === 1 && p.map_check !== p.cover_set![0])).toBe(true);
    const singles = props.filter((p) => p.cover_set!.length === 1).length;
    expect(flagged.length / singles).toBeGreaterThan(0.01);
    expect(flagged.length / singles).toBeLessThan(0.03);
  });

  it('writes a not_run fire_risk block and none of the model tests', () => {
    const sc = ScorecardSchema.parse(json('scorecard.json'));
    const fr = sc.fire_risk!;
    expect([fr.status, fr.model_pr_auc, fr.model_pr_auc_ci, fr.best_baseline]).toEqual(['not_run', null, null, null]);
    expect(fr.test_dates).toHaveLength(2);
    expect(fr.lift.map((q) => q.quintile)).toEqual([1, 2, 3, 4, 5]);
    // Test rows: cells unburned before the pass with HV there and at the previous pass (no dropped date precedes the test passes).
    const s = SeriesSchema.parse(json('series.json'));
    const firstFire = s.fires.map((r) => { const k = r.findIndex((v) => (v ?? 0) > 0); return k < 0 ? 99 : k; });
    const rows = fr.test_dates.reduce((sum, d) => {
      const b = s.dates.indexOf(d);
      return sum + s.hv.filter((h, j) => firstFire[j] >= b && h[b] !== null && h[b - 1] !== null).length;
    }, 0);
    expect(fr.lift.reduce((a, q) => a + q.n, 0)).toBe(rows);
    const ids = sc.tests.map((t) => t.id);
    for (const id of ['fire_risk_capture', 'land_model_coverage', 'map_out_of_date']) expect(ids).not.toContain(id);
  });

  it('writes 640x640 images for every date plus the reveal pair', () => {
    const m = ManifestSchema.parse(json('manifest.json'));
    for (const f of [...m.images.radar.map((r) => r.file), m.images.reveal.optical_file, m.images.reveal.radar_file]) {
      const png = PNG.sync.read(a.get(f)!);
      expect([png.width, png.height], f).toEqual([640, 640]);
    }
  });
});
