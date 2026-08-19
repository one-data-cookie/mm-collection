# M&M Collection

A minimal local catalogue application built with FastAPI, Jinja2, and SQLite.

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

To keep runtime data elsewhere, set `MM_COLLECTION_DATA_DIR`:

```sh
MM_COLLECTION_DATA_DIR=/path/to/data uvicorn mm_collection.main:app --reload
```

Run the test suite with:

```sh
pytest
```

