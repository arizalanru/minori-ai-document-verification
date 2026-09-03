from pathlib import Path
from typing import Protocol


class OCRAdapter(Protocol):
    def extract(self, image_path: Path) -> list[dict]: ...
