"""Konfigurasi aplikasi; jangan mencetak Settings karena dapat memuat rahasia."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")
    app_name: str = "Asisten Verifikasi Berkas"
    demo_only: bool = True
    database_path: Path = Path("var/app.sqlite3")
    private_files_dir: Path = Path("var/files")
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.1-flash-lite"
    ocr_timeout_seconds: int = 60
    llm_timeout_seconds: int = 60
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 20_000_000
    demo_access_username: str = ""
    demo_access_password: SecretStr = SecretStr("")

    def resolve_path(self, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path
