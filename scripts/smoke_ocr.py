"""Smoke test OCR sintetis.

Tidak memakai Gemini, dokumen asli, atau endpoint aplikasi.
API rujukan: https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md
"""
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import argparse
import json
import platform
import time


def create_fixture(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for candidate in ("C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(candidate, 36)
            break
        except OSError:
            continue
    if font is None:
        raise RuntimeError("Font Arial/DejaVuSans tidak ditemukan; fixture belum dibuat.")
    lines = [
        "DOKUMEN SINTETIS - DEMO OCR",
        "Nama: PESERTA DEMO A",
        "NIK: 0000000000000001",
        "Tanggal Lahir: 21-05-2006",
        "Alamat: JALAN CONTOH NOMOR 1",
        "BUKAN DOKUMEN IDENTITAS RESMI",
    ]
    img = Image.new("RGB", (1400, 600), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((50, 45 + i * 82), line, fill="black", font=font)
    img.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not (root / "app/main.py").is_file():
        raise SystemExit("Letakkan smoke_ocr.py dalam folder scripts pada proyek.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = root / "var" / "smoke_ocr" / run_id
    output.mkdir(parents=True)
    fixture = output / "dummy.png"
    create_fixture(fixture)
    print(f"Gambar dummy: {fixture}", flush=True)
    if args.fixture_only:
        print("Hanya fixture dibuat; OCR belum dijalankan.")
        return

    report = {
        "mode": "LIVE_OCR_SYNTHETIC_INPUT",
        "status": "RUNNING",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scope": "OCR saja; bukan uji LLM, field extraction, atau kelayakan",
    }
    settings = {
        "device": "cpu",
        "lang": "en",
        "ocr_version": "PP-OCRv5",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    report["settings"] = settings
    try:
        for package in ("paddlepaddle", "paddleocr", "paddlex", "numpy"):
            report[package] = version(package)
        from paddleocr import PaddleOCR

        print("Memuat model CPU. Pemakaian pertama dapat mengunduh model.", flush=True)
        start = time.perf_counter()
        ocr = PaddleOCR(**settings)
        report["initialization_seconds"] = round(time.perf_counter() - start, 3)
        start = time.perf_counter()
        results = list(ocr.predict(str(fixture)))
        report["inference_seconds"] = round(time.perf_counter() - start, 3)
        texts = []
        for i, result in enumerate(results):
            result.save_to_json(str(output / f"ocr_{i}.json"))
            texts.extend(str(text) for text in result["rec_texts"])
        (output / "recognized_text.txt").write_text("\n".join(texts), encoding="utf-8")
        report["recognized_lines"] = len(texts)
        if not texts:
            raise RuntimeError("OCR selesai tetapi tidak menghasilkan teks.")
        report["status"] = "COMPLETED_REQUIRES_INSPECTION"
        print("\nTEKS HASIL OCR:", flush=True)
        for text in texts:
            print(text)
        print("\nBandingkan teks dengan dummy.png; ini belum membuktikan akurasi field.")
    except Exception as exc:
        report["status"] = "FAILED"
        report["error_type"] = type(exc).__name__
        report["error_message"] = str(exc)
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nOutput tersimpan: {output}", flush=True)


if __name__ == "__main__":
    main()
