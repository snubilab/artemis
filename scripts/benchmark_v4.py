"""
Benchmark V4: Parent-Level Rule Comparison for ARTEMIS vs TROY.

Fixes V3's 1:1 sub-criteria matching limitation by comparing at the
parent inclusion rule level:

1. Each inclusion rule → 1 "RuleFingerprint" (name, occurrence_type, pooled concept IDs)
2. Semantic N:1 matching (multiple ARTEMIS rules can match one TROY composite rule)
3. Per-rule resolved concept pool recall

Usage:
    conda run -n artemis python scripts/benchmark_v4.py
"""
import json
import sys
import os
import re
from datetime import datetime
from typing import Dict, Any, List, Set, Tuple, Optional
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
import psycopg2

# ============================================================
# Configuration
# ============================================================
TROY_PATH = "data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
ARTEMIS_PATH = "data/sample/LEADER/TELOS_LEADER_design_paper_e2e.json"
REPORT_DIR = "output"

DB_HOST = os.environ.get("OMOP_DB_HOST", "localhost")
DB_PORT = os.environ.get("OMOP_DB_PORT", "5432")
DB_NAME = os.environ.get("OMOP_DB_NAME", "postgres")
DB_USER = os.environ.get("OMOP_DB_USER", "postgres")
DB_PASS = os.environ.get("OMOP_DB_PASS", "mypass")
SCHEMA = "synthea_cdm"

# ============================================================
# Manual Rule Mapping: TROY rule name → [ARTEMIS rule names]
# Needed because TROY regroups design paper criteria differently.
# ============================================================
MANUAL_MAPPING = {
    "prior CV disease": [
        "Prior MI", "Prior stroke or TIA", "Prior revascularization",
        "Arterial stenosis >50%", "Symptomatic CHD", "Asymptomatic cardiac ischemia",
        "CHF NYHA II-III", "Chronic renal failure", "Microalbuminuria or proteinuria",
        "Hypertension with LVH", "LV dysfunction", "Low ABI",
    ],
    "No use of insulin": ["Non-allowed insulin"],
    "No acute coronary or cerebrovascular event ": [
        "Recent acute coronary/cerebrovascular event", "Planned revascularization"
    ],
    "No eGFR <30 mL/min/1.73m2": [
        "Severe renal impairment (measurement)", "Severe renal impairment (CKD 4-5)"
    ],
}

# Medical alias expansion for fuzzy matching
MEDICAL_ALIASES = {
    "tia": {"transient", "ischemic", "attack"},
    "pad": {"peripheral", "arterial", "disease"},
    "ckd": {"chronic", "kidney"},
    "esld": {"end", "stage", "liver"},
    "esrd": {"end", "stage", "renal"},
    "mi": {"myocardial", "infarction"},
    "chf": {"congestive", "heart", "failure"},
    "nyha": {"new", "york", "heart", "association"},
    "men2": {"multiple", "endocrine", "neoplasia"},
    "mtc": {"medullary", "thyroid", "carcinoma"},
    "fmtc": {"familial", "medullary", "thyroid", "carcinoma"},
    "glp1": {"glp", "1", "receptor", "agonist"},
    "dpp4": {"dpp", "4", "inhibitor"},
    "egfr": {"estimated", "glomerular", "filtration", "rate"},
    "hba1c": {"hemoglobin", "a1c"},
    "cv": {"cardiovascular"},
    "t1dm": {"type", "1", "diabetes"},
    "t2dm": {"type", "2", "diabetes"},
    "lv": {"left", "ventricular"},
    "lvh": {"left", "ventricular", "hypertrophy"},
    "abi": {"ankle", "brachial", "index"},
    "chd": {"coronary", "heart", "disease"},
}

STOPWORDS = {
    "history", "of", "the", "a", "and", "or", "with", "without",
    "no", "prior", "recent", "current", "use", "within", "days",
    "months", ">=", "<=", ">", "<", "to", "in", "for", "on",
}


