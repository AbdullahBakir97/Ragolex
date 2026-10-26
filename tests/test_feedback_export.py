import json

from ragolex import cli
from ragolex.evaluation.dataset import load_dataset
from ragolex.evaluation.metrics import normalize
from ragolex.services.feedback_export_service import evidence

from .test_ask_api import GUIDE, ask, upload_process_and_index
from .test_conversations_api import feedback_url, start


def test_evidence_is_the_start_of_the_sentence_closest_to_the_answer():
    passage = ("Upload a file first.\nProcessing splits each file into chunks. "
               "Indexing stores an embedding vector per chunk, so search can compare it with "
               "the question and find the best matching passages quickly.")

    phrase = evidence(passage, "Each chunk gets an embedding vector [1].")

    assert phrase == "Indexing stores an embedding vector per chunk, so search can compare it with the"
    assert evidence("", "anything") == ""


def test_rated_answers_become_a_dataset(client, embedder, llm, tmp_path, capsys):
    upload_process_and_index(client)
    conversation_id = start(client).json()["id"]
    good = ask(client, question="Where is the embedding vector stored?",
               conversation_id=conversation_id).json()["message_id"]
    bad = ask(client, question="And where are the chunks?",
              conversation_id=conversation_id).json()["message_id"]
    client.put(feedback_url(conversation_id, good), json={"rating": "up"})
    client.put(feedback_url(conversation_id, bad), json={"rating": "down", "comment": "Wrong."})
    output = tmp_path / "dataset"

    assert cli.main(["feedback-export", "demo", str(output)]) == cli.PASSED

    assert "Exported 1 documents, 1 cases" in capsys.readouterr().out
    dataset = load_dataset(output)
    assert dataset.label == "demo-feedback/v1"
    [case] = dataset.cases
    assert case.question == "Where is the embedding vector stored?"
    assert case.reference_answer == "Each chunk gets an embedding vector."
    [source] = case.expected_sources
    assert source.file == "guide.txt"
    assert normalize(source.evidence) in normalize(GUIDE)
    assert (output / "documents" / "guide.txt").read_text() == GUIDE
    [review] = [json.loads(line) for line in (output / "cases-to-review.jsonl").open()]
    assert (review["question"], review["rating"], review["comment"]) == (
        "And where are the chunks?", "down", "Wrong.")
    assert review["cited"][0]["file"] == "guide.txt"


def test_exports_only_into_a_new_folder(client, tmp_path, capsys):
    (tmp_path / "taken.txt").write_text("x")

    assert cli.main(["feedback-export", "demo", str(tmp_path)]) == cli.FAILED
    assert "is not empty" in capsys.readouterr().err


def test_an_unknown_project_cannot_be_exported(client, tmp_path, capsys):
    assert cli.main(["feedback-export", "nope", str(tmp_path / "out")]) == cli.FAILED
    assert "project_not_found" in capsys.readouterr().err
