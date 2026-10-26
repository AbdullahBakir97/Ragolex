"""Decks of flashcards: saved from study material, reviewed by spaced repetition, exported to Anki."""

from datetime import datetime, timedelta

import pytest

from .test_study_api import processed

CARDS = [
    {"front": "What does processing do?", "back": "Splits files into chunks.",
     "file_id": None, "chunk_index": 1},
    {"front": "What does indexing store?", "back": "An embedding vector\nper chunk.",
     "chunk_index": 2, "page": 4},
    {"front": "Term:\tchunk", "back": "A <piece> of a document & its text."},
]


@pytest.fixture
def file_id(client):
    return processed(client)


def create(client, name="Guide", cards=None, project="demo", file_id=None):
    # Cards with a file_id of None come from ``file_id``.
    cards = [{**card, "file_id": file_id} if "file_id" in card and card["file_id"] is None
             else card for card in (CARDS if cards is None else cards)]
    response = client.post(f"/api/v1/projects/{project}/decks", json={"name": name,
                                                                        "cards": cards})
    assert response.status_code == 201, response.text
    return response.json()


def due(client, deck_id, **params):
    response = client.get(f"/api/v1/projects/demo/decks/{deck_id}/review", params=params)
    assert response.status_code == 200
    return response.json()


def grade(client, deck_id, card_id, value):
    return client.post(f"/api/v1/projects/demo/decks/{deck_id}/cards/{card_id}/review",
                       json={"grade": value})


def test_a_deck_starts_with_every_card_due(client, file_id):
    deck = create(client, file_id=file_id)

    assert (deck["name"], deck["cards"], deck["due"]) == ("Guide", 3, 3)
    listed = client.get("/api/v1/projects/demo/decks").json()
    assert [d["id"] for d in listed] == [deck["id"]]
    cards = client.get(f"/api/v1/projects/demo/decks/{deck['id']}/cards").json()
    assert cards["total"] == 3
    first = cards["items"][0]
    assert (first["front"], first["source"]) == ("What does processing do?", {
        "file_id": file_id, "chunk_index": 1, "page": None, "section": None})
    assert (first["repetitions"], first["interval_days"], first["last_reviewed_at"]) == (0, 0, None)


def test_reviewing_schedules_each_card_by_how_well_it_was_remembered(client, file_id):
    deck = create(client, file_id=file_id)
    queue = due(client, deck["id"])
    assert [card["front"] for card in queue["cards"]] == [card["front"] for card in CARDS]
    assert queue["cards"][0]["intervals"] == {"again": pytest.approx(0.006944), "hard": 1.0,
                                              "good": 1.0, "easy": 4.0}

    good = grade(client, deck["id"], queue["cards"][0]["id"], "good")
    again = grade(client, deck["id"], queue["cards"][1]["id"], "again")

    assert good.status_code == again.status_code == 200
    reviewed = good.json()
    assert (reviewed["repetitions"], reviewed["interval_days"]) == (1, 1.0)
    due_at = datetime.fromisoformat(reviewed["due_at"])
    last = datetime.fromisoformat(reviewed["last_reviewed_at"])
    assert due_at - last == timedelta(days=1)
    assert again.json()["interval_days"] == pytest.approx(10 / 1440, abs=1e-6)
    # Only the card not reviewed yet is still due.
    after = due(client, deck["id"])
    assert after["deck"]["due"] == 1
    assert [card["front"] for card in after["cards"]] == ["Term:\tchunk"]


def test_the_queue_can_be_taken_a_few_cards_at_a_time(client):
    deck = create(client)

    assert len(due(client, deck["id"], limit=2)["cards"]) == 2


def test_cards_can_be_added_to_a_deck(client):
    deck = create(client, cards=[])
    assert (deck["cards"], deck["due"]) == (0, 0)

    response = client.post(f"/api/v1/projects/demo/decks/{deck['id']}/cards",
                           json={"cards": CARDS[:2]})
    again = client.post(f"/api/v1/projects/demo/decks/{deck['id']}/cards",
                        json={"cards": CARDS[2:]})

    assert response.json()["cards"] == 2
    assert again.json()["cards"] == 3
    cards = client.get(f"/api/v1/projects/demo/decks/{deck['id']}/cards").json()["items"]
    assert [card["front"] for card in cards] == [card["front"] for card in CARDS]


