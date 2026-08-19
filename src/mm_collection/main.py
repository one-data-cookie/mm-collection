"""FastAPI entry point for M&M Collection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from .catalog import ITEM_FIELDS, PhotoError, create_item
from .database import apply_migrations, database_path, list_items

PACKAGE_DIRECTORY = Path(__file__).parent
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")


def create_app(db_path: Path | None = None) -> FastAPI:
    target = db_path or database_path()
    photos = target.parent / "photos"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        apply_migrations(target)
        photos.mkdir(parents=True, exist_ok=True)
        app.state.database_path = target
        app.state.photo_directory = photos
        yield

    application = FastAPI(title="M&M Collection", lifespan=lifespan)
    application.mount(
        "/static",
        StaticFiles(directory=PACKAGE_DIRECTORY / "static"),
        name="static",
    )
    application.mount(
        "/media",
        StaticFiles(directory=photos, check_dir=False),
        name="media",
    )

    @application.get("/", response_class=HTMLResponse, name="index")
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"items": list_items(target)},
        )

    @application.get("/items/new", response_class=HTMLResponse, name="new_item")
    async def new_item(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="new_item.html",
            context={"values": {}, "error": None},
        )

    @application.post(
        "/items/new", response_class=HTMLResponse, name="create_item"
    )
    async def create_item_route(request: Request) -> HTMLResponse:
        form = await request.form()
        values = {
            field: (str(form.get(field, "")).strip() or None)
            for field in ITEM_FIELDS
        }
        uploads = [
            upload
            for upload in form.getlist("photos")
            if isinstance(upload, UploadFile) and upload.filename
        ]

        if values["title"] is None:
            return templates.TemplateResponse(
                request=request,
                name="new_item.html",
                context={"values": values, "error": "Please enter a title."},
                status_code=422,
            )

        try:
            await create_item(target, photos, values, uploads)
        except PhotoError as error:
            return templates.TemplateResponse(
                request=request,
                name="new_item.html",
                context={"values": values, "error": str(error)},
                status_code=400,
            )

        return RedirectResponse(request.url_for("index"), status_code=303)

    return application


app = create_app()
