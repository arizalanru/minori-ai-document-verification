import hashlib
import json
import logging
import uuid
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from app.core.errors import DomainError
from app.db.repository import Database
from app.domain.rules import aggregate, evaluate_rules
from app.domain.document_contracts import SCHEMAS, REQUIRED_FIELDS, EXTRA_FIELDS, DATE_FIELDS, validate_document
from app.storage.files import inspect_image


logger = logging.getLogger(__name__)


DOCUMENT_TYPES = ("KTP", "KK", "IJAZAH", "TRANSKRIP", "SKCK", "MCU")
EXTRACTED_FIELDS = (
    "nama",
    "nik",
    "tanggal_lahir",
    "alamat",
    "pendidikan_terakhir",
    "nomor_dokumen",
) + EXTRA_FIELDS


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def one(connection, sql, arguments=()):
    row = connection.execute(sql, arguments).fetchone()
    if row is None:
        raise DomainError("NOT_FOUND", "Objek tidak ditemukan", 404)
    return row


def check_revision(application, expected_revision):
    if application["revision"] != expected_revision:
        raise DomainError(
            "REVISION_CONFLICT", "Ambil revision terbaru dan ulangi aksi", 409
        )


def invalidate(connection, application_id):
    connection.execute(
        "UPDATE applications SET revision=revision+1, "
        "active_evaluation_id=NULL, confirmed_evaluation_id=NULL WHERE id=?",
        (application_id,),
    )


def cached(connection, scope, key, payload):
    if not key:
        return None
    row = connection.execute(
        "SELECT * FROM request_keys WHERE scope=? AND request_key=?", (scope, key)
    ).fetchone()
    if row:
        if row["payload_hash"] != digest(payload):
            raise DomainError(
                "IDEMPOTENCY_CONFLICT", "Key digunakan untuk payload berbeda", 409
            )
        return json.loads(row["response_json"])


def remember(connection, scope, key, payload, response):
    if key:
        connection.execute(
            "INSERT INTO request_keys VALUES(?,?,?,?)",
            (scope, key, digest(payload), dump(response)),
        )


