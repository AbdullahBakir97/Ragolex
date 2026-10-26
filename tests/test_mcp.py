"""The Model Context Protocol server: the protocol, the tools, and who may use them."""

import pytest

from ragolex.core.config import get_settings

from .fakes import FakeEmbedder, FakeLLM
from .test_ask_api import upload_process_and_index
from .test_auth import bearer, make_key


def rpc(client, method, params=None, id_=1, headers=None):
    message = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return client.post("/api/v1/mcp", json=message, headers=headers or {})


def call(client, tool, headers=None, **arguments):
    return rpc(client, "tools/call", {"name": tool, "arguments": arguments}, headers=headers).json()


@pytest.fixture
def models(client):
    """The fake models, where the MCP tools find the app's models."""
    client.app.state.embedder = FakeEmbedder()
    client.app.state.llm = llm = FakeLLM("Each chunk gets an embedding vector [1].")
    return llm


def test_initialize_negotiates_the_protocol_version(client):
    known = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                       "clientInfo": {"name": "test", "version": "1"}})
    unknown = rpc(client, "initialize", {"protocolVersion": "1999-01-01"})

    result = known.json()["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "ragolex"
    assert "list_projects" in result["instructions"]
    assert unknown.json()["result"]["protocolVersion"] == "2025-06-18"


def test_notifications_get_no_answer_and_ping_answers(client):
    notification = client.post("/api/v1/mcp", json={"jsonrpc": "2.0",
                                                    "method": "notifications/initialized"})

    assert (notification.status_code, notification.content) == (202, b"")
    assert rpc(client, "ping", id_="p").json() == {"jsonrpc": "2.0", "id": "p", "result": {}}


def test_tools_are_listed_with_their_schemas(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]

    assert [tool["name"] for tool in tools] == ["list_projects", "list_files",
                                                "search_knowledge", "ask"]
    search = tools[2]
    assert search["inputSchema"]["required"] == ["project", "query"]
    assert search["annotations"]["readOnlyHint"] is True


def test_the_tools_use_the_projects_documents(client, embedder, llm, models):
    file_id = upload_process_and_index(client)

    projects = call(client, "list_projects")["result"]
    files = call(client, "list_files", project="demo")["result"]
    found = call(client, "search_knowledge", project="demo", query="embedding vector", top_k=2)
    answered = call(client, "ask", project="demo", question="Where is the embedding vector stored?")

    assert projects["isError"] is False
    assert "- demo: 1 files" in projects["content"][0]["text"]
    assert file_id in files["content"][0]["text"]
    passages = found["result"]["content"][0]["text"]
    assert passages.startswith(f"[1] (file {file_id}, chunk ")
    assert "Indexing stores an embedding vector per chunk." in passages
    text = answered["result"]["content"][0]["text"]
    assert text.startswith("Each chunk gets an embedding vector [1].\n\nSources:\n[1] (file ")


def test_search_and_ask_can_be_limited_to_tags(client, embedder, llm, models):
    upload_process_and_index(client)
    other = upload_process_and_index(client, name="other.txt",
                                     text="Embedding vectors are stored elsewhere entirely.")
    client.put(f"/api/v1/projects/demo/files/{other}/tags", json={"tags": ["archive"]})

    files = call(client, "list_files", project="demo")["result"]["content"][0]["text"]
    found = call(client, "search_knowledge", project="demo", query="embedding vector",
                 tags=["Archive"])["result"]["content"][0]["text"]
    call(client, "ask", project="demo", question="Where is the embedding vector stored?",
         tags=["archive"])
    bad = call(client, "search_knowledge", project="demo", query="x", tags="archive")
    invalid = call(client, "search_knowledge", project="demo", query="x", tags=["a/b"])

    assert f"{other} (other.txt, text/plain, 48 bytes; tags: archive)" in files
    assert found.count("[") == found.count(f"(file {other},")
    assert "other.txt" in models.calls[-1][-1].content
    assert "guide.txt" not in models.calls[-1][-1].content
    assert bad["error"]["message"] == "tags must be a list of at most 20 strings"
    assert invalid["result"]["isError"] is True


def test_a_failing_tool_reports_why(client, models):
    unknown = call(client, "list_files", project="nope")["result"]

    assert unknown["isError"] is True
    assert unknown["content"][0]["text"] == "project_not_found: project not found"


def test_tools_need_their_models(client):
    client.app.state.embedder = None

    result = call(client, "search_knowledge", project="demo", query="x")["result"]

    assert result["isError"] is True
    assert result["content"][0]["text"].startswith("embedding_not_configured")


@pytest.mark.parametrize(("message", "code"), [
    ({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, -32601),
    ({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope"}}, -32602),
    ({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
      "params": {"name": "ask", "arguments": {"project": "demo"}}}, -32602),
    ({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
      "params": {"name": "search_knowledge",
                 "arguments": {"project": "../etc", "query": "x"}}}, -32602),
    ({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
      "params": {"name": "search_knowledge",
                 "arguments": {"project": "demo", "query": "x", "top_k": 500}}}, -32602),
    ({"id": 1, "method": "ping"}, -32600),
])
def test_protocol_errors(client, message, code):
    response = client.post("/api/v1/mcp", json=message)

    assert response.json()["error"]["code"] == code


def test_unreadable_requests(client):
    not_json = client.post("/api/v1/mcp", content=b"{nope", headers={"Content-Type": "application/json"})
    as_text = client.post("/api/v1/mcp", content=b"{}", headers={"Content-Type": "text/plain"})
    foreign = rpc(client, "ping", headers={"Origin": "https://evil.example"})

    assert not_json.json()["error"]["code"] == -32700
    assert as_text.status_code == 415
    assert foreign.status_code == 403
    assert client.get("/api/v1/mcp").status_code == 405


def test_a_batch_gets_one_answer_per_request(client):
    response = client.post("/api/v1/mcp", json=[
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"}])

    assert [reply["id"] for reply in response.json()] == [1, 2]


def test_tools_follow_the_keys_tenant_and_scopes(client, db, monkeypatch, models):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    reader = make_key(db, "acme", ["read"])

    assert rpc(client, "ping").status_code == 401
    tools = rpc(client, "tools/list", headers=bearer(reader)).json()["result"]["tools"]
    refused = call(client, "ask", headers=bearer(reader), project="demo", question="Hi?")

    assert "ask" not in [tool["name"] for tool in tools]
    assert refused["result"]["isError"] is True
    assert refused["result"]["content"][0]["text"].startswith("api_key_scope_missing")
    assert "no projects yet" in call(client, "list_projects", headers=bearer(reader))["result"][
        "content"][0]["text"]


def test_answers_count_against_the_quota(client, embedder, llm, models, monkeypatch):
    monkeypatch.setenv("ANSWERS_PER_MONTH", "1")
    get_settings.cache_clear()
    upload_process_and_index(client)

    first = call(client, "ask", project="demo", question="Where is the embedding vector stored?")
    second = call(client, "ask", project="demo", question="Where is the embedding vector stored?")

    assert first["result"]["isError"] is False
    assert second["result"]["content"][0]["text"].startswith("answer_quota_exceeded")


def test_tools_are_offered_as_function_schemas(client):
    schemas = client.get("/api/v1/tools").json()

    assert [s["function"]["name"] for s in schemas] == ["list_projects", "list_files",
                                                        "search_knowledge", "ask"]
    assert schemas[3] == {"type": "function", "function": {
        "name": "ask", "description": schemas[3]["function"]["description"],
        "parameters": rpc(client, "tools/list").json()["result"]["tools"][3]["inputSchema"]}}

