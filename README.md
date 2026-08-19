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

## Docker

The container stores the SQLite database and every original/display photograph
under `/data`. The Compose configuration maps that directory to the repository's
ignored `data/` directory, so rebuilding the image does not remove the catalogue.

Build and start the application:

```sh
docker compose up --build -d
```

Open <http://127.0.0.1:8000/>. Check the container status and logs with:

```sh
docker compose ps
docker compose logs -f
```

Stop the application without deleting its data:

```sh
docker compose down
```

Back up the complete `data/` directory to preserve the database and all original
photographs.

## Home Assistant OS

The repository is also a Home Assistant app repository. Published images support
Raspberry Pi 4 (`aarch64`) and local `amd64` Home Assistant installations.

To install it in Home Assistant:

1. Open **Settings → Apps → App store**.
2. Open the store menu, choose **Repositories**, and add
   `https://github.com/one-data-cookie/mm-collection`.
3. Install **M&M Collection**, start it, and enable **Show in sidebar**.

The catalogue is available only through Home Assistant Ingress. Home Assistant
handles authentication, and all catalogue data remains in the app's persistent
`/data` directory. Select the app in Home Assistant backups to include the
database and photographs.
