import { describe, expect, it } from 'vitest';
import { en } from '../src/i18n/en';
import { id } from '../src/i18n/id';
import { t } from '../src/i18n';

describe('i18n', () => {
  it('has the same keys in English and Indonesian', () => {
    expect(Object.keys(id).sort()).toEqual(Object.keys(en).sort());
  });
  it('contains no em dash in any string', () => {
    for (const v of [...Object.values(en), ...Object.values(id)]) expect(v).not.toContain('—');
  });
  it('never claims mock values were measured or observed', () => {
    for (const v of Object.values(en)) expect(v).not.toMatch(/\bmeasured\b|\bobserved\b|detected by NISAR/i);
  });
  it('fills template variables', () => {
    expect(t('en', 'counts.total', { n: 12 })).toContain('12');
  });
});