# ============================================================
# Data Model: Parent-Level Rule Fingerprint
# ============================================================
@dataclass
class RuleFingerprint:
    """One fingerprint per parent inclusion rule."""
    rule_name: str
    occurrence_type: str  # PRESENCE or ABSENCE
    concept_set_names: List[str]  # All CS names in this rule
    concept_set_ids: List[int]  # All CodesetIds referenced
    n_sub_criteria: int  # Number of CriteriaList entries
    is_demographic: bool = False

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'\[.*?\]', '', text)
        text = re.sub(r'\(.*?\)', '', text)
        text = re.sub(r'[^\w\s]', '', text)
        return ' '.join(w for w in text.split() if w)

    def _expand_tokens(self, text: str) -> Set[str]:
        """Expand text to token set, resolving aliases."""
        norm = self._normalize(text)
        tokens = set()
        for word in norm.split():
            if word in STOPWORDS:
                continue
            if word in MEDICAL_ALIASES:
                tokens.update(MEDICAL_ALIASES[word])
            else:
                tokens.add(word)
        return tokens

    @property
    def tokens(self) -> Set[str]:
        return self._expand_tokens(self.rule_name)


def extract_rule_fingerprints(
    circe_json: Dict[str, Any],
    label: str = ""
) -> List[RuleFingerprint]:
    """Extract one fingerprint per parent inclusion rule."""
    # Build CS map
    cs_map = {}
    for cs in circe_json.get("ConceptSets", []):
        name = re.sub(r'\[TROY\]\s*', '', cs["name"])
        cs_map[cs["id"]] = name

    fingerprints = []
    for rule in circe_json.get("InclusionRules", []):
        rule_name = rule.get("name", "Unnamed")
        expr = rule.get("expression", {})
        criteria_list = expr.get("CriteriaList", [])
        demo_list = expr.get("DemographicCriteriaList", [])

        # Determine occurrence (from first criteria entry)
        occurrence_type = "PRESENCE"
        if criteria_list:
            occ = criteria_list[0].get("Occurrence", {})
            count_column = occ.get("CountColumn", "")
            if count_column:
                occurrence_type = "ABSENCE"
            occ_type = occ.get("Type", 2)
            if occ_type == 0:  # AT_MOST with Count=0 → ABSENCE
                occurrence_type = "ABSENCE"
            elif occ_type == 1:  # AT_LEAST → PRESENCE
                occurrence_type = "PRESENCE"

        # Collect all concept set names and IDs (from CriteriaList + nested Groups)
        cs_names = []
        cs_ids = []

        def _collect_from_criteria_list(cl):
            for crit_entry in cl:
                crit = crit_entry.get("Criteria", {})
                for domain_key, content in crit.items():
                    csid = content.get("CodesetId", 0)
                    if csid != 0:
                        cs_ids.append(csid)
                        cs_names.append(cs_map.get(csid, f"UNMAPPED({csid})"))

        _collect_from_criteria_list(criteria_list)

        # Handle nested Groups (e.g., TROY "prior CV disease")
        for group in expr.get("Groups", []):
            _collect_from_criteria_list(group.get("CriteriaList", []))
            for sub_group in group.get("Groups", []):
                _collect_from_criteria_list(sub_group.get("CriteriaList", []))

        total_criteria = len(criteria_list) + sum(
            len(g.get("CriteriaList", [])) for g in expr.get("Groups", [])
        )

        if demo_list and not criteria_list and not cs_ids:
            fingerprints.append(RuleFingerprint(
                rule_name=rule_name,
                occurrence_type="DEMOGRAPHIC",
                concept_set_names=[],
                concept_set_ids=[],
                n_sub_criteria=0,
                is_demographic=True,
            ))
            continue

        fingerprints.append(RuleFingerprint(
            rule_name=rule_name,
            occurrence_type=occurrence_type,
            concept_set_names=cs_names,
            concept_set_ids=cs_ids,
            n_sub_criteria=total_criteria,
        ))

    return fingerprints


