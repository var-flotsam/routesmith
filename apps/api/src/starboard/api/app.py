"""The FastAPI application."""

from fastapi import FastAPI

from starboard.api.db import engine_for, session_maker
from starboard.api.email import ConsoleEmailSender, EmailSender
from starboard.api.queue import ArqQueue, JobQueue
from starboard.api.routers import auth, orgs, routes, runs, uploads
from starboard.api.settings import Settings
from starboard.api.storage import LocalObjectStore, ObjectStore


def create_app(
    settings: Settings | None = None,
    email_sender: EmailSender | None = None,
    store: ObjectStore | None = None,
    queue: JobQueue | None = None,
) -> FastAPI:
    """The app; it connects to the database and Redis on first use, not here."""
    app = FastAPI(title="Starboard Routing", version="0.0.0")
    app.state.settings = settings = settings or Settings()
    app.state.engine = engine = engine_for(settings.database_url)
    app.state.sessions = session_maker(engine)
    app.state.email_sender = email_sender or ConsoleEmailSender()
    app.state.store = store or LocalObjectStore(settings.upload_dir)
    app.state.queue = queue or ArqQueue(settings.redis_url)

    @app.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        """Liveness: the process answers. It does not touch the database."""
        return {"status": "ok"}

    for router in (auth.router, orgs.router, routes.router, uploads.router, runs.router):
        app.include_router(router)
    return app
