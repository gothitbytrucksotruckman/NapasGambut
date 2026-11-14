import { Map as MLMap, type MapLayerMouseEvent, NavigationControl, setWorkerUrl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { useEffect, useRef, useState } from 'react';
import { Legend } from '../components/Legend';
import { Timeline } from '../components/Timeline';
import { droppedReason, hasCoherence, isDropped } from '../data/selectors';
import { formatDate, t } from '../i18n';
import { LayerSwitch } from '../layers/LayerSwitch';
import { addRadarLayer, applyValues, fillColorFor, RADAR_LAYER, showRadar } from '../layers/mapLayers';
import { RampLegend } from '../layers/RampLegend';
import type { RampLayer } from '../layers/ramps';
import { cssVar } from '../data/states';
import {
  addHatchImage, applyStates, buildStyle, CELLS, CELLS_FILL, hollowOpacityExpr, repaint, setCellsVisible, setHatchFilter,
  setSelected, stateColorExpr,
} from '../map/layers';
import { useApp } from '../state/store';
import { PulseCard } from './PulseCard';
import './SeasonMap.css';

// MapLibre locates its worker relative to its own module URL; Vite's dep pre-bundling moves the module, so point at the real file.
setWorkerUrl(workerUrl);

const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

function hasWebGL() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

export function SeasonMap() {
  const { state, bundle, dispatch } = useApp();
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [webgl] = useState(hasWebGL);
  const { lang, dateIndex, selectedCell, basemap, layer } = state;
  // Bumped when the theme changes, so map colours are re-read from the tokens.
  const [themeTick, setThemeTick] = useState(0);
  useEffect(() => {
    const mo = new MutationObserver(() => setThemeTick((n) => n + 1));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const mq = matchMedia('(prefers-color-scheme: dark)');
    const onMq = () => setThemeTick((n) => n + 1);
    mq.addEventListener('change', onMq);
    return () => { mo.disconnect(); mq.removeEventListener('change', onMq); };
  }, []);

  // Create the map once.
  useEffect(() => {
    if (!el.current || !webgl) return;
    const [w, s, e, n] = bundle.manifest.study_area.bbox;
    const map = new MLMap({
      container: el.current,
      style: buildStyle(bundle, basemap),
      bounds: [[w, s], [e, n]],
      fitBoundsOptions: { padding: 24 },
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      attributionControl: { compact: true },
    });
    map.touchZoomRotate.disableRotation();
    // Bottom-left: the pulse card opens on the right and would cover top-right controls.
    map.addControl(new NavigationControl({ showCompass: false }), 'bottom-left');
    map.on('load', () => {
      addHatchImage(map);
      map.setPaintProperty(CELLS_FILL, 'fill-opacity', hollowOpacityExpr());
      addRadarLayer(map, bundle, 'canals');
      setReady(true);
    });
    map.on('click', CELLS_FILL, (ev: MapLayerMouseEvent) => {
      const id = ev.features?.[0]?.properties?.id;
      if (typeof id === 'string') dispatch({ type: 'select', cell: id });
    });
    map.on('mouseenter', CELLS_FILL, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', CELLS_FILL, () => { map.getCanvas().style.cursor = ''; });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // basemap changes are applied below without rebuilding the map
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bundle, webgl]);

  // Recolour on date or layer change: feature-state only, the source is never rebuilt.
  // State codes always go in ("s": hollow fire outline, no-data hatch); continuous values go in as "v".
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    applyStates(map, bundle, dateIndex);
    setHatchFilter(map, bundle, dateIndex);
    if (layer === 'hh' || layer === 'hv' || layer === 'coh') applyValues(map, bundle, layer, dateIndex, CELLS);
    if (layer === 'radar') showRadar(map, bundle, dateIndex);
  }, [ready, bundle, dateIndex, layer]);

  // Layer and theme: swap the fill expression, show cells or the radar picture, re-read colour tokens.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const ramp = layer === 'hh' || layer === 'hv' || layer === 'coh';
    const fill = ramp ? fillColorFor(layer, cssVar('--s-nodata')) : stateColorExpr();
    repaint(map, fill);
    // Ramps colour every cell by value; hollow fire and opacity tricks only belong to the state layer.
    map.setPaintProperty(CELLS_FILL, 'fill-opacity', ramp ? 0.9 : hollowOpacityExpr());
    map.setLayoutProperty('cells-silent', 'visibility', layer === 'state' ? 'visible' : 'none');
    setCellsVisible(map, layer !== 'radar');
    // showRadar() (date effect above) turns the picture on per date; here it is only turned off.
    if (layer !== 'radar' && map.getLayer(RADAR_LAYER)) map.setLayoutProperty(RADAR_LAYER, 'visibility', 'none');
  }, [ready, layer, themeTick]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setSelected(map, selectedCell);
    const f = selectedCell ? bundle.idx.feature.get(selectedCell) : null;
    if (!f) return;
    // Keep the cell visible beside the pulse card: shift the view left on desktop, up on phones.
    const c = map.getContainer();
    const wide = c.clientWidth > 860;
    const offset: [number, number] = wide ? [-Math.min(230, c.clientWidth / 4), 0] : [0, -c.clientHeight / 4];
    const zoom = Math.max(map.getZoom(), 11);
    // Reduced motion (PRD 11): the fly-to becomes an instant jump.
    if (reducedMotion()) map.jumpTo({ center: f.properties.centroid, zoom });
    else map.flyTo({ center: f.properties.centroid, zoom, offset, duration: 700 });
    if (reducedMotion()) map.panBy(offset.map((v) => -v) as [number, number], { animate: false });
  }, [ready, bundle, selectedCell]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setLayoutProperty('basemap', 'visibility', basemap === 'osm' ? 'visible' : 'none');
  }, [ready, basemap]);

  const date = bundle.manifest.dates[dateIndex];
  const reason = isDropped(bundle, dateIndex) ? droppedReason(bundle, dateIndex, lang) : null;

  return (
    <div className="season">
      <div className="season__map">
        {webgl ? (
          <div ref={el} className="season__canvas" role="region" aria-label={t(lang, 'map.label')} />
        ) : (
          <p className="season__nowebgl">{t(lang, 'map.webgl')}</p>
        )}
        {reason && (
          <p className="season__dropped" role="status">
            {t(lang, 'counts.dropped', { reason })}
          </p>
        )}
        <div className="season__tools">
          <LayerSwitch layer={layer} lang={lang} hasCoherence={hasCoherence(bundle)} onChange={(l) => dispatch({ type: 'setLayer', layer: l })} />
          <div className="season__basemap">
            <label htmlFor="basemap">{t(lang, 'map.basemap')}</label>
            <select id="basemap" value={basemap} onChange={(e) => dispatch({ type: 'setBasemap', basemap: e.target.value as 'osm' | 'none' })}>
              <option value="osm">{t(lang, 'map.basemap.osm')}</option>
              <option value="none">{t(lang, 'map.basemap.none')}</option>
            </select>
          </div>
        </div>
        <PulseCard />
      </div>
      <aside className="season__side">
        {layer !== 'state' && (
          <>
            {layer === 'radar' ? (
              <section className="ramp-legend" aria-labelledby="ramp-h">
                <h2 id="ramp-h" className="legend__title">{t(lang, 'layer.radar.title')}</h2>
                <p className="ramp-legend__what">{t(lang, 'layer.radar.what')}</p>
              </section>
            ) : (
              <RampLegend layer={layer as RampLayer} lang={lang} />
            )}
            {layer === 'coh' && dateIndex === 0 && <p className="ramp-legend__note">{t(lang, 'layer.coh.first')}</p>}
            <hr className="season__rule" />
          </>
        )}
        {/* Counts stay on every layer: they are the map's text alternative (PRD 11). */}
        <Legend title={t(lang, 'legend.title', { date: formatDate(date, lang) })} />
      </aside>
      <Timeline />
    </div>
  );
}

/** Same grid as SeasonMap, so nothing jumps when the bundle arrives (PRD 11). */
export function SeasonMapSkeleton({ label }: { label: string }) {
  return (
    <div className="season season--skeleton" aria-busy="true">
      <div className="season__map">
        <p className="season__loading" role="status">{label}</p>
      </div>
      <aside className="season__side">
        {Array.from({ length: 8 }, (_, i) => <div key={i} className="skeleton-row" />)}
      </aside>
      <div className="timeline timeline--skeleton" />
    </div>
  );
}
