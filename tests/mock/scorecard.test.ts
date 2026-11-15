import { describe, expect, it } from 'vitest';
import { median, quantile, spearman, mad } from '../../scripts/mock/stats';
import { fireLift, mockFireRisk } from '../../scripts/mock/scorecard';

describe('fire-risk lift', () => {
  it('splits rows into quintiles by HV index like pandas qcut', () => {
    // 7 distinct values: qcut(q=5) puts 2, 1, 1, 1, 2 rows in the bins.
    const rows = [5, -3, 0, 2, -1, 9, 1].map((hv, i) => ({ hv, fire: i % 2 === 0 }));
    expect(fireLift(rows)).toEqual([
      { quintile: 1, n: 2, fires: 1, rate: 0.5 },        // -3 (no), -1 (yes)
      { quintile: 2, n: 1, fires: 1, rate: 1 },          // 0 (yes)
      { quintile: 3, n: 1, fires: 1, rate: 1 },          // 1 (yes)
      { quintile: 4, n: 1, fires: 0, rate: 0 },          // 2 (no)
      { quintile: 5, n: 2, fires: 1, rate: 0.5 },        // 5 (yes), 9 (no)
    ]);
  });

  it('builds panel rows the way build_panel does', () => {
    const dates = ['d0', 'd1', 'd2', 'd3', 'd4'];
    const dropped = [false, false, false, true, false]; // kept passes 0, 1, 2, 4
    const hv = [
      [0, -10, -20, null, -30], // fire in interval 2 -> target true at pass 2
      [0, -5, null, null, 0],   // no HV at pass 2 -> row only at pass 1
      [0, 10, 20, null, 0],     // burned in interval 0 -> never a row
    ];
    const fires = [[0, 0, 1, 0], [0, 0, 0, 0], [2, 0, 0, null]];
    const fr = mockFireRisk(hv, fires, dates, dropped);
    expect(fr.test_dates).toEqual(['d1', 'd2']);
    expect(fr.lift.reduce((a, q) => a + q.n, 0)).toBe(3);
    expect(fr.lift.reduce((a, q) => a + q.fires, 0)).toBe(1);
  });
});

describe('stats helpers', () => {
  it('computes medians for odd and even lengths', () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 2, 3])).toBe(2.5);
  });
  it('uses linear (type 7) quantiles', () => {
    expect(quantile([1, 2, 3, 4], 0.25)).toBe(1.75);
  });
  it('gives -1 for a perfectly reversed ranking', () => {
    expect(spearman([1, 2, 3], [3, 2, 1])).toBeCloseTo(-1);
  });
  it('averages ranks for ties', () => {
    expect(spearman([1, 1, 2], [1, 1, 2])).toBeCloseTo(1);
  });
  it('computes the median absolute deviation', () => {
    expect(mad([1, 2, 3, 4, 100])).toBe(1);
  });
});
