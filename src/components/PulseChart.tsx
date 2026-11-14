// The pulse card chart (PRD 8.3): one shared time axis, four stacked bands, each with its own scale.
// Stacked bands instead of a dual axis: dB lines, coherence and rain never share a y-scale.
// d3-scale scaleLinear and d3-shape line/area with .defined() verified in node_modules/@types/d3-*.
import { scaleLinear } from 'd3-scale';
import { area, line } from 'd3-shape';
import { useId, useState } from 'react';
import { STATE } from '../contract';
import { formatDate, t } from '../i18n';
import type { Lang } from '../state/hash';
import './PulseChart.css';

export type LineMode = 'hh' | 'hv' | 'ratio';

export interface PulseData {
  dates: string[];
  hh: (number | null)[]; // tenths of dB
  hv: (number | null)[];
  coh: (number | null)[]; // per interval
  fires: (number | null)[]; // per interval
  state: number[];
  sigma: (number | null)[]; // dB, per date
  changeK: number;
  rain: (number | null)[]; // mm, per interval
  dropped: boolean[];
}

interface Props {
  data: PulseData;
  mode: LineMode;
  current: number;
  lang: Lang;
  title: string;
}

const W = 560;
const PAD = { l: 44, r: 24 };
const BAND = { fire: [6, 26], main: [36, 184], coh: [206, 240], rain: [262, 294] } as const;
const H = 318;

/** Main-line values in dB, null where missing. HH minus HV is computed for display only (a difference of two given indexes). */
export function mainSeries(d: PulseData, mode: LineMode): (number | null)[] {
  return d.dates.map((_, i) => {
    const hh = d.hh[i], hv = d.hv[i];
    if (mode === 'hh') return hh === null ? null : hh / 10;
    if (mode === 'hv') return hv === null ? null : hv / 10;
    return hh === null || hv === null ? null : (hh - hv) / 10;
  });
}

