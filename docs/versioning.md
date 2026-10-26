# API versioning

Every endpoint is under `/api/v1`. This page is the promise that comes with that `v1`: what may change within it, how anything is retired, and what clients must do to keep working.

## Within `/api/v1`, the API only grows

A client written against `/api/v1` keeps working with every later server. Changes within `v1` are only additions:

| Allowed | Never, within `v1` |
|---|---|
| New endpoints | Removing an endpoint, or changing its path or method |
| New optional query parameters and request fields | A new required parameter or field, or making an optional one required |
| Accepting more: longer text, wider ranges, new enum values in requests | Accepting less: shorter limits, narrower ranges, a stricter pattern, removing an accepted value |
| New fields in responses | Removing a response field, or letting it be missing or null where it never was |
| New values of an enumeration in responses, such as a new `signal` or job `stage` | Changing a field's type, or the success status of an endpoint |
| New error responses with their own `signal` | Changing what an existing `signal` means |

CI enforces the right-hand column: on every pull request, `tools/api_compat.py` compares the API's schema (`sdk/openapi.json`, which a test keeps equal to the code's) with the base branch's, and fails on any breaking change. The [SDKs](../sdk/README.md) are generated from the same schema.

## What clients must do

To keep working as the API grows, a client:

- **ignores fields it does not know** in responses, rather than failing on them;
- **treats enumerations in responses as open:** an unknown `signal`, status or stage is handled like an unexpected one, not as a crash (the SDKs read them as strings);
- **acts on the HTTP status first**, and on `signal` for the reason, since new error signals may appear;
- **sends only what it means to set:** fields left out get the server's defaults, which may improve over time.

The SDKs do all of this.

## Retiring an endpoint

An endpoint, parameter or field that should go away is deprecated first, and keeps working until its sunset, at least **six months** later:

1. **The schema marks it** `deprecated`, with its sunset date in `x-sunset` and its replacement in the description.
2. **Every response says so**, in standard headers that clients and gateways can watch for:

   ```
   Deprecation: @1793491200                        (RFC 9745: deprecated since 2026-11-01)
   Sunset: Sat, 01 May 2027 00:00:00 GMT           (RFC 8594: may be removed after this)
   Link: </api/v1/new>; rel="successor-version"
   ```

3. **Its calls are counted** in the `ragolex_deprecated_requests_total` metric, by route, so operators can see who still uses it before the sunset.
4. **It is listed** in the release notes when it is deprecated and again when it is removed.

In code, a route is deprecated with `**deprecated(since=…, sunset=…, successor=…)` from `api/deprecation.py`, which refuses a sunset less than six months away. Removal still has to pass the CI check: it is a breaking change, made in a pull request labelled `api-breaking`, only after the sunset date.

## A new major version

Changes that cannot be made by adding, such as a different resource model, go into `/api/v2`, served beside `/api/v1`. `v1` then follows the retirement steps above as a whole, with at least six months during which both are served. There is no `/api/v2` yet.

## What this does not cover

The web app and the chat widget are clients like any other, released with the server, so their internals may change at any time; the widget's embed snippet (`<script src=".../widget.js" data-widget="…">`) and its `window.RagolexWidget` methods are stable like the API. The Prometheus metrics, log lines and the command line are operator interfaces: they follow the same spirit, and changes to them are noted in the release notes.
