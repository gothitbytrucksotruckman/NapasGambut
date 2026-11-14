import { describe, expect, it } from 'vitest';
import { median, quantile, spearman, mad } from '../../scripts/mock/stats';

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
