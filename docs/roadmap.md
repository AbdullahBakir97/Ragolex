# Roadmap

Ragolex is growing from a retrieval service into a complete, reusable RAG platform: one deployment that answers questions over any collection of documents, for any number of separate apps, sites, bots and agents.

Phases are delivered in order, each as reviewed, tested pull requests. A phase is done when its acceptance criteria pass in CI.

## Completed

| Step | Delivered | Pull request |
|---|---|---|
| 1 | Working uploads, path-traversal fix, real tests and CI | [#6](https://github.com/AbdullahBakir97/Ragolex/pull/6) |
| 2 | MIT license, README, current dependencies, Dependabot | [#7](https://github.com/AbdullahBakir97/Ragolex/pull/7) |
| 3 | Document processing with an exact-overlap text splitter | [#8](https://github.com/AbdullahBakir97/Ragolex/pull/8) |
| 4 | Layered architecture, correct status codes, logging | [#9](https://github.com/AbdullahBakir97/Ragolex/pull/9) |
| 5 | PostgreSQL storage, migrations, read endpoints, health check | [#14](https://github.com/AbdullahBakir97/Ragolex/pull/14) |
| 6 | Embeddings and vector search with pgvector | [#15](https://github.com/AbdullahBakir97/Ragolex/pull/15) |

## Planned

| Stage | Phases | Ends when |
|---|---|---|
| 1. Answer | 1 Answer generation, 2 Evaluation | Quality scores are recorded in the repository |
| 2. Reuse | 3 Platform, plus a first live deployment | A separate app uses Ragolex through an API key |
| 3. Automate | 4 Ingestion and automation, 5 Agents | Connected sources stay in sync without manual steps |
| 4. Improve | 6 Retrieval quality, 7 Study mode | Evaluation scores improve over the stage 1 baseline |
| 5. Harden | 8 Security, 9 Production, 10 Web app | New tenants can onboard themselves |

### Phase 1: Answer generation

- [x] `POST /api/v1/ask/{project_id}`: answers with citations (file, page, chunk) to the retrieved sources.
- [x] Streaming responses (Server-Sent Events).
- [x] An explicit "I don't know" when no source matches well enough.
- [x] Conversations with follow-up questions.
- [x] An `LLM` interface: OpenAI by default, any OpenAI-compatible server as an option.
- [x] Versioned prompts that treat document text as data, not instructions.
- [x] Token usage and cost recorded per request.

### Phase 2: Evaluation

- [x] A versioned test set of questions, expected sources and reference answers.
- [x] Retrieval metrics (hit rate, recall@k, MRR, and how the minimum score keeps answerable questions and rejects the others).
- [x] Answer metrics: answered and abstained, citation precision, and groundedness and correctness graded by a judge model (`ragolex eval --answers`).
- [x] A `ragolex eval` command with JSON reports.
- [x] Retrieval metrics checked on every pull request; changes that lower them fail CI.
- [x] Thumbs up/down feedback stored to grow the test set (`ragolex feedback-export`).

### Phase 3: Platform and white-label

- [x] Tenants with hashed, scoped, revocable API keys; strict data isolation between tenants.
- [x] Usage accounting, quotas and rate limits per tenant.
- [x] TypeScript and Python SDKs generated from the OpenAPI schema, checked in CI against the API.
- [x] An embeddable chat widget: one `<script>` tag, streaming answers, clickable citations; a name, colour, welcome text and allowed website origins per widget.
- [x] **White-label:** a logo for the widget; an assistant name and instructions per project; serving it all from your own domain (see [Operations](operations.md#your-own-domain)).
- [x] Several brands on one deployment: domains of a workspace's own, proven by a TXT record, serving its projects, sign-in and widgets ([API › Your own domains](api.md#your-own-domains)).
- [x] **Collections and tags:** tag files (at upload, by hand, or per website source), list them by tag, and limit search, answers, chat widgets and the MCP tools to some tags.
- [x] A [versioning policy](versioning.md) for `/api/v1`: the API only grows within it, CI fails on breaking changes, and deprecated endpoints announce their sunset in headers, at least six months ahead.

### Phase 4: Ingestion and automation

- [x] Background jobs for processing and indexing, with status, retries and progress.
- [x] Deleting files and projects everywhere at once; duplicate detection by content hash.
- [x] More formats: DOCX, Markdown and HTML, split by section.
- [x] OCR for scanned PDFs, with Tesseract or a vision model.
- [x] A website connector: crawled within its site and folder, obeying robots.txt, synced on a schedule, adding, replacing and removing pages.
- [x] RSS and Atom feeds, and GitHub repositories' documents, as sources synced like websites.
- [x] Notion and Google Drive sources, read through a workspace's sign-in to them (OAuth), with tokens refreshed and encrypted ([API › Notion and Google Drive](api.md#notion-and-google-drive)).
- [x] Signed outgoing webhooks for automation tools such as n8n, Make and Zapier.
- [x] Telegram, Slack and WhatsApp bots that answer from a project's documents, with sources and follow-up questions ([API › Chat bots](api.md#chat-bots-telegram-slack-and-whatsapp)).

### Phase 5: Agents

- [x] An MCP server with tools such as `search_knowledge`, `ask` and `list_projects`.
- [x] Tool-calling schemas for agent frameworks.
- [x] Agentic retrieval: multi-step search for complex questions, with step and cost limits.

### Phase 6: Retrieval quality

- [x] Hybrid search: PostgreSQL full-text search combined with vector search, merged by reciprocal rank fusion (hit rate 95.7% → 97.8% on `handbook/v1`).
- [x] A reranking step behind a `Reranker` interface (any server with the common `POST /rerank` API).
- [x] Filters by file, page, date and metadata; diversity in the top results (`max_per_file`).
- [x] Index and chunking parameters tuned from measured results (`ragolex tune`, a Tune workflow; see [Evaluation](evaluation.md#tuning-chunk-size-and-overlap)).

### Phase 7: Study mode

- [x] Summaries, flashcards and quizzes generated from documents, each item linked to its source page ([API › Study](api.md#study)).
- [x] Spaced-repetition review and export to Anki ([API › Decks](api.md#decks-and-spaced-repetition)).
- [x] Code-aware chunking for source repositories.

### Phase 8: Security and privacy

- [x] User accounts with roles per tenant: sign-up, sign-in, members, invitations and password resets, in the API ([API › User accounts](api.md#user-accounts)) and the web app ([Web app](web.md)).
- [x] File type checked from content, not the declared type; optional malware scanning with ClamAV.
- [x] Prompt-injection test cases.
- [x] Encryption at rest of uploaded files and webhook secrets, with key rotation (`ENCRYPTION_KEYS`, `ragolex encryption`).
- [x] Per-tenant export and deletion.
- [x] Dependency vulnerability scanning (`pip-audit`, `npm audit`) and secret scanning (`gitleaks`) in CI.
- [x] An audit log of administrative actions, with the key and request behind each (`GET /api/v1/audit`, `ragolex audit`).

### Phase 9: Production

- [x] A multi-stage, non-root Docker image and a full `compose.yaml` stack.
- [x] Automated deployments to staging and production, with automatic rollback ([Deployment](deployment.md)).
- [x] Structured logs (text or JSON) with a request id on every line and response, and the tenant.
- [x] Prometheus metrics: traffic by route, answers, tokens and cost, uploads, jobs and webhook deliveries ([Operations](operations.md#metrics)).
- [x] OpenTelemetry tracing of requests, database queries, searches, answers and jobs ([Operations](operations.md#tracing)).
- [x] Cost dashboards and budget alerts ([Operations](operations.md#budgets-and-cost)).
- [x] Backups with tested restores.
- [x] Type checking (`mypy`) and a coverage threshold (95% of lines and branches) in CI.

### Phase 10: Web app

- [x] A first web app: projects, document upload with progress, streamed answers with clickable citations, search and usage ([Web app](web.md)).
- [x] A chat interface with citations, conversation history and feedback.
- [x] Document management with upload, job status and website sources.
- [x] An admin dashboard for keys, usage, cost and evaluation scores ([Web app](web.md)).
- [x] Accessible, responsive, tested end to end with Playwright.

Ideas and feedback are welcome in [issues](https://github.com/AbdullahBakir97/Ragolex/issues).
