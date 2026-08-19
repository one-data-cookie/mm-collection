"""FastAPI entry point for M&M Collection."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from .catalog import (
    ITEM_FIELDS,
    PhotoError,
    add_photos,
    create_item,
    delete_item as delete_catalog_item,
    manage_photo,
)
from .database import (
    apply_migrations,
    database_path,
    get_item,
    list_items,
    update_item,
)

PACKAGE_DIRECTORY = Path(__file__).parent
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")
ISO_DATE_FIELDS = ("date_acquired",)
INGRESS_PROXY_ADDRESSES = {"172.30.32.2", "127.0.0.1", "::1"}


def _normalize_dates(values: dict[str, str | None]) -> str | None:
    """Normalize entered dates to ISO format, returning an error if invalid."""
    for field in ISO_DATE_FIELDS:
        value = values[field]
        if value is None:
            continue
        try:
            values[field] = date.fromisoformat(value).isoformat()
        except ValueError:
            return "Please enter Date acquired as YYYY-MM-DD."
    return None


def _validation_error(values: dict[str, str | None]) -> str | None:
    if values["title"] is None:
        return "Please enter a title."
    return _normalize_dates(values)


def _path_for(request: Request, name: str, **path_params: object) -> str:
    """Build a same-origin path that remains inside Home Assistant Ingress."""
    path = request.url_for(name, **path_params).path
    ingress_path = request.headers.get("x-ingress-path", "").rstrip("/")
    if ingress_path.startswith("/") and not ingress_path.startswith("//"):
        return f"{ingress_path}{path}"
    return path


templates.env.globals["path_for"] = _path_for


def create_app(db_path: Path | None = None) -> FastAPI:
    target = db_path or database_path()
    photos = target.parent / "photos"
    ingress_only = os.environ.get("MM_COLLECTION_INGRESS_ONLY", "").lower() in {
        "1",
        "true",
        "yes",
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        apply_migrations(target)
        photos.mkdir(parents=True, exist_ok=True)
        app.state.database_path = target
        app.state.photo_directory = photos
        yield

    application = FastAPI(title="M&M Collection", lifespan=lifespan)

    @application.middleware("http")
    async def home_assistant_ingress(request: Request, call_next):
        """Trust Home Assistant's Ingress proxy and generate prefixed URLs."""
        client_host = request.client.host if request.client is not None else None
        if ingress_only and client_host not in INGRESS_PROXY_ADDRESSES:
            return PlainTextResponse("Forbidden", status_code=403)

        return await call_next(request)

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

    @application.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
                "cancel_url": _path_for(request, "index"),
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
                    "cancel_url": _path_for(request, "index"),
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
                    "cancel_url": _path_for(request, "index"),
                },
                status_code=400,
            )

        return RedirectResponse(_path_for(request, "index"), status_code=303)

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
                "cancel_url": _path_for(request, "item_detail", item_id=item_id),
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
                    "cancel_url": _path_for(
                        request, "item_detail", item_id=item_id
                    ),
                },
                status_code=422,
            )

        update_item(item_id, values, target)
        return RedirectResponse(
            _path_for(request, "item_detail", item_id=item_id), status_code=303
        )

    @application.get(
        "/items/{item_id}/photos",
        response_class=HTMLResponse,
        name="manage_photos",
    )
    async def manage_photos_route(request: Request, item_id: int) -> HTMLResponse:
        item = get_item(item_id, target)
        if item is None:
            raise HTTPException(status_code=404, detail="Object not found")
        return templates.TemplateResponse(
            request=request,
            name="manage_photos.html",
            context={"item": item, "error": None},
        )

    @application.post(
        "/items/{item_id}/photos",
        response_class=HTMLResponse,
        name="add_item_photos",
    )
    async def add_item_photos_route(request: Request, item_id: int) -> HTMLResponse:
        item = get_item(item_id, target)
        if item is None:
            raise HTTPException(status_code=404, detail="Object not found")

        form = await request.form()
        uploads = [
            upload
            for upload in form.getlist("photos")
            if isinstance(upload, UploadFile) and upload.filename
        ]
        if not uploads:
            return templates.TemplateResponse(
                request=request,
                name="manage_photos.html",
                context={"item": item, "error": "Please select a photograph."},
                status_code=422,
            )

        try:
            await add_photos(target, photos, item_id, uploads)
        except PhotoError as error:
            return templates.TemplateResponse(
                request=request,
                name="manage_photos.html",
                context={"item": item, "error": str(error)},
                status_code=400,
            )

        return RedirectResponse(
            _path_for(request, "manage_photos", item_id=item_id), status_code=303
        )

    @application.post(
        "/items/{item_id}/photos/{photo_id}",
        name="update_photo",
    )
    async def update_photo_route(
        request: Request, item_id: int, photo_id: int
    ) -> RedirectResponse:
        form = await request.form()
        action = str(form.get("action", "save"))
        caption = str(form.get("caption", "")).strip() or None
        if action not in {"save", "primary", "earlier", "later", "delete"}:
            raise HTTPException(status_code=400, detail="Unknown photo action")
        if not manage_photo(target, photos, item_id, photo_id, caption, action):
            raise HTTPException(status_code=404, detail="Photograph not found")
        return RedirectResponse(
            _path_for(request, "manage_photos", item_id=item_id), status_code=303
        )

    @application.post("/items/{item_id}/delete", name="delete_item")
    async def delete_item_route(request: Request, item_id: int) -> RedirectResponse:
        if not delete_catalog_item(target, photos, item_id):
            raise HTTPException(status_code=404, detail="Object not found")
        return RedirectResponse(_path_for(request, "index"), status_code=303)

    return application


app = create_app()
