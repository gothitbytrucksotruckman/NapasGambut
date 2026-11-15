// Schema 0.2 model fields as display views. Lookup only: nothing here recomputes a model result.
import type { CellProperties, CoverId, Manifest, Scorecard } from '../contract';

export interface CoverView {
  kind: 'one' | 'several' | 'cant_tell';
  covers: CoverId[];
  mapCheck: { map: CoverId; radar: CoverId } | null;
  simulated: boolean;
}

/** The radar's cover set for a cell, or null when the bundle has none (0.1) or the land model was not used. */
export function coverView(props: CellProperties, landModel: Manifest['land_model']): CoverView | null {
  const set = props.cover_set;
  if (!set || !landModel || landModel.status === 'not_used') return null;
  return {
    kind: set.length === 0 ? 'cant_tell' : set.length === 1 ? 'one' : 'several',
    covers: set,
    mapCheck: props.map_check && set.length > 0 ? { map: props.map_check, radar: set[0] } : null,
    simulated: landModel.status === 'simulated',
  };
}

export interface FireRiskView {
  status: NonNullable<Scorecard['fire_risk']>['status'];
  testDates: string[];
  rows: NonNullable<Scorecard['fire_risk']>['lift'];
  model: { prAuc: number; lo: number; hi: number } | null;
  baseline: { id: 'B1' | 'B2' | 'B3'; prAuc: number } | null;
}

export function fireRiskView(fr: Scorecard['fire_risk']): FireRiskView | null {
  if (!fr) return null;
  const ci = fr.model_pr_auc_ci;
  return {
    status: fr.status,
    testDates: fr.test_dates,
    rows: fr.lift,
    model: fr.model_pr_auc !== null && ci ? { prAuc: fr.model_pr_auc, lo: ci[0], hi: ci[1] } : null,
    baseline: fr.best_baseline ? { id: fr.best_baseline.id, prAuc: fr.best_baseline.pr_auc } : null,
  };
}

export const landCoverageTest = (tests: Scorecard['tests']) => tests.find((x) => x.id === 'land_model_coverage') ?? null;
