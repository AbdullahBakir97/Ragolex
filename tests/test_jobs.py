"""Background jobs: the API that queues them, and the worker that runs them."""

import asyncio
import time

import pytest

from ragolex.core.config import get_settings
from ragolex.core.errors import EmbeddingFailed
from ragolex.loaders.registry import default_loader_registry
from ragolex.persistence.database import create_engine, create_session_factory
from ragolex.persistence.repositories import unit_of_work_factory
from ragolex.services.job_runner import JobRunner
from ragolex.storage.file_storage import FileStorage

from .fakes import FakeEmbedder

TEXT = "\n\n".join(f"Paragraph {n} is about topic {n}." for n in range(6)).encode()


def upload(client, name="notes.txt", content=TEXT, project="p1"):
    response = client.post(f"/api/v1/data/upload/{project}",
                           files={"file": (name, content, "text/plain")})
    return response.json()["file_id"]


def enqueue(client, file_id, project="p1", **options):
    return client.post(f"/api/v1/projects/{project}/jobs",
                       json={"file_id": file_id, "chunk_size": 40, "overlap_size": 0, **options})


def job(client, job_id, project="p1"):
    return client.get(f"/api/v1/projects/{project}/jobs/{job_id}").json()


async def _with_runner(db, files_dir, embedder, work, **options):
    engine = create_engine(db)
    try:
        runner = JobRunner(unit_of_work_factory(create_session_factory(engine)),
                           FileStorage(root=files_dir), default_loader_registry(), embedder,
                           batch_size=2, **options)
        return await work(runner)
    finally:
        await engine.dispose()


@pytest.fixture
def claim(db):
    """Claim the next job as a worker that then stops, holding it for ``lease`` seconds."""
    def run(lease=0):
        async def work():
            engine = create_engine(db)
            try:
                async with unit_of_work_factory(create_session_factory(engine))() as uow:
                    claimed = await uow.jobs.claim(lease)
                    await uow.commit()
                    return claimed
            finally:
                await engine.dispose()
        return asyncio.run(work())
    return run


def test_a_queued_job_processes_and_indexes_the_file(client, run_jobs, query):
    file_id = upload(client)

    response = enqueue(client, file_id)

    assert response.status_code == 202
    queued = response.json()
    assert queued | {"id": None, "created_at": None} == {
        "id": None, "file_id": file_id, "status": "queued", "stage": None, "progress": 0.0,
        "chunks_count": None, "attempts": 0, "max_attempts": 3, "chunk_size": 40,
        "overlap_size": 0, "error": None, "created_at": None, "started_at": None,
        "finished_at": None}

    embedder = FakeEmbedder()
    assert run_jobs(embedder) == [True]

    done = job(client, queued["id"])
    assert (done["status"], done["stage"], done["progress"], done["attempts"]) == (
        "succeeded", "indexing", 1.0, 1)
    assert done["chunks_count"] == 6 == len(query("SELECT 1 FROM chunks WHERE embedding IS NOT NULL"))
    assert done["started_at"] <= done["finished_at"]
    # Six chunks in batches of two.
    assert [len(call) for call in embedder.calls] == [2, 2, 2]


def test_progress_is_recorded_after_each_batch(client, db, files_dir):
    enqueue(client, upload(client))
    seen = []

    class WatchingEmbedder(FakeEmbedder):
        async def embed(self, texts):
            seen.append(job(client, client.get("/api/v1/projects/p1/jobs").json()["items"][0]["id"]))
            return await super().embed(texts)

    asyncio.run(_with_runner(db, files_dir, WatchingEmbedder(), lambda runner: runner.run_next()))

    assert [(j["status"], j["stage"], round(j["progress"], 2)) for j in seen] == [
        ("running", "indexing", 0.0), ("running", "indexing", 0.33), ("running", "indexing", 0.67)]


def test_nothing_due_means_no_work(client, run_jobs):
    assert run_jobs(times=2) == [False, False]


def test_a_provider_failure_is_tried_again_later(client, run_jobs):
    job_id = enqueue(client, upload(client)).json()["id"]

    run_jobs(FakeEmbedder(fail_on_call=1), retry_delays=(3600,))

    waiting = job(client, job_id)
    assert (waiting["status"], waiting["attempts"], waiting["error"]) == (
        "queued", 1, "embedding_failed")
    # Not due for an hour.
    assert run_jobs() == [False]