# ============================================================
# Matching: Allow N:1 grouping (2-phase)
# ============================================================
def compute_token_similarity(troy: RuleFingerprint, artemis: RuleFingerprint) -> float:
    """Compute semantic similarity between two rule fingerprints.
    
    Uses both rule names AND concept set names from both sides for matching.
    """
    if troy.is_demographic and artemis.is_demographic:
        t1 = troy.tokens
        t2 = artemis.tokens
        return len(t1 & t2) / len(t1 | t2) if t1 and t2 else 0.0

    if troy.is_demographic != artemis.is_demographic:
        return 0.0

    # Build expanded token pools (rule name + CS names)
    troy_name_tokens = troy.tokens
    artemis_name_tokens = artemis.tokens
    if not troy_name_tokens or not artemis_name_tokens:
        return 0.0

    # Score 1: rule name ↔ rule name
    name_jaccard = len(troy_name_tokens & artemis_name_tokens) / len(troy_name_tokens | artemis_name_tokens)

    # Score 2: TROY rule name ↔ ARTEMIS CS names
    artemis_cs_tokens = set()
    for cs in artemis.concept_set_names:
        artemis_cs_tokens.update(artemis._expand_tokens(cs))
    troy_in_artemis_cs = len(troy_name_tokens & artemis_cs_tokens) / len(troy_name_tokens) if troy_name_tokens else 0.0

    # Score 3: TROY CS names ↔ ARTEMIS rule name
    troy_cs_tokens = set()
    for cs in troy.concept_set_names:
        troy_cs_tokens.update(troy._expand_tokens(cs))
    artemis_in_troy_cs = len(artemis_name_tokens & troy_cs_tokens) / len(artemis_name_tokens) if artemis_name_tokens else 0.0

    # Score 4: TROY CS names ↔ ARTEMIS CS names
    cs_jaccard = 0.0
    if troy_cs_tokens and artemis_cs_tokens:
        cs_jaccard = len(troy_cs_tokens & artemis_cs_tokens) / len(troy_cs_tokens | artemis_cs_tokens)

    return max(name_jaccard, troy_in_artemis_cs * 0.85, artemis_in_troy_cs * 0.85, cs_jaccard * 0.9)


def match_rules(
    troy_fps: List[RuleFingerprint],
    artemis_fps: List[RuleFingerprint],
    troy_json: Dict[str, Any],
    artemis_json: Dict[str, Any],
    cur,
    name_threshold: float = 0.3,
    concept_overlap_threshold: float = 0.1,
) -> Tuple[List[Tuple[RuleFingerprint, List[RuleFingerprint]]], List[RuleFingerprint], List[RuleFingerprint]]:
    """
    Match TROY rules to ARTEMIS rules with 2-phase matching.

    Phase 1: Token-based name matching (rule names + CS names)
    Phase 2: Concept-overlap matching for remaining unmatched rules.
             Resolves concept IDs and checks if ARTEMIS rule's concepts
             overlap with TROY rule's concept pool. Handles N:1 grouping.
    """
    # ── Phase 0: Manual mapping ─────────────
    troy_by_name = {fp.rule_name: i for i, fp in enumerate(troy_fps)}
    artemis_by_name = {fp.rule_name: j for j, fp in enumerate(artemis_fps)}

    troy_groups: Dict[int, List[int]] = {}
    artemis_used = set()

    for troy_name, artemis_names in MANUAL_MAPPING.items():
        if troy_name in troy_by_name:
            i = troy_by_name[troy_name]
            troy_groups[i] = []
            for tn in artemis_names:
                if tn in artemis_by_name:
                    j = artemis_by_name[tn]
                    troy_groups[i].append(j)
                    artemis_used.add(j)

    print(f"[Phase 0] Manual mapping: {len(troy_groups)} TROY rules, "
          f"{len(artemis_used)} ARTEMIS rules consumed")

    # ── Phase 1: Name-based greedy matching (remaining) ─────────────
    scores = []
    for i, troy in enumerate(troy_fps):
        if i in troy_groups:
            continue
        for j, artemis in enumerate(artemis_fps):
            if j in artemis_used:
                continue
            score = compute_token_similarity(troy, artemis)
            if score >= name_threshold:
                scores.append((score, i, j))

    scores.sort(key=lambda x: x[0], reverse=True)

    for score, i, j in scores:
        if j not in artemis_used:
            if i not in troy_groups:
                troy_groups[i] = []
            troy_groups[i].append(j)
            artemis_used.add(j)

    print(f"[Phase 1] Name matching: {len(troy_groups)} TROY rules matched, "
          f"{sum(len(v) for v in troy_groups.values())} ARTEMIS rules consumed")

    # ── Phase 2: Concept-overlap matching ─────────────
    remaining_troy = {i for i in range(len(troy_fps)) if i not in troy_groups and not troy_fps[i].is_demographic}
    remaining_artemis = {j for j in range(len(artemis_fps)) if j not in artemis_used and not artemis_fps[j].is_demographic}

    if remaining_troy and remaining_artemis:
        # Pre-resolve concept pools for remaining rules
        troy_pools = {}
        for i in remaining_troy:
            ids = pool_concept_ids_for_rule(troy_fps[i], troy_json)
            troy_pools[i] = resolve_concept_set(cur, ids) if ids else set()

        artemis_pools = {}
        for j in remaining_artemis:
            ids = pool_concept_ids_for_rule(artemis_fps[j], artemis_json)
            artemis_pools[j] = resolve_concept_set(cur, ids) if ids else set()

        # For each unmatched ARTEMIS rule, find best TROY rule by concept overlap
        concept_scores = []
        for j in remaining_artemis:
            t_pool = artemis_pools[j]
            if not t_pool:
                continue
            for i in remaining_troy:
                tr_pool = troy_pools[i]
                if not tr_pool:
                    continue
                overlap = len(t_pool & tr_pool) / len(tr_pool)
                if overlap >= concept_overlap_threshold:
                    concept_scores.append((overlap, i, j))

        concept_scores.sort(key=lambda x: x[0], reverse=True)

        for overlap, i, j in concept_scores:
            if j not in artemis_used:
                if i not in troy_groups:
                    troy_groups[i] = []
                troy_groups[i].append(j)
                artemis_used.add(j)

        phase2_matched = sum(1 for i in troy_groups if i in remaining_troy)
        phase2_artemis = sum(1 for j in artemis_used if j in remaining_artemis)
        print(f"[Phase 2] Concept overlap: {phase2_matched} TROY rules matched, "
              f"{phase2_artemis} ARTEMIS rules consumed")

    # Build result
    matched = []
    for i, artemis_indices in troy_groups.items():
        matched.append((troy_fps[i], [artemis_fps[j] for j in artemis_indices]))

    unmatched_troy = [fp for i, fp in enumerate(troy_fps) if i not in troy_groups]
    unmatched_artemis = [fp for j, fp in enumerate(artemis_fps) if j not in artemis_used]

    return matched, unmatched_troy, unmatched_artemis


