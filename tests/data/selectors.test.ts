import { beforeAll, describe, expect, it } from 'vitest';
import { loadBundle } from '../../src/data/load';
import type { Bundle } from '../../src/data/load';
import { cellSeries, countsByState, isDropped, statesAtDate } from '../../src/data/selectors';
import { fakeFetch, readJson } from './fixture';

let b: Bundle;
beforeAll(async () => { b = await loadBundle('http://x/', fakeFetch()); });

describe('selectors', () => {
  it('returns a cell series by id, independent of geojson order', async () => {
    const cells = readJson('cells.geojson');
    cells.features.reverse();
    const shuffled = await loadBundle('http://x/', fakeFetch({ 'cells.geojson': cells }));
    const id = b.series.cells[10];
    expect(cellSeries(shuffled, id)!.props.id).toBe(id);
    expect(cellSeries(shuffled, id)!.hh).toEqual(b.series.hh[10]);
  });

  it('returns null for an unknown cell', () => {
    expect(cellSeries(b, 'r999c999')).toBeNull();
  });

  it('ignores geojson features that are not in series.cells', async () => {
    const cells = readJson('cells.geojson');
    const extra = structuredClone(cells.features[0]);
    extra.properties.id = 'r099c099';
    cells.features.push(extra);
    const withExtra = await loadBundle('http://x/', fakeFetch({ 'cells.geojson': cells }));
    expect(withExtra.idx.feature.has('r099c099')).toBe(false);
  });

  it('counts every cell exactly once per date', () => {
    const counts = countsByState(b, 8);
    expect(Object.values(counts).reduce((a, c) => a + c, 0)).toBe(b.series.cells.length);
    expect(statesAtDate(b, 8)).toHaveLength(b.series.cells.length);
  });

  it('flags the dropped date', () => {
    expect(isDropped(b, b.idx.date.get('2026-10-30')!)).toBe(true);
    expect(isDropped(b, 0)).toBe(false);
  });
});
