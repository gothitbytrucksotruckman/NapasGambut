import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { formatDb, sigmaRange, testSentence } from '../src/data/scorecardText';

// String parity and copy rules for these screens are covered by tests/i18n.test.ts.
const sc = JSON.parse(readFileSync(join(__dirname, '../public/bundle/scorecard.json'), 'utf8'));
const manifest = JSON.parse(readFileSync(join(__dirname, '../public/bundle/manifest.json'), 'utf8'));

describe('scorecard text', () => {
  it('formats dB with a true minus sign and one decimal', () => {
    expect(formatDb(-2.1)).toBe('−2.1');
    expect(formatDb(0.25)).toBe('+0.3');
    expect(formatDb(0)).toBe('0.0');
  });

  it('builds one sentence per test with its value and count, from the bundle only', () => {
    for (const test of sc.tests) {
      const s = testSentence(test, 'en');
      expect(s).toContain(String(test.n));
      expect(s).toContain(test.statistic);
      expect(s.endsWith('.')).toBe(true);
    }
  });

  it('uses the Indonesian name and note when the language is id', () => {
    const t0 = sc.tests[0];
    expect(testSentence(t0, 'id')).toContain(String(t0.n));
  });

  it('reads the sigma range from the manifest and skips nulls', () => {
    const r = sigmaRange(manifest.thresholds.sigma_db);
    const vals = manifest.thresholds.sigma_db.filter((v: number | null) => v !== null);
    expect(r).toEqual({ lo: Math.min(...vals), hi: Math.max(...vals) });
    expect(sigmaRange([null, null])).toBeNull();
  });
});
