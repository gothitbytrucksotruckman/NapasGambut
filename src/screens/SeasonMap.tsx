import { Map as MLMap, type MapLayerMouseEvent, NavigationControl, setWorkerUrl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { useEffect, useRef, useState } from 'react';
import { Legend } from '../components/Legend';
import { Timeline } from '../components/Timeline';
import { droppedReason, isDropped } from '../data/selectors';
import { formatDate, t } from '../i18n';
import {
  addHatchImage, applyStates, buildStyle, CELLS_FILL, hollowOpacityExpr, setHatchFilter, setSelected,
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
  const { lang, dateIndex, selectedCell, basemap } = state;

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

  // Recolour on date change: feature-state only, the source is never rebuilt.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    applyStates(map, bundle, dateIndex);
    setHatchFilter(map, bundle, dateIndex);
  }, [ready, bundle, dateIndex]);

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
          <label htmlFor="basemap">{t(lang, 'map.basemap')}</label>
          <select id="basemap" value={basemap} onChange={(e) => dispatch({ type: 'setBasemap', basemap: e.target.value as 'osm' | 'none' })}>
            <option value="osm">{t(lang, 'map.basemap.osm')}</option>
            <option value="none">{t(lang, 'map.basemap.none')}</option>
          </select>
        </div>
        <PulseCard />
      </div>
      <aside className="season__side">
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
