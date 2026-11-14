// Theme preference: auto (follow the device), light or dark. Tokens already react to data-theme on <html>.
// Stored per viewer in localStorage; every access is guarded because storage can be blocked.
export type Theme = 'auto' | 'light' | 'dark';
const KEY = 'napas-gambut.theme';

export function readTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'auto';
  } catch {
    return 'auto';
  }
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === 'auto') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
  try {
    if (theme === 'auto') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // storage blocked: the choice still applies for this visit
  }
}
