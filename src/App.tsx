import { lazy, Suspense, useEffect, useState } from 'react';
import { AppShell } from './components/AppShell';
import { ErrorScreen } from './components/ErrorScreen';
import { t } from './i18n';
import { Method } from './screens/Method';
import { Reveal, RevealSkeleton } from './screens/Reveal';
import { Scorecard } from './screens/Scorecard';
import { World } from './screens/World';
import './screens/SeasonMap.css';
import { parseHash } from './state/hash';
import { AppProvider, type LoadResult, loadFromEnv, useApp } from './state/store';

const loadSeasonMap = () => import('./screens/SeasonMap').then((m) => ({ default: m.SeasonMap }));
const LazySeasonMap = lazy(loadSeasonMap);

/** Same grid as SeasonMap, kept out of the MapLibre module so the entry chunk has 0 MapLibre bytes. */
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

function Screens() {
  const { state, bundle, dispatch } = useApp();
  const label = t(state.lang, 'load.title');

  // Prefetch the MapLibre chunk in the background after Reveal mounts.
  useEffect(() => {
    if (state.screen === 'reveal') {
      const id = setTimeout(() => { void loadSeasonMap(); }, 60);
      return () => clearTimeout(id);
    }
  }, [state.screen]);

  return (
    <AppShell
      lang={state.lang}
      dataKind={bundle.manifest.data_kind}
      screen={state.screen}
      onNavigate={(screen) => dispatch({ type: 'go', screen })}
      onLang={(lang) => dispatch({ type: 'setLang', lang })}
    >
      {state.screen === 'map' ? (
        <Suspense fallback={<SeasonMapSkeleton label={label} />}>
          <LazySeasonMap />
        </Suspense>
      ) : state.screen === 'scorecard' ? (
        <Scorecard />
      ) : state.screen === 'method' ? (
        <Method />
      ) : state.screen === 'world' ? (
        <World />
      ) : (
        <Reveal />
      )}
    </AppShell>
  );
}

export function App() {
  const [load, setLoad] = useState<LoadResult>({ status: 'loading' });
  useEffect(() => {
    loadFromEnv().then(setLoad);
  }, []);

  // Before the bundle arrives we only know the language and screen from the URL.
  const { lang, screen } = parseHash(location.hash, { dates: [], hasCell: () => false });
  const label = t(lang, 'load.title');

  if (load.status === 'ready')
    return (
      <AppProvider bundle={load.bundle}>
        <Screens />
      </AppProvider>
    );
  return (
    <AppShell lang={lang} dataKind={null}>
      {load.status === 'error' ? (
        <ErrorScreen error={load.error} lang={lang} />
      ) : screen === 'reveal' ? (
        <RevealSkeleton label={label} />
      ) : (
        <SeasonMapSkeleton label={label} />
      )}
    </AppShell>
  );
}
