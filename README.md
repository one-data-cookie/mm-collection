# M&M Collection

A minimal local catalogue application built with FastAPI, Jinja2, and SQLite.

Objects can be added with multiple photographs. The original uploaded files are
preserved, while smaller JPEG copies are generated for browsing. The first
photograph is used as the object's primary image.

JPEG, PNG, WebP, HEIF/HEIC, and AVIF uploads up to 30 MB each are supported.
Existing objects and their metadata can be edited. Photographs can be added,
captioned, reordered, made primary, or removed. Object and photograph deletion
also removes the corresponding local files.

## Requirements

- Python 3.11 or newer

## Local development

Create a virtual environment, install the project, and start the development server:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn mm_collection.main:app --reload
```

Open <http://127.0.0.1:8000/>. On first startup the application creates
`data/collection.sqlite` and applies all pending database migrations.
Uploaded photographs are stored beneath `data/photos/<item-id>/`.

To keep runtime data elsewhere, set `MM_COLLECTION_DATA_DIR`:

```sh
MM_COLLECTION_DATA_DIR=/path/to/data uvicorn mm_collection.main:app --reload
```

Run the test suite with:

```sh
pytest
```