class Backend:
    def __init__(self, settings, root, ocr_factory=None, llm_factory=None):
        self.settings = settings
        self.root = Path(root)
        self.db = Database(settings.resolve_path(settings.database_path))
        self.files = settings.resolve_path(settings.private_files_dir)
        self.ocr_factory = ocr_factory
        self.llm_factory = llm_factory

    def initialize(self):
        self.db.initialize()
        self.files.mkdir(parents=True, exist_ok=True)

    def profile(self,name):
        if name not in ("demo-core-v1", "demo-full-v1"):
            raise DomainError("INVALID_PROFILE", "Profil demo tidak dikenal")
        profile_path = self.root / "config" / "programs" / f"{name}.json"
        return json.loads(profile_path.read_text())

    def create(self, profile_id, key=None):
        profile = self.profile(profile_id)
        payload = {"profile": profile_id}
        with self.db.transaction() as connection:
            previous_response = cached(connection, "create", key, payload)
            if previous_response:
                return previous_response
            application_id = uid()
            connection.execute(
                "INSERT INTO applications(id,profile_json,created_at) VALUES(?,?,?)",
                (application_id, dump(profile), now()),
            )
            response = {
                "application_id": application_id,
                "revision": 0,
                "rule_version_id": profile_id,
                "outcome": "PENDING",
            }
            remember(connection, "create", key, payload, response)
            return response

    def list(self, limit=20, offset=0):
        with self.db.transaction() as connection:
            rows = connection.execute(
                "SELECT id FROM applications ORDER BY created_at DESC "
                "LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self.get(row["id"], detail=False) for row in rows]
    def snapshot(self, connection, application_id):
        documents = {}
        rows = connection.execute(
            """SELECT d.document_type,v.* FROM documents d JOIN versions v
            ON v.id=d.active_version_id WHERE d.application_id=?""",
            (application_id,),
        ).fetchall()
        for row in rows:
            fields = {}
            blocks = []
            members = []
            if row["active_run_id"]:
                run = one(
                    connection,
                    "SELECT * FROM process_runs WHERE id=?",
                    (row["active_run_id"],),
                )
                fields = json.loads(run["fields_json"] or "{}")
                members = fields.pop("anggota", [])
                blocks = json.loads(run["blocks_json"] or "[]")
                for field in fields.values():
                    field["source_kind"] = "extraction"
                    field["source_id"] = run["id"]
                    field["document_version_id"] = row["id"]
            corrections = json.loads(row["corrections_json"])
            fields.update(corrections)
            documents[row["document_type"]] = {
                "version_id": row["id"],
                "review_status": row["review_status"],
                "fields": fields,
                "blocks": blocks,
                "members": members,
                "version_number": row["number"],
            }
        return {"documents": documents}

    def get(self, application_id, detail=True):
        with self.db.transaction() as connection:
            application = one(
                connection,
                "SELECT * FROM applications WHERE id=?",
                (application_id,),
            )
            snapshot = self.snapshot(connection, application_id)
            profile = json.loads(application["profile_json"])
            evaluation = None
            if application["active_evaluation_id"]:
                row = one(
                    connection,
                    "SELECT * FROM evaluations WHERE id=?",
                    (application["active_evaluation_id"],),
                )
                evaluation = {
                    "evaluation_id": row["id"],
                    "input_revision": row["input_revision"],
                    "outcome": row["outcome"],
                    "results": json.loads(row["results_json"]),
                }
            if (
                evaluation
                and application["confirmed_evaluation_id"]
                == evaluation["evaluation_id"]
            ):
                outcome = "INELIGIBLE"
            else:
                outcome = evaluation["outcome"] if evaluation else "PENDING"
            response = {
                "application_id": application_id,
                "revision": application["revision"],
                "rule_version_id": profile["id"],
                "outcome": outcome,
                "evaluation": evaluation,
                "demo_only": True,
            }
            if detail:
                documents = snapshot["documents"]
                response["documents"] = documents
                response["missing_documents"] = [
                    kind
                    for kind in profile["required_documents"]
                    if kind not in documents
                ]
                response["data"] = {
                    name: documents.get(kind, {})
                    .get("fields", {})
                    .get(name, {})
                    .get("value")
                    for name, kind in [
                        ("nama", "KTP"),
                        ("nik", "KTP"),
                        ("tanggal_lahir", "KTP"),
                        ("alamat", "KTP"),
                        ("pendidikan_terakhir", "IJAZAH"),
                    ]
                }
                response["history"] = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT id,action_type,version_id,reason,resulting_revision,"
                        "created_at FROM reviews WHERE application_id=? ORDER BY rowid",
                        (application_id,),
                    )
                ]
            return response

    def version_row(self, connection, version_id):
        return one(
            connection,
            """SELECT v.*,d.application_id,d.document_type,d.active_version_id
            FROM versions v JOIN documents d ON d.id=v.document_id WHERE v.id=?""",
            (version_id,),
        )
    def upload(self, application_id, document_type, content, expected_revision, key=None):
        if document_type not in DOCUMENT_TYPES:
            raise DomainError(
                "INVALID_DOCUMENT_TYPE", "Jenis dokumen tidak didukung"
            )
        if len(content) > self.settings.max_upload_bytes:
            raise DomainError("FILE_TOO_LARGE", "File lebih dari batas", 413)
        extension = inspect_image(content, self.settings.max_image_pixels)
        content_hash = hashlib.sha256(content).hexdigest()
        payload = {
            "sha": content_hash,
            "kind": document_type,
            "revision": expected_revision,
        }
        scope = "upload:" + application_id
        new_path = None
        try:
            with self.db.transaction() as connection:
                previous_response = cached(connection, scope, key, payload)
                if previous_response:
                    return previous_response
                application = one(
                    connection,
                    "SELECT * FROM applications WHERE id=?",
                    (application_id,),
                )
                check_revision(application, expected_revision)
                document = connection.execute(
                    "SELECT * FROM documents WHERE application_id=? "
                    "AND document_type=?",
                    (application_id, document_type),
                ).fetchone()
                if document and document["active_version_id"]:
                    active_version = one(
                        connection,
                        "SELECT * FROM versions WHERE id=?",
                        (document["active_version_id"],),
                    )
                    if active_version["content_hash"] == content_hash:
                        response = {
                            "version_id": active_version["id"],
                            "revision": expected_revision,
                            "deduplicated": True,
                        }
                        remember(connection, scope, key, payload, response)
                        return response
                document_id = document["id"] if document else uid()
                if not document:
                    connection.execute(
                        "INSERT INTO documents(id,application_id,document_type) "
                        "VALUES(?,?,?)",
                        (document_id, application_id, document_type),
                    )
                version_number = connection.execute(
                    "SELECT COALESCE(MAX(number),0)+1 FROM versions "
                    "WHERE document_id=?",
                    (document_id,),
                ).fetchone()[0]
                version_id = uid()
                file_key = version_id + extension
                new_path = self.files / file_key
                with new_path.open("xb") as stored_file:
                    stored_file.write(content)
                connection.execute(
                    "INSERT INTO versions(id,document_id,number,file_key,"
                    "content_hash,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        version_id,
                        document_id,
                        version_number,
                        file_key,
                        content_hash,
                        now(),
                    ),
                )
                connection.execute(
                    "UPDATE documents SET active_version_id=? WHERE id=?",
                    (version_id, document_id),
                )
                invalidate(connection, application_id)
                response = {
                    "version_id": version_id,
                    "revision": expected_revision + 1,
                    "deduplicated": False,
                }
                remember(connection, scope, key, payload, response)
                return response
        except Exception:
            if new_path:
                new_path.unlink(missing_ok=True)
            raise
    def get_run(self, run_id):
        with self.db.transaction() as connection:
            row = dict(
                one(
                    connection,
                    "SELECT * FROM process_runs WHERE id=?",
                    (run_id,),
                )
            )
            for field in ("metadata", "blocks", "fields"):
                default = "[]" if field == "blocks" else "{}"
                row[field] = json.loads(row.pop(field + "_json") or default)
            return row

    def process(self, version_id, expected_revision, key=None):
        scope = "process:" + version_id
        payload = {"revision": expected_revision}
        with self.db.transaction() as connection:
            previous_response = cached(connection, scope, key, payload)
            if previous_response:
                return previous_response
            document_version = self.version_row(connection, version_id)
            application_id = document_version["application_id"]
            application = one(
                connection,
                "SELECT * FROM applications WHERE id=?",
                (application_id,),
            )
            check_revision(application, expected_revision)
            if document_version["active_version_id"] != version_id:
                raise DomainError(
                    "STALE_VERSION", "Dokumen bukan versi aktif", 409
                )
            running = connection.execute(
                "SELECT id FROM process_runs WHERE version_id=? AND status='RUNNING'",
                (version_id,),
            ).fetchone()
            if running:
                raise DomainError(
                    "PROCESS_ALREADY_RUNNING", "Proses masih berjalan", 409
                )
            run_id = uid()
            document_type = document_version["document_type"]
            file_path = self.files / document_version["file_key"]
            # Rerun membatalkan verifikasi/koreksi aktif agar hasil lama tak dipakai.
            connection.execute(
                "UPDATE versions SET active_run_id=NULL, corrections_json='{}', "
                "review_status='needs_review' WHERE id=?",
                (version_id,),
            )
            invalidate(connection, application_id)
            start_revision = expected_revision + 1
            metadata = {
                "mode": "SIMULATED_ADAPTERS"
                if self.ocr_factory or self.llm_factory
                else "LIVE",
                "ocr": "PP-OCRv5",
                "model": self.settings.gemini_model,
            }
            for package in ("paddlepaddle", "paddleocr", "google-genai"):
                try:
                    metadata[package] = version(package)
                except PackageNotFoundError:
                    metadata[package] = "not-installed"
            connection.execute(
                "INSERT INTO process_runs(id,version_id,status,input_revision,"
                "metadata_json,started_at) VALUES(?,?,?,?,?,?)",
                (
                    run_id,
                    version_id,
                    "RUNNING",
                    start_revision,
                    dump(metadata),
                    now(),
                ),
            )
            if key:
                remember(
                    connection,
                    scope,
                    key,
                    payload,
                    {"process_run_id": run_id, "application_id": application_id},
                )

        blocks = []
        fields = {}
        error = None
        status = "SUCCEEDED"
        import time

        start = time.perf_counter()
        if status != "MANUAL_ONLY":
            try:
                if self.ocr_factory:
                    ocr = self.ocr_factory()
                else:
                    from app.adapters.ocr.paddle import PaddleOCRAdapter

                    ocr = PaddleOCRAdapter(self.settings.ocr_timeout_seconds)
                if self.llm_factory:
                    llm = self.llm_factory()
                else:
                    from app.adapters.llm.gemini import GeminiAdapter

                    llm = GeminiAdapter(self.settings)
                blocks = ocr.extract(file_path)
                if not blocks:
                    raise DomainError("OCR_EMPTY", "Tidak ada teks terbaca")
                fields = SCHEMAS[document_type].model_validate(
                    llm.extract(document_type, blocks)
                ).model_dump()
                validate_document(fields, blocks, document_type)
                if document_type == "KTP":
                    fields["nomor_dokumen"] = dict(fields["nik"])
                metadata.update(getattr(llm, "metadata", {}))
                if self.ocr_factory or self.llm_factory:
                    metadata["mode"] = "SIMULATED_ADAPTERS"
            except DomainError as exc:
                status = "FAILED"
                error = exc.code
                fields = {}
            except Exception as exc:
                logger.warning(
                    "Document processing failed unexpectedly (type=%s)",
                    type(exc).__name__,
                )
                status = "FAILED"
                error = "PROCESS_ERROR"
                fields = {}
        metadata["seconds"] = round(time.perf_counter() - start, 3)
        with self.db.transaction() as connection:
            current_application = one(
                connection,
                "SELECT * FROM applications WHERE id=?",
                (application_id,),
            )
            active_version = self.version_row(connection, version_id)
            is_current = (
                current_application["revision"] == start_revision
                and active_version["active_version_id"] == version_id
            )
            metadata["published"] = is_current
            connection.execute(
                "UPDATE process_runs SET status=?,blocks_json=?,fields_json=?,"
                "error_code=?,metadata_json=?,finished_at=? WHERE id=?",
                (
                    status,
                    dump(blocks),
                    dump(fields),
                    error,
                    dump(metadata),
                    now(),
                    run_id,
                ),
            )
            if is_current:
                if status == "SUCCEEDED":
                    connection.execute(
                        "UPDATE versions SET active_run_id=? WHERE id=?",
                        (run_id, version_id),
                    )
                invalidate(connection, application_id)
        # Gunakan data terbaru jika review berubah saat AI masih berjalan.
        result = self.evaluate_latest(application_id)
        return {
            "process_run_id": run_id,
            "status": status,
            "error_code": error,
            "published": is_current,
            "application_id": application_id,
            "revision": result["revision"],
            "evaluation": result["evaluation"],
        }
    def evaluate_in_transaction(self, connection, application_id):
        application = one(
            connection,
            "SELECT * FROM applications WHERE id=?",
            (application_id,),
        )
        snapshot = self.snapshot(connection, application_id)
        profile = json.loads(application["profile_json"])
        results = evaluate_rules(snapshot, profile)
        outcome = aggregate(results)
        evaluation_id = uid()
        connection.execute(
            "INSERT INTO evaluations VALUES(?,?,?,?,?,?,?,?)",
            (
                evaluation_id,
                application_id,
                application["revision"],
                application["profile_json"],
                dump(snapshot),
                dump(results),
                outcome,
                now(),
            ),
        )
        connection.execute(
            "UPDATE applications SET active_evaluation_id=?, "
            "confirmed_evaluation_id=NULL WHERE id=?",
            (evaluation_id, application_id),
        )
        return {
            "revision": application["revision"],
            "evaluation": {
                "evaluation_id": evaluation_id,
                "outcome": outcome,
                "results": results,
            },
        }

    def evaluate_latest(self, application_id):
        with self.db.transaction() as connection:
            return self.evaluate_in_transaction(connection, application_id)

    def evaluate(self, application_id, expected_revision):
        with self.db.transaction() as connection:
            application = one(
                connection,
                "SELECT * FROM applications WHERE id=?",
                (application_id,),
            )
            check_revision(application, expected_revision)
            return self.evaluate_in_transaction(connection, application_id)

    def review(
        self,
        application_id,
        version_id,
        action,
        corrections,
        reason,
        expected_revision,
        page=1,
        key=None,
    ):
        reason = reason.strip()
        if not reason or len(reason) > 2000:
            raise DomainError(
                "REASON_REQUIRED", "Alasan 1-2000 karakter wajib"
            )
        if action not in ("verify", "request_reupload") or page != 1:
            raise DomainError("INVALID_REVIEW", "Aksi/halaman tidak valid")
        invalid_correction = any(
            name not in EXTRACTED_FIELDS
            or (
                value is not None
                and (not isinstance(value, str) or len(value) > 2000)
            )
            for name, value in corrections.items()
        )
        if invalid_correction:
            raise DomainError(
                "INVALID_CORRECTION", "Field/nilai koreksi tidak valid"
            )
        if action == "request_reupload" and corrections:
            raise DomainError(
                "INVALID_CORRECTION",
                "Permintaan ulang tidak sekaligus mengoreksi",
            )
        payload = {
            "vid": version_id,
            "action": action,
            "corrections": corrections,
            "reason": reason,
            "revision": expected_revision,
            "page": page,
        }
        scope = "review:" + application_id
        with self.db.transaction() as connection:
            previous_response = cached(connection, scope, key, payload)
            if previous_response:
                return previous_response
            application = one(
                connection,
                "SELECT * FROM applications WHERE id=?",
                (application_id,),
            )
            check_revision(application, expected_revision)
            document_version = self.version_row(connection, version_id)
            if (
                document_version["application_id"] != application_id
                or document_version["active_version_id"] != version_id
            ):
                raise DomainError(
                    "INVALID_REVIEW_TARGET",
                    "Target bukan dokumen aktif pendaftaran ini",
                    409,
                )
            review_id = uid()
            existing = json.loads(document_version["corrections_json"])
            before = self.snapshot(connection, application_id)["documents"][
                document_version["document_type"]
            ]["fields"]
            if (
                document_version["document_type"] == "KTP"
                and "nomor_dokumen" in corrections
                and "nik" not in corrections
            ):
                raise DomainError(
                    "INVALID_CORRECTION",
                    "Nomor dokumen KTP mengikuti NIK; koreksi field nik",
                )
            if (
                document_version["document_type"] == "KTP"
                and "nik" in corrections
            ):
                corrections = {
                    **corrections,
                    "nomor_dokumen": corrections["nik"],
                }
            for name, value in corrections.items():
                if name in DATE_FIELDS - {"tanggal_lahir"} and value is not None:
                    try:
                        if date.fromisoformat(value.strip()).isoformat() != value.strip():
                            raise ValueError()
                    except ValueError:
                        raise DomainError("INVALID_CORRECTION", "Tanggal dokumen harus sah dalam format YYYY-MM-DD") from None
                existing[name] = {
                    "value": value.strip() if isinstance(value, str) else None,
                    "source_kind": "review",
                    "source_id": review_id,
                    "document_version_id": version_id,
                    "evidence_refs": [{"page_number": 1}],
                    "status": "reviewed",
                }
            after = {**before, **existing}
            required_fields = REQUIRED_FIELDS[document_version["document_type"]]
            if action == "verify" and document_version["document_type"] == "KK":
                if any(after.get(k, {}).get("source_kind") != "review" for k in ("nama", "nik")):
                    raise DomainError("KK_SELECTION_REQUIRED", "Pilih anggota KK yang merupakan peserta dan periksa gambar")
            if action == "verify" and any(
                not after.get(field, {}).get("value") for field in required_fields
            ):
                raise DomainError(
                    "MISSING_FIELDS",
                    "Isi field wajib dari dokumen sebelum verifikasi",
                )
            connection.execute(
                "UPDATE versions SET review_status=?,corrections_json=? WHERE id=?",
                (
                    "verified" if action == "verify" else "needs_review",
                    dump(existing),
                    version_id,
                ),
            )
            invalidate(connection, application_id)
            connection.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    review_id,
                    application_id,
                    version_id,
                    application["active_evaluation_id"],
                    "demo-admin",
                    action,
                    dump({"before": before, "after": after, "page": page}),
                    reason,
                    expected_revision + 1,
                    now(),
                ),
            )
            response = self.evaluate_in_transaction(connection, application_id)
            response["review_id"] = review_id
            remember(connection, scope, key, payload, response)
            return response
    def confirm(self, application_id, evaluation_id, reason, expected_revision):
        if not reason.strip():
            raise DomainError("REASON_REQUIRED", "Alasan wajib")
        with self.db.transaction() as connection:
            application = one(
                connection,
                "SELECT * FROM applications WHERE id=?",
                (application_id,),
            )
            check_revision(application, expected_revision)
            if application["active_evaluation_id"] != evaluation_id:
                raise DomainError(
                    "STALE_EVALUATION", "Evaluasi bukan hasil aktif", 409
                )
            evaluation = one(
                connection,
                "SELECT * FROM evaluations WHERE id=?",
                (evaluation_id,),
            )
            if evaluation["outcome"] != "FLAGGED":
                raise DomainError(
                    "NO_FAILED_RULE", "Tidak ada FAIL untuk dikonfirmasi", 409
                )
            if application["confirmed_evaluation_id"] != evaluation_id:
                connection.execute(
                    "UPDATE applications SET confirmed_evaluation_id=? WHERE id=?",
                    (evaluation_id, application_id),
                )
                failed_rules = [
                    result["rule_code"]
                    for result in json.loads(evaluation["results_json"])
                    if result["result"] == "FAIL"
                ]
                connection.execute(
                    "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        uid(),
                        application_id,
                        None,
                        evaluation_id,
                        "demo-admin",
                        "confirm_ineligible",
                        dump({"failed_rules": failed_rules}),
                        reason,
                        expected_revision,
                        now(),
                    ),
                )
            return {
                "application_id": application_id,
                "revision": expected_revision,
                "outcome": "INELIGIBLE",
                "evaluation_id": evaluation_id,
            }

    def change_profile(self, application_id, name, expected_revision, reason):
        profile = self.profile(name)
        if not reason.strip():
            raise DomainError("REASON_REQUIRED", "Alasan wajib")
        with self.db.transaction() as connection:
            application = one(
                connection,
                "SELECT * FROM applications WHERE id=?",
                (application_id,),
            )
            check_revision(application, expected_revision)
            connection.execute(
                "UPDATE applications SET profile_json=? WHERE id=?",
                (dump(profile), application_id),
            )
            invalidate(connection, application_id)
            connection.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    uid(),
                    application_id,
                    None,
                    application["active_evaluation_id"],
                    "demo-admin",
                    "change_profile",
                    dump(
                        {
                            "before": json.loads(application["profile_json"])["id"],
                            "after": name,
                        }
                    ),
                    reason,
                    expected_revision + 1,
                    now(),
                ),
            )
            return self.evaluate_in_transaction(connection, application_id)

    def history(self, application_id):
        with self.db.transaction() as connection:
            one(
                connection,
                "SELECT id FROM applications WHERE id=?",
                (application_id,),
            )
            return {
                "reviews": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM reviews WHERE application_id=? ORDER BY rowid",
                        (application_id,),
                    )
                ],
                "evaluations": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM evaluations WHERE application_id=? "
                        "ORDER BY rowid",
                        (application_id,),
                    )
                ],
            }

    def content(self, version_id):
        with self.db.transaction() as connection:
            document_version = self.version_row(connection, version_id)
        path = self.files / document_version["file_key"]
        if not path.is_file():
            raise DomainError("FILE_MISSING", "File tidak tersedia", 404)
        return path

    def extraction(self, version_id):
        with self.db.transaction() as connection:
            document_version = self.version_row(connection, version_id)
            runs = [
                dict(row)
                for row in connection.execute(
                    "SELECT id,status,error_code,started_at FROM process_runs "
                    "WHERE version_id=? ORDER BY started_at DESC",
                    (version_id,),
                )
            ]
            active_run = (
                one(
                    connection,
                    "SELECT * FROM process_runs WHERE id=?",
                    (document_version["active_run_id"],),
                )
                if document_version["active_run_id"]
                else None
            )
            return {
                "version_id": version_id,
                "review_status": document_version["review_status"],
                "fields": json.loads(active_run["fields_json"])
                if active_run
                else {},
                "blocks": json.loads(active_run["blocks_json"])
                if active_run
                else [],
                "corrections": json.loads(document_version["corrections_json"]),
                "runs": runs,
            }
