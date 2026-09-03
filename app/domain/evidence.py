import re
from datetime import date, datetime

from app.core.errors import DomainError


def validate_extraction(data, blocks):
    source_text = {block["block_id"]: block["text"] for block in blocks}
    for name, field in data.items():
        evidence_ids = field["evidence_ids"]
        raw_text = field["raw_text"]
        value = field["value"]
        if len(evidence_ids) != len(set(evidence_ids)) or any(
            evidence_id not in source_text for evidence_id in evidence_ids
        ):
            raise DomainError("OUTPUT_INVALID", f"Bukti {name} tidak valid")
        if raw_text is not None and not any(
            raw_text in source_text[evidence_id] for evidence_id in evidence_ids
        ):
            raise DomainError("OUTPUT_INVALID", f"Kutipan {name} tidak cocok")
        if field["status"] != "extracted":
            if value is not None or field["reason_code"] == "NONE":
                raise DomainError(
                    "OUTPUT_INVALID", f"Null/status {name} tidak konsisten"
                )
            continue
        if (
            not value
            or not raw_text
            or not evidence_ids
            or field["reason_code"] != "NONE"
        ):
            raise DomainError(
                "OUTPUT_INVALID", f"Nilai/bukti {name} belum lengkap"
            )
        if name == "tanggal_lahir":
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    raise ValueError()
                normalized = date.fromisoformat(value)
                candidates = []
                for date_format in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
                    try:
                        candidates.append(
                            datetime.strptime(raw_text, date_format).date()
                        )
                    except ValueError:
                        pass
                if normalized not in candidates:
                    raise ValueError()
            except ValueError:
                raise DomainError(
                    "OUTPUT_INVALID",
                    "Tanggal tidak cocok dengan sumber/format yang didukung",
                ) from None
        elif " ".join(value.split()) != " ".join(raw_text.split()):
            raise DomainError("OUTPUT_INVALID", f"Nilai {name} mengubah sumber")
        if name == "nik" and not re.fullmatch(r"[0-9]{16}", value):
            raise DomainError("OUTPUT_INVALID", "NIK ambigu harus null")
