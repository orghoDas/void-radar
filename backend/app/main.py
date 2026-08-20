from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.contacts import router as contacts_router
from app.api.routes.enrichment import router as enrichment_router
from app.api.routes.health import router as health_router
from app.api.routes.identity import router as identity_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.outreach import router as outreach_router
from app.api.routes.scoring import router as scoring_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Void Radar API",
        version="0.1.0",
        description="Prospect intelligence API for Void Studio.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/health", tags=["health"])
    app.include_router(
        ingestion_router,
        prefix="/ingestion",
        tags=["ingestion"],
    )
    app.include_router(
        identity_router,
        prefix="/identity",
        tags=["identity"],
    )
    app.include_router(
        contacts_router,
        prefix="/contacts",
        tags=["contacts"],
    )
    app.include_router(
        enrichment_router,
        prefix="/enrichment",
        tags=["enrichment"],
    )
    app.include_router(
        scoring_router,
        prefix="/scoring",
        tags=["scoring"],
    )
    app.include_router(
        outreach_router,
        prefix="/outreach",
        tags=["outreach"],
    )

    return app


app = create_app()
