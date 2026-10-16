# /// script
# requires-python = ">=3.14"
# dependencies = ["httpx>=0.28.1"]
# ///
"""Load, stress, spike and soak tests against a running provider or engine.

Self-contained, so it runs from any machine with uv — and it should run from a
machine other than the one under test, or the two compete for the same cores:

    uv run perf/loadtest.py discovery
    uv run perf/loadtest.py permissions --token "$TOKEN" --mode stress
    uv run perf/loadtest.py engine-verify --url http://engine:8000 --mode load

Closed loop: each virtual user sends its next request when the last one
answers, so the numbers are what the server sustains at that concurrency, not
its latency at a fixed arrival rate. See doc/operations/performance.md.
"""

import argparse
import asyncio
import json
import os
import platform
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

REPOSITORY = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE = REPOSITORY / "engine/tests/data/astronaut.jpg"
# What a sign-in sends: three frames looking straight ahead, no movements.
VERIFY_FRAMES = 3

type Request = tuple[str, str, dict[str, Any]]


@dataclass
class Sample:
    finished: float
    latency_ms: float
    outcome: str  # the status code, or the exception's name


@dataclass
class Stats:
    label: str
    concurrency: int
    seconds: float
    requests: int
    rps: float
    ok: int
    error_rate: float
    p50_ms: float
    p90_ms: float
    p99_ms: float
    max_ms: float
    outcomes: dict[str, int]
    client_cpu: float


def _percentile(ordered: list[float], share: float) -> float:
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def summarise(
    label: str, samples: list[Sample], concurrency: int, seconds: float, cpu: float
) -> Stats:
    latencies = sorted(s.latency_ms for s in samples if s.outcome.isdigit())
    outcomes = Counter(s.outcome for s in samples)
    ok = sum(n for outcome, n in outcomes.items() if outcome.startswith("2"))
    return Stats(
        label=label,
        concurrency=concurrency,
        seconds=round(seconds, 1),
        requests=len(samples),
        rps=len(samples) / seconds if seconds else 0.0,
        ok=ok,
        error_rate=1 - ok / len(samples) if samples else 0.0,
        p50_ms=_percentile(latencies, 0.50),
        p90_ms=_percentile(latencies, 0.90),
        p99_ms=_percentile(latencies, 0.99),
        max_ms=latencies[-1] if latencies else 0.0,
        outcomes=dict(outcomes.most_common()),
        client_cpu=cpu,
    )


# --------------------------------------------------------------------------
# Scenarios: what one request is
# --------------------------------------------------------------------------


def _bearer(args: argparse.Namespace) -> dict[str, str]:
    if not args.token:
        raise SystemExit(f"{args.scenario} needs --token (or IDEN_TOKEN).")
    return {"Authorization": f"Bearer {args.token}"}


async def scenario(args: argparse.Namespace, client: httpx.AsyncClient) -> Request:
    match args.scenario:
        case "discovery":
            return "GET", "/.well-known/openid-configuration", {}
        case "jwks":
            return "GET", "/.well-known/jwks.json", {}
        case "sessions":
            return "GET", "/entity/sessions", {"headers": _bearer(args)}
        case "permissions":
            return "GET", "/entity/permissions", {"headers": _bearer(args)}
        case "token":
            if not (args.client_id and args.client_secret):
                raise SystemExit("token needs --client-id and --client-secret.")
            form = {
                "grant_type": "client_credentials",
                "client_id": args.client_id,
                "client_secret": args.client_secret,
            }
            if args.scope:
                form["scope"] = args.scope
            return "POST", "/oauth2/token", {"data": form}
        case "engine-verify":
            return await _engine_verify(args, client)
    raise SystemExit(f"Unknown scenario {args.scenario}.")


