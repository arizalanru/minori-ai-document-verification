"""Offline regression tests at the Gemini provider boundary."""
import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from generate_six_document_fixtures import VALUES, fixture
from app.adapters.llm.gemini import (
    GeminiAdapter,
    build_generation_config,
    provider_schema_for_document,
    schema_for_provider,
)
from app.core.errors import DomainError
from app.domain.document_contracts import SCHEMAS


class Secret:
    def get_secret_value(self):
        return "test-key-never-sent"


class Settings:
    gemini_api_key = Secret()
    gemini_model = "TEST-NO-MODEL"
    llm_timeout_seconds = 5


class Response:
    model_version = "test-model-version"
    usage_metadata = None

    def __init__(self, data):
        self.text = json.dumps(data)


class Models:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class Client:
    def __init__(self, models):
        self.models = models

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GeminiAdapterTests(unittest.TestCase):
    def test_provider_schema_conversion_for_all_document_types(self):
        for kind in VALUES:
            with self.subTest(kind=kind):
                source = SCHEMAS[kind].model_json_schema()
                before = copy.deepcopy(source)
                converted = schema_for_provider(source)
                self.assertEqual(source, before)
                self.assertNotIn("additionalProperties", json.dumps(converted))
                self.assertIn("additionalProperties", json.dumps(source))
                self.assertIn("$defs", converted)

    def test_nested_kk_objects_and_array_items_are_sanitized(self):
        converted = schema_for_provider(SCHEMAS["KK"].model_json_schema())
        member_ref = converted["properties"]["anggota"]["items"]["$ref"]
        self.assertEqual(member_ref, "#/$defs/FamilyMember")
        self.assertNotIn(
            "additionalProperties", converted["$defs"]["FamilyMember"]
        )
        self.assertNotIn(
            "additionalProperties", converted["$defs"]["ExtractedField"]
        )

    def test_installed_sdk_transport_serializes_json_schema_keywords(self):
        from diagnose_gemini import capture_request

        prompt = "Instruksi sintetis"
        for kind in ("KTP", "KK"):
            with self.subTest(kind=kind):
                converted = schema_for_provider(SCHEMAS[kind].model_json_schema())
                config = build_generation_config(prompt, converted)
                captured = capture_request(Settings(), config)
                generation = captured["request_dict"]["generationConfig"]
                schema = generation["responseJsonSchema"]
                serialized_text = json.dumps(schema)
                self.assertNotIn("responseSchema", generation)
                self.assertNotIn("additionalProperties", serialized_text)
                self.assertNotIn("additional_properties", serialized_text)
                self.assertNotIn("max_items", serialized_text)
                self.assertNotIn("property_ordering", serialized_text)
                self.assertIn("$defs", schema)
                self.assertIn("$ref", serialized_text)
                self.assertIn("anyOf", serialized_text)
                self.assertIn('"type": "null"', serialized_text)
                if kind == "KK":
                    self.assertIn("maxItems", serialized_text)

    def test_kk_no_maxitems_changes_only_target_on_a_copy(self):
        source = schema_for_provider(SCHEMAS["KK"].model_json_schema())
        source_before = copy.deepcopy(source)
        variant = provider_schema_for_document("KK", source)
        expected = copy.deepcopy(source)
        del expected["properties"]["anggota"]["maxItems"]

        self.assertEqual(source, source_before)
        self.assertEqual(source["properties"]["anggota"]["maxItems"], 30)
        self.assertEqual(variant, expected)

    def test_kk_no_maxitems_transport_differs_only_at_target(self):
        from diagnose_gemini import capture_request, case_config

        prompt = "Instruksi sintetis identik"
        baseline = capture_request(Settings(), case_config("kk-schema", prompt))
        variant = capture_request(
            Settings(), case_config("kk-no-maxitems", prompt)
        )
        baseline_payload = copy.deepcopy(baseline["request_dict"])
        variant_payload = variant["request_dict"]
        baseline_schema = baseline_payload["generationConfig"][
            "responseJsonSchema"
        ]
        variant_schema = variant_payload["generationConfig"][
            "responseJsonSchema"
        ]

        self.assertEqual(
            baseline_schema["properties"]["anggota"]["maxItems"], 30
        )
        del baseline_schema["properties"]["anggota"]["maxItems"]
        self.assertNotIn("maxItems", variant_schema["properties"]["anggota"])
        self.assertEqual(baseline_payload, variant_payload)

    def test_other_document_provider_schemas_are_unchanged(self):
        for kind in ("KTP", "IJAZAH", "TRANSKRIP", "SKCK", "MCU"):
            with self.subTest(kind=kind):
                source = SCHEMAS[kind].model_json_schema()
                self.assertEqual(
                    provider_schema_for_document(kind),
                    schema_for_provider(source),
                )

    def test_real_adapter_kk_transport_omits_provider_maxitems(self):
        from google import genai

        fields, blocks = fixture("KK")
        captured = {}
        real_client = genai.Client

        def client_factory(**kwargs):
            client = real_client(**kwargs)

            def request(method, path, request_dict, http_options=None):
                captured.update(
                    method=method,
                    path=path,
                    request_dict=copy.deepcopy(request_dict),
                )
                body = {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": json.dumps(fields)}],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "modelVersion": "test-model-version",
                }
                return SimpleNamespace(body=json.dumps(body), headers={})

            client._api_client.request = request
            return client

        with patch("google.genai.Client", side_effect=client_factory):
            result = GeminiAdapter(Settings()).extract("KK", blocks)

        runtime_schema = captured["request_dict"]["generationConfig"][
            "responseJsonSchema"
        ]
        self.assertNotIn(
            "maxItems", runtime_schema["properties"]["anggota"]
        )
        self.assertEqual(
            SCHEMAS["KK"].model_json_schema()["properties"]["anggota"][
                "maxItems"
            ],
            30,
        )
        self.assertEqual(len(result["anggota"]), 2)

    def test_kk_internal_member_limit_remains_enforced(self):
        fields, _ = fixture("KK")
        member = fields["anggota"][0]
        fields["anggota"] = [copy.deepcopy(member) for _ in range(31)]
        with self.assertRaises(ValidationError):
            SCHEMAS["KK"].model_validate(fields)

    def test_config_is_forwarded_and_valid_response_is_accepted(self):
        fields, blocks = fixture("KTP")
        models = Models(Response(fields))
        with patch("google.genai.Client", return_value=Client(models)):
            result = GeminiAdapter(Settings()).extract("KTP", blocks)

        self.assertEqual(result["nama"]["value"], VALUES["KTP"]["nama"])
        self.assertEqual(len(models.calls), 1)
        call = models.calls[0]
        self.assertEqual(call["model"], Settings.gemini_model)
        self.assertEqual(call["config"].response_mime_type, "application/json")
        self.assertIsNotNone(call["config"].response_json_schema)
        self.assertIsNone(call["config"].response_schema)
        dumped = call["config"].model_dump(mode="json", by_alias=True)
        self.assertNotIn(
            "additionalProperties", json.dumps(dumped["responseJsonSchema"])
        )

    def test_extra_response_field_remains_rejected_locally(self):
        fields, _ = fixture("KTP")
        fields["unexpected"] = "must fail"
        with self.assertRaises(ValidationError):
            SCHEMAS["KTP"].model_validate(fields)

    def test_fake_evidence_is_rejected_by_real_adapter_validation(self):
        fields, blocks = fixture("KTP")
        fields["nama"]["evidence_ids"] = ["invented"]
        models = Models(Response(fields))
        with patch("google.genai.Client", return_value=Client(models)):
            with self.assertRaises(DomainError) as caught:
                GeminiAdapter(Settings()).extract("KTP", blocks)
        self.assertEqual(caught.exception.code, "OUTPUT_INVALID")

    def test_http_400_schema_error_is_mapped_precisely(self):
        class BadRequest(Exception):
            code = 400
            message = (
                'Invalid JSON payload. Unknown name "additional_properties" '
                "at generation_config.response_schema"
            )

        _, blocks = fixture("KK")
        models = Models(error=BadRequest())
        with patch("google.genai.Client", return_value=Client(models)):
            with self.assertLogs(
                "app.adapters.llm.gemini", level="WARNING"
            ) as logs, self.assertRaises(DomainError) as caught:
                GeminiAdapter(Settings()).extract("KK", blocks)
        self.assertEqual(caught.exception.code, "LLM_SCHEMA_ERROR")
        self.assertNotIn("additional_properties", " ".join(logs.output))
        self.assertNotIn("test-key-never-sent", " ".join(logs.output))

    def test_non_schema_http_400_is_not_classified_as_network_error(self):
        class BadRequest(Exception):
            code = 400
            message = "Request contains an invalid argument."

        _, blocks = fixture("KTP")
        models = Models(error=BadRequest())
        with patch("google.genai.Client", return_value=Client(models)):
            with self.assertRaises(DomainError) as caught:
                GeminiAdapter(Settings()).extract("KTP", blocks)
        self.assertEqual(caught.exception.code, "PROVIDER_BAD_REQUEST")


if __name__ == "__main__":
    unittest.main()
