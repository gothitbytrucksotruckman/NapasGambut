import { STATE } from '../contract';
import { countsByState } from '../data/selectors';
import { STATE_COLOR_VAR, STATE_ORDER } from '../data/states';
import { formatNumber, t } from '../i18n';
import { useApp } from '../state/store';
import './Legend.css';

/** Swatch per state. Fire-radar is filled, fire-silent hollow, no-data hatched, so colour is never the only cue. */
export function Swatch({ code }: { code: number }) {
  const color = `var(${STATE_COLOR_VAR[code]})`;
  if (code === STATE.fire_silent)
    return <svg className="swatch" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" fill="none" stroke={color} strokeWidth="2.5" /></svg>;
  if (code === STATE.fire_radar)
    return <svg className="swatch" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill={color} /></svg>;
  if (code === STATE.no_data)
    return (
      <svg className="swatch" viewBox="0 0 16 16" aria-hidden="true">
        <rect x="0.5" y="0.5" width="15" height="15" fill={color} stroke="var(--s-nodata-hatch)" />
        <path d="M0 16 L16 0 M-4 12 L12 -4 M4 20 L20 4" stroke="var(--s-nodata-hatch)" strokeWidth="1.5" />
      </svg>
    );
  return <svg className="swatch" viewBox="0 0 16 16" aria-hidden="true"><rect width="16" height="16" fill={color} /></svg>;
}

/** Legend with live counts. It doubles as the map's text alternative (PRD 11). */
export function Legend({ title }: { title: string }) {
  const { state, bundle } = useApp();
  const counts = countsByState(bundle, state.dateIndex);
  const total = bundle.series.cells.length;
  const max = Math.max(...Object.values(counts), 1);
  return (
    <section className="legend" aria-labelledby="legend-title">
      <h2 id="legend-title" className="legend__title">{title}</h2>
      <p className="legend__total num">{t(state.lang, 'counts.total', { n: formatNumber(total, state.lang) })}</p>
      <ul className="legend__list" aria-live="polite">
        {STATE_ORDER.map((code) => (
          <li key={code} className="legend__row">
            <Swatch code={code} />
            <span className="legend__label">{t(state.lang, `state.${code}` as `state.${1 | 2 | 3 | 4 | 5 | 6 | 7 | 8}`)}</span>
            <span className="legend__count num">{formatNumber(counts[code], state.lang)}</span>
            <span className="legend__bar" aria-hidden="true">
              <span style={{ width: `${(counts[code] / max) * 100}%`, background: `var(${STATE_COLOR_VAR[code]})` }} />
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
