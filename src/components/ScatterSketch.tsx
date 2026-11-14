// Small hand-drawn sketch of the scattering mechanism for each line mode (PRD 8.3).
// HH: pulse hits wet ground and bounces straight back. HV: pulse scatters in the canopy and returns twisted.
import { t } from '../i18n';
import type { Lang } from '../state/hash';
import type { LineMode } from './PulseChart';

const Sat = () => <path d="M10 8 h14 v8 h-14 Z M4 12 h6 M24 12 h6" className="sk-ink" />;

export function ScatterSketch({ mode, lang }: { mode: LineMode; lang: Lang }) {
  const label = t(lang, mode === 'hh' ? 'pulse.sketch.hh' : mode === 'hv' ? 'pulse.sketch.hv' : 'pulse.sketch.ratio');
  return (
    <svg className="scatter-sketch" viewBox="0 0 120 80" role="img" aria-label={label}>
      <style>{`
        .sk-ink{fill:none;stroke:var(--ink);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
        .sk-pulse{fill:none;stroke:var(--radar);stroke-width:1.75;stroke-linecap:round}
        .sk-water{fill:var(--river);opacity:.35}
        .sk-leaf{fill:var(--s-stable)}
      `}</style>
      <Sat />
      <path d="M0 70 Q15 66 30 70 T60 70 T90 70 T120 70" className="sk-ink" />
      {(mode === 'hh' || mode === 'ratio') && (
        <g>
          <rect x="34" y="68" width="50" height="6" className="sk-water" />
          {/* out and straight back */}
          <path d="M22 18 L58 66" className="sk-pulse" />
          <path d="M60 66 L26 20" className="sk-pulse" strokeDasharray="3 3" />
        </g>
      )}
      {(mode === 'hv' || mode === 'ratio') && (
        <g transform={mode === 'ratio' ? 'translate(28 0)' : undefined}>
          <path d="M80 70 V40 M80 52 L70 44 M80 46 L90 38" className="sk-ink" />
          <circle cx="70" cy="42" r="6" className="sk-leaf" />
          <circle cx="88" cy="36" r="7" className="sk-leaf" />
          <circle cx="80" cy="32" r="6" className="sk-leaf" />
          <path d="M22 16 L72 36" className="sk-pulse" />
          {/* twisted return: a small zig-zag */}
          <path d="M74 34 l-6 -6 l4 -2 l-6 -6 l4 -2 L28 18" className="sk-pulse" strokeDasharray="3 3" />
        </g>
      )}
    </svg>
  );
}