def test_a_deck_holds_at_most_2000_cards(client, monkeypatch):
    monkeypatch.setattr("ragolex.services.deck_service.MAX_CARDS", 4)
    deck = create(client)

    response = client.post(f"/api/v1/projects/demo/decks/{deck['id']}/cards",
                           json={"cards": CARDS[:2]})

    assert (response.status_code, response.json()["signal"]) == (409, "deck_full")


def test_a_deck_exports_to_anki(client, file_id):
    deck = create(client, name="Guide: chapter 1", file_id=file_id)

    response = client.get(f"/api/v1/projects/demo/decks/{deck['id']}/anki")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"] == (
        'attachment; filename="Guide--chapter-1.txt"')
    assert response.text.splitlines() == [
        "#separator:tab", "#html:true", "#notetype:Basic", "#deck:Guide: chapter 1",
        "#tags column:3",
        "What does processing do?\tSplits files into chunks.<br><br><small>guide.txt</small>"
        "\tragolex demo",
        "What does indexing store?\tAn embedding vector<br>per chunk.\tragolex demo",
        "Term: chunk\tA &lt;piece&gt; of a document &amp; its text.\tragolex demo",
    ]


def test_the_export_names_the_page_and_section_of_each_card(client, file_id):
    deck = create(client, cards=[
        {"front": "Q1", "back": "A1", "file_id": file_id, "page": 4},
        {"front": "Q2", "back": "A2", "file_id": file_id, "section": "Setup > Install"},
        {"front": "Q3", "back": "A3", "file_id": "abc123_deleted.txt"}])

    lines = client.get(f"/api/v1/projects/demo/decks/{deck['id']}/anki").text.splitlines()

    assert lines[-3:] == [
        "Q1\tA1<br><br><small>guide.txt, p. 4</small>\tragolex demo",
        "Q2\tA2<br><br><small>guide.txt, Setup &gt; Install</small>\tragolex demo",
        "Q3\tA3<br><br><small>abc123_deleted.txt</small>\tragolex demo"]


def test_deleting_a_deck_deletes_its_cards(client):
    deck = create(client)

    assert client.delete(f"/api/v1/projects/demo/decks/{deck['id']}").status_code == 204
    assert client.get(f"/api/v1/projects/demo/decks/{deck['id']}").status_code == 404
    assert client.get("/api/v1/projects/demo/decks").json() == []


def test_decks_belong_to_their_project(client):
    deck = create(client)
    processed(client, project="other")

    for path in ("", "/cards", "/review", "/anki"):
        response = client.get(f"/api/v1/projects/other/decks/{deck['id']}{path}")
        assert (response.status_code, response.json()["signal"]) == (404, "deck_not_found")
    assert client.delete(f"/api/v1/projects/other/decks/{deck['id']}").status_code == 404
    assert client.get("/api/v1/projects/other/decks").json() == []


def test_unknown_projects_and_cards(client):
    deck = create(client)
    other = create(client, name="Other")
    card = due(client, other["id"])["cards"][0]

    missing = client.get("/api/v1/projects/nowhere/decks")
    wrong_deck = grade(client, deck["id"], card["id"], "good")

    assert (missing.status_code, missing.json()["signal"]) == (404, "project_not_found")
    assert (wrong_deck.status_code, wrong_deck.json()["signal"]) == (404, "card_not_found")


@pytest.mark.parametrize("body", [
    {"name": "", "cards": []},
    {"name": "   ", "cards": []},
    {"name": "x" * 101, "cards": []},
    {"name": "Deck", "cards": [{"front": "", "back": "b"}]},
    {"name": "Deck", "cards": [{"front": "f", "back": "b", "page": 0}]},
    {"name": "Deck", "cards": [{"front": "f", "back": "b"}] * 501},
])
def test_invalid_decks_are_rejected(client, body):
    processed(client)

    assert client.post("/api/v1/projects/demo/decks", json=body).status_code == 422


def test_grades_are_anki_s_four_answers(client):
    deck = create(client)
    card = due(client, deck["id"])["cards"][0]

    assert grade(client, deck["id"], card["id"], "perfect").status_code == 422
