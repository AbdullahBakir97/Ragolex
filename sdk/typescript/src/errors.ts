/** An error response from the API, or a request that never got one. */
export class RagolexError extends Error {
  /** The HTTP status; 0 when the server could not be reached. */
  readonly status: number;
  /** The API's signal, such as `project_not_found`; `validation_error` for invalid requests. */
  readonly signal: string;
  /** The response body, when there was one. */
  readonly body: unknown;
  /** Seconds to wait before trying again, from `Retry-After` (rate limits). */
  readonly retryAfter: number | null;

  constructor(status: number, signal: string, options: { body?: unknown; retryAfter?: number | null; message?: string } = {}) {
    super(options.message ?? `${signal} (HTTP ${status})`);
    this.name = "RagolexError";
    this.status = status;
    this.signal = signal;
    this.body = options.body;
    this.retryAfter = options.retryAfter ?? null;
  }
}

/** The error a response stands for. */
export async function errorFromResponse(response: Response): Promise<RagolexError> {
  let body: unknown;
  try {
    body = await response.clone().json();
  } catch {
    body = undefined;
  }
  const record = (body ?? {}) as Record<string, unknown>;
  const signal =
    typeof record.signal === "string" ? record.signal : Array.isArray(record.detail) ? "validation_error" : "http_error";
  const retry = Number(response.headers.get("Retry-After"));
  return new RagolexError(response.status, signal, {
    body,
    retryAfter: response.headers.has("Retry-After") && Number.isFinite(retry) ? retry : null,
  });
}
