import type { Key } from './en';

// Indonesian. A native speaker on the team reviews every line marked REVIEW.
export const id: Record<Key, string> = {
  'app.title': "Peat's Breath",
  'app.subtitle': 'Napas Gambut',
  'badge.simulated': 'Data simulasi',
  'badge.simulated.title': 'Semua angka dalam prototipe ini dibuat oleh skrip, bukan diambil dari satelit.', // REVIEW

  'nav.label': 'Utama',
  'nav.reveal': 'Asap dan radar', // REVIEW
  'nav.map': 'Peta musim', // REVIEW
  'nav.scorecard': 'Rapor', // REVIEW
  'nav.method': 'Metode',

  'load.title': 'Memuat musim', // REVIEW
  'error.title': 'Paket data gagal dimuat', // REVIEW
  'error.body': 'Aplikasi memeriksa setiap berkas terhadap kontrak data sebelum menampilkan apa pun. Berkas ini gagal:', // REVIEW
  'error.file': 'Berkas',
  'error.field': 'Kolom', // REVIEW
  'error.detail': 'Masalah',
  'error.hint': 'Perbaiki berkasnya, atau arahkan VITE_BUNDLE_URL ke paket yang valid, lalu muat ulang.', // REVIEW
  'error.retry': 'Muat ulang',

  'timeline.label': 'Lintasan radar', // REVIEW
  'timeline.play': 'Putar musim', // REVIEW
  'timeline.pause': 'Jeda',
  'timeline.prev': 'Lintasan sebelumnya', // REVIEW
  'timeline.next': 'Lintasan berikutnya', // REVIEW
  'timeline.pass': 'Lintasan {i} dari {n}', // REVIEW
  'timeline.dropped': 'Tidak ada radar yang dapat dipakai pada lintasan ini', // REVIEW
  'timeline.help': 'Panah kiri dan kanan berpindah lintasan. Spasi untuk putar dan jeda.', // REVIEW

  'legend.title': 'Kondisi gambut pada {date}', // REVIEW
  'counts.total': '{n} sel berukuran 500 m', // REVIEW
  'counts.dropped': 'Lintasan ini dibuang: {reason}', // REVIEW

  'map.label': 'Peta sel gambut yang diwarnai menurut kondisi', // REVIEW
  'map.basemap': 'Peta latar', // REVIEW
  'map.basemap.osm': 'OpenStreetMap',
  'map.basemap.none': 'Tidak ada',
  'map.selected': 'Sel terpilih {id}', // REVIEW
  'map.clear': 'Hapus pilihan', // REVIEW
  'map.webgl': 'Peramban ini tidak dapat menggambar peta (WebGL mati atau tidak didukung). Jumlah di samping legenda tetap menjelaskan setiap sel.', // REVIEW

  'state.1': 'Tidak ada data',
  'state.2': 'Api, radar mendeteksi',
  'state.3': 'Api, radar tidak mendeteksi',
  'state.4': 'Terbakar',
  'state.5': 'Membasah kembali',
  'state.6': 'Mengering parah',
  'state.7': 'Mengering',
  'state.8': 'Stabil',

  'lang.switch': 'English',

  'stub.title': 'Layar ini menyusul berikutnya', // REVIEW
  'stub.body': 'Peta musim sudah siap. Buka untuk melihat kekeringan menyebar dari lintasan ke lintasan.', // REVIEW
  'stub.cta': 'Buka peta musim', // REVIEW
};
