import { describe, expect, it } from 'vitest';
import { BundleError, loadBundle } from '../../src/data/load';
import { fakeFetch, readJson } from './fixture';

const BASE = 'http://x/bundle/';

async function errorOf(p: Promise<unknown>): Promise<BundleError> {
  try { await p; } catch (e) { return e as BundleError; }
  throw new Error('expected loadBundle to fail');
}

describe('loadBundle', () => {
  it('loads the committed mock bundle and builds lookups', async () => {
    const b = await loadBundle(BASE, fakeFetch());
    expect(b.manifest.data_kind).toBe('mock');
    expect(b.idx.cell.size).toBe(b.series.cells.length);
    expect(b.idx.date.get('2026-09-24')).toBe(8);
    expect(b.imageUrl('images/x.png')).toBe('http://x/bundle/images/x.png');
  });

  it('names the file and field when the manifest is malformed', async () => {
    const m = readJson('manifest.json');
    const e = await errorOf(loadBundle(BASE, fakeFetch({ 'manifest.json': { ...m, dates: 'x' } })));
    expect(e).toBeInstanceOf(BundleError);
    expect(e.file).toBe('manifest.json');
    expect(e.field).toBe('dates');
  });

  it('names the row when a series row is too short', async () => {
    const s = readJson('series.json');
    s.hh[3] = s.hh[3].slice(1);
    const e = await errorOf(loadBundle(BASE, fakeFetch({ 'series.json': s })));
    expect(e.file).toBe('series.json');
    expect(e.field).toBe('hh[3]');
  });

  it('reports a missing file and invalid JSON', async () => {
    expect((await errorOf(loadBundle(BASE, fakeFetch({ 'context.json': 404 })))).file).toBe('context.json');
    expect((await errorOf(loadBundle(BASE, fakeFetch({ 'scorecard.json': '{oops' })))).file).toBe('scorecard.json');
  });

  it('rejects series dates that differ from the manifest', async () => {
    const s = readJson('series.json');
    s.dates = [...s.dates].reverse();
    expect((await errorOf(loadBundle(BASE, fakeFetch({ 'series.json': s })))).field).toBe('dates');
  });

  it('accepts a real-data manifest with no seed and real geometry', async () => {
    const m = readJson('manifest.json');
    const nisar = { ...m, data_kind: 'nisar', generator: { ...m.generator, seed: null }, geometry: { track: 12, frame: 3, direction: 'A' } };
    const b = await loadBundle(BASE, fakeFetch({ 'manifest.json': nisar }));
    expect(b.manifest.data_kind).toBe('nisar');
  });
});
