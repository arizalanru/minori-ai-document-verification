# Pengujian backend

Jalankan seluruh tes tanpa jaringan atau provider AI:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Tes memakai SQLite sementara, adapter OCR/LLM simulasi, dan gambar kecil
sintetis. Cakupannya meliputi aturan kelayakan demo, usia, konflik data,
kelengkapan, versi, koreksi, idempotensi, validasi bukti, kegagalan provider,
isolasi pendaftaran, hasil AI terlambat, dan pemulihan proses terhenti.

`scripts/demo_backend.py` adalah demo HTTP yang terpisah dan dapat memanggil
provider AI. Hasil tes layanan tidak mengukur akurasi OCR atau LLM.
