"""Uji satu request Gemini pada output OCR sintetis tanpa membuat keputusan."""
from pathlib import Path
from datetime import datetime, timezone, date
from importlib.metadata import version
import argparse
import hashlib
import json
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def validate_evidence(data, blocks):
    source = {b["block_id"]: b["text"] for b in blocks}
    for name, field in data.items():
        ids = field["evidence_ids"]
        if len(ids) != len(set(ids)) or any(i not in source for i in ids):
            raise ValueError(f"{name}: referensi bukti tidak valid")
        raw = field["raw_text"]
        if raw is not None and not any(raw in source[i] for i in ids):
            raise ValueError(f"{name}: kutipan tidak cocok dengan bukti")
        if field["status"] == "extracted":
            if not field["value"] or not raw or not ids or field["reason_code"] != "NONE":
                raise ValueError(f"{name}: extracted memerlukan nilai dan bukti")
            value = field["value"]
            if name == "tanggal_lahir":
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("Tanggal bukan ISO")
                date.fromisoformat(value)
                original = datetime.strptime(raw, "%d-%m-%Y").date()
                if original.isoformat() != value:
                    raise ValueError("Tanggal berubah dibanding teks sumber")
            elif " ".join(value.split()) != " ".join(raw.split()):
                raise ValueError(f"{name}: nilai berubah dibanding kutipan")
            if name == "nik" and not re.fullmatch(r"[0-9]{16}", value):
                raise ValueError("NIK bukan 16 digit")
        elif field["value"] is not None:
            raise ValueError(f"{name}: field tidak pasti harus null")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr", required=True, help="Path ocr_0.json hasil dummy")
    args = parser.parse_args()
    if not (ROOT / "app/main.py").exists():
        raise SystemExit("Simpan script dalam folder scripts proyek.")
    from app.core.config import Settings
    from app.domain.schemas import ExtractionResult
    from google import genai
    from google.genai import types

    settings = Settings()
    key = settings.gemini_api_key.get_secret_value().strip()
    if not key:
        raise SystemExit("GEMINI_API_KEY kosong. Isi .env lokal tanpa mengirim key ke chat.")
    input_path = Path(args.ocr)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    original = json.loads(input_path.read_text(encoding="utf-8"))
    original = original.get("res", original)
    texts = original.get("rec_texts", [])
    if not texts or not all(isinstance(t, str) for t in texts):
        raise SystemExit("Input tidak memiliki rec_texts yang valid.")
    if "DOKUMEN SINTETIS - DEMO OCR" not in texts:
        raise SystemExit("Script ini khusus output gambar dummy smoke_ocr.py.")
    blocks = [{"block_id": f"b{i+1}", "page_number": 1, "text": t}
              for i, t in enumerate(texts)]
    prompt = (ROOT / "prompts/extraction.v1.txt").read_text(encoding="utf-8")
    prompt += """
Untuk fixture ini: pendidikan_terakhir tidak relevan; gunakan null,
not_applicable, NOT_EXPECTED, raw_text null, evidence_ids [].
nomor_dokumen mengikuti NIK yang tertulis, dengan bukti sama.
Kutip raw_text hanya bagian nilai, tanpa label seperti Nama: atau NIK:.
Setiap kutipan harus substring persis dari satu blok sumber.
Tanggal eksplisit DD-MM-YYYY boleh diubah menjadi YYYY-MM-DD.
extracted memakai reason_code NONE. Jangan menghasilkan keputusan.
"""
    output = ROOT / "var/smoke_llm" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True)
    report = {"status": "STARTED", "mode": "LIVE_LLM_SYNTHETIC_OCR",
              "requested_model": settings.gemini_model, "sdk_version": version("google-genai"),
              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "schema_sha256": hashlib.sha256(json.dumps(ExtractionResult.model_json_schema(), sort_keys=True).encode()).hexdigest()}
    (output / "input_blocks.json").write_text(json.dumps(blocks, indent=2), encoding="utf-8")
    try:
        schema = ExtractionResult.model_json_schema()
        config = {
            "system_instruction": prompt,
            "temperature": 0,
            "automatic_function_calling": {"disable": True},
        }
        # SDK lama/baru memakai nama konfigurasi structured output berbeda.
        if "response_json_schema" in types.GenerateContentConfig.model_fields:
            config.update(response_mime_type="application/json", response_json_schema=schema)
        else:
            config["response_format"] = {"text": {"mime_type": "application/json", "schema": schema}}
        print("Memanggil Gemini satu kali dengan teks OCR sintetis...", flush=True)
        start = time.perf_counter()
        with genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000)) as client:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=json.dumps({"document_type": "KTP_DEMO", "blocks": blocks}),
                config=types.GenerateContentConfig(**config),
            )
        report["request_seconds"] = round(time.perf_counter() - start, 3)
        report["model_version"] = getattr(response, "model_version", None)
        if response.usage_metadata:
            report["usage"] = response.usage_metadata.model_dump(mode="json")
        raw = response.text
        if not raw:
            raise ValueError("Model tidak mengembalikan teks JSON")
        (output / "response_raw.txt").write_text(raw, encoding="utf-8")
        data = ExtractionResult.model_validate_json(raw).model_dump()
        validate_evidence(data, blocks)
        (output / "extraction.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        report["status"] = "SCHEMA_AND_BASIC_EVIDENCE_VALID"
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print("\nSkema dan bukti dasar valid. Periksa kelengkapan nilai secara manual.")
        print("Belum ada keputusan administrasi atau metrik akurasi sistem.")
    except Exception as exc:
        report["status"] = "FAILED"
        report["error_type"] = type(exc).__name__
        # Jangan mencetak exception provider mentah: bisa memuat URL/kredensial.
        code = getattr(exc, "code", None)
        message = str(getattr(exc, "message", "")).replace(key, "[REDACTED]")
        report["provider_message"] = message
        print("Pesan dari Gemini:", message)
        report["http_code"] = code if isinstance(code, (int, str)) else None
        if isinstance(exc, ValueError) and type(exc).__name__ != "ValidationError":
            report["validation_error"] = str(exc).replace(key, "[REDACTED]")
        print(f"Gagal: {report['error_type']}, HTTP={report.get('http_code')}")
        if "validation_error" in report:
            print(report["validation_error"])
        print("401/403: akses key; 404: model; 429: kuota/rate limit. Jangan ulangi terus-menerus.")
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Hasil: {output}")
    return 0 if report["status"] == "SCHEMA_AND_BASIC_EVIDENCE_VALID" else 1


if __name__ == "__main__":
    sys.exit(main())
