#!/usr/bin/env python3
"""
Extract criteria-level concept mapping benchmark from OHDSI study cohort JSONs.

For each InclusionRule that references a ConceptSet via CodesetId, extracts:
  (criterion_name, concept_set_name, [ground_truth_concept_ids])

Output: artemis/data/benchmark_data/ohdsi_criteria_benchmark.json
"""

from __future__ import annotations

import glob
import json
import os
import re
import statistics
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STUDIES_DIR = Path(__file__).parent.parent / "data" / "ohdsi_studies"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "benchmark_data"
OUTPUT_FILE = OUTPUT_DIR / "ohdsi_criteria_benchmark.json"

# CIRCE criteria type → OMOP domain hint (clinical domains only)
# Each CIRCE criteria key maps to one of the five target domains.
CRITERIA_DOMAIN_MAP: dict[str, str] = {
    "ConditionOccurrence": "Condition",
    "ConditionEra": "Condition",
    "DrugExposure": "Drug",
    "DrugEra": "Drug",
    "DoseEra": "Drug",
    "Measurement": "Measurement",
    "ProcedureOccurrence": "Procedure",
    "Observation": "Observation",
    "ObservationPeriod": None,   # not a clinical domain
    "VisitOccurrence": None,
    "VisitDetail": None,
    "Death": None,
    "DeviceExposure": None,
}

CLINICAL_DOMAINS = {"Condition", "Drug", "Measurement", "Procedure", "Observation"}

MIN_CONCEPTS = 1
MAX_CONCEPTS = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_meaningful_name(name: str) -> bool:
    """Return True if the concept set name looks like a clinical label.

    Filters out:
    - Empty / whitespace-only strings
    - Pure numeric strings (e.g. "12345")
    - Very short strings (length < 3)
    """
    stripped = name.strip()
    if not stripped or len(stripped) < 3:
        return False
    if re.fullmatch(r"\d+", stripped):
        return False
    return True


def _extract_concept_ids(concept_set: dict) -> list[int]:
    """Return sorted CONCEPT_IDs that the expert INCLUDED in this concept set.

    `isExcluded` was ignored, so every concept the expert deliberately removed was
    recorded as a correct answer. Measured on the shipped benchmark: 596 of 2,109
    ground-truth ids (28.3%) are excluded concepts, across 33 of 242 questions, and
    three questions are 100% excluded -- a mapper scores full marks there only by
    returning exactly what the expert deleted, and is penalised on both recall and
    precision for getting it right.

    benchmark_v5.py:336-343 already documents the intended rule ("isExcluded=true:
    remove from result set") and implements it. This extractor and the scorer in
    quick_concept_benchmark_v2.py never read the flag, so the rule existed in one
    place and the gold was built in another.

    Descendant expansion (`includeDescendants`) is a separate question and is
    deliberately left alone here.
    """
    ids: list[int] = []
    for item in concept_set.get("expression", {}).get("items", []):
        if item.get("isExcluded"):
            continue
        concept = item.get("concept", {})
        cid = concept.get("CONCEPT_ID")
        if cid is not None:
            ids.append(int(cid))
    return sorted(set(ids))


def _infer_domain_from_concept_set(concept_set: dict) -> str | None:
    """Infer domain from the DOMAIN_ID fields of concepts in the set."""
    domain_counts: dict[str, int] = {}
    for item in concept_set.get("expression", {}).get("items", []):
        domain = item.get("concept", {}).get("DOMAIN_ID", "")
        if domain:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
    if not domain_counts:
        return None
    # Return most common domain
    dominant = max(domain_counts, key=lambda k: domain_counts[k])
    # Normalize Drug vocabulary domain label to "Drug"
    if dominant in ("Drug",):
        return "Drug"
    if dominant in ("Condition",):
        return "Condition"
    if dominant in ("Procedure",):
        return "Procedure"
    if dominant in ("Measurement",):
        return "Measurement"
    if dominant in ("Observation",):
        return "Observation"
    return None


