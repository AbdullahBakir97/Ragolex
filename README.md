# Ragolex

> A retrieval-augmented generation (RAG) service with a web app: upload documents, split them into chunks, index them with embeddings, and get answers that cite the passages they come from.

[![CI](https://github.com/AbdullahBakir97/Ragolex/actions/workflows/ci.yml/badge.svg)](https://github.com/AbdullahBakir97/Ragolex/actions/workflows/ci.yml) ![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?style=flat-square&logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white) ![Vue](https://img.shields.io/badge/Vue_3-4FC08D?style=flat-square&logo=vuedotjs&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](./LICENSE)

<p align="center">
  <img src="docs/media/how-an-answer-is-made.gif" width="880" alt="Animation of how Ragolex answers a question: a PDF is uploaded, read page by page, split into overlapping chunks, embedded as vectors and indexed; a question is then embedded, the nearest chunks above the minimum score become numbered sources, and the model answers from them with citations.">
</p>
<p align="center"><sub>How an answer is made, with sample data · <a href="docs/media/how-an-answer-is-made.mp4">MP4</a></sub></p>

## Features

- **Upload** PDF, Word (`.docx`), Markdown, HTML and text files into separate projects, with type checks and a size limit enforced while streaming.
- **Process** them into chunks that respect paragraphs, with exact overlap between chunks, page numbers for PDFs, and the section headings for Markdown, HTML and Word files.
- **Index** chunks as embeddings with OpenAI or any OpenAI-compatible server, such as Ollama, in background jobs with progress and retries, run by the API or by separate workers.
- **Search** by meaning and by words at once (hybrid search: pgvector and PostgreSQL full-text search, merged by rank fusion), best match first, with a similarity score.
- **Ask** questions and get answers with citations to the file, page or section, and chunk, streamed as they are written if you like, or an explicit "no answer" when the documents don't say.
- **Follow up** in conversations: a follow-up question is rewritten into a standalone one before searching, and the questions and answers are kept, with thumbs up or down on each answer.
- **Track** the tokens and cost of every answer, per answer and per project.
- **Embed a chat widget** in any website with one `<script>` tag: streamed answers with clickable citations, in the site's colour and with its logo, allowed only on the websites you list, without API keys in the page. Give each project's assistant a name and instructions on tone and style; it still answers only from the documents.
- **Build on it** with the [TypeScript and Python SDKs](sdk/README.md), generated from the OpenAPI schema: every endpoint typed, streamed answers, uploads and jobs.
- **Connect agents** through a built-in MCP server (`/api/v1/mcp`) with `list_projects`, `search_knowledge` and `ask` tools, or the same tools as function-calling schemas.
- **Sync websites** into a project: their pages are crawled (within the site, obeying robots.txt), indexed and kept up to date on a schedule, with new, changed and removed pages handled.
- **Automate** with signed webhooks: uploads, deletions and finished jobs are sent to n8n, Make, Zapier or any URL, retried for a day until received.
- **Evaluate** retrieval with `ragolex eval` on a versioned dataset: hit rate, recall and MRR, checked in CI with a real embedding model so a change that makes search worse fails. With `--answers`, answers are graded too: citation precision, groundedness and correctness. Rated answers become new test cases with `ragolex feedback-export`.
- **Browse** projects, files and chunks through paged endpoints; check readiness with a health endpoint.
- **Operate** it with request ids on every log line (text or JSON) and response, and Prometheus metrics for traffic, answers, tokens, cost, jobs and webhooks.
- **Serve several apps** from one deployment: tenants keep their projects apart, and API keys with scopes (`read`, `write`, `ask`, `admin`) say what each app may do, within its own rate limit and monthly quotas, with an audit log of who changed what. Uploaded files and webhook secrets can be encrypted at rest, with key rotation.
- **Use it in the browser** with the web app: projects, drag-and-drop uploads, conversations with streamed answers and clickable sources, search and usage, in light and dark.

Better retrieval, hybrid search and reranking, measured by the evaluation, is next; see the [roadmap](docs/roadmap.md).

## Web app

<p align="center">
  <img src="docs/media/web-ask.png" width="880" alt="The Ask page of the web app: the project's conversations beside a question and a follow-up, each answered with numbered citations and its cited sources, the follow-up showing the standalone question it was searched with.">
</p>

Upload documents and ask questions in the browser: each file is uploaded, split and indexed as soon as it is dropped, answers stream in with their sources, and every source opens at its passage. It uses only the public API. See [Web app](docs/web.md).

## How it works

Documents are indexed once: uploaded, read, split into overlapping chunks, embedded and stored in PostgreSQL with pgvector. Every question is then embedded with the same model, the closest chunks above a minimum score become numbered sources, and the language model answers only from them, citing each one.

<p align="center">
  <img src="docs/media/live-trace.gif" width="880" alt="Animated trace of one run: the ingest steps (upload, extract text, split, embed, store) complete one after another, then the ask steps (question, embed query, vector search, rank, build prompt, generate, answer), with a timing chart and an event log.">
</p>
<p align="center"><sub>One run from upload to cited answer, with sample data · <a href="docs/media/live-trace.mp4">MP4</a></sub></p>

<p align="center">
  <img src="docs/media/system-overview.png" width="880" alt="System overview infographic: the five ingest steps and the seven ask steps around the shared index, key defaults (1,000-character chunks, 200 characters of overlap, 1,536-dimension vectors, 64 chunks per request, 5 sources per answer), and diagrams of chunking with overlap, search by meaning, the prompt and a cited answer.">
</p>

## Quick start

### With Docker

Requires only Docker. One command starts PostgreSQL with pgvector, applies the migrations, and serves the API and the web app:

```bash
git clone https://github.com/AbdullahBakir97/Ragolex.git
cd Ragolex
cp .env.example .env             # Windows: copy .env.example .env; then add your API key
docker compose up --build
```

Open **http://localhost:3000** for the web app. If a port is already in use, set another one in `.env`, e.g. `WEB_PORT=3001` (see [Docker ports](docs/configuration.md#docker-ports)).

### With Python

Requires Python 3.11+ and Docker for the database. Use this to work on the code: the API reloads on every change.

```bash
git clone https://github.com/AbdullahBakir97/Ragolex.git
cd Ragolex

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

cp .env.example .env             # Windows: copy .env.example .env
docker compose up -d db          # PostgreSQL 16 with pgvector on localhost:5432
alembic upgrade head             # create or update the database tables
uvicorn ragolex.main:app --reload

cd frontend && npm install && npm run dev   # optional: the web app on http://localhost:5173 (Node 22.12+)
```

Either way, **http://localhost:8000** shows the interactive API docs. Run commands from the repository root, where `.env` is read. Indexing, search and answers need `OPENAI_API_KEY` in `.env`, or OpenAI-compatible servers in `EMBEDDING_BASE_URL` and `LLM_BASE_URL`.

### Try it

```bash
curl -F "file=@notes.txt;type=text/plain" http://localhost:8000/api/v1/data/upload/demo
# {"signal": "file_uploaded_successfully", "file_id": "a16q20nzrtvj_notes.txt"}

curl -X POST http://localhost:8000/api/v1/data/process/demo \
  -H "Content-Type: application/json" -d '{"file_id": "a16q20nzrtvj_notes.txt"}'
curl -X POST http://localhost:8000/api/v1/index/demo

curl -X POST http://localhost:8000/api/v1/search/demo \
  -H "Content-Type: application/json" -d '{"query": "What do my notes say about overlap?"}'
curl -X POST http://localhost:8000/api/v1/ask/demo \
  -H "Content-Type: application/json" -d '{"question": "What do my notes say about overlap?"}'
```

## Documentation

| | |
|---|---|
| [Configuration](docs/configuration.md) | Every setting, with defaults |
| [API](docs/api.md) | Endpoints, requests, responses and errors |
| [SDKs](sdk/README.md) | The TypeScript and Python clients |
| [API versioning](docs/versioning.md) | What may change within `/api/v1`, and how endpoints are retired |
| [Architecture](docs/architecture.md) | Layers, rules and extension points |
| [Web app](docs/web.md) | Pages, how it is built, running it |
| [Evaluation](docs/evaluation.md) | Datasets, retrieval metrics and the CI check |
| [Operations](docs/operations.md) | Health, logs, metrics and the audit log |
| [Development](docs/development.md) | Tests, migrations and workflow |
| [Roadmap](docs/roadmap.md) | Completed and planned work |

## Tech stack

FastAPI · PostgreSQL 16 with pgvector · SQLAlchemy 2 (async) and Alembic · OpenAI-compatible embeddings and chat models · pypdf · Vue 3, TypeScript and Vite, served by nginx · pytest, ruff, mypy and Vitest in GitHub Actions

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](.github/CONTRIBUTING.md) and the [Code of Conduct](.github/CODE_OF_CONDUCT.md). To report a security issue, follow [SECURITY.md](.github/SECURITY.md).

## Author

**Abdullah Bakir** — [@AbdullahBakir97](https://github.com/AbdullahBakir97)

Full-Stack Developer based in Germany - Python · Django · Vue · Nuxt.

## License

Released under the [MIT License](./LICENSE).
