# @ragolex/client

A TypeScript client for the [Ragolex](../../README.md) API: every endpoint, typed from the API's OpenAPI schema, plus methods for uploads, streamed answers and background jobs. It runs in Node 20+ and in browsers, and its one dependency is `openapi-fetch`.

```bash
npm install @ragolex/client     # or, from this repository: npm install ./sdk/typescript
```

```ts
import { Ragolex, RagolexError } from "@ragolex/client";

const rag = new Ragolex({ baseUrl: "https://rag.example.com", apiKey: process.env.RAGOLEX_API_KEY });

// Upload a file and wait until it is split and indexed.
await rag.addDocument("handbook", new File([text], "leave-policy.md"), { tags: ["hr"] });

// Search, and ask: only files tagged hr.
const results = await rag.search("handbook", "paid leave", { top_k: 5, filters: { tags: ["hr"] } });
const answer = await rag.ask("handbook", "How many days of leave do I get?");
console.log(answer.answer, answer.citations);

// Stream an answer as it is written.
for await (const event of rag.askStream("handbook", "And for part-time staff?")) {
  if (event.type === "delta") process.stdout.write(event.text);
  else console.log("\nSources:", event.answer.citations.map((c) => c.file_id));
}
```

## Every endpoint

`rag.api` is an [openapi-fetch](https://openapi-ts.dev/openapi-fetch/) client for the whole API: paths, parameters, bodies and responses are checked by TypeScript.

```ts
const { data: files } = await rag.api.GET("/api/v1/projects/{project_id}/files", {
  params: { path: { project_id: "handbook" }, query: { tag: "hr", limit: 50 } },
});

await rag.api.PUT("/api/v1/projects/{project_id}/files/{file_id}/tags", {
  params: { path: { project_id: "handbook", file_id: files!.items[0]!.file_id } },
  body: { tags: ["hr", "policies"] },
});
```

Every request and response type is exported too: `Schemas["JobResponse"]`, or the shorter `Answer`, `Job`, `FileInfo`, `SearchResult`…

## Errors

An error response throws a `RagolexError`, with the API's `signal`, the HTTP `status`, the response `body` and, for rate limits, `retryAfter` in seconds. A server that cannot be reached is `status` 0 and `signal` `network_error`.

```ts
try {
  await rag.ask("handbook", question);
} catch (error) {
  if (error instanceof RagolexError && error.signal === "rate_limited") await wait(error.retryAfter);
  else throw error;
}
```

## Methods

| Method | Does |
|---|---|
| `upload(project, file, { name, tags })` | Uploads a `Blob` or `File`; content the project has already returns `file_already_uploaded` |
| `process(project, fileId, { chunk_size, overlap_size })` | Queues the job that splits and indexes a file |
| `waitForJob(project, jobId, { intervalMs, timeoutMs, signal })` | Waits until a job succeeds; throws if it fails |
| `addDocument(project, file, options)` | All three: upload, process, wait |
| `search(project, query, options)` | The best matching chunks |
| `ask(project, question, options)` | An answer with citations |
| `askStream(project, question, options)` | The answer as it is written: `delta` events, then `answer` |

## Development

`src/schema.ts` is generated from [`../openapi.json`](../openapi.json): run `npm run generate` after the schema changes (see [../README.md](../README.md)). `npm test` runs the tests, `npm run build` writes `dist/`.