# ============================================================
# Concept Set Resolution & Comparison
# ============================================================
def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )


def resolve_concept_set(cur, concept_ids: list) -> Set[int]:
    """Resolve concept IDs with descendants."""
    if not concept_ids:
        return set()
    resolved = set(concept_ids)
    cur.execute(f"""
        SELECT DISTINCT ca.descendant_concept_id
        FROM {SCHEMA}.concept_ancestor ca
        JOIN {SCHEMA}.concept c ON ca.descendant_concept_id = c.concept_id
        WHERE ca.ancestor_concept_id = ANY(%s)
          AND c.standard_concept = 'S'
    """, (list(concept_ids),))
    for row in cur.fetchall():
        resolved.add(row[0])
    return resolved


def extract_concept_ids_from_cs(cs: Dict[str, Any]) -> List[int]:
    items = cs.get("expression", {}).get("items", [])
    return [item["concept"]["CONCEPT_ID"] for item in items if "concept" in item]


def pool_concept_ids_for_rule(
    rule_fp: RuleFingerprint,
    circe_json: Dict[str, Any],
) -> List[int]:
    """Get all concept IDs referenced by a rule's concept sets."""
    all_ids = []
    cs_by_id = {cs["id"]: cs for cs in circe_json.get("ConceptSets", [])}
    for csid in rule_fp.concept_set_ids:
        if csid in cs_by_id:
            all_ids.extend(extract_concept_ids_from_cs(cs_by_id[csid]))
    return all_ids


