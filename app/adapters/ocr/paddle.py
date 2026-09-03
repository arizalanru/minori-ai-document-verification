import json
import subprocess
import sys
import tempfile
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.core.errors import DomainError


class PaddleOCRAdapter:
    def __init__(self, timeout=60):
        self.timeout = timeout

    def extract(self, image_path):
        with tempfile.TemporaryDirectory(prefix="ocr-result-") as tmp:
            output = Path(tmp) / "blocks.json"
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "app.adapters.ocr.worker",
                        str(image_path),
                        str(output),
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                raise DomainError(
                    "OCR_TIMEOUT", "OCR melewati batas waktu", 503
                ) from None
            if result.returncode or not output.exists():
                raise DomainError(
                    "OCR_ERROR", "OCR gagal; cek smoke_ocr.py", 503
                )
            blocks = json.loads(output.read_text(encoding="utf-8"))
            if not blocks:
                raise DomainError("OCR_EMPTY", "Tidak ada teks terbaca")
            return blocks
