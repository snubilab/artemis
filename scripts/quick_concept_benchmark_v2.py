#!/usr/bin/env python3
"""
Quick Concept Mapping Benchmark v2

Fixes over the original quick benchmark:
1. Loads the criteria benchmark file instead of sampling ATLAS cohort JSONs.
2. Restricts the evaluation set to clinical domains only.
3. Uses real per-item timeout handling for Agent2 instead of blocking on
   ThreadPoolExecutor shutdown after a timeout.
4. Evaluates against the correct gold field and normalizes raw concept IDs
   offline via OMOP vocabulary CSVs so standard/non-standard vocabulary
   mismatches do not undercount recall.
5. Preserves gold IDs in the output payload for post-hoc inspection.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import logging
import math
import os
import random
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parent
DEFAULT_DATASET_PATH = APP_DIR / "data" / "benchmark_data" / "ohdsi_criteria_benchmark.json"
DEFAULT_CONCEPT_PATH = REPO_ROOT / "omop_vocab" / "files" / "CONCEPT.csv"
DEFAULT_RELATIONSHIP_PATH = REPO_ROOT / "omop_vocab" / "files" / "CONCEPT_RELATIONSHIP.csv"

CLINICAL_DOMAINS = ("Condition", "Drug", "Procedure", "Measurement")
MAPPER_CHOICES = {
    "rag": "RAG",
    "llm": "LLM Direct",
    "llm_direct": "LLM Direct",
    "llm_rag": "LLM RAG",
    "gpt54_rag": "GPT54 RAG",
    "agent2": "Agent2",
}
DEFAULT_MAPPERS = ("RAG", "LLM Direct", "Agent2")

DEFAULT_SAMPLE_SIZE = 50
DEFAULT_RANDOM_SEED = 42
DEFAULT_AGENT2_TIMEOUT_S = 120.0
DEFAULT_LLM_TIMEOUT_S = 45.0
RAW_ROW_KEYS = (
    "id",
    "study",
    "cohort",
    "criterion_name",
    "concept_set_name",
    "domain",
    "gold_raw_ids",
    "pred_raw_ids",
    "latency_ms",
    "error",
)

ALLOWED_RUNTIME_ENV = {
    "AZURE_API_KEY",
    "AZURE_ENDPOINT",
    "AZURE_API_VERSION",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "LLM_SEED",
    "DATABASE_URL",
    "OMOP_DB_HOST",
    "OMOP_DB_PORT",
    "OMOP_DB_NAME",
    "OMOP_DB_USER",
    "OMOP_DB_PASS",
    "CDM_SCHEMA",
    "PHOEBE_SCHEMA",
    "REDIS_URL",
    "CHROMA_URL",
    "CHROMA_PERSIST_DIRECTORY",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "EMBEDDING_MODEL",
    "MEDCPT_DEVICE",
    "DEBUG",
    "JSON_LOGS",
    "RAG_COLLECTION_NAME",
    "RAG_TOP_K",
    "AGENT2_CRITIC_MODEL_TIER",
}
SAFE_PASSTHROUGH_ENV = {
    "HOME",
    "PATH",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
    "TERM",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "NO_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "TOKENIZERS_PARALLELISM",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clinical concept mapping benchmark (v2)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH, help="Benchmark JSON file")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE_SIZE, help="Sample size")
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED, help="Random seed")
    parser.add_argument("--shard-id", type=int, default=0, help="0-indexed shard index (for parallel runs)")
    parser.add_argument("--num-shards", type=int, default=1, help="Total number of shards")
    parser.add_argument(
        "--mappers",
        default="rag,llm,agent2",
        help="Comma-separated subset of: rag,llm,llm_rag,gpt54_rag,agent2",
    )
    parser.add_argument(
        "--agent2-timeout",
        type=float,
        default=DEFAULT_AGENT2_TIMEOUT_S,
        help="Per-item Agent2 timeout in seconds (<=0 disables timeout)",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=DEFAULT_LLM_TIMEOUT_S,
        help="Per-item LLM Direct timeout in seconds",
    )
    parser.add_argument(
        "--save-path",
        type=Path,
        help="Optional output JSON path. If omitted, results are printed only.",
    )
    parser.add_argument(
        "--concept-path",
        type=Path,
        default=DEFAULT_CONCEPT_PATH,
        help="Path to OMOP CONCEPT.csv (default: omop_vocab/files/CONCEPT.csv)",
    )
    parser.add_argument(
        "--relationship-path",
        type=Path,
        default=DEFAULT_RELATIONSHIP_PATH,
        help="Path to OMOP CONCEPT_RELATIONSHIP.csv",
    )
    return parser.parse_args()


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def bootstrap_runtime_env() -> None:
    """
    Keep only env vars that ARTEMIS settings expect, then selectively load
    artemis/.env. This avoids pydantic-settings crashing on Broadsea's repo-wide
    .env keys while still giving the script the DB/LLM credentials it needs.
    """

    dotenv_values = parse_dotenv(APP_DIR / ".env")
    retained: dict[str, str] = {}
    for key, value in list(os.environ.items()):
        if key in ALLOWED_RUNTIME_ENV or key in SAFE_PASSTHROUGH_ENV or key.startswith(("CONDA", "_")):
            retained[key] = value

    os.environ.clear()
    os.environ.update(retained)

    for key in ALLOWED_RUNTIME_ENV:
        if key not in os.environ and key in dotenv_values:
            os.environ[key] = dotenv_values[key]

    os.environ.setdefault("CHROMA_PERSIST_DIRECTORY", str(APP_DIR / "chroma_db"))
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")
    os.environ.setdefault("POSTHOG_DISABLED", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ["DEBUG"] = "false"
    os.environ["JSON_LOGS"] = "false"

    # python-dotenv in src.settings.py searches upward from cwd; running from a
    # neutral directory avoids reloading Broadsea's top-level .env.
    try:
        os.chdir("/tmp")
    except OSError:
        pass


bootstrap_runtime_env()

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def quiet_third_party_logging() -> None:
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level < logging.WARNING:
        root.setLevel(logging.WARNING)

    for name in (
        "urllib3",
        "httpcore",
        "httpx",
        "openai",
        "chromadb",
        "huggingface_hub",
        "neo4j",
        "src",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def parse_mapper_names(raw: str) -> list[str]:
    names: list[str] = []
    for token in raw.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token not in MAPPER_CHOICES:
            raise ValueError(f"Unknown mapper '{token}'. Expected one of: {sorted(MAPPER_CHOICES)}")
        canonical = MAPPER_CHOICES[token]
        if canonical not in names:
            names.append(canonical)
    if not names:
        raise ValueError("At least one mapper must be selected")
    return names


def coerce_int_list(values: Iterable[Any]) -> list[int]:
    output: list[int] = []
    for value in values:
        try:
            output.append(int(value))
        except (TypeError, ValueError):
            continue
    return output


def load_benchmark_items(dataset_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    raw_items = payload["items"] if isinstance(payload, dict) else payload
    items: list[dict[str, Any]] = []

    for raw in raw_items:
        domain = raw.get("domain_hint") or raw.get("domain")
        if domain not in CLINICAL_DOMAINS:
            continue

        gold_raw_ids = coerce_int_list(raw.get("ground_truth_concept_ids", []))
        if not gold_raw_ids:
            continue

        items.append(
            {
                "id": raw["id"],
                "study": raw.get("study"),
                "cohort": raw.get("cohort"),
                "criterion_name": raw.get("criterion_name"),
                "concept_set_name": raw.get("concept_set_name"),
                "domain": domain,
                "gold_raw_ids": gold_raw_ids,
            }
        )

    return items


def stratified_sample(items: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    if n <= 0 or n >= len(items):
        return list(items)

    rng = random.Random(seed)
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_domain[item["domain"]].append(item)

    for bucket in by_domain.values():
        rng.shuffle(bucket)

    order = [domain for domain in CLINICAL_DOMAINS if domain in by_domain]
    selected: list[dict[str, Any]] = []
    iterators = {domain: iter(by_domain[domain]) for domain in order}

    while len(selected) < n:
        added = False
        for domain in order:
            if len(selected) >= n:
                break
            try:
                selected.append(next(iterators[domain]))
                added = True
            except StopIteration:
                continue
        if not added:
            break

    return selected


def call_with_timeout(func: Callable[[], list[int]], timeout_s: float) -> tuple[list[int], float, Optional[str]]:
    if timeout_s <= 0:
        start = time.perf_counter()
        try:
            pred_ids = coerce_int_list(func())
            error: Optional[str] = None
        except BaseException as exc:  # noqa: BLE001 - preserve concrete failure in output
            pred_ids = []
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - start) * 1000
        return pred_ids, latency_ms, error

    state: dict[str, Any] = {"pred_ids": [], "error": None}

    def target() -> None:
        try:
            state["pred_ids"] = coerce_int_list(func())
        except BaseException as exc:  # noqa: BLE001 - preserve concrete failure in output
            state["error"] = f"{type(exc).__name__}: {exc}"

    start = time.perf_counter()
    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout_s)
    latency_ms = (time.perf_counter() - start) * 1000

    if worker.is_alive():
        return [], latency_ms, f"timeout after {timeout_s:.1f}s"
    return state["pred_ids"], latency_ms, state["error"]


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end >= start:
        text = text[start : end + 1]
    return json.loads(text)


def make_row(item: dict[str, Any], pred_raw_ids: list[int], latency_ms: float, error: Optional[str]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "study": item["study"],
        "cohort": item["cohort"],
        "criterion_name": item["criterion_name"],
        "concept_set_name": item["concept_set_name"],
        "domain": item["domain"],
        "gold_raw_ids": list(item["gold_raw_ids"]),
        "pred_raw_ids": pred_raw_ids,
        "latency_ms": latency_ms,
        "error": error,
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def serialize_raw_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in RAW_ROW_KEYS}


def serialize_results_raw(mapper_names: list[str], results: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {
        slugify_mapper(mapper_name): [serialize_raw_row(row) for row in results.get(mapper_name, [])]
        for mapper_name in mapper_names
    }


def save_progress(
    save_path: Path,
    args: argparse.Namespace,
    sample: list[dict[str, Any]],
    mapper_names: list[str],
    results: dict[str, list[dict[str, Any]]],
) -> None:
    payload = {
        "schema_version": 2,
        "status": "in_progress",
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "dataset": str(args.dataset),
        "sample_size": len(sample),
        "sample_ids": [item["id"] for item in sample],
        "domains": list(CLINICAL_DOMAINS),
        "mappers": mapper_names,
        "progress": {slugify_mapper(name): len(results.get(name, [])) for name in mapper_names},
        "results_raw": serialize_results_raw(mapper_names, results),
    }
    write_json_atomic(save_path, payload)


def load_resume_rows(
    save_path: Path,
    args: argparse.Namespace,
    sample: list[dict[str, Any]],
    mapper_names: list[str],
) -> dict[str, list[dict[str, Any]]]:
    empty = {mapper_name: [] for mapper_name in mapper_names}
    if not save_path.exists():
        return empty

    try:
        payload = json.loads(save_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Resume disabled: failed to read save-path JSON ({exc})")
        return empty

    expected_sample_ids = [item["id"] for item in sample]
    saved_sample_ids = payload.get("sample_ids")
    if isinstance(saved_sample_ids, list) and saved_sample_ids != expected_sample_ids:
        print("Resume disabled: save-path sample_ids do not match this run.")
        return empty

    sample_by_id = {item["id"]: item for item in sample}
    key_lookup: dict[str, str] = {}
    for mapper_name in mapper_names:
        key_lookup[mapper_name] = mapper_name
        key_lookup[mapper_name.lower()] = mapper_name
        key_lookup[slugify_mapper(mapper_name)] = mapper_name

    loaded_rows: dict[str, dict[Any, dict[str, Any]]] = {mapper_name: {} for mapper_name in mapper_names}

    raw_results = payload.get("results_raw")
    if isinstance(raw_results, dict):
        for key, rows in raw_results.items():
            mapper_name = key_lookup.get(str(key), key_lookup.get(str(key).lower()))
            if mapper_name is None or not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item = sample_by_id.get(row.get("id"))
                if item is None:
                    continue
                loaded_rows[mapper_name][item["id"]] = make_row(
                    item,
                    coerce_int_list(row.get("pred_raw_ids", [])),
                    float(row.get("latency_ms") or 0.0),
                    str(row["error"]) if row.get("error") is not None else None,
                )

    if not any(loaded_rows.values()):
        per_item = payload.get("per_item")
        if isinstance(per_item, list):
            for entry in per_item:
                if not isinstance(entry, dict):
                    continue
                item = sample_by_id.get(entry.get("id"))
                if item is None:
                    continue
                for mapper_name in mapper_names:
                    mapper_payload = entry.get(slugify_mapper(mapper_name))
                    if not isinstance(mapper_payload, dict):
                        continue
                    loaded_rows[mapper_name][item["id"]] = make_row(
                        item,
                        coerce_int_list(mapper_payload.get("pred_raw_ids", [])),
                        float(mapper_payload.get("latency_ms") or 0.0),
                        str(mapper_payload["error"]) if mapper_payload.get("error") is not None else None,
                    )

    restored: dict[str, list[dict[str, Any]]] = {}
    for mapper_name in mapper_names:
        mapper_by_id = loaded_rows[mapper_name]
        restored[mapper_name] = [mapper_by_id[item["id"]] for item in sample if item["id"] in mapper_by_id]
        if restored[mapper_name]:
            print(f"Resume {mapper_name}: restored {len(restored[mapper_name])}/{len(sample)} rows from {save_path}")
    return restored


def run_rag_pass(
    sample: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    on_checkpoint: Optional[Callable[[], None]] = None,
) -> list[dict[str, Any]]:
    existing_by_id = {row["id"]: row for row in rows}
    rows[:] = [existing_by_id[item["id"]] for item in sample if item["id"] in existing_by_id]
    existing_by_id = {row["id"]: row for row in rows}
    if rows:
        print(f"\n[Phase 1/3] RAG resume: {len(rows)}/{len(sample)} already completed")
    if len(rows) >= len(sample):
        return rows

    print("\n[Phase 1/3] Loading RAG mapper...")
    from src.agents.conceptset.rag_search import get_rag_search

    rag = get_rag_search()

    for index, item in enumerate(sample, 1):
        if item["id"] in existing_by_id:
            continue
        print(f"  [RAG {index}/{len(sample)}] {item['concept_set_name'][:60]}")

        top_k = max(20, len(item["gold_raw_ids"]))
        start = time.perf_counter()
        error: Optional[str] = None
        pred_ids: list[int] = []
        try:
            candidates = rag.search(
                item["concept_set_name"],
                n_results=top_k,
                domain_filter=item["domain"],
            )
            pred_ids = [candidate.concept_id for candidate in candidates]
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - start) * 1000
        row = make_row(item, pred_ids, latency_ms, error)
        rows.append(row)
        existing_by_id[item["id"]] = row
        if on_checkpoint:
            on_checkpoint()

    del rag
    gc.collect()
    return rows


def run_llm_pass(
    sample: list[dict[str, Any]],
    timeout_s: float,
    rows: list[dict[str, Any]],
    on_checkpoint: Optional[Callable[[], None]] = None,
) -> list[dict[str, Any]]:
    existing_by_id = {row["id"]: row for row in rows}
    rows[:] = [existing_by_id[item["id"]] for item in sample if item["id"] in existing_by_id]
    existing_by_id = {row["id"]: row for row in rows}
    if rows:
        print(f"\n[Phase 2/3] LLM Direct resume: {len(rows)}/{len(sample)} already completed")
    if len(rows) >= len(sample):
        return rows

    print("\n[Phase 2/3] Loading LLM Direct mapper...")
    from langchain_core.messages import HumanMessage
    from src.utils.llm import get_llm

    def build_prompt(item: dict[str, Any]) -> str:
        top_k = max(20, len(item["gold_raw_ids"]))
        return (
            "You are an OMOP vocabulary expert.\n"
            f"Map the following concept set name to standard OMOP concept IDs.\n"
            f"Clinical domain: {item['domain']}\n"
            f"Concept set name: \"{item['concept_set_name']}\"\n"
            f"Return ONLY valid JSON in this exact shape: "
            f'{{"concept_ids": [int, ...]}}.\n'
            f"Return up to {top_k} standard concept IDs. No prose."
        )

    for index, item in enumerate(sample, 1):
        if item["id"] in existing_by_id:
            continue
        print(f"  [LLM {index}/{len(sample)}] {item['concept_set_name'][:60]}")

        def invoke() -> list[int]:
            llm = get_llm()
            response = llm.invoke([HumanMessage(content=build_prompt(item))])
            parsed = parse_json_object(str(response.content))
            return coerce_int_list(parsed.get("concept_ids", []))

        pred_ids, latency_ms, error = call_with_timeout(invoke, timeout_s)
        row = make_row(item, pred_ids, latency_ms, error)
        rows.append(row)
        existing_by_id[item["id"]] = row
        if on_checkpoint:
            on_checkpoint()

    gc.collect()
    return rows


def run_llm_rag_pass(
    sample: list[dict[str, Any]],
    timeout_s: float,
    rows: list[dict[str, Any]],
    llm_model_name: Optional[str] = None,
    on_checkpoint: Optional[Callable[[], None]] = None,
) -> list[dict[str, Any]]:
    existing_by_id = {row["id"]: row for row in rows}
    rows[:] = [existing_by_id[item["id"]] for item in sample if item["id"] in existing_by_id]
    existing_by_id = {row["id"]: row for row in rows}
    if rows:
        print(f"\n[Phase 2.5/3] LLM RAG resume: {len(rows)}/{len(sample)} already completed")
    if len(rows) >= len(sample):
        return rows

    print("\n[Phase 2.5/3] Loading LLM RAG mapper...")
    from src.agents.conceptset.rag_search import get_rag_search

    rag = get_rag_search()
    reranker = None
    if llm_model_name is None:
        from src.agents.agent2.reranker import ConceptReranker

        reranker = ConceptReranker()

    for index, item in enumerate(sample, 1):
        if item["id"] in existing_by_id:
            continue
        print(f"  [LLM RAG {index}/{len(sample)}] {item['concept_set_name'][:60]}")

        top_k = max(20, len(item["gold_raw_ids"]))
        start = time.perf_counter()
        error: Optional[str] = None
        pred_ids: list[int] = []

        try:
            candidates = rag.search(
                item["concept_set_name"],
                n_results=top_k,
                domain_filter=item["domain"],
            )
        except Exception as exc:  # noqa: BLE001
            candidates = []
            error = f"{type(exc).__name__}: {exc}"

        search_latency_ms = (time.perf_counter() - start) * 1000
        latency_ms = search_latency_ms

        if candidates and error is None:
            selected_ids, rerank_latency_ms, rerank_error = call_with_timeout(
                lambda item=item, candidates=candidates, reranker=reranker, llm_model_name=llm_model_name: (
                    _rerank_candidates_with_llm(
                        item["concept_set_name"],
                        candidates,
                        min(3, len(candidates)),
                        llm_model_name,
                    )
                    if llm_model_name
                    else [
                        candidate.concept_id
                        for candidate in reranker.rerank_topn(
                            item["concept_set_name"], candidates, top_n=min(3, len(candidates))
                        )
                    ]
                ),
                timeout_s,
            )
            pred_ids = selected_ids
            latency_ms += rerank_latency_ms
            error = rerank_error

        row = make_row(item, pred_ids, latency_ms, error)
        rows.append(row)
        existing_by_id[item["id"]] = row
        if on_checkpoint:
            on_checkpoint()

    gc.collect()
    return rows


def _rerank_candidates_with_llm(
    query_text: str,
    candidates: list[Any],
    top_n: int,
    model_name: str,
) -> list[int]:
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from src.utils.llm import get_llm

    candidates_text = ""
    for candidate in candidates:
        candidates_text += (
            f"- ID: {candidate.concept_id} | Name: {candidate.concept_name} "
            f"| Class: {candidate.concept_class_id} | Vocab: {candidate.vocabulary_id}\n"
        )

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an expert medical terminologist.\n"
         "Select up to {top_n} OMOP Concept IDs from the candidates that "
         "best match the user's clinical intent. Order by relevance.\n"
         "Return ONLY a JSON object: {{\"selected_ids\": [id1, id2, ...]}}\n"
         "If none fit, return {{\"selected_ids\": []}}"),
        ("user", "Clinical term: {user_query}\n\nCandidates:\n{candidates_text}"),
    ])
    chain = prompt | get_llm(model_name=model_name, temperature=0.0) | JsonOutputParser()
    result = chain.invoke({
        "user_query": query_text,
        "candidates_text": candidates_text,
        "top_n": top_n,
    })
    return coerce_int_list(result.get("selected_ids", []))[:top_n]


def run_agent2_pass(
    sample: list[dict[str, Any]],
    timeout_s: float,
    rows: list[dict[str, Any]],
    on_checkpoint: Optional[Callable[[], None]] = None,
) -> list[dict[str, Any]]:
    existing_by_id = {row["id"]: row for row in rows}
    rows[:] = [existing_by_id[item["id"]] for item in sample if item["id"] in existing_by_id]
    existing_by_id = {row["id"]: row for row in rows}
    if rows:
        print(f"\n[Phase 3/3] Agent2 resume: {len(rows)}/{len(sample)} already completed")
    if len(rows) >= len(sample):
        return rows

    print("\n[Phase 3/3] Loading Agent2 mapper...")
    from src.agents.agent2.workflow import get_agent2

    agent2 = get_agent2()

    for index, item in enumerate(sample, 1):
        if item["id"] in existing_by_id:
            continue
        print(f"  [Agent2 {index}/{len(sample)}] {item['concept_set_name'][:60]}")

        pred_ids, latency_ms, error = call_with_timeout(
            lambda item=item: agent2.process(item["concept_set_name"], domain_hint=item["domain"]),
            timeout_s,
        )
        row = make_row(item, pred_ids, latency_ms, error)
        rows.append(row)
        existing_by_id[item["id"]] = row
        if on_checkpoint:
            on_checkpoint()

    del agent2
    gc.collect()
    return rows


class OfflineVocabularyResolver:
    def __init__(self, concept_path: Path, relationship_path: Path) -> None:
        self.concept_path = concept_path
        self.relationship_path = relationship_path
        self.concept_meta: dict[int, dict[str, Any]] = {}
        self.maps_to: dict[int, set[int]] = defaultdict(set)

    def _load_concepts(self, needed_ids: set[int]) -> None:
        if not needed_ids:
            return

        with self.concept_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                try:
                    concept_id = int(row["concept_id"])
                except (TypeError, ValueError):
                    continue
                if concept_id not in needed_ids:
                    continue
                self.concept_meta[concept_id] = {
                    "standard_concept": row.get("standard_concept") or "",
                    "invalid_reason": row.get("invalid_reason") or "",
                    "domain_id": row.get("domain_id") or "",
                    "vocabulary_id": row.get("vocabulary_id") or "",
                }
                if len(self.concept_meta) >= len(needed_ids):
                    # This condition is approximate, but good enough to avoid
                    # iterating to EOF when all needed IDs are already seen.
                    if all(concept_id in self.concept_meta for concept_id in needed_ids):
                        break

    def _is_valid_standard(self, concept_id: int) -> bool:
        meta = self.concept_meta.get(concept_id)
        return bool(meta and meta["standard_concept"] == "S" and not meta["invalid_reason"])

    def load(self, concept_ids: set[int]) -> None:
        needed = set(concept_ids) - set(self.concept_meta)
        self._load_concepts(needed)

        nonstandard_sources = {
            concept_id
            for concept_id in concept_ids
            if concept_id not in self.maps_to and not self._is_valid_standard(concept_id)
        }
        if not nonstandard_sources:
            return

        mapped_targets: set[int] = set()
        with self.relationship_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                if row.get("relationship_id") != "Maps to":
                    continue
                if row.get("invalid_reason"):
                    continue
                try:
                    src_id = int(row["concept_id_1"])
                    dst_id = int(row["concept_id_2"])
                except (TypeError, ValueError):
                    continue
                if src_id in nonstandard_sources:
                    self.maps_to[src_id].add(dst_id)
                    mapped_targets.add(dst_id)

        self._load_concepts(mapped_targets - set(self.concept_meta))

        for src_id, dst_ids in list(self.maps_to.items()):
            self.maps_to[src_id] = {dst_id for dst_id in dst_ids if self._is_valid_standard(dst_id)}

    def normalize_ordered(self, raw_ids: Iterable[int]) -> tuple[list[int], list[int]]:
        ordered: list[int] = []
        unresolved: list[int] = []
        seen: set[int] = set()

        for raw_id in coerce_int_list(raw_ids):
            if self._is_valid_standard(raw_id):
                targets = [raw_id]
            else:
                mapped = sorted(self.maps_to.get(raw_id, set()))
                if mapped:
                    targets = mapped
                else:
                    targets = [raw_id]
                    unresolved.append(raw_id)

            for target in targets:
                if target not in seen:
                    ordered.append(target)
                    seen.add(target)

        return ordered, unresolved


def compute_metrics(pred_ids: list[int], gold_ids: list[int]) -> dict[str, float]:
    pred_set = set(pred_ids)
    gold_set = set(gold_ids)

    overlap = pred_set & gold_set
    precision = len(overlap) / len(pred_set) if pred_set else 0.0
    recall = len(overlap) / len(gold_set) if gold_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "hit_at_1": float(bool(set(pred_ids[:1]) & gold_set)),
        "hit_at_5": float(bool(set(pred_ids[:5]) & gold_set)),
        "hit_at_10": float(bool(set(pred_ids[:10]) & gold_set)),
        "hallucinated": float(len([pred_id for pred_id in pred_ids if pred_id not in gold_set])),
    }


def enrich_rows(rows: list[dict[str, Any]], resolver: OfflineVocabularyResolver) -> list[dict[str, Any]]:
    for row in rows:
        gold_ids, gold_unresolved = resolver.normalize_ordered(row["gold_raw_ids"])
        pred_ids, pred_unresolved = resolver.normalize_ordered(row["pred_raw_ids"])
        row["gold_normalized_ids"] = gold_ids
        row["gold_unresolved_ids"] = gold_unresolved
        row["pred_normalized_ids"] = pred_ids
        row["pred_unresolved_ids"] = pred_unresolved
        row.update(compute_metrics(pred_ids, gold_ids))
    return rows


def avg(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(row.get(key, 0.0)) for row in rows) / len(rows)


def print_results(
    mapper_names: list[str],
    results: dict[str, list[dict[str, Any]]],
    sample: list[dict[str, Any]],
    dataset_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    domain_counts = Counter(item["domain"] for item in sample)

    print("\n" + "=" * 88)
    print(f"=== CONCEPT MAPPING BENCHMARK V2 ({len(sample)} items, clinical-only) ===")
    print("=" * 88)
    print(f"Dataset: {dataset_path}")
    print(f"Domains: {dict(domain_counts)}")

    header = (
        f"{'Mapper':<14} {'Precision':>9}  {'Recall':>8}  {'F1':>7}"
        f"  {'Hit@1':>6}  {'Hit@5':>6}  {'Hit@10':>7}  {'Latency(ms)':>11}  {'Errors':>6}"
    )
    print(header)
    print("-" * len(header))

    aggregate: dict[str, dict[str, float]] = {}
    for mapper_name in mapper_names:
        rows = results[mapper_name]
        error_count = sum(1 for row in rows if row.get("error"))
        summary = {
            "precision": avg(rows, "precision"),
            "recall": avg(rows, "recall"),
            "f1": avg(rows, "f1"),
            "hit_at_1": avg(rows, "hit_at_1"),
            "hit_at_5": avg(rows, "hit_at_5"),
            "hit_at_10": avg(rows, "hit_at_10"),
            "latency_ms": avg(rows, "latency_ms"),
            "error_count": float(error_count),
        }
        aggregate[mapper_name] = summary
        print(
            f"{mapper_name:<14} {summary['precision']:>9.3f}  {summary['recall']:>8.3f}  {summary['f1']:>7.3f}"
            f"  {summary['hit_at_1']:>6.3f}  {summary['hit_at_5']:>6.3f}  {summary['hit_at_10']:>7.3f}"
            f"  {summary['latency_ms']:>11.0f}  {int(summary['error_count']):>6d}"
        )

    by_domain: dict[str, dict[str, dict[str, float]]] = {}
    print("\n=== By Domain ===")
    for domain in CLINICAL_DOMAINS:
        print(f"\n[{domain}]")
        print(f"{'Mapper':<14} {'Recall':>8}  {'F1':>7}  {'Errors':>6}")
        print("-" * 42)
        by_domain[domain] = {}
        for mapper_name in mapper_names:
            domain_rows = [row for row in results[mapper_name] if row["domain"] == domain]
            metrics = {
                "precision": avg(domain_rows, "precision"),
                "recall": avg(domain_rows, "recall"),
                "f1": avg(domain_rows, "f1"),
                "error_count": float(sum(1 for row in domain_rows if row.get("error"))),
                "count": float(len(domain_rows)),
            }
            by_domain[domain][mapper_name] = metrics
            print(
                f"{mapper_name:<14} {metrics['recall']:>8.3f}  {metrics['f1']:>7.3f}  {int(metrics['error_count']):>6d}"
            )

    return aggregate, by_domain


def slugify_mapper(name: str) -> str:
    return name.lower().replace(" ", "_")


def combine_per_item(
    sample: list[dict[str, Any]],
    mapper_names: list[str],
    results: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_mapper_id = {
        mapper_name: {row["id"]: row for row in rows}
        for mapper_name, rows in results.items()
    }

    combined: list[dict[str, Any]] = []
    for item in sample:
        entry = {
            "id": item["id"],
            "study": item["study"],
            "cohort": item["cohort"],
            "criterion_name": item["criterion_name"],
            "concept_set_name": item["concept_set_name"],
            "domain": item["domain"],
            "gold_raw_ids": item["gold_raw_ids"],
        }
        if mapper_names:
            first_row = by_mapper_id[mapper_names[0]][item["id"]]
            entry["gold_normalized_ids"] = first_row["gold_normalized_ids"]
            entry["gold_unresolved_ids"] = first_row["gold_unresolved_ids"]

        for mapper_name in mapper_names:
            row = by_mapper_id[mapper_name][item["id"]]
            entry[slugify_mapper(mapper_name)] = {
                "pred_raw_ids": row["pred_raw_ids"],
                "pred_normalized_ids": row["pred_normalized_ids"],
                "pred_unresolved_ids": row["pred_unresolved_ids"],
                "precision": row["precision"],
                "recall": row["recall"],
                "f1": row["f1"],
                "hit_at_1": row["hit_at_1"],
                "hit_at_5": row["hit_at_5"],
                "hit_at_10": row["hit_at_10"],
                "latency_ms": row["latency_ms"],
                "error": row["error"],
            }
        combined.append(entry)

    return combined


def print_sample_preview(sample: list[dict[str, Any]], mapper_names: list[str], results: dict[str, list[dict[str, Any]]], limit: int = 5) -> None:
    print("\n=== Sample Preview ===")
    for item in sample[:limit]:
        print(f"- [{item['domain']}] {item['concept_set_name']} (gold={len(item['gold_raw_ids'])})")
        for mapper_name in mapper_names:
            row = next(row for row in results[mapper_name] if row["id"] == item["id"])
            error_note = f" | error={row['error']}" if row.get("error") else ""
            print(
                f"  {mapper_name:<12} recall={row['recall']:.3f} "
                f"pred={len(row['pred_normalized_ids'])} "
                f"lat={row['latency_ms']:.0f}ms{error_note}"
            )


def collect_all_ids(results: dict[str, list[dict[str, Any]]]) -> set[int]:
    concept_ids: set[int] = set()
    for rows in results.values():
        for row in rows:
            concept_ids.update(row["gold_raw_ids"])
            concept_ids.update(row["pred_raw_ids"])
    return concept_ids


def save_results(
    save_path: Path,
    args: argparse.Namespace,
    sample: list[dict[str, Any]],
    mapper_names: list[str],
    aggregate: dict[str, Any],
    by_domain: dict[str, Any],
    results: dict[str, list[dict[str, Any]]],
) -> None:
    payload = {
        "schema_version": 2,
        "status": "completed",
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "dataset": str(args.dataset),
        "sample_size": len(sample),
        "sample_ids": [item["id"] for item in sample],
        "domains": list(CLINICAL_DOMAINS),
        "mappers": mapper_names,
        "progress": {slugify_mapper(name): len(results.get(name, [])) for name in mapper_names},
        "results_raw": serialize_results_raw(mapper_names, results),
        "aggregate": aggregate,
        "by_domain": by_domain,
        "per_item": combine_per_item(sample, mapper_names, results),
    }
    write_json_atomic(save_path, payload)
    print(f"\nSaved results to: {save_path}")


def main() -> int:
    args = parse_args()
    mapper_names = parse_mapper_names(args.mappers)
    quiet_third_party_logging()

    print("=" * 68)
    print("LOADING BENCHMARK DATA (criteria benchmark, clinical-only)...")
    print("=" * 68)
    items = load_benchmark_items(args.dataset)
    print(f"Loaded {len(items)} clinical benchmark items from {args.dataset}")

    sample = stratified_sample(items, args.sample, args.seed)
    if args.num_shards > 1:
        shard_size = math.ceil(len(sample) / args.num_shards)
        start = args.shard_id * shard_size
        sample = sample[start: start + shard_size]
    print(f"Sampled {len(sample)} items with seed={args.seed}" +
          (f" (shard {args.shard_id}/{args.num_shards})" if args.num_shards > 1 else ""))

    results: dict[str, list[dict[str, Any]]] = {mapper_name: [] for mapper_name in mapper_names}
    if args.save_path:
        resumed = load_resume_rows(args.save_path, args, sample, mapper_names)
        for mapper_name in mapper_names:
            results[mapper_name] = resumed.get(mapper_name, [])

    def checkpoint() -> None:
        if args.save_path:
            save_progress(args.save_path, args, sample, mapper_names, results)

    if "RAG" in mapper_names:
        run_rag_pass(sample, results["RAG"], checkpoint)
    if "LLM Direct" in mapper_names:
        run_llm_pass(sample, args.llm_timeout, results["LLM Direct"], checkpoint)
    if "LLM RAG" in mapper_names:
        run_llm_rag_pass(sample, args.llm_timeout, results["LLM RAG"], checkpoint)
    if "GPT54 RAG" in mapper_names:
        run_llm_rag_pass(sample, args.llm_timeout, results["GPT54 RAG"], "gpt-5.4", checkpoint)
    if "Agent2" in mapper_names:
        run_agent2_pass(sample, args.agent2_timeout, results["Agent2"], checkpoint)

    resolver = OfflineVocabularyResolver(
        concept_path=args.concept_path,
        relationship_path=args.relationship_path,
    )
    resolver.load(collect_all_ids(results))
    for mapper_name in mapper_names:
        enrich_rows(results[mapper_name], resolver)

    aggregate, by_domain = print_results(mapper_names, results, sample, args.dataset)
    print_sample_preview(sample, mapper_names, results)

    if args.save_path:
        save_results(args.save_path, args, sample, mapper_names, aggregate, by_domain, results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
