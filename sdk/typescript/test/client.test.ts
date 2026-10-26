import { describe, expect, it, vi } from "vitest";

import { Ragolex, RagolexError } from "../src/index.js";

type Handler = (request: Request) => Response | Promise<Response>;

/** A client whose requests go to `handler`; `requests` keeps them. */
function clientWith(handler: Handler, apiKey: string | null = "ragolex_test") {
  const requests: Request[] = [];
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    requests.push(request.clone());
    return handler(request);
  });
  const rag = new Ragolex({ baseUrl: "https://rag.example.com/", apiKey: apiKey ?? undefined, fetch });
  return { rag, requests };
}

function sse(...events: [string, unknown][]): Response {
  const text = events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
  const bytes = new TextEncoder().encode(text);
  // Split mid-event, as a network would.
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, 20));
      controller.enqueue(bytes.slice(20));
      controller.close();
    },
  });
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

const ANSWER = { signal: "answer_success", answer: "25 days [1].", citations: [] };

describe("Ragolex", () => {
  it("calls the typed API with the key, and returns the data", async () => {
    const { rag, requests } = clientWith(() => Response.json({ total: 0, offset: 0, limit: 5, items: [] }));

    const { data } = await rag.api.GET("/api/v1/projects/{project_id}/files", {
      params: { path: { project_id: "hand book" }, query: { limit: 5, tag: "hr" } },
    });

    expect(data?.items).toEqual([]);
    expect(requests[0]!.url).toBe("https://rag.example.com/api/v1/projects/hand%20book/files?limit=5&tag=hr");
    expect(requests[0]!.headers.get("Authorization")).toBe("Bearer ragolex_test");
  });

  it("sends no key when it has none", async () => {
    const { rag, requests } = clientWith(() => Response.json({ status: "ok", database: "ok" }), null);

    await rag.api.GET("/api/v1/health");

    expect(requests[0]!.headers.has("Authorization")).toBe(false);
  });

  it("throws error responses as RagolexErrors with their signal", async () => {
    const { rag } = clientWith(() =>
      Response.json({ signal: "rate_limited" }, { status: 429, headers: { "Retry-After": "12" } }),
    );

    const error = await rag.api.GET("/api/v1/projects").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(RagolexError);
    expect(error).toMatchObject({ status: 429, signal: "rate_limited", retryAfter: 12 });
  });

  it("names validation errors", async () => {
    const { rag } = clientWith(() => Response.json({ detail: [{ msg: "bad" }] }, { status: 422 }));

    await expect(rag.search("docs", "")).rejects.toMatchObject({ status: 422, signal: "validation_error" });
  });

  it("reports a server it cannot reach", async () => {
    const { rag } = clientWith(() => {
      throw new TypeError("fetch failed");
    });

    await expect(rag.upload("docs", new Blob(["x"]), { name: "a.txt" })).rejects.toMatchObject({
      status: 0,
      signal: "network_error",
    });
  });

  it("uploads a file with its tags", async () => {
    const { rag, requests } = clientWith(() => Response.json({ signal: "file_uploaded_successfully", file_id: "a_x.txt" }));

    const upload = await rag.upload("docs", new File(["Cats purr."], "cats.txt", { type: "text/plain" }), {
      tags: ["pets", "v2"],
    });

    expect(upload.file_id).toBe("a_x.txt");
    const form = await requests[0]!.formData();
    expect(requests[0]!.url).toBe("https://rag.example.com/api/v1/data/upload/docs");
    expect((form.get("file") as File).name).toBe("cats.txt");
    expect(form.get("tags")).toBe("pets,v2");
    expect(requests[0]!.headers.get("Authorization")).toBe("Bearer ragolex_test");
  });

  it("adds a document: upload, process, and wait for its job", async () => {
    const states = ["queued", "running", "succeeded"];
    const { rag, requests } = clientWith((request) => {
      const path = new URL(request.url).pathname;
      if (path.startsWith("/api/v1/data/upload")) return Response.json({ signal: "file_uploaded_successfully", file_id: "a_x.txt" });
      if (request.method === "POST") return Response.json({ id: "j1", status: "queued" });
      return Response.json({ id: "j1", status: states.shift() });
    });

    await rag.addDocument("docs", new Blob(["x"]), { name: "x.txt", intervalMs: 1 });

    const posted = await requests[1]!.json();
    expect(posted).toEqual({ file_id: "a_x.txt" });
    expect(requests.map((r) => `${r.method} ${new URL(r.url).pathname}`)).toEqual([
      "POST /api/v1/data/upload/docs",
      "POST /api/v1/projects/docs/jobs",
      "GET /api/v1/projects/docs/jobs/j1",
      "GET /api/v1/projects/docs/jobs/j1",
      "GET /api/v1/projects/docs/jobs/j1",
    ]);
  });

  it("does not process content the project has already", async () => {
    const { rag, requests } = clientWith(() => Response.json({ signal: "file_already_uploaded", file_id: "a_x.txt" }));

    await rag.addDocument("docs", new Blob(["x"]), { name: "x.txt" });

    expect(requests).toHaveLength(1);
  });

  it("throws when a job fails", async () => {
    const { rag } = clientWith(() => Response.json({ id: "j1", status: "failed", error: "file_has_no_text" }));

    await expect(rag.waitForJob("docs", "j1")).rejects.toMatchObject({ signal: "file_has_no_text" });
  });

  it("exports the tenant as a ZIP archive", async () => {
    const zip = new Uint8Array([0x50, 0x4b, 0x03, 0x04]);
    const { rag, requests } = clientWith(() => new Response(zip, { headers: { "Content-Type": "application/zip" } }));

    const archive = await rag.exportTenant();

    expect(new Uint8Array(await archive.arrayBuffer())).toEqual(zip);
    expect(new URL(requests[0]!.url).pathname).toBe("/api/v1/export");
    expect(requests[0]!.headers.get("Authorization")).toBe("Bearer ragolex_test");
  });

  it("searches and asks with options", async () => {
    const { rag, requests } = clientWith((request) =>
      new URL(request.url).pathname.startsWith("/api/v1/search")
        ? Response.json({ signal: "search_success", results: [{ file_id: "a", chunk_index: 0, score: 0.9, text: "t" }] })
        : Response.json(ANSWER),
    );

    const results = await rag.search("docs", "leave", { top_k: 3, filters: { tags: ["hr"] } });
    const answer = await rag.ask("docs", "How much leave?", { conversation_id: "c1" });

    expect(results[0]!.score).toBe(0.9);
    expect(answer.answer).toBe("25 days [1].");
    expect(await requests[0]!.json()).toEqual({ query: "leave", top_k: 3, filters: { tags: ["hr"] } });
    expect(await requests[1]!.json()).toEqual({ question: "How much leave?", conversation_id: "c1" });
  });

  it("streams an answer as it is written", async () => {
    const { rag, requests } = clientWith(() => sse(["delta", { text: "25 " }], ["delta", { text: "days [1]." }], ["answer", ANSWER]));

    const events = [];
    for await (const event of rag.askStream("docs", "How much leave?", { top_k: 4 })) events.push(event);

    expect(events).toEqual([
      { type: "delta", text: "25 " },
      { type: "delta", text: "days [1]." },
      { type: "answer", answer: ANSWER },
    ]);
    expect(requests[0]!.headers.get("Accept")).toBe("text/event-stream");
    expect(await requests[0]!.json()).toEqual({ question: "How much leave?", top_k: 4 });
  });

  it("throws the error event of a stream, and a stream cut short", async () => {
    const failing = clientWith(() => sse(["delta", { text: "25" }], ["error", { signal: "llm_failed" }])).rag;
    const cut = clientWith(() => sse(["delta", { text: "25" }])).rag;

    const drain = async (stream: AsyncIterable<unknown>) => {
      for await (const _ of stream);
    };

    await expect(drain(failing.askStream("docs", "q"))).rejects.toMatchObject({ status: 502, signal: "llm_failed" });
    await expect(drain(cut.askStream("docs", "q"))).rejects.toMatchObject({ signal: "llm_failed" });
  });
});
