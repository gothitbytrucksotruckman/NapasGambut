import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { readingFor } from '../src/data/reading';

const DATES = ['2026-06-20', '2026-07-02', '2026-07-14', '2026-07-26', '2026-08-07', '2026-08-19', '2026-08-31', '2026-09-12', '2026-09-24', '2026-10-06', '2026-10-18', '2026-10-30', '2026-11-11'];
const LANGS = ['en', 'id'] as const;

const clean = (s: string) => {
  expect(s.length).toBeGreaterThan(10);
  expect(s).not.toMatch(/undefined|NaN|null|\{|\}|—/);
  expect(s.trim().endsWith('.')).toBe(true);
};

// 8 stable, 7 drying, 6 deep, 2 fire radar, 3 fire silent, 4 burned, 5 rewetting, 1 no data
const shapes: Record<string, number[]> = {
  allNoData: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
  flat: [8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 1, 8],
  dried: [8, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 1, 7],
  driedDeep: [8, 8, 7, 7, 6, 6, 6, 6, 6, 6, 6, 1, 6],
  burnedRadar: [8, 7, 7, 6, 6, 6, 6, 2, 4, 4, 4, 1, 4],
  burnedSilent: [8, 7, 7, 6, 6, 6, 6, 3, 4, 4, 4, 1, 4],
  fullStory: [8, 7, 7, 7, 6, 6, 6, 6, 2, 4, 4, 1, 4],
  driedThenRewet: [8, 7, 7, 7, 6, 6, 6, 6, 6, 6, 6, 1, 5],
  flatThenRewet: [8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 1, 5],
  fireWithoutDrying: [8, 8, 8, 8, 8, 8, 8, 2, 4, 4, 4, 1, 4],
  backToStable: [8, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 1, 8],
  firstDateDropped: [1, 8, 7, 7, 7, 7, 7, 7, 7, 7, 7, 1, 7],
};

describe('reading sentence', () => {
  for (const [name, seq] of Object.entries(shapes))
    it(`reads the "${name}" shape in both languages`, () => {
      for (const lang of LANGS) clean(readingFor(seq, DATES, lang));
    });

  it('matches the brief example for a dried, burned, unrecovered cell', () => {
    expect(readingFor(shapes.fullStory, DATES, 'en')).toBe(
      'Dried from early July and reached deep drying by early August, burned in late September, no recovery yet.',
    );
  });

  it('does not repeat the date when a cell goes straight to deep drying', () => {
    const straightDeep = [8, 8, 8, 6, 6, 6, 6, 6, 6, 6, 6, 1, 5];
    expect(readingFor(straightDeep, DATES, 'en')).toBe('Went straight to deep drying in late July, began re-wetting by mid November.');
    expect(readingFor(straightDeep, DATES, 'id')).not.toMatch(/akhir Juli.*akhir Juli/);
  });

  it('says a flat cell stayed within the noise', () => {
    expect(readingFor(shapes.flat, DATES, 'en')).toBe('Stayed within the noise all season.');
  });

  it('notes when the radar did not see the fire', () => {
    expect(readingFor(shapes.burnedSilent, DATES, 'en')).toContain('the radar did not see the fire');
  });

  it('never fails on any sequence of codes, even ones the rules cannot produce', () => {
    const codes = [1, 2, 3, 4, 5, 6, 7, 8];
    for (let n = 0; n < 8 ** 5; n++) {
      const seq = Array.from({ length: 5 }, (_, k) => codes[Math.floor(n / 8 ** k) % 8]);
      for (const lang of LANGS) clean(readingFor(seq, DATES.slice(0, 5), lang));
    }
  });

  it('reads every cell in the committed mock bundle', () => {
    const s = JSON.parse(readFileSync(join(__dirname, '../public/bundle/series.json'), 'utf8'));
    for (const row of s.state as number[][]) clean(readingFor(row, s.dates, 'en'));
  });
});
