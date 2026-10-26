"""Tags group a project's files into collections that searches and answers can be limited to."""

import pytest

from ragolex.domain.tags import InvalidTag, normalize_tag, normalize_tags

from .test_ask_api import ask, upload_process_and_index


def upload(client, name="notes.txt", content=b"Some notes.", tags=None, project="demo"):
    data = {"tags": tags} if tags is not None else {}
    return client.post(f"/api/v1/data/upload/{project}", data=data,
                       files={"file": (name, content, "text/plain")})


def listed(client, **params):
    page = client.get("/api/v1/projects/demo/files", params=params).json()
    return {f["original_name"]: f["tags"] for f in page["items"]}


@pytest.mark.parametrize(("tag", "normalized"), [
    ("guides", "guides"),
    ("Release Notes", "release-notes"),
    ("  v2_beta ", "v2-beta"),
    ("Über", "über"),
    ("x" * 32, "x" * 32),
])
def test_tags_are_normalized(tag, normalized):
    assert normalize_tag(tag) == normalized


@pytest.mark.parametrize("tag", ["", " ", "-", "a/b", "a.b", "#x", "x" * 33])
def test_invalid_tags_are_refused(tag):
    with pytest.raises(InvalidTag):
        normalize_tag(tag)


def test_tags_lose_duplicates_and_are_limited():
    assert normalize_tags(["B", "a", "b"]) == ("b", "a")
    with pytest.raises(InvalidTag, match="At most 2 tags"):
        normalize_tags(["a", "b", "c"], limit=2)


def test_uploads_are_tagged_and_duplicates_gain_new_tags(client):
    first = upload(client, tags="Guides, v2")
    again = upload(client, name="copy.txt", tags="v2,handbook")

    assert first.status_code == again.status_code == 200
    assert again.json() == {"signal": "file_already_uploaded", "file_id": first.json()["file_id"]}
    assert listed(client) == {"notes.txt": ["guides", "v2", "handbook"]}


def test_a_bad_upload_tag_is_refused_and_nothing_is_stored(client):
    response = upload(client, tags="fine, not/fine")

    assert response.status_code == 422
    assert response.json()["signal"] == "tag_invalid"
    assert client.get("/api/v1/projects/demo/files").status_code == 404


def test_files_are_retagged_listed_by_tag_and_tags_are_counted(client):
    guide = upload(client, name="guide.txt", content=b"Guide.", tags="guides").json()["file_id"]
    upload(client, name="faq.txt", content=b"FAQ.", tags="guides,faq")
    upload(client, name="other.txt", content=b"Other.")

    response = client.put(f"/api/v1/projects/demo/files/{guide}/tags",
                          json={"tags": ["Handbook", "guides", "handbook"]})

    assert response.status_code == 200
    assert response.json()["tags"] == ["handbook", "guides"]
    assert listed(client, tag="guides") == {"guide.txt": ["handbook", "guides"],
                                            "faq.txt": ["guides", "faq"]}
    assert client.get("/api/v1/projects/demo/files", params={"tag": "Guides"}).json()["total"] == 2
    assert listed(client, tag="nothing") == {}
    assert client.get("/api/v1/projects/demo/tags").json() == {"items": [
        {"tag": "faq", "files": 1}, {"tag": "guides", "files": 2}, {"tag": "handbook", "files": 1}]}

    cleared = client.put(f"/api/v1/projects/demo/files/{guide}/tags", json={"tags": []})
    assert cleared.json()["tags"] == []


def test_retagging_validates_and_needs_the_file(client):
    file_id = upload(client).json()["file_id"]
    path = f"/api/v1/projects/demo/files/{file_id}/tags"

    assert client.put(path, json={"tags": ["a/b"]}).status_code == 422
    assert client.put(path, json={"tags": [f"t{i}" for i in range(21)]}).status_code == 422
    assert client.get("/api/v1/projects/demo/files", params={"tag": "a/b"}).json() == {
        "signal": "tag_invalid"}
    missing = client.put("/api/v1/projects/demo/files/nope_missing.txt/tags", json={"tags": []})
    assert (missing.status_code, missing.json()) == (404, {"signal": "file_not_found"})
    unknown = client.get("/api/v1/projects/nothing/tags")
    assert (unknown.status_code, unknown.json()) == (404, {"signal": "project_not_found"})


def test_searches_and_answers_use_only_files_with_the_tags(client, embedder, llm):
    guide = upload_process_and_index(client)
    other = upload_process_and_index(client, name="other.txt",
                                     text="Embedding vectors are stored elsewhere entirely.")
    client.put(f"/api/v1/projects/demo/files/{other}/tags", json={"tags": ["archive"]})

    found = client.post("/api/v1/search/demo", json={
        "query": "embedding vector", "top_k": 10, "filters": {"tags": ["Archive", "missing"]}})
    nothing = client.post("/api/v1/search/demo", json={
        "query": "embedding vector", "filters": {"tags": ["missing"]}})
    answer = ask(client, question="Where is the embedding vector stored?",
                 filters={"tags": ["archive"]}).json()

    assert {hit["file_id"] for hit in found.json()["results"]} == {other}
    assert nothing.json()["results"] == []
    assert {citation["file_id"] for citation in answer["citations"]} <= {other}
    assert "other.txt" in llm.calls[-1][-1].content
    assert guide not in llm.calls[-1][-1].content


def test_search_tag_filters_are_validated(client, embedder):
    response = client.post("/api/v1/search/demo", json={
        "query": "retrieval", "filters": {"tags": ["not/a/tag"]}})

    assert response.status_code == 422
