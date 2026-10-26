import pytest

from ragolex.api.dependencies import get_embedder

from .fakes import FakeEmbedder

TEXT = "\n\n".join(f"Paragraph {i} about retrieval and generation." for i in range(5))


def upload_and_process(client, project="demo", name="notes.txt", text=TEXT):
    response = client.post(f"/api/v1/data/upload/{project}",
                           files={"file": (name, text.encode(), "text/plain")})
    file_id = response.json()["file_id"]
    response = client.post(f"/api/v1/data/process/{project}",
                           json={"file_id": file_id, "chunk_size": 60, "overlap_size": 0})
    assert response.status_code == 200
    return file_id


def test_index_embeds_new_chunks_and_is_repeatable(client, embedder, query):
    upload_and_process(client)

    first = client.post("/api/v1/index/demo")
    second = client.post("/api/v1/index/demo")

    assert first.status_code == 200
    assert first.json() == {"signal": "indexing_success", "embedded_count": 5, "chunks_count": 5}
    assert second.json() == {"signal": "indexing_success", "embedded_count": 0, "chunks_count": 5}
    assert query("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL") == [(5,)]


def test_project_details_show_index_progress(client, embedder):
    file_id = upload_and_process(client)
    upload_and_process(client, text="Just one paragraph.")
    client.post("/api/v1/index/demo", json={"file_id": file_id})

    project = client.get("/api/v1/projects/demo").json()

    assert (project["chunks_count"], project["embedded_chunks_count"]) == (6, 5)


def test_index_a_single_file(client, embedder):
    upload_and_process(client)
    file_id = upload_and_process(client, text="Just one paragraph.")

    response = client.post("/api/v1/index/demo", json={"file_id": file_id})

    assert response.json() == {"signal": "indexing_success", "embedded_count": 1, "chunks_count": 1}


def test_reprocessing_a_file_needs_indexing_again(client, embedder):
    file_id = upload_and_process(client)
    client.post("/api/v1/index/demo")

    client.post("/api/v1/data/process/demo",
                json={"file_id": file_id, "chunk_size": 1000, "overlap_size": 0})

    assert client.post("/api/v1/index/demo").json()["embedded_count"] == 1


@pytest.mark.parametrize(("path", "body", "status", "signal"), [
    ("/api/v1/index/missing", None, 404, "project_not_found"),
    ("/api/v1/index/demo", {"file_id": "nope.txt"}, 404, "file_not_found"),
])
def test_index_unknown_project_or_file(client, embedder, path, body, status, signal):
    upload_and_process(client)

    response = client.post(path, json=body)

    assert (response.status_code, response.json()) == (status, {"signal": signal})


def test_index_invalid_file_id(client, embedder):
    response = client.post("/api/v1/index/demo", json={"file_id": "../etc/passwd"})

    assert response.status_code == 422


def test_index_reports_embedding_failures(client):
    # Each test gets a new app, so the override needs no cleanup.
    client.app.dependency_overrides[get_embedder] = lambda: FakeEmbedder(fail_on_call=1)
    upload_and_process(client)

    response = client.post("/api/v1/index/demo")

    assert (response.status_code, response.json()) == (502, {"signal": "embedding_failed"})


def test_index_without_embedding_configuration(client):
    upload_and_process(client)
    client.app.state.embedder = None

    response = client.post("/api/v1/index/demo")

    assert (response.status_code, response.json()) == (503, {"signal": "embedding_not_configured"})


# One chunk per paragraph at chunk_size 60.
GUIDE = "\n\n".join([
    "Upload a file first, as text or PDF.",
    "Processing splits each file into chunks.",
    "Indexing stores an embedding vector per chunk.",
    "Search compares the question with the chunks.",
])


def search(client, project="demo", **body):
    return client.post(f"/api/v1/search/{project}", json=body)


