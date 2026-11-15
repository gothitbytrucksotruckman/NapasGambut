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

  // Pulse card (milestone 3)
  'pulse.title': 'Sel {id}',
  'pulse.close': 'Tutup sel', // REVIEW
  'pulse.chartTitle': 'Denyut musim untuk sel {id}', // REVIEW
  'pulse.class': 'Jenis lahan',
  'pulse.canal': 'Kerapatan kanal', // REVIEW
  'pulse.canalUnit': 'km per km²',
  'pulse.tree': 'Tutupan pohon', // REVIEW
  'pulse.pixels': 'Piksel 20 m yang valid', // REVIEW
  'pulse.pixelsOf': '{n} dari 625',
  'pulse.reading': 'Bacaan', // REVIEW
  'pulse.copy': 'Salin tautan ke sel ini', // REVIEW
  'pulse.copied': 'Tautan disalin',
  'pulse.copyFail': 'Gagal menyalin. Pilih tautan di bawah lalu salin sendiri.', // REVIEW
  'pulse.notFound': 'Sel ini tidak ada dalam paket data.', // REVIEW
  'pulse.lineLabel': 'Garis utama', // REVIEW
  'pulse.mode.hh': 'HH: tanah', // REVIEW
  'pulse.mode.hv': 'HV: tajuk', // REVIEW
  'pulse.mode.ratio': 'HH dikurangi HV', // REVIEW
  'pulse.explain.hh': 'HH mengirim dan menerima gelombang secara mendatar, jadi ia mendengarkan lantai: tanah basah dan air memantulkannya dengan kuat.\nGaris yang turun berarti permukaan gambut mengering.', // REVIEW
  'pulse.explain.hv': 'HV mengirim mendatar dan mendengarkan tegak. Hanya daun dan ranting yang memutar gelombang seperti itu, jadi ia mendengarkan perabot.\nPenurunan tiba-tiba setelah api berarti tajuk terbakar.', // REVIEW
  'pulse.explain.ratio': 'HH dikurangi HV membandingkan lantai dengan perabot.\nNilainya naik saat tanah tetap basah di bawah tajuk yang menipis, dan turun saat tanah mengering di bawah tutupan yang utuh.', // REVIEW
  'pulse.axis.db': 'Perubahan dB sejak 20 Juni', // REVIEW
  'pulse.axis.coh': 'Koherensi', // REVIEW
  'pulse.axis.rain': 'Hujan, mm',
  'pulse.axis.fire': 'Api',
  'pulse.band': 'Pita derau (±{k}σ)', // REVIEW
  'pulse.legend.hh': 'Indeks kebasahan radar (HH)', // REVIEW
  'pulse.legend.hv': 'Indeks tajuk (HV)', // REVIEW
  'pulse.legend.ratio': 'HH dikurangi HV', // REVIEW
  'pulse.legend.coh': 'Koherensi, per selang', // REVIEW
  'pulse.legend.rain': 'Hujan, per selang', // REVIEW
  'pulse.legend.fire': 'Deteksi api (isi: radar mendeteksi, kosong: radar tidak mendeteksi)', // REVIEW
  'pulse.dropped': 'dibuang', // REVIEW
  'pulse.table': 'Tampilkan angka', // REVIEW
  'pulse.th.date': 'Lintasan', // REVIEW
  'pulse.th.state': 'Kondisi',
  'pulse.th.hh': 'HH dB',
  'pulse.th.hv': 'HV dB',
  'pulse.th.coh': 'Koherensi', // REVIEW
  'pulse.th.rain': 'Hujan mm',
  'pulse.th.rain3d': 'Hujan 3 hari mm', // REVIEW
  'pulse.noCoherence': 'Tidak ada dalam paket data ini', // REVIEW
  'timeline.rain3d': 'Hujan 3 hari: {mm} mm', // REVIEW
  'pulse.th.fire': 'Api',
  'pulse.sketch.hh': 'Sketsa: gelombang radar mengenai tanah basah dan memantul lurus kembali.', // REVIEW
  'pulse.sketch.hv': 'Sketsa: gelombang radar tersebar di antara daun dan ranting lalu kembali terpuntir.', // REVIEW
  'pulse.sketch.ratio': 'Sketsa: gema lantai dan tajuk berdampingan.', // REVIEW
  'class.drained': 'Gambut terdrainase',
  'class.rewetted': 'Gambut yang dibasahi kembali',
  'class.plantation': 'Perkebunan di atas gambut',
  'class.intact_forest': 'Hutan rawa gambut utuh',
  'class.reference_forest': 'Hutan acuan (tanah mineral)',
  'class.settlement': 'Permukiman',

  // Reveal, scorecard, method (milestone 4)
  'reveal.headline': 'Pada {date}, asap menutupi tanah. Radar tetap melihatnya.', // REVIEW
  'reveal.lede': 'Radar memancarkan gelombang mikronya sendiri dan mendengarkan pantulannya, sehingga bekerja pada malam hari dan menembus asap serta awan yang membutakan kamera satelit biasa.', // REVIEW
  'reveal.cta': 'Saksikan musimnya', // REVIEW
  'reveal.optical': 'Kamera satelit',
  'reveal.radar': 'Radar pita L', // REVIEW
  'reveal.divider': 'Geser antara tampilan kamera dan tampilan radar', // REVIEW
  'reveal.dividerValue': '{n}% radar',
  'reveal.simNote': 'Kedua gambar dibuat dari paket data simulasi, bukan diambil oleh satelit.', // REVIEW
  'reveal.rulerNote': 'Satu garis untuk setiap lintasan radar 12 hari. Gambar ini adalah lintasan {i} dari {n}.', // REVIEW
  'reveal.imgOptical': 'Tampilan kamera simulasi dari lanskap gambut, hampir seluruhnya tertutup asap cokelat keabuan.', // REVIEW
  'reveal.imgRadar': 'Tampilan radar simulasi dari area yang sama, memperlihatkan sungai, blok kanal, perkebunan, dan hutan dengan jelas.', // REVIEW

  'score.title': 'Rapor', // REVIEW
  'score.lede': 'Seperti apa musim ini bagi setiap jenis lahan, dan di mana harus bertindak lebih dulu.', // REVIEW
  'score.classes': 'Menurut jenis lahan', // REVIEW
  'score.th.class': 'Jenis lahan',
  'score.th.n': 'Sel',
  'score.th.median': 'Indeks kebasahan terendah, median', // REVIEW
  'score.th.spread': 'Separuh sel di tengah', // REVIEW
  'score.th.burned': 'Terbakar',
  'score.th.recovery': 'Lintasan sampai pulih, median', // REVIEW
  'score.noRecovery': 'tidak ada yang pulih', // REVIEW
  'score.spreadText': '{a} sampai {b} dB',
  'score.fastest': 'Tempat menutup kanal lebih dulu', // REVIEW
  'score.fastestNote': 'Sel terdrainase dan perkebunan yang indeks kebasahannya turun paling rendah musim ini.', // REVIEW
  'score.dams': 'Sekat kanal yang perlu diperiksa', // REVIEW
  'score.damsNote': 'Sel yang dibasahi kembali tetapi mengering lebih parah daripada sel terdrainase pada umumnya. Sekatnya mungkin bocor.', // REVIEW
  'score.th.rank': 'Peringkat',
  'score.th.cell': 'Sel',
  'score.th.min': 'Terendah, dB',
  'score.th.when': 'Kapan',
  'score.th.gap': 'Di bawah median terdrainase, dB', // REVIEW
  'score.open': 'Buka sel {id} di peta', // REVIEW
  'score.empty': 'Tidak ada sel yang memenuhi aturan ini.', // REVIEW
  'score.tests': 'Pemeriksaan pola', // REVIEW
  'score.testValue': '{statistic}: {value}, dari {n} sel.', // REVIEW
  'score.mockNote': 'Pemeriksaan ini dijalankan pada data simulasi. Hasilnya menunjukkan metodenya bekerja dari awal sampai akhir, bukan keadaan gambut yang sebenarnya.', // REVIEW

  'method.title': 'Metode dan batasan', // REVIEW
  'method.mock': 'Semua angka dalam prototipe ini dibuat oleh skrip dari benih {seed}. Tidak ada yang diambil dari satelit. Alur kerja NISAR yang sebenarnya akan menulis berkas yang sama, dan aplikasi akan menampilkannya tanpa perubahan kode.', // REVIEW
  'method.radarH': 'Bagaimana radar melihat gambut', // REVIEW
  'method.radar1': 'NISAR membawa radar pita L. Seperti kelelawar, radar meneriakkan denyut dan mendengarkan gemanya sendiri, sehingga tidak perlu sinar matahari dan gelombang 24 cm-nya menembus asap dan awan.', // REVIEW
  'method.radar2': 'Tanah basah memantulkan sinyal kembali ke radar seperti jalan basah berkilau di bawah lampu mobil. Saat gambut mengering, pantulannya meredup. Garis HH yang turun di kartu denyut adalah peredupan itu.', // REVIEW
  'method.radar3': 'Radar mengirim dan menerima dalam dua arah. HH terutama mendengarkan lantai: tanah dan air. HV terutama mendengarkan perabot: daun dan ranting. Api membakar perabot, jadi HV turun tajam setelah kebakaran.', // REVIEW
  'method.indexH': 'Indeks kebasahan radar', // REVIEW
  'method.index': 'Untuk setiap sel 500 m, indeks adalah perubahan kecerahan HH sejak {first}, dalam desibel, dikurangi perubahan yang sama di hutan acuan pada tanah mineral. Pengurangan ini menghapus perubahan yang memengaruhi seluruh citra, seperti radar itu sendiri atau cuaca.', // REVIEW
  'method.rulesH': 'Bagaimana kondisi sel ditentukan', // REVIEW
  'method.rulesIntro': 'Pada setiap lintasan, aturan diperiksa dengan urutan ini. Aturan pertama yang cocok yang dipakai. σ (sigma) adalah batas derau: seberapa besar hutan acuan bergoyang pada lintasan itu.', // REVIEW
  'method.rule1': 'Tidak ada data: lintasan dibuang, atau kurang dari separuh sel memiliki piksel radar yang dapat dipakai.', // REVIEW
  'method.rule2': 'Api, radar mendeteksi: api terdeteksi sejak lintasan sebelumnya, dan radar juga menunjukkannya (HV turun lebih dari {k}σ, atau koherensi turun di bawah 20).', // REVIEW
  'method.rule3': 'Api, radar tidak mendeteksi: api terdeteksi, tetapi radar tidak menunjukkan tanda apa pun. Api permukaan berintensitas rendah bisa begini.', // REVIEW
  'method.rule4': 'Terbakar: sel pernah terbakar pada lintasan sebelumnya.', // REVIEW
  'method.rule5': 'Membasah kembali: hujan sudah kembali (satu selang dengan sedikitnya {rain} mm) dan indeks naik lebih dari {k}σ di atas titik terendahnya.', // REVIEW
  'method.rule6': 'Mengering parah: indeks lebih dari {deep}σ di bawah nol.', // REVIEW
  'method.rule7': 'Mengering: indeks lebih dari {k}σ di bawah nol.', // REVIEW
  'method.rule8': 'Stabil: tidak satu pun di atas. Perubahannya masih dalam batas derau.', // REVIEW
  'method.limitsH': 'Yang tidak dapat diketahui dari radar', // REVIEW
  'method.limit1': 'Indeks ini adalah sinyal kebasahan relatif, bukan kedalaman muka air dalam sentimeter. Sumur pantau lapangan tetap diperlukan untuk mengubahnya menjadi kedalaman.', // REVIEW
  'method.limit2': 'Di bawah hutan rawa yang rapat dan utuh, tajuk menyerap sebagian besar sinyal, sehingga radar hanya sedikit melihat permukaan gambut. Perubahan kecil di sana bisa terlewat.', // REVIEW
  'method.limit3': 'Api berintensitas rendah yang membara di bawah permukaan bisa membiarkan tajuk tetap berdiri. Radar mungkin tidak mendeteksinya; deteksi api satelit tetap menangkap banyak di antaranya.', // REVIEW
  'method.limit4': 'Satu lintasan setiap 12 hari bisa melewatkan api yang mulai dan padam di antara dua lintasan.', // REVIEW
  'method.factsH': 'Paket data ini', // REVIEW
  'method.kind': 'Jenis data',
  'method.kind.mock': 'Simulasi',
  'method.kind.nisar': 'NISAR',
  'method.generator': 'Pembuat data', // REVIEW
  'method.seed': 'Benih', // REVIEW
  'method.area': 'Wilayah kajian', // REVIEW
  'method.cellSize': 'Ukuran sel',
  'method.passes': 'Lintasan radar', // REVIEW
  'method.passesValue': '{n} lintasan, {first} sampai {last}', // REVIEW
  'method.thresholds': 'Ambang batas', // REVIEW
  'method.thresholdsValue': 'perubahan {k}σ, utama {h}σ, parah {deep}σ, hujan dianggap kembali pada {rain} mm', // REVIEW
  'method.sigmaRange': 'Batas derau σ', // REVIEW
  'method.sigmaValue': '{lo} sampai {hi} dB',
  'method.dropped': 'Lintasan yang dibuang', // REVIEW
  'method.noneDropped': 'Tidak ada',
  'method.scenes': 'Citra radar yang dipakai', // REVIEW
  'method.noScenes': 'Tidak ada. Paket ini adalah simulasi.', // REVIEW
  'method.geometry': 'Orbit',
  'method.geometryNone': 'Belum ditetapkan', // REVIEW
  'method.sourcesH': 'Sumber',
  'method.futureH': 'Yang bisa dilakukan NISAR berikutnya', // REVIEW
  'method.future1': 'Rekaman setahun penuh, agar musim kemarau bisa dibandingkan dengan musim hujan yang mengisi kembali gambut.', // REVIEW
  'method.future2': 'Pemantauan setiap 12 hari sepanjang musim kemarau, dikirim ke tim restorasi selagi masih ada waktu untuk menutup kanal.', // REVIEW
  'method.future3': 'Metode yang sama untuk gambut tropis lain: Cekungan Kongo dan Amazon Peru.', // REVIEW
  'method.future4': 'Memadukan radar pita L NISAR dengan radar pita S-nya, yang lebih peka terhadap tajuk, untuk memisahkan lantai dan perabot dengan lebih bersih.', // REVIEW

  // Map layers and theme (milestone 5)
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
  // Schema 0.2: model lahan dan hindcast risiko kebakaran
  'cover.forest': 'Hutan', // REVIEW
  'cover.degraded': 'Lahan terbuka atau terdegradasi', // REVIEW
  'cover.plantation': 'Perkebunan', // REVIEW
  'cover.built': 'Lahan terbangun', // REVIEW
  'pulse.cover': 'Tutupan menurut radar', // REVIEW
  'pulse.coverSeveral': 'Salah satu dari: {list}', // REVIEW
  'pulse.coverCantTell': 'Radar tidak bisa memastikan', // REVIEW
  'pulse.coverSimulated': '(simulasi)', // REVIEW
  'pulse.coverHint': 'Kelas yang tidak bisa disingkirkan oleh radar, dicek terhadap peta 2021.', // REVIEW
  'pulse.mapCheck': 'Peta (2021): {map}. Radar (2026): {radar}. Perlu dicek di lapangan.', // REVIEW
  'score.fire': 'Hindcast risiko kebakaran, musim 2026, satu lokasi', // REVIEW
  'score.fire.passed': 'Model menempatkan sel yang terbakar lebih tinggi daripada aturan sederhana pada dua lintasan terakhir. Hasilnya ada di pemeriksaan di atas.', // REVIEW
  'score.fire.notPassed': 'Model tidak mengalahkan aturan sederhana, jadi hanya tabel yang ditampilkan.', // REVIEW
  'score.fire.numbers': 'PR-AUC model {m} (selang 95% {lo} sampai {hi}) dibandingkan aturan sederhana terbaik, {id} ({rule}): {b}.', // REVIEW
  'score.fire.B1': 'ada api dalam radius 2 km pada selang terakhir', // REVIEW
  'score.fire.B2': 'urutkan menurut indeks radar HV', // REVIEW
  'score.fire.B3': 'B1 dan B2 bersama-sama', // REVIEW
  'score.fire.notRun': 'Tidak ada model risiko kebakaran yang dijalankan pada bundel ini. Tabel di bawah hanya deskriptif.', // REVIEW
  'score.fire.caption': 'Bagian sel yang mengalami api sebelum lintasan berikutnya, menurut indeks radar HV, pada lintasan uji {dates}. Kelompok 1 memiliki indeks terendah.', // REVIEW
  'score.fire.th.fifth': 'Kelompok seperlima indeks radar HV', // REVIEW
  'score.fire.th.n': 'Sel-lintasan', // REVIEW
  'score.fire.th.fires': 'Api', // REVIEW
  'score.fire.th.rate': 'Tingkat api', // REVIEW
  'score.fire.limit': 'Hindcast satu musim di satu lokasi. Ini mengurutkan sel; ini bukan prakiraan.', // REVIEW
  'method.modelsH': 'Dua model dan batasannya', // REVIEW
  'method.landH': 'Tutupan lahan dari radar', // REVIEW
  'method.land1': 'Model pohon gradient-boosted membaca kecerahan dan tekstur radar di setiap sel: HH, HV, bagaimana HV berubah sepanjang musim, dan bagaimana HV bervariasi di dalam sel. Model ini memilah sel ke dalam empat jenis tutupan: hutan, lahan terbuka atau terdegradasi, perkebunan, dan lahan terbangun.', // REVIEW
  'method.land2': 'Model belajar dari peta 2021 (ESA WorldCover dan konsesi GFW). Kepadatan kanal dan pengeringan sengaja tidak dijadikan masukan, agar pemeriksaan kanal dan pengeringan tetap adil.', // REVIEW
  'method.land3': 'Setiap sel mendapat himpunan tutupan yang tidak bisa disingkirkan oleh radar. Pada blok 5 km yang disisihkan, himpunan itu memuat kelas peta sekitar {pct}% dari waktu. Angka ini berarti kesesuaian dengan peta 2021, bukan dengan kondisi di lapangan. Gambut dan kanal tetap diambil dari peta; radar tidak bisa melihat tanah gambut.', // REVIEW
  'method.landUsed': 'Jenis lahan di peta berasal dari model ini.', // REVIEW
  'method.landCoverage': 'Dicek pada blok yang disisihkan: {value}% dari {n} sel (target {pct}%).', // REVIEW
  'method.mapCheck': 'Sel tempat radar dengan yakin berbeda dari peta lama ditandai sebagai perlu dicek di lapangan. Banyak di antaranya sel campuran, bukan perubahan nyata.', // REVIEW
  'method.fireH': 'Hindcast risiko kebakaran', // REVIEW
  'method.fire1': 'Model logistik kecil mengurutkan sel menurut risiko kebakaran sampai lintasan berikutnya. Model hanya memakai apa yang sudah diketahui pada lintasan itu: indeks radar HV dan perubahannya, kepadatan kanal, jarak ke api sebelumnya, panjang selang, dan tutupan lahan.', // REVIEW
  'method.fire2': 'Model diuji pada dua lintasan terakhir yang tidak pernah dilihatnya, dibandingkan tiga aturan sederhana, dengan selang 95% dari pengambilan ulang blok 5 km. Model hanya ditampilkan jika batas bawahnya mengalahkan aturan terbaik; jika tidak, aplikasi menampilkan tabel dan menyebutkannya.', // REVIEW
  'method.fire3': 'Satu musim, satu lokasi, sedikit api: hindcast, bukan prakiraan.', // REVIEW
  'method.aiH': 'Penggunaan AI', // REVIEW
  'method.ai1': 'Kelas lahan dan hindcast risiko kebakaran memakai pembelajaran mesin (scikit-learn, himpunan konformal MAPIE, cleanlab).', // REVIEW
  'method.ai2': 'Tidak ada model bahasa yang berjalan di aplikasi. Setiap kalimat tentang sel berasal dari templat tetap.', // REVIEW
  'method.ai3': 'Asisten pemrograman AI membantu menulis perangkat lunak dan teks bahasa Indonesia, yang ditinjau oleh penutur asli.', // REVIEW
};
