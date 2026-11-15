// Pulse card (PRD 8.3): side panel on desktop, bottom sheet on phones. Opens over the map, never leaves it.
import { useEffect, useRef, useState } from 'react';
import { CopyLink } from '../components/CopyLink';
import { Swatch } from '../components/Legend';
import { type LineMode, mainSeries, PulseChart, type PulseData } from '../components/PulseChart';
import { ScatterSketch } from '../components/ScatterSketch';
import type { CoverId } from '../contract';
import { coverView } from '../data/models';
import { readingFor } from '../data/reading';
import { cellSeries, isDropped } from '../data/selectors';
import { formatDate, formatNumber, type Key, t } from '../i18n';
import { useApp } from '../state/store';
import './PulseCard.css';

const MODES: LineMode[] = ['hh', 'hv', 'ratio'];
const MODE_KEY: Record<LineMode, Key> = { hh: 'pulse.mode.hh', hv: 'pulse.mode.hv', ratio: 'pulse.mode.ratio' };
const EXPLAIN_KEY: Record<LineMode, Key> = { hh: 'pulse.explain.hh', hv: 'pulse.explain.hv', ratio: 'pulse.explain.ratio' };

// Shape cues for the radar cover row, so the cases differ by more than wording.
const CantTellSymbol = () => (
  <svg className="pulse__sym" viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
    <path d="M6 6.2 a2 2 0 1 1 2.6 1.9 c-0.5 0.2 -0.6 0.5 -0.6 1.1 v0.6" fill="none" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="8" cy="11.6" r="0.9" fill="currentColor" />
  </svg>
);
const SeveralSymbol = () => (
  <svg className="pulse__sym" viewBox="0 0 16 16" aria-hidden="true">
    <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
    <rect x="5.5" y="5.5" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);
const FlagSymbol = () => (
  <svg className="pulse__sym" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M3 15 V1.5" stroke="currentColor" strokeWidth="1.5" />
    <path d="M3.75 2 H13 L10.5 5 L13 8 H3.75 Z" fill="currentColor" />
  </svg>
);

