"""Command-line tools. Run `ragolex --help`."""

import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
import uuid
from datetime import date
from pathlib import Path

from ragolex.connectors.factory import create_crawler
from ragolex.core.config import Settings, get_settings
from ragolex.core.errors import AppError
from ragolex.core.logging_config import configure_logging
from ragolex.domain.models import DEFAULT_TENANT, SCOPES
from ragolex.embeddings.factory import create_embedder
from ragolex.evaluation.dataset import Dataset, DatasetError, load_dataset
from ragolex.evaluation.report import (
    BaselineMismatch,
    add_answers,
    baseline_from,
    build_report,
    compare,
)
from ragolex.llm.factory import create_llm
from ragolex.loaders.registry import default_loader_registry
from ragolex.persistence.database import (
    EmbeddingDimensionsMismatch,
    create_engine,
    create_session_factory,
    match_embedding_dimensions,
    resize_embeddings,
    stored_embedding_dimensions,
)
from ragolex.persistence.repositories import (
    SqlTenantRepository,
    SqlUnitOfWork,
    unit_of_work_factory,
)
from ragolex.rerankers.factory import create_reranker
from ragolex.scanners.factory import create_scanner
from ragolex.services.answer_service import AnswerService
from ragolex.services.audit import AuditService, record
from ragolex.services.auth_service import AuthService
from ragolex.services.evaluation_service import (
    AnswerSettings,
    EvaluationService,
    Usage,
)
from ragolex.services.feedback_export_service import FeedbackExportService
from ragolex.services.indexing_service import IndexingService
from ragolex.services.job_runner import JobRunner
from ragolex.services.processing_service import ProcessingService
from ragolex.services.search_service import SearchService
from ragolex.services.source_syncer import SourceSyncer
from ragolex.services.upload_service import UploadService
from ragolex.services.webhook_dispatcher import WebhookDispatcher
from ragolex.storage.file_storage import FileStorage
from ragolex.webhooks.factory import create_webhook_sender

# Exit codes of `ragolex eval`.
PASSED, REGRESSED, FAILED = 0, 1, 2


async def _resize_embeddings() -> int:
    settings = get_settings()
    wanted = settings.EMBEDDING_DIMENSIONS
    engine = create_engine(settings.DATABASE_URL)
    try:
        stored = await stored_embedding_dimensions(engine)
        if stored is None:
            print("Could not read the vector size: the database is unreachable or not "
                  "migrated yet (run `alembic upgrade head`).", file=sys.stderr)
            return 1
        if stored == wanted:
            print(f"Vectors already have {wanted} dimensions; nothing to change.")
            return 0
        cleared = await resize_embeddings(engine, wanted)
    finally:
        await engine.dispose()
    print(f"Vectors now have {wanted} dimensions instead of {stored}. {cleared} stored "
          f"vectors were cleared: index your projects again to embed them with "
          f"{settings.EMBEDDING_MODEL}.")
    return 0


