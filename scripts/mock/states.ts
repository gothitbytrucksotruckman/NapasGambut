// State rules, PRD 6.6. Pure: one cell in, one state code per date out. First match wins.
// "Fire in the interval ending at this date" is read as "fire since the last valid pass" (the Method text's wording);
// the two agree when no pass is dropped. pipeline/07_states.py must apply the same rules.
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
  // Detections since the last valid pass: a fire during a dropped pass (e.g. a satellite data gap) is not lost.
  let firesSince = 0;

  for (let t = 0; t < x.dropped.length; t++) {
    if (t > 0 && (x.rainInterval[t - 1] ?? 0) >= x.k.rainReturn) rainReturned = true;
    if (t > 0) firesSince += x.fires[t - 1] ?? 0;

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
      if (D !== null) firesSince = 0;
      continue;
    }
    const sigma = x.sigma[t];
    if (sigma === null) throw new Error(`sigma missing at valid date ${t}`);
    const fire = firesSince > 0;
    firesSince = 0;
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
