import hashlib
import json
from pathlib import Path

import pytest

from ragolex.evaluation.dataset import DatasetError, load_dataset
from ragolex.evaluation.metrics import normalize
from ragolex.loaders.registry import default_loader_registry
from ragolex.services.processing_service import ProcessingService
from ragolex.text.splitter import RecursiveTextSplitter

EVALS = Path(__file__).resolve().parents[1] / "evals"

# A released dataset never changes, so its results stay comparable; changes
# go into a new version. Update a hash only for a version not yet released.
RELEASED = {
    "handbook/v1": "da430293ada70100df52268468380940e1057b2b44b4b22622d4e01f29967d5a",
    "injection/v1": "e67ca7ade5542a5f83330e4b227b05d86a3f135da2f93db3a670feaeb65c0aeb",
}


def content_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode() + b"\0"
                      + path.read_bytes() + b"\0")
    return digest.hexdigest()


@pytest.mark.parametrize("label", sorted(RELEASED))
def test_released_datasets_do_not_change(label):
    assert content_hash(EVALS / label) == RELEASED[label]


@pytest.mark.parametrize("label", sorted(RELEASED))
@pytest.mark.parametrize(("chunk_size", "overlap_size"), [(1000, 200), (300, 50)])
def test_every_evidence_fits_in_one_chunk(label, chunk_size, overlap_size):
    """A missed source then always means search missed it, whatever the chunking."""
    dataset = load_dataset(EVALS / label)
    loaders = default_loader_registry()
    splitter = RecursiveTextSplitter(chunk_size=chunk_size, overlap_size=overlap_size)
    chunks = {}
    for document in dataset.documents:
        pages = loaders.get(document.name).load(document.path, source=document.name)
        chunks[document.name] = [normalize(chunk.text)
                                 for chunk in ProcessingService._split(pages, splitter)]

    missing = [(case.id, source.evidence) for case in dataset.cases
               for source in case.expected_sources
               if not any(normalize(source.evidence) in chunk for chunk in chunks[source.file])]

    assert missing == []


def test_every_injection_case_says_what_an_answer_must_not_hold():
    dataset = load_dataset(EVALS / "injection" / "v1")

    assert all(case.forbidden for case in dataset.cases)
    assert {"override", "tag-breakout", "disguised-tags", "exfiltration", "system-leak",
            "false-fact", "unanswerable"} <= {tag for case in dataset.cases for tag in case.tags}


def test_the_handbook_has_every_kind_of_question():
    dataset = load_dataset(EVALS / "handbook" / "v1")

    tags = {tag for case in dataset.cases for tag in case.tags}
    assert {"direct", "paraphrase", "multi", "pdf", "unanswerable"} <= tags
    assert all(case.answerable == ("unanswerable" not in case.tags) for case in dataset.cases)
    assert dataset.label == "handbook/v1"


def write_dataset(directory: Path, cases: list[dict], documents=("notes.txt",)) -> Path:
    (directory / "documents").mkdir(parents=True)
    for name in documents:
        (directory / "documents" / name).write_text("Cats purr when they are content.")
    (directory / "dataset.json").write_text(json.dumps(
        {"name": "tiny", "version": "v1", "documents": list(documents)}))
    (directory / "cases.jsonl").write_text("\n".join(
        case if isinstance(case, str) else json.dumps(case) for case in cases))
    return directory


CAT = {"id": "purr", "question": "When do cats purr?",
       "expected_sources": [{"file": "notes.txt", "evidence": "purr when"}],
       "reference_answer": "When they are content."}


def test_loads_a_dataset(tmp_path):
    unanswerable = {"id": "dogs", "question": "Do dogs purr?", "tags": ["unanswerable"],
                    "expected_sources": [], "reference_answer": None}
    dataset = load_dataset(write_dataset(tmp_path, [CAT, unanswerable]))

    cat, dog = dataset.cases
    assert (cat.answerable, dog.answerable) == (True, False)
    assert cat.expected_sources[0].file == "notes.txt"
    assert dataset.documents[0].content_type == "text/plain"


@pytest.mark.parametrize(("cases", "documents", "message"), [
    ([{**CAT, "forbidden": "PWNED"}], ("notes.txt",), "'forbidden' must be a list of texts"),
    ([{**CAT, "forbidden": [" "]}], ("notes.txt",), "'forbidden' must be a list of texts"),
    ([CAT, CAT], ("notes.txt",), "used twice: purr"),
    ([{**CAT, "expected_sources": [{"file": "other.txt", "evidence": "x"}]}], ("notes.txt",),
     "'other.txt' is not one of"),
    ([{**CAT, "reference_answer": None}], ("notes.txt",), "or neither"),
    ([{**CAT, "question": " "}], ("notes.txt",), "needs an 'id' and a 'question'"),
    (["{not json"], ("notes.txt",), "cases.jsonl:1: not valid JSON"),
    ([CAT], ("notes.doc",), r"\.doc is not a supported document type"),
    ([], ("notes.txt",), "there are no cases"),
])
def test_rejects_invalid_datasets(tmp_path, cases, documents, message):
    write_dataset(tmp_path, cases, documents)

    with pytest.raises(DatasetError, match=message):
        load_dataset(tmp_path)


def test_rejects_a_missing_dataset(tmp_path):
    with pytest.raises(DatasetError, match="dataset.json: cannot be read"):
        load_dataset(tmp_path / "nothing")