# ============================================================
# Main Evaluation
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark V4: Parent-Level Rule Comparison")
    parser.add_argument("--troy", default=TROY_PATH)
    parser.add_argument("--artemis", default=ARTEMIS_PATH)
    parser.add_argument("--report-dir", default=REPORT_DIR, help="Directory for JSON report")
    args = parser.parse_args()

    with open(args.troy) as f:
        troy_json = json.load(f)
    with open(args.artemis) as f:
        artemis_json = json.load(f)

    # Extract parent-level fingerprints
    troy_fps = extract_rule_fingerprints(troy_json, "TROY")
    artemis_fps = extract_rule_fingerprints(artemis_json, "ARTEMIS")

    print(f"TROY: {len(troy_fps)} parent rules")
    print(f"ARTEMIS: {len(artemis_fps)} parent rules")
    print()

    # DB connection for concept resolution
    conn = get_db_connection()
    cur = conn.cursor()

    # Match rules (2-phase: name + concept overlap)
    matched, unmatched_troy, unmatched_artemis = match_rules(
        troy_fps, artemis_fps, troy_json, artemis_json, cur
    )

    # Evaluate matched pairs
    print("=" * 70)
    print("MATCHED RULES")
    print("=" * 70)

    total_recall = 0.0
    n_recall = 0
    full = 0
    partial = 0
    wrong = 0

    for troy_fp, artemis_group in matched:
        artemis_names = [t.rule_name for t in artemis_group]

        if troy_fp.is_demographic:
            print(f"  ✅ [DEMO] {troy_fp.rule_name} ↔ {artemis_names}")
            full += 1
            total_recall += 1.0
            n_recall += 1
            continue

        # Pool concept IDs
        troy_ids = pool_concept_ids_for_rule(troy_fp, troy_json)
        artemis_ids = []
        for t_fp in artemis_group:
            artemis_ids.extend(pool_concept_ids_for_rule(t_fp, artemis_json))

        # Resolve with descendants
        troy_resolved = resolve_concept_set(cur, troy_ids)
        artemis_resolved = resolve_concept_set(cur, artemis_ids)

        if not troy_resolved:
            recall = 1.0
        else:
            recall = len(troy_resolved & artemis_resolved) / len(troy_resolved)

        total_recall += recall
        n_recall += 1

        # Classify
        if recall >= 0.8:
            emoji = "✅"
            full += 1
        elif recall >= 0.3:
            emoji = "🔶"
            partial += 1
        else:
            emoji = "❌"
            wrong += 1

        group_tag = ""
        if len(artemis_group) > 1:
            group_tag = f" ({len(artemis_group)} ARTEMIS rules)"

        print(f"  {emoji} {troy_fp.rule_name} ↔ {artemis_names[0]}{group_tag}: "
              f"Recall={recall:.0%} (TROY={len(troy_resolved)}, ARTEMIS={len(artemis_resolved)})")

    # Unmatched TROY
    missed = len(unmatched_troy)
    if unmatched_troy:
        print()
        print(f"UNMATCHED TROY ({missed}):")
        for fp in unmatched_troy:
            troy_ids = pool_concept_ids_for_rule(fp, troy_json)
            n_concepts = len(resolve_concept_set(cur, troy_ids)) if troy_ids else 0
            print(f"  ❌ {fp.rule_name} ({fp.n_sub_criteria} sub, {n_concepts} resolved concepts)")
            total_recall += 0.0
            n_recall += 1

    # Unmatched ARTEMIS (extra rules)
    if unmatched_artemis:
        print()
        print(f"UNMATCHED ARTEMIS ({len(unmatched_artemis)}) — ARTEMIS-only rules:")
        for fp in unmatched_artemis:
            print(f"  ➕ {fp.rule_name} ({fp.n_sub_criteria} sub-criteria)")

    # Summary
    avg_recall = total_recall / n_recall if n_recall else 0.0
    print()
    print("=" * 70)
    print(f"  SUMMARY: Full={full} | Partial={partial} | Wrong={wrong} | "
          f"Missed={missed} | Avg Recall={avg_recall:.1%}")
    print(f"  TROY rules: {len(troy_fps)} | ARTEMIS rules: {len(artemis_fps)} | "
          f"Matched: {len(matched)} | ARTEMIS extra: {len(unmatched_artemis)}")
    print("=" * 70)

    cur.close()
    conn.close()

    # ── JSON Report ─────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    report = {
        "timestamp": timestamp,
        "troy_path": args.troy,
        "artemis_path": args.artemis,
        "troy_rules": len(troy_fps),
        "artemis_rules": len(artemis_fps),
        "matched": len(matched),
        "unmatched_artemis": len(unmatched_artemis),
        "full": full,
        "partial": partial,
        "wrong": wrong,
        "missed": missed,
        "avg_recall": round(avg_recall, 4),
        "rules": [],
    }
    for troy_fp, artemis_group in matched:
        artemis_names = [t.rule_name for t in artemis_group]
        troy_ids = pool_concept_ids_for_rule(troy_fp, troy_json)
        artemis_ids = []
        for t_fp in artemis_group:
            artemis_ids.extend(pool_concept_ids_for_rule(t_fp, artemis_json))
        report["rules"].append({
            "troy_rule": troy_fp.rule_name,
            "artemis_rules": artemis_names,
            "is_demographic": troy_fp.is_demographic,
            "troy_seed_count": len(troy_ids),
            "artemis_seed_count": len(artemis_ids),
        })
    for fp in unmatched_troy:
        report["rules"].append({
            "troy_rule": fp.rule_name,
            "artemis_rules": [],
            "status": "MISSED",
        })

    os.makedirs(args.report_dir, exist_ok=True)
    report_path = os.path.join(args.report_dir, f"benchmark_v4_{timestamp}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Report saved: {report_path}")


if __name__ == "__main__":
    main()
