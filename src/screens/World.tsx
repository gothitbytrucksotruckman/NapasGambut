import { useState, type KeyboardEvent } from 'react';
import { t, type Key } from '../i18n';
import { useApp } from '../state/store';
import './World.css';

interface PeatRegion {
  id: 'sea' | 'congo' | 'amazon';
  nameKey: Key;
  noteKey: Key;
  coords: string;
  lon: number;
  lat: number;
  hasSeasonMap?: boolean;
}

const REGIONS: readonly PeatRegion[] = [
  {
    id: 'sea',
    nameKey: 'world.sea.name',
    noteKey: 'world.sea.note',
    coords: '2.2 S, 114.0 E',
    lon: 114.0,
    lat: -2.2,
    hasSeasonMap: true,
  },
  {
    id: 'congo',
    nameKey: 'world.congo.name',
    noteKey: 'world.congo.note',
    coords: '0.5 S, 18.0 E',
    lon: 18.0,
    lat: -0.5,
  },
  {
    id: 'amazon',
    nameKey: 'world.amazon.name',
    noteKey: 'world.amazon.note',
    coords: '4.5 S, 75.0 W',
    lon: -75.0,
    lat: -4.5,
  },
];

// Simplified Natural Earth 1:110m landmass outlines in equirectangular 720x360 coordinates:
// x = (lon + 180) * 2, y = (90 - lat) * 2. Bundled inline so zero runtime network fetches occur.
const LANDMASS_PATHS: readonly string[] = [
  // North & Central America
  'M28,50 L48,38 L100,40 L170,44 L200,56 L232,56 L250,76 L228,92 L212,100 L198,118 L200,130 L194,122 L180,122 L166,128 L168,142 L184,138 L192,152 L204,162 L200,164 L176,150 L150,140 L140,134 L126,116 L112,100 L110,82 L88,64 L56,60 L36,70 Z',
  // Greenland
  'M256,60 L272,60 L320,28 L300,16 L236,18 L220,28 L252,44 Z',
  // South America
  'M204,162 L220,158 L240,164 L256,170 L260,180 L290,192 L278,226 L244,250 L226,288 L216,288 L212,264 L218,240 L220,216 L206,204 L198,190 L202,176 Z',
  // Africa
  'M348,108 L380,106 L424,118 L446,156 L462,156 L442,184 L440,202 L430,228 L400,250 L388,224 L384,192 L378,180 L378,172 L366,168 L344,172 L326,150 L334,124 Z',
  // Madagascar
  'M458,204 L460,212 L454,230 L448,228 L452,210 Z',
  // Europe & Asia mainland
  'M342,106 L342,94 L352,84 L368,74 L372,58 L400,40 L420,40 L480,42 L570,28 L640,34 L716,48 L700,60 L680,76 L644,70 L632,92 L618,110 L604,118 L588,136 L576,156 L568,160 L560,154 L568,177.4 L560,170 L556,148 L542,136 L520,154 L514,164 L504,140 L492,130 L476,130 L458,122 L478,136 L464,150 L448,154 L426,120 L432,108 L414,100 L406,104 L390,104 L380,92 L360,104 L348,108 Z',
  // Great Britain & Ireland
  'M350,80 L362,78 L356,64 L348,68 Z',
  // Japan
  'M620,118 L640,108 L650,92 L640,98 L630,112 Z',
  // Philippines
  'M600,144 L605,150 L612,166 L604,167 L601,152 Z',
  // Sumatra
  'M551,169 L560,178 L572,191.6 L567,191 L558,182 Z',
  // Java
  'M572,192 L588.8,195.6 L588.4,197.2 L571,193.8 Z',
  // Borneo
  'M579,177 L595,166.4 L597.6,171.6 L595,182 L592,187.8 L582,187 L580,182 Z',
  // Sulawesi
  'M598,178 L610,177 L605,189 L599,190 Z',
  // New Guinea
  'M622,184 L642,185 L660,200 L648,196 L632,190 Z',
  // Australia
  'M588,224 L618,208 L632,204 L644,202 L666,234 L654,256 L632,250 L590,248 L586,232 Z',
  // New Zealand
  'M708,252 L714,256 L696,272 L692,270 Z',
];

