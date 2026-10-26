"""The FastAPI application."""

import re

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from starboard.api.db import engine_for, session_maker
from starboard.api.email import ConsoleEmailSender, EmailSender
from starboard.api.queue import ArqQueue, JobQueue
from starboard.api.routers import auth, orgs, routes, runs, shares, uploads
from starboard.api.settings import Settings
from starboard.api.storage import LocalObjectStore, ObjectStore

_METHOD_NOT_ALLOWED = 405


def _template(path: str) -> re.Pattern[str]:
    """A spec path such as `/orgs/{org_id}` as a pattern matching request paths."""
    return re.compile("[^/]+".join(re.escape(part) for part in re.split(r"\{[^/]+?\}", path)))


def create_app(
    settings: Settings | None = None,
    email_sender: EmailSender | None = None,
    store: ObjectStore | None = None,
    queue: JobQueue | None = None,
) -> FastAPI:
    """The app; it connects to the database and Redis on first use, not here."""
    app = FastAPI(
        title="Starboard Routing",
        version="0.0.0",
        responses={400: {"description": "the request body could not be read"}},
    )
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

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> Response:
        """A 405 lists every method the path takes (RFC 9110, section 15.5.6)."""
        if error.status_code != _METHOD_NOT_ALLOWED:
            return await http_exception_handler(request, error)
        path = request.url.path
        methods = sorted(
            {
                method.upper()
                for template, operations in app.openapi()["paths"].items()
                if _template(template).fullmatch(path)
                for method in operations
            }
        )
        return JSONResponse(
            {"detail": "Method Not Allowed"},
            status_code=_METHOD_NOT_ALLOWED,
            headers={"Allow": ", ".join(methods)},
        )

    routers = (auth, orgs, routes, uploads, runs, shares)
    for module in routers:
        app.include_router(module.router)
    return app
