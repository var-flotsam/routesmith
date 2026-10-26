"""The FastAPI application."""

from fastapi import FastAPI

from starboard.api.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Starboard Routing", version="0.0.0")
    app.state.settings = settings or Settings()

    @app.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        """Liveness: the process answers. It does not touch the database."""
        return {"status": "ok"}

    return app
