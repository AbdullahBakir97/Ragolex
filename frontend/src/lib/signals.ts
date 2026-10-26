// What each error signal of the API means to someone using the app.

const MESSAGES: Record<string, string> = {
  file_type_not_supported: "Only PDF, Word, Markdown, HTML, text and source code files can be uploaded.",
  file_size_exceeded: "The file is larger than the server allows.",
  file_content_mismatch: "The file's content is not of its type, for example a program named like a text file.",
  file_infected: "The malware scanner found malware in this file, so it was not kept.",
  malware_scan_failed: "The file could not be scanned for malware, so it was not kept. Try again later.",
  file_upload_failed: "The file could not be saved. Try again.",
  file_not_found: "That file does not exist in this project.",
  project_not_found: "This project has no documents yet.",
  conversation_not_found: "This conversation no longer exists.",
  message_not_found: "This answer no longer exists, so it cannot be rated.",
  file_has_no_text: "No text could be read from the file. Scanned PDFs need OCR first.",
  processing_failed: "The file could not be split into chunks.",
  embedding_not_configured:
    "No embedding model is configured. Set OPENAI_API_KEY or EMBEDDING_BASE_URL on the server.",
  embedding_failed:
    "The embedding model failed: it was unreachable, rejected the request or sent an unexpected reply. The API's log says which.",
  llm_not_configured:
    "No language model is configured. Set OPENAI_API_KEY or LLM_BASE_URL on the server.",
  llm_failed:
    "The language model failed: it was unreachable, rejected the request or sent an unexpected reply. The API's log says which.",
  job_failed: "Processing the file failed unexpectedly. The API's log says why.",
  job_abandoned: "The worker processing the file stopped, on every attempt.",
  job_not_found: "That job does not exist in this project.",
  job_not_failed: "Only a failed job can be retried.",
  webhook_not_found: "That webhook no longer exists.",
  webhook_url_not_allowed:
    "Webhooks may not reach this server's network (localhost or private addresses). Set WEBHOOK_ALLOW_PRIVATE_URLS=true on the server to allow it.",
  source_not_found: "That website source no longer exists.",
  source_url_not_allowed:
    "Websites on this server's network (localhost or private addresses) cannot be crawled. Set CRAWLER_ALLOW_PRIVATE_URLS=true on the server to allow it.",
  widget_not_found: "That chat widget no longer exists.",
  widget_origin_invalid:
    "An allowed origin is not a website's origin. Use the scheme, host and any port only, like https://example.com.",
  origin_not_allowed: "This website may not use the widget. Add it to the widget's allowed origins.",
  api_key_required: "This server needs an API key.",
  api_key_invalid: "The API key is unknown or was revoked.",
  api_key_scope_missing: "Your API key may not do this. Ask for a key with the scope it needs.",
  api_key_not_found: "That API key does not exist.",
  rate_limited: "Too many requests this minute. Wait a moment and try again.",
  answer_quota_exceeded: "This month's answers are used up. Ask the administrator for a higher quota.",
  budget_exceeded: "This month's budget for answers is spent. Ask the administrator to raise it.",
  storage_quota_exceeded: "The file does not fit in the storage left. Delete files or ask for more room.",
  internal_error: "The server failed unexpectedly. Its log has the details, under the request's id.",
  validation_error: "The request was not valid.",
  network_error: "The server could not be reached. Is the API running?",
};

export function signalMessage(signal: string): string {
  return MESSAGES[signal] ?? `The server reported an error (${signal}).`;
}
