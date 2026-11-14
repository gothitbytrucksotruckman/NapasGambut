import { describe, expect, it } from 'vitest';
import { mulberry32 } from '../../scripts/mock/rng';
import { DATES, DROPPED_INDEX, droughtCurve, simulateRain } from '../../scripts/mock/season';
import { buildLandscape, GRID } from '../../scripts/mock/landscape';

const land = buildLandscape(mulberry32(20261114));
const total = GRID.rows * GRID.cols;
const share = (cls: string) => land.cells.filter((c) => c.cls === cls).length / total;

describe('rng', () => {
  it('repeats the same sequence for the same seed', () => {
    const a = mulberry32(7), b = mulberry32(7);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });
});

describe('season', () => {
  it('has 13 dates every 12 days from 2026-06-20, dropping 2026-10-30', () => {
    expect(DATES).toHaveLength(13);
    expect(DATES[0]).toBe('2026-06-20');
    expect(DATES[12]).toBe('2026-11-11');
    expect(DATES[DROPPED_INDEX]).toBe('2026-10-30');
  });
  it('drought curve starts near 0.15, peaks at 10-06, ends near 0.45', () => {
    const s = droughtCurve();
    expect(s[0]).toBeCloseTo(0.15, 2);
    expect(s[9]).toBeCloseTo(1, 2);
    expect(s[12]).toBeCloseTo(0.45, 2);
  });
  it('rain stays under 50 mm per interval until the 10-18 to 10-30 interval', () => {
    const r = simulateRain(mulberry32(1));
    expect(r.rainInterval.slice(0, 10).every((v) => v < 50)).toBe(true);
    expect(r.rainInterval[10]).toBeGreaterThanOrEqual(50);
    expect(r.rain3day.slice(11).every((v) => v >= 40 && v <= 90)).toBe(true);
  });
});

describe('landscape', () => {
  it('lands class shares near the brief targets', () => {
    expect(share('drained')).toBeGreaterThan(0.34);
    expect(share('drained')).toBeLessThan(0.48);
    expect(share('rewetted')).toBeGreaterThan(0.06);
    expect(share('rewetted')).toBeLessThan(0.1);
    expect(share('plantation')).toBeGreaterThan(0.09);
    expect(share('plantation')).toBeLessThan(0.15);
    expect(share('intact_forest')).toBeGreaterThan(0.25);
    expect(share('intact_forest')).toBeLessThan(0.35);
    expect(share('reference_forest')).toBeGreaterThan(0.035);
    expect(share('reference_forest')).toBeLessThan(0.065);
    expect(share('settlement')).toBeGreaterThan(0.002);
    expect(share('settlement')).toBeLessThan(0.01);
    const water = (total - land.cells.length) / total;
    expect(water).toBeGreaterThan(0.01);
    expect(water).toBeLessThan(0.06);
  });

  it('places 15 to 25 dams', () => {
    expect(land.dams.length).toBeGreaterThanOrEqual(15);
    expect(land.dams.length).toBeLessThanOrEqual(25);
  });

  it('keeps rewetted cells in one 4-connected block', () => {
    const set = new Set(land.cells.filter((c) => c.cls === 'rewetted').map((c) => c.row * 1000 + c.col));
    const start = set.values().next().value!;
    const seen = new Set([start]);
    const queue = [start];
    while (queue.length) {
      const k = queue.pop()!;
      for (const n of [k - 1, k + 1, k - 1000, k + 1000]) if (set.has(n) && !seen.has(n)) { seen.add(n); queue.push(n); }
    }
    expect(seen.size).toBe(set.size);
  });

  it('uses padded ids and clips some cells near the river', () => {
    expect(land.cells.every((c) => /^r\d{3}c\d{3}$/.test(c.id))).toBe(true);
    expect(land.cells.every((c) => c.nPixels >= 300 && c.nPixels <= 625)).toBe(true);
    expect(land.cells.some((c) => c.nPixels < 313)).toBe(true);
  });

  it('gives drained peat far more canal than intact forest', () => {
    const med = (cls: string) => {
      const v = land.cells.filter((c) => c.cls === cls).map((c) => c.canalDensity).sort((a, b) => a - b);
      return v[v.length >> 1];
    };
    expect(med('drained')).toBeGreaterThan(0.5);
    expect(med('intact_forest')).toBeLessThan(0.2);
    expect(land.cells.every((c) => c.cf >= 0 && c.cf <= 1)).toBe(true);
  });
});
