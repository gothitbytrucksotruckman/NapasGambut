const sorted = (v: number[]) => [...v].sort((a, b) => a - b);

/** Linear interpolation between order statistics (R type 7). */
export function quantile(v: number[], p: number): number {
  if (!v.length) throw new Error('quantile of empty array');
  const s = sorted(v);
  const h = (s.length - 1) * p;
  const lo = Math.floor(h);
  return s[lo] + (h - lo) * ((s[Math.min(lo + 1, s.length - 1)]) - s[lo]);
}
export const median = (v: number[]) => quantile(v, 0.5);
export const mad = (v: number[]) => {
  const m = median(v);
  return median(v.map((x) => Math.abs(x - m)));
};

function ranks(v: number[]): number[] {
  const order = v.map((x, i) => [x, i] as const).sort((a, b) => a[0] - b[0]);
  const r = new Array<number>(v.length);
  for (let i = 0; i < order.length; ) {
    let j = i;
    while (j + 1 < order.length && order[j + 1][0] === order[i][0]) j++;
    for (let k = i; k <= j; k++) r[order[k][1]] = (i + j) / 2 + 1;
    i = j + 1;
  }
  return r;
}

/** Spearman rank correlation: Pearson correlation of average ranks. */
export function spearman(a: number[], b: number[]): number {
  const ra = ranks(a), rb = ranks(b);
  const n = a.length;
  const ma = ra.reduce((s, x) => s + x, 0) / n, mb = rb.reduce((s, x) => s + x, 0) / n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) {
    num += (ra[i] - ma) * (rb[i] - mb);
    da += (ra[i] - ma) ** 2;
    db += (rb[i] - mb) ** 2;
  }
  return num / Math.sqrt(da * db);
}

export const round = (v: number, d = 2) => Math.round(v * 10 ** d) / 10 ** d;
