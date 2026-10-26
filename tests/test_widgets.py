"""Chat widgets: managing them, and visitors of other websites asking through them."""

import json
import re

import pytest

from ragolex.core.config import get_settings
from ragolex.core.errors import WidgetOriginInvalid
from ragolex.domain.models import Widget
from ragolex.services.widget_service import normalize_origin, origin_allowed

from .test_ask_api import upload_process_and_index
from .test_auth import bearer, make_key

SITE = "https://shop.example.com"
QUESTION = "Where is the embedding vector stored?"


def create_widget(client, project="demo", headers=None, **fields):
    body = {"name": "Helper", "allowed_origins": [SITE], **fields}
    return client.post(f"/api/v1/projects/{project}/widgets", json=body, headers=headers or {})


def ask(client, widget_id, origin=SITE, **body):
    """POST a visitor's question; the status and the (event, data) pairs, or the error body."""
    headers = {"Origin": origin} if origin else {}
    with client.stream("POST", f"/api/v1/widgets/{widget_id}/ask", headers=headers,
                       json={"question": QUESTION, **body}) as response:
        response.read()
        if not response.headers["content-type"].startswith("text/event-stream"):
            return response.status_code, response.json()
        events = []
        for block in response.text.strip().split("\n\n"):
            fields = dict(line.split(": ", 1) for line in block.splitlines())
            events.append((fields["event"], json.loads(fields["data"])))
        return response.status_code, events


@pytest.fixture
def widget(client, embedder, llm):
    """A widget for the indexed demo project, allowed on SITE."""
    upload_process_and_index(client)
    return create_widget(client, welcome="Ask me about the guide.").json()


@pytest.mark.parametrize(("origin", "normalized"), [
    ("https://Example.com", "https://example.com"),
    ("https://example.com/", "https://example.com"),
    ("https://example.com:443", "https://example.com"),
    ("http://localhost:5173", "http://localhost:5173"),
    ("http://[::1]:8080", "http://[::1]:8080"),
    (" * ", "*"),
])
def test_origins_are_normalized_as_browsers_send_them(origin, normalized):
    assert normalize_origin(origin) == normalized


@pytest.mark.parametrize("origin", ["example.com", "https://example.com/shop", "ftp://example.com",
                                    "https://user@example.com", "https://example.com?x=1",
                                    "https://example.com:99999", "null", ""])
def test_anything_but_an_origin_is_refused(origin):
    with pytest.raises(WidgetOriginInvalid):
        normalize_origin(origin)


def test_which_pages_may_use_a_widget():
    widget = Widget(id="wgt_x", tenant_id=1, project_id=1, project_name="demo", name="Helper",
                    welcome=None, accent="#2563eb", allowed_origins=(SITE,), created_at=None)

    assert origin_allowed(widget, SITE)
    assert origin_allowed(widget, "https://SHOP.example.com:443")
    assert origin_allowed(widget, None)  # Not another website's page.
    assert origin_allowed(widget, "https://rag.example:8443", host="rag.example:8443")
    assert not origin_allowed(widget, "https://rag.example", host="rag.example:8443")
    assert not origin_allowed(widget, "https://evil.example")
    assert not origin_allowed(widget, "null")
    assert origin_allowed(Widget(**{**widget.__dict__, "allowed_origins": ("*",)}), "null")


def test_widgets_are_created_listed_changed_and_removed(client, widget):
    assert re.fullmatch(r"wgt_[A-Za-z0-9_-]{22}", widget["id"])
    assert widget["project"] == "demo"
    assert widget["accent"] == "#2563eb"
    assert widget["allowed_origins"] == [SITE]
    path = f"/api/v1/projects/demo/widgets/{widget['id']}"

    changed = client.patch(path, json={"accent": "#0F766E", "allowed_origins": [
        "https://a.example/", "https://a.example", "http://localhost:5173"]}).json()
    listed = client.get("/api/v1/projects/demo/widgets").json()["items"]
    removed = client.delete(path)

    assert changed["accent"] == "#0f766e"
    assert changed["allowed_origins"] == ["https://a.example", "http://localhost:5173"]
    assert changed["name"] == "Helper" and changed["welcome"] == "Ask me about the guide."
    assert listed == [changed]
    assert removed.status_code == 204
    assert client.get(path).json()["signal"] == "widget_not_found"
    assert client.get(f"/api/v1/widgets/{widget['id']}").status_code == 404


def test_any_origin_replaces_the_others(client, widget):
    changed = client.patch(f"/api/v1/projects/demo/widgets/{widget['id']}",
                           json={"allowed_origins": [SITE, "*"]}).json()

    assert changed["allowed_origins"] == ["*"]