export function PulseChart({ data, mode, current, lang, title }: Props) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const n = data.dates.length;
  const x = scaleLinear().domain([0, n - 1]).range([PAD.l, W - PAD.r]);
  const step = x(1) - x(0);

  const main = mainSeries(data, mode);
  const other = mode === 'hh' ? mainSeries(data, 'hv') : mode === 'hv' ? mainSeries(data, 'hh') : null;
  const band = data.sigma.map((s) => (s === null ? null : s * data.changeK));
  const all = [...main, ...(other ?? []), ...band, ...band.map((b) => (b === null ? null : -b))].filter((v): v is number => v !== null);
  const lo = Math.min(-1, ...all), hi = Math.max(0.5, ...all);
  const y = scaleLinear().domain([lo - 0.2, hi + 0.2]).nice().range([BAND.main[1], BAND.main[0]]);
  const yTicks = y.ticks(4);

  const yc = scaleLinear().domain([0, 100]).range([BAND.coh[1], BAND.coh[0]]);
  const rainMax = Math.max(50, ...data.rain.filter((v): v is number => v !== null));
  const yr = scaleLinear().domain([0, rainMax]).range([BAND.rain[1], BAND.rain[0]]);

  type P = [number, number | null];
  const pts = (vals: (number | null)[]): P[] => vals.map((v, i) => [i, v]);
  const mkLine = line<P>().defined((p) => p[1] !== null).x((p) => x(p[0])).y((p) => y(p[1]!));
  const mkBand = area<P>().defined((p) => p[1] !== null).x((p) => x(p[0])).y0((p) => y(-p[1]!)).y1((p) => y(p[1]!));

  // Coherence as steps: a flat segment across each interval.
  const hasCoh = data.coh.some((v) => v !== null);
  const cohSegs = data.coh.map((v, k) => (v === null ? null : { x0: x(k), x1: x(k + 1), y: yc(v) }));

  // Fire markers sit in the middle of their interval; filled when the state at the interval end is fire_radar.
  const fireMarks = data.fires.map((f, k) => {
    if (!f) return null;
    const agrees = data.state[k + 1] === STATE.fire_radar;
    return { cx: (x(k) + x(k + 1)) / 2, n: f, agrees };
  });

  const modeLabel = t(lang, mode === 'hh' ? 'pulse.legend.hh' : mode === 'hv' ? 'pulse.legend.hv' : 'pulse.legend.ratio');
  const otherLabel = mode === 'hh' ? t(lang, 'pulse.legend.hv') : mode === 'hv' ? t(lang, 'pulse.legend.hh') : null;
  const focus = hover ?? current;
  const f1 = (v: number | null) => (v === null ? '–' : v.toFixed(1));

  return (
    <figure className="pulse-chart" aria-labelledby={`${id}-t`}>
      <figcaption id={`${id}-t`} className="visually-hidden">{title}</figcaption>
      <ul className="pulse-chart__legend" aria-hidden="true">
        <li><span className="key key--main" />{modeLabel}</li>
        {otherLabel && <li><span className="key key--other" />{otherLabel}</li>}
        <li><span className="key key--band" />{t(lang, 'pulse.band', { k: data.changeK })}</li>
        <li><span className="key key--coh" />{t(lang, 'pulse.legend.coh')}</li>
        <li><span className="key key--rain" />{t(lang, 'pulse.legend.rain')}</li>
      </ul>
      <svg viewBox={`0 0 ${W} ${H}`} className="pulse-chart__svg" role="img" aria-label={title}
        onPointerLeave={() => setHover(null)}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const vx = ((e.clientX - r.left) / r.width) * W;
          setHover(Math.max(0, Math.min(n - 1, Math.round(x.invert(vx)))));
        }}>
        <defs>
          <pattern id={`${id}-hatch`} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="5" stroke="var(--rule-strong)" strokeWidth="1.5" />
          </pattern>
        </defs>

        {/* dropped dates: hatched column through every band, so the gap is explained, not blank */}
        {data.dropped.map((dr, i) => dr && (
          <g key={`d${i}`}>
            <rect x={x(i) - step / 2} y={BAND.fire[0]} width={step} height={BAND.rain[1] - BAND.fire[0]} fill={`url(#${id}-hatch)`} opacity="0.6" />
            <text x={x(i)} y={BAND.main[0] + 10} className="pulse-chart__drop" textAnchor="middle">{t(lang, 'pulse.dropped')}</text>
          </g>
        ))}

        {/* band labels */}
        <text x={4} y={BAND.fire[0] + 13} className="pulse-chart__axis">{t(lang, 'pulse.axis.fire')}</text>
        {/* band names sit just above their band, clear of the tick column */}
        <text x={PAD.l} y={BAND.coh[0] - 6} className="pulse-chart__axis">{t(lang, 'pulse.axis.coh')}</text>
        <text x={PAD.l} y={BAND.rain[0] - 6} className="pulse-chart__axis">{t(lang, 'pulse.axis.rain')}</text>

        {/* main band: grid, zero line, noise band, lines */}
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className={t === 0 ? 'pulse-chart__zero' : 'pulse-chart__grid'} />
            <text x={PAD.l - 6} y={y(t) + 4} className="pulse-chart__tick num" textAnchor="end">{t > 0 ? `+${t}` : t}</text>
          </g>
        ))}
        <path d={mkBand(pts(band)) ?? ''} className="pulse-chart__band" />
        {other && <path d={mkLine(pts(other)) ?? ''} className="pulse-chart__other" />}
        <path d={mkLine(pts(main)) ?? ''} className="pulse-chart__main" />
        {main.map((v, i) => v !== null && <circle key={i} cx={x(i)} cy={y(v)} r={i === focus ? 4.5 : 2.5} className="pulse-chart__dot" />)}

        {/* coherence steps, 0 to 100 */}
        <line x1={PAD.l} x2={W - PAD.r} y1={BAND.coh[1]} y2={BAND.coh[1]} className="pulse-chart__grid" />
        <text x={PAD.l - 6} y={BAND.coh[0] + 4} className="pulse-chart__tick num" textAnchor="end">100</text>
        <text x={PAD.l - 6} y={BAND.coh[1] + 4} className="pulse-chart__tick num" textAnchor="end">0</text>
        {hasCoh ? (
          cohSegs.map((s, k) => s && <line key={k} x1={s.x0 + 1} x2={s.x1 - 1} y1={s.y} y2={s.y} className="pulse-chart__coh" />)
        ) : (
          <text
            x={(PAD.l + W - PAD.r) / 2}
            y={(BAND.coh[0] + BAND.coh[1]) / 2 + 4}
            className="pulse-chart__tick"
            textAnchor="middle"
          >
            {t(lang, 'pulse.noCoherence')}
          </text>
        )}

        {/* rain bars per interval */}
        <line x1={PAD.l} x2={W - PAD.r} y1={BAND.rain[1]} y2={BAND.rain[1]} className="pulse-chart__grid" />
        {data.rain.map((v, k) => v !== null && v > 0 && (
          <rect key={k} x={x(k) + 3} width={step - 6} y={yr(v)} height={BAND.rain[1] - yr(v)} rx="1" className="pulse-chart__rain" />
        ))}

        {/* fire markers per interval */}
        {fireMarks.map((m, k) => m && (
          <g key={k}>
            <circle cx={m.cx} cy={(BAND.fire[0] + BAND.fire[1]) / 2} r="7" className={m.agrees ? 'pulse-chart__fire' : 'pulse-chart__fire pulse-chart__fire--silent'} />
            <text x={m.cx + 11} y={(BAND.fire[0] + BAND.fire[1]) / 2 + 4} className="pulse-chart__tick num">{m.n}</text>
          </g>
        ))}

        {/* current pass marker, in sync with the timeline */}
        <line x1={x(current)} x2={x(current)} y1={BAND.fire[0]} y2={BAND.rain[1]} className="pulse-chart__now" />

        {/* date axis */}
        {data.dates.map((d, i) => i % 2 === 0 && (
          <text key={d} x={x(i)} y={H - 6} className="pulse-chart__tick num" textAnchor={i === n - 1 ? 'end' : i === 0 ? 'start' : 'middle'}>{formatDate(d, lang, 'short')}</text>
        ))}
      </svg>

      {/* hover / current readout: text tokens only, identity carried by the keys above */}
      <p className="pulse-chart__readout num" aria-live="off">
        <strong>{formatDate(data.dates[focus], lang)}</strong>
        {' · '}{modeLabel}: {f1(main[focus])}
        {focus > 0 && <>{' · '}{t(lang, 'pulse.axis.coh')}: {hasCoh ? (data.coh[focus - 1] ?? '–') : t(lang, 'pulse.noCoherence')}{' · '}{t(lang, 'pulse.axis.rain')}: {data.rain[focus - 1] ?? '–'}</>}
      </p>
    </figure>
  );
}
