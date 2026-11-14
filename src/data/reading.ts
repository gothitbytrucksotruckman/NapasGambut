// One-sentence reading of a cell's season (PRD 8.3). Fixed templates over the state sequence, no language model.
// It only describes states the bundle already decided; it never re-derives science.
import { STATE } from '../contract';
import type { Lang } from '../state/hash';

const MONTHS = {
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
  id: ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'],
};

/** "2026-09-24" → "late September" / "akhir September" */
function when(iso: string, lang: Lang): string {
  const [, m, d] = iso.split('-').map(Number);
  const part = d <= 10 ? 0 : d <= 20 ? 1 : 2;
  const month = MONTHS[lang][m - 1];
  return lang === 'en' ? `${['early', 'mid', 'late'][part]} ${month}` : `${['awal', 'pertengahan', 'akhir'][part]} ${month}`; // REVIEW
}

const T = {
  en: {
    noData: 'No usable radar for this cell all season.',
    flat: 'Stayed within the noise all season.',
    dried: (w: string) => `Dried from ${w}`,
    dryThenDeep: (a: string, b: string) => `Dried from ${a} and reached deep drying by ${b}`,
    straightDeep: (w: string) => `Went straight to deep drying in ${w}`,
    burned: (w: string) => `burned in ${w}`,
    burnedFirst: (w: string) => `Burned in ${w}`,
    silent: 'though the radar did not see the fire',
    rewet: (w: string) => `began re-wetting by ${w}`,
    rewetFirst: (w: string) => `Began re-wetting by ${w}`,
    recovered: (w: string) => `back within the noise by ${w}`,
    noRecovery: 'no recovery yet',
    stillDry: 'still dry at the last pass',
    join: ', ',
  },
  id: {
    noData: 'Tidak ada radar yang dapat dipakai untuk sel ini sepanjang musim.', // REVIEW
    flat: 'Tetap dalam batas derau sepanjang musim.', // REVIEW
    dried: (w: string) => `Mengering sejak ${w}`, // REVIEW
    dryThenDeep: (a: string, b: string) => `Mengering sejak ${a} dan mengering parah pada ${b}`, // REVIEW
    straightDeep: (w: string) => `Langsung mengering parah pada ${w}`, // REVIEW
    burned: (w: string) => `terbakar pada ${w}`, // REVIEW
    burnedFirst: (w: string) => `Terbakar pada ${w}`, // REVIEW
    silent: 'meskipun radar tidak mendeteksi apinya', // REVIEW
    rewet: (w: string) => `mulai membasah kembali pada ${w}`, // REVIEW
    rewetFirst: (w: string) => `Mulai membasah kembali pada ${w}`, // REVIEW
    recovered: (w: string) => `kembali dalam batas derau pada ${w}`, // REVIEW
    noRecovery: 'belum pulih', // REVIEW
    stillDry: 'masih kering pada lintasan terakhir', // REVIEW
    join: ', ',
  },
};

const isFire = (s: number) => s === STATE.fire_radar || s === STATE.fire_silent;
const isDry = (s: number) => s === STATE.drying || s === STATE.deep_drying;

export function readingFor(states: number[], dates: string[], lang: Lang): string {
  const tx = T[lang];
  const valid = states.map((s, i) => [s, i] as const).filter(([s]) => s !== STATE.no_data);
  if (valid.length === 0) return tx.noData;

  const first = (pred: (s: number) => boolean, from = 0) => valid.find(([s, i]) => i >= from && pred(s))?.[1];
  const dryAt = first(isDry);
  const deepAt = first((s) => s === STATE.deep_drying);
  const fireAt = first(isFire);
  const silentFire = fireAt !== undefined && states[fireAt] === STATE.fire_silent;
  const after = fireAt ?? deepAt ?? dryAt ?? 0;
  const rewetAt = first((s) => s === STATE.rewetting, after);
  const last = valid[valid.length - 1][0];
  const backToStable = dryAt !== undefined && fireAt === undefined && last === STATE.stable;

  if (dryAt === undefined && fireAt === undefined && rewetAt === undefined) return tx.flat;

  const parts: string[] = [];
  // Drying, only if it came before any fire.
  const dryBeforeFire = dryAt !== undefined && (fireAt === undefined || dryAt < fireAt);
  const deepBeforeFire = deepAt !== undefined && (fireAt === undefined || deepAt < fireAt);
  if (dryBeforeFire && deepBeforeFire && deepAt! > dryAt!) parts.push(tx.dryThenDeep(when(dates[dryAt!], lang), when(dates[deepAt!], lang)));
  // Same pass for first drying and deep drying: the cell skipped plain drying.
  else if (dryBeforeFire && deepBeforeFire) parts.push(tx.straightDeep(when(dates[deepAt!], lang)));
  else if (dryBeforeFire) parts.push(tx.dried(when(dates[dryAt!], lang)));

  if (fireAt !== undefined) {
    const w = when(dates[fireAt], lang);
    parts.push(parts.length ? tx.burned(w) : tx.burnedFirst(w));
    if (silentFire) parts.push(tx.silent);
  }

  if (rewetAt !== undefined) {
    const w = when(dates[rewetAt], lang);
    parts.push(parts.length ? tx.rewet(w) : tx.rewetFirst(w));
  } else if (fireAt !== undefined) {
    parts.push(tx.noRecovery);
  } else if (backToStable) {
    const back = valid.find(([s, i]) => i > dryAt! && s === STATE.stable)![1];
    parts.push(tx.recovered(when(dates[back], lang)));
  } else if (isDry(last)) {
    parts.push(tx.stillDry);
  }

  return `${parts.join(tx.join)}.`;
}
