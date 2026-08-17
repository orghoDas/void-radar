from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("")
def health_check() -> dict[str, str]:
    settings = get_settings()

    return {
        "status": "ok",
        "service": "void-radar-api",
        "environment": settings.app_env,
    }

