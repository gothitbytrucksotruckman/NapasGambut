import { useState } from 'react';
import type { Lang } from '../state/hash';
import { tl } from './strings';
import { applyTheme, readTheme, type Theme } from './theme';
import './ThemeSwitch.css';

/** Theme select for the header. Both themes come from the same tokens (src/styles/tokens.css). */
export function ThemeSwitch({ lang, onChange }: { lang: Lang; onChange?: (t: Theme) => void }) {
  const [theme, setTheme] = useState<Theme>(readTheme);
  return (
    <label className="theme-switch">
      <span className="visually-hidden">{tl(lang, 'theme.label')}</span>
      <select
        value={theme}
        onChange={(e) => {
          const t = e.target.value as Theme;
          setTheme(t);
          applyTheme(t);
          onChange?.(t);
        }}
      >
        <option value="auto">{tl(lang, 'theme.auto')}</option>
        <option value="light">{tl(lang, 'theme.light')}</option>
        <option value="dark">{tl(lang, 'theme.dark')}</option>
      </select>
    </label>
  );
}
