# API

All endpoints are under `/api/v1` (only `/` sits outside it, redirecting to `/docs`). The interactive reference, generated from the code, is at `/docs` on a running server (and the schema at `/openapi.json`, also kept in [`sdk/openapi.json`](../sdk/openapi.json)). Each operation's `operationId` is the name of its route function, such as `upload_data` or `search_project`.

**Versions:** within `/api/v1` the API only grows: nothing a client relies on is removed or changed, and anything retired is announced at least six months ahead. See [API versioning](versioning.md) for the promise and what clients must do.

**SDKs:** a [TypeScript](../sdk/typescript/README.md) and a [Python](../sdk/python/README.md) client are generated from the schema: every endpoint, typed, with uploads, streamed answers and background jobs as methods. See [sdk/](../sdk/README.md).

Every error response has the form `{"signal": "<name>"}` with a matching HTTP status; validation errors (`422`) list the fields that failed. An unexpected failure is `500` `{"signal": "internal_error", "request_id": "…"}`.

Every response carries an `X-Request-ID` header, which the server's log lines for that request carry too: quote it when reporting a problem. A client, or a proxy in front of the API, may send its own `X-Request-ID` (up to 128 letters, digits and `._:-`) to follow a request across services; it is kept.

## Authentication and tenants

Every project belongs to a **tenant**: an organisation or app whose projects, files, answers, jobs and webhooks are invisible to every other tenant. Two tenants can each have a project called `docs`.

With `AUTH_ENABLED=false` (the default, for your own computer), no key is needed and every request acts for the tenant `default` with every scope. With `AUTH_ENABLED=true`, every endpoint except `/api/v1/` and `/api/v1/health` needs an API key, sent as `Authorization: Bearer <key>` or `X-API-Key: <key>`:

```bash
ragolex tenants create acme
ragolex keys create --tenant acme --name website --scope read --scope ask
curl -H "Authorization: Bearer ragolex_…" http://localhost:8000/api/v1/projects
```

A key belongs to one tenant and has one or more **scopes**:

| Scope | Allows |
|---|---|
| `read` | Listing and reading projects, files, chunks, usage, conversations, feedback and jobs; search |
| `write` | Uploading, processing, indexing and deleting; queuing and retrying jobs |
| `ask` | Asking questions, starting and deleting conversations, rating answers |
| `admin` | Managing the tenant's API keys and webhooks |

A key is shown once, when it is created; the server keeps only its SHA-256, and the first 12 characters (`prefix`) to recognise it in lists. Revoking a key stops it at once.

| Case | Status | Response |
|---|---|---|
| No key | `401` | `{"signal": "api_key_required"}` |
| Unknown or revoked key | `401` | `{"signal": "api_key_invalid"}` |
| The key lacks the route's scope | `403` | `{"signal": "api_key_scope_missing"}` |

`GET /api/v1/me` shows the tenant and scopes of the key used. With an `admin` key, a tenant manages its own keys:

```bash
curl -X POST http://localhost:8000/api/v1/keys -H "Authorization: Bearer ragolex_…" \
  -H "Content-Type: application/json" -d '{"name": "ci", "scopes": ["read"]}'
curl http://localhost:8000/api/v1/keys -H "Authorization: Bearer ragolex_…"
curl -X DELETE http://localhost:8000/api/v1/keys/<key id> -H "Authorization: Bearer ragolex_…"
```

