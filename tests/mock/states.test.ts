import { describe, expect, it } from 'vitest';
import { classifyCell, type CellInput } from '../../scripts/mock/states';

// 5 dates, 4 intervals. sigma 0.5 dB everywhere except date 0.
const base = (): CellInput => ({
  D: [0, 0, 0, 0, 0],
  hv: [0, 0, 0, 0, 0],
  coh: [50, 50, 50, 50],
  fires: [0, 0, 0, 0],
  nPixels: 625,
  dropped: [false, false, false, false, false],
  sigma: [null, 0.5, 0.5, 0.5, 0.5],
  rainInterval: [5, 5, 5, 5],
  k: { change: 2, deep: 4, rainReturn: 50 },
});
const run = (patch: Partial<CellInput>) => classifyCell({ ...base(), ...patch });

describe('state rules (first match wins)', () => {
  it('marks every date stable when nothing happens, including date 0', () => {
    expect(run({})).toEqual([8, 8, 8, 8, 8]);
  });
  it('rule 1: dropped date is no_data', () => {
    expect(run({ dropped: [false, false, true, false, false], D: [0, 0, null, 0, 0] })[2]).toBe(1);
  });
  it('rule 1: a cell under 313 pixels is no_data on every date', () => {
    expect(run({ nPixels: 312 })).toEqual([1, 1, 1, 1, 1]);
  });
  it('rule 2: fire with an HV drop beyond change_k sigma is fire_radar', () => {
    expect(run({ fires: [0, 3, 0, 0], hv: [0, 0, -1.2, -1.2, -1.2] })[2]).toBe(2);
  });
  it('rule 2: fire with coherence under 20 is fire_radar', () => {
    expect(run({ fires: [0, 3, 0, 0], coh: [50, 12, 40, 40] })[2]).toBe(2);
  });
  it('rule 3: fire with neither radar sign is fire_silent', () => {
    expect(run({ fires: [0, 3, 0, 0], coh: [50, 35, 40, 40] })[2]).toBe(3);
  });
  it('rule 4: dates after a fire state are burned', () => {
    expect(run({ fires: [0, 3, 0, 0], coh: [50, 12, 40, 40] }).slice(3)).toEqual([4, 4]);
  });
  it('fire beats deep drying when both apply', () => {
    expect(run({ fires: [0, 0, 2, 0], D: [0, -1, -2.5, -3, -3], coh: [50, 50, 10, 40] })[3]).toBe(2);
  });
  it('rule 5: rewetting needs rain returned and a rise above the lowest earlier D', () => {
    const s = run({ D: [0, -3, -3, -1.5, -1.5], rainInterval: [5, 5, 80, 5] });
    expect(s[3]).toBe(5);
  });
  it('rule 5: no rewetting before rain returns', () => {
    const s = run({ D: [0, -3, -1.5, -1.5, -1.5] });
    expect(s[2]).toBe(7);
  });
  it('rule 6: D below -deep_k sigma is deep_drying', () => {
    expect(run({ D: [0, -2.1, 0, 0, 0] })[1]).toBe(6);
  });
  it('rule 7: D below -change_k sigma is drying', () => {
    expect(run({ D: [0, -1.1, 0, 0, 0] })[1]).toBe(7);
  });
  it('HV fall is measured from the last valid date, skipping a dropped date', () => {
    const s = run({
      dropped: [false, false, true, false, false],
      D: [0, 0, null, 0, 0],
      hv: [0, 0, null, -1.5, -1.5],
      coh: [50, null, null, 50],
      fires: [0, 0, 2, 0],
    });
    expect(s[3]).toBe(2);
  });
  it('a fire in the interval ending on a dropped date counts at the next valid date', () => {
    // Real NISAR data has a permanent gap: the fire happens while the radar has no pass.
    const s = run({ dropped: [false, false, true, false, false], D: [0, 0, null, 0, 0], fires: [0, 3, 0, 0] });
    expect(s).toEqual([8, 8, 1, 3, 4]);
  });
});
