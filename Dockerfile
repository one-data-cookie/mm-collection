FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MM_COLLECTION_DATA_DIR=/data

WORKDIR /app

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install . \
    && mkdir -p /data \
    && chown -R app:app /data

USER app

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["uvicorn", "mm_collection.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
