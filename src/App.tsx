import { useEffect, useState } from 'react';
import { AppShell } from './components/AppShell';
import { ErrorScreen } from './components/ErrorScreen';
import { t } from './i18n';
import { SeasonMap, SeasonMapSkeleton } from './screens/SeasonMap';
import { ScreenStub } from './screens/ScreenStub';
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
      {state.screen === 'map' ? <SeasonMap /> : <ScreenStub />}
    </AppShell>
  );
}

export function App() {
  const [load, setLoad] = useState<LoadResult>({ status: 'loading' });
  useEffect(() => {
    loadFromEnv().then(setLoad);
  }, []);

  // Before the bundle arrives we only know the language from the URL.
  const lang = parseHash(location.hash, { dates: [], hasCell: () => false }).lang;

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
      ) : (
        <SeasonMapSkeleton label={t(lang, 'load.title')} />
      )}
    </AppShell>
  );
}
