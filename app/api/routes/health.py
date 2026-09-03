from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "stage": "backend-core",
        "dependencies_checked": False,
        "demo_only": True,
        "authentication": "not-implemented-local-only",
    }
