import { useState } from 'react';
import { t } from '../i18n';
import type { Lang } from '../state/hash';

/** Copies the current URL (it already carries cell, date, layer and language). Falls back to a selectable field. */
export function CopyLink({ lang }: { lang: Lang }) {
  const [status, setStatus] = useState<'idle' | 'ok' | 'fail'>('idle');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      setStatus('ok');
    } catch {
      setStatus('fail');
    }
  };
  return (
    <div className="copy-link">
      <button type="button" className="btn" onClick={copy}>{t(lang, 'pulse.copy')}</button>
      <span role="status" className="copy-link__status">
        {status === 'ok' && t(lang, 'pulse.copied')}
        {status === 'fail' && t(lang, 'pulse.copyFail')}
      </span>
      {status === 'fail' && (
        <input className="copy-link__field" readOnly value={location.href} aria-label={t(lang, 'pulse.copy')}
          onFocus={(e) => e.currentTarget.select()} autoFocus />
      )}
    </div>
  );
}
