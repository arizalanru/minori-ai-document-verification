"""Kontrak ekstraksi per jenis; aturan medis dan keaslian tidak diotomasi."""
from pydantic import BaseModel, ConfigDict, Field

from app.domain.schemas import ExtractedField, ExtractionResult


class FamilyMember(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nama: ExtractedField
    nik: ExtractedField
    tanggal_lahir: ExtractedField


class FamilyExtraction(ExtractionResult):
    anggota: list[FamilyMember] = Field(max_length=30)


class TranscriptExtraction(ExtractionResult):
    institusi: ExtractedField


class PoliceExtraction(ExtractionResult):
    tanggal_terbit: ExtractedField
    tanggal_berakhir: ExtractedField


class MedicalExtraction(ExtractionResult):
    tanggal_pemeriksaan: ExtractedField
    kesimpulan_dokter: ExtractedField


SCHEMAS = {
    "KTP": ExtractionResult,
    "IJAZAH": ExtractionResult,
    "KK": FamilyExtraction,
    "TRANSKRIP": TranscriptExtraction,
    "SKCK": PoliceExtraction,
    "MCU": MedicalExtraction,
}
REQUIRED_FIELDS = {
    "KTP": ("nama", "nik", "tanggal_lahir", "alamat"),
    "IJAZAH": ("nama", "pendidikan_terakhir", "nomor_dokumen"),
    "KK": ("nama", "nik", "nomor_dokumen"),
    "TRANSKRIP": ("nama", "institusi"),
    "SKCK": ("nama", "nomor_dokumen", "tanggal_terbit"),
    "MCU": ("nama", "tanggal_pemeriksaan", "kesimpulan_dokter"),
}
EXTRA_FIELDS = (
    "institusi", "tanggal_terbit", "tanggal_berakhir",
    "tanggal_pemeriksaan", "kesimpulan_dokter",
)
DATE_FIELDS = {"tanggal_lahir", "tanggal_terbit", "tanggal_berakhir", "tanggal_pemeriksaan"}


def validate_document(data, blocks, kind):
    from app.core.errors import DomainError
    from app.domain.evidence import validate_extraction

    validate_extraction({k: v for k, v in data.items() if k != "anggota"}, blocks)
    if kind == "KK":
        for member in data["anggota"]:
            validate_extraction(member, blocks)
        # Pemilihan peserta adalah aksi admin. Bahkan KK satu anggota tidak
        # boleh otomatis mengisi identitas peserta pada envelope utama.
        if any(data[k]["value"] is not None for k in ("nama", "nik", "tanggal_lahir")):
            raise DomainError("OUTPUT_INVALID", "Pilih identitas peserta KK melalui review admin")
