"""Main FastAPI application for ARTEMIS."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.tte import router as tte_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="ARTEMIS API",
        description="ARTEMIS integration endpoints for Broadsea/ATLAS.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(tte_router)

    try:
        from src.agents.conceptset.api import router as conceptset_router

        app.include_router(conceptset_router)
    except Exception:
        # Keep the TTE MVP bootable even when optional conceptset dependencies are unavailable.
        pass

    @app.on_event("startup")
    async def _spark_startup_check() -> None:
        import os as _os

        if _os.environ.get("COHORT_ENGINE") == "spark":
            from src.pipeline.spark_startup import validate_spark_prerequisites

            validate_spark_prerequisites()

    return app


app = create_app()