async def _run(settings: Settings, args: argparse.Namespace, dataset: Dataset) -> dict:
    embedder = create_embedder(settings)
    if embedder is None:
        raise _Failure("No embedding model is configured: set OPENAI_API_KEY, or "
                       "EMBEDDING_BASE_URL for an OpenAI-compatible server such as Ollama.")
    llm = judge = None
    if args.answers:
        llm = create_llm(settings)
        if llm is None:
            await embedder.aclose()
            raise _Failure("--answers needs a language model: set OPENAI_API_KEY, or "
                           "LLM_BASE_URL for an OpenAI-compatible server such as Ollama.")
        # The judge grades at temperature 0, so the same answer gets the same grade.
        judge = create_llm(settings.model_copy(update={
            "LLM_MODEL": args.judge_model or settings.LLM_MODEL, "LLM_TEMPERATURE": 0.0}))
    parameters = _parameters(settings, args, dataset)
    reranker = create_reranker(settings)
    engine = create_engine(settings.DATABASE_URL)
    try:
        if await stored_embedding_dimensions(engine) is None:
            raise _Failure("The database is unreachable or not migrated yet "
                           "(run `alembic upgrade head`).")
        await match_embedding_dimensions(engine, settings.EMBEDDING_DIMENSIONS)
        # The documents' files only live as long as the run.
        with tempfile.TemporaryDirectory(prefix="ragolex-eval-") as files:
            async with create_session_factory(engine)() as session:
                # Evaluations run in the default tenant, apart from its projects by name.
                tenant = await SqlTenantRepository(session).get_or_create(DEFAULT_TENANT)
                await session.commit()
                uow = SqlUnitOfWork(session, tenant.id)
                storage = FileStorage(root=Path(files))
                search = SearchService(uow=uow, embedder=embedder,
                                       mode=parameters["search_mode"], reranker=reranker,
                                       rerank_candidates=settings.RERANK_CANDIDATES)
                service = EvaluationService(
                    uow=uow,
                    upload=UploadService(storage=storage, uow=uow,
                                         allowed_types=settings.FILE_ALLOWED_TYPES,
                                         max_bytes=settings.max_upload_bytes,
                                         read_size=settings.FILE_DEFAULT_CHUNK_SIZE),
                    processing=ProcessingService(storage=storage,
                                                 loaders=default_loader_registry(), uow=uow),
                    indexing=IndexingService(uow=uow, embedder=embedder,
                                             batch_size=settings.EMBEDDING_BATCH_SIZE),
                    search=search)
                answers = None
                if llm is not None and judge is not None:
                    answers = AnswerSettings(
                        answers=AnswerService(search=search, llm=llm, uow=uow,
                                              min_score=parameters["min_score"],
                                              prices=settings.llm_prices),
                        judge=judge, min_score=parameters["min_score"],
                        # Another judge model has prices of its own, which are not configured.
                        judge_prices=None if args.judge_model else settings.llm_prices)
                run = await service.run(dataset, top_k=args.top_k, chunk_size=args.chunk_size,
                                        overlap_size=args.overlap_size, answers=answers)
    except EmbeddingDimensionsMismatch as exc:
        raise _Failure(str(exc)) from exc
    finally:
        await embedder.aclose()
        for model in (llm, judge, reranker):
            if model is not None:
                await model.aclose()
        await engine.dispose()

    report = build_report(dataset=dataset, parameters=parameters, results=run.results,
                          chunks=run.chunks, seconds=run.seconds, version=settings.APP_VERSION)
    if answers is not None:
        add_answers(report, run.answers, parameters={
            "llm_model": settings.LLM_MODEL, "judge_model": answers.judge.model,
            "answer_prompt": answers.answers.prompt.version,
            "judge_prompt": answers.judge_prompt.version,
        }, usage={"answers": _usage(run.answer_usage), "judge": _usage(run.judge_usage)})
    return report


def _usage(usage: Usage | None) -> dict | None:
    if usage is None:
        return None
    cost = None if usage.cost_usd is None else round(usage.cost_usd, 6)
    return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "cost_usd": cost}


def _parameters(settings: Settings, args: argparse.Namespace, dataset: Dataset) -> dict:
    return {
        "dataset": dataset.label,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
        "search_mode": args.search_mode or settings.SEARCH_MODE,
        "reranker": _reranker_name(settings),
        "top_k": args.top_k,
        "chunk_size": args.chunk_size,
        "overlap_size": args.overlap_size,
        "min_score": settings.ANSWER_MIN_SCORE if args.min_score is None else args.min_score,
    }


def _reranker_name(settings: Settings) -> str | None:
    """The reranking model, or None when search is not reranked."""
    if not settings.RERANK_BASE_URL:
        return None
    return settings.RERANK_MODEL or "the server's default model"


class _Failure(Exception):
    """The evaluation could not run; the message says why."""


def _percent(value: float | None) -> str:
    return "     –" if value is None else f"{value:6.1%}"


