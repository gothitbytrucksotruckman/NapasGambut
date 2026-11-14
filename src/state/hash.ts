// URL hash <-> shareable view state (PRD 7.2). Unknown values fall back, never throw.
export const SCREENS = ['reveal', 'map', 'scorecard', 'method'] as const;
export const LAYERS = ['state', 'hh', 'hv', 'coh', 'radar'] as const;
export const LANGS = ['en', 'id'] as const;
export type Screen = (typeof SCREENS)[number];
export type LayerId = (typeof LAYERS)[number];
export type Lang = (typeof LANGS)[number];

export interface View {
  screen: Screen;
  dateIndex: number;
  selectedCell: string | null;
  layer: LayerId;
  lang: Lang;
}

const pick = <T extends string>(list: readonly T[], v: string | null, fallback: T): T =>
  v !== null && (list as readonly string[]).includes(v) ? (v as T) : fallback;

export function parseHash(hash: string, ctx: { dates: string[]; hasCell: (id: string) => boolean }): View {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const q = new URLSearchParams(query);
  const d = q.get('d');
  const di = d ? ctx.dates.indexOf(d) : -1;
  const cell = q.get('cell');
  return {
    screen: pick(SCREENS, path || null, 'reveal'),
    dateIndex: di >= 0 ? di : 0,
    selectedCell: cell && /^r\d{3}c\d{3}$/.test(cell) && ctx.hasCell(cell) ? cell : null,
    layer: pick(LAYERS, q.get('layer'), 'state'),
    lang: pick(LANGS, q.get('lang'), 'en'),
  };
}

export function toHash(v: View, dates: string[]): string {
  const q = new URLSearchParams();
  q.set('d', dates[v.dateIndex] ?? dates[0]);
  if (v.selectedCell) q.set('cell', v.selectedCell);
  q.set('layer', v.layer);
  q.set('lang', v.lang);
  return `#/${v.screen}?${q.toString()}`;
}
