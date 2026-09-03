import hashlib
import json

from app.core.config import PROJECT_ROOT
from app.domain.evidence import validate_extraction
from app.domain.schemas import ExtractionResult
from app.core.errors import DomainError


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
        from google.genai import types

        prompt = (PROJECT_ROOT / "prompts/extraction.backend.v1.txt").read_text(
            encoding="utf-8"
        )
        schema = ExtractionResult.model_json_schema()
        config = {
            "system_instruction": prompt,
            "temperature": 0,
            "automatic_function_calling": {"disable": True},
        }
        if "response_json_schema" in types.GenerateContentConfig.model_fields:
            config.update(
                response_mime_type="application/json",
                response_json_schema=schema,
            )
        else:
            config["response_format"] = {
                "text": {"mime_type": "application/json", "schema": schema}
            }

        try:
            http_options = types.HttpOptions(
                timeout=self.settings.llm_timeout_seconds * 1000,
                retry_options=types.HttpRetryOptions(attempts=1),
            )
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
                    config=types.GenerateContentConfig(**config),
                )
        except Exception as exc:
            code = {
                429: "PROVIDER_RATE_LIMIT",
                503: "PROVIDER_BUSY",
                504: "LLM_TIMEOUT",
                404: "MODEL_UNAVAILABLE",
                401: "LLM_ACCESS_DENIED",
                403: "LLM_ACCESS_DENIED",
            }.get(getattr(exc, "code", None), "LLM_ERROR")
            if "timeout" in type(exc).__name__.lower():
                code = "LLM_TIMEOUT"
            raise DomainError(
                code,
                "Layanan LLM gagal; tidak ada keputusan kelayakan",
                503,
            ) from None

        self.metadata = {
            "requested_model": self.settings.gemini_model,
            "model_version": getattr(response, "model_version", None),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "schema_sha256": hashlib.sha256(
                json.dumps(schema, sort_keys=True).encode()
            ).hexdigest(),
            "usage": response.usage_metadata.model_dump(mode="json")
            if response.usage_metadata
            else None,
        }
        try:
            data = ExtractionResult.model_validate_json(response.text or "").model_dump()
        except Exception:
            raise DomainError(
                "OUTPUT_INVALID", "Respons tidak sesuai skema"
            ) from None
        validate_extraction(data, blocks)
        if document_type == "KTP":
            data["nomor_dokumen"] = dict(data["nik"])
        return data
