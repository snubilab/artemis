#!/usr/bin/env python3
"""Is the 48-worker mapping cap in tte_service still load-bearing?

    python scripts/measure_mapping_worker_cap.py --study 8 --workers 48,0

``--workers 0`` means uncapped: the pool gets a ceiling above the task count, so
concurrency equals the number of mappable criteria, which is what removing the cap
would do. Any other value forces that ceiling.

Why this script exists. The cap was added when "Ingredient rollup skipped" warnings
were read as Postgres connect timeouts under mapping concurrency (39 at 16 workers,
209 uncapped). 7fbeab2 showed the error text said something else --
``QueuePool limit of size 20 overflow 40 reached, connection timed out, timeout
60.00`` -- i.e. the pool was being drained by a connection the rollup's safety net
checked out and never returned. Concurrency set how fast the pool drained, not
whether it drained. Whether the cap is still needed was never re-measured.

What it measures: rollup skips, wall clock, and peak backend count on the Postgres
server, per worker ceiling, on one study.

Read-only with respect to the live store: the store is copied first, the same way
benchmark_value_constraint_arms.py does it, because the default store is the one the
live service serves from.

Note on the criterion cache. A warm cache does NOT make this measure nothing.
``_exact_ingredient_mapping`` runs *before* the cache lookup and opens its own
psycopg2 connection, and expression building rolls up from there, so the DB path
under test executes on a cache hit. Running with the cache warm is the cheaper and
safer arm: it issues no LLM calls, so it neither waits on a shared vLLM server nor
inflates a wall clock someone else is publishing. CRITERION_CACHE_ENABLED=false adds
the LLM leg back and is the faithful reproduction of the original 209-skip run.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_MARKER = "Ingredient rollup skipped"


class SkipCounter(logging.Handler):
    """Counts the one warning the cap was introduced to suppress."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.skips = 0
        self.pool_errors = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            return
        if SKIP_MARKER in message:
            self.skips += 1
            if "QueuePool" in message:
                self.pool_errors += 1


class BackendSampler(threading.Thread):
    """Peak backend count on the server, sampled from one dedicated connection.

    The SQLAlchemy pool's own ``checkedout`` is not the binding number: the refiner
    and the exact-ingredient lookup open raw psycopg2 connections outside the pool,
    so the server's max_connections is the ceiling that actually applies.
    """

    def __init__(self, dsn: str, interval: float = 0.25) -> None:
        super().__init__(daemon=True)
        self.dsn, self.interval = dsn, interval
        self.peak = 0
        self.limit: int | None = None
        self._done = threading.Event()

    def run(self) -> None:
        try:
            import psycopg2

            conn = psycopg2.connect(self.dsn)
        except Exception as exc:  # a failed sampler must not fail the measurement
            logging.warning("[cap] backend sampler unavailable: %s", exc)
            return
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW max_connections")
                self.limit = int(cur.fetchone()[0])
                while not self._done.is_set():
                    cur.execute("SELECT count(*) FROM pg_stat_activity")
                    self.peak = max(self.peak, int(cur.fetchone()[0]))
                    self._done.wait(self.interval)
        finally:
            conn.close()

    def stop(self) -> None:
        self._done.set()
        self.join(timeout=5)


def isolate_store() -> Path:
    default = Path(os.environ.get("TTE_STORE_PATH") or ROOT / "tmp" / "tte" / "studies.json")
    bench = default.with_name("cap_measure.json")
    if not bench.exists():
        shutil.copyfile(default, bench)
    os.environ["TTE_STORE_PATH"] = str(bench)
    return bench


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=int, default=8, help="study id (8 = EMPA-REG)")
    parser.add_argument(
        "--workers",
        default="-1,0",
        help="ceilings to compare; -1 = as shipped (min(48, mappable)), 0 = uncapped",
    )
    parser.add_argument("--uncapped-ceiling", type=int, default=512)
    args = parser.parse_args()

    isolate_store()
    from src.services.tte_service import TTEService
    from src.services.tte_store import TTEStore
    from src.settings import settings
    from src.utils.llm import resolve_model

    counter = SkipCounter()
    logging.getLogger().addHandler(counter)
    logging.getLogger().setLevel(logging.INFO)

    service = TTEService(TTEStore(os.environ["TTE_STORE_PATH"]))
    eligibility = (service.store.get_study(args.study) or {}).get("eligibility") or {}
    if not eligibility:
        print(f"study {args.study} has no eligibility in the store")
        return 1

    print(json.dumps({
        "study": args.study,
        "resolved_model": resolve_model(None),
        "criterion_cache_enabled": os.environ.get("CRITERION_CACHE_ENABLED", "true"),
        "pool": "size=20 overflow=40 pool_timeout=60 connect_timeout=3",
    }, indent=2), flush=True)

    shipped = os.environ.get("TTE_MAPPING_MAX_WORKERS")
    rows = []
    for token in [int(p) for p in args.workers.split(",") if p.strip()]:
        # -1 leaves the shipped cap alone; 0 raises the ceiling above the task count,
        # so concurrency becomes the number of mappable criteria.
        if token < 0:
            os.environ.pop("TTE_MAPPING_MAX_WORKERS", None)
        else:
            os.environ["TTE_MAPPING_MAX_WORKERS"] = str(
                args.uncapped_ceiling if token == 0 else token
            )

        before = counter.skips
        sampler = BackendSampler(settings.DATABASE_URL)
        sampler.start()
        started = time.monotonic()
        # A fresh copy per arm: _build_seeded_target_circe pops keys off its input.
        service._build_seeded_target_circe(json.loads(json.dumps(eligibility)))
        wall = time.monotonic() - started
        sampler.stop()

        rows.append({
            "label": "as shipped" if token < 0 else ("uncapped" if token == 0 else f"cap {token}"),
            "ceiling": os.environ.get("TTE_MAPPING_MAX_WORKERS", "48 (default)"),
            "skips": counter.skips - before,
            "pool_errors": counter.pool_errors,
            "wall_s": round(wall, 1),
            "peak_backends": sampler.peak,
            "max_connections": sampler.limit,
        })
        print(json.dumps(rows[-1]), flush=True)

    if shipped is None:
        os.environ.pop("TTE_MAPPING_MAX_WORKERS", None)
    else:
        os.environ["TTE_MAPPING_MAX_WORKERS"] = shipped

    print(f"\n{'arm':<12}{'ceiling':>14}{'skips':>7}{'wall s':>9}{'peak be':>9}{'max_conn':>10}")
    for row in rows:
        print(f"{row['label']:<12}{row['ceiling']:>14}{row['skips']:>7}"
              f"{row['wall_s']:>9}{row['peak_backends']:>9}{row['max_connections'] or '?':>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
