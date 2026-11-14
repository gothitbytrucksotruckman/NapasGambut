// HH, HV, coherence and fires, PRD 6.4. All values in dB or 0..100 floats; rounding happens at write time.
import type { ClassId } from '../../src/contract';
import { GRID, type Landscape } from './landscape';
import { normal, randInt, type Rng, smoothField, uniform } from './rng';
import { DATES, DROPPED_INDEX, droughtCurve, FIRE_INTERVALS, RAIN_RETURN_INTERVAL } from './season';

const AMP: Record<ClassId, number> = {
  drained: 2.6, plantation: 1.6, rewetted: 1.1, intact_forest: 0.25, reference_forest: 0, settlement: 0,
};
const COH_BASE: Record<ClassId, number> = {
  settlement: 75, drained: 55, rewetted: 50, plantation: 40, intact_forest: 30, reference_forest: 25,
};
const FIRE_CLASS: Record<ClassId, number> = {
  drained: 1, plantation: 0.6, rewetted: 0.5, intact_forest: 0.2, reference_forest: 0, settlement: 0,
};
const SPREAD_ROUNDS = 4;
const isForest =(c: ClassId) => c === 'intact_forest' || c === 'reference_forest';

export interface Signals {
  D: (number | null)[][];
  hv: (number | null)[][];
  coh: (number | null)[][];
  fires: number[][];
  /** cell index -> interval index of its fire */
  fireInterval: Map<number, number>;
  /** cell index -> whether the radar saw the fire */
  radarAgrees: Map<number, boolean>;
  /** cell indices of rewetted cells that behave like drained (failed dams) */
  leakyDams: Set<number>;
}

/** Fires: ~8 hazard-weighted ignitions, spreading with p 0.35 for 1 to 2 intervals. Retries until 6-10% burn. */
function simulateFires(rng: Rng, land: Landscape, s: number[]): Map<number, number> {
  const n = land.cells.length;
  const byRC = new Map(land.cells.map((c, i) => [c.row * GRID.cols + c.col, i]));
  const neighbours = (i: number) => {
    const { row, col } = land.cells[i];
    const out: number[] = [];
    for (let dr = -1; dr <= 1; dr++)
      for (let dc = -1; dc <= 1; dc++) {
        if (!dr && !dc) continue;
        const j = byRC.get((row + dr) * GRID.cols + col + dc);
        if (j !== undefined && col + dc >= 0 && col + dc < GRID.cols) out.push(j);
      }
    return out;
  };
  for (let attempt = 0; attempt < 200; attempt++) {
    const burned = new Map<number, number>();
    const nIgnite = randInt(rng, 7, 9);
    for (let g = 0; g < nIgnite; g++) {
      // Pick an interval weighted by s^3, then a cell weighted by hazard.
      const iw = FIRE_INTERVALS.map((k) => s[k + 1] ** 3);
      let u = rng() * iw.reduce((a, b) => a + b, 0);
      let k = FIRE_INTERVALS[0];
      for (let j = 0; j < iw.length; j++) if ((u -= iw[j]) <= 0) { k = FIRE_INTERVALS[j]; break; }
      const hz = land.cells.map((c, i) => (burned.has(i) ? 0 : (0.3 + c.cf) * FIRE_CLASS[c.cls]));
      let v = rng() * hz.reduce((a, b) => a + b, 0);
      let seed = 0;
      for (let i = 0; i < n; i++) if ((v -= hz[i]) <= 0) { seed = i; break; }
      burned.set(seed, k);
      let front = [seed];
      const spreadFor = randInt(rng, 1, 2);
      for (let step = 1; step <= spreadFor; step++) {
        const kk = Math.min(k + step, FIRE_INTERVALS[FIRE_INTERVALS.length - 1]);
        // A 12-day interval spans several 500 m hops, so spread runs SPREAD_ROUNDS rounds per interval.
        for (let round = 0; round < SPREAD_ROUNDS; round++) {
          const next: number[] = [];
          for (const f of front)
            for (const j of neighbours(f))
              if (!burned.has(j) && FIRE_CLASS[land.cells[j].cls] > 0 && rng() < 0.35) {
                burned.set(j, kk);
                next.push(j);
              }
          front = next.length ? next : front;
        }
      }
    }
    const share = burned.size / n;
    if (share >= 0.06 && share <= 0.1) return burned;
  }
  throw new Error('fire simulation could not reach a 6-10% burned share');
}

