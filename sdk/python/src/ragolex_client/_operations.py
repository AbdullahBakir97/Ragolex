"""Generated from sdk/openapi.json by sdk/python/generate.py: do not edit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypeVar

from ._types import UNSET, Unset, _body, _bytes, _list, _none, _path, _raw
from .models import (
    ApiKeyCreatedResponse,
    ApiKeyRequest,
    ApiKeyResponse,
    AskRequest,
    AskResponse,
    AssistantResponse,
    AssistantUpdateRequest,
    AuditListResponse,
    CardListResponse,
    CardRequest,
    CardResponse,
    CardsRequest,
    ChunkListResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    DeckRequest,
    DeckResponse,
    DeliveryListResponse,
    DeliveryResponse,
    FeedbackListResponse,
    FeedbackRequest,
    FileListResponse,
    FileResponse,
    FileTagsRequest,
    HealthResponse,
    IndexRequest,
    IndexResponse,
    JobListResponse,
    JobRequest,
    JobResponse,
    MeResponse,
    MessageResponse,
    ProcessRequest,
    ProcessResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectUsageResponse,
    ReviewQueueResponse,
    ReviewRequest,
    SearchFiltersRequest,
    SearchRequest,
    SearchResponse,
    SourceListResponse,
    SourcePagesResponse,
    SourceRequest,
    SourceResponse,
    StudyRequest,
    StudyResponse,
    TagListResponse,
    TenantUsageResponse,
    WebhookCreatedResponse,
    WebhookListResponse,
    WebhookRequest,
    WebhookResponse,
    WelcomeResponse,
    WidgetConfigResponse,
    WidgetListResponse,
    WidgetRequest,
    WidgetResponse,
    WidgetUpdateRequest,
)

T = TypeVar("T")


class Operations:
    """Every operation of the API, as a method named after its operationId."""

    def _request(self, method: str, path: str, *, query: dict[str, Any], json: Any,
                 response: Callable[[Any], T]) -> T:
        raise NotImplementedError

    def welcome(
        self,
    ) -> WelcomeResponse:
        """Service name and version
        """
        return self._request('GET', '/api/v1/', query={}, json=None, response=WelcomeResponse.model_validate)

    def health(
        self,
    ) -> HealthResponse:
        """Health check for load balancers and orchestrators
        """
        return self._request('GET', '/api/v1/health', query={}, json=None, response=HealthResponse.model_validate)

    def process_data(
        self,
        project_id: str,
        *,
        file_id: str,
        chunk_size: int | Unset = UNSET,
        overlap_size: int | Unset = UNSET,
    ) -> ProcessResponse:
        """Split an uploaded file into chunks and store them

        Processing a file again replaces its previous chunks. Read the chunks with GET /api/v1/projects/{project_id}/files/{file_id}/chunks.
        """
        return self._request('POST', f'/api/v1/data/process/{_path(project_id)}', query={}, json=_body(ProcessRequest, {'file_id': file_id, 'chunk_size': chunk_size, 'overlap_size': overlap_size}, optional=False), response=ProcessResponse.model_validate)

    def list_projects(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ProjectListResponse:
        """List projects in name order
        """
        return self._request('GET', '/api/v1/projects', query={'offset': offset, 'limit': limit}, json=None, response=ProjectListResponse.model_validate)

    def get_project(
        self,
        project_id: str,
    ) -> ProjectResponse:
        """Project details with file, chunk and index counts
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}', query={}, json=None, response=ProjectResponse.model_validate)

    def delete_project(
        self,
        project_id: str,
    ) -> None:
        """Delete a project with all its files, chunks, answers and conversations
        """
        return self._request('DELETE', f'/api/v1/projects/{_path(project_id)}', query={}, json=None, response=_none)

    def get_assistant(
        self,
        project_id: str,
    ) -> AssistantResponse:
        """The project's assistant: its name and its owner's instructions
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/assistant', query={}, json=None, response=AssistantResponse.model_validate)

    def update_assistant(
        self,
        project_id: str,
        *,
        name: str | None | Unset = UNSET,
        instructions: str | None | Unset = UNSET,
    ) -> AssistantResponse:
        """Change the project's assistant

        Only the fields sent change; null or blank clears one. Answers follow the instructions in the tone and style they set, but always answer from the documents only, with citations.
        """
        return self._request('PATCH', f'/api/v1/projects/{_path(project_id)}/assistant', query={}, json=_body(AssistantUpdateRequest, {'name': name, 'instructions': instructions}, optional=False), response=AssistantResponse.model_validate)

    def get_usage(
        self,
        project_id: str,
    ) -> ProjectUsageResponse:
        """Token usage and cost of the project's answers
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/usage', query={}, json=None, response=ProjectUsageResponse.model_validate)

    def list_files(
        self,
        project_id: str,
        *,
        tag: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> FileListResponse:
        """List a project's files in upload order
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/files', query={'tag': tag, 'offset': offset, 'limit': limit}, json=None, response=FileListResponse.model_validate)

    def set_file_tags(
        self,
        project_id: str,
        file_id: str,
        *,
        tags: list[str],
    ) -> FileResponse:
        """Replace a file's tags

        Tags group files into collections: searches, answers and widgets can be limited to files with some tags.
        """
        return self._request('PUT', f'/api/v1/projects/{_path(project_id)}/files/{_path(file_id)}/tags', query={}, json=_body(FileTagsRequest, {'tags': tags}, optional=False), response=FileResponse.model_validate)

    def list_tags(
        self,
        project_id: str,
    ) -> TagListResponse:
        """List a project's tags by name, with how many files have each
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/tags', query={}, json=None, response=TagListResponse.model_validate)

    def list_chunks(
        self,
        project_id: str,
        file_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ChunkListResponse:
        """List a file's chunks in order
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/files/{_path(file_id)}/chunks', query={'offset': offset, 'limit': limit}, json=None, response=ChunkListResponse.model_validate)

    def delete_file(
        self,
        project_id: str,
        file_id: str,
    ) -> None:
        """Delete a file with its chunks

        Answers that cited the file keep their copy of the cited text.
        """
        return self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/files/{_path(file_id)}', query={}, json=None, response=_none)

    def index_project(
        self,
        project_id: str,
        *,
        file_id: str | None | Unset = UNSET,
    ) -> IndexResponse:
        """Embed a project's chunks so they can be searched

        Embeds only chunks that have no embedding yet, in batches that are saved one by one: after a failure, calling again continues where it stopped, and after processing a file only its new chunks are embedded.
        """
        return self._request('POST', f'/api/v1/index/{_path(project_id)}', query={}, json=_body(IndexRequest, {'file_id': file_id}, optional=True), response=IndexResponse.model_validate)

    def create_job(
        self,
        project_id: str,
        *,
        file_id: str,
        chunk_size: int | Unset = UNSET,
        overlap_size: int | Unset = UNSET,
    ) -> JobResponse:
        """Process and index a file in the background

        The same work as POST /data/process and POST /index, done by a worker. Follow it with GET .../jobs/{job_id}.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/jobs', query={}, json=_body(JobRequest, {'file_id': file_id, 'chunk_size': chunk_size, 'overlap_size': overlap_size}, optional=False), response=JobResponse.model_validate)

    def list_jobs(
        self,
        project_id: str,
        *,
        status: Literal['queued', 'running', 'succeeded', 'failed'] | str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> JobListResponse:
        """List jobs, most recent first
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/jobs', query={'status': status, 'offset': offset, 'limit': limit}, json=None, response=JobListResponse.model_validate)

    def get_job(
        self,
        project_id: str,
        job_id: str,
    ) -> JobResponse:
        """A job's status and progress
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/jobs/{_path(job_id)}', query={}, json=None, response=JobResponse.model_validate)

    def retry_job(
        self,
        project_id: str,
        job_id: str,
    ) -> JobResponse:
        """Queue a failed job again
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/jobs/{_path(job_id)}/retry', query={}, json=None, response=JobResponse.model_validate)

    def create_source(
        self,
        project_id: str,
        *,
        url: str,
        max_pages: int | Unset = UNSET,
        sync_interval_hours: int | Unset = UNSET,
        tags: list[str] | Unset = UNSET,
    ) -> SourceResponse:
        """Keep a website's pages in the project

        The site's pages under the URL's folder are crawled, following their links (robots.txt is obeyed), and each page is stored as a file and processed and indexed in the background; then again every `sync_interval_hours`, adding new pages, replacing changed ones and deleting the ones that are gone. The first sync starts at once. The project is created if it has no files yet.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/sources', query={}, json=_body(SourceRequest, {'url': url, 'max_pages': max_pages, 'sync_interval_hours': sync_interval_hours, 'tags': tags}, optional=False), response=SourceResponse.model_validate)

    def list_sources(
        self,
        project_id: str,
    ) -> SourceListResponse:
        """List a project's sources
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/sources', query={}, json=None, response=SourceListResponse.model_validate)

    def get_source(
        self,
        project_id: str,
        source_id: str,
    ) -> SourceResponse:
        """A source
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/sources/{_path(source_id)}', query={}, json=None, response=SourceResponse.model_validate)

    def delete_source(
        self,
        project_id: str,
        source_id: str,
        *,
        keep_files: bool | None = None,
    ) -> None:
        """Stop syncing a source, and delete the files it stored
        """
        return self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/sources/{_path(source_id)}', query={'keep_files': keep_files}, json=None, response=_none)

    def list_source_pages(
        self,
        project_id: str,
        source_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> SourcePagesResponse:
        """The pages a source stored, in URL order
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/sources/{_path(source_id)}/pages', query={'offset': offset, 'limit': limit}, json=None, response=SourcePagesResponse.model_validate)

    def sync_source(
        self,
        project_id: str,
        source_id: str,
    ) -> SourceResponse:
        """Sync a source now

        A worker syncs it as soon as one is free.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/sources/{_path(source_id)}/sync', query={}, json=None, response=SourceResponse.model_validate)

    def create_webhook(
        self,
        project_id: str,
        *,
        url: str,
        events: list[Literal['file.uploaded', 'file.deleted', 'job.succeeded', 'job.failed', 'source.synced'] | str],
        description: str | None | Unset = UNSET,
    ) -> WebhookCreatedResponse:
        """Send a project's events to a URL

        Each event is POSTed as JSON, signed with the returned `secret` (see X-Ragolex-Signature), and retried for about 20 hours until the URL answers 2xx. The project is created if it has no files yet.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/webhooks', query={}, json=_body(WebhookRequest, {'url': url, 'events': events, 'description': description}, optional=False), response=WebhookCreatedResponse.model_validate)

    def list_webhooks(
        self,
        project_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> WebhookListResponse:
        """List a project's webhooks
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/webhooks', query={'offset': offset, 'limit': limit}, json=None, response=WebhookListResponse.model_validate)

    def get_webhook(
        self,
        project_id: str,
        webhook_id: str,
    ) -> WebhookResponse:
        """A webhook
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/webhooks/{_path(webhook_id)}', query={}, json=None, response=WebhookResponse.model_validate)

    def delete_webhook(
        self,
        project_id: str,
        webhook_id: str,
    ) -> None:
        """Stop sending events to a webhook, and forget its deliveries
        """
        return self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/webhooks/{_path(webhook_id)}', query={}, json=None, response=_none)

    def ping_webhook(
        self,
        project_id: str,
        webhook_id: str,
    ) -> DeliveryResponse:
        """Send a ping event, to check the webhook is reached
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/webhooks/{_path(webhook_id)}/ping', query={}, json=None, response=DeliveryResponse.model_validate)

    def list_deliveries(
        self,
        project_id: str,
        webhook_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> DeliveryListResponse:
        """What was sent to a webhook, most recent first
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/webhooks/{_path(webhook_id)}/deliveries', query={'offset': offset, 'limit': limit}, json=None, response=DeliveryListResponse.model_validate)

    def create_widget(
        self,
        project_id: str,
        *,
        name: str,
        allowed_origins: list[str],
        welcome: str | None | Unset = UNSET,
        accent: str | None | Unset = UNSET,
        tags: list[str] | Unset = UNSET,
        logo_url: str | None | Unset = UNSET,
    ) -> WidgetResponse:
        """Add a chat widget for a project's documents

        Embed it with `<script src="https://<web app>/widget.js" data-widget="<id>" async></script>`. Visitors of the allowed websites can then ask the project, without an API key.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/widgets', query={}, json=_body(WidgetRequest, {'name': name, 'welcome': welcome, 'accent': accent, 'allowed_origins': allowed_origins, 'tags': tags, 'logo_url': logo_url}, optional=False), response=WidgetResponse.model_validate)

    def list_widgets(
        self,
        project_id: str,
    ) -> WidgetListResponse:
        """List a project's chat widgets
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/widgets', query={}, json=None, response=WidgetListResponse.model_validate)

    def get_widget(
        self,
        project_id: str,
        widget_id: str,
    ) -> WidgetResponse:
        """A chat widget
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/widgets/{_path(widget_id)}', query={}, json=None, response=WidgetResponse.model_validate)

    def update_widget(
        self,
        project_id: str,
        widget_id: str,
        *,
        name: str | None | Unset = UNSET,
        welcome: str | None | Unset = UNSET,
        accent: str | None | Unset = UNSET,
        allowed_origins: list[str] | None | Unset = UNSET,
        tags: list[str] | None | Unset = UNSET,
        logo_url: str | None | Unset = UNSET,
    ) -> WidgetResponse:
        """Change a chat widget

        Only the fields sent change. Pages already open pick the changes up when they are loaded again.
        """
        return self._request('PATCH', f'/api/v1/projects/{_path(project_id)}/widgets/{_path(widget_id)}', query={}, json=_body(WidgetUpdateRequest, {'name': name, 'welcome': welcome, 'accent': accent, 'allowed_origins': allowed_origins, 'tags': tags, 'logo_url': logo_url}, optional=False), response=WidgetResponse.model_validate)

    def delete_widget(
        self,
        project_id: str,
        widget_id: str,
    ) -> None:
        """Remove a chat widget

        Pages that embed it stop showing it. The conversations visitors had in it stay with the project.
        """
        return self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/widgets/{_path(widget_id)}', query={}, json=None, response=_none)

    def widget_config(
        self,
        widget_id: str,
    ) -> WidgetConfigResponse:
        """What a widget shows
        """
        return self._request('GET', f'/api/v1/widgets/{_path(widget_id)}', query={}, json=None, response=WidgetConfigResponse.model_validate)

    def widget_feedback(
        self,
        conversation_id: str,
        message_id: int,
        widget_id: str,
        *,
        rating: Literal['up', 'down'] | str,
        comment: str | None | Unset = UNSET,
    ) -> None:
        """Rate an answer thumbs up or down

        Only in a conversation started in this widget. The rating shows with the project's other feedback.
        """
        return self._request('PUT', f'/api/v1/widgets/{_path(widget_id)}/conversations/{_path(conversation_id)}/messages/{_path(message_id)}/feedback', query={}, json=_body(FeedbackRequest, {'rating': rating, 'comment': comment}, optional=False), response=_none)

    def me(
        self,
    ) -> MeResponse:
        """The tenant and scopes of the API key used
        """
        return self._request('GET', '/api/v1/me', query={}, json=None, response=MeResponse.model_validate)

    def list_keys(
        self,
    ) -> list[ApiKeyResponse]:
        """The tenant's API keys, newest first
        """
        return self._request('GET', '/api/v1/keys', query={}, json=None, response=_list(ApiKeyResponse))

    def create_key(
        self,
        *,
        name: str,
        scopes: list[Literal['read', 'write', 'ask', 'admin'] | str],
    ) -> ApiKeyCreatedResponse:
        """Create an API key for the tenant

        The key is returned only once; only a hash of it is stored.
        """
        return self._request('POST', '/api/v1/keys', query={}, json=_body(ApiKeyRequest, {'name': name, 'scopes': scopes}, optional=False), response=ApiKeyCreatedResponse.model_validate)

    def revoke_key(
        self,
        key_id: str,
    ) -> None:
        """Revoke an API key

        It stops working at once.
        """
        return self._request('DELETE', f'/api/v1/keys/{_path(key_id)}', query={}, json=None, response=_none)

    def usage(
        self,
    ) -> TenantUsageResponse:
        """The tenant's usage this month, and its limits
        """
        return self._request('GET', '/api/v1/usage', query={}, json=None, response=TenantUsageResponse.model_validate)

    def list_audit_events(
        self,
        *,
        action: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> AuditListResponse:
        """The tenant's audit log, most recent first

        Administrative actions: API keys created and revoked, webhooks and chat widgets added, changed and removed, files and projects deleted, and limits changed, each with the key that did it and its request id. Kept as long as the tenant.
        """
        return self._request('GET', '/api/v1/audit', query={'action': action, 'offset': offset, 'limit': limit}, json=None, response=AuditListResponse.model_validate)

    def export_tenant(
        self,
    ) -> bytes:
        """Everything the tenant has, as a ZIP archive

        Every project with its files as uploaded, sources, chat widgets, webhooks (without their secrets), conversations with their feedback and answer usage, and the tenant's API keys (names and prefixes only) and audit log, as JSON files and the files themselves. Chunks and embeddings are left out: processing the files again makes them. `manifest.json` lists what is inside. Recorded in the audit log as `tenant.exported`.
        """
        return self._request('GET', '/api/v1/export', query={}, json=None, response=_bytes)

    def tool_schemas(
        self,
    ) -> list[dict[str, Any]]:
        """The MCP tools as function-calling schemas

        For agent frameworks that call functions rather than speak MCP: each tool's name, description and JSON Schema parameters, in the common `{"type": "function", "function": {...}}` form. Run a tool with POST /api/v1/mcp (tools/call) or the matching REST endpoint.
        """
        return self._request('GET', '/api/v1/tools', query={}, json=None, response=_raw)

    def search_project(
        self,
        project_id: str,
        *,
        query: str,
        top_k: int | Unset = UNSET,
        min_score: float | None | Unset = UNSET,
        filters: SearchFiltersRequest | dict[str, Any] | None | Unset = UNSET,
    ) -> SearchResponse:
        """Find the chunks that best match a question

        Searches the project's indexed chunks (see POST /api/v1/index/{project_id}), best match first: by meaning and by the query's words with SEARCH_MODE=hybrid (the default), by meaning only with vector. Scores are the cosine similarity either way. Chunks that are not indexed yet are not found.
        """
        return self._request('POST', f'/api/v1/search/{_path(project_id)}', query={}, json=_body(SearchRequest, {'query': query, 'top_k': top_k, 'min_score': min_score, 'filters': filters}, optional=False), response=SearchResponse.model_validate)

    def ask_project(
        self,
        project_id: str,
        *,
        question: str,
        top_k: int | Unset = UNSET,
        min_score: float | None | Unset = UNSET,
        conversation_id: str | None | Unset = UNSET,
        filters: SearchFiltersRequest | dict[str, Any] | None | Unset = UNSET,
    ) -> AskResponse:
        """Answer a question from the project's documents

        Finds the indexed chunks that best match the question and has a language model answer from them, citing each source as [n]. Signal `no_answer`, with `answer` null, means the documents do not answer the question. With `conversation_id`, the question is a follow-up: it is first rewritten into a standalone question from the conversation so far, and the question and the answer are added to the conversation.
        """
        return self._request('POST', f'/api/v1/ask/{_path(project_id)}', query={}, json=_body(AskRequest, {'question': question, 'top_k': top_k, 'min_score': min_score, 'conversation_id': conversation_id, 'filters': filters}, optional=False), response=AskResponse.model_validate)

    def create_conversation(
        self,
        project_id: str,
        *,
        title: str | None | Unset = UNSET,
    ) -> ConversationResponse:
        """Start a conversation

        Ask in it with POST /api/v1/ask/{project_id} and its `conversation_id`.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/conversations', query={}, json=_body(ConversationCreateRequest, {'title': title}, optional=True), response=ConversationResponse.model_validate)

    def list_conversations(
        self,
        project_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ConversationListResponse:
        """List conversations, most recent first
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/conversations', query={'offset': offset, 'limit': limit}, json=None, response=ConversationListResponse.model_validate)

    def get_conversation(
        self,
        project_id: str,
        conversation_id: str,
    ) -> ConversationDetailResponse:
        """A conversation with its questions and answers
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/conversations/{_path(conversation_id)}', query={}, json=None, response=ConversationDetailResponse.model_validate)

    def delete_conversation(
        self,
        project_id: str,
        conversation_id: str,
    ) -> None:
        """Delete a conversation and its messages
        """
        return self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/conversations/{_path(conversation_id)}', query={}, json=None, response=_none)

    def rate_answer(
        self,
        project_id: str,
        conversation_id: str,
        message_id: int,
        *,
        rating: Literal['up', 'down'] | str,
        comment: str | None | Unset = UNSET,
    ) -> MessageResponse:
        """Rate an answer thumbs up or down

        Replaces any rating the answer had. Rated answers can be reviewed with GET /api/v1/projects/{project_id}/feedback and exported as evaluation cases with `ragolex feedback-export`.
        """
        return self._request('PUT', f'/api/v1/projects/{_path(project_id)}/conversations/{_path(conversation_id)}/messages/{_path(message_id)}/feedback', query={}, json=_body(FeedbackRequest, {'rating': rating, 'comment': comment}, optional=False), response=MessageResponse.model_validate)

    def unrate_answer(
        self,
        project_id: str,
        conversation_id: str,
        message_id: int,
    ) -> None:
        """Remove an answer's rating
        """
        return self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/conversations/{_path(conversation_id)}/messages/{_path(message_id)}/feedback', query={}, json=None, response=_none)

    def list_feedback(
        self,
        project_id: str,
        *,
        rating: Literal['up', 'down'] | str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> FeedbackListResponse:
        """Rated answers, most recently rated first
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/feedback', query={'rating': rating, 'offset': offset, 'limit': limit}, json=None, response=FeedbackListResponse.model_validate)

    def study(
        self,
        project_id: str,
        *,
        file_id: str,
        kind: Literal['summary', 'flashcards', 'quiz'] | str,
        count: int | Unset = UNSET,
    ) -> StudyResponse:
        """Write a summary, flashcards or a quiz from a document

        Gives the document's chunks to the language model (spread evenly over a long document) and returns study material of the requested kind. Each item cites the passages it comes from, with their page or section. Costs a model call, counted like an answer in usage and the answer quota.
        """
        return self._request('POST', f'/api/v1/study/{_path(project_id)}', query={}, json=_body(StudyRequest, {'file_id': file_id, 'kind': kind, 'count': count}, optional=False), response=StudyResponse.model_validate)

    def list_decks(
        self,
        project_id: str,
    ) -> list[DeckResponse]:
        """List the project's decks, newest first
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks', query={}, json=None, response=_list(DeckResponse))

    def create_deck(
        self,
        project_id: str,
        *,
        name: str,
        cards: list[CardRequest | dict[str, Any]] | Unset = UNSET,
    ) -> DeckResponse:
        """Create a deck of flashcards

        Usually with the flashcards of `POST /study`; every card is new and due at once.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/decks', query={}, json=_body(DeckRequest, {'name': name, 'cards': cards}, optional=False), response=DeckResponse.model_validate)

    def get_deck(
        self,
        project_id: str,
        deck_id: str,
    ) -> DeckResponse:
        """A deck, with how many cards are due
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}', query={}, json=None, response=DeckResponse.model_validate)

    def delete_deck(
        self,
        project_id: str,
        deck_id: str,
    ) -> None:
        """Delete a deck and its cards
        """
        return self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}', query={}, json=None, response=_none)

    def list_cards(
        self,
        project_id: str,
        deck_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> CardListResponse:
        """A deck's cards, in order
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/cards', query={'offset': offset, 'limit': limit}, json=None, response=CardListResponse.model_validate)

    def add_cards(
        self,
        project_id: str,
        deck_id: str,
        *,
        cards: list[CardRequest | dict[str, Any]],
    ) -> DeckResponse:
        """Add cards to a deck

        After its other cards, new and due at once. A deck holds up to 2,000 cards.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/cards', query={}, json=_body(CardsRequest, {'cards': cards}, optional=False), response=DeckResponse.model_validate)

    def review_queue(
        self,
        project_id: str,
        deck_id: str,
        *,
        limit: int | None = None,
    ) -> ReviewQueueResponse:
        """The cards due for review now

        The longest due first, each with the interval every grade would give it. Review them one at a time with `POST .../review`.
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/review', query={'limit': limit}, json=None, response=ReviewQueueResponse.model_validate)

    def review_card(
        self,
        project_id: str,
        deck_id: str,
        card_id: str,
        *,
        grade: Literal['again', 'hard', 'good', 'easy'] | str,
    ) -> CardResponse:
        """Grade a review of a card, and schedule its next one

        Spaced repetition as in Anki: `again` brings the card back in ten minutes, the other grades in days that grow with each good review.
        """
        return self._request('POST', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/cards/{_path(card_id)}/review', query={}, json=_body(ReviewRequest, {'grade': grade}, optional=False), response=CardResponse.model_validate)

    def export_anki(
        self,
        project_id: str,
        deck_id: str,
    ) -> bytes:
        """Export a deck for Anki

        A text file to import in Anki (File > Import): one Basic note per card, into a deck of the same name, tagged `ragolex` and the project's name, with the document and page each card comes from.
        """
        return self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/anki', query={}, json=None, response=_bytes)


class AsyncOperations:
    """Every operation of the API, as an async method named after its operationId."""

    async def _request(self, method: str, path: str, *, query: dict[str, Any], json: Any,
                       response: Callable[[Any], T]) -> T:
        raise NotImplementedError

    async def welcome(
        self,
    ) -> WelcomeResponse:
        """Service name and version
        """
        return await self._request('GET', '/api/v1/', query={}, json=None, response=WelcomeResponse.model_validate)

    async def health(
        self,
    ) -> HealthResponse:
        """Health check for load balancers and orchestrators
        """
        return await self._request('GET', '/api/v1/health', query={}, json=None, response=HealthResponse.model_validate)

    async def process_data(
        self,
        project_id: str,
        *,
        file_id: str,
        chunk_size: int | Unset = UNSET,
        overlap_size: int | Unset = UNSET,
    ) -> ProcessResponse:
        """Split an uploaded file into chunks and store them

        Processing a file again replaces its previous chunks. Read the chunks with GET /api/v1/projects/{project_id}/files/{file_id}/chunks.
        """
        return await self._request('POST', f'/api/v1/data/process/{_path(project_id)}', query={}, json=_body(ProcessRequest, {'file_id': file_id, 'chunk_size': chunk_size, 'overlap_size': overlap_size}, optional=False), response=ProcessResponse.model_validate)

    async def list_projects(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ProjectListResponse:
        """List projects in name order
        """
        return await self._request('GET', '/api/v1/projects', query={'offset': offset, 'limit': limit}, json=None, response=ProjectListResponse.model_validate)

    async def get_project(
        self,
        project_id: str,
    ) -> ProjectResponse:
        """Project details with file, chunk and index counts
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}', query={}, json=None, response=ProjectResponse.model_validate)

    async def delete_project(
        self,
        project_id: str,
    ) -> None:
        """Delete a project with all its files, chunks, answers and conversations
        """
        return await self._request('DELETE', f'/api/v1/projects/{_path(project_id)}', query={}, json=None, response=_none)

    async def get_assistant(
        self,
        project_id: str,
    ) -> AssistantResponse:
        """The project's assistant: its name and its owner's instructions
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/assistant', query={}, json=None, response=AssistantResponse.model_validate)

    async def update_assistant(
        self,
        project_id: str,
        *,
        name: str | None | Unset = UNSET,
        instructions: str | None | Unset = UNSET,
    ) -> AssistantResponse:
        """Change the project's assistant

        Only the fields sent change; null or blank clears one. Answers follow the instructions in the tone and style they set, but always answer from the documents only, with citations.
        """
        return await self._request('PATCH', f'/api/v1/projects/{_path(project_id)}/assistant', query={}, json=_body(AssistantUpdateRequest, {'name': name, 'instructions': instructions}, optional=False), response=AssistantResponse.model_validate)

    async def get_usage(
        self,
        project_id: str,
    ) -> ProjectUsageResponse:
        """Token usage and cost of the project's answers
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/usage', query={}, json=None, response=ProjectUsageResponse.model_validate)

    async def list_files(
        self,
        project_id: str,
        *,
        tag: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> FileListResponse:
        """List a project's files in upload order
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/files', query={'tag': tag, 'offset': offset, 'limit': limit}, json=None, response=FileListResponse.model_validate)

    async def set_file_tags(
        self,
        project_id: str,
        file_id: str,
        *,
        tags: list[str],
    ) -> FileResponse:
        """Replace a file's tags

        Tags group files into collections: searches, answers and widgets can be limited to files with some tags.
        """
        return await self._request('PUT', f'/api/v1/projects/{_path(project_id)}/files/{_path(file_id)}/tags', query={}, json=_body(FileTagsRequest, {'tags': tags}, optional=False), response=FileResponse.model_validate)

    async def list_tags(
        self,
        project_id: str,
    ) -> TagListResponse:
        """List a project's tags by name, with how many files have each
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/tags', query={}, json=None, response=TagListResponse.model_validate)

    async def list_chunks(
        self,
        project_id: str,
        file_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ChunkListResponse:
        """List a file's chunks in order
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/files/{_path(file_id)}/chunks', query={'offset': offset, 'limit': limit}, json=None, response=ChunkListResponse.model_validate)

    async def delete_file(
        self,
        project_id: str,
        file_id: str,
    ) -> None:
        """Delete a file with its chunks

        Answers that cited the file keep their copy of the cited text.
        """
        return await self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/files/{_path(file_id)}', query={}, json=None, response=_none)

    async def index_project(
        self,
        project_id: str,
        *,
        file_id: str | None | Unset = UNSET,
    ) -> IndexResponse:
        """Embed a project's chunks so they can be searched

        Embeds only chunks that have no embedding yet, in batches that are saved one by one: after a failure, calling again continues where it stopped, and after processing a file only its new chunks are embedded.
        """
        return await self._request('POST', f'/api/v1/index/{_path(project_id)}', query={}, json=_body(IndexRequest, {'file_id': file_id}, optional=True), response=IndexResponse.model_validate)

    async def create_job(
        self,
        project_id: str,
        *,
        file_id: str,
        chunk_size: int | Unset = UNSET,
        overlap_size: int | Unset = UNSET,
    ) -> JobResponse:
        """Process and index a file in the background

        The same work as POST /data/process and POST /index, done by a worker. Follow it with GET .../jobs/{job_id}.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/jobs', query={}, json=_body(JobRequest, {'file_id': file_id, 'chunk_size': chunk_size, 'overlap_size': overlap_size}, optional=False), response=JobResponse.model_validate)

    async def list_jobs(
        self,
        project_id: str,
        *,
        status: Literal['queued', 'running', 'succeeded', 'failed'] | str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> JobListResponse:
        """List jobs, most recent first
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/jobs', query={'status': status, 'offset': offset, 'limit': limit}, json=None, response=JobListResponse.model_validate)

    async def get_job(
        self,
        project_id: str,
        job_id: str,
    ) -> JobResponse:
        """A job's status and progress
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/jobs/{_path(job_id)}', query={}, json=None, response=JobResponse.model_validate)

    async def retry_job(
        self,
        project_id: str,
        job_id: str,
    ) -> JobResponse:
        """Queue a failed job again
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/jobs/{_path(job_id)}/retry', query={}, json=None, response=JobResponse.model_validate)

    async def create_source(
        self,
        project_id: str,
        *,
        url: str,
        max_pages: int | Unset = UNSET,
        sync_interval_hours: int | Unset = UNSET,
        tags: list[str] | Unset = UNSET,
    ) -> SourceResponse:
        """Keep a website's pages in the project

        The site's pages under the URL's folder are crawled, following their links (robots.txt is obeyed), and each page is stored as a file and processed and indexed in the background; then again every `sync_interval_hours`, adding new pages, replacing changed ones and deleting the ones that are gone. The first sync starts at once. The project is created if it has no files yet.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/sources', query={}, json=_body(SourceRequest, {'url': url, 'max_pages': max_pages, 'sync_interval_hours': sync_interval_hours, 'tags': tags}, optional=False), response=SourceResponse.model_validate)

    async def list_sources(
        self,
        project_id: str,
    ) -> SourceListResponse:
        """List a project's sources
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/sources', query={}, json=None, response=SourceListResponse.model_validate)

    async def get_source(
        self,
        project_id: str,
        source_id: str,
    ) -> SourceResponse:
        """A source
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/sources/{_path(source_id)}', query={}, json=None, response=SourceResponse.model_validate)

    async def delete_source(
        self,
        project_id: str,
        source_id: str,
        *,
        keep_files: bool | None = None,
    ) -> None:
        """Stop syncing a source, and delete the files it stored
        """
        return await self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/sources/{_path(source_id)}', query={'keep_files': keep_files}, json=None, response=_none)

    async def list_source_pages(
        self,
        project_id: str,
        source_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> SourcePagesResponse:
        """The pages a source stored, in URL order
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/sources/{_path(source_id)}/pages', query={'offset': offset, 'limit': limit}, json=None, response=SourcePagesResponse.model_validate)

    async def sync_source(
        self,
        project_id: str,
        source_id: str,
    ) -> SourceResponse:
        """Sync a source now

        A worker syncs it as soon as one is free.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/sources/{_path(source_id)}/sync', query={}, json=None, response=SourceResponse.model_validate)

    async def create_webhook(
        self,
        project_id: str,
        *,
        url: str,
        events: list[Literal['file.uploaded', 'file.deleted', 'job.succeeded', 'job.failed', 'source.synced'] | str],
        description: str | None | Unset = UNSET,
    ) -> WebhookCreatedResponse:
        """Send a project's events to a URL

        Each event is POSTed as JSON, signed with the returned `secret` (see X-Ragolex-Signature), and retried for about 20 hours until the URL answers 2xx. The project is created if it has no files yet.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/webhooks', query={}, json=_body(WebhookRequest, {'url': url, 'events': events, 'description': description}, optional=False), response=WebhookCreatedResponse.model_validate)

    async def list_webhooks(
        self,
        project_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> WebhookListResponse:
        """List a project's webhooks
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/webhooks', query={'offset': offset, 'limit': limit}, json=None, response=WebhookListResponse.model_validate)

    async def get_webhook(
        self,
        project_id: str,
        webhook_id: str,
    ) -> WebhookResponse:
        """A webhook
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/webhooks/{_path(webhook_id)}', query={}, json=None, response=WebhookResponse.model_validate)

    async def delete_webhook(
        self,
        project_id: str,
        webhook_id: str,
    ) -> None:
        """Stop sending events to a webhook, and forget its deliveries
        """
        return await self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/webhooks/{_path(webhook_id)}', query={}, json=None, response=_none)

    async def ping_webhook(
        self,
        project_id: str,
        webhook_id: str,
    ) -> DeliveryResponse:
        """Send a ping event, to check the webhook is reached
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/webhooks/{_path(webhook_id)}/ping', query={}, json=None, response=DeliveryResponse.model_validate)

    async def list_deliveries(
        self,
        project_id: str,
        webhook_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> DeliveryListResponse:
        """What was sent to a webhook, most recent first
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/webhooks/{_path(webhook_id)}/deliveries', query={'offset': offset, 'limit': limit}, json=None, response=DeliveryListResponse.model_validate)

    async def create_widget(
        self,
        project_id: str,
        *,
        name: str,
        allowed_origins: list[str],
        welcome: str | None | Unset = UNSET,
        accent: str | None | Unset = UNSET,
        tags: list[str] | Unset = UNSET,
        logo_url: str | None | Unset = UNSET,
    ) -> WidgetResponse:
        """Add a chat widget for a project's documents

        Embed it with `<script src="https://<web app>/widget.js" data-widget="<id>" async></script>`. Visitors of the allowed websites can then ask the project, without an API key.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/widgets', query={}, json=_body(WidgetRequest, {'name': name, 'welcome': welcome, 'accent': accent, 'allowed_origins': allowed_origins, 'tags': tags, 'logo_url': logo_url}, optional=False), response=WidgetResponse.model_validate)

    async def list_widgets(
        self,
        project_id: str,
    ) -> WidgetListResponse:
        """List a project's chat widgets
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/widgets', query={}, json=None, response=WidgetListResponse.model_validate)

    async def get_widget(
        self,
        project_id: str,
        widget_id: str,
    ) -> WidgetResponse:
        """A chat widget
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/widgets/{_path(widget_id)}', query={}, json=None, response=WidgetResponse.model_validate)

    async def update_widget(
        self,
        project_id: str,
        widget_id: str,
        *,
        name: str | None | Unset = UNSET,
        welcome: str | None | Unset = UNSET,
        accent: str | None | Unset = UNSET,
        allowed_origins: list[str] | None | Unset = UNSET,
        tags: list[str] | None | Unset = UNSET,
        logo_url: str | None | Unset = UNSET,
    ) -> WidgetResponse:
        """Change a chat widget

        Only the fields sent change. Pages already open pick the changes up when they are loaded again.
        """
        return await self._request('PATCH', f'/api/v1/projects/{_path(project_id)}/widgets/{_path(widget_id)}', query={}, json=_body(WidgetUpdateRequest, {'name': name, 'welcome': welcome, 'accent': accent, 'allowed_origins': allowed_origins, 'tags': tags, 'logo_url': logo_url}, optional=False), response=WidgetResponse.model_validate)

    async def delete_widget(
        self,
        project_id: str,
        widget_id: str,
    ) -> None:
        """Remove a chat widget

        Pages that embed it stop showing it. The conversations visitors had in it stay with the project.
        """
        return await self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/widgets/{_path(widget_id)}', query={}, json=None, response=_none)

    async def widget_config(
        self,
        widget_id: str,
    ) -> WidgetConfigResponse:
        """What a widget shows
        """
        return await self._request('GET', f'/api/v1/widgets/{_path(widget_id)}', query={}, json=None, response=WidgetConfigResponse.model_validate)

    async def widget_feedback(
        self,
        conversation_id: str,
        message_id: int,
        widget_id: str,
        *,
        rating: Literal['up', 'down'] | str,
        comment: str | None | Unset = UNSET,
    ) -> None:
        """Rate an answer thumbs up or down

        Only in a conversation started in this widget. The rating shows with the project's other feedback.
        """
        return await self._request('PUT', f'/api/v1/widgets/{_path(widget_id)}/conversations/{_path(conversation_id)}/messages/{_path(message_id)}/feedback', query={}, json=_body(FeedbackRequest, {'rating': rating, 'comment': comment}, optional=False), response=_none)

    async def me(
        self,
    ) -> MeResponse:
        """The tenant and scopes of the API key used
        """
        return await self._request('GET', '/api/v1/me', query={}, json=None, response=MeResponse.model_validate)

    async def list_keys(
        self,
    ) -> list[ApiKeyResponse]:
        """The tenant's API keys, newest first
        """
        return await self._request('GET', '/api/v1/keys', query={}, json=None, response=_list(ApiKeyResponse))

    async def create_key(
        self,
        *,
        name: str,
        scopes: list[Literal['read', 'write', 'ask', 'admin'] | str],
    ) -> ApiKeyCreatedResponse:
        """Create an API key for the tenant

        The key is returned only once; only a hash of it is stored.
        """
        return await self._request('POST', '/api/v1/keys', query={}, json=_body(ApiKeyRequest, {'name': name, 'scopes': scopes}, optional=False), response=ApiKeyCreatedResponse.model_validate)

    async def revoke_key(
        self,
        key_id: str,
    ) -> None:
        """Revoke an API key

        It stops working at once.
        """
        return await self._request('DELETE', f'/api/v1/keys/{_path(key_id)}', query={}, json=None, response=_none)

    async def usage(
        self,
    ) -> TenantUsageResponse:
        """The tenant's usage this month, and its limits
        """
        return await self._request('GET', '/api/v1/usage', query={}, json=None, response=TenantUsageResponse.model_validate)

    async def list_audit_events(
        self,
        *,
        action: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> AuditListResponse:
        """The tenant's audit log, most recent first

        Administrative actions: API keys created and revoked, webhooks and chat widgets added, changed and removed, files and projects deleted, and limits changed, each with the key that did it and its request id. Kept as long as the tenant.
        """
        return await self._request('GET', '/api/v1/audit', query={'action': action, 'offset': offset, 'limit': limit}, json=None, response=AuditListResponse.model_validate)

    async def export_tenant(
        self,
    ) -> bytes:
        """Everything the tenant has, as a ZIP archive

        Every project with its files as uploaded, sources, chat widgets, webhooks (without their secrets), conversations with their feedback and answer usage, and the tenant's API keys (names and prefixes only) and audit log, as JSON files and the files themselves. Chunks and embeddings are left out: processing the files again makes them. `manifest.json` lists what is inside. Recorded in the audit log as `tenant.exported`.
        """
        return await self._request('GET', '/api/v1/export', query={}, json=None, response=_bytes)

    async def tool_schemas(
        self,
    ) -> list[dict[str, Any]]:
        """The MCP tools as function-calling schemas

        For agent frameworks that call functions rather than speak MCP: each tool's name, description and JSON Schema parameters, in the common `{"type": "function", "function": {...}}` form. Run a tool with POST /api/v1/mcp (tools/call) or the matching REST endpoint.
        """
        return await self._request('GET', '/api/v1/tools', query={}, json=None, response=_raw)

    async def search_project(
        self,
        project_id: str,
        *,
        query: str,
        top_k: int | Unset = UNSET,
        min_score: float | None | Unset = UNSET,
        filters: SearchFiltersRequest | dict[str, Any] | None | Unset = UNSET,
    ) -> SearchResponse:
        """Find the chunks that best match a question

        Searches the project's indexed chunks (see POST /api/v1/index/{project_id}), best match first: by meaning and by the query's words with SEARCH_MODE=hybrid (the default), by meaning only with vector. Scores are the cosine similarity either way. Chunks that are not indexed yet are not found.
        """
        return await self._request('POST', f'/api/v1/search/{_path(project_id)}', query={}, json=_body(SearchRequest, {'query': query, 'top_k': top_k, 'min_score': min_score, 'filters': filters}, optional=False), response=SearchResponse.model_validate)

    async def ask_project(
        self,
        project_id: str,
        *,
        question: str,
        top_k: int | Unset = UNSET,
        min_score: float | None | Unset = UNSET,
        conversation_id: str | None | Unset = UNSET,
        filters: SearchFiltersRequest | dict[str, Any] | None | Unset = UNSET,
    ) -> AskResponse:
        """Answer a question from the project's documents

        Finds the indexed chunks that best match the question and has a language model answer from them, citing each source as [n]. Signal `no_answer`, with `answer` null, means the documents do not answer the question. With `conversation_id`, the question is a follow-up: it is first rewritten into a standalone question from the conversation so far, and the question and the answer are added to the conversation.
        """
        return await self._request('POST', f'/api/v1/ask/{_path(project_id)}', query={}, json=_body(AskRequest, {'question': question, 'top_k': top_k, 'min_score': min_score, 'conversation_id': conversation_id, 'filters': filters}, optional=False), response=AskResponse.model_validate)

    async def create_conversation(
        self,
        project_id: str,
        *,
        title: str | None | Unset = UNSET,
    ) -> ConversationResponse:
        """Start a conversation

        Ask in it with POST /api/v1/ask/{project_id} and its `conversation_id`.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/conversations', query={}, json=_body(ConversationCreateRequest, {'title': title}, optional=True), response=ConversationResponse.model_validate)

    async def list_conversations(
        self,
        project_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ConversationListResponse:
        """List conversations, most recent first
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/conversations', query={'offset': offset, 'limit': limit}, json=None, response=ConversationListResponse.model_validate)

    async def get_conversation(
        self,
        project_id: str,
        conversation_id: str,
    ) -> ConversationDetailResponse:
        """A conversation with its questions and answers
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/conversations/{_path(conversation_id)}', query={}, json=None, response=ConversationDetailResponse.model_validate)

    async def delete_conversation(
        self,
        project_id: str,
        conversation_id: str,
    ) -> None:
        """Delete a conversation and its messages
        """
        return await self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/conversations/{_path(conversation_id)}', query={}, json=None, response=_none)

    async def rate_answer(
        self,
        project_id: str,
        conversation_id: str,
        message_id: int,
        *,
        rating: Literal['up', 'down'] | str,
        comment: str | None | Unset = UNSET,
    ) -> MessageResponse:
        """Rate an answer thumbs up or down

        Replaces any rating the answer had. Rated answers can be reviewed with GET /api/v1/projects/{project_id}/feedback and exported as evaluation cases with `ragolex feedback-export`.
        """
        return await self._request('PUT', f'/api/v1/projects/{_path(project_id)}/conversations/{_path(conversation_id)}/messages/{_path(message_id)}/feedback', query={}, json=_body(FeedbackRequest, {'rating': rating, 'comment': comment}, optional=False), response=MessageResponse.model_validate)

    async def unrate_answer(
        self,
        project_id: str,
        conversation_id: str,
        message_id: int,
    ) -> None:
        """Remove an answer's rating
        """
        return await self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/conversations/{_path(conversation_id)}/messages/{_path(message_id)}/feedback', query={}, json=None, response=_none)

    async def list_feedback(
        self,
        project_id: str,
        *,
        rating: Literal['up', 'down'] | str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> FeedbackListResponse:
        """Rated answers, most recently rated first
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/feedback', query={'rating': rating, 'offset': offset, 'limit': limit}, json=None, response=FeedbackListResponse.model_validate)

    async def study(
        self,
        project_id: str,
        *,
        file_id: str,
        kind: Literal['summary', 'flashcards', 'quiz'] | str,
        count: int | Unset = UNSET,
    ) -> StudyResponse:
        """Write a summary, flashcards or a quiz from a document

        Gives the document's chunks to the language model (spread evenly over a long document) and returns study material of the requested kind. Each item cites the passages it comes from, with their page or section. Costs a model call, counted like an answer in usage and the answer quota.
        """
        return await self._request('POST', f'/api/v1/study/{_path(project_id)}', query={}, json=_body(StudyRequest, {'file_id': file_id, 'kind': kind, 'count': count}, optional=False), response=StudyResponse.model_validate)

    async def list_decks(
        self,
        project_id: str,
    ) -> list[DeckResponse]:
        """List the project's decks, newest first
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks', query={}, json=None, response=_list(DeckResponse))

    async def create_deck(
        self,
        project_id: str,
        *,
        name: str,
        cards: list[CardRequest | dict[str, Any]] | Unset = UNSET,
    ) -> DeckResponse:
        """Create a deck of flashcards

        Usually with the flashcards of `POST /study`; every card is new and due at once.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/decks', query={}, json=_body(DeckRequest, {'name': name, 'cards': cards}, optional=False), response=DeckResponse.model_validate)

    async def get_deck(
        self,
        project_id: str,
        deck_id: str,
    ) -> DeckResponse:
        """A deck, with how many cards are due
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}', query={}, json=None, response=DeckResponse.model_validate)

    async def delete_deck(
        self,
        project_id: str,
        deck_id: str,
    ) -> None:
        """Delete a deck and its cards
        """
        return await self._request('DELETE', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}', query={}, json=None, response=_none)

    async def list_cards(
        self,
        project_id: str,
        deck_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> CardListResponse:
        """A deck's cards, in order
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/cards', query={'offset': offset, 'limit': limit}, json=None, response=CardListResponse.model_validate)

    async def add_cards(
        self,
        project_id: str,
        deck_id: str,
        *,
        cards: list[CardRequest | dict[str, Any]],
    ) -> DeckResponse:
        """Add cards to a deck

        After its other cards, new and due at once. A deck holds up to 2,000 cards.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/cards', query={}, json=_body(CardsRequest, {'cards': cards}, optional=False), response=DeckResponse.model_validate)

    async def review_queue(
        self,
        project_id: str,
        deck_id: str,
        *,
        limit: int | None = None,
    ) -> ReviewQueueResponse:
        """The cards due for review now

        The longest due first, each with the interval every grade would give it. Review them one at a time with `POST .../review`.
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/review', query={'limit': limit}, json=None, response=ReviewQueueResponse.model_validate)

    async def review_card(
        self,
        project_id: str,
        deck_id: str,
        card_id: str,
        *,
        grade: Literal['again', 'hard', 'good', 'easy'] | str,
    ) -> CardResponse:
        """Grade a review of a card, and schedule its next one

        Spaced repetition as in Anki: `again` brings the card back in ten minutes, the other grades in days that grow with each good review.
        """
        return await self._request('POST', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/cards/{_path(card_id)}/review', query={}, json=_body(ReviewRequest, {'grade': grade}, optional=False), response=CardResponse.model_validate)

    async def export_anki(
        self,
        project_id: str,
        deck_id: str,
    ) -> bytes:
        """Export a deck for Anki

        A text file to import in Anki (File > Import): one Basic note per card, into a deck of the same name, tagged `ragolex` and the project's name, with the document and page each card comes from.
        """
        return await self._request('GET', f'/api/v1/projects/{_path(project_id)}/decks/{_path(deck_id)}/anki', query={}, json=None, response=_bytes)


__all__ = ['AsyncOperations', 'Operations']
