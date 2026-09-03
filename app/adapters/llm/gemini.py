import hashlib
import json
import logging

from app.core.config import PROJECT_ROOT
from app.core.errors import DomainError
from app.domain.document_contracts import SCHEMAS, validate_document


logger = logging.getLogger(__name__)

_SCHEMA_ERROR_MARKERS = (
    "additional_properties",
    "additionalproperties",
    "invalid json payload",
    "response schema",
    "response_schema",
    "responseschema",
)


def schema_for_provider(value):
    """Return an API-compatible copy without weakening the source models."""
    if isinstance(value, dict):
        return {
            name: schema_for_provider(item)
            for name, item in value.items()
            if name not in ("additionalProperties", "additional_properties")
        }
    if isinstance(value, list):
        return [schema_for_provider(item) for item in value]
    return value


def provider_schema_for_document(document_type, internal_schema=None):
    """Build the provider-only schema for one document type."""
    source = internal_schema or SCHEMAS[document_type].model_json_schema()
    provider_schema = schema_for_provider(source)
    if document_type == "KK":
        provider_schema["properties"]["anggota"].pop("maxItems", None)
    return provider_schema


def build_generation_config(system_instruction, provider_schema=None):
    """Build the one configuration path shared by runtime and diagnostics."""
    from google.genai import types

    values = {
        "system_instruction": system_instruction,
        "temperature": 0,
        "automatic_function_calling": {"disable": True},
    }
    if provider_schema is not None:
        values.update(
            response_mime_type="application/json",
            response_json_schema=provider_schema,
        )
    return types.GenerateContentConfig(**values)


def build_http_options(timeout_seconds):
    from google.genai import types

    return types.HttpOptions(
        timeout=timeout_seconds * 1000,
        retry_options=types.HttpRetryOptions(attempts=1),
    )


def _provider_error_code(exc):
    status = getattr(exc, "code", None)
    type_name = type(exc).__name__.lower()
    module_name = type(exc).__module__.lower()
    message = str(getattr(exc, "message", exc)).lower()

    if "timeout" in type_name or "timeout" in module_name:
        return "LLM_TIMEOUT"
    if status == 400:
        if any(marker in message for marker in _SCHEMA_ERROR_MARKERS):
            return "LLM_SCHEMA_ERROR"
        return "PROVIDER_BAD_REQUEST"
    if isinstance(exc, (TypeError, ValueError)):
        return "LLM_SCHEMA_ERROR"
    if (
        "connection" in type_name
        or "network" in type_name
        or module_name.startswith(("httpx", "httpcore"))
    ):
        return "LLM_NETWORK_ERROR"
    return {
        429: "PROVIDER_RATE_LIMIT",
        503: "PROVIDER_BUSY",
        504: "LLM_TIMEOUT",
        404: "MODEL_UNAVAILABLE",
        401: "LLM_ACCESS_DENIED",
        403: "LLM_ACCESS_DENIED",
    }.get(status, "LLM_ERROR")


class GeminiAdapter:
    def __init__(self, settings):
        self.settings = settings
        self.metadata = {}

    def extract(self, document_type, blocks):
        key = self.settings.gemini_api_key.get_secret_value()
        if not key:
            raise DomainError(
                "LLM_KEY_MISSING", "Isi GEMINI_API_KEY di .env", 503
            )

        from google import genai

        prompt = (PROJECT_ROOT / "prompts/extraction.backend.v2.txt").read_text(
            encoding="utf-8"
        )
        result_schema = SCHEMAS[document_type]
        internal_schema = result_schema.model_json_schema()
        provider_schema = provider_schema_for_document(
            document_type, internal_schema
        )
        config = build_generation_config(prompt, provider_schema)

        try:
            http_options = build_http_options(self.settings.llm_timeout_seconds)
            with genai.Client(api_key=key, http_options=http_options) as client:
                response = client.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=json.dumps(
                        {
                            "document_type": document_type,
                            "blocks": [
                                {
                                    name: block[name]
                                    for name in ("block_id", "page_number", "text")
                                }
                                for block in blocks
                            ],
                        }
                    ),
                    config=config,
                )
        except Exception as exc:
            code = _provider_error_code(exc)
            logger.warning(
                "Gemini request failed (type=%s, status=%s, category=%s)",
                type(exc).__name__,
                getattr(exc, "code", None),
                code,
            )
            raise DomainError(
                code,
                "Layanan pembacaan dokumen gagal; tidak ada keputusan kelayakan",
                503,
            ) from None

        self.metadata = {
            "requested_model": self.settings.gemini_model,
            "model_version": getattr(response, "model_version", None),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "schema_sha256": hashlib.sha256(
                json.dumps(internal_schema, sort_keys=True).encode()
            ).hexdigest(),
            "usage": response.usage_metadata.model_dump(mode="json")
            if response.usage_metadata
            else None,
        }
        try:
            data = result_schema.model_validate_json(response.text or "").model_dump()
        except Exception:
            raise DomainError(
                "OUTPUT_INVALID", "Respons tidak sesuai skema"
            ) from None
        validate_document(data, blocks, document_type)
        if document_type == "KTP":
            data["nomor_dokumen"] = dict(data["nik"])
        return data
