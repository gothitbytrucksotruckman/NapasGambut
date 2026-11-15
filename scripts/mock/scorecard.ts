// Scorecard, PRD 5.9 and 6.7. Descriptive statistics on simulated data.
import { STATE, type CanalRanking, type Scorecard } from '../../src/contract';
import { canalId, type Landscape, type LonLat } from './landscape';
import { median, quantile, round, spearman } from './stats';

const NOTE_EN = 'Descriptive only, computed on simulated data. Not evidence about real peat.';
const NOTE_ID = 'Hanya deskriptif, dihitung dari data simulasi. Bukan bukti tentang gambut nyata.'; // REVIEW

const KM_PER_DEG_LAT = 110.574;
function pointToSegmentKm(p: LonLat, a: LonLat, b: LonLat): number {
  const cosLat = Math.cos((((a[1] + b[1]) * 0.5) * Math.PI) / 180);
  const kmLon = 111.32 * cosLat;
  const px = (p[0] - a[0]) * kmLon, py = (p[1] - a[1]) * KM_PER_DEG_LAT;
  const vx = (b[0] - a[0]) * kmLon, vy = (b[1] - a[1]) * KM_PER_DEG_LAT;
  const len2 = vx * vx + vy * vy;
  const t = len2 > 0 ? Math.max(0, Math.min(1, (px * vx + py * vy) / len2)) : 0;
  return Math.hypot(px - t * vx, py - t * vy);
}

function lineLengthKm(coords: LonLat[]): number {
  let len = 0;
  for (let i = 1; i < coords.length; i++) {
    const a = coords[i - 1], b = coords[i];
    const kmLon = 111.32 * Math.cos((((a[1] + b[1]) * 0.5) * Math.PI) / 180);
    len += Math.hypot((b[0] - a[0]) * kmLon, (b[1] - a[1]) * KM_PER_DEG_LAT);
  }
  return len;
}

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

  const isBurnedOrFire = (s: number) => s === STATE.fire_radar || s === STATE.fire_silent || s === STATE.burned;
  const anyBurnedState = (i: number) => states[i].some(isBurnedOrFire);
  const peatCellIdx = cells
    .map((c, i) => ({ c, i }))
    .filter(({ c, i }) => minInfo[i].min !== null && (c.cls === 'drained' || c.cls === 'rewetted' || c.cls === 'plantation'));

  const canals: CanalRanking[] = land.canals
    .map((coords, ci): CanalRanking | null => {
      const matched = peatCellIdx.filter(({ c }) => {
        for (let s = 1; s < coords.length; s++) {
          if (pointToSegmentKm(c.centroid, coords[s - 1], coords[s]) <= 1.0) return true;
        }
        return false;
      });
      if (!matched.length) return null;
      const mins = matched.map(({ i }) => minInfo[i].min!);
      return {
        canal: canalId(ci),
        name_en: `Canal #${ci + 1}`,
        name_id: `Kanal #${ci + 1}`,
        length_km: round(lineLengthKm(coords), 2),
        n_cells: matched.length,
        median_min_hh_db: round(median(mins), 1),
        n_burned_cells: matched.filter(({ i }) => anyBurnedState(i)).length,
      };
    })
    .filter((v): v is CanalRanking => v !== null)
    .sort((a, b) => a.median_min_hh_db - b.median_min_hh_db || b.n_burned_cells - a.n_burned_cells || a.canal.localeCompare(b.canal))
    .slice(0, 20);

  const rew = by_class[1], dr = by_class[0];
  return {
    by_class,
    rankings: { fastest_drying, dams_to_inspect, canals },
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

type FireRisk = NonNullable<Scorecard['fire_risk']>;

/**
 * Quintile lift by HV index, quintile 1 = lowest. pandas qcut(q=5) in pipeline/07b_fire_risk.py is the reference:
 * without ties, rank r of n falls in bin max(1, ceil(5r / (n - 1))), which is what qcut's interpolated edges give.
 * shortcut: tied HV values are split by row order rather than kept in one bin as qcut does; fine for a simulated bundle.
 */
export function fireLift(rows: { hv: number; fire: boolean }[]): FireRisk['lift'] {
  const n = rows.length;
  const order = rows.map((_, i) => i).sort((a, b) => rows[a].hv - rows[b].hv || a - b);
  const groups = [1, 2, 3, 4, 5].map((quintile) => ({ quintile, n: 0, fires: 0 }));
  order.forEach((i, r) => {
    const g = groups[n === 1 ? 0 : Math.max(1, Math.ceil((5 * r) / (n - 1))) - 1];
    g.n++;
    if (rows[i].fire) g.fires++;
  });
  return groups.filter((g) => g.n > 0).map((g) => ({ ...g, rate: round(g.fires / g.n, 3) }));
}

/**
 * The fire-risk block for the mock: no model runs, so only the test dates and the lift are filled in.
 * Panel rule as build_panel in pipeline/07b_fire_risk.py: for kept passes p_0..p_m and each i in 1..m-1,
 * one row per cell not burned before p_i with HV at p_i and p_(i-1); target = any fire from p_i to p_(i+1).
 */
export function mockFireRisk(hv: (number | null)[][], fires: (number | null)[][], dates: string[], dropped: boolean[]): FireRisk {
  const kept = dates.map((_, t) => t).filter((t) => !dropped[t]);
  const nInt = dates.length - 1;
  const firstFire = fires.map((row) => { const k = row.findIndex((v) => (v ?? 0) > 0); return k < 0 ? nInt : k; });
  const rows: { pass: number; hv: number; fire: boolean }[] = [];
  for (let i = 1; i < kept.length - 1; i++) {
    const [a, b, c] = [kept[i - 1], kept[i], kept[i + 1]];
    hv.forEach((h, j) => {
      if (firstFire[j] < b || h[b] === null || h[a] === null) return;
      rows.push({ pass: b, hv: h[b]! / 10, fire: fires[j].slice(b, c).some((v) => (v ?? 0) > 0) });
    });
  }
  const testPasses = [...new Set(rows.map((r) => r.pass))].slice(-2);
  return {
    status: 'not_run',
    test_dates: testPasses.map((t) => dates[t]),
    model_pr_auc: null,
    model_pr_auc_ci: null,
    best_baseline: null,
    lift: fireLift(rows.filter((r) => testPasses.includes(r.pass))),
  };
}
