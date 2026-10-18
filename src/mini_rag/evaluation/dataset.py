"""Versioned evaluation datasets: documents, and questions asked about them.

A dataset is a folder with ``dataset.json`` (its name, version and
documents), the documents in ``documents/``, and ``cases.jsonl`` with one
question per line. A released version never changes; changes make a new
version, so results stay comparable.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from mini_rag.domain.file_types import CONTENT_TYPES


class DatasetError(ValueError):
    """The dataset is missing or not valid; the message says where."""


@dataclass(frozen=True)
class ExpectedSource:
    """A passage that answers the question: in ``file``, containing ``evidence``.

    Evidence is a short phrase rather than a chunk number, so the case stays
    valid when documents are split differently.
    """

    file: str
    evidence: str


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    tags: tuple[str, ...]
    expected_sources: tuple[ExpectedSource, ...]
    # What a correct answer says; None when the documents do not answer.
    reference_answer: str | None
    # Text an answer must not hold, such as what a prompt injection in a
    # document asks for; compared ignoring case.
    forbidden: tuple[str, ...] = ()

    @property
    def answerable(self) -> bool:
        return bool(self.expected_sources)


@dataclass(frozen=True)
class DatasetDocument:
    name: str
    path: Path
    content_type: str


@dataclass(frozen=True)
class Dataset:
    name: str
    version: str
    description: str
    documents: tuple[DatasetDocument, ...]
    cases: tuple[Case, ...]

    @property
    def label(self) -> str:
        return f"{self.name}/{self.version}"


def load_dataset(directory: Path) -> Dataset:
    """Read and check the dataset in ``directory``."""
    directory = Path(directory)
    manifest = _read_json(directory / "dataset.json")
    for key in ("name", "version", "documents"):
        if not manifest.get(key):
            raise DatasetError(f"{directory / 'dataset.json'}: '{key}' is missing")

    documents = tuple(_document(directory, name) for name in manifest["documents"])
    names = {document.name for document in documents}
    if len(names) != len(documents):
        raise DatasetError(f"{directory / 'dataset.json'}: a document is listed twice")

    cases_path = directory / "cases.jsonl"
    try:
        lines = cases_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DatasetError(f"{cases_path}: cannot be read ({exc.strerror})") from exc
    cases = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{cases_path}:{number}"
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{where}: not valid JSON ({exc})") from exc
        cases.append(_case(data, names, where))
    if not cases:
        raise DatasetError(f"{cases_path}: there are no cases")
    ids = [case.id for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise DatasetError(f"{cases_path}: case ids are used twice: {', '.join(duplicates)}")

    return Dataset(name=manifest["name"], version=manifest["version"],
                   description=manifest.get("description", ""), documents=documents,
                   cases=tuple(cases))


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatasetError(f"{path}: cannot be read ({exc.strerror})") from exc
    except json.JSONDecodeError as exc:
        raise DatasetError(f"{path}: not valid JSON ({exc})") from exc


def _document(directory: Path, name: str) -> DatasetDocument:
    path = directory / "documents" / name
    content_type = CONTENT_TYPES.get(path.suffix.lower())
    if content_type is None:
        raise DatasetError(f"{path}: only {', '.join(CONTENT_TYPES)} documents are supported")
    if not path.is_file():
        raise DatasetError(f"{path}: the document does not exist")
    return DatasetDocument(name=name, path=path, content_type=content_type)


def _case(data: dict, documents: set[str], where: str) -> Case:
    case_id = data.get("id")
    question = data.get("question")
    if not case_id or not isinstance(question, str) or not question.strip():
        raise DatasetError(f"{where}: a case needs an 'id' and a 'question'")
    sources = []
    for source in data.get("expected_sources", []):
        file, evidence = source.get("file"), source.get("evidence")
        if file not in documents:
            raise DatasetError(f"{where}: '{file}' is not one of the dataset's documents")
        if not evidence or not evidence.strip():
            raise DatasetError(f"{where}: an expected source needs its 'evidence'")
        sources.append(ExpectedSource(file=file, evidence=evidence))
    answer = data.get("reference_answer")
    # An answerable question needs its answer; an unanswerable one has none.
    if bool(sources) != bool(answer):
        raise DatasetError(f"{where}: a case has expected sources and a reference answer, "
                           f"or neither")
    forbidden = data.get("forbidden", [])
    if not isinstance(forbidden, list) or not all(
            isinstance(text, str) and text.strip() for text in forbidden):
        raise DatasetError(f"{where}: 'forbidden' must be a list of texts")
    return Case(id=case_id, question=question, tags=tuple(data.get("tags", [])),
                expected_sources=tuple(sources), reference_answer=answer,
                forbidden=tuple(forbidden))
