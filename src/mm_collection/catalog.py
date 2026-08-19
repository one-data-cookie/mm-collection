"""Item creation and photograph processing."""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from starlette.datastructures import UploadFile

from .database import connect

register_heif_opener()

ITEM_FIELDS = (
    "title",
    "author",
    "date_created",
    "type",
    "date_acquired",
    "seller",
    "price",
    "story",
)
MAX_PHOTO_BYTES = 30 * 1024 * 1024
DISPLAY_MAXIMUM_SIZE = (1600, 1600)
ORIGINAL_EXTENSIONS = {
    "AVIF": ".avif",
    "HEIF": ".heic",
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


class PhotoError(ValueError):
    """A photograph cannot be safely accepted or processed."""


def _photo_format(contents: bytes, filename: str) -> str:
    try:
        with Image.open(BytesIO(contents)) as image:
            image_format = image.format
            image.verify()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise PhotoError(f'“{filename}” is not a readable image.') from error

    if image_format not in ORIGINAL_EXTENSIONS:
        raise PhotoError(f'“{filename}” uses an unsupported image format.')
    return image_format


def _make_display_photo(contents: bytes, destination: Path, filename: str) -> None:
    try:
        with Image.open(BytesIO(contents)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail(DISPLAY_MAXIMUM_SIZE, Image.Resampling.LANCZOS)

            if image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                flattened = Image.new("RGB", rgba.size, "white")
                flattened.paste(rgba, mask=rgba.getchannel("A"))
                image = flattened
            elif image.mode != "RGB":
                image = image.convert("RGB")

            image.save(destination, "JPEG", quality=85, optimize=True)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise PhotoError(f'“{filename}” could not be converted for display.') from error


async def _read_upload(upload: UploadFile) -> bytes:
    contents = await upload.read(MAX_PHOTO_BYTES + 1)
    if len(contents) > MAX_PHOTO_BYTES:
        raise PhotoError(f'“{upload.filename}” is larger than 30 MB.')
    if not contents:
        raise PhotoError(f'“{upload.filename}” is empty.')
    return contents


async def create_item(
    database: Path,
    photo_directory: Path,
    values: dict[str, str | None],
    uploads: list[UploadFile],
) -> int:
    """Create one item and all its photo files as a single logical operation."""
    item_directory: Path | None = None
    item_directory_created = False

    try:
        with connect(database) as connection:
            item_id = connection.execute(
                """
                INSERT INTO items(
                    title, author, date_created, type,
                    date_acquired, seller, price, story
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(values.get(field) for field in ITEM_FIELDS),
            ).lastrowid
            if item_id is None:
                raise RuntimeError("SQLite did not return an item identifier")

            if uploads:
                item_directory = photo_directory / str(item_id)
                originals_directory = item_directory / "originals"
                display_directory = item_directory / "display"
                originals_directory.mkdir(parents=True)
                item_directory_created = True
                display_directory.mkdir()

            for position, upload in enumerate(uploads):
                filename = upload.filename or "photograph"
                contents = await _read_upload(upload)
                image_format = _photo_format(contents, filename)
                identifier = uuid4().hex
                original_name = identifier + ORIGINAL_EXTENSIONS[image_format]
                display_name = identifier + ".jpg"
                original_relative = Path(str(item_id), "originals", original_name)
                display_relative = Path(str(item_id), "display", display_name)
                original_path = photo_directory / original_relative
                display_path = photo_directory / display_relative

                original_path.write_bytes(contents)
                _make_display_photo(contents, display_path, filename)
                connection.execute(
                    """
                    INSERT INTO photos(
                        item_id, original_path, display_path,
                        position, is_primary
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        original_relative.as_posix(),
                        display_relative.as_posix(),
                        position,
                        position == 0,
                    ),
                )

        return item_id
    except Exception:
        if item_directory is not None and item_directory_created:
            shutil.rmtree(item_directory, ignore_errors=True)
        raise
