from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core.config import PROJECT_ROOT, Settings
from app.core.errors import DomainError
from app.services.backend import Backend


def create_app(settings=None, ocr_factory=None, llm_factory=None):
    settings = settings or Settings()
    backend = Backend(settings, PROJECT_ROOT, ocr_factory, llm_factory)

    @asynccontextmanager
    async def lifespan(app):
        backend.initialize()
        yield

    app = FastAPI(
        title="Asisten Verifikasi Berkas",
        version="0.3.0-admin",
        lifespan=lifespan,
    )
    app.state.backend = backend

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