export function PulseCard() {
  const { state, bundle, dispatch } = useApp();
  const { lang, selectedCell, dateIndex } = state;
  const [mode, setMode] = useState<LineMode>('hh');
  const panel = useRef<HTMLElement>(null);
  const close = () => dispatch({ type: 'select', cell: null });

  // Escape closes; focus moves into the panel when a new cell opens.
  useEffect(() => {
    if (!selectedCell) return;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCell]);

  if (!selectedCell) return null;
  const cs = cellSeries(bundle, selectedCell);
  if (!cs) {
    return (
      <aside className="pulse" ref={panel} tabIndex={-1} aria-label={t(lang, 'pulse.title', { id: selectedCell })}>
        <p>{t(lang, 'pulse.notFound')}</p>
        <button type="button" className="btn" onClick={close}>{t(lang, 'pulse.close')}</button>
      </aside>
    );
  }

  const { manifest, context } = bundle;
  const data: PulseData = {
    dates: manifest.dates,
    hh: cs.hh, hv: cs.hv, coh: cs.coh, fires: cs.fires, state: cs.state,
    sigma: manifest.thresholds.sigma_db,
    changeK: manifest.thresholds.change_k,
    rain: context.rain_interval_mm,
    dropped: manifest.dates.map((_, i) => isDropped(bundle, i)),
  };
  const p = cs.props;
  const cover = coverView(p, manifest.land_model);
  const coverLabel = (c: CoverId) => t(lang, `cover.${c}`);
  const reading = readingFor(cs.state, manifest.dates, lang);
  const title = t(lang, 'pulse.chartTitle', { id: selectedCell });
  const stateKey = (c: number) => `state.${c}` as `state.${1 | 2 | 3 | 4 | 5 | 6 | 7 | 8}`;
  const hh = mainSeries(data, 'hh'), hv = mainSeries(data, 'hv');
  const f1 = (v: number | null) => (v === null ? '' : v.toFixed(1));
  const rain3d = (i: number) => {
    const v = context.rain_3day_mm[i];
    return v === null || v === undefined ? '' : String(v);
  };

  return (
    <aside className="pulse" ref={panel} tabIndex={-1} aria-labelledby="pulse-h">
      <header className="pulse__head">
        <div>
          <h2 id="pulse-h" className="pulse__title num">{t(lang, 'pulse.title', { id: selectedCell })}</h2>
          <p className="pulse__now">
            <Swatch code={cs.state[dateIndex]} />
            <span>{formatDate(manifest.dates[dateIndex], lang)}: {t(lang, stateKey(cs.state[dateIndex]))}</span>
          </p>
        </div>
        <button type="button" className="btn pulse__close" onClick={close} aria-label={t(lang, 'pulse.close')}>
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 2 L12 12 M12 2 L2 12" stroke="currentColor" strokeWidth="2" /></svg>
        </button>
      </header>

      <p className="pulse__reading">{reading}</p>

      <fieldset className="pulse__modes">
        <legend className="visually-hidden">{t(lang, 'pulse.lineLabel')}</legend>
        {MODES.map((m) => (
          <label key={m} className={m === mode ? 'is-on' : undefined}>
            <input type="radio" name="pulse-mode" value={m} checked={m === mode} onChange={() => setMode(m)} />
            {t(lang, MODE_KEY[m])}
          </label>
        ))}
      </fieldset>

      <PulseChart data={data} mode={mode} current={dateIndex} lang={lang} title={title} />

      <div className="pulse__explain">
        <ScatterSketch mode={mode} lang={lang} />
        <p>{t(lang, EXPLAIN_KEY[mode]).split('\n').map((line, i) => <span key={i}>{line}</span>)}</p>
      </div>

      <dl className="pulse__facts">
        <div><dt>{t(lang, 'pulse.class')}</dt><dd>{t(lang, `class.${p.class}` as Key)}</dd></div>
        {cover && (
          <div>
            <dt>{t(lang, 'pulse.cover')}</dt>
            <dd>
              <span className="pulse__cover">
                {cover.kind === 'cant_tell' && <CantTellSymbol />}
                {cover.kind === 'several' && <SeveralSymbol />}
                <span>
                  {cover.kind === 'cant_tell' ? t(lang, 'pulse.coverCantTell')
                    : cover.kind === 'one' ? coverLabel(cover.covers[0])
                    : t(lang, 'pulse.coverSeveral', { list: cover.covers.map(coverLabel).join(', ') })}
                  {cover.simulated && ` ${t(lang, 'pulse.coverSimulated')}`}
                </span>
              </span>
              <span className="pulse__hint">{t(lang, 'pulse.coverHint')}</span>
              {cover.mapCheck && (
                <span className="pulse__mapcheck">
                  <FlagSymbol />
                  <span>{t(lang, 'pulse.mapCheck', { map: coverLabel(cover.mapCheck.map), radar: coverLabel(cover.mapCheck.radar) })}</span>
                </span>
              )}
            </dd>
          </div>
        )}
        <div><dt>{t(lang, 'pulse.canal')}</dt><dd className="num">{p.canal_density_km_per_km2.toFixed(2)} {t(lang, 'pulse.canalUnit')}</dd></div>
        <div><dt>{t(lang, 'pulse.tree')}</dt><dd className="num">{formatNumber(p.tree_cover_pct, lang)}%</dd></div>
        <div><dt>{t(lang, 'pulse.pixels')}</dt><dd className="num">{t(lang, 'pulse.pixelsOf', { n: p.n_pixels })}</dd></div>
      </dl>

      <details className="pulse__table">
        <summary>{t(lang, 'pulse.table')}</summary>
        <div className="pulse__tablewrap">
          <table className="num">
            <thead>
              <tr>
                <th scope="col">{t(lang, 'pulse.th.date')}</th>
                <th scope="col">{t(lang, 'pulse.th.state')}</th>
                <th scope="col">{t(lang, 'pulse.th.hh')}</th>
                <th scope="col">{t(lang, 'pulse.th.hv')}</th>
                <th scope="col">{t(lang, 'pulse.th.coh')}</th>
                <th scope="col">{t(lang, 'pulse.th.rain')}</th>
                <th scope="col">{t(lang, 'pulse.th.rain3d')}</th>
                <th scope="col">{t(lang, 'pulse.th.fire')}</th>
              </tr>
            </thead>
            <tbody>
              {manifest.dates.map((d, i) => (
                <tr key={d} aria-current={i === dateIndex ? 'true' : undefined}>
                  <th scope="row">{formatDate(d, lang, 'short')}</th>
                  <td>{t(lang, stateKey(cs.state[i]))}</td>
                  <td>{f1(hh[i])}</td>
                  <td>{f1(hv[i])}</td>
                  <td>{i > 0 ? cs.coh[i - 1] ?? '' : ''}</td>
                  <td>{i > 0 ? context.rain_interval_mm[i - 1] ?? '' : ''}</td>
                  <td>{rain3d(i)}</td>
                  <td>{i > 0 && cs.fires[i - 1] ? cs.fires[i - 1] : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <CopyLink lang={lang} />
    </aside>
  );
}