def _print_summary(report: dict) -> None:
    parameters, metrics, dataset = report["parameters"], report["metrics"], report["dataset"]
    print(f"Retrieval on {parameters['dataset']}: {dataset['cases']} questions "
          f"({metrics['answerable']} answerable), {dataset['documents']} documents in "
          f"{dataset['chunks']} chunks")
    print(f"{parameters['embedding_model']} ({parameters['embedding_dimensions']} dimensions), "
          f"{parameters['search_mode']} search"
          + (f" reranked by {parameters['reranker']}" if parameters["reranker"] else "")
          + f", top {parameters['top_k']}, chunks of {parameters['chunk_size']} with "
          f"{parameters['overlap_size']} overlap, min score {parameters['min_score']}")
    print()
    rows = [("hit rate", "hit_rate", "answerable questions with a relevant result"),
            (f"recall@{parameters['top_k']}", "recall", "expected sources found"),
            ("MRR", "mrr", "1 / rank of the first relevant result, averaged"),
            ("above min score", "above_min_score", "answerable questions that would be answered"),
            ("rejected", "rejected", "unanswerable questions with no result at min score")]
    for label, key, meaning in rows:
        print(f"  {label:<16}{_percent(metrics[key])}   {meaning}")
    suggestion = report["suggested_min_score"]
    if suggestion:
        print(f"\n  A min score of {suggestion['min_score']} would answer "
              f"{suggestion['above_min_score']:.0%} of the answerable questions and reject "
              f"{suggestion['rejected']:.0%} of the others.")
    elif metrics["answerable"] and metrics["unanswerable"]:
        print("\n  No min score separates the answerable questions from the others: the "
              "unanswerable ones score as high as the relevant results.")
    if report["metrics_by_tag"]:
        print(f"\n  {'tag':<14}{'questions':>10}{'hit rate':>10}{'MRR':>8}")
        for tag, values in report["metrics_by_tag"].items():
            print(f"  {tag:<14}{values['answerable'] + values['unanswerable']:>10}"
                  f"{_percent(values['hit_rate']):>10}{_percent(values['mrr']):>8}")
    missed = [case for case in report["cases"]
              if case["answerable"] and case["first_relevant_rank"] is None]
    if missed:
        print(f"\n  No relevant result in the top {parameters['top_k']}:")
        for case in missed:
            print(f"    {case['id']}: {case['question']}")
    if "answer_metrics" in report:
        _print_answers(report)
    seconds = report["seconds"]
    print(f"\n  Took {seconds['processing']} s to process, {seconds['indexing']} s to index "
          f"and {seconds['search']} s to search"
          + (f", {seconds['answers']} s to answer and grade." if "answers" in seconds else "."))


def _print_answers(report: dict) -> None:
    parameters, metrics = report["answer_parameters"], report["answer_metrics"]
    print(f"\nAnswers by {parameters['llm_model']} ({parameters['answer_prompt']}), graded by "
          f"{parameters['judge_model']} ({parameters['judge_prompt']})")
    print()
    rows = [("answered", "answered", "answerable questions that got an answer"),
            ("abstained", "abstained", "unanswerable questions answered with no_answer"),
            ("citation precision", "citation_precision", "citations of an expected passage"),
            ("cites expected", "cites_expected", "answers citing an expected passage"),
            ("grounded", "grounded", "statements supported by the cited sources, per the judge"),
            ("correct", "correct", "agreement with the reference answer, per the judge")]
    for label, key, meaning in rows:
        print(f"  {label:<19}{_percent(metrics[key])}   {meaning}")
    if metrics["unjudged"]:
        print(f"  The judge gave no clear verdict on {metrics['unjudged']} answers.")
    wrong = [case for case in report["cases"]
             if case.get("answer") and case["answer"]["correct"] is not None
             and case["answer"]["correct"] < 1]
    if wrong:
        print("\n  Not fully correct:")
        for case in wrong:
            print(f"    {case['id']}: {case['answer']['reason'] or case['question']}")
    usage = report["answer_usage"]
    for name in ("answers", "judge"):
        spent = usage[name]
        if spent and spent["input_tokens"] is not None:
            cost = "" if spent["cost_usd"] is None else f", ${spent['cost_usd']:.4f}"
            print(f"  {name.capitalize()}: {spent['input_tokens']:,} tokens in, "
                  f"{spent['output_tokens']:,} out{cost}")


def _read_baseline(path: Path) -> dict:
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise _Failure(f"The baseline {path} cannot be read ({exc.strerror}). Create it "
                       f"with --save-baseline.") from exc
    except json.JSONDecodeError as exc:
        raise _Failure(f"The baseline {path} is not valid JSON ({exc}).") from exc
    if not isinstance(baseline.get("parameters"), dict) or not isinstance(
            baseline.get("metrics"), dict):
        raise _Failure(f"The baseline {path} needs 'parameters' and 'metrics'.")
    return baseline


