// Talks to a widget's public API: no key, the widget id is all it needs.

import { readEvents } from "../api/sse";

export interface WidgetConfig {
  id: string;
  name: string;
  welcome: string | null;
  accent: string;
}

export interface WidgetCitation {
  number: number;
  file_name: string | null;
  page: number | null;
  section: string | null;
  text: string;
}

export interface WidgetAnswer {
  signal: "answer_success" | "no_answer";
  answer: string | null;
  citations: WidgetCitation[];
  conversation_id: string;
  message_id: number | null;
}

export type AskEvent = { kind: "delta"; text: string } | { kind: "answer"; answer: WidgetAnswer };

/** A refused or failed request: the API's signal, and when to try again if it says. */
export class WidgetError extends Error {
  constructor(
    readonly signal: string,
    readonly status: number,
    readonly retryAfter: number | null = null,
  ) {
    super(signal);
  }
}

export class WidgetClient {
  constructor(
    private readonly apiBase: string,
    readonly widgetId: string,
  ) {}

  private url(path = ""): string {
    return `${this.apiBase.replace(/\/$/, "")}/api/v1/widgets/${encodeURIComponent(this.widgetId)}${path}`;
  }

  async config(): Promise<WidgetConfig> {
    const response = await send(this.url());
    return (await response.json()) as WidgetConfig;
  }

  /** The answer's text as it is written, then the answer; throws WidgetError on failure. */
  async *ask(question: string, conversationId: string | null, signal?: AbortSignal): AsyncGenerator<AskEvent> {
    const response = await send(this.url("/ask"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(conversationId ? { question, conversation_id: conversationId } : { question }),
      signal,
    });
    if (!response.body) throw new WidgetError("network_error", 0);
    for await (const event of readEvents(response.body)) {
      const data = JSON.parse(event.data);
      if (event.event === "delta") yield { kind: "delta", text: data.text };
      else if (event.event === "answer") yield { kind: "answer", answer: data as WidgetAnswer };
      else if (event.event === "error") throw new WidgetError(data.signal, 200);
    }
  }

  async rate(conversationId: string, messageId: number, rating: "up" | "down"): Promise<void> {
    const path = `/conversations/${encodeURIComponent(conversationId)}/messages/${messageId}/feedback`;
    await send(this.url(path), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating }),
    });
  }
}

async function send(url: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    // No cookies: the widget acts for the website, not for whoever visits it.
    response = await fetch(url, { ...init, credentials: "omit", mode: "cors" });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new WidgetError("network_error", 0);
  }
  if (response.ok) return response;
  let signal = "request_failed";
  try {
    signal = ((await response.json()) as { signal?: string }).signal ?? signal;
  } catch {
    // Not one of the API's errors, e.g. a proxy's page.
  }
  const retryAfter = Number(response.headers.get("Retry-After"));
  throw new WidgetError(signal, response.status, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null);
}

/** What to tell a visitor when asking failed. */
export function failureMessage(error: unknown): string {
  const signal = error instanceof WidgetError ? error.signal : "network_error";
  switch (signal) {
    case "rate_limited":
      return "Too many questions at once. Please try again in a minute.";
    case "answer_quota_exceeded":
    case "budget_exceeded":
      return "This assistant cannot answer more questions right now. Please come back later.";
    case "conversation_not_found":
      return "This conversation has ended. Start a new one to keep asking.";
    case "network_error":
      return "The assistant could not be reached. Check your connection and try again.";
    default:
      return "Something went wrong while answering. Please try again.";
  }
}
