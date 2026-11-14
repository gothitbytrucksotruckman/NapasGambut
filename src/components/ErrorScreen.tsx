import type { BundleError } from '../data/load';
import { t } from '../i18n';
import type { Lang } from '../state/hash';

/** Full-screen bundle error (PRD 7.1): names the file and field so the data team can fix their output. */
export function ErrorScreen({ error, lang }: { error: BundleError; lang: Lang }) {
  return (
    <section className="error-screen" role="alert" aria-labelledby="err-title">
      <h1 id="err-title">{t(lang, 'error.title')}</h1>
      <p>{t(lang, 'error.body')}</p>
      <dl>
        <dt>{t(lang, 'error.file')}</dt>
        <dd><code>{error.file}</code></dd>
        {error.field && (
          <>
            <dt>{t(lang, 'error.field')}</dt>
            <dd><code>{error.field}</code></dd>
          </>
        )}
        <dt>{t(lang, 'error.detail')}</dt>
        <dd>{error.detail}</dd>
      </dl>
      <p className="error-screen__hint">{t(lang, 'error.hint')}</p>
      <button type="button" className="btn btn--primary" onClick={() => location.reload()}>{t(lang, 'error.retry')}</button>
    </section>
  );
}
