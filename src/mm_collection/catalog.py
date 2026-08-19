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


async def _store_photo(
    connection,
    photo_directory: Path,
    item_id: int,
    upload: UploadFile,
    position: int,
    is_primary: bool,
) -> tuple[Path, Path]:
    """Write one original/display pair and insert its database record."""
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

    try:
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
                is_primary,
            ),
        )
    except Exception:
        original_path.unlink(missing_ok=True)
        display_path.unlink(missing_ok=True)
        raise

    return original_path, display_path


def _remove_paths(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _prune_empty_photo_directories(photo_directory: Path, item_id: int) -> None:
    item_directory = photo_directory / str(item_id)
    for directory in (item_directory / "originals", item_directory / "display"):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        item_directory.rmdir()
    except OSError:
        pass


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
                await _store_photo(
                    connection,
                    photo_directory,
                    item_id,
                    upload,
                    position,
                    position == 0,
                )

        return item_id
    except Exception:
        if item_directory is not None and item_directory_created:
            shutil.rmtree(item_directory, ignore_errors=True)
        raise


async def add_photos(
    database: Path,
    photo_directory: Path,
    item_id: int,
    uploads: list[UploadFile],
) -> bool:
    """Append photos to an item, cleaning up every new file after failure."""
    created_paths: list[Path] = []

    try:
        with connect(database) as connection:
            exists = connection.execute(
                "SELECT 1 FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if exists is None:
                return False

            stats = connection.execute(
                """
                SELECT count(*) AS photo_count, max(position) AS last_position
                FROM photos WHERE item_id = ?
                """,
                (item_id,),
            ).fetchone()
            photo_count = stats["photo_count"]
            next_position = (stats["last_position"] or 0) + (1 if photo_count else 0)

            item_directory = photo_directory / str(item_id)
            (item_directory / "originals").mkdir(parents=True, exist_ok=True)
            (item_directory / "display").mkdir(exist_ok=True)

            for offset, upload in enumerate(uploads):
                paths = await _store_photo(
                    connection,
                    photo_directory,
                    item_id,
                    upload,
                    next_position + offset,
                    photo_count == 0 and offset == 0,
                )
                created_paths.extend(paths)
    except Exception:
        _remove_paths(created_paths)
        _prune_empty_photo_directories(photo_directory, item_id)
        raise

    return True


def manage_photo(
    database: Path,
    photo_directory: Path,
    item_id: int,
    photo_id: int,
    caption: str | None,
    action: str,
) -> bool:
    """Update, move, make primary, or remove one item photograph."""
    deleted_paths: list[Path] = []

    with connect(database) as connection:
        photo = connection.execute(
            "SELECT * FROM photos WHERE id = ? AND item_id = ?",
            (photo_id, item_id),
        ).fetchone()
        if photo is None:
            return False

        if action != "delete":
            connection.execute(
                "UPDATE photos SET caption = ? WHERE id = ?",
                (caption, photo_id),
            )

        if action == "save":
            pass
        elif action == "primary":
            connection.execute(
                "UPDATE photos SET is_primary = 0 WHERE item_id = ?", (item_id,)
            )
            connection.execute(
                "UPDATE photos SET is_primary = 1 WHERE id = ?", (photo_id,)
            )
        elif action in {"earlier", "later"}:
            ordered = connection.execute(
                """
                SELECT id, position FROM photos
                WHERE item_id = ? ORDER BY position, id
                """,
                (item_id,),
            ).fetchall()
            current_index = next(
                index for index, row in enumerate(ordered) if row["id"] == photo_id
            )
            neighbor_index = current_index + (-1 if action == "earlier" else 1)
            if 0 <= neighbor_index < len(ordered):
                current = ordered[current_index]
                neighbor = ordered[neighbor_index]
                connection.execute(
                    "UPDATE photos SET position = ? WHERE id = ?",
                    (neighbor["position"], current["id"]),
                )
                connection.execute(
                    "UPDATE photos SET position = ? WHERE id = ?",
                    (current["position"], neighbor["id"]),
                )
        elif action == "delete":
            deleted_paths = [
                photo_directory / photo["original_path"],
                photo_directory / photo["display_path"],
            ]
            was_primary = bool(photo["is_primary"])
            connection.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
            remaining = connection.execute(
                """
                SELECT id FROM photos
                WHERE item_id = ? ORDER BY position, id
                """,
                (item_id,),
            ).fetchall()
            for position, row in enumerate(remaining):
                connection.execute(
                    "UPDATE photos SET position = ? WHERE id = ?",
                    (position, row["id"]),
                )
            if was_primary and remaining:
                connection.execute(
                    "UPDATE photos SET is_primary = 1 WHERE id = ?",
                    (remaining[0]["id"],),
                )
        else:
            raise ValueError("Unknown photo action")

    if deleted_paths:
        _remove_paths(deleted_paths)
        _prune_empty_photo_directories(photo_directory, item_id)
    return True


def delete_item(database: Path, photo_directory: Path, item_id: int) -> bool:
    """Remove an item record, its photo rows, and its complete photo directory."""
    with connect(database) as connection:
        result = connection.execute("DELETE FROM items WHERE id = ?", (item_id,))
    if result.rowcount != 1:
        return False

    shutil.rmtree(photo_directory / str(item_id), ignore_errors=True)
    return True
