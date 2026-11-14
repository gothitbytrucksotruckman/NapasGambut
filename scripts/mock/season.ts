import { type Rng, uniform } from './rng';

const START = Date.UTC(2026, 5, 20);
export const DATES = Array.from({ length: 13 }, (_, i) => new Date(START + i * 12 * 86400000).toISOString().slice(0, 10));
export const DROPPED_DATE = '2026-10-30';
export const DROPPED_INDEX = DATES.indexOf(DROPPED_DATE);
/** Intervals k = DATES[k] -> DATES[k+1] in which fires may start: 08-07 (index 4) to 10-18 (index 10). */
export const FIRE_INTERVALS = [4, 5, 6, 7, 8, 9];
/** First interval with heavy rain: 10-18 -> 10-30. */
export const RAIN_RETURN_INTERVAL = 10;
export const RAIN_RETURN_MM = 50;

/** Drought strength s(t) per date: 0.15 -> 1.0 at 10-06 (index 9), flat to 10-18, 0.45 at 11-11. */
export function droughtCurve(): number[] {
  return DATES.map((_, i) => {
    if (i <= 9) {
      const x = i / 9;
      return 0.15 + 0.85 * (x * x * (3 - 2 * x)); // smoothstep
    }
    return [1, 0.97, 0.7, 0.45][i - 9];
  });
}

export function simulateRain(rng: Rng): { rain3day: number[]; rainInterval: number[] } {
  const rain3day = DATES.map((_, i) => Math.round(i <= 10 ? uniform(rng, 0, 15) : uniform(rng, 40, 90)));
  const rainInterval = DATES.slice(1).map((_, k) =>
    Math.round(k < RAIN_RETURN_INTERVAL ? uniform(rng, 2, 40) : uniform(rng, 140, 260)),
  );
  return { rain3day, rainInterval };
}
