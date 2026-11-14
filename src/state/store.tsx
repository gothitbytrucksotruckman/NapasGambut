// App state (PRD 7.2): one reducer, URL hash kept in sync for shareable views.
import { createContext, type ReactNode, useContext, useEffect, useMemo, useReducer, useRef } from 'react';
import { BundleError, loadBundle, type Bundle } from '../data/load';
import { type LayerId, type Lang, parseHash, type Screen, toHash, type View } from './hash';

export type Basemap = 'osm' | 'none';

export interface AppState extends View {
  playing: boolean;
  basemap: Basemap;
}

type Action =
  | { type: 'hydrate'; view: View }
  | { type: 'go'; screen: Screen }
  | { type: 'setDate'; index: number }
  | { type: 'step'; delta: 1 | -1 }
  | { type: 'select'; cell: string | null }
  | { type: 'setLayer'; layer: LayerId }
  | { type: 'togglePlay' }
  | { type: 'stop' }
  | { type: 'setLang'; lang: Lang }
  | { type: 'setBasemap'; basemap: Basemap };

function reducer(n: number) {
  const clamp = (i: number) => Math.max(0, Math.min(n - 1, i));
  return (s: AppState, a: Action): AppState => {
    switch (a.type) {
      case 'hydrate': return { ...s, ...a.view };
      case 'go': return { ...s, screen: a.screen, playing: false };
      case 'setDate': return { ...s, dateIndex: clamp(a.index) };
      case 'step': return { ...s, dateIndex: clamp(s.dateIndex + a.delta), playing: false };
      case 'select': return { ...s, selectedCell: a.cell };
      case 'setLayer': return { ...s, layer: a.layer };
      // Pressing play on the last pass restarts from the first.
      case 'togglePlay': return s.playing ? { ...s, playing: false } : { ...s, playing: true, dateIndex: s.dateIndex >= n - 1 ? 0 : s.dateIndex };
      case 'stop': return { ...s, playing: false };
      case 'setLang': return { ...s, lang: a.lang };
      case 'setBasemap': return { ...s, basemap: a.basemap };
    }
  };
}

type Ctx = { state: AppState; bundle: Bundle; dispatch: (a: Action) => void };
const AppCtx = createContext<Ctx | null>(null);

export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error('useApp outside AppProvider');
  return c;
}

const PLAY_MS = 1200;

export function AppProvider({ bundle, children }: { bundle: Bundle; children: ReactNode }) {
  const ctx = { dates: bundle.manifest.dates, hasCell: (id: string) => bundle.idx.cell.has(id) };
  const reduce = useMemo(() => reducer(bundle.manifest.dates.length), [bundle]);
  const [state, dispatch] = useReducer(reduce, undefined, () => ({
    ...parseHash(location.hash, ctx),
    playing: false,
    basemap: 'osm' as Basemap,
  }));

  // State -> URL. Screen changes push history (Back works); scrubbing replaces (no history spam).
  const lastScreen = useRef(state.screen);
  useEffect(() => {
    const h = toHash(state, bundle.manifest.dates);
    if (h === location.hash) return;
    if (state.screen !== lastScreen.current) history.pushState(null, '', h);
    else history.replaceState(null, '', h);
    lastScreen.current = state.screen;
  }, [state.screen, state.dateIndex, state.selectedCell, state.layer, state.lang, bundle]);

  // URL -> state (Back/Forward, pasted links).
  useEffect(() => {
    const onHash = () => {
      const v = parseHash(location.hash, ctx);
      lastScreen.current = v.screen;
      dispatch({ type: 'hydrate', view: v });
    };
    addEventListener('popstate', onHash);
    addEventListener('hashchange', onHash);
    return () => {
      removeEventListener('popstate', onHash);
      removeEventListener('hashchange', onHash);
    };
  }, [bundle]);

  useEffect(() => {
    document.documentElement.lang = state.lang;
  }, [state.lang]);

  // Playback: one pass per 1.2 s, stops on the last pass.
  useEffect(() => {
    if (!state.playing) return;
    if (state.dateIndex >= bundle.manifest.dates.length - 1) {
      dispatch({ type: 'stop' });
      return;
    }
    const id = setTimeout(() => dispatch({ type: 'setDate', index: state.dateIndex + 1 }), PLAY_MS);
    return () => clearTimeout(id);
  }, [state.playing, state.dateIndex, bundle]);

  return <AppCtx.Provider value={{ state, bundle, dispatch }}>{children}</AppCtx.Provider>;
}

export type LoadResult = { status: 'loading' } | { status: 'ready'; bundle: Bundle } | { status: 'error'; error: BundleError };

export async function loadFromEnv(): Promise<LoadResult> {
  const url = import.meta.env.VITE_BUNDLE_URL || `${import.meta.env.BASE_URL}bundle/`;
  try {
    return { status: 'ready', bundle: await loadBundle(url) };
  } catch (e) {
    return { status: 'error', error: e instanceof BundleError ? e : new BundleError('(bundle)', '', String(e)) };
  }
}
