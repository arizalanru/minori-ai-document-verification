"""Kontrak enam dokumen dan review; adapter SIMULATED, bukan akurasi OCR/LLM."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from generate_six_document_fixtures import fixture, VALUES, missing
from app.domain.document_contracts import SCHEMAS, validate_document
from app.core.errors import DomainError
from app.services.backend import Backend
from test_backend_core import Settings, image_bytes


class SixDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = Backend(Settings(self.tmp.name), ROOT)
        self.backend.initialize()
        self.aid = self.backend.create("demo-full-v1")["application_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def rev(self):
        return self.backend.get(self.aid)["revision"]

    def process(self, kind, transform=None):
        fields, blocks = fixture(kind)
        if transform:
            transform(fields)
        class OCR:
            def extract(self, path): return copy.deepcopy(blocks)
        class LLM:
            def extract(self, document_type, text): return copy.deepcopy(fields)
        self.backend.ocr_factory = OCR
        self.backend.llm_factory = LLM
        version = self.backend.upload(self.aid, kind, image_bytes(), self.rev())["version_id"]
        result = self.backend.process(version, self.rev())
        return version, result

    def verify(self, version, corrections=None):
        return self.backend.review(self.aid, version, "verify", corrections or {}, "Dicocokkan dengan gambar sintetis", self.rev())

    def test_each_document_schema_and_evidence(self):
        for kind in VALUES:
            with self.subTest(kind=kind):
                fields, blocks = fixture(kind)
                parsed = SCHEMAS[kind].model_validate(fields).model_dump()
                validate_document(parsed, blocks, kind)

    def test_each_document_uses_pipeline_and_needs_review(self):
        for kind in VALUES:
            with self.subTest(kind=kind):
                version, result = self.process(kind)
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(self.backend.extraction(version)["review_status"], "needs_review")
        self.assertEqual(self.backend.get(self.aid)["outcome"], "REVIEW")

    def test_full_flow_requires_explicit_kk_selection(self):
        for kind in VALUES:
            version, result = self.process(kind)
            self.assertEqual(result["status"], "SUCCEEDED")
            if kind == "KK":
                with self.assertRaises(DomainError) as exc:
                    self.verify(version)
                self.assertEqual(exc.exception.code, "KK_SELECTION_REQUIRED")
                data = self.backend.get(self.aid)["documents"]["KK"]
                self.assertEqual(len(data["members"]), 2)
                member = data["members"][1]
                self.verify(version, {k: v["value"] for k, v in member.items()})
            else:
                self.verify(version)
        self.assertEqual(self.backend.get(self.aid)["outcome"], "ELIGIBLE")

    def test_kk_cannot_auto_select_head(self):
        _, result = self.process("KK", lambda f: f.update(nama=copy.deepcopy(f["anggota"][0]["nama"])))
        self.assertEqual(result["error_code"], "OUTPUT_INVALID")

    def test_kk_member_evidence_checked(self):
        def invalid(fields): fields["anggota"][1]["nik"]["evidence_ids"] = ["invented"]
        _, result = self.process("KK", invalid)
        self.assertEqual(result["error_code"], "OUTPUT_INVALID")

    def test_mcu_missing_conclusion_cannot_verify(self):
        version, result = self.process("MCU", lambda f: f.update(kesimpulan_dokter=missing()))
        self.assertEqual(result["status"], "SUCCEEDED")
        with self.assertRaises(DomainError) as exc: self.verify(version)
        self.assertEqual(exc.exception.code, "MISSING_FIELDS")

    def test_mcu_invented_conclusion_rejected(self):
        def invalid(fields): fields["kesimpulan_dokter"]["value"] = "FIT TO WORK"
        _, result = self.process("MCU", invalid)
        self.assertEqual(result["error_code"], "OUTPUT_INVALID")

    def test_additional_dates_validate_source(self):
        for kind, key in [("SKCK", "tanggal_terbit"), ("SKCK", "tanggal_berakhir"), ("MCU", "tanggal_pemeriksaan")]:
            with self.subTest(kind=kind, key=key):
                _, result = self.process(kind, lambda f: f[key].update(value="2026-02-30"))
                self.assertEqual(result["error_code"], "OUTPUT_INVALID")

    def test_required_fields_for_all_extra_types(self):
        for kind, key in [("TRANSKRIP", "institusi"), ("SKCK", "nomor_dokumen"), ("MCU", "tanggal_pemeriksaan")]:
            with self.subTest(kind=kind):
                version, result = self.process(kind, lambda f: f.update({key: missing()}))
                self.assertEqual(result["status"], "SUCCEEDED")
                with self.assertRaises(DomainError): self.verify(version)

    def test_wrong_member_conflicts_with_ktp(self):
        for kind in ("KTP", "IJAZAH", "KK"):
            version, _ = self.process(kind)
            if kind == "KK":
                member = self.backend.get(self.aid)["documents"]["KK"]["members"][0]
                self.verify(version, {k: v["value"] for k, v in member.items()})
            else:
                self.verify(version)
        rules = {r["rule_code"]: r["result"] for r in self.backend.get(self.aid)["evaluation"]["results"]}
        self.assertEqual(rules["NIK_CONSISTENCY"], "UNKNOWN")
        self.assertEqual(rules["IDENTITY_CONSISTENCY"], "UNKNOWN")
        self.assertEqual(rules["AGE_RANGE"], "UNKNOWN")

    def test_invalid_date_correction_rejected(self):
        version, _ = self.process("SKCK")
        with self.assertRaises(DomainError) as exc:
            self.verify(version, {"tanggal_terbit": "2026-02-30"})
        self.assertEqual(exc.exception.code, "INVALID_CORRECTION")

    def test_extra_doc_reupload_invalidates_verification(self):
        version, _ = self.process("MCU")
        self.verify(version)
        self.backend.review(self.aid, version, "request_reupload", {}, "Gambar kurang jelas", self.rev())
        self.assertEqual(self.backend.get(self.aid)["documents"]["MCU"]["review_status"], "needs_review")
        self.assertEqual(self.backend.get(self.aid)["outcome"], "REVIEW")

    def test_skck_expiry_is_optional_not_inferred(self):
        version, result = self.process("SKCK", lambda f: f.update(tanggal_berakhir=missing()))
        self.assertEqual(result["status"], "SUCCEEDED")
        self.verify(version)
        self.assertIsNone(self.backend.get(self.aid)["documents"]["SKCK"]["fields"]["tanggal_berakhir"]["value"])
