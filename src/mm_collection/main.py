"""FastAPI entry point for M&M Collection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .database import apply_migrations, database_path

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def create_app(db_path: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        target = db_path or database_path()
        apply_migrations(target)
        app.state.database_path = target
        yield

    application = FastAPI(title="M&M Collection", lifespan=lifespan)

    @application.get("/", response_class=HTMLResponse, name="index")
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={},
        )

    return application


app = create_app()

