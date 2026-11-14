// Reveal (PRD 8.1): the landing screen. One idea in ten seconds: smoke blinds the camera, radar sees through.
import { Divider } from '../components/Divider';
import { PassRuler } from '../components/PassRuler';
import { isDropped } from '../data/selectors';
import { formatDate, t } from '../i18n';
import { useApp } from '../state/store';
import './Reveal.css';

export function Reveal() {
  const { state, bundle, dispatch } = useApp();
  const { lang } = state;
  const { manifest } = bundle;
  const rv = manifest.images.reveal;
  const revealIndex = Math.max(0, manifest.dates.indexOf(rv.date));
  const dropped = manifest.dates.map((_, i) => isDropped(bundle, i));

  return (
    <section className="reveal" aria-labelledby="reveal-h">
      <div className="reveal__text">
        <h1 id="reveal-h" className="reveal__headline">{t(lang, 'reveal.headline', { date: formatDate(rv.date, lang) })}</h1>
        <p className="reveal__lede">{t(lang, 'reveal.lede')}</p>
        <div className="reveal__ruler">
          <PassRuler dates={manifest.dates} dropped={dropped} current={revealIndex} height={22} />
          <p className="reveal__rulernote">{t(lang, 'reveal.rulerNote', { i: revealIndex + 1, n: manifest.dates.length })}</p>
        </div>
        <button type="button" className="btn btn--primary reveal__cta"
          onClick={() => { dispatch({ type: 'setDate', index: 0 }); dispatch({ type: 'go', screen: 'map' }); }}>
          {t(lang, 'reveal.cta')}
        </button>
        {manifest.data_kind === 'mock' && <p className="reveal__sim">{t(lang, 'reveal.simNote')}</p>}
      </div>
      <div className="reveal__compare">
        <Divider
          leftSrc={bundle.imageUrl(rv.optical_file)}
          rightSrc={bundle.imageUrl(rv.radar_file)}
          leftAlt={t(lang, 'reveal.imgOptical')}
          rightAlt={t(lang, 'reveal.imgRadar')}
          leftLabel={t(lang, 'reveal.optical')}
          rightLabel={t(lang, 'reveal.radar')}
          sliderLabel={t(lang, 'reveal.divider')}
          valueText={(n) => t(lang, 'reveal.dividerValue', { n })}
          size={640}
        />
      </div>
    </section>
  );
}