def _extract_criteria_from_inclusion_rules(
    cohort: dict,
    cs_map: dict[int, dict],
    study: str,
    cohort_filename: str,
) -> list[dict]:
    """Extract benchmark items from InclusionRules in a cohort JSON."""
    items: list[dict] = []

    for rule in cohort.get("InclusionRules", []):
        criterion_name = rule.get("name", "").strip()
        if not criterion_name:
            continue

        expression = rule.get("expression", {})
        for criteria_list_item in expression.get("CriteriaList", []):
            criteria = criteria_list_item.get("Criteria", {})
            for circe_type, criteria_detail in criteria.items():
                # Determine domain hint from CIRCE type
                domain_hint = CRITERIA_DOMAIN_MAP.get(circe_type)
                if domain_hint not in CLINICAL_DOMAINS:
                    continue

                codeset_id = criteria_detail.get("CodesetId")
                if codeset_id is None:
                    continue

                concept_set = cs_map.get(int(codeset_id))
                if concept_set is None:
                    continue

                cs_name = concept_set.get("name", "").strip()
                if not _is_meaningful_name(cs_name):
                    continue

                concept_ids = _extract_concept_ids(concept_set)
                if not (MIN_CONCEPTS <= len(concept_ids) <= MAX_CONCEPTS):
                    continue

                # Use domain from concept set concepts if CIRCE type gives ambiguous hint
                inferred_domain = _infer_domain_from_concept_set(concept_set)
                final_domain = inferred_domain if inferred_domain in CLINICAL_DOMAINS else domain_hint

                items.append({
                    "study": study,
                    "cohort": cohort_filename,
                    "criterion_name": criterion_name,
                    "concept_set_name": cs_name,
                    "domain_hint": final_domain,
                    "ground_truth_concept_ids": concept_ids,
                })

    return items


def _extract_from_primary_criteria(
    cohort: dict,
    cs_map: dict[int, dict],
    study: str,
    cohort_filename: str,
) -> list[dict]:
    """Extract benchmark items from PrimaryCriteria as well (cohort entry event)."""
    items: list[dict] = []
    pc = cohort.get("PrimaryCriteria", {})

    for criteria_container in pc.get("CriteriaList", []):
        for circe_type, criteria_detail in criteria_container.items():
            domain_hint = CRITERIA_DOMAIN_MAP.get(circe_type)
            if domain_hint not in CLINICAL_DOMAINS:
                continue

            codeset_id = criteria_detail.get("CodesetId")
            if codeset_id is None:
                continue

            concept_set = cs_map.get(int(codeset_id))
            if concept_set is None:
                continue

            cs_name = concept_set.get("name", "").strip()
            if not _is_meaningful_name(cs_name):
                continue

            concept_ids = _extract_concept_ids(concept_set)
            if not (MIN_CONCEPTS <= len(concept_ids) <= MAX_CONCEPTS):
                continue

            inferred_domain = _infer_domain_from_concept_set(concept_set)
            final_domain = inferred_domain if inferred_domain in CLINICAL_DOMAINS else domain_hint

            # Use concept set name as criterion name for primary criteria
            items.append({
                "study": study,
                "cohort": cohort_filename,
                "criterion_name": f"[primary] {cs_name}",
                "concept_set_name": cs_name,
                "domain_hint": final_domain,
                "ground_truth_concept_ids": concept_ids,
            })

    return items


# ---------------------------------------------------------------------------
# Inline assertions (TDD-style)
# ---------------------------------------------------------------------------

