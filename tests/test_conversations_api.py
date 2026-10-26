import uuid

from ragolex.api.dependencies import get_llm

from .fakes import FakeLLM
from .test_ask_api import ask, stream_events, upload_process_and_index


def start(client, project="demo", **body):
    return client.post(f"/api/v1/projects/{project}/conversations", json=body or None)


def test_a_conversation_keeps_questions_answers_and_sources(client, embedder, llm):
    file_id = upload_process_and_index(client)
    created = start(client)
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["title"] is None

    answer = ask(client, question="Where is the embedding vector stored?",
                 conversation_id=conversation["id"]).json()

    assert (answer["conversation_id"], answer["search_question"]) == (conversation["id"], None)
    detail = client.get(f"/api/v1/projects/demo/conversations/{conversation['id']}").json()
    assert detail["title"] == "Where is the embedding vector stored?"
    question, reply = detail["messages"]
    assert (question["role"], question["content"], question["citations"]) == (
        "user", "Where is the embedding vector stored?", [])
    assert (reply["role"], reply["content"], reply["prompt_version"]) == (
        "assistant", "Each chunk gets an embedding vector [1].", "answer-v1")
    assert reply["citations"][0] == answer["citations"][0]
    assert reply["citations"][0]["file_id"] == file_id


def test_a_streamed_follow_up_is_rewritten_and_kept(client, embedder):
    upload_process_and_index(client)
    fake = FakeLLM(replies=["Each chunk gets an embedding vector [1].",
                            "What compares the question with the chunks?",
                            "Search does [1]."])
    client.app.dependency_overrides[get_llm] = lambda: fake
    conversation_id = start(client).json()["id"]
    ask(client, question="Where is the embedding vector stored?", conversation_id=conversation_id)

    status, events = stream_events(client, question="And what compares them?",
                                   conversation_id=conversation_id)

    assert status == 200
    event, answer = events[-1]
    assert event == "answer"
    assert answer["search_question"] == "What compares the question with the chunks?"
    assert answer["citations"][0]["text"] == "Search compares the question with the chunks."
    messages = client.get(f"/api/v1/projects/demo/conversations/{conversation_id}").json()["messages"]
    assert [m["content"] for m in messages] == [
        "Where is the embedding vector stored?", "Each chunk gets an embedding vector [1].",
        "And what compares them?", "Search does [1]."]
    assert messages[-1]["search_question"] == "What compares the question with the chunks?"


def test_conversations_are_listed_newest_first_and_deleted(client, embedder, llm):
    upload_process_and_index(client)
    first = start(client).json()["id"]
    second = start(client, title="Named").json()["id"]
    ask(client, question="Where is the embedding vector stored?", conversation_id=first)

    page = client.get("/api/v1/projects/demo/conversations").json()

    assert (page["total"], [c["id"] for c in page["items"]]) == (2, [first, second])
    assert page["items"][1]["title"] == "Named"
    assert client.delete(f"/api/v1/projects/demo/conversations/{first}").status_code == 204
    response = client.get(f"/api/v1/projects/demo/conversations/{first}")
    assert (response.status_code, response.json()) == (404, {"signal": "conversation_not_found"})


def test_unknown_and_foreign_conversations_are_not_found(client, embedder, llm):
    upload_process_and_index(client)
    upload_process_and_index(client, project="other")
    foreign = start(client, project="other").json()["id"]

    for conversation_id in (str(uuid.uuid4()), foreign):
        response = ask(client, question="anything", conversation_id=conversation_id)
        assert (response.status_code, response.json()) == (404, {"signal": "conversation_not_found"})
        status, body = stream_events(client, question="anything", conversation_id=conversation_id)
        assert (status, body) == (404, {"signal": "conversation_not_found"})
        assert client.delete(f"/api/v1/projects/demo/conversations/{conversation_id}").status_code == 404


def test_conversation_ids_and_projects_are_validated(client):
    assert client.get("/api/v1/projects/demo/conversations/not-a-uuid").status_code == 422
    assert ask(client, question="q", conversation_id="not-a-uuid").status_code == 422
    response = start(client, project="missing")
    assert (response.status_code, response.json()) == (404, {"signal": "project_not_found"})
    assert start(client, title="x" * 201).status_code == 422


def test_conversation_endpoints_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]

    conversations = paths["/api/v1/projects/{project_id}/conversations"]
    one = paths["/api/v1/projects/{project_id}/conversations/{conversation_id}"]
    assert set(conversations) == {"get", "post"} and set(one) == {"get", "delete"}
    assert "conversation_not_found" in one["get"]["responses"]["404"]["description"]
    ask_errors = paths["/api/v1/ask/{project_id}"]["post"]["responses"]["404"]["description"]
    assert "conversation_not_found" in ask_errors


def feedback_url(conversation_id, message_id, project="demo"):
    return (f"/api/v1/projects/{project}/conversations/{conversation_id}"
            f"/messages/{message_id}/feedback")


def test_answers_are_rated_reviewed_and_unrated(client, embedder, llm):
    upload_process_and_index(client)
    conversation_id = start(client).json()["id"]
    answer = ask(client, question="Where is the embedding vector stored?",
                 conversation_id=conversation_id).json()
    message_id = answer["message_id"]
    messages = client.get(f"/api/v1/projects/demo/conversations/{conversation_id}").json()["messages"]
    assert [m["id"] for m in messages][1] == message_id
    assert messages[1]["feedback"] is None

    rated = client.put(feedback_url(conversation_id, message_id),
                       json={"rating": "down", "comment": "Too short."})

    assert rated.status_code == 200
    assert rated.json()["feedback"]["rating"] == "down"
    listed = client.get("/api/v1/projects/demo/feedback").json()
    assert (listed["up"], listed["down"], listed["total"]) == (0, 1, 1)
    [item] = listed["items"]
    assert (item["question"], item["answer"], item["feedback"]["comment"]) == (
        "Where is the embedding vector stored?", "Each chunk gets an embedding vector [1].",
        "Too short.")
    assert item["citations"][0]["number"] == 1
    assert client.get("/api/v1/projects/demo/feedback", params={"rating": "up"}).json()["total"] == 0

    assert client.delete(feedback_url(conversation_id, message_id)).status_code == 204
    assert client.get("/api/v1/projects/demo/feedback").json()["total"] == 0


def test_only_answers_can_be_rated(client, embedder, llm):
    upload_process_and_index(client)
    conversation_id = start(client).json()["id"]
    message_id = ask(client, question="Where is the embedding vector stored?",
                     conversation_id=conversation_id).json()["message_id"]

    question = client.put(feedback_url(conversation_id, message_id - 1), json={"rating": "up"})
    unknown = client.put(feedback_url(uuid.uuid4(), message_id), json={"rating": "up"})

    assert (question.status_code, question.json()) == (404, {"signal": "message_not_found"})
    assert (unknown.status_code, unknown.json()) == (404, {"signal": "conversation_not_found"})
    for body in ({"rating": "sideways"}, {"rating": "up", "comment": "x" * 1001}):
        assert client.put(feedback_url(conversation_id, message_id), json=body).status_code == 422
