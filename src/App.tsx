import { useEffect, useState } from 'react';
import { AppShell } from './components/AppShell';
import { ErrorScreen } from './components/ErrorScreen';
import { t } from './i18n';
import { Method } from './screens/Method';
import { Reveal, RevealSkeleton } from './screens/Reveal';
import { Scorecard } from './screens/Scorecard';
import { SeasonMap, SeasonMapSkeleton } from './screens/SeasonMap';
import { parseHash } from './state/hash';
import { AppProvider, type LoadResult, loadFromEnv, useApp } from './state/store';

function Screens() {
  const { state, bundle, dispatch } = useApp();
  return (
    <AppShell
      lang={state.lang}
      dataKind={bundle.manifest.data_kind}
      screen={state.screen}
      onNavigate={(screen) => dispatch({ type: 'go', screen })}
      onLang={(lang) => dispatch({ type: 'setLang', lang })}
    >
      {state.screen === 'map' ? <SeasonMap /> : state.screen === 'scorecard' ? <Scorecard /> : state.screen === 'method' ? <Method /> : <Reveal />}
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
