import { describe, expect, it } from 'vitest';
import { parseHash, toHash } from '../../src/state/hash';

const dates = ['2026-06-20', '2026-07-02', '2026-09-24'];
const cells = new Set(['r012c034']);
const ctx = { dates, hasCell: (id: string) => cells.has(id) };

describe('url hash', () => {
  it('round-trips a full view', () => {
    const v = { screen: 'map', dateIndex: 2, selectedCell: 'r012c034', layer: 'hv', lang: 'id' } as const;
    expect(parseHash(toHash(v, dates), ctx)).toEqual(v);
  });
  it('defaults to the reveal screen with no hash', () => {
    expect(parseHash('', ctx)).toEqual({ screen: 'reveal', dateIndex: 0, selectedCell: null, layer: 'state', lang: 'en' });
  });
  it('falls back safely on unknown date, cell, layer, screen and language', () => {
    expect(parseHash('#/nowhere?d=1999-01-01&cell=r999c999&layer=xyz&lang=fr', ctx)).toEqual({
      screen: 'reveal', dateIndex: 0, selectedCell: null, layer: 'state', lang: 'en',
    });
  });
  it('falls back from layer=coh to state when coherence is absent', () => {
    expect(parseHash('#/map?layer=coh', { ...ctx, hasCoherence: false }).layer).toBe('state');
    expect(parseHash('#/map?layer=coh', { ...ctx, hasCoherence: true }).layer).toBe('coh');
  });
  it('drops a malformed cell id', () => {
    expect(parseHash('#/map?cell=<script>', ctx).selectedCell).toBeNull();
  });
});
