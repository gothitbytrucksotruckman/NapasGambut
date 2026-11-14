// Display metadata for state codes: colour token, legend symbol, and the order the legend lists them.
// Labels come from i18n; the codes themselves come from the contract.
import { STATE } from '../contract';

/** Legend order: worst news first, so a fire brigade reads fire before drying. */
export const STATE_ORDER = [STATE.fire_radar, STATE.fire_silent, STATE.burned, STATE.deep_drying, STATE.drying, STATE.rewetting, STATE.stable, STATE.no_data] as const;

export const STATE_COLOR_VAR: Record<number, string> = {
  [STATE.no_data]: '--s-nodata',
  [STATE.fire_radar]: '--s-fire',
  [STATE.fire_silent]: '--s-fire',
  [STATE.burned]: '--s-burned',
  [STATE.rewetting]: '--s-rewet',
  [STATE.deep_drying]: '--s-deep',
  [STATE.drying]: '--s-drying',
  [STATE.stable]: '--s-stable',
};

/** Read the resolved colour of a CSS custom property (MapLibre needs real colours, not var()). */
export const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