async def _engine_verify(
    args: argparse.Namespace, client: httpx.AsyncClient
) -> Request:
    """A sign-in's frames, compared with templates the engine made of the same
    photo — so every request is a match, the same work a real one costs."""
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    frame = args.image.read_bytes()
    embedded = await client.post(
        "/embed", files=[("frames", ("0.jpg", frame, "image/jpeg"))], headers=headers
    )
    embedded.raise_for_status()
    template = embedded.json()["embeddings"][0]
    if template is None:
        raise SystemExit(f"The engine found no single face in {args.image}.")
    steps = ["center"] * VERIFY_FRAMES
    files = [
        ("frames", (f"{i}.jpg", frame, "image/jpeg")) for i in range(VERIFY_FRAMES)
    ]
    meta = json.dumps({"steps": steps, "templates": [template]})
    return (
        "POST",
        "/verify",
        {"files": files, "data": {"meta": meta}, "headers": headers},
    )


# --------------------------------------------------------------------------
# Running a phase
# --------------------------------------------------------------------------


async def preflight(client: httpx.AsyncClient, request: Request) -> None:
    """One request first: a wrong URL or token is a message, not a table of
    thirty seconds of failures."""
    method, path, kwargs = request
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise SystemExit(f"Cannot reach {client.base_url}: {exc!r}") from exc
    if not response.is_success:
        raise SystemExit(
            f"{method} {path} answered {response.status_code}: {response.text[:300]}"
        )


async def run_phase(
    client: httpx.AsyncClient,
    request: Request,
    label: str,
    concurrency: int,
    seconds: float,
) -> tuple[Stats, list[Sample]]:
    method, path, kwargs = request
    samples: list[Sample] = []
    deadline = time.perf_counter() + seconds

    async def user() -> None:
        while time.perf_counter() < deadline:
            started = time.perf_counter()
            try:
                response = await client.request(method, path, **kwargs)
                outcome = str(response.status_code)
            except httpx.HTTPError as exc:
                outcome = type(exc).__name__
            finished = time.perf_counter()
            samples.append(Sample(finished, (finished - started) * 1000, outcome))

    began, cpu_began = time.perf_counter(), time.process_time()
    await asyncio.gather(*(user() for _ in range(concurrency)))
    elapsed = time.perf_counter() - began
    cpu = (time.process_time() - cpu_began) / elapsed
    return summarise(label, samples, concurrency, elapsed, cpu), samples


# --------------------------------------------------------------------------
# Modes: which phases, at what concurrency
# --------------------------------------------------------------------------

type Phase = Callable[[str, int, float], Any]


async def load(args: argparse.Namespace, phase: Phase) -> list[Stats]:
    stats, _ = await phase("load", args.concurrency, args.duration)
    return [stats]


async def stress(args: argparse.Namespace, phase: Phase) -> list[Stats]:
    """Double the concurrency until the server breaks a threshold or the
    ceiling is reached. The last row under both thresholds is its capacity."""
    results = []
    concurrency = args.start
    while concurrency <= args.max:
        stats, _ = await phase(f"x{concurrency}", concurrency, args.duration)
        results.append(stats)
        print(_row(stats), flush=True)
        if stats.error_rate > args.max_errors or stats.p99_ms > args.max_p99:
            break
        concurrency *= 2
    return results


async def spike(args: argparse.Namespace, phase: Phase) -> list[Stats]:
    """Steady, then a sudden crowd, then steady again: does it recover?"""
    results = []
    for label, concurrency in (
        ("before", args.concurrency),
        ("spike", args.spike),
        ("after", args.concurrency),
    ):
        stats, _ = await phase(label, concurrency, args.duration)
        results.append(stats)
        print(_row(stats), flush=True)
    return results


