// Map-side helpers for the HH, HV, coherence and radar-picture layers. Wired into SeasonMap in the polish step.
// APIs checked in node_modules/maplibre-gl/dist/maplibre-gl.d.ts: setFeatureState, setPaintProperty,
// setLayoutProperty, addSource (ImageSourceSpecification: type, url, coordinates), ImageSource#updateImage({url}),
// getLayer, getSource. Image coordinates: top-left, then clockwise (matches manifest images.bounds).
import type { ImageSource, Map as MLMap } from 'maplibre-gl';
import type { Bundle } from '../data/load';
import { valuesAtDate } from '../data/selectors';
import type { LayerId } from '../state/hash';
import { type RampLayer, rampColorExpr } from './ramps';

export const RADAR_SRC = 'radar-img';
export const RADAR_LAYER = 'radar-img';

/** Feature-state "v" for a continuous layer: HH/HV in dB (tenths / 10), coherence 0..100. */
export function applyValues(map: MLMap, b: Bundle, layer: RampLayer, t: number, source: string) {
  const vals = valuesAtDate(b, layer, t);
  const ids = b.series.cells;
  const scale = layer === 'coh' ? 1 : 0.1;
  for (let i = 0; i < ids.length; i++) map.setFeatureState({ source, id: ids[i] }, { v: vals[i] === null ? null : vals[i]! * scale });
}

/** The cell fill's colour expression for the current layer. State layer keeps its own expression. */
export const fillColorFor = (layer: RampLayer, noData: string) => rampColorExpr(layer, noData);

export function radarFile(b: Bundle, t: number): string | null {
  const date = b.manifest.dates[t];
  const entry = b.manifest.images.radar.find((r) => r.date === date);
  return entry ? b.imageUrl(entry.file) : null;
}

/** Add the radar-picture source and layer once, hidden, just below the context lines. */
export function addRadarLayer(map: MLMap, b: Bundle, beforeId: string) {
  if (map.getSource(RADAR_SRC)) return;
  const url = radarFile(b, 0);
  if (!url) return;
  map.addSource(RADAR_SRC, { type: 'image', url, coordinates: b.manifest.images.bounds });
  map.addLayer({ id: RADAR_LAYER, type: 'raster', source: RADAR_SRC, layout: { visibility: 'none' }, paint: { 'raster-fade-duration': 0, 'raster-resampling': 'nearest' } }, beforeId);
}

/**
 * Point the radar picture at date t and warm the browser cache for t+1 (PRD 8.2 "preload the next date's image").
 * A date with no picture hides the layer, so the previous pass's picture never shows under the wrong date.
 */
export function showRadar(map: MLMap, b: Bundle, t: number) {
  const src = map.getSource<ImageSource>(RADAR_SRC);
  const url = radarFile(b, t);
  if (src && url) src.updateImage({ url });
  if (map.getLayer(RADAR_LAYER)) map.setLayoutProperty(RADAR_LAYER, 'visibility', url ? 'visible' : 'none');
  const next = radarFile(b, t + 1);
  if (next) new Image().src = next;
}

/** Which map layers are visible for each app layer. */
export function visibilityFor(layer: LayerId) {
  return { cells: layer !== 'radar', radar: layer === 'radar' };
}
