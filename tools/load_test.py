"""Load-test a running Ragolex: concurrent searches and answers, with latency percentiles.

Point it at a server whose project already has indexed documents. With the
stand-in models of tools/fake_models.py, it measures Ragolex itself (search
in PostgreSQL, prompts, bookkeeping) rather than a model provider:

    python tools/load_test.py --url http://127.0.0.1:8000 --key ragolex_… \\
        --project handbook --concurrency 16 --seconds 30

Each worker repeats one request, chosen in turn from search and ask (or only
--only search), with questions from --questions (one per line) or a built-in
list. Results go to stdout as a table; --json writes them for comparing runs.
The tenant's rate limit applies as for any client: give the key's tenant no
limit (`ragolex tenants limits … --requests-per-minute 0`) to measure capacity.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx

QUESTIONS = [
    "How many vacation days do I get?",
    "When can production deploys happen?",
    "What does the company pay for hotels?",
    "How do I report a security incident?",
    "Can I work from another country?",
    "Who approves a deploy outside the window?",
    "How much is the home office allowance?",
    "What happens in the first week of onboarding?",
]


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


async def worker(client: httpx.AsyncClient, project: str, kinds: list[str],
                 questions: list[str], deadline: float, offset: int,
                 timings: dict[str, list[float]], outcomes: Counter) -> None:
    turn = offset
    while time.monotonic() < deadline:
        kind = kinds[turn % len(kinds)]
        question = questions[turn % len(questions)]
        turn += 1
        if kind == "search":
            request = client.post(f"/api/v1/search/{project}",
                                  json={"query": question, "top_k": 5})
        else:
            request = client.post(f"/api/v1/ask/{project}", json={"question": question})
        started = time.monotonic()
        try:
            response = await request
            status = str(response.status_code)
        except httpx.HTTPError as exc:
            status = type(exc).__name__
        elapsed = time.monotonic() - started
        outcomes[(kind, status)] += 1
        if status == "200":
            timings[kind].append(elapsed)


async def run(args: argparse.Namespace) -> dict:
    questions = (Path(args.questions).read_text().split("\n") if args.questions else QUESTIONS)
    questions = [q.strip() for q in questions if q.strip()]
    kinds = [args.only] if args.only else ["search", "ask"]
    headers = {"Authorization": f"Bearer {args.key}"} if args.key else {}
    timings: dict[str, list[float]] = defaultdict(list)
    outcomes: Counter = Counter()
    limits = httpx.Limits(max_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.url, headers=headers, timeout=args.timeout,
                                 limits=limits) as client:
        started = time.monotonic()
        deadline = started + args.seconds
        await asyncio.gather(*(worker(client, args.project, kinds, questions, deadline, n,
                                      timings, outcomes)
                               for n in range(args.concurrency)))
        elapsed = time.monotonic() - started
    report = {"url": args.url, "project": args.project, "concurrency": args.concurrency,
              "seconds": round(elapsed, 1), "endpoints": {}}
    for kind in kinds:
        done = timings[kind]
        statuses = {status: count for (k, status), count in outcomes.items() if k == kind}
        report["endpoints"][kind] = {
            "requests": sum(statuses.values()), "statuses": statuses,
            "per_second": round(len(done) / elapsed, 1),
            **({"p50_ms": round(statistics.median(done) * 1000),
                "p95_ms": round(percentile(done, 0.95) * 1000),
                "p99_ms": round(percentile(done, 0.99) * 1000),
                "max_ms": round(max(done) * 1000)} if done else {}),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--key", help="an API key with the ask scope (unset: no key)")
    parser.add_argument("--project", required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--only", choices=["search", "ask"])
    parser.add_argument("--questions", help="a file with one question per line")
    parser.add_argument("--json", help="also write the results to this file")
    args = parser.parse_args()

    report = asyncio.run(run(args))
    print(f"{report['concurrency']} workers for {report['seconds']} s against {report['url']}")
    print(f"{'endpoint':<8} {'requests':>8} {'per s':>7} {'p50':>7} {'p95':>7} {'p99':>7}"
          f" {'max':>7}  statuses")
    for kind, row in report["endpoints"].items():
        cells = [f"{row[key]:>5} ms" if key in row else f"{'-':>7}"
                 for key in ("p50_ms", "p95_ms", "p99_ms", "max_ms")]
        print(f"{kind:<8} {row['requests']:>8} {row['per_second']:>7} {' '.join(cells)}  "
              f"{row['statuses']}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    failed = sum(count for row in report["endpoints"].values()
                 for status, count in row["statuses"].items() if status != "200")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
