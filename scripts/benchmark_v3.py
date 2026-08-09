"""
Benchmark V3: Multi-Layer Evaluation for ARTEMIS Cohort Pipeline.
Compares ARTEMIS output against TROY reference using 3 layers:
  Layer 1: Static Sanity Check (validator)
  Layer 2: Semantic Fingerprinting (rule-level Jaccard)
  Layer 3: Concept Set Resolved Recall (V2 inherited)

NOT THE MEASURE OF RECORD (note added 2026-08-09). What this IS for: the historical
three-layer view (validator sanity, rule-level fingerprint Jaccard, concept recall) that
the later benchmarks were built from. What it is NOT: current. Its 1:1 sub-criteria
matching is superseded by benchmark_v4.py's parent-rule matching, and its concept
resolution predates the canonical Circe closure (direct items, descendants through
concept_ancestor filtered by invalid_reason IS NULL, isExcluded subtracted as an
anti-join), so its recall/precision are not comparable to current numbers.

Measure of record: per-eligibility-criterion 1:1 concept-set overlap against data/gold/,
macro-averaged -- scripts/conceptset_overlap_eval.py --mode closure (see AGENTS.md
EVALUATION).

Usage:
    conda run -n artemis python scripts/benchmark_v3.py
    conda run -n artemis python scripts/benchmark_v3.py --artemis output/leader/circe_cohort.json
"""
import json
import sys
import os
import re
from typing import Dict, Any, List, Set, Tuple, Optional
from dataclasses import dataclass, field

# ============================================================
# C-Hotfix Constants
# ============================================================
MEDICAL_STOPWORDS = {
    "history", "of", "the", "a", "and", "or", "with", "without",
    "disorder", "disease", "condition", "finding", "measurement",
    "procedure", "observation", "drug", "to", "in", "for", "on",
}

# Medical abbreviation aliases → expanded token sets
MEDICAL_ALIASES = {
    "tia": {"transient", "ischemic", "attack"},
    "tias": {"transient", "ischemic", "attack"},
    "pad": {"peripheral", "arterial", "disease"},
    "ckd": {"chronic", "kidney"},
    "esld": {"end", "stage", "liver"},
    "esrd": {"end", "stage", "renal"},
    "mi": {"myocardial", "infarction"},
    "chf": {"congestive", "heart", "failure"},
    "nyha": {"new", "york", "heart", "association"},
    "men2": {"multiple", "endocrine", "neoplasia", "type", "2"},
    "mtc": {"medullary", "thyroid", "carcinoma"},
    "fmtc": {"familial", "medullary", "thyroid", "carcinoma"},
    "glp1": {"glp", "1", "receptor", "agonist"},
    "dpp4": {"dpp", "4", "inhibitor"},
    "egfr": {"estimated", "glomerular", "filtration", "rate"},
    "hba1c": {"hemoglobin", "a1c"},
    "cv": {"cardiovascular"},
    "t1dm": {"type", "1", "diabetes", "mellitus"},
    "t2dm": {"type", "2", "diabetes", "mellitus"},
}

# Domain compatibility matrix for cross-domain matching
# (domain_a, domain_b) -> score_factor (1.0 = same, 0.0 = incompatible)
DOMAIN_COMPAT = {
    ("ConditionOccurrence", "ProcedureOccurrence"): 0.75,
    ("ProcedureOccurrence", "ConditionOccurrence"): 0.75,
    ("DrugExposure", "DrugEra"): 0.9,
    ("DrugEra", "DrugExposure"): 0.9,
    ("Measurement", "Observation"): 0.8,
    ("Observation", "Measurement"): 0.8,
}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

import psycopg2

# ============================================================
# Configuration
# ============================================================
TROY_PATH = "data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
ARTEMIS_PATH = "data/sample/LEADER/ARTEMIS_LEADER_design_paper_e2e.json"
DB_HOST = os.environ.get("OMOP_DB_HOST", "localhost")
DB_PORT = os.environ.get("OMOP_DB_PORT", "5432")
DB_NAME = os.environ.get("OMOP_DB_NAME", "postgres")
DB_USER = os.environ.get("OMOP_DB_USER", "postgres")
DB_PASS = os.environ.get("OMOP_DB_PASS", "mypass")
SCHEMA = os.environ.get("CDM_SCHEMA", "synthea23m")

