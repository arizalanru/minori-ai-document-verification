# Asisten Verifikasi Berkas

Prototipe lokal untuk membantu admin memeriksa kelengkapan berkas peserta.
Aplikasi menerima gambar dokumen, menjalankan OCR dan ekstraksi terstruktur dengan
LLM, mengevaluasi aturan demo, lalu meminta admin memeriksa hasil terhadap gambar
sumber.

Proyek ini menggunakan FastAPI, SQLite, PaddleOCR, Gemini, dan halaman admin
sederhana. Aplikasi hanya ditujukan untuk demonstrasi lokal dan belum memiliki
autentikasi atau kontrol akses produksi.

## Batasan penting

- Gunakan dokumen sintetis. Label `demo_only` bukan pendeteksi data pribadi.
- Profil `demo-core-v1` dan `demo-full-v1` berisi asumsi demonstrasi, bukan
  kebijakan resmi program.
- Hasil `ELIGIBLE` hanya menyatakan aturan administrasi demo terpenuhi. Hasil ini
  bukan keputusan penerimaan atau bukti keaslian dokumen.
- OCR dan LLM hanya memproses KTP dan ijazah. Jenis dokumen lain tetap memerlukan
  pemeriksaan manual; aplikasi tidak melakukan analisis medis.
- Input hanya JPEG/PNG satu halaman. PDF dan dokumen multi-halaman belum
  didukung.
- Penyimpanan memakai kolom JSON di SQLite. Belum ada migrasi untuk mengubahnya
  menjadi tabel field dan snapshot terpisah.
- File hasil upload disimpan di luar direktori statis, tetapi endpoint file belum
  dilindungi autentikasi. Jalankan server hanya di `127.0.0.1`.

## Struktur proyek

```text
app/
  api/                 endpoint dan skema request HTTP
  adapters/            integrasi PaddleOCR dan Gemini
  core/                konfigurasi dan error domain
  db/                  koneksi dan schema SQLite
  domain/              schema ekstraksi, validasi bukti, dan aturan demo
  services/backend.py  alur aplikasi dan transaksi
  storage/              validasi dan penyimpanan gambar
  web/                  halaman admin, JavaScript, dan CSS
config/programs/        profil aturan demo
prompts/                instruksi ekstraksi LLM
scripts/                pemeriksaan struktur, smoke test, dan demo HTTP
tests/                  tes layanan dan aturan dengan data sintetis
```

## Instalasi

Contoh berikut memakai PowerShell dan virtual environment proyek:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\backend.txt
```

PaddlePaddle dan PaddleOCR tidak dipasang oleh `requirements/backend.txt` karena
paket runtime harus disesuaikan dengan Python, sistem operasi, dan perangkat yang
digunakan. Gunakan versi yang tercatat pada
`requirements/lock-windows-py312.txt` bila lingkungannya sesuai, lalu verifikasi
dengan smoke test.

Salin `.env.example` menjadi `.env` secara lokal dan isi konfigurasi yang
diperlukan. Jangan commit `.env` atau kunci API. Konfigurasi utama:

```dotenv
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
```

Nilai di atas mengikuti default pada kode saat ini. `GEMINI_MODEL` dapat diganti
melalui konfigurasi sesuai model yang tersedia bagi akun, tanpa mengubah kode.

- `DATABASE_PATH` dan `PRIVATE_FILES_DIR`: lokasi data lokal.
- `GEMINI_API_KEY` dan `GEMINI_MODEL`: kredensial dan model ekstraksi.
- `OCR_TIMEOUT_SECONDS` dan `LLM_TIMEOUT_SECONDS`: batas waktu provider.
- `MAX_UPLOAD_BYTES` dan `MAX_IMAGE_PIXELS`: batas gambar.

Nama variabel konfigurasi merupakan bagian dari kompatibilitas aplikasi dan
tidak boleh diubah tanpa migrasi.

## Menjalankan aplikasi

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1
```

Buka `http://127.0.0.1:8000/` untuk halaman admin atau
`http://127.0.0.1:8000/docs` untuk dokumentasi API. Gunakan satu proses server
dan hindari `--reload` saat OCR berjalan karena aplikasi memakai satu database
SQLite dan proses OCR terpisah.

Alur penggunaan:

1. Buat pendaftaran dengan profil demo.
2. Upload gambar sintetis KTP dan ijazah.
3. Jalankan OCR dan LLM pada masing-masing dokumen.
4. Bandingkan nilai ekstraksi dan bukti OCR dengan gambar sumber.
5. Koreksi bila perlu, isi alasan, lalu verifikasi atau minta upload ulang.
6. Tinjau hasil aturan. Hasil `FLAGGED` hanya dapat menjadi `INELIGIBLE` setelah
   konfirmasi admin.

Setiap aksi mutasi memakai `revision` terbaru. Konflik revisi menghasilkan HTTP
409 agar admin memuat ulang data sebelum mengulang aksi. Request key opsional
tersedia pada create, upload, process, dan review untuk idempotensi.

## Pengujian

Tes default tidak memakai jaringan, API berbayar, database `var`, atau dokumen
asli:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe scripts\check_structure.py
node --check app\web\static\admin.js
```

Tes layanan memakai SQLite sementara, gambar kecil sintetis, dan adapter
OCR/LLM simulasi. Tes tersebut memeriksa aturan, revisi, idempotensi, review,
validasi bukti, kegagalan provider, serta hasil proses yang terlambat. Tes ini
bukan pengukuran akurasi OCR/LLM dan bukan tes integrasi provider.

Smoke test berikut bersifat terpisah:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_ocr.py
.\.venv\Scripts\python.exe scripts\smoke_llm.py --ocr <path-ke-ocr_0.json>
```

`smoke_llm.py` melakukan satu panggilan Gemini berbayar. Jalankan hanya jika
memang ingin menguji provider. `scripts/demo_backend.py` membuat dua gambar
sintetis dan dapat melakukan hingga dua panggilan LLM melalui server lokal.

## Alur data

Upload memvalidasi format, ukuran, dan dimensi gambar sebelum menyimpan versi
baru. Saat pemrosesan dimulai, PaddleOCR menghasilkan blok teks beserta posisi
buktinya. Gemini mengubah blok tersebut menjadi enam field terstruktur tanpa
membuat keputusan kelayakan. Domain kemudian memvalidasi schema, nilai, kutipan,
dan ID bukti sebelum hasil dipublikasikan.

Evaluator membuat snapshot dari versi dokumen aktif, koreksi admin, dan profil
aturan demo. Nilai `PASS`, `FAIL`, atau `UNKNOWN` digabungkan menjadi
`ELIGIBLE`, `FLAGGED`, atau `REVIEW`. Admin tetap harus melihat gambar sumber,
memperbaiki nilai bila perlu, dan mencatat alasan review. Setiap perubahan
membatalkan evaluasi lama sebagai hasil aktif, tetapi riwayat evaluasi dan review
tetap disimpan.
