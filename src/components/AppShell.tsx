import type { ReactNode } from 'react';
import { t } from '../i18n';
import { ThemeSwitch } from '../layers/ThemeSwitch';
import { SCREENS, type Lang, type Screen } from '../state/hash';
import './AppShell.css';

interface Props {
  lang: Lang;
  dataKind: 'mock' | 'nisar' | null; // null while loading: badge space is reserved, not shown
  screen?: Screen;
  onNavigate?: (s: Screen) => void;
  onLang?: (l: Lang) => void;
  children: ReactNode;
}

const NAV_KEY = { reveal: 'nav.reveal', map: 'nav.map', scorecard: 'nav.scorecard', method: 'nav.method', world: 'nav.world' } as const;

/** Header lives here, not per screen, so the simulated-data badge cannot be skipped by any screen. */
export function AppShell({ lang, dataKind, screen, onNavigate, onLang, children }: Props) {
  return (
    <div className="shell">
      <header className="shell__bar">
        <div className="shell__brand">
          <span className="shell__title">{t(lang, 'app.title')}</span>
          <span className="shell__sub">{t(lang, 'app.subtitle')}</span>
        </div>
        {dataKind === 'mock' && (
          <span className="sim-badge" title={t(lang, 'badge.simulated.title')}>
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M0 12 L12 0 M-3 9 L9 -3 M3 15 L15 3" stroke="currentColor" strokeWidth="1.6" />
            </svg>
            {t(lang, 'badge.simulated')}
          </span>
        )}
        {onNavigate && (
          <nav className="shell__nav" aria-label={t(lang, 'nav.label')}>
            {SCREENS.map((s) => (
              <a key={s} href={`#/${s}`} aria-current={s === screen ? 'page' : undefined}
                onClick={(e) => { e.preventDefault(); onNavigate(s); }}>
                {t(lang, NAV_KEY[s])}
              </a>
            ))}
          </nav>
        )}
        {onLang && (
          <div className="shell__prefs">
            <ThemeSwitch lang={lang} />
            <button type="button" className="btn shell__lang" lang={lang === 'en' ? 'id' : 'en'} onClick={() => onLang(lang === 'en' ? 'id' : 'en')}>
              {t(lang, 'lang.switch')}
            </button>
          </div>
        )}
      </header>
      <main className="shell__main">{children}</main>
    </div>
  );
}