function projectLonLat(lon: number, lat: number): { x: number; y: number } {
  return {
    x: (lon + 180) * 2,
    y: (90 - lat) * 2,
  };
}

export function World() {
  const { state, dispatch } = useApp();
  const { lang } = state;
  const [activeId, setActiveId] = useState<PeatRegion['id']>('sea');

  function handleMarkerKey(e: KeyboardEvent<SVGGElement>, id: PeatRegion['id']) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setActiveId(id);
    }
  }

  return (
    <div className="world">
      <header className="world__head">
        <h1>{t(lang, 'world.title')}</h1>
        <p className="world__lede">{t(lang, 'world.lede')}</p>
      </header>

      <section className="world__mapFrame" aria-label={t(lang, 'world.mapLabel')}>
        <svg
          className="world__svg"
          viewBox="0 0 720 360"
          role="img"
          aria-label={t(lang, 'world.mapLabel')}
        >
          {/* Ocean background */}
          <rect x="0" y="0" width="720" height="360" className="world__ocean" />

          {/* Tropical peat belt: 30 N (y=120) to 30 S (y=240) */}
          <rect x="0" y="120" width="720" height="120" className="world__belt" />
          <line x1="0" y1="120" x2="720" y2="120" className="world__tropic" />
          <line x1="0" y1="180" x2="720" y2="180" className="world__equator" />
          <line x1="0" y1="240" x2="720" y2="240" className="world__tropic" />

          {/* Static equirectangular coastlines */}
          <g aria-hidden="true">
            {LANDMASS_PATHS.map((d, i) => (
              <path key={i} d={d} className="world__land" />
            ))}
          </g>

          {/* Latitude reference labels */}
          <text x="8" y="115" className="world__latLabel">
            30 N
          </text>
          <text x="8" y="175" className="world__latLabel">
            0
          </text>
          <text x="8" y="253" className="world__latLabel">
            30 S
          </text>

          {/* Three approximate tropical peatland markers */}
          {REGIONS.map((region) => {
            const { x, y } = projectLonLat(region.lon, region.lat);
            const selected = activeId === region.id;
            return (
              <g
                key={region.id}
                transform={`translate(${x}, ${y})`}
                className={selected ? 'world__marker world__marker--active' : 'world__marker'}
                role="button"
                tabIndex={0}
                aria-pressed={selected}
                aria-label={`${t(lang, region.nameKey)} (${t(lang, 'world.approx')})`}
                onClick={() => setActiveId(region.id)}
                onKeyDown={(e) => handleMarkerKey(e, region.id)}
              >
                <circle r="18" className="world__markerHalo" />
                <circle r="10" className="world__markerRing" />
                <circle r="4.5" className="world__markerDot" />
                <title>{`${t(lang, region.nameKey)} (${region.coords}, ${t(lang, 'world.approx')})`}</title>
              </g>
            );
          })}
        </svg>

        <div className="world__legend">
          <span className="world__legendItem">
            <span className="world__beltSwatch" aria-hidden="true" />
            {t(lang, 'world.belt')}
          </span>
          <span className="world__approxBadge">{t(lang, 'world.approx')}</span>
        </div>
      </section>

      <div className="world__cards">
        {REGIONS.map((region) => {
          const selected = activeId === region.id;
          return (
            <article
              key={region.id}
              className={selected ? 'world__card world__card--active' : 'world__card'}
              onClick={() => setActiveId(region.id)}
            >
              <div className="world__cardTop">
                <h2>{t(lang, region.nameKey)}</h2>
                <span className="world__approxBadge">{t(lang, 'world.approx')}</span>
              </div>

              <dl className="world__meta">
                <div>
                  <dt>{t(lang, 'world.coords')}</dt>
                  <dd className="num">{region.coords}</dd>
                </div>
                <div>
                  <dt>{t(lang, 'world.noteLabel')}</dt>
                  <dd>{t(lang, region.noteKey)}</dd>
                </div>
              </dl>

              {region.hasSeasonMap ? (
                <button
                  type="button"
                  className="world__cta"
                  onClick={(e) => {
                    e.stopPropagation();
                    dispatch({ type: 'go', screen: 'map' });
                  }}
                >
                  {t(lang, 'world.openSea')}
                </button>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}
