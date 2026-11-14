// Legend for a continuous layer: gradient bar, end labels, and a plain-words reading of each end.
import type { Lang } from '../state/hash';
import { LAYER_RAMPS, type RampLayer, rampGradient } from './ramps';
import { type Key, t } from '../i18n';

export function RampLegend({ layer, lang }: { layer: RampLayer; lang: Lang }) {
  const { domain, unit } = LAYER_RAMPS[layer];
  const fmt = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v)}${unit ? ` ${unit}` : ''}`;
  return (
    <section className="ramp-legend" aria-labelledby="ramp-h">
      <h2 id="ramp-h" className="legend__title">{t(lang, `layer.${layer}.title` as Key)}</h2>
      <p className="ramp-legend__what">{t(lang, `layer.${layer}.what` as Key)}</p>
      <div className="ramp-legend__bar" style={{ background: rampGradient(layer) }} aria-hidden="true" />
      <div className="ramp-legend__ends num">
        <span>{fmt(domain[0])}<br /><small>{t(lang, `layer.${layer}.low` as Key)}</small></span>
        <span>{fmt(domain[1])}<br /><small>{t(lang, `layer.${layer}.high` as Key)}</small></span>
      </div>
      <p className="ramp-legend__note">{t(lang, 'layer.clamp')}</p>
    </section>
  );
}
