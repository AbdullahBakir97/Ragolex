import secrets
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from mini_rag.core.errors import (
    ConversationNotFound,
    OriginNotAllowed,
    ProjectNotFound,
    WidgetNotFound,
    WidgetOriginInvalid,
)
from mini_rag.domain.models import Conversation, Project, Widget
from mini_rag.domain.repositories import UnitOfWork
from mini_rag.services.audit import record
from mini_rag.services.tag_service import clean_tags

WIDGET_PREFIX = "wgt_"
DEFAULT_ACCENT = "#2563eb"
ANY_ORIGIN = "*"
_DEFAULT_PORTS = {"http": 80, "https": 443}


def generate_widget_id() -> str:
    """A new widget id: public, but random, so widgets cannot be listed by guessing."""
    return WIDGET_PREFIX + secrets.token_urlsafe(16)


def normalize_origin(origin: str) -> str:
    """``origin`` as browsers send it (``https://example.com``), or ``*`` for any.

    Raises WidgetOriginInvalid for anything else, such as a URL with a path.
    """
    origin = origin.strip()
    if origin == ANY_ORIGIN:
        return origin
    try:
        parts = urlsplit(origin)
        port = parts.port
    except ValueError:
        raise WidgetOriginInvalid(f"{origin} is not a website origin") from None
    if (parts.scheme not in _DEFAULT_PORTS or not parts.hostname or parts.username
            or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise WidgetOriginInvalid(
            f"{origin} is not a website origin, like https://example.com") from None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    shown_port = f":{port}" if port and port != _DEFAULT_PORTS[parts.scheme] else ""
    return f"{parts.scheme}://{host}{shown_port}"


def origin_allowed(widget: Widget, origin: str | None, host: str | None = None) -> bool:
    """Whether a page on ``origin`` may use the widget, asking the server at ``host``.

    Browsers send the Origin header with every request a page on another
    website makes, so such a page is refused unless its website is allowed.
    A request without the header is not from another website's page: it
    is the same site, or not a browser, which could send any Origin anyway.
    Pages on the server's own host (the web app, e.g. its widget preview)
    may use every widget; pages cannot set the Host header.
    """
    if origin is None or ANY_ORIGIN in widget.allowed_origins:
        return True
    try:
        parts = urlsplit(origin)
        if host and parts.netloc.lower() == host.lower():
            return True
        return normalize_origin(origin) in widget.allowed_origins
    except (ValueError, WidgetOriginInvalid):
        return False  # e.g. "null", from a sandboxed frame or a local file


class WidgetService:
    """Manages a project's chat widgets, and lets the widgets' visitors in."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def create(self, project_name: str, name: str, welcome: str | None, accent: str | None,
                     allowed_origins: Sequence[str], tags: Sequence[str] = (),
                     logo_url: str | None = None) -> Widget:
        """``tags``, when given, limit its answers to files with any of them."""
        project = await self._project(project_name)
        widget = await self.uow.widgets.create(
            widget_id=generate_widget_id(), project_id=project.id, name=name.strip(),
            welcome=_text(welcome), accent=_accent(accent or DEFAULT_ACCENT),
            allowed_origins=_origins(allowed_origins), tags=clean_tags(tags),
            logo_url=_text(logo_url))
        await record(self.uow, project.tenant_id, "widget.created", widget.id,
                     project=project.name, name=widget.name,
                     allowed_origins=list(widget.allowed_origins), tags=list(widget.tags))
        await self.uow.commit()
        return widget

    async def list(self, project_name: str) -> list[Widget]:
        project = await self._project(project_name)
        return await self.uow.widgets.list_for_project(project.id)

    async def get(self, project_name: str, widget_id: str) -> Widget:
        project = await self._project(project_name)
        widget = await self.uow.widgets.get(widget_id)
        if widget is None or widget.project_id != project.id:
            raise WidgetNotFound()
        return widget

    async def update(self, project_name: str, widget_id: str,
                     changes: Mapping[str, Any]) -> Widget:
        """Change the settings named in ``changes``; the others stay as they are."""
        project = await self._project(project_name)
        cleaned = dict(changes)
        if "name" in cleaned:
            cleaned["name"] = cleaned["name"].strip()
        if "welcome" in cleaned:
            cleaned["welcome"] = _text(cleaned["welcome"])
        if "accent" in cleaned:
            cleaned["accent"] = _accent(cleaned["accent"] or DEFAULT_ACCENT)
        if "allowed_origins" in cleaned:
            cleaned["allowed_origins"] = _origins(cleaned["allowed_origins"])
        if "tags" in cleaned:
            cleaned["tags"] = list(clean_tags(cleaned["tags"] or ()))
        if "logo_url" in cleaned:
            cleaned["logo_url"] = _text(cleaned["logo_url"])
        widget = await self.uow.widgets.update(project.id, widget_id, cleaned)
        if widget is None:
            raise WidgetNotFound()
        await record(self.uow, project.tenant_id, "widget.updated", widget_id,
                     project=project.name, changes=cleaned)
        await self.uow.commit()
        return widget

    async def delete(self, project_name: str, widget_id: str) -> None:
        """Remove the widget; its conversations stay with the project."""
        project = await self._project(project_name)
        if not await self.uow.widgets.delete(project.id, widget_id):
            raise WidgetNotFound()
        await record(self.uow, project.tenant_id, "widget.deleted", widget_id,
                     project=project.name)
        await self.uow.commit()

    async def open(self, widget_id: str, origin: str | None, host: str | None = None) -> Widget:
        """The widget a visitor's page uses; refused to pages on other websites."""
        widget = await self.uow.widgets.get(widget_id)
        if widget is None:
            raise WidgetNotFound()
        if not origin_allowed(widget, origin, host):
            raise OriginNotAllowed(f"The widget may not be used on {origin}; add it to the "
                                   "widget's allowed origins")
        return widget

    async def conversation(self, widget: Widget, conversation_id: str | None) -> Conversation:
        """The visitor's conversation, or a new one; saved with the answer.

        A visitor can only continue conversations started in this widget.
        """
        if conversation_id is None:
            return await self.uow.conversations.create(widget.project_id, None,
                                                       widget_id=widget.id)
        conversation = await self.uow.conversations.get(widget.project_id, conversation_id)
        if conversation is None or conversation.widget_id != widget.id:
            raise ConversationNotFound()
        return conversation

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project


def _text(value: str | None) -> str | None:
    return (value or "").strip() or None


def _accent(value: str) -> str:
    return value.strip().lower()  # The API checks it is a #rrggbb colour.


def _origins(origins: Sequence[str]) -> list[str]:
    normalized = list(dict.fromkeys(normalize_origin(origin) for origin in origins))
    return [ANY_ORIGIN] if ANY_ORIGIN in normalized else normalized
