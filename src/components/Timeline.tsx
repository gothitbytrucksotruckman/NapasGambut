import { useEffect, type KeyboardEvent } from 'react';
import { droppedReason, isDropped } from '../data/selectors';
import { formatDate, t } from '../i18n';
import { useApp } from '../state/store';
import { PassRuler } from './PassRuler';
import './Timeline.css';

const Icon = ({ d }: { d: string }) => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d={d} fill="currentColor" /></svg>
);
const PLAY = 'M4 2 L14 8 L4 14 Z';
const PAUSE = 'M3 2 H6.5 V14 H3 Z M9.5 2 H13 V14 H9.5 Z';
const PREV = 'M12 2 L5 8 L12 14 Z M3 2 H5 V14 H3 Z';
const NEXT = 'M4 2 L11 8 L4 14 Z M11 2 H13 V14 H11 Z';

/** One tick per pass, dropped pass hatched, play/pause and step (PRD 8.2). */
export function Timeline() {
  const { state, bundle, dispatch } = useApp();
  const { dates } = bundle.manifest;
  const n = dates.length;
  const i = state.dateIndex;
  const dropped = dates.map((_, k) => isDropped(bundle, k));
  const lang = state.lang;
  const valueText = `${formatDate(dates[i], lang)}, ${t(lang, 'timeline.pass', { i: i + 1, n })}${dropped[i] ? `. ${t(lang, 'timeline.dropped')}` : ''}`;

  // Space toggles play anywhere on the map screen, unless focus is in a form control or on a button.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.code !== 'Space') return;
      const tag = (e.target as HTMLElement).tagName;
      if (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'A'].includes(tag)) return;
      e.preventDefault();
      dispatch({ type: 'togglePlay' });
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [dispatch]);

  const onSliderKey = (e: KeyboardEvent) => {
    const go = (k: number) => { e.preventDefault(); dispatch({ type: 'setDate', index: k }); dispatch({ type: 'stop' }); };
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') go(i - 1);
    else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') go(i + 1);
    else if (e.key === 'Home') go(0);
    else if (e.key === 'End') go(n - 1);
  };

  const pick = (clientX: number, target: HTMLElement) => {
    const r = target.getBoundingClientRect();
    const k = Math.floor(((clientX - r.left) / r.width) * n);
    dispatch({ type: 'setDate', index: k });
    dispatch({ type: 'stop' });
  };

  return (
    <div className="timeline">
      <div className="timeline__buttons">
        <button type="button" className="btn" onClick={() => dispatch({ type: 'step', delta: -1 })} disabled={i === 0} aria-label={t(lang, 'timeline.prev')}>
          <Icon d={PREV} />
        </button>
        <button type="button" className="btn btn--primary timeline__play" onClick={() => dispatch({ type: 'togglePlay' })}
          aria-label={state.playing ? t(lang, 'timeline.pause') : t(lang, 'timeline.play')}>
          <Icon d={state.playing ? PAUSE : PLAY} />
        </button>
        <button type="button" className="btn" onClick={() => dispatch({ type: 'step', delta: 1 })} disabled={i === n - 1} aria-label={t(lang, 'timeline.next')}>
          <Icon d={NEXT} />
        </button>
      </div>

      <div className="timeline__track">
        <div className="timeline__readout">
          <span className="timeline__date">{formatDate(dates[i], lang)}</span>
          <span className="timeline__pass num">{t(lang, 'timeline.pass', { i: i + 1, n })}</span>
          {dropped[i] && <span className="timeline__droptag">{t(lang, 'timeline.dropped')}</span>}
        </div>
        <div
          className="timeline__slider"
          role="slider"
          tabIndex={0}
          aria-label={t(lang, 'timeline.label')}
          aria-valuemin={1}
          aria-valuemax={n}
          aria-valuenow={i + 1}
          aria-valuetext={valueText}
          aria-describedby="timeline-help"
          onKeyDown={onSliderKey}
          onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); pick(e.clientX, e.currentTarget); }}
          onPointerMove={(e) => { if (e.buttons) pick(e.clientX, e.currentTarget); }}
        >
          <PassRuler dates={dates} dropped={dropped} current={i} height={30} />
          <div className="timeline__labels" aria-hidden="true">
            {dates.map((d, k) => (
              <span key={d} className={k === i ? 'is-current' : undefined} title={dropped[k] ? droppedReason(bundle, k, lang) ?? undefined : undefined}>
                {k % 2 === 0 || k === i ? formatDate(d, lang, 'short') : ''}
              </span>
            ))}
          </div>
        </div>
        <p id="timeline-help" className="visually-hidden">{t(lang, 'timeline.help')}</p>
      </div>
    </div>
  );
}
