import type { Lang } from '../state/hash';
import { en, type Key } from './en';
import { id } from './id';

const dict = { en, id } as const;

export function t(lang: Lang, key: Key, vars?: Record<string, string | number>): string {
  let s: string = dict[lang][key];
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

const MONTHS = {
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
  id: ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'],
};
const SHORT = {
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
  id: ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'],
};

/** "2026-09-24" → "24 September 2026" (both languages use day-month-year). */
export function formatDate(iso: string, lang: Lang, style: 'long' | 'short' = 'long'): string {
  const [y, m, d] = iso.split('-').map(Number);
  return style === 'long' ? `${d} ${MONTHS[lang][m - 1]} ${y}` : `${d} ${SHORT[lang][m - 1]}`;
}

export const formatNumber = (n: number, lang: Lang) => n.toLocaleString(lang === 'en' ? 'en-GB' : 'id-ID');

export type { Key };
