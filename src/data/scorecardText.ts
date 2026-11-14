// Formatting for scorecard and method values. Display only: every number comes from the bundle as-is.
import type { Scorecard } from '../contract';
import type { Lang } from '../state/hash';

/** -2.1 → "−2.1" (true minus sign, reads better in tabular figures). */
export function formatDb(v: number): string {
  const r = Math.round(v * 10) / 10;
  if (r === 0) return '0.0';
  return `${r > 0 ? '+' : '−'}${Math.abs(r).toFixed(1)}`;
}

/** "More canals, more drying. Spearman rank correlation: −0.445, from 3865 cells." plus the note. */
export function testSentence(test: Scorecard['tests'][number], lang: Lang): string {
  const name = lang === 'en' ? test.name_en : test.name_id;
  const value = Math.abs(test.value) < 10 ? test.value.toFixed(Number.isInteger(test.value * 100) ? 2 : 3) : String(test.value);
  const shown = value.startsWith('-') ? `−${value.slice(1)}` : value;
  const from = lang === 'en' ? `from ${test.n} cells` : `dari ${test.n} sel`; // REVIEW
  return `${name}. ${test.statistic}: ${shown}, ${from}.`;
}

export function sigmaRange(sigma: (number | null)[]): { lo: number; hi: number } | null {
  const v = sigma.filter((s): s is number => s !== null);
  return v.length ? { lo: Math.min(...v), hi: Math.max(...v) } : null;
}
