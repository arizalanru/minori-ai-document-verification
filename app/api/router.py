from fastapi import APIRouter

from app.api.routes import backend, health

router = APIRouter()
router.include_router(health.router)
router.include_router(backend.router)
