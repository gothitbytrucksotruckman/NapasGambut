import { describe, expect, it } from 'vitest';
import { LAYER_RAMPS, rampColorExpr, rampGradient, rampStops } from '../src/layers/ramps';
import { CLASS_IDS } from '../src/contract';
import { en } from '../src/i18n/en';
import { id } from '../src/i18n/id';
import { LAYERS } from '../src/state/hash';

// Layer keys are built from template strings (`layer.${l}.title`), which the compiler cannot check.
describe('layer strings', () => {
  const dicts = { en: en as Record<string, string>, id: id as Record<string, string> };
  it('has a switch label for every layer and a legend for every layer in both languages', () => {
    for (const lang of ['en', 'id'] as const) {
      for (const l of LAYERS) expect(dicts[lang][`layer.${l}`], `${lang} layer.${l}`).toBeTruthy();
      for (const l of ['hh', 'hv', 'coh', 'radar']) {
        expect(dicts[lang][`layer.${l}.title`]).toBeTruthy();
        expect(dicts[lang][`layer.${l}.what`]).toBeTruthy();
      }
      for (const l of ['hh', 'hv', 'coh']) for (const end of ['low', 'high']) expect(dicts[lang][`layer.${l}.${end}`]).toBeTruthy();
    }
  });
  it('has a class label for every class the contract allows', () => {
    for (const c of CLASS_IDS) for (const lang of ['en', 'id'] as const) expect(dicts[lang][`class.${c}`]).toBeTruthy();
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