The first key of a tenant comes from the command line (`ragolex keys create`), run where the database is reachable, e.g. `docker compose exec app ragolex keys create --tenant acme --name admin`. `ragolex keys list` and `ragolex keys revoke` work there too, `ragolex tenants list` lists tenants, and `ragolex tenants export` and `ragolex tenants delete` [export and delete](#export-and-delete-a-tenants-data) one. Projects that existed before tenants belong to `default`.

### User accounts

People sign in with an email and a password instead of an API key. A tenant is their **workspace**, and each member has a **role** there, which grants scopes as a key's do:

| Role | Scopes | For |
|---|---|---|
| `owner` | `read`, `write`, `ask`, `admin` | Whoever created the workspace |
| `admin` | `read`, `write`, `ask`, `admin` | Managing keys, webhooks and members |
| `editor` | `read`, `write`, `ask` | Uploading, changing and asking |
| `viewer` | `read`, `ask` | Searching and asking only |

With `AUTH_ENABLED=true` and `SIGNUP_ENABLED=true` (the default), anyone can sign up: the account gets a new workspace, which it owns. Signing up or in sets a session cookie, `ragolex_session`, sent with every later request to `/api`:

```bash
curl -c cookies.txt -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "ada@example.com", "password": "at least 10 characters", "name": "Ada", "workspace": "acme"}'
curl -b cookies.txt http://localhost:8000/api/v1/projects
```

| Endpoint | Does |
|---|---|
| `POST /api/v1/auth/signup` | Creates the account and its workspace, and signs in (`201`) |
| `POST /api/v1/auth/login` | Signs in with `email` and `password`, in the first of the user's workspaces |
| `GET /api/v1/auth/session` | The signed-in user, the workspace the session works in, and all of the user's workspaces |
| `PUT /api/v1/auth/session/workspace` | Works in another of the user's workspaces: `{"workspace": "zenith"}` |
| `POST /api/v1/auth/logout` | Ends the session and removes the cookie (`204`) |

How it is kept safe:

- **Passwords** have at least 10 characters, and only their Argon2id hash is stored. Email addresses are compared in lower case, so one address has one account.
- **Sign-in failures** answer the same `login_failed` for a wrong password and an unknown email. The 10th failure in a row locks the account for 15 minutes (`429` `account_locked`); a good sign-in starts the count again.
- **The session cookie** is `HttpOnly` (scripts cannot read it), `SameSite=Strict` (other sites cannot send it, which stops cross-site request forgery), `Secure` (HTTPS only, unless `SESSION_COOKIE_SECURE=false`) and only sent to `/api`. A session lasts `SESSION_DAYS` (30) days; the server keeps only the token's SHA-256.
- **A request with an API key** acts for the key, even when the browser also has a session cookie.

Workspace names are 2 to 64 lower-case letters, digits, `-` and `_`. `GET /api/v1/me` shows a signed-in user and their `role` too.

| Case | Status | Response |
|---|---|---|
| `AUTH_ENABLED` is off | `409` | `{"signal": "accounts_disabled"}` |
| `SIGNUP_ENABLED` is off | `403` | `{"signal": "signup_disabled"}` |
| The email has an account, or the workspace name is taken | `409` | `{"signal": "email_taken"}`, `{"signal": "workspace_taken"}` |
| Wrong email or password | `401` | `{"signal": "login_failed"}` |
| Too many failures in a row | `429` | `{"signal": "account_locked"}` |
| No session, or it expired, or the user left the workspace | `401` | `{"signal": "session_required"}` |
| Not a member of that workspace (or of any) | `404` | `{"signal": "workspace_not_found"}` |

With sign-up off, accounts are added from the command line or by [invitation](#members-and-invitations). A new account asks for its password; an existing one keeps it and gets the role:

```bash
docker compose exec app ragolex users add ada@example.com --tenant acme --role owner --name "Ada Lovelace"
```

### Members and invitations

A workspace's owners and admins (and API keys with the `admin` scope) manage its members. Only a signed-in **owner** makes someone an owner, or changes or removes an owner, and a workspace always keeps one owner (`409` `last_owner`).

| Endpoint | Does |
|---|---|
| `GET /api/v1/members` | The members, by email, with their role, when they joined and last signed in |
| `PUT /api/v1/members/{user_id}` | Changes a member's role: `{"role": "editor"}`. Their sessions get it with their next request |
| `DELETE /api/v1/members/{user_id}` | Removes a member (`204`): the account stays, its sessions in the workspace end at once |
| `POST /api/v1/invitations` | Invites an email with a role: `{"email": "grace@example.com", "role": "editor"}` (`201`) |
| `GET /api/v1/invitations` | Invitations not accepted yet, newest first (expired ones too) |
| `DELETE /api/v1/invitations/{invitation_id}` | Revokes an invitation: its link stops working (`204`) |

Inviting answers with a `link` to send, shown only then, such as `http://localhost:3000/invite#Xq2v…`; with `SMTP_HOST` set it is emailed too (`"emailed": true`). Links start with `APP_URL`, even for a workspace with [its own domain](#your-own-domains), as password reset links do: a domain may later pass to someone else. The link works once, for a week, and only for the email invited; inviting the address again replaces it. The web app opens it, or a client does it with the token after `#`:

| Endpoint | Does |
|---|---|
| `POST /api/v1/auth/invitation` | What the link offers: `{"token": "…"}` → the workspace, role, who invited, and `has_account` |
| `POST /api/v1/auth/invitation/accept` | Joins the workspace and works in it. Signed in, as the invited email's account; not signed in, it makes that account from `name` and `password` and signs in. An email that has an account signs in first |

Accepting works with `SIGNUP_ENABLED` off: an invitation is the permission.

### Passwords

| Endpoint | Does |
|---|---|
| `POST /api/v1/auth/password-reset` | `{"email": "…"}`: emails a link to choose a new password. Always `202`, so it tells nobody which addresses have accounts; at most one link a minute per account |
| `POST /api/v1/auth/password-reset/confirm` | `{"token": "…", "password": "…"}`: sets the new password (`204`). Every session of the account ends, and a lock from failed sign-ins is lifted |
| `PUT /api/v1/auth/password` | `{"current_password": "…", "new_password": "…"}`: a signed-in user's new password (`204`). Their other sessions end. A wrong current password counts as a failed sign-in |

A reset link works once, for an hour, and a newer one replaces it. Without email (`SMTP_HOST` empty), operators make one for the account's owner:

```bash
docker compose exec app ragolex users reset-password ada@example.com
```

Invitation and reset tokens are sent in request bodies and kept in the link's fragment (after `#`), which browsers never send to a server, so they stay out of access logs; the server keeps only their SHA-256.

| Case | Status | Response |
|---|---|---|
| Not an owner, for owners' roles | `403` | `{"signal": "owner_required"}` |
| The last owner would leave or become less | `409` | `{"signal": "last_owner"}` |
| No such member, or invitation, in the workspace | `404` | `{"signal": "member_not_found"}`, `{"signal": "invitation_not_found"}` |
| Inviting a member | `409` | `{"signal": "already_member"}` |
| The invitation link is wrong, used, revoked or expired | `404` | `{"signal": "invitation_invalid"}` |
| Signed in as another email than the invited one | `403` | `{"signal": "invitation_for_someone_else"}` |
| No account yet, and no `name` or `password` for one | `422` | `{"signal": "account_details_required"}` |
| The reset link is wrong, used or expired | `404` | `{"signal": "password_reset_invalid"}` |
| The current password is wrong | `403` | `{"signal": "current_password_wrong"}` |

### Your own domains

A workspace can serve on domains of its own, such as `help.acme.com`: its web app, its API and its chat widgets, all from the same deployment. An `admin` key, or an owner's or admin's session, manages them:

| Endpoint | Does |
|---|---|
| `GET /api/v1/domains` | The workspace's domains, by name |
| `POST /api/v1/domains` | Adds one: `{"domain": "help.acme.com"}` (`201`), not yet verified |
| `POST /api/v1/domains/{domain_id}/verify` | Looks its TXT record up now; once found, the domain serves the workspace |
| `DELETE /api/v1/domains/{domain_id}` | Removes it (`204`): it stops serving at once |

Each domain lists the DNS `records` to add at its DNS provider: a TXT record, `_ragolex.help.acme.com` holding `ragolex-verification=…`, which proves the workspace controls the domain, and a CNAME to this server. Several workspaces may claim a domain, so a claim blocks nobody; only one can have it verified (`409` `domain_taken`).

On a verified domain, every request acts for its workspace:

- **Signing in** works in that workspace (`404` `workspace_not_found` for someone who is not a member), and **signing up** is off: people are invited. A session keeps its user's other workspaces for the server's own domain.
- **API keys** of other workspaces, and users who are not members, are refused with `403` `wrong_domain`; switching workspace is refused there too.
- **Chat widgets** answer only if they are the workspace's.
- With authentication off, requests act for the domain's workspace instead of `default`.

Two endpoints need no key: `GET /api/v1/site` says which workspace the request's domain serves, and whether people may sign up there (for the web app's sign-in page); `GET /api/v1/domains/allowed?domain=help.acme.com` answers `200` for a verified domain and `404` otherwise, for a proxy that gets certificates on demand (see [Operations › A domain per workspace](operations.md#a-domain-per-workspace)).

| Case | Status | Response |
|---|---|---|
| Not a domain, or the server's own (`APP_URL`) | `422` | `{"signal": "domain_invalid"}` |
| The workspace has it already | `409` | `{"signal": "domain_exists"}` |
| Its TXT record was not found | `409` | `{"signal": "domain_not_verified"}` |
| Another workspace has it verified | `409` | `{"signal": "domain_taken"}` |
| The DNS servers did not answer | `503` | `{"signal": "dns_lookup_failed"}` |
| A key or user of another workspace, on this one's domain | `403` | `{"signal": "wrong_domain"}` |

## Audit log

Administrative actions are recorded in their tenant's audit log, in the same transaction as the action itself, so a recorded action happened and every action that happened is recorded. `GET /api/v1/audit` (`admin` scope) lists them, most recent first; `?action=api_key` or `?action=widget.deleted` keeps the actions that start with it. Operators can read the same log with `ragolex audit --tenant <name>`.

```json
{"id": 12, "action": "api_key.created", "target": "0b5c3e8e-…",
 "details": {"name": "ci", "prefix": "ragolex_Xq2v…", "scopes": ["read"]},
 "actor": {"key_id": "8d1f…", "name": "ops laptop"}, "request_id": "3f2a…", "created_at": "2026-10-18T12:30:02Z"}
```

| Action | Target | Details |
|---|---|---|
| `tenant.created`, `tenant.limits_changed` | The tenant's name | The new limits (`changes`) |
| `member.added`, `member.role_changed`, `member.removed` | The member's email | Their `role` (and `previous_role`) |
| `invitation.created`, `invitation.revoked`, `invitation.accepted` | The invited email | The invitation's id and `role` |
| `domain.added`, `domain.verified`, `domain.removed` | The domain | |
| `bot.created`, `bot.updated`, `bot.deleted` | The bot's id | Project, kind, name and what changed; never its credentials |
| `connection.created`, `connection.renewed`, `connection.deleted` | The connection's id | Its kind and account; never its tokens |
| `api_key.created`, `api_key.revoked` | The key's id | Name, prefix and scopes, never the key |
| `webhook.created`, `webhook.deleted` | The webhook's id | Project, URL and events, never the secret |
| `widget.created`, `widget.updated`, `widget.deleted` | The widget's id | Project, and the settings set or changed |
| `project.assistant_updated` | The project's name | The assistant's name and instructions |
| `file.deleted`, `project.deleted` | The file's id, or the project's name | The project |
| `tenant.exported` | The tenant's name | How many projects, files, conversations, keys, members, invitations and audit events the archive holds |

`actor` is the API key that did it, with its name, and `user` the signed-in user, with their email; both are `null` for the server's operators: the command line, or requests while authentication is off. `request_id` matches the request's `X-Request-ID` and its log lines. Events are kept as long as the tenant; a revoked key still shows by name.

## Evaluation runs

Every `ragolex eval` run is recorded for a tenant (the default tenant, or `--tenant <name>`): its dataset, parameters and metrics. `GET /api/v1/evaluations` (`admin` scope) lists them, most recent first, `?dataset=handbook` for one dataset, to follow retrieval and answer quality as documents, models and settings change. See [Evaluation](evaluation.md).

```json
{"id": "7c1e…", "dataset": "handbook", "dataset_version": "v1", "cases": 53,
 "parameters": {"dataset": "handbook/v1", "embedding_model": "nomic-embed-text:v1.5", "search_mode": "hybrid",
                "reranker": null, "top_k": 5, "chunk_size": 1000, "overlap_size": 200, "min_score": 0.3, "…": "…"},
 "metrics": {"hit_rate": 0.957, "recall": 0.957, "mrr": 0.902, "above_min_score": 0.957, "rejected": 0.714, "…": "…"},
 "answer_metrics": null, "version": "0.1.0", "created_at": "2026-10-19T09:12:44Z"}
```

`answer_metrics` holds the answers' metrics (`answered`, `abstained`, `citation_precision`, `grounded`, `correct`) when the run answered the questions (`--answers`). Metrics compare only between runs with the same `parameters`.

## Export and delete a tenant's data

`GET /api/v1/export` (`admin` scope) returns everything the tenant has as one ZIP archive, for a backup, a move to another server, or a data request:

```bash
curl -H "Authorization: Bearer ragolex_…" -o acme.zip http://localhost:8000/api/v1/export
```

| In the archive | What it holds |
|---|---|
| `manifest.json` | The format and its version, the tenant, when it was made, how many of each thing it holds, and files the database lists that were no longer on disk |
| `tenant.json` | The tenant and its limits |
| `api_keys.json` | Each key's id, name, prefix, scopes and dates; never the key or its hash |
| `members.json` | Each member's email, name, role, and when they joined and last signed in; never passwords or sessions |
| `invitations.json` | Each open invitation's email, role and dates; never its link |
| `domains.json` | The workspace's own domains, and when each was verified |
| `connections.json` | Its Notion and Google Drive connections: kind, account, who connected it and when; never their tokens |
| `audit.jsonl` | The [audit log](#audit-log), oldest first, one event per line |
| `projects/<project>/project.json` | The project, and its [answer usage](#token-usage-and-cost) added up |
| `projects/<project>/files.json` | Each file's id, name, type, size, SHA-256, tags and date, and its path in the archive |
| `projects/<project>/files/<file_id>` | The files, exactly as uploaded |
| `projects/<project>/sources.json`, `widgets.json`, `webhooks.json`, `bots.json` | The project's sources, chat widgets, webhooks and bots; webhooks without their signing secret, bots without their credentials |
| `projects/<project>/conversations.jsonl` | Each conversation with its questions and answers, their citations and feedback |

Chunks and their embeddings are left out: processing the files again makes them, with whichever embedding model is used then. Each export is recorded in the audit log as `tenant.exported`.

Operators can do the same from the command line, where the database and the files are reachable, and delete a tenant:

```bash
ragolex tenants export acme acme.zip   # never overwrites a file
ragolex tenants delete acme            # says what would be deleted
ragolex tenants delete acme --yes      # deletes it
```

Deleting a tenant deletes each of its projects as `DELETE /api/v1/projects/{project_id}` does (the rows first, then the files on disk), then the tenant itself with its API keys, its rate-limit counters and its audit log. There is no undo, so export first. If it stops partway, running it again finishes the job. Other tenants are not touched, and the `default` tenant comes back, empty, the next time a request uses it.

## Rate limits and quotas

Each tenant can have four limits. The server's settings give the defaults (`RATE_LIMIT_PER_MINUTE`, `ANSWERS_PER_MONTH`, `STORAGE_MB_PER_TENANT`, `BUDGET_USD_PER_MONTH`; `0`, the default, is unlimited), and `ragolex tenants limits <tenant> --requests-per-minute N --answers-per-month N --storage-mb N --budget-usd USD` gives a tenant its own (a number, `0` for unlimited, or `default`).

| Limit | When it is reached | Response |
|---|---|---|
| Requests per minute | Counted per minute of the clock, across every API process; health checks are not counted | `429` `{"signal": "rate_limited"}` with `Retry-After` (seconds) |
| Answers per calendar month (UTC) | Asking (`/ask` and `/ask/.../stream`) is refused; search still works | `429` `{"signal": "answer_quota_exceeded"}` |
| Megabytes of stored files | An upload that would not fit is refused and removed; content already stored costs nothing | `413` `{"signal": "storage_quota_exceeded"}` |
| US dollars of answers per calendar month (UTC) | Once this month's answers cost the budget, asking is refused; search still works | `429` `{"signal": "budget_exceeded"}` |

Questions asked through a [chat widget](#chat-widget) count against the limits of the widget's tenant, like any other.

With a rate limit, every response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset` (Unix time when the minute ends). `GET /api/v1/usage` shows the tenant's usage this month against its limits:

```json
{"tenant": "acme", "period_start": "2026-10-01T00:00:00Z", "requests_per_minute": 600,
 "answers": {"used": 5, "limit": 50}, "storage_bytes": {"used": 1997, "limit": 10485760},
 "input_tokens": 4500, "output_tokens": 150, "cost_usd": 0.00204, "budget_usd": 25.0}
```

A `limit` or `budget_usd` of `null` is unlimited.

### Budgets and their alerts

A budget counts what answers cost, so it needs the model's prices (`LLM_INPUT_PRICE_PER_MILLION` and `LLM_OUTPUT_PRICE_PER_MILLION`); answers of unknown cost are not counted. An answer is allowed while this month's cost is under the budget, so the last one can take it a little over.

When the month's cost reaches 80% and then 100% of the budget, the tenant is alerted once each per month:

- a [`budget.alert`](#webhooks) event to every webhook of the tenant's projects that subscribes to it;
- a `budget.alert` event in the [audit log](#audit-log);
- a warning in the API's log;
- the `ragolex_budget_alerts_total` metric (see [Operations](operations.md#budgets-and-cost)).

### Cost history

`GET /api/v1/usage/history?days=30` (1 to 366 days, today included) gives the tenant's answers per day (UTC, days without answers included, oldest first), per project and per model (costliest first), for a cost dashboard. The web app's Usage page charts it.

```json
{"start": "2026-09-19T00:00:00Z",
 "days": [{"day": "2026-09-19", "answers": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}, …,
          {"day": "2026-10-18", "answers": 12, "input_tokens": 14160, "output_tokens": 492, "cost_usd": 0.0064512}],
 "projects": [{"project": "handbook", "answers": 12, "input_tokens": 14160, "output_tokens": 492, "cost_usd": 0.0064512}],
 "models": [{"model": "gpt-4o-mini", "answers": 9, "input_tokens": 14160, "output_tokens": 492, "cost_usd": 0.0064512},
            {"model": null, "answers": 3, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}]}
```

A `model` of `null` counts the questions that matched no source, for which no model was called.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Redirects to `/docs` |
| `GET` | `/api/v1/` | Welcome message with app name and version |
| `GET` | `/api/v1/health` | `200` `{"status": "ok", "database": "ok"}`, or `503` when the database is unreachable |
| `GET` | `/api/v1/me` | The tenant and scopes of the API key used, or the signed-in user with their role |
| `POST` | `/api/v1/auth/signup` | Create an account with a workspace of its own, and sign in |
| `POST` | `/api/v1/auth/login` | Sign in with an email and password |
| `POST` | `/api/v1/auth/logout` | Sign out |
| `GET` | `/api/v1/auth/session` | The signed-in user and their workspaces |
| `PUT` | `/api/v1/auth/session/workspace` | Work in another of the user's workspaces |
| `POST` | `/api/v1/auth/invitation` | What an invitation link offers (the token in the body) |
| `POST` | `/api/v1/auth/invitation/accept` | Accept an invitation, making the account if it has none, and work in its workspace |
| `POST` | `/api/v1/auth/password-reset` | Email a link to choose a new password (always `202`) |
| `POST` | `/api/v1/auth/password-reset/confirm` | Choose a new password with a reset link |
| `PUT` | `/api/v1/auth/password` | Change the signed-in user's password |
| `GET` | `/api/v1/members` | The workspace's members (`admin`) |
| `PUT` | `/api/v1/members/{user_id}` | Change a member's role (`admin`; owners' roles: an owner) |
| `DELETE` | `/api/v1/members/{user_id}` | Remove a member from the workspace (`admin`) |
| `GET` | `/api/v1/invitations` | Invitations not accepted yet (`admin`) |
| `POST` | `/api/v1/invitations` | Invite an email, returning the link once (`admin`) |
| `DELETE` | `/api/v1/invitations/{invitation_id}` | Revoke an invitation (`admin`) |
| `GET` | `/api/v1/domains` | The workspace's own domains (`admin`) |
| `POST` | `/api/v1/domains` | Add a domain; it serves once its TXT record is verified (`admin`) |
| `POST` | `/api/v1/domains/{domain_id}/verify` | Look the domain's TXT record up now (`admin`) |
| `DELETE` | `/api/v1/domains/{domain_id}` | Remove a domain (`admin`) |
| `GET` | `/api/v1/domains/allowed` | Whether a domain is a verified workspace's, for on-demand certificates (no key) |
| `GET` | `/api/v1/site` | Which workspace this domain serves, and whether people may sign up here (no key) |
| `GET` | `/api/v1/usage` | The tenant's usage this month, against its limits |
| `GET` | `/api/v1/usage/history` | The tenant's answers and their cost per day, project and model |
| `GET` | `/api/v1/audit` | The tenant's audit log, most recent first (paged; `?action=` filters; `admin`) |
| `GET` | `/api/v1/export` | Everything the tenant has as a ZIP archive (`admin`); see [Export](#export-and-delete-a-tenants-data) |
| `GET` | `/api/v1/evaluations` | The tenant's evaluation runs with their metrics, most recent first (paged; `?dataset=` filters; `admin`) |
| `POST` | `/api/v1/mcp` | Model Context Protocol server: the tools below, for agents |
| `GET` | `/api/v1/tools` | The same tools as function-calling schemas |
| `GET` | `/api/v1/keys` | The tenant's API keys (`admin`) |
| `POST` | `/api/v1/keys` | Create an API key; it is returned once (`admin`) |
| `DELETE` | `/api/v1/keys/{key_id}` | Revoke an API key (`admin`) |
| `POST` | `/api/v1/data/upload/{project_id}` | Upload a file into a project |
| `POST` | `/api/v1/data/process/{project_id}` | Split an uploaded file into chunks and store them |
| `POST` | `/api/v1/index/{project_id}` | Embed a project's chunks so they can be searched |
| `POST` | `/api/v1/projects/{project_id}/jobs` | Process and index a file in the background |
| `GET` | `/api/v1/projects/{project_id}/jobs` | List jobs, most recent first (paged; `?status=` filters) |
| `GET` | `/api/v1/projects/{project_id}/jobs/{job_id}` | A job's status and progress |
| `POST` | `/api/v1/projects/{project_id}/jobs/{job_id}/retry` | Queue a failed job again |
| `GET` | `/api/v1/connections` | The workspace's Notion and Google Drive connections, and which services this server can connect (`admin`) |
| `POST` | `/api/v1/connections` | Start connecting Notion or Google Drive: where to send the person to sign in (`admin`) |
| `DELETE` | `/api/v1/connections/{connection_id}` | Remove a connection no source uses (`admin`) |
| `POST` | `/api/v1/projects/{project_id}/sources` | Keep a website's pages, a feed, a GitHub repository, Notion pages or a Google Drive folder in the project, synced on a schedule (`write`) |
| `GET` | `/api/v1/projects/{project_id}/sources` | List the project's sources |
| `GET` | `/api/v1/projects/{project_id}/sources/{source_id}` | A source: pages, last and next sync, last error |
| `GET` | `/api/v1/projects/{project_id}/sources/{source_id}/pages` | The pages a source stored (paged) |
| `POST` | `/api/v1/projects/{project_id}/sources/{source_id}/sync` | Sync a source now (`write`) |
| `DELETE` | `/api/v1/projects/{project_id}/sources/{source_id}` | Remove a source and, unless `?keep_files=true`, the files it stored (`write`) |
| `POST` | `/api/v1/projects/{project_id}/webhooks` | Send the project's events to a URL; returns its signing secret once |
| `GET` | `/api/v1/projects/{project_id}/webhooks` | List the project's webhooks (paged) |
| `GET` | `/api/v1/projects/{project_id}/webhooks/{webhook_id}` | A webhook |
| `DELETE` | `/api/v1/projects/{project_id}/webhooks/{webhook_id}` | Stop sending to a webhook and forget its deliveries |
| `POST` | `/api/v1/projects/{project_id}/webhooks/{webhook_id}/ping` | Send a `ping` event |
| `GET` | `/api/v1/projects/{project_id}/webhooks/{webhook_id}/deliveries` | What was sent, most recent first (paged) |
| `POST` | `/api/v1/projects/{project_id}/widgets` | Add a chat widget for websites to embed (`admin`) |
| `GET` | `/api/v1/projects/{project_id}/widgets` | List the project's chat widgets (`admin`) |
| `GET` | `/api/v1/projects/{project_id}/widgets/{widget_id}` | A chat widget (`admin`) |
| `PATCH` | `/api/v1/projects/{project_id}/widgets/{widget_id}` | Change a chat widget's settings (`admin`) |
| `DELETE` | `/api/v1/projects/{project_id}/widgets/{widget_id}` | Remove a chat widget; its conversations stay (`admin`) |
| `POST` | `/api/v1/projects/{project_id}/bots` | Add a bot that answers in Telegram, Slack or WhatsApp (`admin`) |
| `GET` | `/api/v1/projects/{project_id}/bots` | List the project's bots (`admin`) |
| `GET` | `/api/v1/projects/{project_id}/bots/{bot_id}` | A bot (`admin`) |
| `PATCH` | `/api/v1/projects/{project_id}/bots/{bot_id}` | Change a bot (`admin`) |
| `DELETE` | `/api/v1/projects/{project_id}/bots/{bot_id}` | Remove a bot (`admin`) |
| `POST` | `/api/v1/bots/{bot_id}/webhook` | Where a chat app delivers a bot's messages (signed by the app, no key) |
| `GET` | `/api/v1/bots/{bot_id}/webhook` | WhatsApp checking the callback URL (no key) |
| `GET` | `/api/v1/widgets/{widget_id}` | What a widget shows, for its visitors (no key) |
| `POST` | `/api/v1/widgets/{widget_id}/ask` | Answer a visitor's question, streamed (no key) |
| `PUT` | `/api/v1/widgets/{widget_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | A visitor rates an answer (no key) |
| `POST` | `/api/v1/search/{project_id}` | Find the chunks that best match a question |
| `POST` | `/api/v1/ask/{project_id}` | Answer a question from the project's documents, with citations |
| `POST` | `/api/v1/ask/{project_id}/stream` | The same answer, streamed as it is written (Server-Sent Events) |
| `POST` | `/api/v1/study/{project_id}` | A summary, flashcards or a quiz from a document, each item linked to its source |
| `GET`, `POST` | `/api/v1/projects/{project_id}/decks` | List the project's decks of flashcards, or create one |
| `GET`, `DELETE` | `/api/v1/projects/{project_id}/decks/{deck_id}` | A deck with its counts of cards and of cards due, or delete it |
| `GET`, `POST` | `/api/v1/projects/{project_id}/decks/{deck_id}/cards` | A deck's cards in order, or add some |
| `GET` | `/api/v1/projects/{project_id}/decks/{deck_id}/review` | The cards due for review now |
| `POST` | `/api/v1/projects/{project_id}/decks/{deck_id}/cards/{card_id}/review` | Grade a review and schedule the card's next one |
| `GET` | `/api/v1/projects/{project_id}/decks/{deck_id}/anki` | The deck as a text file to import in Anki |
| `GET` | `/api/v1/projects` | List projects in name order (paged) |
| `GET` | `/api/v1/projects/{project_id}` | Project details with file, chunk and index counts |
| `GET` | `/api/v1/projects/{project_id}/usage` | Token usage and cost of the project's answers |
| `GET` | `/api/v1/projects/{project_id}/assistant` | The project's assistant: its name and instructions |
| `PATCH` | `/api/v1/projects/{project_id}/assistant` | Change the assistant's name and instructions (`admin`) |
| `GET` | `/api/v1/projects/{project_id}/files` | List a project's files (paged; `?tag=` filters) |
| `PUT` | `/api/v1/projects/{project_id}/files/{file_id}/tags` | Replace a file's tags (`write`) |
| `GET` | `/api/v1/projects/{project_id}/tags` | The project's tags, with how many files have each |
| `DELETE` | `/api/v1/projects/{project_id}` | Delete a project with all its files, chunks, answers and conversations |
| `GET` | `/api/v1/projects/{project_id}/files/{file_id}/chunks` | List a file's chunks (paged) |
| `DELETE` | `/api/v1/projects/{project_id}/files/{file_id}` | Delete a file with its chunks |
| `POST` | `/api/v1/projects/{project_id}/conversations` | Start a conversation |
| `GET` | `/api/v1/projects/{project_id}/conversations` | List conversations, most recent first (paged) |
| `GET` | `/api/v1/projects/{project_id}/conversations/{conversation_id}` | A conversation with its questions and answers |
| `DELETE` | `/api/v1/projects/{project_id}/conversations/{conversation_id}` | Delete a conversation and its messages |
| `PUT` | `/api/v1/projects/{project_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | Rate an answer thumbs up or down |
| `DELETE` | `/api/v1/projects/{project_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | Remove an answer's rating |
| `GET` | `/api/v1/projects/{project_id}/feedback` | Rated answers, most recently rated first (paged) |

## Upload a file

`project_id` may contain letters, digits, `_` and `-` (1–64 characters). Files are stored under `FILES_DIR/<project_id>/` (default `assets/files/`) with a random prefix, so uploads never overwrite each other. A missing or generic content type (`application/octet-stream`, as browsers often send for Markdown) is taken from the file's extension, and so is the type of any [source code](#source-code) file. Each file's SHA-256 is kept, and content the project already has is not stored again, whatever the file's name: the response then carries the existing file's id, so uploading the same files twice is safe.

The content must be of the file's type, whatever its name and declared type say: a PDF starts with `%PDF-` (within its first kilobyte), a Word document is a ZIP archive, and text is not binary (not a PDF or ZIP archive, and not more than a tenth control characters, as programs, images and UTF-16 text are). When `CLAMAV_URL` is set, every new file is also scanned for malware by ClamAV before it is kept; a file that cannot be scanned is refused rather than kept unscanned. A refused file leaves nothing behind.

```bash
curl -F "file=@notes.txt;type=text/plain" http://localhost:8000/api/v1/data/upload/demo1
curl -F "file=@handbook.pdf" -F "tags=handbook, hr" http://localhost:8000/api/v1/data/upload/demo1
```

The optional `tags` field gives the file [tags](#tags-and-collections), comma-separated. A file the project already has gains the tags it did not have.

```json
{"signal": "file_uploaded_successfully", "file_id": "a16q20nzrtvj_notes.txt"}
```

| Case | Status | Response |
|---|---|---|
| Upload saved | `200` | `{"signal": "file_uploaded_successfully", "file_id": "..."}` |
| The project has this content already | `200` | `{"signal": "file_already_uploaded", "file_id": "<the existing file>"}` |
| File type not in `FILE_ALLOWED_TYPES` | `415` | `{"signal": "file_type_not_supported"}` |
| File larger than `FILE_MAX_SIZE` | `413` | `{"signal": "file_size_exceeded"}` |
| Content not of the file's type, e.g. a program named `notes.txt` | `415` | `{"signal": "file_content_mismatch"}` |
| The malware scanner found malware | `422` | `{"signal": "file_infected"}` |
| The malware scanner is unreachable or could not scan the file | `503` | `{"signal": "malware_scan_failed"}` |
| A tag that is not one (see [tags](#tags-and-collections)), or more than 20 | `422` | `{"signal": "tag_invalid"}` |
| Invalid `project_id` | `422` | Validation error details |
| Storage failure on the server | `500` | `{"signal": "file_upload_failed"}` |

## Process a file into chunks

Send the `file_id` returned by the upload. Text is split on paragraphs first, then lines, then words, and a word is cut only if it alone is longer than a chunk. Paragraph breaks are respected: a chunk may hold several whole paragraphs, but part of a paragraph is never joined with another one. Every chunk after the first begins with up to `overlap_size` characters of the text just before it, starting at a word boundary, so context carries across chunk borders. Each chunk is at most `chunk_size` characters, overlap included, and is an exact slice of the document text.

```bash
curl -X POST http://localhost:8000/api/v1/data/process/demo1 \
  -H "Content-Type: application/json" \
  -d '{"file_id": "a16q20nzrtvj_notes.txt", "chunk_size": 1000, "overlap_size": 200}'
```

```json
{"signal": "processing_success", "file_id": "a16q20nzrtvj_notes.txt", "chunks_count": 1}
```

The chunks are stored in the database. Processing a file again (for example with other chunk settings) replaces its chunks in one transaction; if it fails, the previous chunks are kept.

| Field | Default | Rules |
|---|---|---|
| `file_id` | required | ID returned by the upload endpoint |
| `chunk_size` | `1000` | 1–100000 characters |
| `overlap_size` | `200` | 0 or more, smaller than `chunk_size` |

Supported files, chosen by extension:

| Extension | Read as | Extra chunk metadata |
|---|---|---|
| `.txt` | UTF-8 text | |
| `.pdf` | One document per page | `page`, from 1 |
| `.md`, `.markdown` | One document per section, keeping the Markdown; YAML front matter is left out | `section` |
| `.html`, `.htm` | The readable text, one document per section; scripts, styles, navigation, footers and forms are left out | `section`, `title` (the page's `<title>`) |
| `.docx` | One document per section; tables as one line per row, list items with `-` | `section` |
| Source code: `.py`, `.js`, `.mjs`, `.cjs`, `.jsx`, `.ts`, `.mts`, `.cts`, `.tsx`, `.go`, `.java`, `.kt`, `.kts`, `.cs`, `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx`, `.rs`, `.php`, `.swift` | One document per definition; see [Source code](#source-code) | `section` (the definition's name), `language` |

A section starts at a heading (in Word, a paragraph in a heading style) and its text starts with that heading. `section` is the path of headings above it, such as `"Setup > Install"`, so chunks never mix two sections and citations can say where they come from. Scanned PDFs are read with OCR when `OCR_ENGINE` is set ([Reading scanned PDFs](configuration.md#reading-scanned-pdfs)): their pages' chunks have `"ocr": true` in their metadata. The older `.doc` format is not read.

### Source code

A chunk holding the end of one function and the start of the next answers questions about neither, so source files are split where their definitions start:

- Each top-level function, class, interface, struct or other type is a document of its own. The comments, decorators and annotations right above it come with it, and its name is the `section`: `read`, `Reader`, `Point::Point`, or `Server.Start` for a Go method.
- A class longer than 1,500 characters is split again into its members, named `Reader.close`. The lines before the first member (the class line, its docstring, its fields) stay under the class's name.
- The lines between definitions, such as imports and constants, are documents without a section. One-line statements are never definitions of their own.
- Each document is then split into chunks like any text, so a long function still becomes several chunks, all with its `section`. Methods are dedented so they read as code of their own.

Python is read with Python's own parser. The other languages are read by following their brackets, which needs no grammar per language: C, C++, C#, Go, Java, JavaScript, Kotlin, PHP, Rust, Swift and TypeScript. A file that cannot be followed this way, such as one with a syntax error or a regular expression holding a lone bracket, is still read, as one document.

For code, the extension decides the content type whatever the upload declares (`text/x-python`, `text/x-typescript` and so on): browsers name code types inconsistently, sending a `.ts` file as `video/mp2t` for instance. The content must still be text.

| Case | Status | Response |
|---|---|---|
| Chunks created | `200` | `{"signal": "processing_success", ...}` |
| No such file in this project (or not uploaded through the API) | `404` | `{"signal": "file_not_found"}` |
| Extension is not one of the above | `415` | `{"signal": "file_type_not_supported"}` |
| No extractable text (e.g. a scanned PDF, without OCR) | `422` | `{"signal": "file_has_no_text"}` |
| A scanned page could not be read: the OCR engine failed or is not installed | `502` | `{"signal": "ocr_failed"}` |
| File could not be read | `422` | `{"signal": "processing_failed"}` |
| Invalid `file_id` or chunk settings | `422` | Validation error details |

## Read projects, files and chunks

```bash
curl http://localhost:8000/api/v1/projects
curl http://localhost:8000/api/v1/projects/demo1
curl "http://localhost:8000/api/v1/projects/demo1/files?offset=0&limit=20"
curl "http://localhost:8000/api/v1/projects/demo1/files/a16q20nzrtvj_notes.txt/chunks?limit=5"
```

```json
{"name": "demo1", "created_at": "2026-10-16T21:13:55Z", "files_count": 1, "chunks_count": 4, "embedded_chunks_count": 4}
```

```json
{
  "total": 4, "offset": 0, "limit": 5,
  "items": [
    {"chunk_index": 0, "text": "...", "metadata": {"source": "a16q20nzrtvj_notes.txt", "page": 1}}
  ]
}
```

Lists are paged with `offset` (default `0`) and `limit` (default `20`, at most `100`); `total` is the number of items overall. Projects are listed by name, with only `name` and `created_at`; a project exists once a file was uploaded into it. Files are listed in upload order, chunks by `chunk_index`. An unknown project returns `404` `{"signal": "project_not_found"}`, an unknown file `404` `{"signal": "file_not_found"}`.

## Tags and collections

Tags group a project's files into collections, such as `handbook`, `release-notes` or `v2`: searches, answers, chat widgets and the MCP tools can then use only the files with some tags. A file has up to 20 tags. A tag is 1–32 letters (of any script), digits and hyphens; tags are lowercased, with spaces and underscores turned into hyphens, so `Release Notes` and `release_notes` are both `release-notes`.

```bash
curl -X PUT http://localhost:8000/api/v1/projects/demo1/files/a16q20nzrtvj_notes.txt/tags \
  -H "Content-Type: application/json" -d '{"tags": ["handbook", "v2"]}'
curl "http://localhost:8000/api/v1/projects/demo1/files?tag=handbook"
curl http://localhost:8000/api/v1/projects/demo1/tags
```

```json
{"items": [{"tag": "handbook", "files": 12}, {"tag": "v2", "files": 3}]}
```

`PUT .../tags` replaces the file's tags (`[]` removes them) and returns the file, with its `tags`; every file listed carries its `tags`. Tags are given at upload too, and a [source](#sources-websites-feeds-github-notion-and-google-drive) gives its own to the pages it stores. Limit a search or an answer to files with any of some tags with the `tags` [filter](#filters); a [chat widget](#chat-widget) with tags answers its visitors only from those files. An invalid tag in a body is a validation error (`422`); in `?tag=` or an upload's `tags`, it is `422` `{"signal": "tag_invalid"}`.

## Delete files and projects

```bash
curl -X DELETE http://localhost:8000/api/v1/projects/demo1/files/a16q20nzrtvj_notes.txt
curl -X DELETE http://localhost:8000/api/v1/projects/demo1
```

Both return `204`. Deleting a file removes its chunks and embeddings from the database and the file from `FILES_DIR`; answers that cited it keep their copy of the cited text. Deleting a project removes everything in it: files, chunks, answers, conversations, ratings, jobs and webhooks, and its folder under `FILES_DIR`. The database is changed first, in one transaction; if the files on disk cannot be removed afterwards, a warning is logged and the request still succeeds, since nothing points at them any more. An unknown project or file returns `404`, as above.

## Index chunks for search

Indexing turns each chunk into an embedding: a vector that captures its meaning. It needs `OPENAI_API_KEY`, or an OpenAI-compatible server in `EMBEDDING_BASE_URL`.

```bash
curl -X POST http://localhost:8000/api/v1/index/demo1
curl -X POST http://localhost:8000/api/v1/index/demo1 \
  -H "Content-Type: application/json" -d '{"file_id": "a16q20nzrtvj_notes.txt"}'   # one file only
```

```json
{"signal": "indexing_success", "embedded_count": 4, "chunks_count": 4}
```

Only chunks without an embedding are sent, in batches of `EMBEDDING_BATCH_SIZE`, and each batch is saved on its own. So calling it again after a failure continues where it stopped, and after processing a file only its new chunks are embedded. Processing a file again removes its old embeddings with its old chunks, so index the project again afterwards. `embedded_chunks_count` in the project details shows how much of a project is indexed.

| Case | Status | Response |
|---|---|---|
| Done (also when there was nothing to do) | `200` | `{"signal": "indexing_success", ...}` |
| No such project or file | `404` | `{"signal": "project_not_found"}` / `{"signal": "file_not_found"}` |
| The embedding provider failed | `502` | `{"signal": "embedding_failed"}` |
| No API key and no `EMBEDDING_BASE_URL` | `503` | `{"signal": "embedding_not_configured"}` |

## Background jobs

Processing and indexing a large file can take minutes, longer than a request should wait. A job does both in the background: queue it with the same options as processing, then follow it.

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/jobs \
  -H "Content-Type: application/json" \
  -d '{"file_id": "a16q20nzrtvj_notes.txt", "chunk_size": 1000, "overlap_size": 200}'
curl http://localhost:8000/api/v1/projects/demo1/jobs/0b6f3c1e-8a52-4d47-9a0e-2f5d7c1b9e44
```

```json
{
  "id": "0b6f3c1e-8a52-4d47-9a0e-2f5d7c1b9e44", "file_id": "a16q20nzrtvj_notes.txt",
  "status": "running", "stage": "indexing", "progress": 0.5, "chunks_count": null,
  "attempts": 1, "max_attempts": 3, "chunk_size": 1000, "overlap_size": 200, "error": null,
  "created_at": "2026-10-18T05:44:07Z", "started_at": "2026-10-18T05:44:07Z", "finished_at": null
}
```

A job is `queued`, then `running` (`stage` is `processing`, then `indexing`, while `progress` goes from 0 to 1 as chunks are indexed), then `succeeded` with its `chunks_count`, or `failed` with the signal of what went wrong in `error`.

- **Retries.** When the embedding provider fails (`embedding_failed`), or something unexpected happens (`job_failed`), the job is queued again after 10 seconds, then 1 minute, then 5 minutes, until `max_attempts` (`JOB_MAX_ATTEMPTS`). Meanwhile it is `queued` with an `error`. A failure caused by the file, such as `file_has_no_text`, fails the job at once. So does `embedding_not_configured`: the chunks are stored, and indexing later finishes the work.
- **Retrying by hand.** `POST .../jobs/{job_id}/retry` queues a failed job again with all its attempts (`202`). For a job that has not failed, it returns `409` `{"signal": "job_not_failed"}`.
- **Workers.** The API runs `JOB_WORKERS` jobs at once (default 1). `ragolex worker` runs more in a process of its own, on any machine with the same database and `FILES_DIR`. Each job runs once, whatever the number of workers: a worker holds a job for 5 minutes and extends that as it goes. If a worker stops, its job is taken up again once that time runs out, which uses up an attempt; a worker that is shut down puts its job back at once. A job whose worker stopped on every attempt fails with `job_abandoned`.
- **Deletion.** Deleting the file or the project deletes its jobs.

| Case | Status | Response |
|---|---|---|
| Queued | `202` | The job |
| No such project, file or job | `404` | `{"signal": "project_not_found"}` / `{"signal": "file_not_found"}` / `{"signal": "job_not_found"}` |
| Options not valid, such as `overlap_size` not smaller than `chunk_size` | `422` | Validation error details |

## Sources: websites, feeds, GitHub, Notion and Google Drive

A source keeps a website's pages, a feed's entries, a GitHub repository's documents, Notion pages or a Google Drive folder's files in a project: they are fetched, stored as files and indexed, then synced again on a schedule. `kind` says which (default `website`); the rest of this section describes websites, with [feeds and repositories](#feeds-and-github-repositories) and [Notion and Google Drive](#notion-and-google-drive) below.

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/sources \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.example.com/guide/", "max_pages": 100, "sync_interval_hours": 24, "tags": ["docs"]}'
```

```json
{"id": "f77f0c0a-…", "kind": "website", "url": "https://docs.example.com/guide/", "max_pages": 100,
 "sync_interval_hours": 24, "pages_count": 0, "syncing": false, "last_synced_at": null,
 "next_sync_at": "2026-10-18T12:46:40Z", "last_error": null, "tags": ["docs"],
 "created_at": "2026-10-18T12:46:40Z"}
```

- **What is crawled.** The pages under the URL's folder (`https://docs.example.com/guide/intro` covers everything under `/guide/`), on the same host and port, found by following links from the URL, breadth first, up to `max_pages` (1–1000, default 50). Queries and fragments are dropped, so `page?x=1` and `page` are one page. HTML, PDF, text and Markdown pages are kept; images and other types are skipped, as are pages larger than `FILE_MAX_SIZE`.
- **Politely.** `robots.txt` is obeyed, its `Crawl-delay` too, and so are pages' `<meta name="robots">` tags (`noindex`, `nofollow`) and `rel="nofollow"` links. Requests are spaced by `CRAWLER_DELAY_SECONDS` and sent as `ragolex-crawler/1.0`.
- **Safely.** As for webhooks, only public addresses are crawled (`422` `{"signal": "source_url_not_allowed"}` when adding one on this server's network, and every host and redirect is checked again during a crawl), unless `CRAWLER_ALLOW_PRIVATE_URLS=true`. Redirects are followed only within the crawled folder.
- **Stored like uploads.** Each page goes through the upload checks (its type against its content, malware scanning, the storage quota, duplicates) and is stored as a file named by its URL (its `original_name` is the URL, so answers cite it), then processed and indexed by a background job. The source's optional `tags` (see [tags](#tags-and-collections)) are given to its pages.
- **Kept in sync.** The first sync starts at once, then every `sync_interval_hours` (0: only on `POST …/sync`). A new page is added, a changed page replaces its file, and an unchanged one is left alone. A page that is gone (no longer linked, or `404`) has its file deleted. A page that could not be fetched this time (a timeout, a `5xx`) keeps what it had, and when the site cannot be crawled at all, `last_error` says why and every page is kept. Files the project already had are never deleted by a sync.

Syncs run in the API's workers when `JOB_WORKERS` is above 0, and in `ragolex worker`; a source is held by one worker at a time. Deleting a source deletes the files its syncs created, unless `?keep_files=true`.

### Feeds and GitHub repositories

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/sources -H "Content-Type: application/json" \
  -d '{"kind": "feed", "url": "https://blog.example.com/feed.xml", "max_pages": 100}'
curl -X POST http://localhost:8000/api/v1/projects/demo1/sources -H "Content-Type: application/json" \
  -d '{"kind": "github", "url": "https://github.com/acme/handbook/tree/main/docs", "sync_interval_hours": 6}'
```

- **`feed`:** an RSS 2.0, RSS 1.0 or Atom feed. Each entry, up to `max_pages` from the newest, becomes a page at its own address, holding its title, date and content (the full content when the feed has it, its summary otherwise). Entries that drop off the feed are **kept**, since feeds list only their latest; delete them by hand, or the source, if they should go. The feed is fetched with the website crawler's safeguards: public addresses only (unless `CRAWLER_ALLOW_PRIVATE_URLS`), the size limit, and at most five redirects.
- **`github`:** `https://github.com/<owner>/<repo>`, at its default branch, or `.../tree/<branch or tag>/<folder>` for one branch and folder. Its Markdown, text, reStructuredText, HTML and PDF files are kept, top-level ones first, up to `max_pages`; hidden and vendored folders (`.github`, `node_modules`, `vendor`) are skipped. Each is a page at its `github.com/.../blob/...` address, so answers cite it, and files deleted from the repository are removed from the project. `GITHUB_TOKEN` reads private repositories and raises GitHub's rate limit from 60 requests an hour to 5000: a sync makes two requests, plus one per file. A repository that cannot be read (not found, rate limited) fails the sync with `last_error` and keeps every page.

Any other `kind`, or a `github` URL that is not a repository's, is refused with `422`.

### Notion and Google Drive

Notion pages and Google Drive files are private, so these sources read through a **connection**: an admin signs the workspace in to the service once, choosing what it may read, and its sources use that sign-in. The server needs an OAuth app with each service; see [Configuration › Notion and Google Drive](configuration.md#notion-and-google-drive).

```bash
# Start connecting: send the person to authorize_url.
curl -X POST http://localhost:8000/api/v1/connections -H "Content-Type: application/json" \
  -d '{"kind": "notion", "return_to": "http://localhost:3000/projects/demo1/documents"}'
# {"authorize_url": "https://api.notion.com/v1/oauth/authorize?client_id=…&state=…"}

# Once they come back with ?connected=con_…, add sources that read through it.
curl -X POST http://localhost:8000/api/v1/projects/demo1/sources -H "Content-Type: application/json" \
  -d '{"kind": "notion", "connection_id": "con_V1StGXR8_Z5jdHi6B-myT1", "sync_interval_hours": 6}'
curl -X POST http://localhost:8000/api/v1/projects/demo1/sources -H "Content-Type: application/json" \
  -d '{"kind": "google_drive", "connection_id": "con_…", "url": "https://drive.google.com/drive/folders/1AbC…"}'
```

- **Connecting.** `POST /api/v1/connections` (`admin`) with a `kind` returns an `authorize_url`, valid once for 15 minutes. At the service, the person signs in and allows reading (in Notion, they pick the pages to share); the service sends them to `/api/v1/connections/callback`, which keeps the connection and redirects to `return_to` with `?connected=<id>`, or with `?connection_error=<signal>`: `connection_denied` (they declined), `connection_failed` (the service refused the code) or `connection_request_invalid` (the link was used or expired). `return_to` must be on this server's web app or one of the workspace's [verified domains](#your-own-domains); otherwise they land on the Admin page. Open `authorize_url` in the browser that made the request: the response gives it a cookie that finishing the sign-in needs, so nobody can send someone else the link and have their account connected to another workspace (the web app does both). A service the server has no OAuth app with is `409` `{"signal": "connector_not_configured"}`.
- **Connections.** `GET /api/v1/connections` (`admin`) lists them, oldest first, with their `account` (the Notion workspace, or the Google account's email), who connected them, how many sources use each and `last_error`, and says which services the server can connect (`available`) and the `redirect_uri` to register. Tokens are stored encrypted when `ENCRYPTION_KEYS` is set and are never returned. Google's last an hour: they are refreshed before a sync that needs them, and a refused refresh (the access was revoked) fails the sync with `last_error`, also noted on the connection. Connecting the same account again renews that connection, and its sources carry on. `DELETE /api/v1/connections/{connection_id}` (`admin`) forgets it, once no source uses it (`409` `{"signal": "connection_in_use"}` otherwise); revoke the access at the service too.
- **`notion`:** with no `url`, every page the connection can read, most recently edited first; with a page's `url` (`https://www.notion.so/…-<id>`), that page and the pages and database entries under it. Each page becomes Markdown (`# Title`, then its headings, paragraphs, lists, to-dos, quotes, callouts, code, tables and equations, with bold, italics and links), at its `notion.so` address, so answers cite it. Pages no longer shared, or deleted, are removed from the project. Notion's rate limit is waited out.
- **`google_drive`:** with no `url`, all of My Drive; with a folder's `url` (`https://drive.google.com/drive/folders/<id>`, shared drives too), that folder and the folders in it. Google Docs are read as Markdown and Slides as text; PDF, Word, Markdown, HTML and text files as they are; spreadsheets, images and other files are skipped, as are files over `FILE_MAX_SIZE`. Each is a page at its Drive address, and files moved out, deleted or trashed are removed from the project.
- A `notion` or `google_drive` source needs a `connection_id` (`422` without one) and the `admin` scope (`403` `{"signal": "api_key_scope_missing"}` otherwise): a connection reads whatever its account can, such as all of a Google Drive, so only admins choose what it reads. A connection of the workspace's other service is `422` `{"signal": "connection_wrong_kind"}`, and an unknown one `404` `{"signal": "connection_not_found"}`. Other kinds take none.
- Sources that share a connection sync one at a time, which keeps a workspace within the service's rate limit.

## Webhooks

A webhook sends a project's events to a URL as they happen, for automation tools such as n8n, Make and Zapier.

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/webhooks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/hooks/ragolex", "events": ["job.succeeded", "job.failed"]}'
```

```json
{"id": "215a3491-5398-4b18-9048-d242b96fa592", "url": "https://example.com/hooks/ragolex",
 "events": ["job.failed", "job.succeeded"], "description": null, "created_at": "2026-10-18T05:56:09Z",
 "secret": "whsec_…"}
```

The `secret` is returned only by this call; keep it to check signatures. Adding a webhook to a project that has no files yet creates the project.

| Event | When | `data` |
|---|---|---|
| `file.uploaded` | A file was stored (not when the project had its content already) | `file_id`, `original_name`, `content_type`, `size_bytes` |
| `file.deleted` | A file was deleted | `file_id` |
| `job.succeeded` | A background job processed and indexed its file | `job_id`, `file_id`, `status`, `chunks_count`, `error`, `attempts` |
| `job.failed` | A background job failed, after its last attempt | The same, with the failure's signal in `error` |
| `source.synced` | A website source was synced | `source_id`, `url`, `added`, `updated`, `removed`, `unchanged`, and `error` when the site could not be crawled |
| `budget.alert` | The tenant's answers this month cost 80%, then 100%, of its [budget](#budgets-and-their-alerts); sent to every webhook of the tenant that subscribes to it, with the project of the answer that reached it | `threshold_percent`, `budget_usd`, `cost_usd`, `period_start` |
| `ping` | Sent by `POST .../ping`, whatever the webhook's events | `webhook_id` |

Each delivery is a `POST` with a JSON body:

```json
{"id": "6a0c…", "event": "job.succeeded", "created_at": "2026-10-18T05:56:12.408Z", "project": "demo1",
 "data": {"job_id": "9725833e-…", "file_id": "9jaqw1s4jucs_onboarding.md", "status": "succeeded",
          "chunks_count": 2, "error": null, "attempts": 1}}
```

and these headers:

| Header | Value |
|---|---|
| `X-Ragolex-Event` | The event |
| `X-Ragolex-Delivery` | The delivery's id, also the body's `id`; the same on every attempt, so a receiver can skip a delivery it already handled |
| `X-Ragolex-Signature` | `t=<unix time>,v1=<hex>`: an HMAC-SHA256, with the webhook's secret, of `<t>.<raw body>` |

To check a delivery, compute the HMAC from the raw body (before parsing it), compare it in constant time, and reject old timestamps:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(","))
    signed = parts["t"].encode() + b"." + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    fresh = abs(time.time() - int(parts["t"])) <= tolerance
    return fresh and hmac.compare_digest(expected, parts["v1"])
```

Events are queued in the same transaction as the change they report, so one is sent exactly when the change is saved. A delivery counts as delivered when the receiver answers `2xx` within `WEBHOOK_TIMEOUT_SECONDS`. Otherwise it is tried again after 10 seconds, 1 minute, 5 and 30 minutes, then 2, 6 and 12 hours: 8 attempts over about 20 hours. After that it is marked failed. Redirects are not followed. `GET .../deliveries` shows each delivery's `status` (`pending`, `delivered` or `failed`), `attempts`, the receiver's last `response_status`, and the last `error` in our words (`HTTP 500`, `timed out`, `could not connect`). Deliveries are sent by the API when `JOB_WORKERS` is above 0, and always by `ragolex worker`.

Webhooks reach only public addresses: an address on this server's network (`localhost`, private networks, the cloud metadata service at `169.254.169.254`) is refused, when the webhook is added (`422` `{"signal": "webhook_url_not_allowed"}`) and again whenever a delivery is sent, after resolving the host. For a receiver next to the API, such as n8n in the same compose stack, set `WEBHOOK_ALLOW_PRIVATE_URLS=true`.

## Tools for agents (MCP)

`POST /api/v1/mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server, so agents and assistants that speak MCP can use a tenant's projects as tools. It uses the Streamable HTTP transport without sessions: each POST carries one JSON-RPC message (`Content-Type: application/json`) and gets a JSON answer. Point an MCP client at `https://<your server>/api/v1/mcp`, with the API key in its headers (`Authorization: Bearer ragolex_…`) when authentication is on.

| Tool | Scope | Does |
|---|---|---|
| `list_projects` | `read` | Lists the tenant's projects, with files and indexed chunks |
| `list_files` | `read` | Lists a project's files, with their tags |
| `search_knowledge` | `read` | The best matching passages, each with file, page or section, and score |
| `ask` | `ask` | An answer from the documents with `[n]` citations and its sources; counts against the answer quota |

`search_knowledge` and `ask` take an optional `tags` list, to use only the files with at least one of those [tags](#tags-and-collections). `ask` also takes `research: true` for [research mode](#research-mode), for questions with several parts.

`tools/list` shows only the tools the key may use. A tool that fails (an unknown project, no embedding model, the quota reached) answers with `isError: true` and the signal, so the agent can change course; bad arguments are a JSON-RPC error (`-32602`). Requests count against the tenant's rate limit like any other. Requests from a web page on another site (an `Origin` header for another host) are refused.

```bash
curl -X POST http://localhost:8000/api/v1/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
       "params": {"name": "search_knowledge", "arguments": {"project": "demo1", "query": "overlap"}}}'
```

For agent frameworks that call functions instead, `GET /api/v1/tools` returns the same tools as `{"type": "function", "function": {"name", "description", "parameters"}}` schemas.

## Chat widget

A chat widget lets the visitors of a website ask a project's documents: a chat button in the page's corner opens a panel where answers stream in as they are written, with numbered citations that open the passage they cite, and thumbs up or down on each answer.

![A website with the chat widget open: a question, the answer with a numbered citation, and the cited passage opened below it](media/widget.png)

Add one with an `admin` key, or on the web app's Widget page:

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/widgets \
  -H "Content-Type: application/json" \
  -d '{"name": "Handbook assistant", "welcome": "Hi! Ask me anything about our handbook.",
       "accent": "#0f766e", "allowed_origins": ["https://example.com", "https://www.example.com"]}'
```

```json
{"id": "wgt_FZLBMlg8nrGS3z0ObXvgoQ", "project": "demo1", "name": "Handbook assistant",
 "welcome": "Hi! Ask me anything about our handbook.", "accent": "#0f766e",
 "allowed_origins": ["https://example.com", "https://www.example.com"], "created_at": "2026-10-18T11:21:15Z"}
```

Then add one tag to the website's pages, with the address of the web app, which serves the script:

```html
<script src="https://rag.example.com/widget.js" data-widget="wgt_FZLBMlg8nrGS3z0ObXvgoQ" async></script>
```

| Attribute | |
|---|---|
| `data-widget` | The widget's id (required) |
| `data-api` | Where the API is, when it is not where the script is served from |
| `data-position` | `left` puts the button in the bottom left corner instead of the right |
| `data-open` | `true` opens the panel when the page loads |

The page can also call `window.RagolexWidget.open()` and `.close()`. The widget lives in a shadow root, so the page's styles do not change it and its styles do not leak into the page. It keeps the visitor's conversation in the browser tab's session storage, so it carries on from page to page, and fills the screen on phones.

| Setting | |
|---|---|
| `name` | Shown in the widget's header (1–100 characters) |
| `welcome` | The first message visitors see (optional, up to 500 characters) |
| `accent` | The widget's colour as `#rrggbb` (default `#2563eb`); text on it is black or white, whichever reads better |
| `allowed_origins` | The websites that may use the widget, as origins: scheme, host and any port, like `https://example.com` (1–20; `*` for any website). Anything else, such as a URL with a path, is refused with `422` `{"signal": "widget_origin_invalid"}` |
| `tags` | Optional [tags](#tags-and-collections): visitors get answers only from the files with at least one of them (default `[]`, every file) |
| `logo_url` | Optional: an `https` URL of a square image shown in the widget's header (up to 2000 characters); anything else is refused with `422` |

`PATCH` changes only the settings it sends; pages that embed the widget pick the changes up when they are next loaded.

**What visitors can do.** The widget's id is public: it is in the page. With it, and no API key, a visitor can only see the widget's name, welcome, colour and logo (`GET /api/v1/widgets/{widget_id}`), ask its one project (`POST .../ask`), and rate the answers in their own conversations. Answers stream as Server-Sent Events like [`/ask/{project_id}/stream`](#streaming-the-answer), but the final `answer` event holds only what a visitor needs: the answer, its citations with the document's name, page, section and passage, the `conversation_id` to send with the next question, and the `message_id` to rate it. No file ids, scores, prompt versions or costs. A visitor can continue only conversations started in the same widget (`404` `{"signal": "conversation_not_found"}` otherwise). Widget requests count against the tenant's rate limit and answer quota, and their conversations appear with the project's others, marked with the widget's `widget_id`; removing the widget keeps them.

**Which websites.** Browsers send an `Origin` header with every request a page makes to another site, and a page on a website the widget does not allow is refused with `403` `{"signal": "origin_not_allowed"}`; the widget then stays hidden and says why in the browser console. The widget's routes answer any website's CORS requests (without cookies), so that refusal is readable. Pages on the API's own host, such as the web app's widget preview, may use every widget. The check keeps other websites from embedding your widget; it is not a password, since a client outside a browser can send any `Origin`, which is why a widget can do no more than its visitors could anyway.

## Chat bots: Telegram, Slack and WhatsApp

A bot answers in a chat app what people ask it, from the project's documents, as the chat widget does on a website: each answer ends with the sources its `[n]` markers cite, each chat (or Slack thread) keeps a conversation so follow-up questions work, and a bot with `tags` answers only from the files that have them. Bots need the `admin` scope to manage:

| Endpoint | Does |
|---|---|
| `POST /api/v1/projects/{project_id}/bots` | Adds a bot: `{"kind": "telegram", "name": "Help desk", "credentials": {"token": "…"}, "tags": []}` (`201`) |
| `GET /api/v1/projects/{project_id}/bots` | The project's bots, oldest first |
| `GET`, `PATCH`, `DELETE /api/v1/projects/{project_id}/bots/{bot_id}` | One bot; change its `name`, `tags`, `enabled` or `credentials`; remove it (its conversations stay) |

The chat app is asked to accept the credentials before the bot is saved, and they are stored encrypted (with `ENCRYPTION_KEYS`) and never returned. A bot shows its `account` in the app, its `webhook_url`, when it last answered, and why it last failed (`last_error`), such as a reply the app refused.

**Telegram.** Talk to [@BotFather](https://t.me/BotFather), send `/newbot`, and give the token it shows as `{"token": "…"}`. The bot sets its webhook with Telegram itself, which needs `APP_URL` to be an `https://` address Telegram can reach. People find the bot by its `@name`; `/start` says what it does and `/new` starts a new conversation. In groups, mention it or reply to it.

**Slack.** Create an app at [api.slack.com/apps](https://api.slack.com/apps). Under *OAuth & Permissions* give the bot the scopes `app_mentions:read`, `chat:write` and `im:history`, and install it to the workspace; under *Event Subscriptions* turn events on, paste the bot's `webhook_url` as the Request URL (Slack checks it at once), and subscribe to the bot events `app_mention` and `message.im`. Give `{"bot_token": "xoxb-…", "signing_secret": "…"}` (the signing secret is under *Basic Information*). People mention the bot in a channel, and it answers in a thread, or message it directly.

**WhatsApp.** In a [Meta app](https://developers.facebook.com/apps) with the WhatsApp product, take the phone number's id and an access token (a system user's permanent token for production) from *API Setup*, and the app secret from *App settings › Basic*: `{"access_token": "…", "phone_number_id": "…", "app_secret": "…"}`. Then, under *WhatsApp › Configuration*, set the Callback URL to the bot's `webhook_url` and the Verify token to its `verify_token`, and subscribe to `messages`.

Chat apps deliver each message to `POST /api/v1/bots/{bot_id}/webhook`, which needs no key: it checks the app's proof instead (Telegram's secret token, Slack's signature with its signing secret, no older than five minutes, and WhatsApp's signature with the app secret). It answers the app at once, since apps wait only seconds, and the reply follows when it is written. A message the app delivers again is answered once. Each answer counts against the workspace's [rate limit, quotas and budget](#rate-limits-and-quotas); over them, the bot says so in the chat. One chat may send a bot `BOT_CHAT_MESSAGES_PER_MINUTE` messages a minute (10 by default): past that, the bot asks it once to slow down, and ignores its messages until the minute is over, so one chat cannot spend the workspace's quota. Deliveries larger than 1 MB are refused (`413`) without being read whole. A bot's `webhook_url` starts with `APP_URL`, never a workspace's own domain, since messages carry the bot's secret.

| Case | Status | Response |
|---|---|---|
| Credentials missing, or refused by the chat app | `422` | `{"signal": "bot_credentials_invalid"}` |
| The chat app failed or could not be reached | `502` | `{"signal": "bot_platform_failed"}` |
| No such bot | `404` | `{"signal": "bot_not_found"}` |
| A delivery the app did not sign | `401` | `{"signal": "bot_signature_invalid"}` |

## Search

```bash
curl -X POST http://localhost:8000/api/v1/search/demo1 \
  -H "Content-Type: application/json" \
  -d '{"query": "How does the overlap work?", "top_k": 3}'
```

```json
{
  "signal": "search_success",
  "results": [
    {"file_id": "a16q20nzrtvj_notes.txt", "chunk_index": 2, "score": 0.83,
     "text": "...", "metadata": {"source": "a16q20nzrtvj_notes.txt", "page": 1}}
  ]
}
```

Results are the project's indexed chunks that best match the query, best first. With `SEARCH_MODE=hybrid` (the default), a chunk ranks higher both for being close in meaning and for containing the query's words, so exact terms such as names, codes and numbers are found even when the embedding misses them; with `vector`, only meaning counts. With a reranker configured (`RERANK_BASE_URL`), the best `RERANK_CANDIDATES` results are reordered by a reranking model, which reads the query and each passage together. Either way `score` is the cosine similarity between the query and the chunk (1 is the best match), which `min_score` and `ANSWER_MIN_SCORE` are compared with. Chunks that are not indexed yet are not found; a project without any returns an empty list.

| Field | Default | Rules |
|---|---|---|
| `query` | required | 1–2000 characters, not blank |
| `top_k` | `5` | 1–50 |
| `min_score` | none | -1 to 1; leaves out weaker results |
| `filters` | none | Narrows the chunks searched; see [Filters](#filters) |

Errors are the same as for indexing; `file_not_found` means a file named in `filters.file_ids` is not in the project.

### Filters

`filters` narrows search, and answers, to some of the project's chunks. Every field is optional, and the given ones all apply:

```bash
curl -X POST http://localhost:8000/api/v1/search/demo1 \
  -H "Content-Type: application/json" \
  -d '{"query": "refund window", "filters": {"file_ids": ["a16q20nzrtvj_policies.pdf"], "page_from": 3, "page_to": 8, "max_per_file": 2}}'
```

| Field | Rules | Keeps |
|---|---|---|
| `file_ids` | up to 100 of the project's file ids | Chunks of these files only |
| `tags` | up to 20 [tags](#tags-and-collections) | Chunks of files with at least one of these tags |
| `page_from`, `page_to` | 1 or more; `page_from` ≤ `page_to` | Chunks on these pages; chunks without a page (not from a PDF) are left out |
| `uploaded_after`, `uploaded_before` | ISO 8601 timestamps, after before before | Chunks of files uploaded in that time |
| `metadata` | up to 10 keys with string, number or boolean values | Chunks whose metadata has these values, e.g. `{"page": 3}` |
| `max_per_file` | 1–50 | At most this many results per file, so one long document does not fill all of them |

An invalid combination returns `422`.

## The project's assistant

Each project's answers come from its assistant, which can have a name and its owner's instructions on tone, style and what to say. They apply to every answer from the project: through the API, in the web app, and in its chat widgets.

```bash
curl -X PATCH http://localhost:8000/api/v1/projects/demo1/assistant \
  -H "Content-Type: application/json" \
  -d '{"name": "Ada", "instructions": "Be warm and brief. When the documents do not cover a question, suggest writing to hr@example.com."}'
```

```json
{"name": "Ada", "instructions": "Be warm and brief. When the documents do not cover a question, suggest writing to hr@example.com."}
```

`PATCH` changes only the fields it sends, and `null` or a blank value clears one; it needs the `admin` scope, and is recorded in the [audit log](operations.md#audit-log) as `project.assistant_updated`. `name` is up to 60 characters, `instructions` up to 4000.

The name and the instructions are given to the model after the [prompt's rules](architecture.md#prompts), which say that the rules come first: instructions can set the tone, the length, the format or what to mention, but not make the assistant answer beyond the documents, leave out citations, or follow text found in a document. Answers keep the prompt's `prompt_version`.

## Ask a question

Asking searches the project like the search endpoint, then has a language model answer from the best matching chunks only, citing each source with a `[n]` marker. It needs a language model as well as embeddings: `OPENAI_API_KEY`, or an OpenAI-compatible server in `LLM_BASE_URL`.

```bash
curl -X POST http://localhost:8000/api/v1/ask/demo1 \
  -H "Content-Type: application/json" \
  -d '{"question": "How does the overlap work?"}'
```

```json
{
  "signal": "answer_success",
  "answer": "Each chunk begins with up to overlap_size characters of the text before it [1], starting at a word boundary [2].",
  "citations": [
    {"number": 1, "file_id": "a16q20nzrtvj_notes.txt", "chunk_index": 2, "page": 1, "section": null, "score": 0.83, "text": "..."},
    {"number": 2, "file_id": "a16q20nzrtvj_notes.txt", "chunk_index": 5, "page": 2, "section": null, "score": 0.71, "text": "..."}
  ],
  "prompt_version": "answer-v1",
  "usage": {"input_tokens": 1180, "output_tokens": 41, "cost_usd": 0.0005376}
}
```

`citations` lists the sources the answer cites, in the order they are first cited; `number` matches the `[n]` marker in `answer`. `page` is set for PDFs and `null` otherwise. `prompt_version` names the prompt that produced the answer, so answers can be compared when prompts change.

When the documents do not answer the question, the response is `200` with signal `no_answer`, `answer` `null` and no citations, rather than a guess:

```json
{"signal": "no_answer", "answer": null, "citations": [], "prompt_version": "answer-v1",
 "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}}
```

That happens when no indexed chunk scores at least `min_score` (the model is then not called at all), or when the model finds no answer in the chunks it is given. Document text is passed to the model as quoted data, so instructions hidden in a document are not followed; see [Prompts](architecture.md#prompts).

| Field | Default | Rules |
|---|---|---|
| `question` | required | 1–2000 characters, not blank |
| `top_k` | `5` | 1–20; most chunks the answer may use |
| `min_score` | `ANSWER_MIN_SCORE` (`0.3`) | -1 to 1; chunks scoring below it are not used |
| `filters` | none | Answer only from the chunks these [filters](#filters) keep |
| `conversation_id` | none | A conversation of this project (see [Conversations](#conversations)); omit to ask on its own |
| `research` | `false` | [Research mode](#research-mode): the model plans the searches, for questions with several parts |
| `max_steps` | `3` | 1–5; in research mode, the most planning and review steps, capped by `RESEARCH_MAX_STEPS` |

| Case | Status | Response |
|---|---|---|
| Answered | `200` | `{"signal": "answer_success", ...}` |
| The documents do not answer the question | `200` | `{"signal": "no_answer", "answer": null, ...}` |
| No such project | `404` | `{"signal": "project_not_found"}` |
| No such conversation in this project | `404` | `{"signal": "conversation_not_found"}` |
| Invalid request | `422` | Validation error details |
| The embedding provider or the language model failed | `502` | `{"signal": "embedding_failed"}` / `{"signal": "llm_failed"}` |
| Embeddings or the language model are not configured | `503` | `{"signal": "embedding_not_configured"}` / `{"signal": "llm_not_configured"}` |

### Streaming the answer

`POST /api/v1/ask/{project_id}/stream` takes the same request and returns the same answer as [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events), so a client can show the text while the model writes it:

```bash
curl -N -X POST http://localhost:8000/api/v1/ask/demo1/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "How does the overlap work?"}'
```

```text
event: delta
data: {"text": "Each chunk begins with"}

event: delta
data: {"text": " up to overlap_size characters [1]."}

event: answer
data: {"signal": "answer_success", "answer": "Each chunk begins with up to overlap_size characters [1].", "citations": [...], "prompt_version": "answer-v1"}
```

| Event | Data | When |
|---|---|---|
| `delta` | `{"text": "..."}` | The next piece of the answer; joined in order, they give the full text |
| `answer` | The same JSON as `POST /api/v1/ask/{project_id}` | Once, at the end, with the citations |
| `error` | `{"signal": "llm_failed"}` | The language model failed partway; the stream ends |

A `no_answer` reply sends no `delta` events, only the final `answer` event: text that might still be the model's no-answer reply is held back until it is clearly an answer. Errors found before streaming starts, such as an unknown project or a missing model configuration, are ordinary JSON responses with the status codes in the table above.

### Research mode

One search finds the chunks closest to the whole question, which can miss a part of a question that asks several things ("How long is the refund window, and who pays for return shipping?"). With `"research": true`, the model plans the searches instead:

1. It splits the question into up to four searches, one for each thing it needs to find.
2. It reads the start of what they found and searches again for any part still missing, or stops when everything is covered.
3. Step 2 repeats until nothing is missing or `max_steps` steps (counting step 1) are taken.

The answer then uses the best chunk of each search in turn, up to `top_k`, so every part of the question gets its sources. A query is never searched twice, and a plan the model gets wrong falls back to searching the question itself. Filters, `min_score` and conversations work as usual; in a conversation, the rewritten follow-up is what gets planned.

```bash
curl -X POST http://localhost:8000/api/v1/ask/demo1 \
  -H "Content-Type: application/json" \
  -d '{"question": "How long is the refund window, and who pays for return shipping?", "research": true}'
```

The answer has the usual fields, plus `research`: the searches made, in order, with how many chunks each found (it is `null` without research mode).

```json
{
  "signal": "answer_success",
  "answer": "Refunds are accepted for 30 days after delivery [1]. Return shipping is free for damaged items [2].",
  "research": [
    {"query": "refund window", "results": 3},
    {"query": "who pays return shipping", "results": 2}
  ]
}
```

Research mode is slower and costs more: each step is one more model call, and each search one more embedding call. The steps' tokens are included in `usage`, and the whole answer counts once against the [answer quota](#rate-limits-and-quotas). The stream endpoint takes `research` too: the searches happen before the first `delta`, and the trail is in the final `answer` event. Agents get it through the MCP `ask` tool's `research` argument.

### Token usage and cost

Every answer reports what it used in `usage`: the prompt tokens the model read (`input_tokens`), the tokens it wrote (`output_tokens`) and the cost in US dollars (`cost_usd`). When no source matches, the model is not called and all three are `0`. Token counts are `null` when the provider does not report them, and `cost_usd` is `null` unless both `LLM_INPUT_PRICE_PER_MILLION` and `LLM_OUTPUT_PRICE_PER_MILLION` are set (see [Configuration](configuration.md)).

Each answer, streamed or not, is also recorded in the database: its project, model, prompt version, whether it found an answer, its tokens and its cost. This record never holds the question or the answer text; only a [conversation](#conversations) keeps those, when the question is asked in one. Answers that fail, or streams that end early, are not recorded.

```bash
curl http://localhost:8000/api/v1/projects/demo1/usage
```

```json
{"answers": 12, "answered": 9, "input_tokens": 14160, "output_tokens": 492, "cost_usd": 0.0064512, "unpriced_answers": 0}
```

`answered` counts the answers that were not `no_answer`. `cost_usd` adds up the answers with a known cost; `unpriced_answers` counts the model calls whose cost is unknown, which are left out of it. An unknown project returns `404` `{"signal": "project_not_found"}`.

### Conversations

A conversation lets a question follow on from the ones before it: "And on Fridays?" after "When do production deploys happen?". Start one, then pass its `id` as `conversation_id` when asking, streamed or not:

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/conversations
```

```json
{"id": "6a69d3de-2e61-455f-a678-428c8c520d70", "title": null,
 "created_at": "2026-10-18T10:00:00Z", "updated_at": "2026-10-18T10:00:00Z"}
```

```bash
curl -X POST http://localhost:8000/api/v1/ask/demo1 \
  -H "Content-Type: application/json" \
  -d '{"question": "And on Fridays?", "conversation_id": "6a69d3de-2e61-455f-a678-428c8c520d70"}'
```

A follow-up cannot be searched for on its own, so the model first rewrites it into a standalone question from the last three questions and answers (prompt `condense-v1`). The sources are searched with that question, and the answer is written with the earlier questions and answers in view. The response then carries `conversation_id`, and `search_question` when the question was rewritten:

```json
{"signal": "answer_success", "answer": "Never on Fridays after noon [1].", "citations": [...],
 "prompt_version": "answer-v1", "usage": {...},
 "conversation_id": "6a69d3de-2e61-455f-a678-428c8c520d70",
 "search_question": "Do production deploys happen on Fridays?"}
```

`usage` includes the rewriting. The first question of a conversation is asked as it is, and becomes its `title` (up to 80 characters); the body of `POST .../conversations` may set one instead: `{"title": "Deploys"}`.

Each answered question is added to the conversation with its answer, citations and `search_question`; failed answers and streams that end early are not. `GET .../conversations/{conversation_id}` returns them oldest first, and `GET .../conversations` lists conversations by when they were last answered in (`offset`, `limit`). An answer that found nothing is stored with `content` `null`:

```json
{"id": "6a69d3de-...", "title": "When do production deploys happen?", "created_at": "...", "updated_at": "...",
 "messages": [
   {"id": 41, "role": "user", "content": "When do production deploys happen?", "citations": [], "prompt_version": null, "search_question": null, "created_at": "..."},
   {"id": 42, "role": "assistant", "content": "On weekdays between 9:00 and 16:00 [1].", "citations": [{"number": 1, "file_id": "...", ...}], "prompt_version": "answer-v1", "search_question": null, "created_at": "...", "feedback": null}
 ]}
```

`DELETE .../conversations/{conversation_id}` removes a conversation and its messages (`204`). A conversation belongs to one project: using its id with another project, or an id that does not exist, returns `404` `{"signal": "conversation_not_found"}`; an id that is not a UUID returns `422`.

### Feedback

An answer in a conversation can be rated thumbs up or down, with an optional comment of up to 1000 characters. The answer's `message_id` is in the response to the question, and every message of `GET .../conversations/{conversation_id}` has its `id` and its `feedback`.

```bash
curl -X PUT http://localhost:8000/api/v1/projects/demo1/conversations/6a69d3de-2e61-455f-a678-428c8c520d70/messages/42/feedback \
  -H "Content-Type: application/json" \
  -d '{"rating": "down", "comment": "It should mention Friday mornings."}'
```

The response is the message with its new `feedback`; rating again replaces it, and `DELETE` on the same path removes it (`204`). Only answers take feedback: a question's id, or an id from another conversation, returns `404` `{"signal": "message_not_found"}`.

`GET /api/v1/projects/{project_id}/feedback` lists the rated answers with the question each one answered, most recently rated first, and how many of each rating the project has; `rating=up` or `rating=down` filters, `offset` and `limit` page:

```json
{"up": 12, "down": 3, "total": 15, "offset": 0, "limit": 20,
 "items": [{"conversation_id": "6a69d3de-...", "message_id": 42,
            "question": "And on a Friday afternoon?", "answer": "Not after noon [1].",
            "citations": [...],
            "feedback": {"rating": "down", "comment": "It should mention Friday mornings.", "created_at": "..."}}]}
```

`ragolex feedback-export` turns these into evaluation cases; see [Evaluation](evaluation.md#growing-the-test-set-from-feedback).

## Study

`POST /api/v1/study/{project_id}` turns one processed document into study material, for learning it rather than asking it questions:

| `kind` | Items |
|---|---|
| `summary` | Key points in the document's order: `text` |
| `flashcards` | A question or term on the `front`, its answer on the `back` |
| `quiz` | Multiple-choice questions: the `question`, four `choices`, the position of the right one in `answer` (from 0), and an `explanation` of why it is right |

```bash
curl -X POST http://localhost:8000/api/v1/study/demo1 \
  -H "Content-Type: application/json" \
  -d '{"file_id": "9jaqw1s4jucs_onboarding.pdf", "kind": "flashcards", "count": 10}'
```

```json
{"kind": "flashcards", "file_id": "9jaqw1s4jucs_onboarding.pdf", "original_name": "onboarding.pdf",
 "items": [{"front": "How many vacation days does an employee get?", "back": "25 days a year.", "sources": [3]}],
 "sources": [{"number": 3, "chunk_index": 7, "page": 2, "section": null, "text": "Every employee gets 25 days of paid vacation a year…"}],
 "prompt_version": "study-flashcards-v1",
 "usage": {"input_tokens": 3184, "output_tokens": 412, "cost_usd": 0.0007248},
 "passages": 12, "chunks": 12}
```

- **Linked to the source.** The document's chunks go to the model as numbered passages, and every item lists in `sources` the passages it comes from; `sources` in the response gives each one's chunk, page (PDFs) or section (Markdown, HTML, Word) and text. Items that cite no passage of the document are left out.
- **At most `count` items** (1–30, by default 10), fewer when the document has less to say; `items` is empty when the model wrote nothing usable.
- **Long documents.** Up to `STUDY_MAX_CHARACTERS` of the document goes to the model at once. A longer document is given in chunks spread evenly over it: `passages` says how many of its `chunks` were used.
- **Costs an answer.** It needs the `ask` scope, makes one model call and is recorded like an answer: in the project's usage, the tenant's answer quota and its costs. The material itself is not stored.
- **Errors.** A document that is not processed yet answers `409` `{"signal": "file_not_processed"}`; an unknown project or file `404`; a failing model `502` `{"signal": "llm_failed"}`.

### Decks and spaced repetition

Flashcards worth keeping go into a deck, to learn by spaced repetition: each card comes back for review just before it would be forgotten, less and less often as it is remembered.

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/decks \
  -H "Content-Type: application/json" \
  -d '{"name": "Onboarding", "cards": [{"front": "How many vacation days does an employee get?",
        "back": "25 days a year.", "file_id": "9jaqw1s4jucs_onboarding.pdf", "chunk_index": 7, "page": 2}]}'
```

```json
{"id": "5b0f6c3e-…", "name": "Onboarding", "cards": 1, "due": 1, "created_at": "2026-10-18T21:40:02Z"}
```

- **Cards.** Each has a `front` and a `back` (up to 2,000 characters), and optionally where it comes from: `file_id`, `chunk_index`, `page`, `section`, as `POST /study` gives them. `POST .../decks/{deck_id}/cards` adds more; a deck holds up to 2,000 cards (`409` `{"signal": "deck_full"}` beyond). A new card is due at once. Creating a deck in a project that has no files yet creates the project.
- **Reviewing.** `GET .../review?limit=20` gives the cards due now, the longest due first, each with the `intervals` (in days) each grade would give it. `POST .../cards/{card_id}/review` with `{"grade": "again" | "hard" | "good" | "easy"}` schedules the next review, as Anki does:

  | Grade | A new card | A card being learnt |
  |---|---|---|
  | `again` | In 10 minutes | In 10 minutes, starting over; a lapse |
  | `hard` | In 1 day | 1.2 × the last interval; the ease drops by 0.15 |
  | `good` | In 1 day, then 3 | The last interval × the ease (2.5 at first) |
  | `easy` | In 4 days | 1.3 × what `good` would give; the ease rises by 0.15 |

  Every card answered `hard` or better comes back at least a day later than last time, and within three years.
- **Anki.** `GET .../anki` downloads the deck as a text file for Anki's File > Import: one Basic note per card, in a deck of the same name, tagged `ragolex` and the project's name, with the document and page under each answer.
- **Scopes.** Reading decks and their cards needs `read`; creating, adding, reviewing and deleting need `write`. An unknown deck is `404` `{"signal": "deck_not_found"}`, a card of another deck `404` `{"signal": "card_not_found"}`.
