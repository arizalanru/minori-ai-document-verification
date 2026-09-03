"""Pemeriksaan sintaks/konfigurasi saja; bukan tes aplikasi atau AI."""
import ast
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
count = 0
for directory in (root / "app", root / "scripts"):
    for path in directory.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += 1
profiles = list((root / "config/programs").glob("*.json"))
for path in profiles:
    json.loads(path.read_text(encoding="utf-8"))
print(f"Sintaks {count} file Python dan {len(profiles)} profil JSON valid.")
print("Belum memeriksa dependency, API, OCR, LLM, database, atau aturan bisnis.")
