"""The FastAPI application."""

from fastapi import FastAPI

from starboard.api.db import engine_for, session_maker
from starboard.api.email import ConsoleEmailSender, EmailSender
from starboard.api.routers import auth, orgs
from starboard.api.settings import Settings


def create_app(
    settings: Settings | None = None, email_sender: EmailSender | None = None
) -> FastAPI:
    """The app; it connects to the database on first use, not here."""
    app = FastAPI(title="Starboard Routing", version="0.0.0")
    app.state.settings = settings = settings or Settings()
    app.state.engine = engine = engine_for(settings.database_url)
    app.state.sessions = session_maker(engine)
    app.state.email_sender = email_sender or ConsoleEmailSender()

    @app.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        """Liveness: the process answers. It does not touch the database."""
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(orgs.router)
    return app
