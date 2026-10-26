import pytest

from ragolex.core.errors import EmbeddingFailed
from ragolex.evaluation.dataset import load_dataset
from ragolex.loaders.registry import default_loader_registry
from ragolex.services.evaluation_service import EvaluationService, project_name
from ragolex.services.indexing_service import IndexingService
from ragolex.services.processing_service import ProcessingService
from ragolex.services.search_service import SearchService
from ragolex.services.upload_service import UploadService
from ragolex.storage.file_storage import FileStorage

from .fakes import FakeEmbedder, FakeUnitOfWork
from .test_eval_dataset import CAT, write_dataset

pytestmark = pytest.mark.anyio


def service(uow, embedder, files):
    storage = FileStorage(root=files)
    return EvaluationService(
        uow=uow,
        upload=UploadService(storage=storage, uow=uow, allowed_types=["text/plain"],
                             max_bytes=1_000_000, read_size=1024),
        processing=ProcessingService(storage=storage, loaders=default_loader_registry(), uow=uow),
        indexing=IndexingService(uow=uow, embedder=embedder, batch_size=16),
        search=SearchService(uow=uow, embedder=embedder))


async def test_runs_each_question_through_upload_processing_indexing_and_search(tmp_path):
    dataset = load_dataset(write_dataset(tmp_path / "dataset", [CAT]))
    uow = FakeUnitOfWork()

    run = await service(uow, FakeEmbedder(), tmp_path / "files").run(
        dataset, top_k=3, chunk_size=1000, overlap_size=0)

    [result] = run.results
    assert result.first_relevant.file == "notes.txt"
    assert result.reciprocal_rank == 1.0
    assert run.chunks == 1
    assert set(run.seconds) == {"processing", "indexing", "search"}
    # The project is only there for the run.
    assert await uow.projects.get_by_name(project_name(dataset)) is None


async def test_the_project_is_deleted_when_the_run_fails(tmp_path):
    dataset = load_dataset(write_dataset(tmp_path / "dataset", [CAT]))
    uow = FakeUnitOfWork()

    with pytest.raises(EmbeddingFailed):
        await service(uow, FakeEmbedder(fail_on_call=1), tmp_path / "files").run(
            dataset, top_k=3, chunk_size=1000, overlap_size=0)

    assert await uow.projects.get_by_name(project_name(dataset)) is None


async def test_a_project_left_by_an_earlier_run_is_replaced(tmp_path):
    dataset = load_dataset(write_dataset(tmp_path / "dataset", [CAT]))
    uow = FakeUnitOfWork()
    left = await uow.projects.get_or_create(project_name(dataset))

    await service(uow, FakeEmbedder(), tmp_path / "files").run(
        dataset, top_k=3, chunk_size=1000, overlap_size=0)

    assert await uow.files.count_for_project(left.id) == 0


async def test_answers_are_written_and_graded(tmp_path):
    from ragolex.services.answer_service import AnswerService
    from ragolex.services.evaluation_service import AnswerSettings

    from .fakes import FakeLLM

    unanswerable = {"id": "dogs", "question": "Do dogs purr?", "expected_sources": [],
                    "reference_answer": None}
    dataset = load_dataset(write_dataset(tmp_path / "dataset", [CAT, unanswerable]))
    uow = FakeUnitOfWork()
    embedder = FakeEmbedder()
    evaluation = service(uow, embedder, tmp_path / "files")
    writer = FakeLLM("Cats purr when they are content [1].")
    judge = FakeLLM('{"grounded": "yes", "correct": "partly", "reason": "Short."}')

    run = await evaluation.run(dataset, top_k=3, chunk_size=1000, overlap_size=0,
                               answers=AnswerSettings(
                                   answers=AnswerService(search=evaluation.search, llm=writer,
                                                         uow=uow, min_score=-1.0),
                                   judge=judge, min_score=-1.0))

    cat, dog = run.answers
    assert cat.text == "Cats purr when they are content [1]."
    assert [(c.file, c.relevant) for c in cat.citations] == [("notes.txt", True)]
    assert (cat.grounded, cat.correct, cat.reason) == (1.0, 0.5, "Short.")
    # The unanswerable question was answered too, so only its grounding counts.
    assert (dog.grounded, dog.correct) == (1.0, None)
    judged = judge.calls[0][1].content
    assert "<reference>\nWhen they are content.\n</reference>" in judged
    assert "<answer>\nCats purr when they are content [1].\n</answer>" in judged
    assert run.answer_usage.input_tokens == 2 * 1200
    assert "answers" in run.seconds
