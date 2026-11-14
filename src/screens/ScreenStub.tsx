// Placeholder for screens built in milestones 3 and 4. It says so plainly and offers the one working path.
import { t } from '../i18n';
import { useApp } from '../state/store';

// TODO(milestone 4): replace with Reveal, Scorecard and Method screens.
export function ScreenStub() {
  const { state, dispatch } = useApp();
  return (
    <section className="stub" aria-labelledby="stub-title">
      <h1 id="stub-title">{t(state.lang, 'stub.title')}</h1>
      <p>{t(state.lang, 'stub.body')}</p>
      <button type="button" className="btn btn--primary" onClick={() => dispatch({ type: 'go', screen: 'map' })}>
        {t(state.lang, 'stub.cta')}
      </button>
    </section>
  );
}
