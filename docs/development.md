# Development

## Setup

Install the runtime and dev dependencies from the repository root, and start PostgreSQL:

```bash
pip install -e ".[dev]"
docker compose up -d db
```

Run the same checks as CI:

```bash
ruff check .
mypy
pytest --cov
```

`mypy` checks the types of everything in `src/`, the bodies of untyped functions included; the repositories are typed as their interfaces, so a SQL repository that drifts from its interface fails here as well as in `tests/test_repository_contracts.py`. `pytest --cov` measures line and branch coverage and fails below 95% (`fail_under` in `pyproject.toml`); without `--cov`, tests run without measuring.

Tests use temporary directories, their own settings and the `ragolex_test` database, which they create on the same server when it is missing (set `TEST_DATABASE_URL` to use another one), so they need no `.env` file and never write to `assets/` or the development database. Embeddings and answers come from deterministic fakes, so the tests need no API key or network.

## Web app

The web interface in `frontend/` is a Vue 3 app written in TypeScript and built with Vite. During development it runs on its own dev server, which forwards `/api`, `/docs` and `/openapi.json` to the API at `http://localhost:8000` (set `API_URL` to use another address):

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, reloads on every change
npm run typecheck    # vue-tsc
npm test             # Vitest unit tests
npm run build        # type check, then the production build in dist/
```

See [Web app](web.md) for what it does and how it is built.

### End-to-end tests

`npm run e2e` drives the web app in Chromium against the real API and database. Playwright starts what they need (`frontend/playwright.config.ts`): `tools/fake_models.py`, a stand-in for the embedding and answer models, so no model account is needed; the API on port 8000, after migrating the database; and the web app on port 5173. The tests cover:

- creating a project and uploading a document until it is indexed, then reading its chunks;
- asking a question: the streamed answer, its source, the conversation's address, a rating and a follow-up; and a question the documents do not answer;
- searching, and adding a chat widget whose live preview answers;
- accessibility: [axe](https://github.com/dequelabs/axe-core) finds no WCAG 2.1 A or AA violation on any page, in the light and dark themes, at desktop and phone width (the tests tagged `@phone` run on a phone too), and no page is wider than the screen.

They need PostgreSQL with pgvector and a database for them, by default `mini_rag_e2e` on `localhost` (set `E2E_DATABASE_URL` for another), and a browser:

```bash
createdb -U mini_rag mini_rag_e2e    # once, or: docker compose exec db createdb -U mini_rag mini_rag_e2e
cd frontend
npx playwright install chromium      # once
npm run e2e                          # --ui to watch them, --headed to see the browser
```

Each test makes its own project with a unique name, so they run in parallel on one database and a second run needs no cleanup. Locally, servers already running on those ports are reused; in CI (the `e2e` job) they are started fresh, and a failed run keeps its report, traces and screenshots as an artifact.

`tools/fake_models.py` also serves a demo of the whole app without an account: run it, then start the API with `EMBEDDING_BASE_URL` and `LLM_BASE_URL` set to `http://127.0.0.1:9999/v1` and `ANSWER_MIN_SCORE=0.05`. Its answers quote the first matching sentence: predictable, not good.

## Docker

The `Dockerfile` builds the API image in two stages: the first installs the package and its dependencies into a virtual environment, the second copies only that environment into a slim Python image and runs as an unprivileged user (UID 10001). `compose.yaml` runs the image as the `app` service next to the database, with settings from `.env` and the database address and file storage path set for the stack; uploaded files live in the `files` volume. On every start the service applies any missing migrations, then starts the API.

`frontend/Dockerfile` builds the web app the same way: Node builds the static files, and an unprivileged nginx image serves them and forwards `/api`, `/docs` and `/openapi.json` to the `app` service. It is the `web` service in `compose.yaml`, on port 3000.

The API runs background jobs and sends webhooks itself (`JOB_WORKERS`). To run them apart, for example on a machine of their own, set `JOB_WORKERS=0` for the API and start `ragolex worker` (as many as you like) with the same database and files:

```bash
docker compose run --rm app ragolex worker --workers 4
```

```bash
docker compose up --build            # the whole stack, rebuilt after code changes
docker compose up -d db              # only the database, to run the API with uvicorn
docker compose logs -f app           # follow the API's logs
docker compose down                  # stop; add --volumes to delete the data too
```

CI builds the images and starts the stack on every push, checks `/api/v1/health` through the web app, an upload, the app's pages and API forwarding, and checks that neither the API nor the web app runs as root.

## Database migrations

The schema is managed with Alembic; the app never creates tables itself. Migrations live in `src/ragolex/persistence/migrations/`, and Alembic's settings are in `pyproject.toml`, so run these commands from the repository root:

```bash
alembic upgrade head                                  # apply all migrations
alembic downgrade -1                                  # undo the latest one
alembic revision --autogenerate -m "describe change"  # after changing persistence/tables.py
```

Review every generated migration before committing it. `tests/test_migrations.py` fails if the models and the migrations ever disagree.

The database needs the pgvector extension, version 0.8 or newer; the `pgvector/pgvector:pg16` image in `compose.yaml` has it, and migration `0002` enables it. The migrations create vectors of 1536 numbers; a database switches to another length for another embedding model with `ragolex resize-embeddings` (see [Changing the embedding model](configuration.md#changing-the-embedding-model)). Autogenerate compares against the migrations' 1536, so generate new migrations on a database that has not been resized.

**Upgrading a local database from before vector search:** `compose.yaml` used `postgres:16-alpine` before and now uses the Debian-based `pgvector/pgvector:pg16`. Text sorting rules differ between the two, so don't reuse the old data volume; recreate it, migrate, and upload your files again:

```bash
docker compose down -v            # deletes the local database volume
docker compose up -d db
alembic upgrade head
```

## Workflow

- Branch from `start-001`, the default branch, and keep each pull request to one topic.
- Every change comes with tests; CI runs `ruff check .`, `mypy` and `pytest --cov` (failing below 95% coverage) on Python 3.11 and 3.12 against PostgreSQL 16 with pgvector, type-checks, tests and builds the web app, and a pull request merges only when it passes.
- The API only grows within `/api/v1` ([API versioning](versioning.md)): CI compares `sdk/openapi.json` with the base branch's and fails on a breaking change. Run the same check locally with `python tools/api_compat.py <(git show origin/start-001:sdk/openapi.json) sdk/openapi.json`.
- The SDKs are generated from `sdk/openapi.json`: after changing the API, regenerate the schema and both SDKs (see [sdk/README.md](../sdk/README.md#after-changing-the-api)). CI fails when the schema or the generated code is out of date, and type-checks and tests both SDKs (the Python one on 3.10 and 3.13).
- CI also checks the dependencies for known vulnerabilities (`pip-audit` on the Python dependencies, `npm audit` on the web app's, development tools included) and the whole git history for committed secrets (`gitleaks`). A vulnerable dependency fails the build until it is upgraded; Dependabot proposes the upgrades.
- CI also measures retrieval with `ragolex eval` and a real embedding model, and fails when it gets worse than the baseline. A change that improves it updates the baseline in the same pull request; see [Evaluation](evaluation.md#baselines-and-ci).
- See [CONTRIBUTING.md](../.github/CONTRIBUTING.md) for the architecture rules and style.
