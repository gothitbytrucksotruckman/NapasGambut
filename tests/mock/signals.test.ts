import { describe, expect, it } from 'vitest';
import { mulberry32 } from '../../scripts/mock/rng';
import { buildLandscape } from '../../scripts/mock/landscape';
import { DROPPED_INDEX, FIRE_INTERVALS } from '../../scripts/mock/season';
import { simulateSignals } from '../../scripts/mock/signals';

const land = buildLandscape(mulberry32(20261114));
const sig = simulateSignals(mulberry32(99), land);

describe('signals', () => {
  it('starts every HH and HV index at exactly 0', () => {
    expect(sig.D.every((row) => row[0] === 0)).toBe(true);
    expect(sig.hv.every((row) => row[0] === 0)).toBe(true);
  });
  it('nulls radar values on the dropped date and coherence of both touching intervals', () => {
    expect(sig.D.every((row) => row[DROPPED_INDEX] === null)).toBe(true);
    expect(sig.coh.every((row) => row[DROPPED_INDEX - 1] === null && row[DROPPED_INDEX] === null)).toBe(true);
  });
  it('only burns in the 08-07 to 10-18 intervals', () => {
    sig.fires.forEach((row) => row.forEach((n, k) => { if (n > 0) expect(FIRE_INTERVALS).toContain(k); }));
  });
  it('burns 6 to 10% of cells with 1 to 6 detections each', () => {
    const share = sig.fireInterval.size / land.cells.length;
    expect(share).toBeGreaterThanOrEqual(0.06);
    expect(share).toBeLessThanOrEqual(0.1);
    sig.fires.forEach((row) => row.forEach((n) => expect(n === 0 || (n >= 1 && n <= 6)).toBe(true)));
  });
  it('dries drained peat far more than intact forest at peak', () => {
    const med = (cls: string) => {
      const v = land.cells.map((c, i) => [c, sig.D[i][9]] as const).filter(([c]) => c.cls === cls).map(([, d]) => d!).sort((a, b) => a - b);
      return v[v.length >> 1];
    };
    expect(med('drained')).toBeLessThan(-1.5);
    expect(Math.abs(med('intact_forest'))).toBeLessThan(0.6);
  });
  it('keeps coherence within 0 to 100', () => {
    sig.coh.forEach((row) => row.forEach((v) => v !== null && expect(v >= 0 && v <= 100).toBe(true)));
  });
});