def test_a_job_fails_after_its_last_attempt(client, run_jobs, monkeypatch):
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()
    job_id = enqueue(client, upload(client)).json()["id"]

    class AlwaysFailing(FakeEmbedder):
        async def embed(self, texts):
            raise EmbeddingFailed("down")

    assert run_jobs(AlwaysFailing(), times=3, retry_delays=(0,)) == [True, True, False]

    failed = job(client, job_id)
    assert (failed["status"], failed["attempts"], failed["max_attempts"], failed["error"]) == (
        "failed", 2, 2, "embedding_failed")
    assert failed["finished_at"] is not None


def test_a_file_without_text_fails_at_once(client, run_jobs, make_pdf):
    response = client.post("/api/v1/data/upload/p1",
                           files={"file": ("scan.pdf", make_pdf([""]), "application/pdf")})
    job_id = enqueue(client, response.json()["file_id"]).json()["id"]

    run_jobs()

    failed = job(client, job_id)
    assert (failed["status"], failed["attempts"], failed["error"]) == (
        "failed", 1, "file_has_no_text")


def test_without_an_embedding_model_the_file_is_only_processed(client, db, files_dir, query):
    job_id = enqueue(client, upload(client)).json()["id"]

    asyncio.run(_with_runner(db, files_dir, None, lambda runner: runner.run_next()))

    failed = job(client, job_id)
    assert (failed["status"], failed["stage"], failed["error"]) == (
        "failed", "processing", "embedding_not_configured")
    assert len(query("SELECT 1 FROM chunks")) == 6


def test_a_job_whose_worker_stopped_is_taken_up_again(client, claim, run_jobs):
    job_id = enqueue(client, upload(client)).json()["id"]
    assert claim(lease=0).id == job_id  # The lease runs out at once.

    run_jobs()

    done = job(client, job_id)
    assert (done["status"], done["attempts"]) == ("succeeded", 2)


def test_a_job_held_by_a_working_worker_is_left_alone(client, claim, run_jobs):
    enqueue(client, upload(client))
    claim(lease=3600)

    assert run_jobs() == [False]


def test_a_job_whose_worker_stopped_on_every_attempt_fails(client, claim, run_jobs, monkeypatch):
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "1")
    get_settings.cache_clear()
    job_id = enqueue(client, upload(client)).json()["id"]
    claim(lease=0)

    assert run_jobs() == [False]

    failed = job(client, job_id)
    assert (failed["status"], failed["error"]) == ("failed", "job_abandoned")


def test_two_workers_never_claim_the_same_job(client, db):
    ids = {enqueue(client, upload(client, f"{n}.txt", f"File {n}.".encode())).json()["id"]
           for n in range(4)}

    async def claim_all():
        engine = create_engine(db)
        factory = unit_of_work_factory(create_session_factory(engine))

        async def one():
            async with factory() as uow:
                claimed = await uow.jobs.claim(3600)
                await asyncio.sleep(0.05)  # Hold the row while the others claim.
                await uow.commit()
                return claimed.id if claimed else None
        try:
            return await asyncio.gather(*(one() for _ in range(6)))
        finally:
            await engine.dispose()

    claimed = asyncio.run(claim_all())

    assert sorted(c for c in claimed if c) == sorted(ids)
    assert claimed.count(None) == 2


def test_stopping_a_worker_returns_its_job_to_the_queue(client, db, files_dir):
    job_id = enqueue(client, upload(client)).json()["id"]
    started = asyncio.Event()

    class Hanging(FakeEmbedder):
        async def embed(self, texts):
            started.set()
            await asyncio.Event().wait()

    async def work(runner):
        task = asyncio.create_task(runner.run_next())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_with_runner(db, files_dir, Hanging(), work))

    queued = job(client, job_id)
    assert (queued["status"], queued["attempts"]) == ("queued", 0)


def test_the_worker_keeps_polling(client, db, files_dir):
    job_id = enqueue(client, upload(client)).json()["id"]

    async def work(runner):
        task = asyncio.create_task(runner.run())
        deadline = time.monotonic() + 10
        while job(client, job_id)["status"] != "succeeded" and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(_with_runner(db, files_dir, FakeEmbedder(), work, poll_seconds=0.05))

    assert job(client, job_id)["status"] == "succeeded"