def _run_inline_tests() -> None:
    assert _is_meaningful_name("") is False
    assert _is_meaningful_name("   ") is False
    assert _is_meaningful_name("12") is False
    assert _is_meaningful_name("12345") is False
    assert _is_meaningful_name("DM") is False   # length < 3
    assert _is_meaningful_name("T2DM") is True
    assert _is_meaningful_name("Myocardial infarction") is True
    assert _is_meaningful_name("[TROY] STEMI") is True

    # _extract_concept_ids
    fake_cs = {
        "expression": {
            "items": [
                {"concept": {"CONCEPT_ID": 100, "DOMAIN_ID": "Condition"}},
                {"concept": {"CONCEPT_ID": 200, "DOMAIN_ID": "Condition"}},
                {"concept": {"CONCEPT_ID": 100, "DOMAIN_ID": "Condition"}},  # duplicate
            ]
        }
    }
    assert _extract_concept_ids(fake_cs) == [100, 200]

    # _infer_domain_from_concept_set
    assert _infer_domain_from_concept_set(fake_cs) == "Condition"

    print("All inline assertions passed.")


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_benchmark() -> dict:
    """Walk all OHDSI studies and extract criteria benchmark items."""

    all_items: list[dict] = []
    study_counts: dict[str, int] = {}

    studies = sorted(
        d for d in os.listdir(STUDIES_DIR)
        if (STUDIES_DIR / d).is_dir()
    )

    for study in studies:
        study_path = STUDIES_DIR / study
        cohort_files = sorted(glob.glob(str(study_path / "*.json")))

        for cohort_path in cohort_files:
            cohort_filename = os.path.basename(cohort_path)
            try:
                with open(cohort_path, encoding="utf-8") as f:
                    cohort = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            # Build concept set map: id → concept set dict
            cs_map: dict[int, dict] = {
                int(cs["id"]): cs
                for cs in cohort.get("ConceptSets", [])
                if "id" in cs
            }

            raw_items = (
                _extract_criteria_from_inclusion_rules(cohort, cs_map, study, cohort_filename)
                + _extract_from_primary_criteria(cohort, cs_map, study, cohort_filename)
            )

            all_items.extend(raw_items)
            if raw_items:
                study_counts[study] = study_counts.get(study, 0) + len(raw_items)

    # Deduplicate: same (study, cohort, concept_set_name) may appear from multiple
    # InclusionRules referencing the same CodesetId. Keep unique by key tuple.
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for item in all_items:
        key = (
            item["study"],
            item["cohort"],
            item["criterion_name"],
            item["concept_set_name"],
        )
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    # Assign stable IDs
    for idx, item in enumerate(deduped):
        item["id"] = f"{item['study']}__{item['cohort'].replace('.json','')}__{idx}"

    # Reorder fields for readability
    ordered: list[dict] = [
        {
            "id": it["id"],
            "study": it["study"],
            "cohort": it["cohort"],
            "criterion_name": it["criterion_name"],
            "concept_set_name": it["concept_set_name"],
            "domain_hint": it["domain_hint"],
            "ground_truth_concept_ids": it["ground_truth_concept_ids"],
        }
        for it in deduped
    ]

    return {
        "metadata": {
            "source": "ohdsi_studies",
            "total_items": len(ordered),
            "studies": len(study_counts),
            "generated": str(date.today()),
        },
        "items": ordered,
        "_study_counts": study_counts,  # kept for stats, stripped before final save
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def print_statistics(result: dict) -> None:
    items = result["items"]
    study_counts = result.get("_study_counts", {})

    print(f"\n{'='*60}")
    print("OHDSI Criteria Benchmark — Extraction Summary")
    print(f"{'='*60}")
    print(f"Total items extracted : {len(items)}")
    print(f"Studies with data     : {result['metadata']['studies']}")

    # Domain distribution
    domain_dist: dict[str, int] = {}
    for it in items:
        d = it["domain_hint"] or "Unknown"
        domain_dist[d] = domain_dist.get(d, 0) + 1

    print(f"\nDomain distribution:")
    for domain, count in sorted(domain_dist.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(items) if items else 0
        print(f"  {domain:<15} {count:>5}  ({pct:.1f}%)")

    # Concepts per item
    concept_counts = [len(it["ground_truth_concept_ids"]) for it in items]
    if concept_counts:
        print(f"\nConcept IDs per item:")
        print(f"  Min    : {min(concept_counts)}")
        print(f"  Median : {statistics.median(concept_counts):.0f}")
        print(f"  Mean   : {statistics.mean(concept_counts):.1f}")
        print(f"  Max    : {max(concept_counts)}")

    # Top 10 studies
    top_studies = sorted(study_counts.items(), key=lambda x: -x[1])[:10]
    print(f"\nTop 10 studies by item count:")
    for study, count in top_studies:
        print(f"  {study:<45} {count:>4}")

    # Sample items
    print(f"\nSample of 5 items:")
    sample = [it for it in items if len(it["concept_set_name"]) > 8][:5]
    for it in sample:
        ids_preview = it["ground_truth_concept_ids"][:3]
        ellipsis = "..." if len(it["ground_truth_concept_ids"]) > 3 else ""
        print(f"  [{it['study']}]")
        print(f"    criterion  : {it['criterion_name'][:80]}")
        print(f"    concept set: {it['concept_set_name']}")
        print(f"    domain     : {it['domain_hint']}")
        print(f"    concept IDs: {ids_preview}{ellipsis} ({len(it['ground_truth_concept_ids'])} total)")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_inline_tests()

    print("Extracting criteria benchmark from OHDSI studies...")
    result = extract_benchmark()

    print_statistics(result)

    # Strip internal stats before saving
    output = {k: v for k, v in result.items() if k != "_study_counts"}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to: {OUTPUT_FILE}")
