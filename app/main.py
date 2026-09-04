import base64
import binascii
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core.config import PROJECT_ROOT, Settings
from app.core.errors import DomainError
from app.services.backend import Backend


def _valid_basic_auth(request, expected_username, expected_password):
    header = request.headers.get("authorization", "")
    try:
        scheme, encoded = header.split(" ", 1)
        if scheme.lower() != "basic":
            return False
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    return secrets.compare_digest(username, expected_username) and secrets.compare_digest(
        password, expected_password
    )


def create_app(settings=None, ocr_factory=None, llm_factory=None):
    settings = settings or Settings()
    backend = Backend(settings, PROJECT_ROOT, ocr_factory, llm_factory)
    demo_username = settings.demo_access_username.strip()
    demo_password = settings.demo_access_password.get_secret_value()
    if bool(demo_username) != bool(demo_password):
        raise RuntimeError(
            "DEMO_ACCESS_USERNAME and DEMO_ACCESS_PASSWORD must be configured together"
        )

    @asynccontextmanager
    async def lifespan(app):
        backend.initialize()
        yield

    app = FastAPI(
        title="Asisten Verifikasi Berkas",
        version="0.4.0-demo",
        lifespan=lifespan,
    )
    app.state.backend = backend

    if demo_username and demo_password:
        @app.middleware("http")
        async def protect_demo(request: Request, call_next):
            if request.url.path == "/api/v1/health":
                return await call_next(request)
            if not _valid_basic_auth(request, demo_username, demo_password):
                return Response(
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Minori Demo", charset="UTF-8"'},
                )
            return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(router, prefix="/api/v1")
    web_root = PROJECT_ROOT / "app" / "web"
    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def admin_home():
        return FileResponse(
            web_root / "templates" / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_app()
