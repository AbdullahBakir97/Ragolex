# Ragolex API image. Build: docker build -t ragolex .
# Run the whole stack (database, migrations, API) with: docker compose up

# Build stage: install the app and its dependencies into a virtual
# environment, so the final image needs no build tools or pip cache.
FROM python:3.12-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# With tracing, so TRACING_ENABLED works in the image.
RUN pip install ".[tracing]"


# Final stage: the virtual environment and an unprivileged user.
FROM python:3.12-slim-bookworm

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FILES_DIR=/app/assets/files

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/assets/files \
    && chown -R app:app /app

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# Alembic reads its settings from pyproject.toml in the working directory.
COPY pyproject.toml ./
# The evaluation datasets, for `ragolex eval evals/handbook/v1`.
COPY evals ./evals

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]

# Settings come from the environment (see .env.example); DATABASE_URL must
# point at PostgreSQL with pgvector. Apply migrations first with:
#   docker run --rm --env-file .env ragolex alembic upgrade head
# The API logs each request itself, with its id, so uvicorn's access log is off.
CMD ["uvicorn", "ragolex.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
