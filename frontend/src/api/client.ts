import { signalMessage } from "@/lib/signals";

import { authHeaders, noteRefusal } from "./auth";
import { readEvents } from "./sse";
import type {
  Answer,
  AskOptions,
  Assistant,
  BotKind,
  ChatBot,
  ConnectionKind,
  ConnectionList,
  SsoRole,
  SsoSettings,
  ChatWidget,
  ChatWidgetSettings,
  Chunk,
  SourceKind,
  SourcePage,
  WebsiteSource,
  Conversation,
  ConversationDetail,
  ConversationMessage,
  CreatedWebhook,
  FeedbackList,
  FileInfo,
  Health,
  IndexResult,
  Job,
  Me,
  Page,
  ProcessOptions,
  ProcessResult,
  Project,
  ProjectListItem,
  ProjectUsage,
  Rating,
  SearchOptions,
  SearchResult,
  TagCount,
  ApiKeyInfo,
  AuditEvent,
  CreatedApiKey,
  CreatedInvitation,
  Domain,
  EvaluationRun,
  Invitation,
  InvitationPreview,
  Member,
  MemberRole,
  Session,
  Site,
  Scope,
  Card,
  Deck,
  NewCard,
  ReviewCard,
  ReviewGrade,
  StudyKind,
  StudyMaterial,
  TenantUsage,
  UsageHistory,
  UploadResult,
  Webhook,
  WebhookDelivery,
  WebhookEvent,
  Welcome,
} from "./types";

const BASE = "/api/v1";

/** An error response of the API, or a failure to reach it. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly signal: string,
    message = signalMessage(signal),
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turns an error response into an ApiError: `{"signal"}` bodies, or FastAPI's 422 `{"detail"}`. */
export function errorFromBody(status: number, body: unknown): ApiError {
  if (body && typeof body === "object") {
    if ("signal" in body && typeof body.signal === "string") return new ApiError(status, body.signal);
    if ("detail" in body && Array.isArray(body.detail) && body.detail.length > 0) {
      const [first] = body.detail as { msg?: string; loc?: unknown[] }[];
      const field = first?.loc?.at(-1);
      const detail = [field, first?.msg].filter(Boolean).join(": ");
      return new ApiError(status, "validation_error", detail || signalMessage("validation_error"));
    }
  }
  return new ApiError(status, `http_${status}`, `The server answered with status ${status}.`);
}

/**
 * Sends a request; an error response becomes an ApiError. Unless `quiet`, a
 * refusal for want of a key or a session sends the app to the sign-in page.
 */
async function send(path: string, init: RequestInit = {}, quiet = false): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(BASE + path, { ...init, headers: { ...authHeaders(), ...(init.headers as object) } });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = errorFromBody(response.status, body);
    if (!quiet) noteRefusal(error.signal);
    throw error;
  }
  return response;
}

