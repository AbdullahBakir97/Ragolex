# Contributing

Thanks for considering a contribution!

## Quick path

1. Fork the repository.
2. Create a topic branch: `git checkout -b feature/short-name`.
3. Make your change. Keep diffs focused — small PRs land faster.
4. Run the local checks before opening the PR (the same ones CI runs):
   ```bash
   pip install -e ".[dev]"
   docker compose up -d db
   ruff check .
   pytest
   ```
5. Open a pull request describing **what** changed and **why**.

## Architecture rules

The layers and their allowed dependencies are described in
[docs/architecture.md](../docs/architecture.md) and enforced by
`tests/test_architecture.py`. In practice:

- Keep routes thin: validate input with the schemas, call a service, return
  a response model.
- Never import FastAPI or Starlette outside `ragolex.api`.
- Report failures by raising an `AppError` subclass from `core/errors.py`;
  don't build error responses by hand. A new kind of failure gets its own
  subclass with its signal and HTTP status.
- Receive collaborators through the constructor; wire them in
  `api/dependencies.py`.
- Services talk to the database only through the interfaces in
  `domain/repositories.py`; add a method there (and to
  `persistence/repositories.py` and `tests/fakes.py`) rather than
  importing SQLAlchemy in a service.
- Services get embeddings only through the `Embedder` interface in
  `domain/embedder.py`, and generated text only through the `LLM`
  interface in `domain/llm.py`; only `ragolex.embeddings` and
  `ragolex.llm` may import a provider SDK. Tests use `FakeEmbedder` and
  `FakeLLM` from `tests/fakes.py` and never call a real provider.
- Change the schema only with a migration: edit `persistence/tables.py`,
  run `alembic revision --autogenerate -m "..."`, review the result, and
  commit both. The test suite fails if they disagree.
- Give every service and loader unit tests, plus an API test for each new
  endpoint or response.

## Style

- Keep code readable; use clear names over clever ones.
- Match the file's surrounding conventions.
- Keep commit messages concise, in the imperative mood
  (e.g. `Add export option`, not `added export option`).

## Reporting bugs

Open an issue with:
- A short title describing the problem.
- Steps to reproduce.
- What you expected vs. what happened.
- Environment (OS, Python/Node version, browser).

## Asking questions

Open a discussion or issue with the `question` label.

## Code of conduct

By participating you agree to abide by the
[Code of Conduct](./CODE_OF_CONDUCT.md).

_Last updated: 2026-05-04 — maintained by [@AbdullahBakir97](https://github.com/AbdullahBakir97)_
