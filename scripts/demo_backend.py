"""Demo HTTP dengan dua gambar sintetis dan maksimal dua panggilan LLM."""

import json
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"

def call(path, payload=None, raw=None, content_type=None):
    data = (
        raw
        if raw is not None
        else json.dumps(payload).encode()
        if payload is not None
        else None
    )
    request = Request(
        BASE + path,
        data=data,
        headers={"Content-Type": content_type or "application/json"},
    )
    with urlopen(request, timeout=180) as response:
        return json.load(response)

def make_image(path, lines):
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
    except OSError:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    image = Image.new("RGB", (1400, 650), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((45, 40 + index * 75), line, font=font, fill="black")
    image.save(path)

def upload(application_id, document_type, path, revision):
    boundary = "demo-" + uuid.uuid4().hex
    parts = []
    for key, value in [
        ("document_type", document_type),
        ("expected_revision", str(revision)),
    ]:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: image/png\r\n\r\n'.encode())
    parts.extend([path.read_bytes(), f"\r\n--{boundary}--\r\n".encode()])
    return call(
        f"/applications/{application_id}/documents",
        raw=b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
    )

def main():
    output = ROOT / "var" / "demo_backend" / uuid.uuid4().hex
    output.mkdir(parents=True)
    health = call("/health")
    if health.get("stage") != "backend-core":
        raise RuntimeError("Server tidak menggunakan backend yang diharapkan")
    application = call("/applications", {"rule_version_id": "demo-core-v1"})
    application_id = application["application_id"]
    print("APPLICATION_ID:", application_id, flush=True)
    (output / "application.json").write_text(
        json.dumps(application, indent=2), encoding="utf-8"
    )
    fixtures = {
        "KTP": [
            "DOKUMEN SINTETIS - DEMO KTP",
            "Nama: PESERTA DEMO A",
            "NIK: 0000000000000001",
            "Tanggal Lahir: 21-05-2006",
            "Alamat: JALAN CONTOH NOMOR 1",
            "BUKAN DOKUMEN IDENTITAS RESMI",
        ],
        "IJAZAH": [
            "DOKUMEN SINTETIS - DEMO IJAZAH",
            "Nama: PESERTA DEMO A",
            "Pendidikan: SMA",
            "Nomor Ijazah: DEMO-IJZ-001",
            "BUKAN IJAZAH RESMI",
        ],
    }
    for document_type, lines in fixtures.items():
        path = output / (document_type.lower() + ".png")
        make_image(path, lines)
        revision = call("/applications/" + application_id)["revision"]
        uploaded = upload(application_id, document_type, path, revision)
        print(
            document_type,
            "version_id:",
            uploaded["version_id"],
            "- memproses OCR/LLM...",
            flush=True,
        )
        processed = call(
            "/documents/" + uploaded["version_id"] + "/process",
            {"expected_revision": uploaded["revision"]},
        )
        print(
            "Status:",
            processed.get("status"),
            "Error:",
            processed.get("error_code"),
            flush=True,
        )
        if processed.get("status") != "SUCCEEDED":
            print(
                "Proses berhenti agar tidak menambah panggilan layanan. "
                "Pendaftaran tetap tersimpan."
            )
            break
    result = call("/applications/" + application_id)
    (output / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("Outcome:", result["outcome"])
    print("Data:", json.dumps(result["data"], ensure_ascii=False))
    print("Revision:", result["revision"])
    print("Hasil:", output)
    print("Periksa gambar dan nilai sebelum verifikasi melalui /docs.")

if __name__ == "__main__":
    try:
        main()
    except HTTPError as exc:
        print("HTTP", exc.code, exc.read().decode(errors="replace"))
        sys.exit(1)
    except (URLError, TimeoutError):
        print(
            "Koneksi/timeout. Periksa server dan status pendaftaran sebelum mengulang."
        )
        sys.exit(1)
