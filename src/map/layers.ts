// MapLibre style and layers for the season map. Verified against node_modules/maplibre-gl/dist/maplibre-gl.d.ts:
// Map#setFeatureState(FeatureIdentifier, state), GeoJSON promoteId, addImage(id, {width,height,data}),
// setPaintProperty, fitBounds, on(type, layerId, listener). Feature-state recolours without rebuilding the source.
import type { FeatureCollection } from 'geojson';
import type { Map as MLMap } from 'maplibre-gl';
import { STATE } from '../contract';
import type { Bundle } from '../data/load';
import { cssVar, STATE_COLOR_VAR } from '../data/states';
import type { Basemap } from '../state/store';

type StyleSpec = Exclude<Parameters<MLMap['setStyle']>[0], string | null>;
// Expressions are built as plain arrays; MapLibre validates them at runtime.
type FillColor = any; // eslint-disable-line @typescript-eslint/no-explicit-any

export const CELLS = 'cells';
export const CELLS_FILL = 'cells-fill';
export const CELLS_HATCH = 'cells-hatch';
export const CELLS_SELECTED = 'cells-selected';
export const CANAL_SELECTED = 'canals-selected';
const HATCH_IMG = 'nodata-hatch';

// Keyless basemap: OpenStreetMap standard tiles. The OSM tile policy allows light use with attribution and a
// browser Referer; CARTO's keyless tiles now return an "API key required" watermark (checked 2026-11-14).
// shortcut: OSM tiles are for low-traffic demos only; switch to a hosted tile provider if the site gets real traffic.
const OSM_TILES = ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'];
const OSM_ATTR = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export const isDark = () => getComputedStyle(document.documentElement).colorScheme === 'dark';

export function buildStyle(b: Bundle, basemap: Basemap): StyleSpec {
  const dark = isDark();
  return {
    version: 8,
    sources: {
      basemap: { type: 'raster', tiles: OSM_TILES, tileSize: 256, attribution: OSM_ATTR, maxzoom: 19 },
      [CELLS]: { type: 'geojson', data: b.cells as unknown as FeatureCollection, promoteId: 'id' },
      context: { type: 'geojson', data: b.contextFeatures as unknown as FeatureCollection },
    },
    layers: [
      { id: 'paper', type: 'background', paint: { 'background-color': cssVar('--paper') } },
      // Greyed and faded so street colours never compete with the state colours.
      { id: 'basemap', type: 'raster', source: 'basemap', layout: { visibility: basemap === 'osm' ? 'visible' : 'none' }, paint: { 'raster-saturation': -1, 'raster-opacity': dark ? 0.25 : 0.45 } },
      { id: CELLS_FILL, type: 'fill', source: CELLS, paint: { 'fill-color': stateColorExpr(), 'fill-opacity': 0.88 } },
      // fill-pattern is set in addHatchImage(), after the image exists.
      { id: CELLS_HATCH, type: 'fill', source: CELLS, filter: ['==', ['literal', 1], 0], paint: { 'fill-opacity': 1 } },
      { id: 'canals', type: 'line', source: 'context', filter: ['==', ['get', 'kind'], 'canal'], paint: { 'line-color': cssVar('--canal'), 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.6, 13, 1.6], 'line-opacity': 0.8 } },
      { id: CANAL_SELECTED, type: 'line', source: 'context', filter: ['==', ['get', 'id'], ''], paint: { 'line-color': cssVar('--s-fire'), 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 3, 13, 5], 'line-opacity': 1 } },
      { id: 'river', type: 'line', source: 'context', filter: ['==', ['get', 'kind'], 'river'], paint: { 'line-color': cssVar('--river'), 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 2.5, 13, 6] } },
      { id: 'dams', type: 'circle', source: 'context', filter: ['==', ['get', 'kind'], 'dam'], paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 2.5, 13, 5], 'circle-color': cssVar('--paper-raised'), 'circle-stroke-color': cssVar('--ink'), 'circle-stroke-width': 1.5 } },
      { id: 'town', type: 'circle', source: 'context', filter: ['==', ['get', 'kind'], 'town'], paint: { 'circle-radius': 5, 'circle-color': cssVar('--ink'), 'circle-stroke-color': cssVar('--paper'), 'circle-stroke-width': 2 } },
      // "Fire, radar silent" is drawn hollow: a red outline over a faint fill (PRD 9).
      { id: 'cells-silent', type: 'line', source: CELLS, paint: { 'line-color': cssVar('--s-fire'), 'line-width': 1.5, 'line-opacity': ['case', ['==', ['feature-state', 's'], STATE.fire_silent], 1, 0] } },
      { id: CELLS_SELECTED, type: 'line', source: CELLS, filter: ['==', ['get', 'id'], ''], paint: { 'line-color': cssVar('--ink'), 'line-width': 3 } },
    ],
  };
}