async def soak(args: argparse.Namespace, phase: Phase) -> list[Stats]:
    """One long run, reported per interval: latency that creeps up over an
    hour is a leak or a growing table, not a slow route."""
    whole, samples = await phase("soak", args.concurrency, args.duration)
    start = min((s.finished - s.latency_ms / 1000 for s in samples), default=0)
    results = []
    for index in range(int(args.duration // args.interval)):
        low, high = index * args.interval, (index + 1) * args.interval
        window = [s for s in samples if low <= s.finished - start < high]
        label = f"{int(low)}-{int(high)}s"
        results.append(
            summarise(label, window, args.concurrency, args.interval, whole.client_cpu)
        )
    return results


MODES = {"load": load, "stress": stress, "spike": spike, "soak": soak}


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

HEADER = (
    "| Phase | Users | Requests | Req/s | Errors | p50 ms | p90 ms | p99 ms | max ms |\n"
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|"
)


def _row(s: Stats) -> str:
    return (
        f"| {s.label} | {s.concurrency} | {s.requests} | {s.rps:.1f} | "
        f"{s.error_rate:.1%} | {s.p50_ms:.1f} | {s.p90_ms:.1f} | {s.p99_ms:.1f} | "
        f"{s.max_ms:.1f} |"
    )


def report(args: argparse.Namespace, results: list[Stats]) -> None:
    print(f"\n{args.scenario} against {args.url}, mode {args.mode}\n")
    print(HEADER)
    for stats in results:
        print(_row(stats))
    failures = Counter[str]()
    for stats in results:
        failures.update({k: v for k, v in stats.outcomes.items() if k[0] != "2"})
    if failures:
        print(f"\nNot 2xx: {dict(failures.most_common())}")
    if "429" in failures:
        print("429s are the rate limiter; see IDEN_RATE_LIMIT_ENABLED in the docs.")
    if any(s.client_cpu > 0.9 for s in results):
        print(
            "\nThe load generator was CPU-bound: the server may manage more than "
            "this. Run it from another machine, or several copies at once."
        )


# --------------------------------------------------------------------------


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load-test the IDEN provider or engine over HTTP."
    )
    parser.add_argument(
        "scenario",
        choices=[
            "discovery",
            "jwks",
            "sessions",
            "permissions",
            "token",
            "engine-verify",
        ],
    )
    parser.add_argument("--mode", choices=list(MODES), default="load")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument(
        "--token",
        default=os.environ.get("IDEN_TOKEN"),
        help="A person's access token (sessions, permissions) or the engine's.",
    )
    parser.add_argument("--client-id")
    parser.add_argument("--client-secret", default=os.environ.get("IDEN_CLIENT_SECRET"))
    parser.add_argument("--scope")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--concurrency", type=int, default=10, help="Virtual users.")
    parser.add_argument(
        "--duration", type=float, default=30, help="Seconds per phase (soak: total)."
    )
    parser.add_argument("--warmup", type=float, default=5)
    parser.add_argument("--start", type=int, default=1, help="stress: first users.")
    parser.add_argument("--max", type=int, default=512, help="stress: last users.")
    parser.add_argument("--max-errors", type=float, default=0.01)
    parser.add_argument("--max-p99", type=float, default=1000, help="stress: ms.")
    parser.add_argument("--spike", type=int, default=100, help="spike: users.")
    parser.add_argument("--interval", type=float, default=60, help="soak: seconds.")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--json", type=Path, help="Also write the results here.")
    return parser.parse_args()


async def main() -> None:
    args = arguments()
    ceiling = max(args.concurrency, args.spike, args.max)
    async with httpx.AsyncClient(
        base_url=args.url,
        timeout=args.timeout,
        limits=httpx.Limits(max_connections=ceiling, max_keepalive_connections=ceiling),
    ) as client:
        request = await scenario(args, client)
        await preflight(client, request)

        async def phase(label: str, concurrency: int, seconds: float):
            return await run_phase(client, request, label, concurrency, seconds)

        if args.warmup:
            await phase("warmup", min(args.concurrency, 10), args.warmup)
        if args.mode in ("stress", "spike"):
            print(HEADER)
        results = await MODES[args.mode](args, phase)

    report(args, results)
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "scenario": args.scenario,
                    "mode": args.mode,
                    "url": args.url,
                    "client": f"{platform.system()} {platform.machine()}, "
                    f"{os.cpu_count()} cores",
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "phases": [asdict(stats) for stats in results],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
