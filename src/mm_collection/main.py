"""FastAPI entry point for M&M Collection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from .catalog import ITEM_FIELDS, PhotoError, create_item
from .database import (
    apply_migrations,
    database_path,
    get_item,
    list_items,
    update_item,
)

PACKAGE_DIRECTORY = Path(__file__).parent
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")
DATE_FIELDS = ("date_created", "date_acquired")


def _normalize_dates(values: dict[str, str | None]) -> str | None:
    """Normalize entered dates to ISO format, returning an error if invalid."""
    for field in DATE_FIELDS:
        value = values[field]
        if value is None:
            continue
        try:
            values[field] = date.fromisoformat(value).isoformat()
        except ValueError:
            return "Please enter dates as YYYY-MM-DD."
    return None


def _validation_error(values: dict[str, str | None]) -> str | None:
    if values["title"] is None:
        return "Please enter a title."
    return _normalize_dates(values)


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
            context={
                "values": {},
                "error": None,
                "editing": False,
                "cancel_url": request.url_for("index"),
            },
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

        validation_error = _validation_error(values)
        if validation_error is not None:
            return templates.TemplateResponse(
                request=request,
                name="new_item.html",
                context={
                    "values": values,
                    "error": validation_error,
                    "editing": False,
                    "cancel_url": request.url_for("index"),
                },
                status_code=422,
            )

        try:
            await create_item(target, photos, values, uploads)
        except PhotoError as error:
            return templates.TemplateResponse(
                request=request,
                name="new_item.html",
                context={
                    "values": values,
                    "error": str(error),
                    "editing": False,
                    "cancel_url": request.url_for("index"),
                },
                status_code=400,
            )

        return RedirectResponse(request.url_for("index"), status_code=303)

    @application.get(
        "/items/{item_id}", response_class=HTMLResponse, name="item_detail"
    )
    async def item_detail(request: Request, item_id: int) -> HTMLResponse:
        item = get_item(item_id, target)
        if item is None:
            raise HTTPException(status_code=404, detail="Object not found")
        return templates.TemplateResponse(
            request=request,
            name="item_detail.html",
            context={"item": item},
        )

    @application.get(
        "/items/{item_id}/edit", response_class=HTMLResponse, name="edit_item"
    )
    async def edit_item(request: Request, item_id: int) -> HTMLResponse:
        item = get_item(item_id, target)
        if item is None:
            raise HTTPException(status_code=404, detail="Object not found")
        return templates.TemplateResponse(
            request=request,
            name="new_item.html",
            context={
                "values": item,
                "error": None,
                "editing": True,
                "cancel_url": request.url_for("item_detail", item_id=item_id),
            },
        )

    @application.post(
        "/items/{item_id}/edit",
        response_class=HTMLResponse,
        name="update_item",
    )
    async def update_item_route(request: Request, item_id: int) -> HTMLResponse:
        if get_item(item_id, target) is None:
            raise HTTPException(status_code=404, detail="Object not found")

        form = await request.form()
        values = {
            field: (str(form.get(field, "")).strip() or None)
            for field in ITEM_FIELDS
        }
        validation_error = _validation_error(values)
        if validation_error is not None:
            return templates.TemplateResponse(
                request=request,
                name="new_item.html",
                context={
                    "values": values,
                    "error": validation_error,
                    "editing": True,
                    "cancel_url": request.url_for("item_detail", item_id=item_id),
                },
                status_code=422,
            )

        update_item(item_id, values, target)
        return RedirectResponse(
            request.url_for("item_detail", item_id=item_id), status_code=303
        )

    return application


app = create_app()
