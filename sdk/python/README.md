# ragolex-client

A Python client for the [Ragolex](../../README.md) API: a method for every endpoint, with Pydantic models, in a sync and an asyncio client, generated from the API's OpenAPI schema. Python 3.10+; it needs `httpx` and `pydantic`.

```bash
pip install ragolex-client       # or, from this repository: pip install ./sdk/python
```

```python
from ragolex_client import AnswerDelta, AnswerDone, Ragolex

with Ragolex("https://rag.example.com", api_key="ragolex_…") as rag:
    # Upload a file (a path, bytes or a binary file) and wait until it is indexed.
    rag.add_document("handbook", "leave-policy.pdf", tags=["hr"])

    # Search, and ask: only files tagged hr.
    hits = rag.search_project("handbook", query="paid leave", top_k=5, filters={"tags": ["hr"]})
    answer = rag.ask_project("handbook", question="How many days of leave do I get?")
    print(answer.answer, [c.file_id for c in answer.citations])

    # Stream an answer as it is written.
    for event in rag.ask_stream("handbook", "And for part-time staff?"):
        if isinstance(event, AnswerDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, AnswerDone):
            print("\nSources:", [c.file_id for c in event.answer.citations])
```

`AsyncRagolex` has the same methods, to await (`async for` for `ask_stream`).

## Every endpoint

Each operation of the API is a method named after its `operationId`: `list_projects`, `list_files`, `set_file_tags`, `create_job`, `get_job`, `search_project`, `ask_project`, `create_conversation`, `create_source`, `create_webhook`, `create_widget`, `create_key`, `list_audit_events`… Path parameters come first; query parameters and body fields are keyword arguments. Results are the API's models, from `ragolex_client.models`, and files are `bytes`: `rag.export_tenant()` returns everything the tenant has as a ZIP archive (with an `admin` key).

```python
files = rag.list_files("handbook", tag="hr", limit=50)
rag.set_file_tags("handbook", files.items[0].file_id, tags=["hr", "policies"])
rag.update_widget("handbook", widget_id, welcome=None)   # None clears it; fields not given stay
```

Body fields you leave out are not sent, so the API's defaults apply; `None` is sent as `null`. Nested models can be given as dicts, and requests are checked against the API's models before they are sent.

## Errors

An error response raises `RagolexError`, with the API's `signal` (such as `project_not_found`), the HTTP `status`, the response `body` and, for rate limits, `retry_after` in seconds. A server that cannot be reached is `status` 0 and `signal` `network_error`.

## Beyond the generated methods

| Method | Does |
|---|---|
| `upload(project_id, file, filename=, content_type=, tags=)` | Uploads a path, bytes or a binary file; content the project has already returns `file_already_uploaded` |
| `wait_for_job(project_id, job_id, interval=, timeout=)` | Waits until a job succeeds; raises if it fails |
| `add_document(project_id, file, ...)` | Uploads, processes and waits |
| `ask_stream(project_id, question, ...)` | The answer as it is written: `AnswerDelta` events, then `AnswerDone` |

## Development

`models.py` and `_operations.py` are generated from [`../openapi.json`](../openapi.json) by `python generate.py` (no dependencies); `python generate.py --check` fails when they are out of date. `pip install -e ".[test]" && pytest` runs the tests.
