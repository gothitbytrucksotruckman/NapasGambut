// Scorecard, PRD 5.9 and 6.7. Descriptive statistics on simulated data.
import { STATE, type Scorecard } from '../../src/contract';
import type { Landscape } from './landscape';
import { median, quantile, round, spearman } from './stats';

const NOTE_EN = 'Descriptive only, computed on simulated data. Not evidence about real peat.';
const NOTE_ID = 'Hanya deskriptif, dihitung dari data simulasi. Bukan bukti tentang gambut nyata.'; // REVIEW

interface Input {
  land: Landscape;
  D: (number | null)[][]; // dB
  states: number[][];
  dates: string[];
  peakIndex: number;
}

export function buildScorecard({ land, D, states, dates, peakIndex }: Input): Scorecard {
  const cells = land.cells;
  // Lowest HH index per cell over valid dates.
  const minInfo = cells.map((_, i) => {
    let min = Infinity, at = 0;
    D[i].forEach((v, t) => {
      if (v !== null && states[i][t] !== STATE.no_data && v < min) { min = v; at = t; }
    });
    return { min: min === Infinity ? null : min, at };
  });
  const isFire = (s: number) => s === STATE.fire_radar || s === STATE.fire_silent;
  const burned = (i: number) => states[i].some(isFire);

  const classes = ['drained', 'rewetted', 'plantation', 'intact_forest', 'reference_forest', 'settlement'] as const;
  const by_class = classes.map((cls) => {
    const idx = cells.map((c, i) => (c.cls === cls ? i : -1)).filter((i) => i >= 0);
    const mins = idx.map((i) => minInfo[i].min).filter((v): v is number => v !== null);
    const recov = idx
      .map((i) => {
        const r = states[i].findIndex((s, t) => t > minInfo[i].at && s === STATE.rewetting);
        return r < 0 ? null : r - minInfo[i].at;
      })
      .filter((v): v is number => v !== null);
    return {
      class: cls,
      n_cells: idx.length,
      median_min_hh_db: round(median(mins)),
      p25_min_hh_db: round(quantile(mins, 0.25)),
      p75_min_hh_db: round(quantile(mins, 0.75)),
      share_burned: round(idx.filter(burned).length / idx.length, 3),
      median_passes_to_recovery: recov.length ? median(recov) : null,
    };
  });

  const drainedMedian = by_class[0].median_min_hh_db;
  const fastest_drying = cells
    .map((c, i) => ({ c, i, m: minInfo[i] }))
    .filter(({ c, m }) => (c.cls === 'drained' || c.cls === 'plantation') && m.min !== null)
    .sort((a, b) => a.m.min! - b.m.min! || a.i - b.i)
    .slice(0, 20)
    .map(({ c, m }) => ({ cell: c.id, class: c.cls, min_hh_db: round(m.min!), date_of_min: dates[m.at] }));

  const dams_to_inspect = cells
    .map((c, i) => ({ c, m: minInfo[i].min }))
    .filter(({ c, m }) => c.cls === 'rewetted' && m !== null && m < drainedMedian)
    .sort((a, b) => a.m! - b.m!)
    .map(({ c, m }) => ({ cell: c.id, min_hh_db: round(m!), gap_vs_drained_median_db: round(m! - drainedMedian) }));

  // Test 1: canal density vs minimum HH, peat classes only.
  const peat = cells.map((c, i) => ({ c, m: minInfo[i].min })).filter(
    ({ c, m }) => m !== null && (c.cls === 'drained' || c.cls === 'rewetted' || c.cls === 'plantation'),
  );
  const rho = spearman(peat.map((p) => p.c.canalDensity), peat.map((p) => p.m!));

  // Test 3: HH on the pass before the fire, burned minus unburned peat cells on the same date.
  const diffs: number[] = [];
  const unburnedPeat = peat.map(({ c }) => cells.indexOf(c)).filter((i) => !burned(i));
  cells.forEach((_, i) => {
    const t = states[i].findIndex(isFire);
    if (t <= 1) return;
    const before = D[i][t - 1];
    const others = unburnedPeat.map((j) => D[j][t - 1]).filter((v): v is number => v !== null);
    if (before !== null && others.length) diffs.push(before - median(others));
  });

  const forestPeak = cells
    .map((c, i) => (c.cls === 'intact_forest' ? D[i][peakIndex] : null))
    .filter((v): v is number => v !== null)
    .map(Math.abs);

  const rew = by_class[1], dr = by_class[0];
  return {
    by_class,
    rankings: { fastest_drying, dams_to_inspect },
    tests: [
      {
        id: 'canal_vs_drying',
        name_en: 'More canals, more drying',
        name_id: 'Makin banyak kanal, makin kering', // REVIEW
        statistic: 'Spearman rank correlation',
        value: round(rho, 3),
        n: peat.length,
        note_en: `${NOTE_EN} A negative value means cells with more canal length reached lower (drier) minimums.`,
        note_id: `${NOTE_ID} Nilai negatif berarti sel dengan kanal lebih panjang mencapai titik terendah yang lebih kering.`, // REVIEW
      },
      {
        id: 'rewetted_vs_drained',
        name_en: 'Rewetted cells dry less',
        name_id: 'Sel yang dibasahi kembali lebih sedikit mengering', // REVIEW
        statistic: `Difference in median minimum HH index, dB (rewetted n=${rew.n_cells}, drained n=${dr.n_cells})`,
        value: round(rew.median_min_hh_db - dr.median_min_hh_db),
        n: rew.n_cells + dr.n_cells,
        note_en: `${NOTE_EN} A positive value means rewetted cells stayed wetter.`,
        note_id: `${NOTE_ID} Nilai positif berarti sel yang dibasahi kembali tetap lebih basah.`, // REVIEW
      },
      {
        id: 'drying_before_fire',
        name_en: 'Drying comes before fire',
        name_id: 'Pengeringan mendahului api', // REVIEW
        statistic: 'Median HH index on the pass before the fire, burned minus unburned cells, dB',
        value: round(median(diffs)),
        n: diffs.length,
        note_en: `${NOTE_EN} A negative value means cells were already drier than their neighbours one pass before burning.`,
        note_id: `${NOTE_ID} Nilai negatif berarti sel sudah lebih kering dari sekitarnya satu lintasan sebelum terbakar.`, // REVIEW
      },
      {
        id: 'forest_flat',
        name_en: 'Intact forest shows little signal',
        name_id: 'Hutan utuh hanya menunjukkan sedikit sinyal', // REVIEW
        statistic: `Median absolute HH index of intact forest at peak drought (${dates[peakIndex]}), dB`,
        value: round(median(forestPeak)),
        n: forestPeak.length,
        note_en: `${NOTE_EN} L-band radar sees little of the peat surface under dense canopy.`,
        note_id: `${NOTE_ID} Radar pita L hanya sedikit melihat permukaan gambut di bawah tajuk yang rapat.`, // REVIEW
      },
    ],
  };
}
