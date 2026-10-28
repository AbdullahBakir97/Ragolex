// Shapes of the Ragolex API's requests and responses (see /docs).

export interface Welcome {
  message: string;
  app_name: string;
  app_version: string;
}

export interface Health {
  status: "ok" | "unavailable";
  database: "ok" | "unavailable";
}

export interface Page<T> {
  total: number;
  offset: number;
  limit: number;
  items: T[];
}

export interface ProjectListItem {
  name: string;
  created_at: string;
}

export interface Project {
  name: string;
  created_at: string;
  files_count: number;
  chunks_count: number;
  embedded_chunks_count: number;
}

export interface ProjectUsage {
  answers: number;
  answered: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  unpriced_answers: number;
}

export interface FileInfo {
  file_id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
  /** Lowercase letters, digits and hyphens; they group files into collections. */
  tags: string[];
}

export interface TagCount {
  tag: string;
  /** How many of the project's files have it. */
  files: number;
}

export interface ChunkMetadata {
  source?: string;
  page?: number;
  /** The headings above the chunk in Markdown, HTML and Word files: "Setup > Install". */
  section?: string;
  [key: string]: unknown;
}

export interface Chunk {
  chunk_index: number;
  text: string;
  metadata: ChunkMetadata;
}

export interface UploadResult {
  signal: string;
  file_id: string;
}

export interface ProcessOptions {
  chunk_size: number;
  overlap_size: number;
}

/** How files are split unless chosen otherwise: the API's defaults (see sdk/openapi.json). */
export const DEFAULT_PROCESS_OPTIONS: ProcessOptions = { chunk_size: 1000, overlap_size: 200 };

export interface ProcessResult {
  signal: string;
  file_id: string;
  chunks_count: number;
}

export interface Meter {
  used: number;
  limit: number | null;
}

export interface TenantUsage {
  tenant: string;
  period_start: string;
  requests_per_minute: number | null;
  answers: Meter;
  storage_bytes: Meter;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  /** The monthly budget in US dollars; null when there is none. */
  budget_usd: number | null;
}

