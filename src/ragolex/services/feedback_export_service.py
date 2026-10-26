import re
from dataclasses import dataclass
from pathlib import Path

from ragolex.core.errors import FileNotFound, ProjectNotFound
from ragolex.domain.models import RatedAnswer, StoredCitation
from ragolex.domain.repositories import UnitOfWork
from ragolex.prompts.answer import strip_citations
from ragolex.storage.file_storage import FileStorage, clean_file_name

PAGE = 100
# Evidence is a short phrase, so it stays within one chunk however a document is split.
EVIDENCE_WORDS = 14
SUPPORTED = (".txt", ".pdf")


@dataclass(frozen=True)
class ExportedDocument:
    name: str
    path: Path


@dataclass(frozen=True)
class FeedbackExport:
    """A project's documents, and its rated answers as evaluation cases.

    ``cases`` come from answers rated thumbs up: their question, the
    passages they cited as expected sources, and the answer as reference.
    ``to_review`` are the answers rated thumbs down, which need a person to
    write the right answer before they can become cases.
    """

    documents: list[ExportedDocument]
    cases: list[dict]
    to_review: list[dict]


class FeedbackExportService:
    """Turns feedback on a project's answers into an evaluation dataset."""

    def __init__(self, uow: UnitOfWork, storage: FileStorage):
        self.uow = uow
        self.storage = storage

    async def export(self, project_name: str) -> FeedbackExport:
        project = await self.uow.projects.get_by_name(project_name)
        if project is None:
            raise ProjectNotFound()

        names: dict[str, str] = {}
        documents = []
        offset = 0
        while files := await self.uow.files.list_for_project(project.id, offset=offset,
                                                             limit=PAGE):
            for file in files:
                name = _document_name(file.original_name, file.key, set(names.values()))
                try:
                    path = self.storage.get_file_path(project.folder, file.key)
                except FileNotFound:
                    # Its record outlived the file; answers citing it go to review.
                    continue
                if name is not None:
                    names[file.key] = name
                    documents.append(ExportedDocument(name=name, path=path))
            offset += len(files)

        cases, to_review = [], []
        offset = 0
        while rated := await self.uow.conversations.rated_answers(project.id, rating=None,
                                                                  offset=offset, limit=PAGE):
            for answer in rated:
                case = _case(answer, names) if answer.feedback.rating == "up" else None
                if case is not None:
                    cases.append(case)
                else:
                    to_review.append(_to_review(answer, names))
            offset += len(rated)
        return FeedbackExport(documents=documents, cases=cases, to_review=to_review)


def _document_name(original: str, key: str, taken: set[str]) -> str | None:
    name = clean_file_name(original)
    if not name.lower().endswith(SUPPORTED):
        return None
    # Two uploads of the same name keep their upload id apart.
    return name if name not in taken else clean_file_name(key)


def _case(answer: RatedAnswer, names: dict[str, str]) -> dict | None:
    """A ready case from a thumbs-up answer; None when it cannot be one."""
    if answer.answer is None:
        return None
    sources = []
    for citation in answer.citations:
        if citation.file_key in names:
            source = {"file": names[citation.file_key],
                      "evidence": evidence(citation.text, answer.answer)}
            if source["evidence"] and source not in sources:
                sources.append(source)
    if not sources:
        return None
    return {"id": f"feedback-{answer.message_id}", "question": answer.question,
            "tags": ["feedback"], "expected_sources": sources,
            "reference_answer": strip_citations(answer.answer).strip()}


def _to_review(answer: RatedAnswer, names: dict[str, str]) -> dict:
    return {"id": f"feedback-{answer.message_id}", "question": answer.question,
            "rating": answer.feedback.rating, "comment": answer.feedback.comment,
            "answer_given": answer.answer,
            "cited": [_cited(citation, names) for citation in answer.citations],
            "tags": ["feedback"], "expected_sources": [], "reference_answer": None}


def _cited(citation: StoredCitation, names: dict[str, str]) -> dict:
    return {"file": names.get(citation.file_key, citation.file_key),
            "chunk_index": citation.chunk_index, "page": citation.page, "text": citation.text}


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", text.casefold()) if len(word) > 3}


def evidence(passage: str, answer: str) -> str:
    """The start of the passage's sentence that shares the most words with the answer."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(passage.split())) if s]
    if not sentences:
        return ""
    said = _words(answer)
    best = max(sentences, key=lambda sentence: len(_words(sentence) & said))
    return " ".join(best.split()[:EVIDENCE_WORDS])