def test_list_jobs_most_recent_first_and_by_status(client, run_jobs):
    first = enqueue(client, upload(client, "a.txt", b"Alpha.")).json()["id"]
    run_jobs()
    second = enqueue(client, upload(client, "b.txt", b"Beta.")).json()["id"]

    every = client.get("/api/v1/projects/p1/jobs").json()
    queued = client.get("/api/v1/projects/p1/jobs?status=queued").json()

    assert ([j["id"] for j in every["items"]], every["total"]) == ([second, first], 2)
    assert ([j["id"] for j in queued["items"]], queued["total"]) == ([second], 1)
    assert client.get("/api/v1/projects/p1/jobs?status=lost").status_code == 422


def test_retry_queues_a_failed_job_again(client, run_jobs, make_pdf):
    response = client.post("/api/v1/data/upload/p1",
                           files={"file": ("scan.pdf", make_pdf([""]), "application/pdf")})
    job_id = enqueue(client, response.json()["file_id"]).json()["id"]
    run_jobs()

    retried = client.post(f"/api/v1/projects/p1/jobs/{job_id}/retry")

    assert retried.status_code == 202
    assert retried.json() | {"created_at": None} == job(client, job_id) | {"created_at": None}
    assert (retried.json()["status"], retried.json()["attempts"], retried.json()["error"]) == (
        "queued", 0, None)
    again = client.post(f"/api/v1/projects/p1/jobs/{job_id}/retry")
    assert (again.status_code, again.json()) == (409, {"signal": "job_not_failed"})


@pytest.mark.parametrize(("path", "signal"), [
    ("/api/v1/projects/nope/jobs", "project_not_found"),
    ("/api/v1/projects/p1/jobs/00000000-0000-0000-0000-000000000000", "job_not_found"),
])
def test_unknown_projects_and_jobs(client, path, signal):
    upload(client)

    response = client.get(path)

    assert (response.status_code, response.json()) == (404, {"signal": signal})


def test_jobs_need_a_file_of_the_project(client):
    upload(client)

    response = enqueue(client, "abc_missing.txt")

    assert (response.status_code, response.json()) == (404, {"signal": "file_not_found"})
    assert enqueue(client, upload(client), chunk_size=10, overlap_size=10).status_code == 422


def test_deleting_a_file_deletes_its_jobs(client):
    file_id = upload(client)
    job_id = enqueue(client, file_id).json()["id"]

    client.delete(f"/api/v1/projects/p1/files/{file_id}")

    assert client.get(f"/api/v1/projects/p1/jobs/{job_id}").status_code == 404


def test_the_app_runs_jobs_with_its_own_workers(db, monkeypatch):
    from fastapi.testclient import TestClient

    from ragolex import main

    monkeypatch.setenv("JOB_WORKERS", "2")
    monkeypatch.setattr(main, "create_embedder", lambda settings: FakeEmbedder())
    get_settings.cache_clear()
    with TestClient(main.create_app()) as client:
        job_id = enqueue(client, upload(client)).json()["id"]
        deadline = time.monotonic() + 10
        while job(client, job_id)["status"] != "succeeded" and time.monotonic() < deadline:
            time.sleep(0.05)

        assert job(client, job_id)["status"] == "succeeded"


def test_the_worker_command_runs_the_configured_number_of_workers(db, monkeypatch, capsys):
    from ragolex import cli

    runs = []

    class Runner(JobRunner):
        async def run(self):
            runs.append(self)

    class Dispatcher(cli.WebhookDispatcher):
        async def run(self):
            pass

    class Syncer(cli.SourceSyncer):
        async def run(self):
            pass

    monkeypatch.setattr(cli, "JobRunner", Runner)
    monkeypatch.setattr(cli, "WebhookDispatcher", Dispatcher)
    monkeypatch.setattr(cli, "SourceSyncer", Syncer)
    monkeypatch.setenv("JOB_WORKERS", "0")
    get_settings.cache_clear()

    assert cli.main(["worker"]) == 0
    assert len(runs) == 1
    assert cli.main(["worker", "--workers", "3"]) == 0
    assert len(runs) == 4
    assert "Running jobs with 3 workers" in capsys.readouterr().out


def test_a_jobs_log_lines_carry_its_id(client, run_jobs, capsys):
    queued = enqueue(client, upload(client)).json()
    capsys.readouterr()

    run_jobs(FakeEmbedder())

    err = capsys.readouterr().err
    assert f"[request_id=job:{queued['id']}]: Job {queued['id']}: processing" in err
