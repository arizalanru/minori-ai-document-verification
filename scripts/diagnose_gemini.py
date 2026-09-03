"""One-case Gemini transport diagnostic; dry-run unless --live is explicit."""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.adapters.llm.gemini import (
    build_generation_config,
    build_http_options,
    provider_schema_for_document,
    schema_for_provider,
)
from app.core.config import PROJECT_ROOT, Settings
from app.domain.document_contracts import SCHEMAS


CASES = (
    "basic",
    "config",
    "simple-schema",
    "ktp-schema",
    "kk-schema",
    "kk-no-maxitems",
)
SYNTHETIC_CONTENT = (
    "DIAGNOSTIK SINTETIS. Tidak ada data peserta. "
    "Berikan jawaban singkat sesuai format yang diminta."
)
SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


class TransportCaptured(Exception):
    pass


def case_config(case, prompt):
    if case == "basic":
        return None
    if case == "config":
        return build_generation_config(prompt)
    if case == "simple-schema":
        return build_generation_config(prompt, SIMPLE_SCHEMA)
    kind = "KTP" if case == "ktp-schema" else "KK"
    if case == "kk-no-maxitems":
        schema = provider_schema_for_document("KK")
    else:
        schema = schema_for_provider(SCHEMAS[kind].model_json_schema())
    return build_generation_config(prompt, schema)


def case_difference(case):
    return {
        "basic": "baseline: teks sintetis tanpa GenerateContentConfig",
        "config": "dibanding basic: menambah parameter non-schema adapter",
        "simple-schema": "dibanding config: hanya menambah schema satu string",
        "ktp-schema": "dibanding simple-schema: hanya mengganti schema menjadi KTP",
        "kk-schema": "dibanding ktp-schema: hanya mengganti schema menjadi KK",
        "kk-no-maxitems": (
            "dibanding kk-schema: hanya menghapus properties.anggota.maxItems "
            "pada salinan schema provider"
        ),
    }[case]


def walk_keys(value, keys, types):
    if isinstance(value, dict):
        keys.update(value.keys())
        schema_type = value.get("type")
        if isinstance(schema_type, str):
            types[schema_type] += 1
        for child in value.values():
            walk_keys(child, keys, types)
    elif isinstance(value, list):
        for child in value:
            walk_keys(child, keys, types)


def depth(value):
    if isinstance(value, dict):
        return 1 + max((depth(child) for child in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((depth(child) for child in value), default=0)
    return 0


def capture_request(settings, config):
    from google import genai

    captured = {}
    client = genai.Client(
        api_key="offline-placeholder",
        http_options=build_http_options(settings.llm_timeout_seconds),
    )

    def capture(method, path, request_dict, http_options=None):
        captured.update(
            method=method,
            path=path,
            request_dict=request_dict,
            http_options=http_options,
        )
        raise TransportCaptured()

    client._api_client.request = capture
    try:
        client.models.generate_content(
            model=settings.gemini_model,
            contents=SYNTHETIC_CONTENT,
            config=config,
        )
    except TransportCaptured:
        return captured
    finally:
        client.close()
    raise RuntimeError("Transport SDK tidak berhasil ditangkap")


def print_dry_run(case, captured):
    payload = captured["request_dict"]
    generation = payload.get("generationConfig", {})
    schema_name = next(
        (name for name in ("responseJsonSchema", "responseSchema") if name in generation),
        None,
    )
    schema = generation.get(schema_name, {}) if schema_name else {}
    keys = Counter()
    types = Counter()
    walk_keys(schema, keys, types)

    print("Mode: OFFLINE DRY-RUN (tidak ada koneksi API)")
    print(f"Kasus: {case}")
    print(f"Perubahan: {case_difference(case)}")
    print(f"Model: {settings_model_label(payload, captured)}")
    print(f"Metode/path SDK: {captured['method'].upper()} {captured['path']}")
    print(f"Top-level payload keys: {sorted(payload)}")
    print(f"generationConfig keys: {sorted(generation)}")
    if case == "basic":
        print("automatic_function_calling: tidak dikonfigurasi")
    else:
        print("automatic_function_calling.disable: true (kontrol SDK; tidak masuk wire body)")
    if not schema_name:
        print("Structured schema: tidak dikirim")
        return
    print(f"Structured schema field: {schema_name}")
    print(f"Schema JSON bytes: {len(json.dumps(schema, separators=(',', ':')))}")
    print(f"Schema maximum nesting depth: {depth(schema)}")
    print(f"Schema type counts: {dict(sorted(types.items()))}")
    for name in (
        "additional_properties",
        "additionalProperties",
        "$defs",
        "$ref",
        "anyOf",
        "nullable",
        "maxItems",
        "max_items",
        "propertyOrdering",
        "property_ordering",
    ):
        print(f"Schema key {name}: {keys[name]}")


def settings_model_label(payload, captured):
    path_model = captured["path"].split(":", 1)[0]
    return path_model.removeprefix("models/") or "(tidak ditemukan)"


def redact(text, api_key):
    safe = str(text or "")
    if api_key:
        safe = safe.replace(api_key, "[REDACTED]")
    safe = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [REDACTED]", safe)
    safe = re.sub(
        r"(?i)(?:key|api[_-]?key)=([^\s&]+)",
        "api_key=[REDACTED]",
        safe,
    )
    return safe[:2000]


def run_live(settings, case, config):
    from google import genai

    key = settings.gemini_api_key.get_secret_value()
    if not key:
        print("Gagal: GEMINI_API_KEY belum tersedia melalui Settings.")
        return 2
    try:
        with genai.Client(
            api_key=key,
            http_options=build_http_options(settings.llm_timeout_seconds),
        ) as client:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=SYNTHETIC_CONTENT,
                config=config,
            )
    except Exception as exc:
        print("Mode: LIVE (satu request, tanpa retry/fallback)")
        print(f"Kasus: {case}")
        print(f"HTTP status: {getattr(exc, 'code', None) or 'tidak tersedia'}")
        print(f"Provider status: {redact(getattr(exc, 'status', None), key) or 'tidak tersedia'}")
        message = redact(getattr(exc, "message", None), key)
        print(f"Pesan: {message or 'provider tidak memberi pesan rinci'}")
        if not message or message.strip().lower() == "request contains an invalid argument.":
            print("Keterangan: pesan provider tetap generik; penyebab belum dapat ditentukan.")
        details = redact(getattr(exc, "details", None), key)
        if details and details != message:
            print(f"Detail (maks. 2000 karakter): {details}")
        return 1

    print("Mode: LIVE (satu request, tanpa retry/fallback)")
    print(f"Kasus: {case}")
    print("HTTP status: 200 (request berhasil)")
    print(f"Model version: {getattr(response, 'model_version', None) or 'tidak tersedia'}")
    print(f"Respons sintetis (maks. 500 karakter): {(response.text or '')[:500]}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=CASES, help="tepat satu kasus diagnosis")
    parser.add_argument(
        "--live",
        action="store_true",
        help="izinkan tepat satu panggilan Gemini live",
    )
    args = parser.parse_args()

    settings = Settings()
    prompt = (PROJECT_ROOT / "prompts/extraction.backend.v2.txt").read_text(
        encoding="utf-8"
    )
    config = case_config(args.case, prompt)
    if args.live:
        return run_live(settings, args.case, config)
    captured = capture_request(settings, config)
    print_dry_run(args.case, captured)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
