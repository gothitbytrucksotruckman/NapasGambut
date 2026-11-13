// State rules, PRD 6.6. Pure: one cell in, one state code per date out. First match wins.
import { STATE } from '../../src/contract';

export interface CellInput {
  D: (number | null)[]; // HH drying index in dB, per date
  hv: (number | null)[]; // HV index in dB, per date
  coh: (number | null)[]; // coherence 0..100, per interval
  fires: (number | null)[]; // detections per interval
  nPixels: number;
  dropped: boolean[]; // per date
  sigma: (number | null)[]; // per date, dB
  rainInterval: (number | null)[]; // per interval, mm
  k: { change: number; deep: number; rainReturn: number };
}

export function classifyCell(x: CellInput): number[] {
  const out: number[] = [];
  let burnedBefore = false;
  let rainReturned = false;
  let minD = Infinity;
  let lastHv: number | null = null;

  for (let t = 0; t < x.dropped.length; t++) {
    if (t > 0 && (x.rainInterval[t - 1] ?? 0) >= x.k.rainReturn) rainReturned = true;

    if (x.dropped[t] || x.nPixels < 313) {
      out.push(STATE.no_data);
      continue;
    }
    const D = x.D[t];
    const hv = x.hv[t];
    if (t === 0 || D === null) {
      out.push(D === null ? STATE.no_data : STATE.stable);
      if (D !== null) minD = Math.min(minD, D);
      if (hv !== null) lastHv = hv;
      continue;
    }
    const sigma = x.sigma[t];
    if (sigma === null) throw new Error(`sigma missing at valid date ${t}`);
    const fire = (x.fires[t - 1] ?? 0) > 0;
    const coh = x.coh[t - 1];
    const hvFell = hv !== null && lastHv !== null && lastHv - hv > x.k.change * sigma;
    const cohLow = coh !== null && coh < 20;

    let s: number;
    if (fire && (hvFell || cohLow)) s = STATE.fire_radar;
    else if (fire) s = STATE.fire_silent;
    else if (burnedBefore) s = STATE.burned;
    else if (rainReturned && D - minD > x.k.change * sigma) s = STATE.rewetting;
    else if (D < -x.k.deep * sigma) s = STATE.deep_drying;
    else if (D < -x.k.change * sigma) s = STATE.drying;
    else s = STATE.stable;

    if (s === STATE.fire_radar || s === STATE.fire_silent) burnedBefore = true;
    out.push(s);
    minD = Math.min(minD, D);
    if (hv !== null) lastHv = hv;
  }
  return out;
}