def test_search_finds_the_most_relevant_chunks(client, embedder):
    file_id = upload_and_process(client, text=GUIDE)
    client.post("/api/v1/index/demo")

    response = search(client, query="Where is the embedding vector stored?", top_k=2)

    assert response.status_code == 200
    body = response.json()
    assert body["signal"] == "search_success"
    assert len(body["results"]) == 2
    best = body["results"][0]
    assert best["text"] == "Indexing stores an embedding vector per chunk."
    assert (best["file_id"], best["chunk_index"]) == (file_id, 2)
    assert best["metadata"] == {"source": file_id}
    assert 0 < body["results"][1]["score"] < best["score"] <= 1


def test_search_only_sees_indexed_chunks_of_the_project(client, embedder):
    upload_and_process(client, text=GUIDE)
    upload_and_process(client, project="other", text="An embedding vector per chunk.")
    client.post("/api/v1/index/other")

    unindexed = search(client, query="embedding vector")
    client.post("/api/v1/index/demo")
    indexed = search(client, query="embedding vector", top_k=50)

    assert unindexed.json() == {"signal": "search_success", "results": []}
    assert len(indexed.json()["results"]) == 4  # all of demo's chunks, none of other's


def test_search_min_score(client, embedder):
    upload_and_process(client, text=GUIDE)
    client.post("/api/v1/index/demo")

    results = search(client, query="embedding vector", top_k=10, min_score=0.2).json()["results"]

    assert [r["chunk_index"] for r in results] == [2]


def test_search_unknown_project(client, embedder):
    response = search(client, project="missing", query="anything")

    assert (response.status_code, response.json()) == (404, {"signal": "project_not_found"})


@pytest.mark.parametrize("body", [
    {"query": ""},
    {"query": "   "},
    {"query": "x" * 2001},
    {"query": "ok", "top_k": 0},
    {"query": "ok", "top_k": 51},
    {"query": "ok", "min_score": 1.5},
    {},
])
def test_search_validates_the_request(client, embedder, body):
    assert search(client, **body).status_code == 422


def test_search_without_embedding_configuration(client):
    client.app.state.embedder = None

    response = search(client, query="anything")

    assert (response.status_code, response.json()) == (503, {"signal": "embedding_not_configured"})


def test_search_filters_by_file_and_reports_unknown_files(client, embedder):
    first = upload_and_process(client, name="first.txt")
    upload_and_process(client, name="second.txt")
    client.post("/api/v1/index/demo")

    only_first = client.post("/api/v1/search/demo", json={
        "query": "retrieval", "top_k": 10, "filters": {"file_ids": [first]}}).json()
    unknown = client.post("/api/v1/search/demo", json={
        "query": "retrieval", "filters": {"file_ids": ["nope_missing.txt"]}})

    assert {hit["file_id"] for hit in only_first["results"]} == {first}
    assert (unknown.status_code, unknown.json()) == (404, {"signal": "file_not_found"})


@pytest.mark.parametrize("filters", [
    {"page_from": 3, "page_to": 2},
    {"uploaded_after": "2026-10-02T00:00:00Z", "uploaded_before": "2026-10-01T00:00:00Z"},
    {"max_per_file": 0},
    {"file_ids": ["../etc/passwd"]},
    {"metadata": {f"k{i}": i for i in range(11)}},
])
def test_search_filters_are_validated(client, embedder, filters):
    response = client.post("/api/v1/search/demo", json={"query": "retrieval", "filters": filters})

    assert response.status_code == 422


def test_search_is_reranked_when_a_reranker_is_set(client, embedder):
    from .test_search_service import FakeReranker

    upload_and_process(client)
    client.post("/api/v1/index/demo")
    plain = client.post("/api/v1/search/demo", json={"query": "retrieval", "top_k": 5}).json()
    last = plain["results"][-1]["text"]
    client.app.state.reranker = FakeReranker({last: 1.0})

    reranked = client.post("/api/v1/search/demo", json={"query": "retrieval", "top_k": 5}).json()

    assert reranked["results"][0]["text"] == last
