#!/usr/bin/env python3
"""Score one (arm, model) run directory against the gold Circe cohorts.

Reads only what `run_model.py` wrote plus `data/gold/`, so it needs no GPU and
no served model and can be re-run at any time. Writes `scores.json` into the
run directory; the synthesis phase reads that file.

Metrics, in the priority order of the brief:

  1. Concept mapping accuracy. Two views, because gold and generated name their
     concept sets in different styles and name alignment is itself a judgement
     call:
       1a  relation profile  - every generated concept id classified against the
           whole gold concept id set for that trial via OMOP concept_ancestor:
           exact / descendant / ancestor / sibling / unrelated. Needs no name
           alignment, so it cannot be gamed or broken by naming style. This is
           the metric that would have caught "BI 10773" -> CHF-6366 metabolite.
       1b  per-term  - gold concept-set name aligned to generated concept-set
           name by normalised token Jaccard. The alignment score is recorded on
           every pair so a reader can audit the pairing rather than trust it.
  2. End-to-end Circe agreement: concept-set and rule counts, concept-id
     Jaccard, entry criterion domain, surviving value constraints.
  3. Per-stage behaviour, from the recorded calls. Gold constrains the mapping
     stage only; extraction/decomposition/routing are reported descriptively
     and are labelled as having no ground truth rather than given a fake score.
  4. Model-agnostic mechanics: schema compliance, latency, tokens, truncation,
     and which model each call actually reached.

Usage
  score_run.py <run_dir> [--gold <dir>] [--align-threshold 0.34]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

# Study id -> gold treatment cohort, relative to data/gold/. Every study in the
# store uses comparisonMode=target_minus_treatment, so the pipeline emits one
# arm (the treatment arm) and only the treatment gold is a legitimate pair.
# The "(indication)" gold variants are minimal drug+indication cohorts with no
# inclusion rules — they are not the eligibility answer key and are not used.
GOLD_BY_STUDY = {
    2: "PLATO/_TROY v1.1_ Ticagrelor (PLATO).json",
    3: "ARISTOTLE/_TROY v1.1_ Apixaban (ARISTOTLE).json",
    5: "LEADER/_TROY v1.1_ Liraglutide (LEADER).json",
    8: "EMPA-REG OUTCOME/[TROY v1.1] Empagliflozin (EMPA-REG OUTCOME).json",
    9: "CARMELINA/[TROY v1.1] Linagliptin (CARMELINA).json",
    10: "CAROLINA/[TROY v1.1] Linagliptin (CAROLINA).json",
}

# gpt-4o is the incumbent being replaced, so its run must carry a price.
# Anything served locally is free at the margin and priced at zero.
PRICE_PER_TOKEN = {
    "gpt-4o": (2.5e-6, 1.0e-5),
    "gpt-4o-mini": (1.65e-7, 6.6e-7),
}

# Gold names carry curation bookkeeping that generated names never have.
_GOLD_NOISE = re.compile(r"(\[troy[^\]]*\]|copy of:|_cond\b|_proc\b|_lab\b|\(.*?\))", re.IGNORECASE)
_NON_WORD = re.compile(r"[^a-z0-9]+")
_STOPWORDS = frozenset({"of", "the", "or", "and", "in", "with", "history", "a", "to", "for", "by"})


def normalize_name(name: str) -> frozenset[str]:
    cleaned = _GOLD_NOISE.sub(" ", name or "")
    tokens = {t for t in _NON_WORD.sub(" ", cleaned.lower()).split() if t and t not in _STOPWORDS}
    return frozenset(tokens)


def jaccard(a: Iterable[Any], b: Iterable[Any]) -> float:
    sa, sb = set(a), set(b)
    union = sa | sb
    return round(len(sa & sb) / len(union), 4) if union else 0.0


# --------------------------------------------------------------------------
# Circe readers
# --------------------------------------------------------------------------

def concept_sets(cohort: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for cset in cohort.get("ConceptSets") or []:
        ids = {
            int(item["concept"]["CONCEPT_ID"])
            for item in (cset.get("expression") or {}).get("items") or []
            if isinstance(item.get("concept"), dict) and item["concept"].get("CONCEPT_ID") is not None
        }
        out.append({"id": cset.get("id"), "name": cset.get("name") or "", "concept_ids": ids})
    return out


def all_concept_ids(cohort: dict[str, Any]) -> set[int]:
    return {cid for cset in concept_sets(cohort) for cid in cset["concept_ids"]}


def entry_domain(cohort: dict[str, Any]) -> str | None:
    criteria = (cohort.get("PrimaryCriteria") or {}).get("CriteriaList") or [{}]
    return next((k for k in (criteria[0] or {})), None)


def value_constraints(node: Any, parent: str = "") -> Counter:
    """Count Circe range objects by the field they constrain.

    A Circe numeric/date range is any object carrying an "Op" key; the parent
    key names what is being constrained (Age, ValueAsNumber, OccurrenceCount...).
    This is what "did value constraints survive" means concretely.
    """
    found: Counter = Counter()
    if isinstance(node, dict):
        if "Op" in node:
            found[parent or "?"] += 1
        for key, value in node.items():
            found += value_constraints(value, key)
    elif isinstance(node, list):
        for item in node:
            found += value_constraints(item, parent)
    return found


# --------------------------------------------------------------------------
# Metric 1: concept mapping accuracy
# --------------------------------------------------------------------------

class Hierarchy:
    """OMOP concept_ancestor relations restricted to the ids in play.

    Two queries per id-set, not one per pair: concept_ancestor has 75M rows and
    a per-pair query would dominate the scoring run.
    """

    def __init__(self, ids: set[int]) -> None:
        from sqlalchemy import text

        from src.settings import settings
        from src.utils.db import SessionLocal

        schema = settings.CDM_SCHEMA
        id_list = sorted(ids)
        self.pairs: set[tuple[int, int]] = set()
        self.parents: dict[int, set[int]] = {}
        self.names: dict[int, str] = {}
        if not id_list:
            return
        with SessionLocal() as session:
            rows = session.execute(text(
                f"SELECT ancestor_concept_id, descendant_concept_id FROM {schema}.concept_ancestor "
                "WHERE ancestor_concept_id = ANY(:ids) AND descendant_concept_id = ANY(:ids)"
            ), {"ids": id_list}).fetchall()
            self.pairs = {(int(a), int(d)) for a, d in rows}
            rows = session.execute(text(
                f"SELECT descendant_concept_id, ancestor_concept_id FROM {schema}.concept_ancestor "
                "WHERE descendant_concept_id = ANY(:ids) AND min_levels_of_separation = 1"
            ), {"ids": id_list}).fetchall()
            for child, parent in rows:
                self.parents.setdefault(int(child), set()).add(int(parent))
            rows = session.execute(text(
                f"SELECT concept_id, concept_name FROM {schema}.concept WHERE concept_id = ANY(:ids)"
            ), {"ids": id_list}).fetchall()
            self.names = {int(cid): name for cid, name in rows}

    def relation(self, generated: int, gold_ids: set[int]) -> str:
        if generated in gold_ids:
            return "exact"
        if any((gold, generated) in self.pairs for gold in gold_ids):
            return "descendant"
        if any((generated, gold) in self.pairs for gold in gold_ids):
            return "ancestor"
        mine = self.parents.get(generated, set())
        if mine and any(mine & self.parents.get(gold, set()) for gold in gold_ids):
            return "sibling"
        return "unrelated"


def relation_profile(generated_ids: set[int], gold_ids: set[int], hierarchy: Hierarchy) -> dict[str, Any]:
    """Metric 1a: alignment-free classification of every generated concept."""
    labels = {cid: hierarchy.relation(cid, gold_ids) for cid in generated_ids}
    counts = Counter(labels.values())
    total = len(generated_ids) or 1
    covered = {cid for cid in gold_ids if cid in generated_ids
               or any((cid, gen) in hierarchy.pairs for gen in generated_ids)}
    return {
        "generated_concepts": len(generated_ids),
        "gold_concepts": len(gold_ids),
        "counts": dict(counts),
        "exact_rate": round(counts["exact"] / total, 4),
        # exact + hierarchy neighbours: defensibly the same clinical idea
        "in_hierarchy_rate": round(
            (counts["exact"] + counts["descendant"] + counts["ancestor"]) / total, 4),
        "unrelated_rate": round(counts["unrelated"] / total, 4),
        "gold_recall": round(len(covered) / len(gold_ids), 4) if gold_ids else None,
        # Named, because "unrelated" is where a wrong-compound defect hides and a
        # bare count cannot distinguish a wrong mapping from a defensible extra.
        "unrelated_sample": sorted(
            ({"id": cid, "name": hierarchy.names.get(cid, "")}
             for cid, label in labels.items() if label == "unrelated"),
            key=lambda c: c["name"],
        )[:40],
    }


def align_terms(
    gold_sets: list[dict[str, Any]],
    gen_sets: list[dict[str, Any]],
    threshold: float,
    hierarchy: Hierarchy,
) -> dict[str, Any]:
    """Metric 1b: greedy name alignment, then per-term concept recall."""
    scored = sorted(
        (
            (jaccard(normalize_name(g["name"]), normalize_name(p["name"])), gi, pi)
            for gi, g in enumerate(gold_sets)
            for pi, p in enumerate(gen_sets)
        ),
        reverse=True,
    )
    used_gold: set[int] = set()
    used_gen: set[int] = set()
    pairs: list[dict[str, Any]] = []
    for score, gi, pi in scored:
        if score < threshold or gi in used_gold or pi in used_gen:
            continue
        used_gold.add(gi)
        used_gen.add(pi)
        gold, gen = gold_sets[gi], gen_sets[pi]
        labels = Counter(hierarchy.relation(cid, gold["concept_ids"]) for cid in gen["concept_ids"])
        pairs.append({
            "gold_name": gold["name"],
            "gen_name": gen["name"],
            "align_score": score,
            "gold_ids": len(gold["concept_ids"]),
            "gen_ids": len(gen["concept_ids"]),
            "id_jaccard": jaccard(gold["concept_ids"], gen["concept_ids"]),
            "relations": dict(labels),
            "any_exact": labels["exact"] > 0,
        })
    return {
        "align_threshold": threshold,
        "aligned_terms": len(pairs),
        "gold_terms": len(gold_sets),
        "gen_terms": len(gen_sets),
        "gold_unmatched": [g["name"] for i, g in enumerate(gold_sets) if i not in used_gold],
        "gen_unmatched": [p["name"] for i, p in enumerate(gen_sets) if i not in used_gen],
        "term_hit_rate": round(sum(p["any_exact"] for p in pairs) / len(pairs), 4) if pairs else None,
        "mean_id_jaccard": round(statistics.mean(p["id_jaccard"] for p in pairs), 4) if pairs else None,
        "pairs": pairs,
    }


# --------------------------------------------------------------------------
# Metrics 3 and 4: recorded calls
# --------------------------------------------------------------------------

def call_metrics(calls: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(calls) or 1
    latencies = [c["latency_s"] for c in calls if c.get("latency_s") is not None]
    input_tokens = sum(c.get("input_tokens") or 0 for c in calls)
    output_tokens = sum(c.get("output_tokens") or 0 for c in calls)
    by_stage: dict[str, dict[str, Any]] = {}
    for stage, group in _group(calls, "stage").items():
        n = len(group)
        by_stage[stage] = {
            "calls": n,
            "json_ok_rate": round(sum(bool(c.get("json_ok")) for c in group) / n, 4),
            "errors": sum(1 for c in group if c.get("error")),
            "truncated": sum(1 for c in group if c.get("truncated")),
            "median_latency_s": round(statistics.median(
                [c["latency_s"] for c in group if c.get("latency_s") is not None] or [0.0]), 3),
            "output_tokens": sum(c.get("output_tokens") or 0 for c in group),
        }
    models = Counter(str(c.get("model_used")) for c in calls)
    cost = 0.0
    for model, count in models.items():
        rate = PRICE_PER_TOKEN.get(model)
        if rate:
            share = count / total
            cost += input_tokens * share * rate[0] + output_tokens * share * rate[1]
    return {
        "calls": len(calls),
        "errors": sum(1 for c in calls if c.get("error")),
        # Schema compliance: strict = parsed on the first try with no repair.
        "strict_json_rate": round(sum(bool(c.get("json_ok")) for c in calls) / total, 4),
        "recoverable_json_rate": round(sum(bool(c.get("json_recovered")) for c in calls) / total, 4),
        "truncated_calls": sum(1 for c in calls if c.get("truncated")),
        "median_latency_s": round(statistics.median(latencies or [0.0]), 3),
        "p90_latency_s": round(sorted(latencies)[int(len(latencies) * 0.9)], 3) if latencies else None,
        "total_llm_seconds": round(sum(latencies), 1),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        # A model id here other than the one under test means a call escaped
        # LLM_MODEL and the run is measuring a different model on that stage.
        "models_used": dict(models),
        "estimated_cost_usd": round(cost, 4),
        "by_stage": by_stage,
        "ground_truth_note": "Gold constrains the mapping stage only; per-stage "
                             "figures for extraction/decomposition/routing are "
                             "descriptive, not scored against a key.",
    }


def _group(items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        out.setdefault(str(item.get(key)), []).append(item)
    return out


# --------------------------------------------------------------------------

def score_repeat(rep_dir: Path, gold: dict[str, Any], threshold: float) -> dict[str, Any]:
    result = json.loads((rep_dir / "result.json").read_text())
    out: dict[str, Any] = {
        "rep": rep_dir.name,
        "status": result.get("status"),
        "error": result.get("error"),
        "seconds": (result.get("processEligibility") or {}).get("seconds"),
    }
    calls_file = rep_dir / "stage_calls.jsonl"
    calls = [json.loads(line) for line in calls_file.read_text().splitlines() if line.strip()] \
        if calls_file.exists() else []
    out["mechanics"] = call_metrics(calls)
    if out["status"] != "completed":
        return out

    # The arm Circe is what a user actually gets; the target Circe is the
    # eligibility-only intermediate. Gold is an arm cohort, so arm_0 is the pair.
    arm_file = rep_dir / "circe_arm_0.json"
    generated = json.loads((arm_file if arm_file.exists() else rep_dir / "circe_target.json").read_text())
    out["compared_file"] = (arm_file if arm_file.exists() else rep_dir / "circe_target.json").name

    gold_sets, gen_sets = concept_sets(gold), concept_sets(generated)
    gold_ids, gen_ids = all_concept_ids(gold), all_concept_ids(generated)
    hierarchy = Hierarchy(gold_ids | gen_ids)

    out["concept_mapping"] = {
        "relation_profile": relation_profile(gen_ids, gold_ids, hierarchy),
        "per_term": align_terms(gold_sets, gen_sets, threshold, hierarchy),
    }
    gold_values, gen_values = value_constraints(gold), value_constraints(generated)
    out["circe_agreement"] = {
        "gold_concept_sets": len(gold_sets), "gen_concept_sets": len(gen_sets),
        "gold_inclusion_rules": len(gold.get("InclusionRules") or []),
        "gen_inclusion_rules": len(generated.get("InclusionRules") or []),
        "concept_id_jaccard": jaccard(gold_ids, gen_ids),
        "gold_entry_domain": entry_domain(gold),
        "gen_entry_domain": entry_domain(generated),
        "entry_domain_match": entry_domain(gold) == entry_domain(generated),
        "gold_value_constraints": dict(gold_values),
        "gen_value_constraints": dict(gen_values),
        "value_constraint_ratio": round(sum(gen_values.values()) / sum(gold_values.values()), 4)
        if sum(gold_values.values()) else None,
    }
    return out


def determinism(reps: list[dict[str, Any]]) -> dict[str, Any]:
    """Spread across repeats, or an explicit statement that there is only one."""
    done = [r for r in reps if r.get("status") == "completed"]
    if len(done) < 2:
        return {"samples": len(reps),
                "note": "single sample: no variance measured, treat every number as one draw"}

    def spread(path: tuple[str, ...]) -> dict[str, Any] | None:
        values = []
        for rep in done:
            node: Any = rep
            for key in path:
                node = (node or {}).get(key) if isinstance(node, dict) else None
            if isinstance(node, (int, float)):
                values.append(float(node))
        if len(values) < 2:
            return None
        return {"values": values, "min": min(values), "max": max(values),
                "stdev": round(statistics.stdev(values), 4)}

    return {
        "samples": len(reps),
        "completed": len(done),
        "exact_rate": spread(("concept_mapping", "relation_profile", "exact_rate")),
        "unrelated_rate": spread(("concept_mapping", "relation_profile", "unrelated_rate")),
        "concept_id_jaccard": spread(("circe_agreement", "concept_id_jaccard")),
        "gen_inclusion_rules": spread(("circe_agreement", "gen_inclusion_rules")),
        "strict_json_rate": spread(("mechanics", "strict_json_rate")),
        "note": "vLLM continuous batching changes reduction order with batch "
                "composition, so temperature 0 plus a fixed seed is not a "
                "reproducibility guarantee. This is the measured spread.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", help="<root>/<arm>/<model_slug>")
    parser.add_argument("--gold", default=None, help="gold dir (default: <checkout>/data/gold)")
    parser.add_argument("--align-threshold", type=float, default=0.34)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    meta = json.loads((run_dir / "run_meta.json").read_text())
    gold_dir = Path(args.gold) if args.gold else Path(meta["checkout"]) / "data" / "gold"
    # The vocabulary lives behind the pipeline's own db/settings modules, and the
    # arm being scored owns which checkout those come from.
    sys.path.insert(0, meta["checkout"])

    studies: dict[str, Any] = {}
    for study_dir in sorted((run_dir / "studies").iterdir(), key=lambda p: int(p.name)):
        study_id = int(study_dir.name)
        gold_rel = GOLD_BY_STUDY.get(study_id)
        if gold_rel is None:
            studies[study_dir.name] = {"skipped": "no gold cohort mapped for this study"}
            continue
        gold = json.loads((gold_dir / gold_rel).read_text())
        reps = [score_repeat(d, gold, args.align_threshold)
                for d in sorted(study_dir.glob("rep*")) if (d / "result.json").exists()]
        studies[study_dir.name] = {
            "label": gold_rel.split("/")[0],
            "gold_file": gold_rel,
            "repeats": reps,
            "determinism": determinism(reps),
        }

    ok = [r for s in studies.values() for r in s.get("repeats", []) if r.get("status") == "completed"]
    payload = {
        "run_meta": meta,
        "gold_dir": str(gold_dir),
        "aggregate": {
            "studies_attempted": len(studies),
            "repeats_completed": len(ok),
            "repeats_failed": sum(len(s.get("repeats", [])) for s in studies.values()) - len(ok),
            "mean_exact_rate": _mean(ok, ("concept_mapping", "relation_profile", "exact_rate")),
            "mean_in_hierarchy_rate": _mean(ok, ("concept_mapping", "relation_profile", "in_hierarchy_rate")),
            "mean_unrelated_rate": _mean(ok, ("concept_mapping", "relation_profile", "unrelated_rate")),
            "mean_gold_recall": _mean(ok, ("concept_mapping", "relation_profile", "gold_recall")),
            "mean_concept_id_jaccard": _mean(ok, ("circe_agreement", "concept_id_jaccard")),
            "entry_domain_match_rate": _mean(ok, ("circe_agreement", "entry_domain_match")),
            "mean_strict_json_rate": _mean(ok, ("mechanics", "strict_json_rate")),
            "total_llm_calls": sum(r["mechanics"]["calls"] for r in ok),
            "total_llm_seconds": round(sum(r["mechanics"]["total_llm_seconds"] for r in ok), 1),
            "total_estimated_cost_usd": round(sum(r["mechanics"]["estimated_cost_usd"] for r in ok), 4),
            "models_actually_used": dict(sum(
                (Counter(r["mechanics"]["models_used"]) for r in ok), Counter())),
        },
        "gold_caveat": "Gold is a curated key, not an oracle: the investigators "
                       "made judgement calls and this project has already found "
                       "generated output that was defensible where gold differed. "
                       "Every mismatch is recorded with concept names, alignment "
                       "score and hierarchy relation so 'wrong' can be told from "
                       "'different'. Do not read unrelated_rate as an error rate "
                       "without reading unrelated_sample.",
        "studies": studies,
    }
    (run_dir / "scores.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1))

    agg = payload["aggregate"]
    print(f"{meta['arm']}/{meta['model_slug']}  completed={agg['repeats_completed']} "
          f"failed={agg['repeats_failed']}")
    print(f"  exact={agg['mean_exact_rate']} hierarchy={agg['mean_in_hierarchy_rate']} "
          f"unrelated={agg['mean_unrelated_rate']} gold_recall={agg['mean_gold_recall']}")
    print(f"  jaccard={agg['mean_concept_id_jaccard']} entry_match={agg['entry_domain_match_rate']} "
          f"strict_json={agg['mean_strict_json_rate']}")
    print(f"  calls={agg['total_llm_calls']} llm_s={agg['total_llm_seconds']} "
          f"cost=${agg['total_estimated_cost_usd']} models={agg['models_actually_used']}")
    print(f"wrote {run_dir / 'scores.json'}")
    return 0


def _mean(reps: list[dict[str, Any]], path: tuple[str, ...]) -> float | None:
    values = []
    for rep in reps:
        node: Any = rep
        for key in path:
            node = (node or {}).get(key) if isinstance(node, dict) else None
        if isinstance(node, bool):
            values.append(float(node))
        elif isinstance(node, (int, float)):
            values.append(float(node))
    return round(statistics.mean(values), 4) if values else None


if __name__ == "__main__":
    raise SystemExit(main())
