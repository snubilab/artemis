#!/usr/bin/env python3
"""Run the TTE pipeline end-to-end against one LLM, for one experiment arm.

Produces `<root>/<arm>/<model_slug>/` holding, per study and per repeat, the
generated Circe, the per-criterion mapping metadata, every raw LLM completion,
and timings. Nothing is shared between (arm, model) pairs and nothing is
appended to a common file, so re-running one model cannot disturb another's
results. `score_run.py` reads these directories; the layout is a contract
documented in the output root's README.md.

The pipeline checkout is a parameter, never a constant: arm 2 (ADR-031/032)
points --checkout at its own worktree and needs no change here.

Each (study, repeat) runs in a fresh subprocess. That is not tidiness: the
store, the criterion cache and the LLM cost tracker are all module-level
singletons, so a second study in the same interpreter would inherit the first
one's state, and a crash halfway would take the whole model's run with it.

Usage
  run_model.py --arm baseline --checkout <path> --model vllm/snuh/hari-q3-8b
  run_model.py --arm baseline --checkout <path> --model gpt-4o --studies 5 --repeat 3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("/home/bilab/work/projects/Broadsea/artemis/output/model_eval")
DEFAULT_STUDIES = (2, 3, 5, 8, 9, 10)

# Above this share of failed LLM calls a study is not a measurement of the model.
# The pipeline catches LLM errors and degrades to its heuristic fallbacks, so it
# reports `completed` even when every single call failed — an observed run against
# a server that died mid-study produced 174 "completed" calls, all of them
# APIConnectionError. Status therefore has to be judged on the recorded error rate,
# never on what the pipeline says about itself.
MAX_LLM_ERROR_RATE = 0.25

# Study id -> trial label, as stored in tmp/tte/studies.json. Used only for
# labelling; score_run.py owns the gold-file mapping.
STUDY_LABELS = {
    2: "PLATO", 3: "ARISTOTLE", 5: "LEADER",
    8: "EMPA-REG OUTCOME", 9: "CARMELINA", 10: "CAROLINA",
}

# Files whose text is the prompt surface of the pipeline. Hashed into the run
# metadata so a future reader can tell whether two runs shared a prompt version.
PROMPT_SOURCES = (
    "src/agents/agent1/parser.py",
    "src/agents/planner/decomposer.py",
    "src/agents/conceptset/nlu_router.py",
    "src/agents/agent2/reranker.py",
    "src/agents/conceptset/clinical_reranker.py",
    "src/agents/agent2/critic.py",
    "src/services/tte_service.py",
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def slugify(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# LLM recorder
# --------------------------------------------------------------------------

def install_recorder(sink: Path) -> list[dict[str, Any]]:
    """Record every chat completion the pipeline makes, to `sink` (JSONL).

    Hooks the two concrete chat classes rather than `get_llm`, because nine of
    the ten call sites do `from src.utils.llm import get_llm` at module import
    time — patching the factory would miss whichever module imported first.
    Hooking the classes is also the only way to observe the model a call
    *actually* used, which is how `critic.py`'s hardcoded gpt-4o-mini and the
    comparator's hardcoded model become visible instead of silently billing.
    """
    from langchain_openai.chat_models.base import BaseChatOpenAI

    from src.utils.llm import AzureAIFoundryChatModel

    records: list[dict[str, Any]] = []
    handle = sink.open("a", encoding="utf-8")

    def caller_stage() -> str:
        """Nearest src/ frame below this hook — attributes a call to a stage."""
        frame = sys._getframe(2)
        while frame is not None:
            name = frame.f_globals.get("__name__", "")
            if name.startswith("src.") and not name.startswith("src.utils.llm"):
                return f"{name}:{frame.f_code.co_name}"
            frame = frame.f_back
        return "unknown"

    def wrap(cls: type, model_attr: str) -> None:
        original = cls._generate

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
            stage = caller_stage()
            started = time.perf_counter()
            error: str | None = None
            result = None
            try:
                result = original(self, messages, stop, run_manager, **kwargs)
            except Exception as exc:  # recorded, then re-raised unchanged
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                record = _describe(self, model_attr, messages, result, error, stage)
                record["latency_s"] = round(time.perf_counter() - started, 3)
                records.append(record)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
            return result

        cls._generate = _generate  # type: ignore[method-assign]

    wrap(BaseChatOpenAI, "model_name")
    wrap(AzureAIFoundryChatModel, "model")
    return records


def _describe(
    model_obj: Any,
    model_attr: str,
    messages: list[Any],
    result: Any,
    error: str | None,
    stage: str,
) -> dict[str, Any]:
    prompt_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    record: dict[str, Any] = {
        "stage": stage,
        "model_used": getattr(model_obj, model_attr, None),
        "base_url": str(getattr(model_obj, "openai_api_base", "") or getattr(model_obj, "client", "") or "")[:80],
        "prompt_chars": prompt_chars,
        "requested_json": bool(
            (getattr(model_obj, "model_kwargs", None) or {}).get("response_format")
            or getattr(model_obj, "response_format", None)
        ),
        "error": error,
    }
    if result is None:
        record.update({"output": None, "json_ok": False, "json_recovered": False})
        return record

    generation = result.generations[0]
    text = generation.message.content if isinstance(generation.message.content, str) else ""
    meta = getattr(generation.message, "response_metadata", {}) or {}
    usage = getattr(generation.message, "usage_metadata", None) or {}
    strict, recovered = _json_status(text)
    record.update({
        "output": text,
        "output_chars": len(text),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "finish_reason": meta.get("finish_reason"),
        # A model that runs to the context ceiling never emitted a closing brace;
        # this is the failure-to-terminate signal, distinct from a parse failure.
        "truncated": meta.get("finish_reason") == "length",
        "json_ok": strict,
        "json_recovered": recovered,
    })
    return record


def _json_status(text: str) -> tuple[bool, bool]:
    """(parses as JSON on the first try, parses after fence/prefix recovery)."""
    stripped = text.strip()
    try:
        json.loads(stripped)
        return True, True
    except (json.JSONDecodeError, ValueError):
        pass
    fenced = _FENCE.search(stripped)
    candidate = fenced.group(1) if fenced else stripped[stripped.find("{"): stripped.rfind("}") + 1]
    try:
        json.loads(candidate)
        return False, True
    except (json.JSONDecodeError, ValueError):
        return False, False


# --------------------------------------------------------------------------
# Worker: one (study, repeat)
# --------------------------------------------------------------------------

def run_one(study_id: int, out_dir: Path, snapshot: Path) -> dict[str, Any]:
    """Process eligibility, apply it, build the arm Circe. Writes into out_dir."""
    from src.services.tte_service import TTEService
    from src.services.tte_store import TTEStore
    from src.utils.llm import get_cost_tracker

    store_path = Path(os.environ["TTE_STORE_PATH"])
    store_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot, store_path)

    service = TTEService(TTEStore(str(store_path)))
    get_cost_tracker().reset()
    result: dict[str, Any] = {
        "studyId": study_id,
        "label": STUDY_LABELS.get(study_id, str(study_id)),
        "startedAt": now_iso(),
    }

    t0 = time.perf_counter()
    processed = service.process_eligibility(study_id)
    result["processEligibility"] = {
        "status": processed.status,
        "seconds": round(time.perf_counter() - t0, 2),
        "meta": processed.meta,
    }
    if processed.status != "completed":
        result["status"] = "failed"
        result["error"] = (processed.meta or {}).get("failureMessage")
        return result

    artifact = service.store.get_artifact(processed.artifactId)
    payload = artifact.get("payload") or {}
    proposed = (payload.get("proposedChanges") or {}).get("eligibility") or {}
    (out_dir / "circe_target.json").write_text(
        json.dumps(proposed.get("structuredExpression") or {}, ensure_ascii=False, indent=1))
    (out_dir / "criterion_mapping.json").write_text(json.dumps({
        "criterionMappingMetadata": payload.get("criterionMappingMetadata") or {},
        "criterionConceptSetRefs": payload.get("criterionConceptSetRefs") or {},
        "inclusionCriteria": proposed.get("inclusionCriteria") or [],
        "exclusionCriteria": proposed.get("exclusionCriteria") or [],
    }, ensure_ascii=False, indent=1))

    study = service.store.get_study(study_id)
    service.apply_artifact(processed.artifactId, ["eligibility"], int(study.get("version") or 1))

    t1 = time.perf_counter()
    preview = service.preview_seeded_cohorts(study_id)
    # preview_seeded_cohorts returns parsed summaries; the raw per-arm Circe is
    # only reachable through the cache it fills for the register step.
    cached = service._preview_cache.get((study_id, preview["previewHash"]))
    arms = (cached or {}).get("circe_by_arm") or {}
    for arm_key, circe in arms.items():
        (out_dir / f"circe_{arm_key}.json").write_text(
            json.dumps(circe, ensure_ascii=False, indent=1))
    result["previewSeededCohorts"] = {
        "seconds": round(time.perf_counter() - t1, 2),
        "arms": sorted(arms),
        "comparisonMode": study.get("comparisonMode"),
        "treatmentArms": [a.get("name") for a in (study.get("treatmentArms") or [])],
    }
    result["status"] = "completed"
    result["llmCostTracker"] = get_cost_tracker().summary()
    result["finishedAt"] = now_iso()
    return result


def worker_main(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = install_recorder(out_dir / "stage_calls.jsonl")
    result: dict[str, Any] = {}
    try:
        result = run_one(args.study, out_dir, Path(args.snapshot))
    except Exception as exc:  # a failed study must not abort the model's run
        result = {
            "studyId": args.study,
            "label": STUDY_LABELS.get(args.study, str(args.study)),
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "finishedAt": now_iso(),
        }
    result["llmCalls"] = _call_summary(records)
    calls, errors = result["llmCalls"]["calls"], result["llmCalls"]["errors"]
    if calls and errors / calls > MAX_LLM_ERROR_RATE:
        result["status"] = "invalid_llm_errors"
        result["error"] = (f"{errors}/{calls} LLM calls failed — the served model was "
                           f"unreachable or unhealthy; this is not a measurement of it")
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    if not args.keep_store:
        # The store copy is a 24 MB duplicate of the shared snapshot; everything
        # this run added to it is already extracted into the JSON artifacts above.
        for leftover in (out_dir / "studies.json", out_dir / "studies.json.lock"):
            leftover.unlink(missing_ok=True)
    print(f"  study {args.study}: {result.get('status')} "
          f"({result['llmCalls']['calls']} calls, "
          f"{result['llmCalls']['wall_seconds']}s in-LLM)")
    return 0 if result.get("status") == "completed" else 1


def _call_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    models: dict[str, int] = {}
    for record in records:
        models[str(record.get("model_used"))] = models.get(str(record.get("model_used")), 0) + 1
    return {
        "calls": total,
        "errors": sum(1 for r in records if r.get("error")),
        "json_ok": sum(1 for r in records if r.get("json_ok")),
        "json_recovered": sum(1 for r in records if r.get("json_recovered")),
        "truncated": sum(1 for r in records if r.get("truncated")),
        "input_tokens": sum(r.get("input_tokens") or 0 for r in records),
        "output_tokens": sum(r.get("output_tokens") or 0 for r in records),
        "wall_seconds": round(sum(r.get("latency_s") or 0.0 for r in records), 1),
        "models_used": models,
    }


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

def prompt_fingerprint(checkout: Path) -> str:
    digest = hashlib.sha256()
    for rel in PROMPT_SOURCES:
        path = checkout / rel
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
    return digest.hexdigest()[:16]


def probe_server(base_url: str, model: str) -> dict[str, Any]:
    """Ask the served endpoint what it is. Provenance, not a health gate."""
    import httpx

    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", timeout=5.0)
        response.raise_for_status()
        served = response.json().get("data", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "reachable": True,
        "served": [{"id": m.get("id"), "max_model_len": m.get("max_model_len")} for m in served],
        "matches_requested": any(m.get("id") == model.removeprefix("vllm/") for m in served),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", required=True, help="experiment arm, e.g. baseline / with-adr031-032")
    parser.add_argument("--checkout", required=True, help="pipeline checkout to benchmark")
    parser.add_argument("--model", required=True, help="LLM_MODEL value, e.g. vllm/snuh/hari-q3-8b")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="output root")
    parser.add_argument("--studies", default=",".join(map(str, DEFAULT_STUDIES)))
    parser.add_argument("--repeat", type=int, default=1, help="independent samples per study")
    parser.add_argument("--vllm-base-url", default=None, help="overrides VLLM_BASE_URL")
    parser.add_argument("--gpu-memory-utilization", type=float, default=None,
                        help="recorded as provenance; the server does not report it")
    parser.add_argument("--max-model-len", type=int, default=None, help="recorded as provenance")
    parser.add_argument("--label", default=None, help="output dir name (default: slug of --model)")
    parser.add_argument("--keep-store", action="store_true",
                        help="keep each repeat's 24MB store copy (default: discard, it is redundant)")
    parser.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--study", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--out-dir", help=argparse.SUPPRESS)
    parser.add_argument("--snapshot", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.single:
        return worker_main(args)

    checkout = Path(args.checkout).resolve()
    snapshot = checkout / "tmp" / "tte" / "studies.json"
    if not snapshot.exists():
        parser.error(f"input snapshot not found: {snapshot}")

    model_dir = Path(args.root) / args.arm / (args.label or slugify(args.model))
    model_dir.mkdir(parents=True, exist_ok=True)
    studies = [int(s) for s in args.studies.split(",") if s.strip()]

    base_url = args.vllm_base_url or os.environ.get("VLLM_BASE_URL", "")
    env = dict(os.environ)
    env["LLM_MODEL"] = args.model
    if args.vllm_base_url:
        env["VLLM_BASE_URL"] = args.vllm_base_url
    # critic.py:377 otherwise resolves Condition/Drug/Measurement to a literal
    # "gpt-4o-mini", which has no vllm/ prefix and so bills OpenRouter mid-run —
    # silently measuring GPT on part of a pipeline labelled as another model.
    env["AGENT2_CRITIC_MODEL_TIER"] = "gpt-4o"
    # A cache hit skips the LLM, so repeats would measure the cache and a warm
    # directory would measure the previous model.
    env["CRITERION_CACHE_ENABLED"] = "false"
    env["PYTHONPATH"] = str(checkout)

    # Refuse to start against a server that is not serving the requested model:
    # every call would fail, the pipeline would degrade silently, and the run would
    # still write a full set of directories that look complete.
    probe = probe_server(base_url, args.model) if base_url else None
    if probe is not None and not probe.get("matches_requested"):
        parser.error(f"{base_url} is not serving {args.model}: {json.dumps(probe)}")

    commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    meta = {
        "arm": args.arm,
        "model": args.model,
        "model_slug": args.label or slugify(args.model),
        "checkout": str(checkout),
        "git_commit": commit,
        "prompt_fingerprint": prompt_fingerprint(checkout),
        "vllm_base_url": base_url,
        "port": (base_url.split(":")[-1].split("/")[0] if base_url else None),
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "max_model_len": args.max_model_len,
        "studies": studies,
        "repeat": args.repeat,
        "single_sample": args.repeat == 1,
        "critic_tier_forced": "gpt-4o",
        "criterion_cache_enabled": False,
        "input_snapshot": str(snapshot),
        "startedAt": now_iso(),
        "server_probe": probe,
    }
    (model_dir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"[{args.arm}/{meta['model_slug']}] {args.model} -> {model_dir}")

    started = time.perf_counter()
    outcomes: list[str] = []
    aborted = False
    for study_id in studies:
        # Clear the whole study, not just the rep dirs about to be written: a
        # re-run with fewer repeats would otherwise leave stale reps behind and
        # the scorer would fold them into this run's variance.
        study_dir = model_dir / "studies" / str(study_id)
        if study_dir.exists():
            shutil.rmtree(study_dir)
        for repeat in range(args.repeat):
            out_dir = study_dir / f"rep{repeat}"
            out_dir.mkdir(parents=True)
            child = dict(env)
            child["TTE_STORE_PATH"] = str(out_dir / "studies.json")
            proc = subprocess.run(
                [sys.executable, __file__, "--single",
                 "--arm", args.arm, "--checkout", str(checkout), "--model", args.model,
                 "--study", str(study_id), "--out-dir", str(out_dir), "--snapshot", str(snapshot)]
                + (["--keep-store"] if args.keep_store else []),
                cwd=str(checkout), env=child,
            )
            verdict = json.loads((out_dir / "result.json").read_text()).get("status")
            outcomes.append(f"{study_id}/rep{repeat}="
                            f"{'ok' if verdict == 'completed' else verdict or 'FAIL'}")
            # A dead server fails every remaining call in seconds. Continuing would
            # spend the rest of the sweep writing directories that only look complete.
            if verdict == "invalid_llm_errors":
                aborted = True
                break
        if aborted:
            print(f"[abort] {studies[studies.index(study_id):]} not run: served model unhealthy")
            break

    meta["aborted"] = aborted
    meta["finishedAt"] = now_iso()
    meta["wall_seconds"] = round(time.perf_counter() - started, 1)
    meta["outcomes"] = outcomes
    (model_dir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"[done] {meta['wall_seconds']}s  {' '.join(outcomes)}")
    return 0 if all("=ok" in o for o in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
