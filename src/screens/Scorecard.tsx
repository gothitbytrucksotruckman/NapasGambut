// Scorecard (PRD 8.4): class table, two action lists, four tests. Every value is read from scorecard.json.
import { fireRiskView } from '../data/models';
import { formatDb, testSentence } from '../data/scorecardText';
import { formatDate, formatNumber, type Key, t } from '../i18n';
import { useApp } from '../state/store';
import './Scorecard.css';

export function Scorecard() {
  const { state, bundle, dispatch } = useApp();
  const { lang } = state;
  const sc = bundle.scorecard;
  const cls = (id: string) => t(lang, `class.${id}` as Key);
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const fire = fireRiskView(sc.fire_risk);

  // Opening a cell: select it, show the map. The map screen frames the cell and opens its pulse card.
  const open = (cell: string) => {
    dispatch({ type: 'select', cell });
    dispatch({ type: 'go', screen: 'map' });
  };
  // Opening a canal: highlight it and fit map bounds to its LineString coordinates.
  const openCanal = (canal: string) => {
    dispatch({ type: 'selectCanal', canal });
    dispatch({ type: 'go', screen: 'map' });
  };
  const CellButton = ({ id }: { id: string }) => (
    <button type="button" className="score__cell num" onClick={() => open(id)} aria-label={t(lang, 'score.open', { id })}>
      {id}
    </button>
  );

  return (
    <article className="score" aria-labelledby="score-h">
      <header className="score__head">
        <h1 id="score-h">{t(lang, 'score.title')}</h1>
        <p>{t(lang, 'score.lede')}</p>
      </header>

      <section className="score__block score__block--wide" aria-labelledby="score-classes">
        <h2 id="score-classes">{t(lang, 'score.classes')}</h2>
        <div className="score__scroll">
          <table className="score__table">
            <thead>
              <tr>
                <th scope="col">{t(lang, 'score.th.class')}</th>
                <th scope="col" className="r">{t(lang, 'score.th.n')}</th>
                <th scope="col" className="r">{t(lang, 'score.th.median')}</th>
                <th scope="col" className="r">{t(lang, 'score.th.spread')}</th>
                <th scope="col" className="r">{t(lang, 'score.th.burned')}</th>
                <th scope="col" className="r">{t(lang, 'score.th.recovery')}</th>
              </tr>
            </thead>
            <tbody className="num">
              {sc.by_class.map((c) => (
                <tr key={c.class}>
                  <th scope="row">{cls(c.class)}</th>
                  <td className="r">{formatNumber(c.n_cells, lang)}</td>
                  <td className="r"><strong>{formatDb(c.median_min_hh_db)}</strong> dB</td>
                  <td className="r">{t(lang, 'score.spreadText', { a: formatDb(c.p25_min_hh_db), b: formatDb(c.p75_min_hh_db) })}</td>
                  <td className="r">{pct(c.share_burned)}</td>
                  <td className="r">{c.median_passes_to_recovery === null ? t(lang, 'score.noRecovery') : formatNumber(c.median_passes_to_recovery, lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="score__block" aria-labelledby="score-fast">
        <h2 id="score-fast">{t(lang, 'score.fastest')}</h2>
        <p className="score__note">{t(lang, 'score.fastestNote')}</p>
        {sc.rankings.fastest_drying.length === 0 ? (
          <p className="score__empty">{t(lang, 'score.empty')}</p>
        ) : (
          <div className="score__scroll">
            <table className="score__table">
              <thead>
                <tr>
                  <th scope="col" className="r">{t(lang, 'score.th.rank')}</th>
                  <th scope="col">{t(lang, 'score.th.cell')}</th>
                  <th scope="col">{t(lang, 'score.th.class')}</th>
                  <th scope="col" className="r">{t(lang, 'score.th.min')}</th>
                  <th scope="col" className="r">{t(lang, 'score.th.when')}</th>
                </tr>
              </thead>
              <tbody className="num">
                {sc.rankings.fastest_drying.map((r, i) => (
                  <tr key={r.cell}>
                    <td className="r">{i + 1}</td>
                    <td><CellButton id={r.cell} /></td>
                    <td>{cls(r.class)}</td>
                    <td className="r">{formatDb(r.min_hh_db)}</td>
                    <td className="r">{formatDate(r.date_of_min, lang, 'short')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="score__block" aria-labelledby="score-dams">
        <h2 id="score-dams">{t(lang, 'score.dams')}</h2>
        <p className="score__note">{t(lang, 'score.damsNote')}</p>
        {sc.rankings.dams_to_inspect.length === 0 ? (
          <p className="score__empty">{t(lang, 'score.empty')}</p>
        ) : (
          <div className="score__scroll">
            <table className="score__table">
              <thead>
                <tr>
                  <th scope="col" className="r">{t(lang, 'score.th.rank')}</th>
                  <th scope="col">{t(lang, 'score.th.cell')}</th>
                  <th scope="col" className="r">{t(lang, 'score.th.min')}</th>
                  <th scope="col" className="r">{t(lang, 'score.th.gap')}</th>
                </tr>
              </thead>
              <tbody className="num">
                {sc.rankings.dams_to_inspect.map((r, i) => (
                  <tr key={r.cell}>
                    <td className="r">{i + 1}</td>
                    <td><CellButton id={r.cell} /></td>
                    <td className="r">{formatDb(r.min_hh_db)}</td>
                    <td className="r">{formatDb(r.gap_vs_drained_median_db)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {sc.rankings.canals && sc.rankings.canals.length > 0 && (
        <section className="score__block score__block--wide" aria-labelledby="score-canals">
          <h2 id="score-canals">{t(lang, 'score.canals')}</h2>
          <p className="score__note">{t(lang, 'score.canalsNote')}</p>
          <div className="score__scroll">
            <table className="score__table">
              <thead>
                <tr>
                  <th scope="col" className="r">{t(lang, 'score.th.rank')}</th>
                  <th scope="col">{t(lang, 'score.th.canal')}</th>
                  <th scope="col" className="r">{t(lang, 'score.th.length')}</th>
                  <th scope="col" className="r">{t(lang, 'score.th.n')}</th>
                  <th scope="col" className="r">{t(lang, 'score.th.median')}</th>
                  <th scope="col" className="r">{t(lang, 'score.th.burnedCells')}</th>
                </tr>
              </thead>
              <tbody className="num">
                {sc.rankings.canals.map((r, i) => {
                  const label = lang === 'en' ? r.name_en : r.name_id;
                  return (
                    <tr key={r.canal}>
                      <td className="r">{i + 1}</td>
                      <td>
                        <button
                          type="button"
                          className="score__cell"
                          onClick={() => openCanal(r.canal)}
                          aria-label={t(lang, 'score.openCanal', { name: label })}
                        >
                          {label}
                        </button>
                      </td>
                      <td className="r">{r.length_km.toFixed(2)} km</td>
                      <td className="r">{formatNumber(r.n_cells, lang)}</td>
                      <td className="r"><strong>{formatDb(r.median_min_hh_db)}</strong> dB</td>
                      <td className="r">{formatNumber(r.n_burned_cells, lang)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="score__block score__block--wide" aria-labelledby="score-tests">
        <h2 id="score-tests">{t(lang, 'score.tests')}</h2>
        {bundle.manifest.data_kind === 'mock' && <p className="score__note">{t(lang, 'score.mockNote')}</p>}
        <ol className="score__tests">
          {sc.tests.map((test) => (
            <li key={test.id}>
              <p className="score__test">{testSentence(test, lang)}</p>
              <p className="score__testnote">{lang === 'en' ? test.note_en : test.note_id}</p>
            </li>
          ))}
        </ol>
      </section>

      {fire && (
        <section className="score__block score__block--wide" aria-labelledby="score-fire">
          <h2 id="score-fire">{t(lang, 'score.fire')}</h2>
          {fire.status === 'passed' && <p className="score__note">{t(lang, 'score.fire.passed')}</p>}
          {fire.status === 'not_run' && <p className="score__note">{t(lang, 'score.fire.notRun')}</p>}
          {fire.status === 'not_passed' && (
            <p className="score__note">
              {t(lang, 'score.fire.notPassed')}
              {fire.model && fire.baseline && (
                <> <span className="num">{t(lang, 'score.fire.numbers', {
                  m: fire.model.prAuc.toFixed(3), lo: fire.model.lo.toFixed(3), hi: fire.model.hi.toFixed(3),
                  id: fire.baseline.id, rule: t(lang, `score.fire.${fire.baseline.id}`), b: fire.baseline.prAuc.toFixed(3),
                })}</span></>
              )}
            </p>
          )}
          <div className="score__scroll">
            <table className="score__table">
              <caption className="score__caption">
                {t(lang, 'score.fire.caption', { dates: fire.testDates.map((d) => formatDate(d, lang)).join(', ') })}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{t(lang, 'score.fire.th.fifth')}</th>
                  <th scope="col" className="r">{t(lang, 'score.fire.th.n')}</th>
                  <th scope="col" className="r">{t(lang, 'score.fire.th.fires')}</th>
                  <th scope="col" className="r">{t(lang, 'score.fire.th.rate')}</th>
                </tr>
              </thead>
              <tbody className="num">
                {fire.rows.map((r) => (
                  <tr key={r.quintile}>
                    <th scope="row">{r.quintile}</th>
                    <td className="r">{formatNumber(r.n, lang)}</td>
                    <td className="r">{formatNumber(r.fires, lang)}</td>
                    <td className="r">{pct(r.rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="score__note">{t(lang, 'score.fire.limit')}</p>
        </section>
      )}
    </article>
  );
}