# ============================================================
# Data Models
# ============================================================
@dataclass
class SemanticFingerprint:
    """Normalized representation of an InclusionRule for comparison."""
    rule_name: str
    criteria_type: str        # ConditionOccurrence, DrugExposure, etc.
    concept_set_name: str     # Name of referenced ConceptSet
    occurrence_type: str      # PRESENCE / ABSENCE
    window: str               # "-365:0" format
    is_demographic: bool = False

    @property
    def window_group(self) -> str:
        """Categorize temporal window into semantic groups.
        
        CIRCE convention: Coeff*Days produces positive values for 'before index'.
        e.g., Start.Coeff=-1, Start.Days=-365 → 365:0 means "365 days prior to index".
        So both 365:0 and -365:0 mean PRIOR.
        """
        if self.window == "ALL":
            return "ANY_TIME"
        try:
            parts = self.window.split(":")
            start = int(parts[0])
            end = int(parts[1])
            # PRIOR: any window ending at or before index date (end <= 0)
            # Both -365:0 and 365:0 are "prior" in CIRCE convention
            if end <= 0 and start != 0:
                return "PRIOR"
            # POST: window starting at or after index date
            elif start >= 0 and end > 0:
                return "POST"
            # INDEX: exactly at index date (0:0)
            elif start == 0 and end == 0:
                return "INDEX"
            else:
                return "OVERLAP"
        except (ValueError, IndexError):
            return "UNKNOWN"

    @property
    def key(self) -> str:
        """Normalized key for matching (case-insensitive, simplified)."""
        if self.is_demographic:
            return f"DEMO_{self._normalize(self.rule_name)}"
        return f"{self.criteria_type}_{self._normalize(self.concept_set_name)}_{self.occurrence_type}_{self.window_group}"
    
    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for fuzzy matching with medical stopword removal."""
        text = text.lower().strip()
        text = re.sub(r'\[.*?\]', '', text)     # Remove [TROY], [ARTEMIS] tags
        text = re.sub(r'\(.*?\)', '', text)     # Remove (LEADER), (TROY) etc.
        text = re.sub(r'[^\w\s]', '', text)
        words = [w for w in text.split() if w not in MEDICAL_STOPWORDS]
        return '_'.join(words) if words else text.replace(' ', '_')

    @staticmethod
    def _expand_tokens(text: str) -> set:
        """Expand normalized text tokens with medical alias resolution."""
        norm = SemanticFingerprint._normalize(text)
        tokens = set(norm.split('_'))
        tokens.discard('')
        expanded = set()
        for t in tokens:
            if t in MEDICAL_ALIASES:
                expanded.update(MEDICAL_ALIASES[t])
            else:
                expanded.add(t)
        return expanded

    def __repr__(self):
        if self.is_demographic:
            return f"DEMO({self.rule_name})"
        return f"{self.criteria_type}({self.concept_set_name}, {self.occurrence_type}, {self.window})"


@dataclass
class BenchmarkResult:
    """Full V3 benchmark result."""
    # Layer 1: Static Validation
    validation_errors: int = 0
    validation_warnings: int = 0
    validation_details: List[str] = field(default_factory=list)
    
    # Layer 2: Semantic Fingerprinting
    troy_fingerprints: List[SemanticFingerprint] = field(default_factory=list)
    artemis_fingerprints: List[SemanticFingerprint] = field(default_factory=list)
    matched_pairs: List[Tuple[SemanticFingerprint, SemanticFingerprint]] = field(default_factory=list)
    unmatched_troy: List[SemanticFingerprint] = field(default_factory=list)
    unmatched_artemis: List[SemanticFingerprint] = field(default_factory=list)
    fingerprint_jaccard: float = 0.0
    
    # Layer 3: Concept Set Recall
    concept_recalls: List[Dict[str, Any]] = field(default_factory=list)
    avg_concept_recall: float = 0.0


# ============================================================
# Layer 1: Static Sanity Check
# ============================================================
def run_static_validation(artemis_json: Dict[str, Any]) -> Tuple[int, int, List[str]]:
    """Run enhanced validator against ARTEMIS output."""
    details = []
    errors = 0
    warnings = 0
    
    # 1. CodesetId=0 scan
    def scan_codeset_zero(node, path=""):
        nonlocal errors
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "CodesetId" and v == 0:
                    details.append(f"❌ Unmapped CodesetId=0 at {path}")
                    errors += 1
                scan_codeset_zero(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                scan_codeset_zero(item, f"{path}[{i}]")
    
    scan_codeset_zero(artemis_json)
    
    # 2. Domain consistency check
    DEMOGRAPHIC_NAMES = {"age", "gender", "sex", "race", "ethnicity"}
    for i, rule in enumerate(artemis_json.get("InclusionRules", [])):
        rule_name = rule.get("name", "").lower()
        expr = rule.get("expression", {})
        cl = expr.get("CriteriaList", [])
        dl = expr.get("DemographicCriteriaList", [])
        
        first_word = rule_name.split()[0] if rule_name.split() else ""
        if first_word in DEMOGRAPHIC_NAMES and cl and not dl:
            details.append(f"⚠ Rule [{i}] '{rule.get('name','')}' looks demographic but uses CriteriaList")
            warnings += 1
        
        groups = expr.get("Groups", [])
        if not cl and not dl and not groups:
            details.append(f"❌ Rule [{i}] '{rule.get('name','')}' has empty criteria")
            errors += 1
    
    # 3. ConceptSet reference integrity
    valid_ids = {cs.get("id") for cs in artemis_json.get("ConceptSets", [])}
    for i, rule in enumerate(artemis_json.get("InclusionRules", [])):
        expr = rule.get("expression", {})
        for j, crit in enumerate(expr.get("CriteriaList", [])):
            criteria_obj = crit.get("Criteria", {})
            for domain_type, data in criteria_obj.items():
                if isinstance(data, dict):
                    csid = data.get("CodesetId")
                    if csid is not None and csid not in valid_ids and csid != 0:
                        details.append(f"❌ Rule [{i}] references undefined CodesetId={csid}")
                        errors += 1
    
    return errors, warnings, details


# ============================================================
# Layer 2: Semantic Fingerprinting
# ============================================================
def extract_fingerprints(
    circe_json: Dict[str, Any],
    label: str = ""
) -> List[SemanticFingerprint]:
    """Extract semantic fingerprints from all InclusionRules."""
    concept_set_map = {}
    for cs in circe_json.get("ConceptSets", []):
        name = re.sub(r'\[TROY\]\s*', '', cs["name"])  # Strip [TROY] tag
        concept_set_map[cs["id"]] = name
    
    fingerprints = []
    
    for rule in circe_json.get("InclusionRules", []):
        rule_name = rule.get("name", "")
        expr = rule.get("expression", {})
        criteria_list = expr.get("CriteriaList", [])
        demo_list = expr.get("DemographicCriteriaList", [])
        
        # Handle demographic criteria
        if demo_list:
            fingerprints.append(SemanticFingerprint(
                rule_name=rule_name,
                criteria_type="DemographicCriteria",
                concept_set_name="",
                occurrence_type="PRESENCE",
                window="ALL",
                is_demographic=True
            ))
        
        # Handle regular criteria
        for crit in criteria_list:
            criteria_obj = crit.get("Criteria", {})
            occ = crit.get("Occurrence", {})
            occ_type = "ABSENCE" if occ.get("Type", 2) == 0 else "PRESENCE"
            
            # Extract window
            sw = crit.get("StartWindow", {})
            start_days = sw.get("Start", {}).get("Days", 365)
            start_coeff = sw.get("Start", {}).get("Coeff", -1)
            end_days = sw.get("End", {}).get("Days", 0)
            end_coeff = sw.get("End", {}).get("Coeff", 1)
            window_str = f"{start_coeff * start_days}:{end_coeff * end_days}"
            
            for domain_type, domain_data in criteria_obj.items():
                if isinstance(domain_data, dict):
                    csid = domain_data.get("CodesetId", -1)
                    cs_name = concept_set_map.get(csid, f"UNMAPPED({csid})")
                    
                    fingerprints.append(SemanticFingerprint(
                        rule_name=rule_name,
                        criteria_type=domain_type,
                        concept_set_name=cs_name,
                        occurrence_type=occ_type,
                        window=window_str,
                    ))
        
        # Handle Groups recursively
        for group in expr.get("Groups", []):
            sub_fingerprints = _extract_group_fingerprints(group, rule_name, concept_set_map)
            fingerprints.extend(sub_fingerprints)
    
    return fingerprints


def _extract_group_fingerprints(
    group: Dict[str, Any],
    rule_name: str,
    concept_set_map: Dict[int, str]
) -> List[SemanticFingerprint]:
    """Extract fingerprints from nested Groups."""
    fps = []
    for crit in group.get("CriteriaList", []):
        criteria_obj = crit.get("Criteria", {})
        occ = crit.get("Occurrence", {})
        occ_type = "ABSENCE" if occ.get("Type", 2) == 0 else "PRESENCE"
        sw = crit.get("StartWindow", {})
        start_days = sw.get("Start", {}).get("Days", 365)
        start_coeff = sw.get("Start", {}).get("Coeff", -1)
        end_days = sw.get("End", {}).get("Days", 0)
        end_coeff = sw.get("End", {}).get("Coeff", 1)
        window_str = f"{start_coeff * start_days}:{end_coeff * end_days}"
        
        for domain_type, domain_data in criteria_obj.items():
            if isinstance(domain_data, dict):
                csid = domain_data.get("CodesetId", -1)
                cs_name = concept_set_map.get(csid, f"UNMAPPED({csid})")
                fps.append(SemanticFingerprint(
                    rule_name=rule_name,
                    criteria_type=domain_type,
                    concept_set_name=cs_name,
                    occurrence_type=occ_type,
                    window=window_str,
                ))
    
    for sub_group in group.get("Groups", []):
        fps.extend(_extract_group_fingerprints(sub_group, rule_name, concept_set_map))
    
    return fps


def match_fingerprints(
    troy_fps: List[SemanticFingerprint],
    artemis_fps: List[SemanticFingerprint]
) -> Tuple[List[Tuple], List[SemanticFingerprint], List[SemanticFingerprint]]:
    """Match TROY to ARTEMIS using Global Greedy Strategy (best score first)."""
    edges = []  # (score, troy_idx, artemis_idx)
    
    # 1. Calculate all potential pairwise scores
    for i, troy in enumerate(troy_fps):
        for j, artemis in enumerate(artemis_fps):
            score = 0.0
            
            # A. Exact Key Match (includes window_group + occurrence_type)
            if troy.key == artemis.key:
                score = 1.0
            
            # B. Fuzzy Match: allow cross-domain with penalty
            else:
                # Domain compatibility check
                if troy.criteria_type == artemis.criteria_type:
                    domain_factor = 1.0
                else:
                    domain_factor = DOMAIN_COMPAT.get(
                        (troy.criteria_type, artemis.criteria_type), 0.0)
                
                if domain_factor > 0:
                    # Expanded tokens with alias resolution
                    t_words = SemanticFingerprint._expand_tokens(troy.concept_set_name)
                    l_words = SemanticFingerprint._expand_tokens(artemis.concept_set_name)
                    
                    if t_words and l_words:
                        intersect = len(t_words & l_words)
                        union = len(t_words | l_words)
                        jaccard = intersect / union
                        
                        # Token subset match: if smaller ⊆ larger, high confidence
                        smaller, larger = (t_words, l_words) if len(t_words) <= len(l_words) else (l_words, t_words)
                        is_subset = smaller.issubset(larger)
                        
                        if jaccard > 0.3 or is_subset:
                            base_score = max(jaccard, 0.6 if is_subset else 0.0)
                            # Bonus for matching occurrence_type
                            occ_bonus = 0.1 if troy.occurrence_type == artemis.occurrence_type else 0.0
                            score = base_score * 0.9 * domain_factor + occ_bonus
            
            if score > 0:
                edges.append((score, i, j))
    
    # 2. Sort edges by score descending (Global Greedy)
    edges.sort(key=lambda x: x[0], reverse=True)
    
    # 3. Select best matches (1:1)
    matched = []
    troy_used = set()
    artemis_used = set()
    
    for score, i, j in edges:
        if i not in troy_used and j not in artemis_used:
            matched.append((troy_fps[i], artemis_fps[j]))
            troy_used.add(i)
            artemis_used.add(j)
    
    unmatched_troy = [fp for i, fp in enumerate(troy_fps) if i not in troy_used]
    unmatched_artemis = [fp for i, fp in enumerate(artemis_fps) if i not in artemis_used]
    
    return matched, unmatched_troy, unmatched_artemis


def fingerprint_jaccard(troy_fps: List[SemanticFingerprint], 
                        artemis_fps: List[SemanticFingerprint]) -> float:
    """Jaccard similarity on fingerprint key sets."""
    troy_keys = {fp.key for fp in troy_fps}
    artemis_keys = {fp.key for fp in artemis_fps}
    if not troy_keys and not artemis_keys:
        return 1.0
    if not troy_keys or not artemis_keys:
        return 0.0
    return len(troy_keys & artemis_keys) / len(troy_keys | artemis_keys)


# ============================================================
# Layer 3: Concept Set Resolved Recall (V2 inherited)
# ============================================================
def get_db_connection():
    """Get PostgreSQL connection."""
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS
    )


def resolve_concept_set(cur, concept_ids: list, include_descendants: bool = True) -> set:
    """Resolve concept set via CONCEPT_ANCESTOR (same as V2)."""
    if not concept_ids:
        return set()
    resolved = set(concept_ids)
    if include_descendants and concept_ids:
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


def extract_concept_ids_from_concept_set(cs: Dict[str, Any]) -> List[int]:
    """Extract concept IDs from a ConceptSet expression."""
    items = cs.get("expression", {}).get("items", [])
    return [item["concept"]["CONCEPT_ID"] for item in items if "concept" in item]


def compare_concept_sets(
    troy_json: Dict[str, Any],
    artemis_json: Dict[str, Any],
    matched_pairs: List[Tuple[SemanticFingerprint, SemanticFingerprint]],
    unmatched_troy_fps: List[SemanticFingerprint],
    cur
) -> List[Dict[str, Any]]:
    """Compare concept sets for matched rule pairs + count unmatched as recall=0."""
    # Build concept set name → concept IDs maps
    troy_cs_map = {}
    for cs in troy_json.get("ConceptSets", []):
        name = re.sub(r'\[TROY\]\s*', '', cs["name"]).lower()
        troy_cs_map[name] = extract_concept_ids_from_concept_set(cs)
    
    artemis_cs_map = {}
    for cs in artemis_json.get("ConceptSets", []):
        artemis_cs_map[cs["name"].lower()] = extract_concept_ids_from_concept_set(cs)
    
    results = []
    
    # 1. Matched pairs
    for troy_fp, artemis_fp in matched_pairs:
        if troy_fp.is_demographic:
            results.append({
                "troy_rule": troy_fp.rule_name,
                "artemis_rule": artemis_fp.rule_name,
                "type": "demographic",
                "recall": 1.0,
                "match": "DEMO"
            })
            continue
        
        troy_cs_name = troy_fp.concept_set_name.lower()
        artemis_cs_name = artemis_fp.concept_set_name.lower()
        
        troy_ids = troy_cs_map.get(troy_cs_name, [])
        artemis_ids = artemis_cs_map.get(artemis_cs_name, [])
        
        if not troy_ids:
            results.append({
                "troy_rule": troy_fp.rule_name,
                "artemis_rule": artemis_fp.rule_name,
                "troy_cs": troy_fp.concept_set_name,
                "artemis_cs": artemis_fp.concept_set_name,
                "type": "concept_set",
                "recall": 0.0,
                "match": "TROY_CS_EMPTY"
            })
            continue
        
        # Resolve both concept sets
        troy_resolved = resolve_concept_set(cur, troy_ids)
        artemis_resolved = resolve_concept_set(cur, artemis_ids) if artemis_ids else set()
        
        recall = len(troy_resolved & artemis_resolved) / len(troy_resolved) if troy_resolved else 1.0
        jaccard = len(troy_resolved & artemis_resolved) / len(troy_resolved | artemis_resolved) if (troy_resolved | artemis_resolved) else 1.0
        
        results.append({
            "troy_rule": troy_fp.rule_name,
            "artemis_rule": artemis_fp.rule_name,
            "troy_cs": troy_fp.concept_set_name,
            "artemis_cs": artemis_fp.concept_set_name,
            "type": "concept_set",
            "troy_resolved_count": len(troy_resolved),
            "artemis_resolved_count": len(artemis_resolved),
            "recall": recall,
            "jaccard": jaccard,
            "match": "Full" if recall >= 0.9 else ("Partial" if recall >= 0.3 else "Wrong")
        })
    
    # 2. Unmatched TROY rules → recall=0 (C-Hotfix: fix denominator)
    for troy_fp in unmatched_troy_fps:
        if troy_fp.is_demographic:
            continue
        
        troy_cs_name = troy_fp.concept_set_name.lower()
        troy_ids = troy_cs_map.get(troy_cs_name, [])
        troy_resolved_count = 0
        if troy_ids:
            troy_resolved = resolve_concept_set(cur, troy_ids)
            troy_resolved_count = len(troy_resolved)
        
        results.append({
            "troy_rule": troy_fp.rule_name,
            "artemis_rule": "UNMATCHED",
            "troy_cs": troy_fp.concept_set_name,
            "artemis_cs": "—",
            "type": "concept_set",
            "troy_resolved_count": troy_resolved_count,
            "artemis_resolved_count": 0,
            "recall": 0.0,
            "jaccard": 0.0,
            "match": "Missed"
        })
    
    return results


# ============================================================
# Report
# ============================================================
def print_report(result: BenchmarkResult):
    """Print formatted benchmark V3 report."""
    print()
    print("=" * 65)
    print("        BENCHMARK V3 REPORT — ARTEMIS vs TROY (LEADER)")
    print("=" * 65)
    
    # Layer 1
    print()
    print("📋 Layer 1: Static Sanity Check")
    print("-" * 40)
    if result.validation_errors == 0 and result.validation_warnings == 0:
        print("  ✅ All checks passed")
    else:
        print(f"  Errors: {result.validation_errors}, Warnings: {result.validation_warnings}")
        for d in result.validation_details:
            print(f"  {d}")
    
    # Layer 2
    print()
    print("🔑 Layer 2: Semantic Fingerprinting")
    print("-" * 40)
    print(f"  TROY fingerprints:  {len(result.troy_fingerprints)}")
    print(f"  ARTEMIS fingerprints: {len(result.artemis_fingerprints)}")
    print(f"  Matched pairs:      {len(result.matched_pairs)}")
    print(f"  Fingerprint Jaccard: {result.fingerprint_jaccard:.1%}")
    
    if result.matched_pairs:
        print()
        print("  Matched Rules:")
        for troy_fp, artemis_fp in result.matched_pairs:
            print(f"    ✅ TROY: {troy_fp.rule_name}")
            print(f"       → ARTEMIS: {artemis_fp.rule_name}")
            print(f"         [{troy_fp}] ↔ [{artemis_fp}]")
    
    if result.unmatched_troy:
        print()
        print(f"  Unmatched TROY rules ({len(result.unmatched_troy)}):")
        for fp in result.unmatched_troy:
            print(f"    ❌ {fp.rule_name}: {fp}")
    
    if result.unmatched_artemis:
        print()
        print(f"  Unmatched ARTEMIS rules ({len(result.unmatched_artemis)}):")
        for fp in result.unmatched_artemis:
            print(f"    ❓ {fp.rule_name}: {fp}")
    
    # Layer 3
    print()
    print("📊 Layer 3: Concept Set Recall (Resolved)")
    print("-" * 40)
    if result.concept_recalls:
        for cr in result.concept_recalls:
            status = "✅" if cr.get("match") in ("Full", "DEMO") else ("🔶" if cr.get("match") == "Partial" else "❌")
            if cr.get("type") == "demographic":
                print(f"  {status} {cr['troy_rule']}: [Demographic — N/A]")
            else:
                print(f"  {status} {cr['troy_rule']}: Recall={cr['recall']:.0%}")
                if cr.get("troy_resolved_count"):
                    print(f"      TROY={cr['troy_resolved_count']} concepts, ARTEMIS={cr.get('artemis_resolved_count', 0)} concepts")
                    print(f"      CS: {cr['troy_cs']} ↔ {cr['artemis_cs']}")
        
        print()
        print(f"  Average Concept Recall: {result.avg_concept_recall:.1%}")
    
    # Summary
    print()
    print("=" * 65)
    full = sum(1 for cr in result.concept_recalls if cr.get("match") in ("Full", "DEMO"))
    partial = sum(1 for cr in result.concept_recalls if cr.get("match") == "Partial")
    wrong = sum(1 for cr in result.concept_recalls if cr.get("match") == "Wrong")
    missed = sum(1 for cr in result.concept_recalls if cr.get("match") == "Missed")
    
    print(f"  SUMMARY: FP Jaccard={result.fingerprint_jaccard:.1%} | "
          f"Full={full} | Partial={partial} | Wrong={wrong} | Missed={missed} | "
          f"Avg Recall={result.avg_concept_recall:.1%}")
    print(f"  Validation: {result.validation_errors} errors, {result.validation_warnings} warnings")
    print("=" * 65)


# ============================================================
# Main
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark V3: ARTEMIS vs TROY")
    parser.add_argument("--troy", default=TROY_PATH, help="Path to TROY reference JSON")
    parser.add_argument("--artemis", default=ARTEMIS_PATH, help="Path to ARTEMIS output JSON")
    args = parser.parse_args()
    
    # Load JSONs
    with open(args.troy) as f:
        troy_json = json.load(f)
    with open(args.artemis) as f:
        artemis_json = json.load(f)
    
    print(f"Loaded TROY: {len(troy_json.get('ConceptSets', []))} CS, "
          f"{len(troy_json.get('InclusionRules', []))} rules")
    print(f"Loaded ARTEMIS: {len(artemis_json.get('ConceptSets', []))} CS, "
          f"{len(artemis_json.get('InclusionRules', []))} rules")
    
    result = BenchmarkResult()
    
    # Layer 1: Static Validation
    errs, warns, details = run_static_validation(artemis_json)
    result.validation_errors = errs
    result.validation_warnings = warns
    result.validation_details = details
    
    # Layer 2: Semantic Fingerprinting
    troy_fps = extract_fingerprints(troy_json, "TROY")
    artemis_fps = extract_fingerprints(artemis_json, "ARTEMIS")
    result.troy_fingerprints = troy_fps
    result.artemis_fingerprints = artemis_fps
    
    matched, unmatched_troy, unmatched_artemis = match_fingerprints(troy_fps, artemis_fps)
    result.matched_pairs = matched
    result.unmatched_troy = unmatched_troy
    result.unmatched_artemis = unmatched_artemis
    result.fingerprint_jaccard = fingerprint_jaccard(troy_fps, artemis_fps)
    
    # Layer 3: Concept Set Recall
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        recalls = compare_concept_sets(troy_json, artemis_json, matched, unmatched_troy, cur)
        result.concept_recalls = recalls
        
        concept_recall_values = [cr["recall"] for cr in recalls if cr["type"] == "concept_set"]
        result.avg_concept_recall = (
            sum(concept_recall_values) / len(concept_recall_values) 
            if concept_recall_values else 0.0
        )
    finally:
        cur.close()
        conn.close()
    
    # Print report
    print_report(result)


if __name__ == "__main__":
    main()