async function get<T>(path: string, params?: Record<string, number | string>): Promise<T> {
  const query = params ? "?" + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])) : "";
  return (await send(path + query)).json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown, signal?: AbortSignal, quiet = false): Promise<T> {
  const init: RequestInit = { method: "POST", signal };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  return (await send(path, init, quiet)).json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const response = await send(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const response = await send(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json() as Promise<T>;
}

/** A file the API makes, to save: its text and the name the server gives it. */
async function download(path: string): Promise<{ blob: Blob; filename: string | null }> {
  const response = await send(path);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  return { blob: await response.blob(), filename: /filename="([^"]+)"/.exec(disposition)?.[1] ?? null };
}

async function remove(path: string): Promise<void> {
  await send(path, { method: "DELETE" });
}

/** A request whose success has no body (202, 204). */
async function call(method: string, path: string, body?: unknown): Promise<void> {
  await send(path, {
    method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
}

const project = (name: string) => encodeURIComponent(name);
const conversations = (name: string) => `/projects/${project(name)}/conversations`;
const decks = (name: string) => `/projects/${project(name)}/decks`;
const feedbackPath = (name: string, conversationId: string, messageId: number) =>
  `${conversations(name)}/${encodeURIComponent(conversationId)}/messages/${messageId}/feedback`;

export interface PageParams {
  offset?: number;
  limit?: number;
}

export interface UploadOptions {
  /** Given to the file; a file the project already has gains those it did not have. */
  tags?: string[];
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

export interface StreamHandlers {
  onDelta: (text: string) => void;
}

export const api = {
  welcome: () => get<Welcome>("/"),

  /** The health check answers 503 with the same body when the database is down. */
  async health(): Promise<Health> {
    try {
      const response = await fetch(`${BASE}/health`);
      return (await response.json()) as Health;
    } catch {
      throw new ApiError(0, "network_error");
    }
  },

  projects: (page: PageParams = {}) =>
    get<Page<ProjectListItem>>("/projects", { offset: page.offset ?? 0, limit: page.limit ?? 100 }),
  project: (name: string) => get<Project>(`/projects/${project(name)}`),
  usage: (name: string) => get<ProjectUsage>(`/projects/${project(name)}/usage`),
  /** Deletes the project with all its files, chunks, answers and conversations. */
  deleteProject: (name: string) => remove(`/projects/${project(name)}`),
  deleteFile: (name: string, fileId: string) => remove(`/projects/${project(name)}/files/${encodeURIComponent(fileId)}`),
  files: (name: string, page: PageParams = {}, tag?: string) =>
    get<Page<FileInfo>>(`/projects/${project(name)}/files`, {
      offset: page.offset ?? 0,
      limit: page.limit ?? 100,
      ...(tag ? { tag } : {}),
    }),
  /** Replaces the file's tags. */
  setFileTags: (name: string, fileId: string, tags: string[]) =>
    put<FileInfo>(`/projects/${project(name)}/files/${encodeURIComponent(fileId)}/tags`, { tags }),
  tags: (name: string) => get<{ items: TagCount[] }>(`/projects/${project(name)}/tags`),
  assistant: (name: string) => get<Assistant>(`/projects/${project(name)}/assistant`),
  /** Changes the fields given; null clears one. */
  updateAssistant: (name: string, changes: Partial<Assistant>) =>
    patch<Assistant>(`/projects/${project(name)}/assistant`, changes),
  chunks: (name: string, fileId: string, page: PageParams = {}) =>
    get<Page<Chunk>>(`/projects/${project(name)}/files/${encodeURIComponent(fileId)}/chunks`, {
      offset: page.offset ?? 0,
      limit: page.limit ?? 20,
    }),

  /** Uploads with XMLHttpRequest, because fetch cannot report upload progress. */
  upload(name: string, file: File, options: UploadOptions = {}): Promise<UploadResult> {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", `${BASE}/data/upload/${project(name)}`);
      request.responseType = "json";
      for (const [header, value] of Object.entries(authHeaders())) request.setRequestHeader(header, value);
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) options.onProgress?.(event.loaded / event.total);
      };
      request.onload = () => {
        if (request.status >= 200 && request.status < 300) resolve(request.response as UploadResult);
        else {
          const error = errorFromBody(request.status, request.response);
          noteRefusal(error.signal);
          reject(error);
        }
      };
      request.onerror = () => reject(new ApiError(0, "network_error"));
      request.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
      options.signal?.addEventListener("abort", () => request.abort());
      const form = new FormData();
      form.append("file", file, file.name);
      if (options.tags?.length) form.append("tags", options.tags.join(","));
      request.send(form);
    });
  },

  process: (name: string, fileId: string, options: ProcessOptions) =>
    post<ProcessResult>(`/data/process/${project(name)}`, { file_id: fileId, ...options }),
  /** Processes and indexes the file in the background; follow it with `job`. */
  createJob: (name: string, fileId: string, options: ProcessOptions) =>
    post<Job>(`/projects/${project(name)}/jobs`, { file_id: fileId, ...options }),
  job: (name: string, jobId: string) => get<Job>(`/projects/${project(name)}/jobs/${encodeURIComponent(jobId)}`),
  me: () => get<Me>("/me"),

  // Accounts. The session is an HttpOnly cookie the server sets and the browser sends.
  signUp: (body: { email: string; password: string; name: string; workspace: string }) =>
    post<Session>("/auth/signup", body),
  signIn: (email: string, password: string) => post<Session>("/auth/login", { email, password }),
  signOut: () => call("POST", "/auth/logout"),
  /** Quiet: having no session is an answer here, not a reason to sign in. */
  session: async () => (await send("/auth/session", {}, true)).json() as Promise<Session>,
  switchWorkspace: (workspace: string) => put<Session>("/auth/session/workspace", { workspace }),
  changePassword: (current: string, next: string) =>
    call("PUT", "/auth/password", { current_password: current, new_password: next }),
  /** Always succeeds: the server does not say whether the address has an account. */
  requestPasswordReset: (email: string) => call("POST", "/auth/password-reset", { email }),
  resetPassword: (token: string, password: string) =>
    call("POST", "/auth/password-reset/confirm", { token, password }),
  invitation: (token: string) => post<InvitationPreview>("/auth/invitation", { token }, undefined, true),
  /**
   * Signed in, joins as the user; otherwise `name` and `password` make the invited
   * email's account. Quiet: the invitation page says what to do when it fails.
   */
  acceptInvitation: (token: string, account: { name?: string; password?: string } = {}) =>
    post<Session>("/auth/invitation/accept", { token, ...account }, undefined, true),
  members: () => get<Member[]>("/members"),
  changeRole: (userId: number, role: MemberRole) => put<Member>(`/members/${userId}`, { role }),
  removeMember: (userId: number) => remove(`/members/${userId}`),
  invitations: () => get<Invitation[]>("/invitations"),
  invite: (email: string, role: MemberRole) => post<CreatedInvitation>("/invitations", { email, role }),
  revokeInvitation: (invitationId: string) => remove(`/invitations/${encodeURIComponent(invitationId)}`),
  /** Which workspace this domain serves, and whether people may sign up here. */
  site: () => get<Site>("/site"),
  domains: () => get<Domain[]>("/domains"),
  addDomain: (domain: string) => post<Domain>("/domains", { domain }),
  /** Looks the domain's TXT record up now. */
  verifyDomain: (domainId: string) => post<Domain>(`/domains/${encodeURIComponent(domainId)}/verify`),
  removeDomain: (domainId: string) => remove(`/domains/${encodeURIComponent(domainId)}`),
  decks: (name: string) => get<Deck[]>(decks(name)),
  createDeck: (name: string, deckName: string, cards: NewCard[]) => post<Deck>(decks(name), { name: deckName, cards }),
  addCards: (name: string, deckId: string, cards: NewCard[]) =>
    post<Deck>(`${decks(name)}/${encodeURIComponent(deckId)}/cards`, { cards }),
  deleteDeck: (name: string, deckId: string) => remove(`${decks(name)}/${encodeURIComponent(deckId)}`),
  reviewQueue: (name: string, deckId: string, limit = 50) =>
    get<{ deck: Deck; cards: ReviewCard[] }>(`${decks(name)}/${encodeURIComponent(deckId)}/review`, { limit }),
  reviewCard: (name: string, deckId: string, cardId: string, grade: ReviewGrade) =>
    post<Card>(`${decks(name)}/${encodeURIComponent(deckId)}/cards/${encodeURIComponent(cardId)}/review`, { grade }),
  /** The deck as a text file that Anki imports. */
  ankiExport: (name: string, deckId: string) => download(`${decks(name)}/${encodeURIComponent(deckId)}/anki`),
  /** A summary, flashcards or a quiz from a processed document; one model call. */
  study: (name: string, fileId: string, kind: StudyKind, count: number) =>
    post<StudyMaterial>(`/study/${project(name)}`, { file_id: fileId, kind, count }),
  tenantUsage: () => get<TenantUsage>("/usage"),
  keys: () => get<ApiKeyInfo[]>("/keys"),
  createKey: (name: string, scopes: Scope[]) => post<CreatedApiKey>("/keys", { name, scopes }),
  revokeKey: (keyId: string) => remove(`/keys/${encodeURIComponent(keyId)}`),
  audit: (page: PageParams = {}, action?: string) =>
    get<Page<AuditEvent>>("/audit", {
      offset: page.offset ?? 0,
      limit: page.limit ?? 20,
      ...(action ? { action } : {}),
    }),
  evaluations: (page: PageParams = {}) =>
    get<Page<EvaluationRun>>("/evaluations", { offset: page.offset ?? 0, limit: page.limit ?? 50 }),
  usageHistory: (days = 30) => get<UsageHistory>("/usage/history", { days }),
  webhooks: (name: string, page: PageParams = {}) =>
    get<Page<Webhook>>(`/projects/${project(name)}/webhooks`, { offset: page.offset ?? 0, limit: page.limit ?? 100 }),
  createWebhook: (name: string, body: { url: string; events: WebhookEvent[]; description?: string | null }) =>
    post<CreatedWebhook>(`/projects/${project(name)}/webhooks`, body),
  deleteWebhook: (name: string, webhookId: string) =>
    remove(`/projects/${project(name)}/webhooks/${encodeURIComponent(webhookId)}`),
  pingWebhook: (name: string, webhookId: string) =>
    post<WebhookDelivery>(`/projects/${project(name)}/webhooks/${encodeURIComponent(webhookId)}/ping`),
  deliveries: (name: string, webhookId: string, page: PageParams = {}) =>
    get<Page<WebhookDelivery>>(`/projects/${project(name)}/webhooks/${encodeURIComponent(webhookId)}/deliveries`, {
      offset: page.offset ?? 0,
      limit: page.limit ?? 10,
    }),
  sso: () => get<SsoSettings>("/sso"),
  /** Without `client_secret`, the one already set is kept. */
  saveSso: (body: { issuer: string; client_id: string; client_secret?: string; default_role: SsoRole; enabled: boolean; required: boolean }) =>
    put<SsoSettings>("/sso", body),
  deleteSso: () => remove("/sso"),
  /** The workspace that signs this email in, and where to start. */
  ssoDiscover: (email: string) => post<{ workspace: string; start_url: string }>("/auth/sso/discover", { email }),
  connections: () => get<ConnectionList>("/connections"),
  /** Where to send the admin to sign in; they come back to `returnTo`. */
  startConnection: (kind: ConnectionKind, returnTo: string) =>
    post<{ authorize_url: string }>("/connections", { kind, return_to: returnTo }),
  deleteConnection: (id: string) => remove(`/connections/${encodeURIComponent(id)}`),
  sources: (name: string) => get<{ items: WebsiteSource[] }>(`/projects/${project(name)}/sources`),
  createSource: (
    name: string,
    body: {
      kind: SourceKind;
      url?: string;
      connection_id?: string;
      max_pages: number;
      sync_interval_hours: number;
      tags: string[];
    },
  ) =>
    post<WebsiteSource>(`/projects/${project(name)}/sources`, body),
  syncSource: (name: string, sourceId: string) =>
    post<WebsiteSource>(`/projects/${project(name)}/sources/${encodeURIComponent(sourceId)}/sync`),
  sourcePages: (name: string, sourceId: string, page: PageParams = {}) =>
    get<Page<SourcePage>>(`/projects/${project(name)}/sources/${encodeURIComponent(sourceId)}/pages`, {
      offset: page.offset ?? 0,
      limit: page.limit ?? 100,
    }),
  deleteSource: (name: string, sourceId: string, keepFiles: boolean) =>
    remove(`/projects/${project(name)}/sources/${encodeURIComponent(sourceId)}?keep_files=${keepFiles}`),
  bots: (name: string) => get<{ items: ChatBot[] }>(`/projects/${project(name)}/bots`),
  /** The chat app checks the credentials first; they are never returned. */
  createBot: (name: string, body: { kind: BotKind; name: string; credentials: Record<string, string>; tags: string[] }) =>
    post<ChatBot>(`/projects/${project(name)}/bots`, body),
  updateBot: (
    name: string,
    botId: string,
    changes: Partial<{ name: string; tags: string[]; enabled: boolean; credentials: Record<string, string> }>,
  ) => patch<ChatBot>(`/projects/${project(name)}/bots/${encodeURIComponent(botId)}`, changes),
  deleteBot: (name: string, botId: string) => remove(`/projects/${project(name)}/bots/${encodeURIComponent(botId)}`),
  widgets: (name: string) => get<{ items: ChatWidget[] }>(`/projects/${project(name)}/widgets`),
  createWidget: (name: string, settings: ChatWidgetSettings) =>
    post<ChatWidget>(`/projects/${project(name)}/widgets`, settings),
  updateWidget: (name: string, widgetId: string, settings: Partial<ChatWidgetSettings>) =>
    patch<ChatWidget>(`/projects/${project(name)}/widgets/${encodeURIComponent(widgetId)}`, settings),
  deleteWidget: (name: string, widgetId: string) =>
    remove(`/projects/${project(name)}/widgets/${encodeURIComponent(widgetId)}`),
  index: (name: string, fileId?: string) =>
    post<IndexResult>(`/index/${project(name)}`, fileId ? { file_id: fileId } : undefined),
  search: (name: string, query: string, options: SearchOptions) =>
    post<SearchResult>(`/search/${project(name)}`, { query, ...options }),
  conversations: (name: string, page: PageParams = {}) =>
    get<Page<Conversation>>(conversations(name), { offset: page.offset ?? 0, limit: page.limit ?? 50 }),
  createConversation: (name: string) => post<Conversation>(conversations(name)),
  conversation: (name: string, id: string) =>
    get<ConversationDetail>(`${conversations(name)}/${encodeURIComponent(id)}`),
  deleteConversation: (name: string, id: string) => remove(`${conversations(name)}/${encodeURIComponent(id)}`),

  /** Rates an answer in a conversation, replacing any rating it had. */
  rate: (name: string, conversationId: string, messageId: number, rating: Rating, comment?: string) =>
    put<ConversationMessage>(feedbackPath(name, conversationId, messageId), { rating, comment: comment || null }),
  unrate: (name: string, conversationId: string, messageId: number) =>
    remove(feedbackPath(name, conversationId, messageId)),
  feedback: (name: string, options: PageParams & { rating?: Rating } = {}) =>
    get<FeedbackList>(`/projects/${project(name)}/feedback`, {
      offset: options.offset ?? 0,
      limit: options.limit ?? 20,
      ...(options.rating ? { rating: options.rating } : {}),
    }),

  /** With `conversation_id`, the question follows on from that conversation and is added to it. */
  ask: (name: string, question: string, options: AskOptions, signal?: AbortSignal) =>
    post<Answer>(`/ask/${project(name)}`, { question, ...options }, signal),

  /** Streams an answer: text pieces go to `onDelta`, the finished Answer is returned. */
  async askStream(
    name: string,
    question: string,
    options: AskOptions,
    handlers: StreamHandlers,
    signal?: AbortSignal,
  ): Promise<Answer> {
    const response = await send(`/ask/${project(name)}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, ...options }),
      signal,
    });
    if (!response.body) throw new ApiError(0, "network_error");
    for await (const event of readEvents(response.body)) {
      const data = JSON.parse(event.data) as Record<string, unknown>;
      if (event.event === "delta") handlers.onDelta(String(data.text ?? ""));
      else if (event.event === "answer") return data as unknown as Answer;
      else if (event.event === "error") throw new ApiError(502, String(data.signal ?? "llm_failed"));
    }
    throw new ApiError(502, "llm_failed", "The answer stream ended before the answer was complete.");
  },
};
