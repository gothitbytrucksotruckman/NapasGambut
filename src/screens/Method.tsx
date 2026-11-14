// Method and limits (PRD 8.5). Plain words first, formula second, facts from the manifest last.
import { Swatch } from '../components/Legend';
import { PassRuler } from '../components/PassRuler';
import { sigmaRange } from '../data/scorecardText';
import { isDropped } from '../data/selectors';
import { formatDate, type Key, t } from '../i18n';
import { useApp } from '../state/store';
import './Method.css';

const RULES: { code: number; key: Key }[] = [
  { code: 1, key: 'method.rule1' }, { code: 2, key: 'method.rule2' }, { code: 3, key: 'method.rule3' }, { code: 4, key: 'method.rule4' },
  { code: 5, key: 'method.rule5' }, { code: 6, key: 'method.rule6' }, { code: 7, key: 'method.rule7' }, { code: 8, key: 'method.rule8' },
];

export function Method() {
  const { state, bundle } = useApp();
  const { lang } = state;
  const m = bundle.manifest;
  const th = m.thresholds;
  const vars = { k: th.change_k, h: th.headline_k, deep: th.deep_k, rain: th.rain_return_mm };
  const sig = sigmaRange(th.sigma_db);
  const dropped = m.dates.map((_, i) => isDropped(bundle, i));
  const first = m.dates[0], last = m.dates[m.dates.length - 1];
  const geo = m.geometry;
  const geoText = geo.track === null && geo.frame === null && geo.direction === null
    ? t(lang, 'method.geometryNone')
    : [geo.track !== null && `track ${geo.track}`, geo.frame !== null && `frame ${geo.frame}`, geo.direction && (geo.direction === 'A' ? 'ascending' : 'descending')].filter(Boolean).join(', ');

  return (
    <article className="method" aria-labelledby="method-h">
      <h1 id="method-h">{t(lang, 'method.title')}</h1>
      {m.data_kind === 'mock' && (
        <p className="method__mock">{t(lang, 'method.mock', { seed: m.generator.seed ?? '' })}</p>
      )}

      <section aria-labelledby="m-radar">
        <h2 id="m-radar">{t(lang, 'method.radarH')}</h2>
        <p>{t(lang, 'method.radar1')}</p>
        <p>{t(lang, 'method.radar2')}</p>
        <p>{t(lang, 'method.radar3')}</p>
      </section>

      <section aria-labelledby="m-index">
        <h2 id="m-index">{t(lang, 'method.indexH')}</h2>
        <p>{t(lang, 'method.index', { first: formatDate(first, lang) })}</p>
        <p className="method__formula num">
          D<sub>t</sub> = (HH<sub>t</sub> − HH<sub>0</sub>)<sub>cell</sub> − (HH<sub>t</sub> − HH<sub>0</sub>)<sub>reference</sub>
          <br />
          σ<sub>t</sub> = 1.4826 × MAD(D<sub>t</sub> over reference forest)
        </p>
      </section>

      <section aria-labelledby="m-rules">
        <h2 id="m-rules">{t(lang, 'method.rulesH')}</h2>
        <p>{t(lang, 'method.rulesIntro')}</p>
        <ol className="method__rules">
          {RULES.map((r) => (
            <li key={r.code}>
              <Swatch code={r.code} />
              <span><strong>{t(lang, `state.${r.code}` as `state.${1 | 2 | 3 | 4 | 5 | 6 | 7 | 8}`)}.</strong> {t(lang, r.key, vars).replace(/^[^:]+:\s*/, '')}</span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="m-limits">
        <h2 id="m-limits">{t(lang, 'method.limitsH')}</h2>
        <ul className="method__limits">
          <li>{t(lang, 'method.limit1')}</li>
          <li>{t(lang, 'method.limit2')}</li>
          <li>{t(lang, 'method.limit3')}</li>
          <li>{t(lang, 'method.limit4')}</li>
        </ul>
      </section>

      <section aria-labelledby="m-facts">
        <h2 id="m-facts">{t(lang, 'method.factsH')}</h2>
        <PassRuler dates={m.dates} dropped={dropped} height={22} className="method__ruler" />
        <dl className="method__facts">
          <dt>{t(lang, 'method.kind')}</dt>
          <dd>{t(lang, m.data_kind === 'mock' ? 'method.kind.mock' : 'method.kind.nisar')}</dd>
          <dt>{t(lang, 'method.generator')}</dt>
          <dd className="num">{m.generator.name} {m.generator.version}</dd>
          {m.generator.seed !== null && (
            <>
              <dt>{t(lang, 'method.seed')}</dt>
              <dd className="num">{m.generator.seed}</dd>
            </>
          )}
          <dt>{t(lang, 'method.area')}</dt>
          <dd>{lang === 'en' ? m.study_area.name_en : m.study_area.name_id}</dd>
          <dt>{t(lang, 'method.cellSize')}</dt>
          <dd className="num">{m.study_area.cell_size_m} m</dd>
          <dt>{t(lang, 'method.geometry')}</dt>
          <dd className="num">{geoText}</dd>
          <dt>{t(lang, 'method.passes')}</dt>
          <dd className="num">{t(lang, 'method.passesValue', { n: m.dates.length, first: formatDate(first, lang), last: formatDate(last, lang) })}</dd>
          <dt>{t(lang, 'method.thresholds')}</dt>
          <dd className="num">{t(lang, 'method.thresholdsValue', vars)}</dd>
          {sig && (
            <>
              <dt>{t(lang, 'method.sigmaRange')}</dt>
              <dd className="num">{t(lang, 'method.sigmaValue', { lo: sig.lo.toFixed(2), hi: sig.hi.toFixed(2) })}</dd>
            </>
          )}
          <dt>{t(lang, 'method.dropped')}</dt>
          <dd>
            {m.dropped_dates.length === 0 ? t(lang, 'method.noneDropped') : (
              <ul className="method__plain">
                {m.dropped_dates.map((d) => (
                  <li key={d.date}><span className="num">{formatDate(d.date, lang)}</span>: {lang === 'en' ? d.reason_en : d.reason_id}</li>
                ))}
              </ul>
            )}
          </dd>
          <dt>{t(lang, 'method.scenes')}</dt>
          <dd>
            {m.scenes.length === 0 ? t(lang, 'method.noScenes') : (
              <ul className="method__plain num">
                {m.scenes.map((s) => <li key={s.name}>{formatDate(s.date, lang, 'short')} · {s.name} · v{s.version}</li>)}
              </ul>
            )}
          </dd>
        </dl>
      </section>

      <section aria-labelledby="m-sources">
        <h2 id="m-sources">{t(lang, 'method.sourcesH')}</h2>
        <ul className="method__sources">
          {m.sources.map((s) => (
            <li key={s.url}>
              <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a>
              <span>{lang === 'en' ? s.role_en : s.role_id}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="m-future">
        <h2 id="m-future">{t(lang, 'method.futureH')}</h2>
        <ul className="method__limits">
          <li>{t(lang, 'method.future1')}</li>
          <li>{t(lang, 'method.future2')}</li>
          <li>{t(lang, 'method.future3')}</li>
          <li>{t(lang, 'method.future4')}</li>
        </ul>
      </section>
    </article>
  );
}