/** Colour by feature-state "s" (the state code). Missing state draws as no data. */
export function stateColorExpr(): FillColor {
  const pairs: (number | string)[] = [];
  for (const code of Object.values(STATE)) pairs.push(code, cssVar(STATE_COLOR_VAR[code]));
  return ['match', ['coalesce', ['feature-state', 's'], STATE.no_data], ...pairs, cssVar('--s-nodata')] as FillColor;
}

/** Fire-silent cells show a red outline only (hollow), matching the PRD's "red outline, hollow symbol". */
export function hollowOpacityExpr(): FillColor {
  return ['case', ['==', ['feature-state', 's'], STATE.fire_silent], 0.15, 0.88] as FillColor;
}

export function addHatchImage(map: MLMap) {
  if (map.hasImage(HATCH_IMG)) return;
  // Pattern must be opaque where drawn and transparent elsewhere: diagonal hatch lines only.
  const size = 8;
  const data = new Uint8Array(size * size * 4);
  const hex = cssVar('--s-nodata-hatch').replace('#', '');
  const [r, g, bl] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++)
      if ((x + y) % size < 2) data.set([r, g, bl, 255], (y * size + x) * 4);
  map.addImage(HATCH_IMG, { width: size, height: size, data });
  map.setPaintProperty(CELLS_HATCH, 'fill-pattern', HATCH_IMG);
}

/** Push one date's states into feature-state. ~6k calls; measured in docs/LOG.md. */
export function applyStates(map: MLMap, b: Bundle, t: number) {
  const ids = b.series.cells;
  const rows = b.series.state;
  for (let i = 0; i < ids.length; i++) map.setFeatureState({ source: CELLS, id: ids[i] }, { s: rows[i][t] });
}

/** Hatch layer shows exactly the no-data cells for the current date. */
export function setHatchFilter(map: MLMap, b: Bundle, t: number) {
  const ids = b.series.cells.filter((_, i) => b.series.state[i][t] === STATE.no_data);
  map.setFilter(CELLS_HATCH, ['in', ['get', 'id'], ['literal', ids]]);
}

export function setSelected(map: MLMap, id: string | null) {
  map.setFilter(CELLS_SELECTED, ['==', ['get', 'id'], id ?? '']);
}

export function setSelectedCanal(map: MLMap, id: string | null) {
  if (map.getLayer(CANAL_SELECTED)) {
    map.setFilter(CANAL_SELECTED, ['==', ['get', 'id'], id ?? '']);
  }
}

/**
 * Re-read every colour token after a theme change. MapLibre holds resolved colours, not CSS variables,
 * so the paint properties are updated in place; the map, its sources and its feature-state stay as they are.
 * `cellFill` is the current layer's fill expression (state colours or a ramp), rebuilt by the caller.
 */
export function repaint(map: MLMap, cellFill: FillColor) {
  const dark = isDark();
  map.setPaintProperty('paper', 'background-color', cssVar('--paper'));
  map.setPaintProperty('basemap', 'raster-opacity', dark ? 0.25 : 0.45);
  map.setPaintProperty(CELLS_FILL, 'fill-color', cellFill);
  map.setPaintProperty('canals', 'line-color', cssVar('--canal'));
  if (map.getLayer(CANAL_SELECTED)) map.setPaintProperty(CANAL_SELECTED, 'line-color', cssVar('--s-fire'));
  map.setPaintProperty('river', 'line-color', cssVar('--river'));
  map.setPaintProperty('dams', 'circle-color', cssVar('--paper-raised'));
  map.setPaintProperty('dams', 'circle-stroke-color', cssVar('--ink'));
  map.setPaintProperty('town', 'circle-color', cssVar('--ink'));
  map.setPaintProperty('town', 'circle-stroke-color', cssVar('--paper'));
  map.setPaintProperty('cells-silent', 'line-color', cssVar('--s-fire'));
  map.setPaintProperty(CELLS_SELECTED, 'line-color', cssVar('--ink'));
  // Hatch pattern colour also follows the theme.
  if (map.hasImage(HATCH_IMG)) {
    const size = 8;
    const data = new Uint8Array(size * size * 4);
    const hex = cssVar('--s-nodata-hatch').replace('#', '');
    const [r, g, bl] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if ((x + y) % size < 2) data.set([r, g, bl, 255], (y * size + x) * 4);
    map.updateImage(HATCH_IMG, { width: size, height: size, data });
  }
}

/** Show cells or the radar picture; context lines stay on top of both. */
export function setCellsVisible(map: MLMap, visible: boolean) {
  const v = visible ? 'visible' : 'none';
  for (const id of [CELLS_FILL, CELLS_HATCH, 'cells-silent']) map.setLayoutProperty(id, 'visibility', v);
}
