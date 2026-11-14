// Colour ramps for the continuous map layers (PRD 7.2 "layer"). Display only: they colour values the bundle already holds.
// HH/HV are diverging around 0 dB: drier (brown-orange) below, wetter (blue) above, grey "no change" midpoint.
// Coherence is sequential, one hue (teal), light = low, dark = high.
// Fixed domains so colours mean the same thing on every pass and on every bundle.

export type RampLayer = 'hh' | 'hv' | 'coh';

interface Ramp {
  domain: [number, number];
  unit: string;
  /** colour at the domain's low end, middle steps, and high end */
  stops: [number, string][];
  neutral?: string;
}

export const LAYER_RAMPS: Record<RampLayer, Ramp> = {
  hh: {
    domain: [-4, 1],
    unit: 'dB',
    neutral: '#d9d8d2',
    stops: [[-4, '#7a3410'], [-3, '#a8501d'], [-2, '#c97a3f'], [-1, '#e2b07a'], [0, '#d9d8d2'], [0.5, '#8fb7d9'], [1, '#2f72b3']],
  },
  hv: {
    domain: [-4, 1],
    unit: 'dB',
    neutral: '#d9d8d2',
    stops: [[-4, '#7a3410'], [-3, '#a8501d'], [-2, '#c97a3f'], [-1, '#e2b07a'], [0, '#d9d8d2'], [0.5, '#8fb7d9'], [1, '#2f72b3']],
  },
  coh: {
    domain: [0, 100],
    unit: '',
    stops: [[0, '#e3efed'], [25, '#a9d1cb'], [50, '#5fa9a2'], [75, '#2b7d78'], [100, '#0b4f4c']],
  },
};

export const rampStops = (layer: RampLayer) => LAYER_RAMPS[layer].stops.map(([value, color]) => ({ value, color }));

/**
 * MapLibre fill-color: interpolate feature-state "v" (the layer's value in display units) along the ramp,
 * falling back to the no-data colour when "v" is missing.
 * Expression shape follows the MapLibre style spec ('case', 'interpolate', 'feature-state').
 */
export function rampColorExpr(layer: RampLayer, noData: string): unknown {
  const flat = LAYER_RAMPS[layer].stops.flatMap(([v, c]) => [v, c]);
  return ['case', ['==', ['typeof', ['feature-state', 'v']], 'number'], ['interpolate', ['linear'], ['feature-state', 'v'], ...flat], noData];
}

/** CSS linear-gradient for the legend bar, left = domain low. */
export function rampGradient(layer: RampLayer): string {
  const { domain, stops } = LAYER_RAMPS[layer];
  const span = domain[1] - domain[0];
  return `linear-gradient(to right, ${stops.map(([v, c]) => `${c} ${(((v - domain[0]) / span) * 100).toFixed(1)}%`).join(', ')})`;
}