/** Answers, tokens and known cost of a day, a project or a model. */
export interface UsageTotal {
  answers: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface UsageHistory {
  start: string;
  /** Every day (UTC), oldest first. */
  days: (UsageTotal & { day: string })[];
  /** Costliest first. */
  projects: (UsageTotal & { project: string })[];
  /** `model` is null for questions that matched no source. */
  models: (UsageTotal & { model: string | null })[];
}

export interface Me {
  tenant: string;
  scopes: string[];
  key_id: string | null;
  auth_enabled: boolean;
  /** The signed-in user, when the request used a session rather than a key. */
  user?: User | null;
  role?: MemberRole | null;
}

/** What a domain serves, before anyone signs in. */
export interface Site {
  /** The workspace whose own domain this is; null on the server's own. */
  workspace: string | null;
  accounts_enabled: boolean;
  signup_enabled: boolean;
}

export interface DnsRecord {
  type: "TXT" | "CNAME";
  name: string;
  value: string;
}

/** A domain a workspace serves on, once its TXT record proves it. */
export interface Domain {
  id: string;
  domain: string;
  verified: boolean;
  created_at: string;
  verified_at: string | null;
  checked_at: string | null;
  records: DnsRecord[];
}

export type BotKind = "telegram" | "slack" | "whatsapp";

/** A project's assistant in a chat app. Its credentials are never returned. */
export interface ChatBot {
  id: string;
  project: string;
  kind: BotKind;
  name: string;
  /** The bot in the chat app, such as @acme_help_bot. */
  account: string;
  tags: string[];
  enabled: boolean;
  webhook_url: string;
  /** WhatsApp only. */
  verify_token: string | null;
  created_at: string;
  last_message_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
}

export type MemberRole = "owner" | "admin" | "editor" | "viewer";
export const MEMBER_ROLES: MemberRole[] = ["owner", "admin", "editor", "viewer"];

export interface User {
  id: number;
  email: string;
  name: string;
}

export interface Workspace {
  name: string;
  role: MemberRole;
}

/** A signed-in browser: its user, the workspace it works in, and all of the user's. */
export interface Session {
  user: User;
  workspace: Workspace;
  workspaces: Workspace[];
  expires_at: string;
}

export interface Member extends User {
  role: MemberRole;
  joined_at: string;
  last_login_at: string | null;
}

export interface Invitation {
  id: string;
  email: string;
  role: MemberRole;
  invited_by: User | null;
  created_at: string;
  expires_at: string;
}

export interface CreatedInvitation extends Invitation {
  /** Shown only once: the link to send. */
  link: string;
  /** Whether the server emails it too. */
  emailed: boolean;
}

/** What an invitation link offers, before it is accepted. */
export interface InvitationPreview {
  workspace: string;
  email: string;
  role: MemberRole;
  invited_by: string | null;
  expires_at: string;
  has_account: boolean;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface Job {
  id: string;
  file_id: string;
  status: JobStatus;
  stage: "processing" | "indexing" | null;
  /** Share of the chunks indexed, from 0 to 1. */
  progress: number;
  chunks_count: number | null;
  attempts: number;
  max_attempts: number;
  chunk_size: number;
  overlap_size: number;
  /** The signal of the last failure; a queued job with one waits to try again. */
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface IndexResult {
  signal: string;
  embedded_count: number;
  chunks_count: number;
}

export interface SearchFilters {
  file_ids?: string[];
  /** Only files with at least one of these tags. */
  tags?: string[];
  page_from?: number | null;
  page_to?: number | null;
  uploaded_after?: string | null;
  uploaded_before?: string | null;
  metadata?: Record<string, string | number | boolean> | null;
  max_per_file?: number | null;
}

export interface SearchOptions {
  top_k: number;
  min_score: number | null;
  filters?: SearchFilters | null;
}

export interface SearchHit {
  file_id: string;
  chunk_index: number;
  score: number;
  text: string;
  metadata: ChunkMetadata;
}

export interface SearchResult {
  signal: string;
  results: SearchHit[];
}

export interface Citation {
  number: number;
  file_id: string;
  chunk_index: number;
  page: number | null;
  /** Missing in answers stored before sections were read. */
  section?: string | null;
  score: number;
  text: string;
}

export interface Usage {
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
}

export interface Answer {
  signal: "answer_success" | "no_answer";
  answer: string | null;
  citations: Citation[];
  prompt_version: string;
  usage: Usage;
  /** The conversation the question was asked in, if any. */
  conversation_id: string | null;
  /** The standalone question a follow-up was searched with, when it was rewritten. */
  search_question: string | null;
  /** In a conversation: the answer's message, which feedback refers to. */
  message_id: number | null;
  /** In research mode: the searches made, in order. */
  research?: SearchStep[] | null;
}

/** One search of research mode. */
export interface SearchStep {
  query: string;
  /** How many chunks it found. */
  results: number;
}

export type Rating = "up" | "down";

export interface Feedback {
  rating: Rating;
  comment: string | null;
  created_at: string;
}

export interface RatedAnswer {
  conversation_id: string;
  message_id: number;
  question: string;
  answer: string | null;
  citations: Citation[];
  feedback: Feedback;
}

export interface FeedbackList extends Page<RatedAnswer> {
  up: number;
  down: number;
}

export interface AskOptions extends SearchOptions {
  conversation_id?: string | null;
  /** Let the model plan the searches and search again for what is missing. */
  research?: boolean;
}

export interface Conversation {
  id: string;
  /** Null until the first question. */
  title: string | null;
  created_at: string;
  updated_at: string;
  /** The chat widget a website's visitor started it in. */
  widget_id?: string | null;
}

export interface ConversationMessage {
  id: number;
  role: "user" | "assistant";
  /** Null for an answer when the documents did not answer. */
  content: string | null;
  citations: Citation[];
  prompt_version: string | null;
  search_question: string | null;
  created_at: string;
  feedback: Feedback | null;
}

export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[];
}

export const WEBHOOK_EVENTS = [
  "file.uploaded",
  "file.deleted",
  "job.succeeded",
  "job.failed",
  "source.synced",
  "budget.alert",
] as const;
export type WebhookEvent = (typeof WEBHOOK_EVENTS)[number];

export interface Webhook {
  id: string;
  url: string;
  events: WebhookEvent[];
  description: string | null;
  created_at: string;
}

export interface CreatedWebhook extends Webhook {
  /** Signs every delivery; the API shows it only once. */
  secret: string;
}

export interface WebhookDelivery {
  id: string;
  event: WebhookEvent | "ping";
  status: "pending" | "delivered" | "failed";
  attempts: number;
  response_status: number | null;
  error: string | null;
  created_at: string;
  next_attempt_at: string | null;
  delivered_at: string | null;
  payload: Record<string, unknown>;
}


export interface ChatWidget {
  /** Public: it goes in the script tag. */
  id: string;
  project: string;
  name: string;
  welcome: string | null;
  accent: string;
  allowed_origins: string[];
  /** Its answers come only from files with any of these; [] for all files. */
  tags: string[];
  /** An https URL of the image in its header. */
  logo_url: string | null;
  created_at: string;
}

export interface ChatWidgetSettings {
  name: string;
  welcome: string | null;
  accent: string;
  allowed_origins: string[];
  tags: string[];
  logo_url: string | null;
}

/** The assistant that answers from a project. */
export interface Assistant {
  /** The name it goes by in its answers. */
  name: string | null;
  /** The owner's instructions on tone, style and what to say. */
  instructions: string | null;
}

/** website: a site's pages; feed: an RSS or Atom feed's entries; github: a repository's documents. */
export type SourceKind = "website" | "feed" | "github";

export interface WebsiteSource {
  id: string;
  kind: SourceKind;
  url: string;
  max_pages: number;
  /** 0: synced only when asked. */
  sync_interval_hours: number;
  pages_count: number;
  syncing: boolean;
  last_synced_at: string | null;
  next_sync_at: string | null;
  /** Why the last sync could not crawl the site; its pages are kept meanwhile. */
  last_error: string | null;
  /** Given to the pages it stores. */
  tags: string[];
  created_at: string;
}

export interface SourcePage {
  url: string;
  file_id: string;
  synced_at: string;
}

export type Scope = "read" | "write" | "ask" | "admin";
export const SCOPES: Scope[] = ["read", "write", "ask", "admin"];

export interface ApiKeyInfo {
  id: string;
  name: string;
  /** The start of the key, to recognise it. */
  prefix: string;
  scopes: Scope[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** A new key: `key` is returned only this once. */
export interface CreatedApiKey extends ApiKeyInfo {
  key: string;
}

export interface AuditEvent {
  id: number;
  action: string;
  target: string | null;
  details: Record<string, unknown>;
  /** The key that did it; null for the server's operators. */
  actor: { key_id: string; name: string | null } | null;
  request_id: string | null;
  created_at: string;
}

export interface EvaluationRun {
  id: string;
  dataset: string;
  dataset_version: string | null;
  cases: number;
  parameters: Record<string, string | number | null>;
  /** Retrieval: hit_rate, recall, mrr, above_min_score, rejected (0 to 1, or null). */
  metrics: Record<string, number | null>;
  /** Answers, when the run answered: answered, abstained, citation_precision, grounded, correct. */
  answer_metrics: Record<string, number | null> | null;
  version: string;
  created_at: string;
}
export type StudyKind = "summary" | "flashcards" | "quiz";

/** Items cite their passages by number, in `sources`. */
export interface KeyPoint {
  text: string;
  sources: number[];
}

export interface Flashcard {
  front: string;
  back: string;
  sources: number[];
}

export interface QuizQuestion {
  question: string;
  choices: string[];
  /** The position of the right choice, from 0. */
  answer: number;
  explanation: string;
  sources: number[];
}

export interface StudySource {
  number: number;
  chunk_index: number;
  page: number | null;
  section: string | null;
  text: string;
}

interface StudyBase {
  file_id: string;
  original_name: string;
  sources: StudySource[];
  prompt_version: string;
  usage: Usage;
  /** Chunks given to the model, of `chunks`: fewer for a long document. */
  passages: number;
  chunks: number;
}

export type StudyMaterial =
  | (StudyBase & { kind: "summary"; items: KeyPoint[] })
  | (StudyBase & { kind: "flashcards"; items: Flashcard[] })
  | (StudyBase & { kind: "quiz"; items: QuizQuestion[] });

export type ReviewGrade = "again" | "hard" | "good" | "easy";

export interface Deck {
  id: string;
  name: string;
  cards: number;
  /** Cards due for review now. */
  due: number;
  created_at: string;
}

export interface Card {
  id: string;
  front: string;
  back: string;
  source: { file_id: string | null; chunk_index: number | null; page: number | null; section: string | null };
  due_at: string;
  interval_days: number;
  ease: number;
  repetitions: number;
  lapses: number;
  last_reviewed_at: string | null;
  created_at: string;
}

/** A card due for review, with the days until it is due again for each grade. */
export interface ReviewCard extends Card {
  intervals: Record<ReviewGrade, number>;
}

export interface NewCard {
  front: string;
  back: string;
  file_id?: string | null;
  chunk_index?: number | null;
  page?: number | null;
  section?: string | null;
}
