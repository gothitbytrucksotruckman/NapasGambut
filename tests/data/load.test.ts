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

  it('loads both 0.1 bundles (without canals) and 0.2 bundles (with canals)', async () => {
    const m = readJson('manifest.json');
    const sc = readJson('scorecard.json');
    const cf = readJson('context_features.geojson');
    const scNoCanals = { ...sc, rankings: { fastest_drying: sc.rankings.fastest_drying, dams_to_inspect: sc.rankings.dams_to_inspect } };
    const cfNoIds = {
      ...cf,
      features: cf.features.map((f: { properties: { kind: string; name_en: string | null; name_id: string | null } } & Record<string, unknown>) => ({
        ...f,
        properties: { kind: f.properties.kind, name_en: f.properties.name_en, name_id: f.properties.name_id },
      })),
    };
    const v1 = await loadBundle(
      BASE,
      fakeFetch({
        'manifest.json': { ...m, schema_version: '0.1' },
        'scorecard.json': scNoCanals,
        'context_features.geojson': cfNoIds,
      }),
    );
    expect(v1.manifest.schema_version).toBe('0.1');
    expect(v1.scorecard.rankings.canals).toBeUndefined();

    const v2 = await loadBundle(BASE, fakeFetch());
    expect(v2.manifest.schema_version).toBe('0.2');
    expect(v2.scorecard.rankings.canals?.length).toBeGreaterThan(0);
  });
});
