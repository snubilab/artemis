#!/usr/bin/env python3
"""Run the OR-group restatement arms over the labelled case-audit table.

The question every arm answers is the same one
:mod:`src.agents.agent1.criteria_dedup_judge` documents: given the [OR-GROUP]
items already in a trial's criteria list, does the candidate criterion restate an
alternative one of them already offers?

Arms
----
``lexical``
    ``criteria_dedup.restates_or_group_alternative``, frozen, no LLM. The
    incumbent this work proposes to replace, so no result is interpretable
    without it.
``llm_local``
    ``criteria_dedup_judge`` against a local vLLM server. ``resolve_model()``
    MUST return a ``vllm/``-prefixed name here; without the prefix
    ``src.utils.llm.get_llm`` falls through to OpenRouter and the arm is
    mislabelled -- the exact provenance failure recorded in
    ``.claude/rules/broadsea/infra.md``. This script refuses to run the arm when
    the prefix is missing.
``llm_openrouter``
    ``criteria_dedup_judge`` against the configured remote model (PAID).
``always_distinct``
    Not called: the floor an arm that answers "distinct" for every row scores.
    Computed from the labels alone.

Why each arm runs in its own subprocess
---------------------------------------
``src.settings.Settings`` reads ``os.getenv`` in its class body, so ``LLM_MODEL``
is frozen at import time. Setting it in-process after the import would leave
``resolve_model()`` reporting one model while the traffic went to another --
which is the failure this harness exists to avoid, not one to reproduce. Each arm
therefore gets a clean interpreter with its environment already set.

Scoring
-------
Over-deletion (predicting ``restatement`` on a ``distinct`` row: a criterion gold
AND-s separately is deleted and the cohort silently WIDENS) and under-deletion
(predicting ``distinct`` on a ``restatement`` row: the alternative is re-added as
a top-level rule and the cohort collapses) are reported separately, never as one
F1. Error rows are counted, never dropped: an arm that quietly skipped
unparseable rows would report an inflated score on a smaller n.

Usage
-----
    .venv/bin/python scripts/run_orgroup_judge_arms.py
    .venv/bin/python scripts/run_orgroup_judge_arms.py --arm lexical   # one arm
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
EVALSET = REPO_ROOT / "data" / "benchmark_data" / "orgroup_decision_evalset.json"
OUT_DIR = REPO_ROOT / "output" / "orgroup_judge"

LOCAL_VLLM_MODEL = "vllm/google/gemma-4-E4B-it"
LOCAL_VLLM_BASE_URL = "http://127.0.0.1:8000/v1"
# The CONFIGURED value verbatim (src.settings default), not a rewritten id: this
# arm is meant to be whatever production would actually reach today. Probed on
# 2026-08-09: OpenRouter accepts the bare id and reports response_metadata
# model_name = "openai/gpt-4o", so the bare name is not a silent 404 -- it is a
# real paid OpenAI call, which is exactly the trap infra.md records.
OPENROUTER_MODEL = "gpt-4o"

# Every arm that issues calls. always_distinct is computed, not run.
LLM_ARMS = ("llm_local", "llm_openrouter")
ALL_ARMS = ("lexical",) + LLM_ARMS


def arm_env(arm: str) -> dict[str, str]:
    """:param arm: one of :data:`ALL_ARMS`. :returns: the env overlay that arm needs.

    The cache is disabled for every arm. A cache hit returns ``llm_called=False``
    and a latency that measures a dict lookup, so a mixed run would report a
    parse rate and a latency that describe no single thing.
    """
    env = {"ARTEMIS_ORGROUP_JUDGE_CACHE": "0"}
    if arm == "lexical":
        env["ARTEMIS_ORGROUP_JUDGE"] = "lexical"
    elif arm == "llm_local":
        env["ARTEMIS_ORGROUP_JUDGE"] = "llm"
        env["LLM_MODEL"] = LOCAL_VLLM_MODEL
        env["VLLM_BASE_URL"] = LOCAL_VLLM_BASE_URL
    elif arm == "llm_openrouter":
        env["ARTEMIS_ORGROUP_JUDGE"] = "llm"
        env["LLM_MODEL"] = OPENROUTER_MODEL
    else:
        raise ValueError(f"unknown arm {arm!r}")
    return env


def load_rows() -> tuple[list[dict], dict]:
    """:returns: (rows, the full evalset document)."""
    doc = json.loads(EVALSET.read_text(encoding="utf-8"))
    return doc["rows"], doc


def run_one_arm(arm: str) -> dict:
    """Score one arm over every row, writing per-item JSONL.

    :param arm: one of :data:`ALL_ARMS`.
    :returns: the arm's summary dict.
    """
    from src.agents.agent1.criteria_dedup_judge import ERROR, RESTATEMENT, judge_or_group_restatement
    from src.utils.llm import resolve_model

    resolved = resolve_model()
    if arm == "llm_local" and not resolved.startswith("vllm/"):
        raise SystemExit(
            f"REFUSING to run {arm}: resolve_model() returned {resolved!r} with no 'vllm/' prefix. "
            "get_llm() would route this to OpenRouter and the arm would be mislabelled."
        )
    if arm == "llm_openrouter" and resolved.startswith("vllm/"):
        raise SystemExit(f"REFUSING to run {arm}: resolve_model() returned a local model {resolved!r}.")

    rows, _doc = load_rows()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{arm}.jsonl"

    records: list[dict] = []
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            start = time.perf_counter()
            result = judge_or_group_restatement(row["candidate"], row["or_group_items"])
            latency = time.perf_counter() - start
            record = {
                "id": row["id"],
                "trial": row["trial"],
                "candidate": row["candidate"],
                "alternatives": row["alternatives"],
                "label": row["label"],
                "verdict": result.verdict,
                "boolean": result.is_restatement,
                "reason": result.reason,
                "matched_alternatives": list(result.matched_alternatives),
                "source": result.source,
                "llm_called": result.llm_called,
                "warnings": list(result.warnings),
                "resolved_model": result.model,
                "latency_s": round(latency, 4),
                "error": result.error,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            records.append(record)
            flag = "ERR" if record["verdict"] == ERROR else ("YES" if record["boolean"] else "no ")
            mark = " " if record["verdict"] == ERROR else (
                "." if bool(record["boolean"]) == (record["label"] == "restatement") else "X"
            )
            print(f"  {mark} [{arm}] {record['id']:<28} {flag}  {record['candidate'][:60]}", flush=True)

    return summarise(arm, records, resolved, str(out_path))


def summarise(arm: str, records: list[dict], resolved_model: str, out_path: str) -> dict:
    """Count the two error directions separately, and never drop error rows.

    :param arm: arm name. :param records: per-row result records.
    :param resolved_model: ``resolve_model()`` read inside the arm's process.
    :param out_path: the JSONL this arm wrote.
    :returns: the arm's summary dict.
    """
    from src.agents.agent1.criteria_dedup_judge import ERROR

    n = len(records)
    errors = [r for r in records if r["verdict"] == ERROR]
    parsed = [r for r in records if r["verdict"] != ERROR]

    tp = sum(1 for r in parsed if r["boolean"] and r["label"] == "restatement")
    fp = sum(1 for r in parsed if r["boolean"] and r["label"] == "distinct")
    fn = sum(1 for r in parsed if not r["boolean"] and r["label"] == "restatement")
    tn = sum(1 for r in parsed if not r["boolean"] and r["label"] == "distinct")

    n_pos = sum(1 for r in records if r["label"] == "restatement")
    n_neg = sum(1 for r in records if r["label"] == "distinct")

    latencies = sorted(r["latency_s"] for r in records)
    return {
        "arm": arm,
        "resolved_model": resolved_model,
        "jsonl": out_path,
        "n_rows": n,
        "n_errors": len(errors),
        "parse_rate": round(len(parsed) / n, 4) if n else None,
        "n_llm_called": sum(1 for r in records if r["llm_called"]),
        "sources": {s: sum(1 for r in records if r["source"] == s) for s in sorted({r["source"] for r in records})},
        "confusion_on_parsed": {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "n_parsed": len(parsed)},
        # Two directions, deliberately not combined into one number.
        "over_deletion": {
            "false_positives": fp,
            "of_distinct_rows": n_neg,
            "meaning": "predicted restatement on a row gold AND-s separately -- deleting it WIDENS the cohort",
        },
        "under_deletion": {
            "false_negatives": fn,
            "of_restatement_rows": n_pos,
            "meaning": "predicted distinct on a real restatement -- the alternative is re-added and Circe ANDs it",
        },
        "accuracy_strict": round((tp + tn) / n, 4) if n else None,
        "accuracy_on_parsed": round((tp + tn) / len(parsed), 4) if parsed else None,
        "verdict_counts": {v: sum(1 for r in records if r["verdict"] == v) for v in sorted({r["verdict"] for r in records})},
        "latency_s": {
            "total": round(sum(latencies), 2),
            "median": round(latencies[len(latencies) // 2], 3) if latencies else None,
            "max": round(latencies[-1], 3) if latencies else None,
        },
        "error_rows": [{"id": r["id"], "error": r["error"]} for r in errors],
    }


def always_distinct_floor() -> dict:
    """The floor an arm that answers 'distinct' for every row scores. Not called."""
    rows, _doc = load_rows()
    n = len(rows)
    n_pos = sum(1 for r in rows if r["label"] == "restatement")
    n_neg = n - n_pos
    return {
        "arm": "always_distinct",
        "resolved_model": None,
        "computed_not_called": True,
        "n_rows": n,
        "n_errors": 0,
        "parse_rate": 1.0,
        "confusion_on_parsed": {"tp": 0, "fp": 0, "fn": n_pos, "tn": n_neg, "n_parsed": n},
        "over_deletion": {"false_positives": 0, "of_distinct_rows": n_neg},
        "under_deletion": {"false_negatives": n_pos, "of_restatement_rows": n_pos},
        "accuracy_strict": round(n_neg / n, 4),
        "accuracy_on_parsed": round(n_neg / n, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=ALL_ARMS, help="run exactly one arm in this process")
    parser.add_argument("--arms", default=",".join(ALL_ARMS), help="comma-separated arms for the driver")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.arm:
        summary = run_one_arm(args.arm)
        (OUT_DIR / f"{args.arm}.summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    # --- driver: one clean interpreter per arm ---
    started = datetime.now(timezone.utc)
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    oracle_sha = hashlib.sha256(EVALSET.read_bytes()).hexdigest()

    manifest = {
        "command": f"{sys.executable} {' '.join(sys.argv)}",
        "cwd": str(REPO_ROOT),
        "git_head": head,
        "git_dirty": bool(
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "status", "--porcelain"], capture_output=True, text=True
            ).stdout.strip()
        ),
        "started_utc": started.isoformat(),
        "python": sys.version.split()[0],
        "oracle": {"path": str(EVALSET), "sha256": oracle_sha},
        "cache": "disabled (ARTEMIS_ORGROUP_JUDGE_CACHE=0) so every LLM row is a real call",
        "arms": {},
        "arms_not_run": {},
    }

    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        env = os.environ.copy()
        overlay = arm_env(arm)
        env.update(overlay)
        print(f"\n=== arm {arm} :: {overlay} ===", flush=True)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--arm", arm], cwd=str(REPO_ROOT), env=env
        )
        summary_path = OUT_DIR / f"{arm}.summary.json"
        if proc.returncode != 0 or not summary_path.exists():
            manifest["arms_not_run"][arm] = f"exit={proc.returncode}; see stderr above"
            continue
        manifest["arms"][arm] = json.loads(summary_path.read_text(encoding="utf-8"))
        manifest["arms"][arm]["env_overlay"] = overlay

    manifest["arms"]["always_distinct"] = always_distinct_floor()
    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nwrote", OUT_DIR / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
