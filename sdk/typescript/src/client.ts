import createClient, { type Client, type Middleware } from "openapi-fetch";

import { RagolexError, errorFromResponse } from "./errors.js";
import type { components, paths } from "./schema.js";
import { readEvents } from "./sse.js";

export type Schemas = components["schemas"];
export type Answer = Schemas["AskResponse"];
export type AskRequest = Schemas["AskRequest"];
export type Job = Schemas["JobResponse"];
export type SearchRequest = Schemas["SearchRequest"];
export type SearchResult = Schemas["SearchResult"];
export type SearchFilters = Schemas["SearchFiltersRequest"];
export type FileInfo = Schemas["FileResponse"];
export type Upload = Schemas["UploadResponse"];

/** Options of a question, besides the question itself. */
export type AskOptions = Omit<AskRequest, "question">;
/** Options of a search, besides the query. */
export type SearchOptions = Omit<SearchRequest, "query">;

/** What a streamed answer yields: pieces of text as they are written, then the whole answer. */
export type AnswerEvent = { type: "delta"; text: string } | { type: "answer"; answer: Answer };

export interface RagolexOptions {
  /** Where the API is, e.g. `https://rag.example.com`. */
  baseUrl: string;
  /** An API key (`mrag_…`); leave it out when the server does not require one. */
  apiKey?: string;
  /** Another fetch, e.g. for tests or a proxy; the global one by default. */
  fetch?: typeof globalThis.fetch;
  /** Headers sent with every request. */
  headers?: Record<string, string>;
}

export interface UploadOptions {
  /** The file's name, when `file` is a Blob without one. */
  name?: string;
  /** Tags for the file; a file the project already has gains those it did not have. */
  tags?: string[];
}

export interface WaitOptions {
  /** How often to ask, in milliseconds (default 1000). */
  intervalMs?: number;
  /** Give up after this many milliseconds (default 10 minutes). */
  timeoutMs?: number;
  signal?: AbortSignal;
}

const encode = encodeURIComponent;

/**
 * A client for the Ragolex API.
 *
 * `api` is the whole API, typed from its OpenAPI schema: `api.GET("/api/v1/projects")`.
 * Error responses throw a `RagolexError`, so a call that returns has its `data`.
 * The methods beside it cover what the schema cannot type, such as uploads and
 * streamed answers, and the usual steps of a RAG app.
 */
export class Ragolex {
  readonly api: Client<paths>;
  private readonly baseUrl: string;
  private readonly fetcher: typeof globalThis.fetch;
  private readonly headers: Record<string, string>;

  constructor(options: RagolexOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.fetcher = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
    this.headers = { ...options.headers };
    if (options.apiKey) this.headers.Authorization = `Bearer ${options.apiKey}`;
    this.api = createClient<paths>({ baseUrl: this.baseUrl, fetch: this.fetcher, headers: this.headers });
    const throwOnError: Middleware = {
      async onResponse({ response }) {
        if (!response.ok) throw await errorFromResponse(response);
        return undefined;
      },
    };
    this.api.use(throwOnError);
  }

  /** Uploads a file into a project, which is created with its first file. */
  async upload(project: string, file: Blob, options: UploadOptions = {}): Promise<Upload> {
    const form = new FormData();
    const name = options.name ?? (file as Blob & { name?: string }).name ?? "upload";
    form.append("file", file, name);
    if (options.tags?.length) form.append("tags", options.tags.join(","));
    return (await this.send(`/api/v1/data/upload/${encode(project)}`, { method: "POST", body: form })).json();
  }

  /** Splits and indexes an uploaded file in the background; follow the job with `waitForJob`. */
  async process(project: string, fileId: string, options: { chunk_size?: number; overlap_size?: number } = {}): Promise<Job> {
    const { data } = await this.api.POST("/api/v1/projects/{project_id}/jobs", {
      params: { path: { project_id: project } },
      body: { file_id: fileId, ...options },
    });
    return data!;
  }

  /** Waits until a job succeeds, and returns it; throws a `RagolexError` if it fails. */
  async waitForJob(project: string, jobId: string, options: WaitOptions = {}): Promise<Job> {
    const deadline = Date.now() + (options.timeoutMs ?? 600_000);
    for (;;) {
      const { data } = await this.api.GET("/api/v1/projects/{project_id}/jobs/{job_id}", {
        params: { path: { project_id: project, job_id: jobId } },
        signal: options.signal,
      });
      const job = data!;
      if (job.status === "succeeded") return job;
      if (job.status === "failed") throw new RagolexError(422, job.error ?? "job_failed", { body: job });
      if (Date.now() >= deadline) throw new RagolexError(0, "timeout", { message: `Job ${jobId} is still ${job.status}` });
      await sleep(options.intervalMs ?? 1000, options.signal);
    }
  }

  /** Uploads a file, then waits until it is split and indexed. Content the project has already is not processed again. */
  async addDocument(project: string, file: Blob, options: UploadOptions & WaitOptions = {}): Promise<Upload> {
    const upload = await this.upload(project, file, options);
    if (upload.signal !== "file_already_uploaded") {
      const job = await this.process(project, upload.file_id);
      await this.waitForJob(project, job.id, options);
    }
    return upload;
  }

  /** The chunks that best match a query, best first. */
  async search(project: string, query: string, options: SearchOptions = {}): Promise<SearchResult[]> {
    const { data } = await this.api.POST("/api/v1/search/{project_id}", {
      params: { path: { project_id: project } },
      body: { query, ...options },
    });
    return data!.results;
  }

  /** An answer from the project's documents, with citations. */
  async ask(project: string, question: string, options: AskOptions = {}): Promise<Answer> {
    const { data } = await this.api.POST("/api/v1/ask/{project_id}", {
      params: { path: { project_id: project } },
      body: { question, ...options },
    });
    return data!;
  }

  /**
   * The same answer, as it is written: `delta` events with the next piece of
   * text, then one `answer` event. Stop iterating to stop the answer.
   */
  async *askStream(project: string, question: string, options: AskOptions & { signal?: AbortSignal } = {}): AsyncGenerator<AnswerEvent> {
    const { signal, ...body } = options;
    const response = await this.send(`/api/v1/ask/${encode(project)}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, ...body }),
      signal,
    });
    if (!response.body) throw new RagolexError(0, "network_error");
    for await (const event of readEvents(response.body)) {
      const data = JSON.parse(event.data) as Record<string, unknown>;
      if (event.event === "delta") yield { type: "delta", text: String(data.text ?? "") };
      else if (event.event === "answer") {
        yield { type: "answer", answer: data as unknown as Answer };
        return;
      } else if (event.event === "error") throw new RagolexError(502, String(data.signal ?? "llm_failed"), { body: data });
    }
    throw new RagolexError(502, "llm_failed", { message: "The answer stream ended before the answer was complete." });
  }

  private async send(path: string, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, { ...init, headers: { ...this.headers, ...init.headers } });
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") throw caught;
      throw new RagolexError(0, "network_error", { message: `The server could not be reached: ${String(caught)}` });
    }
    if (!response.ok) throw await errorFromResponse(response);
    return response;
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}
