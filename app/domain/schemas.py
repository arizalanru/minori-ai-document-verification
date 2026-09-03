from typing import Literal

from pydantic import BaseModel, ConfigDict


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: str | None
    raw_text: str | None
    status: Literal["extracted", "ambiguous", "not_found", "not_applicable"]
    evidence_ids: list[str]
    reason_code: Literal[
        "NONE",
        "OCR_AMBIGUOUS",
        "MULTIPLE_CANDIDATES",
        "FIELD_ABSENT",
        "NOT_EXPECTED",
        "INVALID_FORMAT",
    ]


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nama: ExtractedField
    nik: ExtractedField
    tanggal_lahir: ExtractedField
    alamat: ExtractedField
    pendidikan_terakhir: ExtractedField
    nomor_dokumen: ExtractedField