export function simulateSignals(rng: Rng, land: Landscape): Signals {
  const s = droughtCurve();
  const T = DATES.length;
  const smooth = DATES.map(() => smoothField(rng, GRID.rows, GRID.cols, 2));
  const smoothHv = DATES.map(() => smoothField(rng, GRID.rows, GRID.cols, 2));

  const rewettedIdx = land.cells.map((c, i) => (c.cls === 'rewetted' ? i : -1)).filter((i) => i >= 0);
  const leakyDams = new Set<number>();
  const nLeaky = Math.max(1, Math.round(rewettedIdx.length * 0.05));
  while (leakyDams.size < nLeaky) leakyDams.add(rewettedIdx[Math.floor(rng() * rewettedIdx.length)]);

  const fireInterval = simulateFires(rng, land, s);
  const radarAgrees = new Map<number, boolean>();
  for (const [i] of fireInterval) radarAgrees.set(i, rng() < (isForest(land.cells[i].cls) ? 0.8 : 0.65));

  const D: (number | null)[][] = [];
  const hv: (number | null)[][] = [];
  const coh: (number | null)[][] = [];
  const fires: number[][] = [];

  land.cells.forEach((c, i) => {
    const amp = leakyDams.has(i) ? AMP.drained : AMP[c.cls];
    const sd = c.cls === 'settlement' ? 0.15 : 0.25;
    const k = c.row * GRID.cols + c.col;
    const fk = fireInterval.get(i);
    const agrees = radarAgrees.get(i) ?? false;
    const scale = 0.6 + 0.8 * c.cf;

    // Noise at t=0 is subtracted so the index is change since the first date.
    const raw = (t: number, field: Float64Array[], mult: number) =>
      -mult * amp * s[t] * scale + sd * (0.6 * field[t][k] + 0.8 * normal(rng));
    const d0 = raw(0, smooth, 1);
    const h0 = raw(0, smoothHv, 0.3);
    const dRow: (number | null)[] = [];
    const hvRow: (number | null)[] = [];
    for (let t = 0; t < T; t++) {
      if (t === DROPPED_INDEX) { dRow.push(null); hvRow.push(null); continue; }
      dRow.push(t === 0 ? 0 : raw(t, smooth, 1) - d0);
      let h = t === 0 ? 0 : raw(t, smoothHv, 0.3) - h0;
      if (fk !== undefined && agrees && t > fk) h -= uniform(rng, 3, 5);
      hvRow.push(h);
    }

    const cohRow: (number | null)[] = [];
    const fireRow: number[] = [];
    for (let kk = 0; kk < T - 1; kk++) {
      fireRow.push(fk === kk ? randInt(rng, 1, 6) : 0);
      if (kk === DROPPED_INDEX - 1 || kk === DROPPED_INDEX) { cohRow.push(null); continue; }
      const sMid = (s[kk] + s[kk + 1]) / 2;
      let v = COH_BASE[c.cls] + 10 * sMid + normal(rng) * 2.5;
      if (fk === kk) v = agrees ? uniform(rng, 8, 15) : uniform(rng, 30, 40);
      else if (fk !== undefined && kk > fk) v = 40 + normal(rng) * 2.5;
      if (kk === RAIN_RETURN_INTERVAL) v -= 15;
      cohRow.push(Math.min(100, Math.max(0, v)));
    }
    D.push(dRow);
    hv.push(hvRow);
    coh.push(cohRow);
    fires.push(fireRow);
  });

  return { D, hv, coh, fires, fireInterval, radarAgrees, leakyDams };
}
