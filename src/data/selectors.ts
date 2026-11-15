// Pure selectors (PRD 7.1). Screens read the bundle only through these.
import { STATE, type CellProperties } from '../contract';
import type { Bundle } from './load';

export type Layer = 'state' | 'hh' | 'hv' | 'coh' | 'radar';

export interface CellSeries {
  id: string;
  props: CellProperties;
  hh: (number | null)[];
  hv: (number | null)[];
  coh: (number | null)[];
  fires: (number | null)[];
  state: number[];
}

export function cellSeries(b: Bundle, id: string): CellSeries | null {
  const i = b.idx.cell.get(id);
  const f = b.idx.feature.get(id);
  if (i === undefined || !f) return null;
  const s = b.series;
  return { id, props: f.properties, hh: s.hh[i], hv: s.hv[i], coh: s.coh[i], fires: s.fires[i], state: s.state[i] };
}

export const statesAtDate = (b: Bundle, t: number): number[] => b.series.state.map((row) => row[t]);

export function countsByState(b: Bundle, t: number): Record<number, number> {
  const out: Record<number, number> = {};
  for (const code of Object.values(STATE)) out[code] = 0;
  for (const row of b.series.state) out[row[t]]++;
  return out;
}

export const isDropped = (b: Bundle, t: number) => b.context.quality[t] === 'dropped';

/** True if at least one cell/interval in the bundle has a non-null coherence value. */
export function hasCoherence(b: Bundle): boolean {
  return b.series.coh.some((row) => row.some((v) => v !== null));
}

/** Per-cell value for a continuous layer at date t. Coherence uses the interval ending at t. */
export function valuesAtDate(b: Bundle, layer: 'hh' | 'hv' | 'coh', t: number): (number | null)[] {
  if (layer === 'coh') return b.series.coh.map((row) => (t === 0 ? null : row[t - 1]));
  return b.series[layer].map((row) => row[t]);
}

export const droppedReason = (b: Bundle, t: number, lang: 'en' | 'id') => {
  const d = b.manifest.dropped_dates.find((x) => x.date === b.manifest.dates[t]);
  return d ? (lang === 'en' ? d.reason_en : d.reason_id) : null;
};