@pytest.mark.parametrize("body", [{"allowed_origins": []}, {"allowed_origins": ["x" * 256]},
                                  {"accent": "blue"}, {"name": "  "}])
def test_invalid_settings_are_refused(client, widget, body):
    created = create_widget(client, **body)
    changed = client.patch(f"/api/v1/projects/demo/widgets/{widget['id']}", json=body)

    assert created.status_code == changed.status_code == 422


def test_allowed_origins_must_be_origins(client, widget):
    body = {"allowed_origins": ["https://example.com/page"]}

    created = create_widget(client, **body).json()
    changed = client.patch(f"/api/v1/projects/demo/widgets/{widget['id']}", json=body).json()

    assert created["signal"] == changed["signal"] == "widget_origin_invalid"


def test_required_settings_cannot_be_cleared(client, widget):
    response = client.patch(f"/api/v1/projects/demo/widgets/{widget['id']}",
                            json={"name": None})

    assert response.status_code == 422


def test_a_widget_needs_an_existing_project(client):
    assert create_widget(client, project="nope").json()["signal"] == "project_not_found"


def test_visitors_see_only_what_the_widget_shows(client, widget):
    response = client.get(f"/api/v1/widgets/{widget['id']}", headers={"Origin": SITE})

    assert response.status_code == 200
    assert response.json() == {"id": widget["id"], "name": "Helper",
                               "welcome": "Ask me about the guide.", "accent": "#2563eb",
                               "logo_url": None}
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_pages_on_other_websites_are_refused_readably(client, widget):
    response = client.get(f"/api/v1/widgets/{widget['id']}",
                          headers={"Origin": "https://evil.example"})
    status, body = ask(client, widget["id"], origin="https://evil.example")

    assert response.status_code == status == 403
    assert response.json()["signal"] == body["signal"] == "origin_not_allowed"
    # So the widget's script can read why.
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_browsers_may_send_widget_requests_from_any_page(client, widget):
    preflight = client.options(f"/api/v1/widgets/{widget['id']}/ask", headers={
        "Origin": SITE, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    other = client.options("/api/v1/projects", headers={
        "Origin": SITE, "Access-Control-Request-Method": "GET"})

    assert preflight.status_code == 204
    assert preflight.headers["Access-Control-Allow-Methods"] == "GET, POST, PUT"
    assert preflight.headers["Access-Control-Allow-Headers"] == "Content-Type"
    # The rest of the API is not for other websites' pages.
    assert "Access-Control-Allow-Origin" not in other.headers


def test_the_servers_own_pages_may_use_any_widget(client, widget):
    # The test client asks testserver, as the web app's widget preview asks its own host.
    response = client.get(f"/api/v1/widgets/{widget['id']}",
                          headers={"Origin": "http://testserver"})

    assert response.status_code == 200


def test_an_unknown_widget_is_not_found(client):
    response = client.get("/api/v1/widgets/wgt_" + "a" * 22)

    assert response.status_code == 404
    assert response.json()["signal"] == "widget_not_found"
    assert client.get("/api/v1/widgets/not-a-widget").status_code == 422


def test_visitors_get_streamed_answers_naming_their_documents(client, widget):
    status, events = ask(client, widget["id"])

    assert status == 200
    deltas = "".join(data["text"] for event, data in events if event == "delta")
    (event, answer), = [e for e in events if e[0] != "delta"]
    assert event == "answer"
    assert deltas == answer["answer"] == "Each chunk gets an embedding vector [1]."
    assert answer["signal"] == "answer_success"
    citation, = answer["citations"]
    assert citation["file_name"] == "guide.txt"
    assert "embedding vector" in citation["text"]
    # Nothing visitors have no use for: ids of files, scores, costs.
    assert set(citation) == {"number", "file_name", "page", "section", "text"}
    assert set(answer) == {"signal", "answer", "citations", "conversation_id", "message_id"}


def test_a_widget_with_tags_answers_only_from_files_with_them(client, widget, llm):
    other = upload_process_and_index(client, name="other.txt",
                                     text="Embedding vectors are stored elsewhere entirely.")
    client.put(f"/api/v1/projects/demo/files/{other}/tags", json={"tags": ["public"]})
    changed = client.patch(f"/api/v1/projects/demo/widgets/{widget['id']}",
                           json={"tags": ["Public"]})
    assert changed.json()["tags"] == ["public"]

    status, events = ask(client, widget["id"])

    assert status == 200
    assert "other.txt" in llm.calls[-1][-1].content
    assert "guide.txt" not in llm.calls[-1][-1].content
    answer = events[-1][1]
    assert {c["file_name"] for c in answer["citations"]} <= {"other.txt"}
    cleared = client.patch(f"/api/v1/projects/demo/widgets/{widget['id']}", json={"tags": None})
    assert cleared.json()["tags"] == []


def test_widget_tags_are_validated(client, widget):
    assert create_widget(client, tags=["no/slash"]).status_code == 422
    created = create_widget(client, tags=["Help Center"])
    assert created.json()["tags"] == ["help-center"]


def test_visitors_follow_up_in_their_conversation(client, widget, llm):
    _, first = ask(client, widget["id"])
    conversation_id = first[-1][1]["conversation_id"]
    _, second = ask(client, widget["id"], question="And where is it kept?",
                    conversation_id=conversation_id)

    assert second[-1][1]["conversation_id"] == conversation_id
    listed = client.get("/api/v1/projects/demo/conversations").json()["items"]
    assert [(c["id"], c["widget_id"], c["title"]) for c in listed] == [
        (conversation_id, widget["id"], QUESTION)]
    messages = client.get(f"/api/v1/projects/demo/conversations/{conversation_id}").json()
    assert len(messages["messages"]) == 4


def test_visitors_cannot_reach_other_conversations(client, widget):
    own = client.post("/api/v1/projects/demo/conversations").json()["id"]
    other = create_widget(client).json()["id"]
    _, events = ask(client, other)
    others = events[-1][1]["conversation_id"]

    for conversation_id in (own, others):
        status, body = ask(client, widget["id"], conversation_id=conversation_id)
        assert (status, body["signal"]) == (404, "conversation_not_found")


def test_a_failed_answer_leaves_no_conversation(client, widget, llm):
    llm.fail_after = 1

    _, events = ask(client, widget["id"])

    assert events[-1] == ("error", {"signal": "llm_failed"})
    assert client.get("/api/v1/projects/demo/conversations").json()["total"] == 0


def test_visitors_rate_answers(client, widget):
    _, events = ask(client, widget["id"])
    answer = events[-1][1]
    path = (f"/api/v1/widgets/{widget['id']}/conversations/{answer['conversation_id']}"
            f"/messages/{answer['message_id']}/feedback")

    rated = client.put(path, json={"rating": "down"}, headers={"Origin": SITE})
    feedback = client.get("/api/v1/projects/demo/feedback").json()
    elsewhere = client.put(path.replace(widget["id"], create_widget(client).json()["id"]),
                           json={"rating": "up"}, headers={"Origin": SITE})

    assert rated.status_code == 204
    assert (feedback["down"], feedback["items"][0]["question"]) == (1, QUESTION)
    assert elsewhere.json()["signal"] == "conversation_not_found"


def test_removing_a_widget_keeps_its_conversations(client, widget):
    ask(client, widget["id"])

    client.delete(f"/api/v1/projects/demo/widgets/{widget['id']}")

    conversation, = client.get("/api/v1/projects/demo/conversations").json()["items"]
    assert conversation["widget_id"] is None


def test_widget_answers_count_against_the_tenants_quota(client, widget, monkeypatch):
    monkeypatch.setenv("ANSWERS_PER_MONTH", "1")
    get_settings.cache_clear()

    first, _ = ask(client, widget["id"])
    second, body = ask(client, widget["id"])

    assert (first, second) == (200, 429)
    assert body["signal"] == "answer_quota_exceeded"


def test_widgets_act_for_their_tenant_without_a_key(client, embedder, llm, db, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    acme, other = make_key(db, "acme"), make_key(db, "other")
    reader = make_key(db, "acme", scopes=("read", "write", "ask"), name="reader")
    for key, text in ((acme, b"Acme: the embedding vector is stored in pgvector."),
                      (other, b"Other: the embedding vector is stored in a spreadsheet.")):
        file_id = client.post("/api/v1/data/upload/docs", headers=bearer(key),
                              files={"file": ("notes.txt", text, "text/plain")}).json()["file_id"]
        client.post("/api/v1/data/process/docs", headers=bearer(key), json={"file_id": file_id})
        client.post("/api/v1/index/docs", headers=bearer(key))

    widget = create_widget(client, project="docs", headers=bearer(acme)).json()
    _, events = ask(client, widget["id"])

    assert events[-1][1]["citations"][0]["text"] == "Acme: the embedding vector is stored in pgvector."
    # Managing widgets takes the admin scope, and only the tenant's own.
    assert create_widget(client, project="docs", headers=bearer(reader)).status_code == 403
    assert client.get(f"/api/v1/projects/docs/widgets/{widget['id']}",
                      headers=bearer(other)).json()["signal"] == "widget_not_found"
