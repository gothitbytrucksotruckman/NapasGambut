// Legend for a continuous layer: gradient bar, end labels, and a plain-words reading of each end.
import type { Lang } from '../state/hash';
import { LAYER_RAMPS, type RampLayer, rampGradient } from './ramps';
import { tl } from './strings';

export function RampLegend({ layer, lang }: { layer: RampLayer; lang: Lang }) {
  const { domain, unit } = LAYER_RAMPS[layer];
  const fmt = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v)}${unit ? ` ${unit}` : ''}`;
  return (
    <section className="ramp-legend" aria-labelledby="ramp-h">
      <h2 id="ramp-h" className="legend__title">{tl(lang, `layer.${layer}.title`)}</h2>
      <p className="ramp-legend__what">{tl(lang, `layer.${layer}.what`)}</p>
      <div className="ramp-legend__bar" style={{ background: rampGradient(layer) }} aria-hidden="true" />
      <div className="ramp-legend__ends num">
        <span>{fmt(domain[0])}<br /><small>{tl(lang, `layer.${layer}.low`)}</small></span>
        <span>{fmt(domain[1])}<br /><small>{tl(lang, `layer.${layer}.high`)}</small></span>
      </div>
      <p className="ramp-legend__note">{tl(lang, 'layer.clamp')}</p>
    </section>
  );
}
