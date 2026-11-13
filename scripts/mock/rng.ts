export type Rng = () => number;

// mulberry32: small, fast, deterministic. Never use Math.random in the generator.
export function mulberry32(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function normal(rng: Rng): number {
  const u = Math.max(rng(), 1e-12);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rng());
}

export const uniform = (rng: Rng, lo: number, hi: number) => lo + (hi - lo) * rng();
export const randInt = (rng: Rng, lo: number, hi: number) => Math.floor(uniform(rng, lo, hi + 1));

/** Spatially smooth noise: box-blurred white noise, rescaled to mean 0, sd 1. */
export function smoothField(rng: Rng, rows: number, cols: number, radius: number, passes = 2): Float64Array {
  let f = new Float64Array(rows * cols).map(() => normal(rng));
  for (let p = 0; p < passes; p++) {
    const g = new Float64Array(rows * cols);
    for (let r = 0; r < rows; r++)
      for (let c = 0; c < cols; c++) {
        let s = 0, n = 0;
        for (let dr = -radius; dr <= radius; dr++)
          for (let dc = -radius; dc <= radius; dc++) {
            const rr = r + dr, cc = c + dc;
            if (rr >= 0 && rr < rows && cc >= 0 && cc < cols) { s += f[rr * cols + cc]; n++; }
          }
        g[r * cols + c] = s / n;
      }
    f = g;
  }
  let mean = 0;
  for (const v of f) mean += v;
  mean /= f.length;
  let sd = 0;
  for (const v of f) sd += (v - mean) ** 2;
  sd = Math.sqrt(sd / f.length) || 1;
  return f.map((v) => (v - mean) / sd);
}
