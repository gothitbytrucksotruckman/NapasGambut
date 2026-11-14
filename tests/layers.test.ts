import { describe, expect, it } from 'vitest';
import { LAYER_RAMPS, rampColorExpr, rampGradient, rampStops } from '../src/layers/ramps';
import { enM5, idM5, tl } from '../src/layers/strings';
import { LAYERS } from '../src/state/hash';

describe('milestone 5 strings', () => {
  it('has the same keys in English and Indonesian', () => {
    expect(Object.keys(idM5).sort()).toEqual(Object.keys(enM5).sort());
  });
  it('has a switch label for every layer and a legend for every continuous layer', () => {
    for (const l of LAYERS) expect(tl('en', `layer.${l}`)).toBeTruthy();
    for (const l of ['hh', 'hv', 'coh', 'radar']) for (const lang of ['en', 'id'] as const) expect(tl(lang, `layer.${l}.title`)).toBeTruthy();
  });
  it('contains no em dash and no "measured/observed" claims', () => {
    for (const v of [...Object.values(enM5), ...Object.values(idM5)]) expect(v).not.toContain('—');
    for (const v of Object.values(enM5)) expect(v).not.toMatch(/\bmeasured\b|\bobserved\b|detected by NISAR/i);
  });
  it('fails loudly on a missing key instead of rendering it', () => {
    expect(() => tl('en', 'layer.nope')).toThrow();
  });
});

describe('ramp gradient', () => {
  it('places the zero stop of the dB ramp at 80% of the bar', () => {
    expect(rampGradient('hh')).toContain('#d9d8d2 80.0%');
  });
});

describe('continuous layer ramps', () => {
  it('defines a fixed display domain for every continuous layer', () => {
    expect(LAYER_RAMPS.hh.domain).toEqual([-4, 1]);
    expect(LAYER_RAMPS.hv.domain).toEqual([-4, 1]);
    expect(LAYER_RAMPS.coh.domain).toEqual([0, 100]);
  });

  it('keeps zero at the neutral midpoint of the diverging dB ramps', () => {
    const stops = rampStops('hh');
    const zero = stops.find((s) => s.value === 0);
    expect(zero?.color).toBe(LAYER_RAMPS.hh.neutral);
  });

  it('orders stops by value and uses only hex colours', () => {
    for (const layer of ['hh', 'hv', 'coh'] as const) {
      const v = rampStops(layer).map((s) => s.value);
      expect([...v].sort((a, b) => a - b)).toEqual(v);
      for (const s of rampStops(layer)) expect(s.color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it('builds a MapLibre expression that falls back to the no-data colour', () => {
    const e = rampColorExpr('hh', '#cccccc') as unknown[];
    expect(e[0]).toBe('case');
    expect(JSON.stringify(e)).toContain('feature-state');
    expect(e[e.length - 1]).toBe('#cccccc');
  });
});
