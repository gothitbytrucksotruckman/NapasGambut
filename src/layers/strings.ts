// Milestone 5 strings (layers, theme), held here until src/i18n/ is committed; then merged and this file deleted.
export const enM5 = {
  'layer.label': 'Map shows',
  'layer.state': 'Condition',
  'layer.hh': 'Wetness (HH)',
  'layer.hv': 'Canopy (HV)',
  'layer.coh': 'Coherence',
  'layer.radar': 'Radar picture',
  'layer.hh.title': 'Radar wetness index (HH)',
  'layer.hh.what': 'Change since the first pass. Below zero means the peat surface is drier.',
  'layer.hh.low': 'drier',
  'layer.hh.high': 'wetter',
  'layer.hv.title': 'Canopy index (HV)',
  'layer.hv.what': 'Change since the first pass. A sharp drop usually means burned or cleared canopy.',
  'layer.hv.low': 'less canopy',
  'layer.hv.high': 'more canopy',
  'layer.coh.title': 'Coherence',
  'layer.coh.what': 'How alike the ground looked on this pass and the one before. Fire and heavy rain lower it.',
  'layer.coh.low': 'changed',
  'layer.coh.high': 'unchanged',
  'layer.coh.first': 'Coherence compares two passes, so the first pass has none.',
  'layer.radar.title': 'Radar picture',
  'layer.radar.what': 'The simulated radar image for this pass. Bright is a strong echo (wet ground, buildings, forest); black is open water.',
  'layer.clamp': 'Values beyond the ends of the bar use the end colour.',
  'theme.label': 'Theme',
  'theme.auto': 'Match device',
  'theme.light': 'Light',
  'theme.dark': 'Dark',
} as const;

export type M5Key = keyof typeof enM5;

export const idM5: Record<M5Key, string> = {
  'layer.label': 'Peta menampilkan', // REVIEW
  'layer.state': 'Kondisi',
  'layer.hh': 'Kebasahan (HH)', // REVIEW
  'layer.hv': 'Tajuk (HV)', // REVIEW
  'layer.coh': 'Koherensi', // REVIEW
  'layer.radar': 'Citra radar', // REVIEW
  'layer.hh.title': 'Indeks kebasahan radar (HH)', // REVIEW
  'layer.hh.what': 'Perubahan sejak lintasan pertama. Di bawah nol berarti permukaan gambut lebih kering.', // REVIEW
  'layer.hh.low': 'lebih kering',
  'layer.hh.high': 'lebih basah',
  'layer.hv.title': 'Indeks tajuk (HV)', // REVIEW
  'layer.hv.what': 'Perubahan sejak lintasan pertama. Penurunan tajam biasanya berarti tajuk terbakar atau dibuka.', // REVIEW
  'layer.hv.low': 'tajuk berkurang', // REVIEW
  'layer.hv.high': 'tajuk bertambah', // REVIEW
  'layer.coh.title': 'Koherensi', // REVIEW
  'layer.coh.what': 'Seberapa mirip tanah pada lintasan ini dengan lintasan sebelumnya. Api dan hujan lebat menurunkannya.', // REVIEW
  'layer.coh.low': 'berubah',
  'layer.coh.high': 'tidak berubah',
  'layer.coh.first': 'Koherensi membandingkan dua lintasan, jadi lintasan pertama tidak memilikinya.', // REVIEW
  'layer.radar.title': 'Citra radar', // REVIEW
  'layer.radar.what': 'Citra radar simulasi untuk lintasan ini. Terang berarti pantulan kuat (tanah basah, bangunan, hutan); hitam adalah air terbuka.', // REVIEW
  'layer.clamp': 'Nilai di luar ujung batang memakai warna ujungnya.', // REVIEW
  'theme.label': 'Tema',
  'theme.auto': 'Ikuti perangkat', // REVIEW
  'theme.light': 'Terang',
  'theme.dark': 'Gelap',
};

export function tl(lang: 'en' | 'id', key: M5Key | string): string {
  const d = (lang === 'en' ? enM5 : idM5) as Record<string, string>;
  const s = d[key];
  if (s === undefined) throw new Error(`missing string ${key}`);
  return s;
}
