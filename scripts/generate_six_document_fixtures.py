"""Buat gambar sintetis tanpa jaringan; JSON expected bukan keluaran AI live."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE_FIELDS = ("nama", "nik", "tanggal_lahir", "alamat", "pendidikan_terakhir", "nomor_dokumen")
VALUES = {
    "KTP": {"nama": "PESERTA DEMO A", "nik": "0000000000000001", "tanggal_lahir": "2006-05-21", "alamat": "JALAN CONTOH NOMOR 1", "nomor_dokumen": "0000000000000001"},
    "IJAZAH": {"nama": "PESERTA DEMO A", "pendidikan_terakhir": "SMA", "nomor_dokumen": "DEMO-IJZ-001"},
    "KK": {"nomor_dokumen": "0000000000000099", "alamat": "JALAN CONTOH NOMOR 1"},
    "TRANSKRIP": {"nama": "PESERTA DEMO A", "institusi": "SEKOLAH DEMO", "nomor_dokumen": "DEMO-TR-001"},
    "SKCK": {"nama": "PESERTA DEMO A", "nik": "0000000000000001", "nomor_dokumen": "DEMO-SKCK-001", "tanggal_terbit": "2026-08-01", "tanggal_berakhir": "2027-02-01"},
    "MCU": {"nama": "PESERTA DEMO A", "nomor_dokumen": "DEMO-MCU-001", "tanggal_pemeriksaan": "2026-08-30", "kesimpulan_dokter": "CONTOH SINTETIS: pemeriksaan lanjutan diperlukan"},
}


def missing(status="not_found", reason="FIELD_ABSENT"):
    return dict(value=None, raw_text=None, status=status, evidence_ids=[], reason_code=reason)


def fixture(kind):
    blocks = []

    def field(name, value):
        block_id = f"b{len(blocks) + 1}"
        blocks.append(dict(block_id=block_id, page_number=1, text=f"{name}: {value}", confidence=.99, polygon=None))
        return dict(value=value, raw_text=value, status="extracted", evidence_ids=[block_id], reason_code="NONE")

    fields = {name: missing() for name in BASE_FIELDS}
    fields.update({name: field(name, value) for name, value in VALUES[kind].items()})
    if kind == "KK":
        for name in ("nama", "nik", "tanggal_lahir"):
            fields[name] = missing("ambiguous", "MULTIPLE_CANDIDATES")
        fields["anggota"] = [
            {name: field(f"Anggota {i} {name}", value) for name, value in member.items()}
            for i, member in enumerate([
                {"nama": "KEPALA KELUARGA DEMO", "nik": "0000000000000002", "tanggal_lahir": "1975-01-01"},
                {"nama": "PESERTA DEMO A", "nik": "0000000000000001", "tanggal_lahir": "2006-05-21"},
            ], 1)
        ]
    return fields, blocks


def main():
    import uuid
    output = Path(__file__).resolve().parents[1] / "var" / "six_document_fixtures" / uuid.uuid4().hex
    output.mkdir(parents=True)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 30)
    except OSError:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
    for kind in VALUES:
        fields, blocks = fixture(kind)
        lines = [f"DOKUMEN SINTETIS - DEMO {kind}", "BUKAN DOKUMEN RESMI"] + [b["text"].replace("_", " ") for b in blocks]
        image = Image.new("RGB", (1900, 100 + 65 * len(lines)), "white")
        draw = ImageDraw.Draw(image)
        for i, line in enumerate(lines):
            draw.text((40, 35 + 65 * i), line, font=font, fill="black")
        image.save(output / f"{kind}.png")
        (output / f"{kind}.expected.json").write_text(json.dumps({"mode": "SYNTHETIC_EXPECTATION_NOT_LIVE_OUTPUT", "fields": fields, "blocks": blocks}, indent=2), encoding="utf-8")
    print("Gambar demo (tanpa panggilan API):", output)


if __name__ == "__main__":
    main()