def _check_baseline(report: dict, baseline: dict, path: Path, tolerance: float) -> int:
    try:
        comparisons = compare(report, baseline)
    except BaselineMismatch as exc:
        raise _Failure(f"The baseline {path} cannot be compared: {exc}") from exc
    print(f"\nCompared with {path} (a drop of more than {tolerance:.1%} fails):")
    regressed = False
    for comparison in comparisons:
        worse = comparison.change < -tolerance
        regressed |= worse
        verdict = "lower" if worse else "better" if comparison.change > tolerance else "ok"
        print(f"  {comparison.metric:<16}{_percent(comparison.baseline)} → "
              f"{_percent(comparison.current)}   {verdict}")
    if regressed:
        print("Retrieval got worse than the baseline.")
        return REGRESSED
    if any(comparison.change > tolerance for comparison in comparisons):
        print("Retrieval got better: update the baseline with --save-baseline to keep it.")
    return PASSED


async def _evaluate(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        dataset = load_dataset(args.dataset)
        baseline = None
        if args.baseline:
            baseline = _read_baseline(args.baseline)
            # Fail before the run when its parameters cannot match.
            compare({"parameters": _parameters(settings, args, dataset), "metrics": {}},
                    {**baseline, "metrics": {}})
        report = await _run(settings, args, dataset)
        _print_summary(report)
        if args.output:
            args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
            print(f"\nReport written to {args.output}.")
        if args.save_baseline:
            args.save_baseline.write_text(json.dumps(baseline_from(report), indent=2) + "\n",
                                          encoding="utf-8")
            print(f"Baseline written to {args.save_baseline}.")
        if baseline is not None:
            return _check_baseline(report, baseline, args.baseline, args.tolerance)
        return PASSED
    except BaselineMismatch as exc:
        print(f"The baseline {args.baseline} cannot be compared: {exc}", file=sys.stderr)
        return FAILED
    except (DatasetError, _Failure) as exc:
        print(exc, file=sys.stderr)
        return FAILED
    except AppError as exc:
        # For example the embedding model failing; its cause says why.
        cause = f" ({exc.__cause__})" if exc.__cause__ else ""
        print(f"The evaluation failed: {exc}{cause}", file=sys.stderr)
        return FAILED


async def _export_feedback(args: argparse.Namespace) -> int:
    settings = get_settings()
    output: Path = args.output
    if output.exists() and any(output.iterdir()):
        print(f"{output} is not empty; choose a new folder for the dataset.", file=sys.stderr)
        return FAILED
    engine = create_engine(settings.DATABASE_URL)
    try:
        async with create_session_factory(engine)() as session:
            tenants = SqlTenantRepository(session)
            # The default tenant exists once anything used it; an empty database has none yet.
            tenant = await (tenants.get_or_create(args.tenant) if args.tenant == DEFAULT_TENANT
                            else tenants.get_by_name(args.tenant))
            if tenant is None:
                print(f"There is no tenant {args.tenant!r}.", file=sys.stderr)
                return FAILED
            service = FeedbackExportService(uow=SqlUnitOfWork(session, tenant.id),
                                            storage=FileStorage(root=settings.FILES_DIR))
            export = await service.export(args.project)
    except AppError as exc:
        print(f"The feedback could not be exported: {exc}", file=sys.stderr)
        return FAILED
    except OSError as exc:
        print(f"The database is unreachable ({exc}).", file=sys.stderr)
        return FAILED
    finally:
        await engine.dispose()

    (output / "documents").mkdir(parents=True, exist_ok=True)
    for document in export.documents:
        shutil.copyfile(document.path, output / "documents" / document.name)
    # Its own name, so it is never mistaken for a released dataset or compared with its baseline.
    project = re.sub(r"[^a-z0-9-]+", "-", args.project.lower()).strip("-")
    name = args.name or f"{project}-feedback".lstrip("-")
    manifest = {"name": name, "version": "v1",
                "description": f"Questions rated in the project {args.project}, with its "
                               f"documents, exported on {date.today().isoformat()}.",
                "documents": [document.name for document in export.documents]}
    (output / "dataset.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for file_name, rows in (("cases.jsonl", export.cases),
                            ("cases-to-review.jsonl", export.to_review)):
        (output / file_name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8")
    print(f"Exported {len(export.documents)} documents, {len(export.cases)} cases from answers "
          f"rated thumbs up, and {len(export.to_review)} rated answers to review, to {output}.")
    print("Check the cases, write reference answers and expected sources for the ones in "
          "cases-to-review.jsonl and move them into cases.jsonl, then run "
          f"`ragolex eval {output}`.")
    return PASSED


async def _tenants_and_keys(args: argparse.Namespace) -> int:
    """`ragolex tenants …`, `ragolex keys …` and `ragolex audit`."""
    engine = create_engine(get_settings().DATABASE_URL)
    try:
        async with create_session_factory(engine)() as session:
            uow = SqlUnitOfWork(session)
            service = AuthService(uow)
            if args.command == "tenants" and args.action == "create":
                tenant = await service.create_tenant(args.name)
                print(f"Tenant {tenant.name} (id {tenant.id}) is ready.")
                return 0
            if args.command == "tenants" and args.action == "limits":
                limited = await uow.tenants.get_by_name(args.name)
                if limited is None:
                    print(f"There is no tenant {args.name!r}.", file=sys.stderr)
                    return 1
                changes = {name: (None if value == "default" else int(value))
                           for name in ("requests_per_minute", "answers_per_month", "storage_mb")
                           if (value := getattr(args, name)) is not None}
                await uow.tenants.set_limits(limited.id, changes)
                await record(uow, limited.id, "tenant.limits_changed", limited.name,
                             changes=changes)
                await uow.commit()
                print(_limits_line(await uow.tenants.get_by_id(limited.id)))
                return 0
            if args.command == "tenants":
                for tenant in await uow.tenants.list_all():
                    print(f"{tenant.id}\t{tenant.name}\t{tenant.created_at:%Y-%m-%d}\t"
                          f"{_limits_line(tenant)}")
                return 0
            owner = await uow.tenants.get_by_name(args.tenant)
            if owner is None:
                print(f"There is no tenant {args.tenant!r}; create it with "
                      f"`ragolex tenants create {args.tenant}`.", file=sys.stderr)
                return 1
            if args.command == "audit":
                page = await AuditService(uow).list(owner.id, action=args.action, offset=0,
                                                    limit=args.limit)
                for event in page.items:
                    who = event.actor_key_name or event.actor_key_id or "operator"
                    details = json.dumps(event.details, ensure_ascii=False, sort_keys=True)
                    print(f"{event.created_at:%Y-%m-%d %H:%M:%S}\t{event.action}\t"
                          f"{event.target or '-'}\t{who}\t{details}")
                return 0
            if args.action == "create":
                created, key = await service.create_key(owner.id, args.name,
                                                        args.scope or list(SCOPES))
                print(f"Key {created.id} for {owner.name}, with {', '.join(created.scopes)}:")
                print(key)
                print("Keep it now: it is not stored and cannot be shown again.", file=sys.stderr)
                return 0
            if args.action == "list":
                for api_key in await service.list_keys(owner.id):
                    state = "revoked" if api_key.revoked_at else "active"
                    print(f"{api_key.id}\t{api_key.prefix}…\t{api_key.name}\t"
                          f"{','.join(api_key.scopes)}\t{state}")
                return 0
            await service.revoke_key(owner.id, args.key_id)
            print(f"Key {args.key_id} is revoked.")
            return 0
    except AppError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


async def _work(workers: int) -> int:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    engine = create_engine(settings.DATABASE_URL)
    embedder = create_embedder(settings)
    sender = create_webhook_sender(settings)
    unit_of_work = unit_of_work_factory(create_session_factory(engine))
    runner = JobRunner(unit_of_work, FileStorage(root=settings.FILES_DIR),
                       default_loader_registry(), embedder, settings.EMBEDDING_BATCH_SIZE)
    dispatcher = WebhookDispatcher(unit_of_work, sender)
    crawler = create_crawler(settings)
    scanner = create_scanner(settings)
    syncer = SourceSyncer.from_settings(settings, unit_of_work, crawler, scanner)
    print(f"Running jobs with {workers} workers, sending webhooks and syncing websites; "
          "stop with Ctrl+C.", flush=True)
    try:
        await asyncio.gather(dispatcher.run(), syncer.run(),
                             *(runner.run() for _ in range(workers)))
    finally:
        await crawler.aclose()
        if embedder is not None:
            await embedder.aclose()
        await sender.aclose()
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ragolex", description="Ragolex maintenance commands.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser(
        "resize-embeddings",
        help="change the stored vector size to EMBEDDING_DIMENSIONS, for an embedding model "
             "with vectors of another length; clears the stored vectors",
        description="Change the database's vector size to EMBEDDING_DIMENSIONS. Stored vectors "
                    "are cleared, because vectors of another model cannot be compared with new "
                    "ones; the chunks stay, and indexing embeds them again.")
    evaluate = commands.add_parser(
        "eval",
        help="measure how well search finds the sources that answer a dataset's questions",
        description="Upload, split and index a dataset's documents in a temporary project, "
                    "search for each of its questions, and report how well the expected "
                    "sources were found. Uses the configured embedding model and database; "
                    "the temporary project is deleted afterwards. Exits with 1 when a metric "
                    "falls below --baseline, and 2 when the evaluation cannot run.")
    evaluate.add_argument("dataset", type=Path, help="the dataset folder, e.g. evals/handbook/v1")
    evaluate.add_argument("--search-mode", choices=["hybrid", "vector"],
                          help="hybrid or vector search (default SEARCH_MODE)")
    evaluate.add_argument("--top-k", type=_positive, default=5,
                          help="results per question (default 5, as for answers)")
    evaluate.add_argument("--chunk-size", type=_positive, default=1000,
                          help="characters per chunk (default 1000, as for uploads)")
    evaluate.add_argument("--overlap-size", type=_non_negative, default=200,
                          help="characters of overlap between chunks (default 200)")
    evaluate.add_argument("--min-score", type=float,
                          help="the minimum score for an answer (default ANSWER_MIN_SCORE)")
    evaluate.add_argument("--answers", action="store_true",
                          help="also answer every question with the configured language model "
                               "and have a judge grade the answers (costs model calls)")
    evaluate.add_argument("--judge-model",
                          help="the model that grades answers (default LLM_MODEL, on the same "
                               "server)")
    evaluate.add_argument("--output", type=Path, help="write the full JSON report here")
    evaluate.add_argument("--baseline", type=Path,
                          help="fail when a metric is lower than in this baseline")
    evaluate.add_argument("--tolerance", type=float, default=0.02,
                          help="how much lower a metric may be than the baseline (default 0.02)")
    evaluate.add_argument("--save-baseline", type=Path,
                          help="write this run's parameters and metrics as a baseline")
    export = commands.add_parser(
        "feedback-export",
        help="turn a project's rated answers into an evaluation dataset",
        description="Write a dataset folder with the project's documents and its rated answers: "
                    "answers rated thumbs up become cases, with the passages they cited as "
                    "expected sources; answers rated thumbs down go to cases-to-review.jsonl, "
                    "to be completed by hand.")
    export.add_argument("project", help="the project whose feedback to export")
    export.add_argument("output", type=Path, help="a new folder for the dataset")
    export.add_argument("--name", help="the dataset's name (default: <project>-feedback)")
    export.add_argument("--tenant", default=DEFAULT_TENANT,
                        help="the tenant that owns the project (default: default)")
    worker = commands.add_parser(
        "worker",
        help="run background jobs (processing and indexing files) and send webhooks until "
             "stopped",
        description="Take queued jobs and run them, as the API's own workers do (JOB_WORKERS). "
                    "Run as many as you like, on any machine with the same database and "
                    "FILES_DIR: each job runs once. Set JOB_WORKERS=0 for an API that only "
                    "queues jobs.")
    worker.add_argument("--workers", type=_positive,
                        help="jobs to run at once (default JOB_WORKERS, or 1 when it is 0)")
    tenants = commands.add_parser("tenants", help="create and list tenants",
                                  description="Tenants keep their projects apart; API keys "
                                              "belong to one.")
    tenant_actions = tenants.add_subparsers(dest="action", required=True, metavar="action")
    create_tenant = tenant_actions.add_parser("create", help="create a tenant")
    create_tenant.add_argument("name", type=_tenant_name, help="letters, digits, _ and -")
    tenant_actions.add_parser("list", help="list tenants with their limits")
    tenant_limits = tenant_actions.add_parser(
        "limits", help="set a tenant's rate limit and quotas",
        description="Each value is a number (0 is unlimited) or 'default' for the server's "
                    "setting (RATE_LIMIT_PER_MINUTE, ANSWERS_PER_MONTH, STORAGE_MB_PER_TENANT).")
    tenant_limits.add_argument("name")
    for option in ("requests-per-minute", "answers-per-month", "storage-mb"):
        tenant_limits.add_argument(f"--{option}", type=_limit, metavar="N|default")
    keys = commands.add_parser("keys", help="create, list and revoke a tenant's API keys")
    key_actions = keys.add_subparsers(dest="action", required=True, metavar="action")
    create_key = key_actions.add_parser("create", help="create a key; it is printed once")
    create_key.add_argument("--tenant", required=True)
    create_key.add_argument("--name", required=True, help="what the key is for")
    create_key.add_argument("--scope", action="append", choices=SCOPES,
                            help="repeat for several (default: all of them)")
    list_keys = key_actions.add_parser("list", help="list a tenant's keys")
    list_keys.add_argument("--tenant", required=True)
    revoke_key = key_actions.add_parser("revoke", help="revoke a key at once")
    revoke_key.add_argument("--tenant", required=True)
    revoke_key.add_argument("key_id", type=_key_id, help="the id `keys list` shows")
    openapi = commands.add_parser(
        "openapi",
        help="write the API's OpenAPI schema, which the SDKs are generated from",
        description="Write the OpenAPI schema of the API as JSON, as served at /openapi.json. "
                    "sdk/openapi.json is this output, and the SDKs are generated from it.")
    openapi.add_argument("--output", type=Path, help="write it here instead of to stdout")
    audit = commands.add_parser("audit", help="show a tenant's audit log, most recent first")
    audit.add_argument("--tenant", required=True)
    audit.add_argument("--action", help="only actions that start with this, e.g. api_key")
    audit.add_argument("--limit", type=_positive, default=50, help="events to show (default 50)")
    args = parser.parse_args(argv)
    if args.command == "openapi":
        return _write_openapi(args.output)
    if args.command in ("tenants", "keys", "audit"):
        return asyncio.run(_tenants_and_keys(args))
    if args.command == "worker":
        workers = args.workers or get_settings().JOB_WORKERS or 1
        try:
            return asyncio.run(_work(workers))
        except KeyboardInterrupt:
            # Running jobs went back to the queue as the workers stopped.
            return 0
    if args.command == "feedback-export":
        return asyncio.run(_export_feedback(args))
    if args.command == "eval":
        if args.overlap_size >= args.chunk_size:
            parser.error("--overlap-size must be smaller than --chunk-size")
        if args.judge_model and not args.answers:
            parser.error("--judge-model needs --answers")
        return asyncio.run(_evaluate(args))
    return asyncio.run(_resize_embeddings())


def _write_openapi(output: Path | None) -> int:
    from ragolex.main import create_app  # The API, only for this command.

    schema = json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"
    if output is None:
        sys.stdout.write(schema)
    else:
        output.write_text(schema, encoding="utf-8")
    return 0


def _limits_line(tenant) -> str:
    def show(value):
        return "default" if value is None else ("unlimited" if value == 0 else str(value))
    return (f"requests/minute {show(tenant.requests_per_minute)}, "
            f"answers/month {show(tenant.answers_per_month)}, "
            f"storage MB {show(tenant.storage_mb)}")


def _limit(value: str) -> str:
    if value == "default" or (value.isdigit() and int(value) <= 2_000_000_000):
        return value
    raise argparse.ArgumentTypeError("use a number of 0 or more, or 'default'")


def _key_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("not a key id") from None


def _tenant_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise argparse.ArgumentTypeError("use 1-64 letters, digits, _ and -")
    return value


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _non_negative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return number


if __name__ == "__main__":
    sys.exit(main())
