import { describe, expect, it } from 'vitest';
import { PNG } from 'pngjs';
import { DEFAULT_SEED, generateBundle, sha256 } from '../../scripts/mock/generate';
import { ManifestSchema, ScorecardSchema, SeriesSchema, STATE } from '../../src/contract';

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

  it('writes 640x640 images for every date plus the reveal pair', () => {
    const m = ManifestSchema.parse(json('manifest.json'));
    for (const f of [...m.images.radar.map((r) => r.file), m.images.reveal.optical_file, m.images.reveal.radar_file]) {
      const png = PNG.sync.read(a.get(f)!);
      expect([png.width, png.height], f).toEqual([640, 640]);
    }
  });
});
