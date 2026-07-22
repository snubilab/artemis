import argparse
import functools
import json
import math
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_DIR = Path(__file__).resolve().parents[2]
SYNTHEA_MODULES_DIR = REPO_DIR / "data" / "synthea" / "synthea" / "src" / "main" / "resources" / "modules"

SYSTEM_CODE_MAP = {
    "SNOMED": "SNOMED-CT",
    "SNOMEDCT": "SNOMED-CT",
    "RxNorm": "RxNorm",
    "LOINC": "LOINC",
}

FALLBACK_SYNTHEA_CODE_OVERRIDES: Dict[tuple[str, str], Dict[str, str]] = {}

# Synthea can only emit Condition/Medication/Observation states during an
# encounter, so generated timelines need a default encounter code container.
ENCOUNTER_CODE = {
    "system": "SNOMED-CT",
    "code": "185349003",
    "display": "Encounter for check up (procedure)",
}

ENCOUNTER_CLASS_BY_VISIT_TYPE = {
    "IP": "inpatient",
    "ER": "emergency",
    "EMER": "emergency",
    "AMB": "ambulatory",
    "OP": "outpatient",
    "HH": "home",
    "VR": "virtual",
}

LEAF_CRITERION_TYPES = (
    "ConditionOccurrence",
    "ProcedureOccurrence",
    "DeviceExposure",
    "Measurement",
    "DrugExposure",
    "Observation",
)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_operator(op: Any) -> str:
    if op is None:
        return "EQ"

    if isinstance(op, dict):
        op = op.get("CONCEPT_CODE") or op.get("CONCEPT_NAME") or op.get("name")

    raw = str(op).strip().upper().replace(" ", "").replace("-", "")
    if not raw:
        return "EQ"

    # Common OHDSI/Atlas comparator patterns
    if raw in {"=", "EQ", "EQUAL", "EQUALS", "EQUALTO", "EXACTMATCH"}:
        return "EQ"
    if raw in {"GE", "GTE", "GREATEROREQUAL", "GREATERTHANOREQUALTO", "GEQ", ">="}:
        return "GE"
    if raw in {"GT", "GREATERTHAN", "GREATER", ">"}:
        return "GT"
    if raw in {"LE", "LTE", "LESSOREQUAL", "LESSOREQUALTO", "<="}:
        return "LE"
    if raw in {"LT", "LESSTHAN", "LESS", "<"}:
        return "LT"
    if raw in {"NE", "NEQ", "NOT", "NOTEQUAL", "NOTEQUALTO", "NEQUAL"}:
        return "NE"

    return raw


def get_codes_for_codeset(gold_json: Dict[str, Any], codeset_id: Any) -> List[Dict[str, str]]:
    """Return de-duplicated Gold code entries for a ConceptSet."""
    if codeset_id is None:
        return []

    target = str(codeset_id)
    for cs in gold_json.get("ConceptSets", []):
        if str(cs.get("id", "")) != target:
            continue

        codes: List[Dict[str, str]] = []
        seen = set()
        for item in cs.get("expression", {}).get("items", []):
            concept = item.get("concept", {})
            code = concept.get("CONCEPT_CODE")
            vocab = concept.get("VOCABULARY_ID", "")
            if code is None:
                continue

            code_obj = {
                "system": SYSTEM_CODE_MAP.get(vocab, vocab),
                "code": str(code),
                "display": concept.get("CONCEPT_NAME"),
            }

            key = (code_obj["system"], code_obj["code"])
            if key in seen:
                continue
            seen.add(key)
            codes.append(code_obj)

        return codes

    return []


def get_synthea_codes_for_codeset(gold_json: Dict[str, Any], codeset_id: Any) -> List[Dict[str, str]]:
    """Return Gold codes lowered to Synthea-emittable codes when needed."""
    lowered: List[Dict[str, str]] = []
    for code_obj in get_codes_for_codeset(gold_json, codeset_id):
        lowered.append(lower_code_for_synthea(code_obj))
    return lowered


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


@functools.lru_cache(maxsize=1)
def load_synthea_rxnorm_catalog() -> List[Dict[str, str]]:
    catalog: List[Dict[str, str]] = []
    if not SYNTHEA_MODULES_DIR.exists():
        return catalog

    for module_path in SYNTHEA_MODULES_DIR.rglob("*.json"):
        if module_path.name.startswith("artemis_"):
            continue
        try:
            payload = json.loads(module_path.read_text())
        except Exception:
            continue

        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                if (
                    current.get("system") == "RxNorm"
                    and "code" in current
                    and "display" in current
                ):
                    catalog.append(
                        {
                            "system": "RxNorm",
                            "code": str(current["code"]),
                            "display": str(current.get("display") or ""),
                        }
                    )
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)

    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in catalog:
        key = (item["system"], item["code"], item["display"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _synthea_candidate_score(gold_code: Dict[str, str], candidate: Dict[str, str]) -> tuple[int, int, int]:
    gold_display = _normalize_text(gold_code.get("display"))
    candidate_display = _normalize_text(candidate.get("display"))
    gold_tokens = set(gold_display.split())
    candidate_tokens = set(candidate_display.split())
    overlap = len(gold_tokens & candidate_tokens)
    starts_with = 1 if gold_display and candidate_display.startswith(gold_display) else 0
    preferred_shape = 1 if "oral tablet" in candidate_display else 0
    return (overlap, starts_with, preferred_shape)


def lower_code_for_synthea(code_obj: Dict[str, str]) -> Dict[str, str]:
    if code_obj.get("system") != "RxNorm":
        return code_obj

    catalog = load_synthea_rxnorm_catalog()
    if any(item["code"] == code_obj["code"] for item in catalog):
        return code_obj

    normalized_display = _normalize_text(code_obj.get("display"))
    candidates = [
        item for item in catalog
        if normalized_display and normalized_display in _normalize_text(item.get("display"))
    ]
    if candidates:
        candidates.sort(
            key=lambda item: (
                _synthea_candidate_score(code_obj, item),
                item["code"],
            ),
            reverse=True,
        )
        return candidates[0]

    key = (code_obj["system"], code_obj["code"])
    return FALLBACK_SYNTHEA_CODE_OVERRIDES.get(key, code_obj)


def _parse_numeric_value_box(node: Dict[str, Any]) -> Dict[str, Any]:
    value_box = node.get("ValueAsNumber")
    if not isinstance(value_box, dict):
        return {}

    value = _to_float(value_box.get("Value"))
    if value is None:
        return {}

    op = _normalize_operator(
        value_box.get("Op")
        or value_box.get("Operator")
        or value_box.get("Comparator")
        or value_box.get("Comparator_")
        or value_box.get("comparison")
        or value_box.get("comparisonOperator")
    )

    unit = value_box.get("Unit")
    if not unit:
        unit = (
            value_box.get("UnitConcept", {}).get("CONCEPT_CODE")
            if isinstance(value_box.get("UnitConcept"), dict)
            else None
        )
        if not unit:
            unit = value_box.get("Units")

    if op == "GT":
        value = value + 0.1
    elif op == "LT":
        value = max(0.0, value - 0.1)

    return {"value": value, "value_operator": op, "value_unit": unit}


def _parse_age_criterion(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    age = node.get("Age")
    if not isinstance(age, dict):
        return None

    value = _to_float(age.get("Value"))
    if value is None:
        return None

    op = _normalize_operator(age.get("Operator") or age.get("Op") or age.get("Comparator"))
    req: Dict[str, Any] = {"type": "Age", "operator": op, "value": value}

    # If we can derive a minimum age, enforce minimum delay.
    if op in {"GE", "GT"}:
        req["min_age"] = value if op == "GE" else value + 0.1
    elif op in {"LE", "LT"}:
        req["max_age"] = value if op == "LE" else value - 0.1
    else:
        # Exact/unknown comparator -> use as minimum age for a safe lower bound
        req["min_age"] = value

    return req


def _extract_min_days_from_era_length(node: Dict[str, Any]) -> Optional[int]:
    era_length = node.get("EraLength")
    if not isinstance(era_length, dict):
        return None

    value = _to_float(era_length.get("Value"))
    if value is None:
        return None

    op = _normalize_operator(
        era_length.get("Op")
        or era_length.get("Operator")
        or era_length.get("Comparator")
    )
    if op == "GT":
        return int(math.floor(value)) + 1
    if op in {"GE", "EQ"}:
        return int(math.ceil(value))
    return None


def _extract_min_age_from_domain_age(node: Dict[str, Any]) -> Optional[float]:
    age = node.get("AgeAtStart")
    if not isinstance(age, dict):
        return None

    value = _to_float(age.get("Value"))
    if value is None:
        return None

    op = _normalize_operator(
        age.get("Op")
        or age.get("Operator")
        or age.get("Comparator")
    )
    if op == "GT":
        return value + 0.1
    if op in {"GE", "EQ"}:
        return value
    return None


def _extract_children(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    children: List[Dict[str, Any]] = []
    for key in ("CriteriaList", "Groups"):
        for item in node.get(key, []) if isinstance(node.get(key, []), list) else []:
            if isinstance(item, dict):
                children.append(item)
    return children


def _leaf_criterion_node(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if "Criteria" in node and isinstance(node.get("Criteria"), dict):
        criteria = node["Criteria"]
        if any(key in criteria for key in LEAF_CRITERION_TYPES):
            return criteria
    if any(key in node for key in LEAF_CRITERION_TYPES):
        return node
    return None


def _extract_wrapper_metadata(node: Dict[str, Any]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}

    occurrence = node.get("Occurrence")
    if isinstance(occurrence, dict):
        if "Type" in occurrence:
            metadata["occurrence_type"] = occurrence.get("Type")
        if "Count" in occurrence:
            metadata["occurrence_count"] = occurrence.get("Count")

    start_window = node.get("StartWindow")
    if isinstance(start_window, dict):
        start = start_window.get("Start") if isinstance(start_window.get("Start"), dict) else {}
        end = start_window.get("End") if isinstance(start_window.get("End"), dict) else {}
        if "Days" in start:
            metadata["start_days"] = start.get("Days")
        if "Coeff" in start:
            metadata["start_coeff"] = start.get("Coeff")
        if "Days" in end:
            metadata["end_days"] = end.get("Days")
        if "Coeff" in end:
            metadata["end_coeff"] = end.get("Coeff")
        if "UseEventEnd" in start_window:
            metadata["use_event_end"] = start_window.get("UseEventEnd")

    end_window = node.get("EndWindow")
    if isinstance(end_window, dict):
        start = end_window.get("Start") if isinstance(end_window.get("Start"), dict) else {}
        end = end_window.get("End") if isinstance(end_window.get("End"), dict) else {}
        if "Days" in start:
            metadata["event_end_start_days"] = start.get("Days")
        if "Coeff" in start:
            metadata["event_end_start_coeff"] = start.get("Coeff")
        if "Days" in end:
            metadata["event_end_end_days"] = end.get("Days")
        if "Coeff" in end:
            metadata["event_end_end_coeff"] = end.get("Coeff")
        if "UseEventEnd" in end_window:
            metadata["event_end_use_event_end"] = end_window.get("UseEventEnd")
        if "UseIndexEnd" in end_window:
            metadata["use_index_end"] = end_window.get("UseIndexEnd")

    leaf_node = _leaf_criterion_node(node)
    if leaf_node:
        for domain_key in LEAF_CRITERION_TYPES:
            domain = leaf_node.get(domain_key)
            if not isinstance(domain, dict):
                continue
            visit_types = domain.get("VisitType")
            if isinstance(visit_types, list) and visit_types:
                metadata["visit_types"] = [
                    vt.get("CONCEPT_CODE") or vt.get("CONCEPT_NAME") or str(vt)
                    for vt in visit_types
                ]
            range_high_ratio = domain.get("RangeHighRatio")
            if isinstance(range_high_ratio, dict):
                metadata["range_high_ratio"] = {
                    "value": range_high_ratio.get("Value"),
                    "operator": _normalize_operator(
                        range_high_ratio.get("Op")
                        or range_high_ratio.get("Operator")
                        or range_high_ratio.get("Comparator")
                    ),
                }
            break

    return metadata


def _build_requirement(
    req_type: str,
    codeset_id: Any,
    metadata: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    req: Dict[str, Any] = {"type": req_type, "codeset_id": codeset_id}
    if metadata:
        for key, value in metadata.items():
            req[key] = value
    if extra:
        req.update(extra)
    return req


def _path_signature(path: List[Dict[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted(json.dumps(req, sort_keys=True) for req in path))


def _dedupe_requirement_paths(paths: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
    deduped: List[List[Dict[str, Any]]] = []
    seen = set()
    for path in paths:
        signature = _path_signature(path)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(path)
    return deduped


def _combine_requirement_path_sets(
    path_sets: List[List[List[Dict[str, Any]]]],
) -> List[List[Dict[str, Any]]]:
    combinations: List[List[Dict[str, Any]]] = [[]]
    for paths in path_sets:
        next_combinations: List[List[Dict[str, Any]]] = []
        for combo in combinations:
            for path in paths:
                next_combinations.append(combo + path)
        combinations = next_combinations
    return _dedupe_requirement_paths(combinations)


def _select_requirement_path(
    paths: List[List[Dict[str, Any]]],
    or_strategy: str,
    rng: random.Random,
) -> List[Dict[str, Any]]:
    if not paths:
        return []
    if or_strategy == "random":
        return list(paths[rng.randrange(len(paths))])
    return list(paths[0])


def _choose_branches(
    branches: List[Dict[str, Any]],
    count: int,
    strategy: str,
    rng: random.Random,
) -> List[int]:
    """
    For ANY / AT_LEAST with count:
    - strategy='first' -> deterministic branch selection (first N branches)
    - strategy='random' -> random branch selection (single branch for ANY; k branches for AT_LEAST)
    """
    if not branches or count <= 0:
        return []

    count = min(count, len(branches))
    if strategy == "random":
        chosen = rng.sample(range(len(branches)), count)
        chosen.sort()
        return chosen

    # deterministic strategy
    return list(range(count))


def _is_exclusion_criterion(criterion_wrapper: Dict[str, Any]) -> bool:
    """Check if a criterion wrapper has Occurrence.Type=0, Count=0 (= exclusion)."""
    occ = criterion_wrapper.get("Occurrence", {})
    return occ.get("Type") == 0 and occ.get("Count", 0) == 0


def _has_value_constraint(criterion_wrapper: Dict[str, Any]) -> bool:
    """Check if a criterion has a numeric value constraint (ValueAsNumber)."""
    crit = criterion_wrapper.get("Criteria", {})
    for domain_key in ("Measurement", "Observation"):
        domain = crit.get(domain_key, {})
        if isinstance(domain, dict) and isinstance(domain.get("ValueAsNumber"), dict):
            return True
    return False


def _negate_operator(op: str) -> str:
    """Negate a comparison operator for inverted inclusion rules."""
    negation_map = {
        "LT": "GE", "LE": "GT", "GT": "LE", "GE": "LT",
        "EQ": "NE", "NE": "EQ",
    }
    return negation_map.get(op, op)


def _classify_rule(rule_node: Dict[str, Any]) -> str:
    """
    Classify an InclusionRule as:
    - 'POSITIVE': at least one criterion has Occurrence.Type >= 1 (generate events)
    - 'INVERTED': all criteria are OccType=0 but have value constraints (negate values)
    - 'EXCLUSION': all criteria are OccType=0 with no value constraints (skip entirely)
    - 'DEMOGRAPHIC': only demographic criteria (age, gender, etc.)
    """
    expression = rule_node.get("expression", {})
    stats = _collect_rule_stats(expression)

    if stats["has_positive"]:
        return "POSITIVE"
    if stats["has_value_constraint"]:
        return "INVERTED"
    if stats["has_demographic"]:
        return "DEMOGRAPHIC"
    return "EXCLUSION"


def _collect_rule_stats(node: Any) -> Dict[str, bool]:
    stats = {
        "has_positive": False,
        "has_value_constraint": False,
        "has_demographic": False,
        "has_exclusion": False,
    }
    if not isinstance(node, dict):
        return stats

    age_req = _parse_age_criterion(node)
    if age_req:
        stats["has_demographic"] = True
        return stats

    leaf_node = _leaf_criterion_node(node)
    if leaf_node is not None:
        occurrence = node.get("Occurrence", {}) if "Criteria" in node else {}
        if _has_value_constraint(node if "Criteria" in node else {"Criteria": leaf_node}):
            stats["has_value_constraint"] = True
        if not occurrence:
            stats["has_positive"] = True
        elif _is_exclusion_criterion(node):
            stats["has_exclusion"] = True
        elif occurrence.get("Type", 0) >= 1:
            stats["has_positive"] = True
        return stats

    for demo in node.get("DemographicCriteriaList", []):
        child_stats = _collect_rule_stats(demo)
        for key, value in child_stats.items():
            stats[key] = stats[key] or value

    for child in _extract_children(node):
        child_stats = _collect_rule_stats(child)
        for key, value in child_stats.items():
            stats[key] = stats[key] or value

    return stats


def _extract_requirements_from_node(
    node: Any,
    or_strategy: str,
    rng: random.Random,
) -> List[Dict[str, Any]]:
    paths = _extract_requirement_paths_from_node(node)
    return _select_requirement_path(paths, or_strategy, rng)


def _extract_requirements_from_leaf(
    node: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    or_strategy: str = "first",
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    rng = rng or random.Random()
    paths = _extract_requirement_paths_from_leaf(node, metadata)
    return _select_requirement_path(paths, or_strategy, rng)


def _extract_requirement_paths_from_node(node: Any) -> List[List[Dict[str, Any]]]:
    if not isinstance(node, dict):
        return [[]]

    age_req = _parse_age_criterion(node)
    if age_req:
        return [[age_req]]

    leaf_node = _leaf_criterion_node(node)
    if leaf_node is not None:
        metadata = _extract_wrapper_metadata(node)
        return _extract_requirement_paths_from_leaf(leaf_node, metadata)

    child_path_sets: List[List[List[Dict[str, Any]]]] = []
    for demo in node.get("DemographicCriteriaList", []):
        if isinstance(demo, dict):
            child_path_sets.append(_extract_requirement_paths_from_node(demo))

    for child in _extract_children(node):
        child_path_sets.append(_extract_requirement_paths_from_node(child))

    if not child_path_sets:
        return [[]]

    node_type = str(node.get("Type", "ALL")).upper()
    if node_type in {"ANY"}:
        paths = [path for child_paths in child_path_sets for path in child_paths]
        return _dedupe_requirement_paths(paths)

    if node_type in {"AT_LEAST", "ATLEAST"}:
        try:
            count = max(1, int(node.get("Count", node.get("count", 1))))
        except (TypeError, ValueError):
            count = 1
        if count == 1:
            paths = [path for child_paths in child_path_sets for path in child_paths]
            return _dedupe_requirement_paths(paths)

        from itertools import combinations

        combinations_paths: List[List[Dict[str, Any]]] = []
        for idxs in combinations(range(len(child_path_sets)), count):
            chosen_sets = [child_path_sets[i] for i in idxs]
            combinations_paths.extend(_combine_requirement_path_sets(chosen_sets))
        return _dedupe_requirement_paths(combinations_paths)

    return _combine_requirement_path_sets(child_path_sets)


def _extract_requirement_paths_from_leaf(
    node: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> List[List[Dict[str, Any]]]:
    metadata = metadata or {}

    correlated_criteria = None
    for domain_key in LEAF_CRITERION_TYPES:
        domain = node.get(domain_key)
        if isinstance(domain, dict) and isinstance(domain.get("CorrelatedCriteria"), dict):
            correlated_criteria = domain.get("CorrelatedCriteria")
            break

    base_requirements: List[Dict[str, Any]] = []

    if "ConditionOccurrence" in node:
        occ = node.get("ConditionOccurrence")
        if isinstance(occ, dict):
            base_requirements.append(_build_requirement("ConditionOccurrence", occ.get("CodesetId"), metadata))
    elif "ProcedureOccurrence" in node:
        proc = node.get("ProcedureOccurrence")
        if isinstance(proc, dict):
            base_requirements.append(_build_requirement("ProcedureOccurrence", proc.get("CodesetId"), metadata))
    elif "DeviceExposure" in node:
        dev = node.get("DeviceExposure")
        if isinstance(dev, dict):
            base_requirements.append(_build_requirement("DeviceExposure", dev.get("CodesetId"), metadata))
    elif "Measurement" in node:
        meas = node.get("Measurement")
        if isinstance(meas, dict):
            base_requirements.append(
                _build_requirement(
                    "Measurement",
                    meas.get("CodesetId"),
                    metadata,
                    _parse_numeric_value_box(meas),
                )
            )
    elif "DrugExposure" in node:
        drug = node.get("DrugExposure")
        if isinstance(drug, dict):
            base_requirements.append(_build_requirement("DrugExposure", drug.get("CodesetId"), metadata))
    elif "Observation" in node:
        obs = node.get("Observation")
        if isinstance(obs, dict):
            base_requirements.append(
                _build_requirement(
                    "Observation",
                    obs.get("CodesetId"),
                    metadata,
                    _parse_numeric_value_box(obs),
                )
            )

    if not base_requirements:
        return [[]]

    if not correlated_criteria:
        return [base_requirements]

    correlated_paths = _extract_requirement_paths_from_node(correlated_criteria)
    combined = [base_requirements + path for path in correlated_paths]
    return _dedupe_requirement_paths(combined)


def extract_requirement_paths(rule_node: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    expression = rule_node.get("expression", {})
    return _extract_requirement_paths_from_node(expression)


def extract_requirements(
    rule_node: Dict[str, Any],
    or_strategy: str = "first",
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    """
    Extract a satisfiable requirement set from one inclusion rule.
    For ANY/AT_LEAST groups, picks branches deterministically by default ('first').
    """
    rng = rng or random.Random()
    expression = rule_node.get("expression", {})
    return _extract_requirements_from_node(expression, or_strategy, rng)


def _age_delay_years(min_age: float) -> int:
    # Ensure synthetic patient can satisfy a >= bound
    return int(math.ceil(float(min_age)))


def _age_delay_days(min_age: float) -> int:
    return int(math.ceil(float(min_age) * 365.0))


def _pick_code(
    gold_json: Dict[str, Any],
    codeset_id: Any,
    code_strategy: str,
    rng: random.Random,
) -> Optional[Dict[str, str]]:
    codes = get_synthea_codes_for_codeset(gold_json, codeset_id)
    if not codes:
        return None

    if code_strategy == "random":
        return rng.choice(codes)
    return codes[0]


def _is_exclusion_requirement(req: Dict[str, Any]) -> bool:
    return req.get("occurrence_type") == 0 and req.get("occurrence_count", 0) == 0


def _encounter_class_for_requirement(req: Dict[str, Any]) -> str:
    visit_types = req.get("visit_types") or []
    for visit_type in visit_types:
        encounter_class = ENCOUNTER_CLASS_BY_VISIT_TYPE.get(str(visit_type).upper())
        if encounter_class:
            return encounter_class
    return "ambulatory"


def _offset_from_endpoint(days: Any, coeff: Any, default_days: int) -> Optional[int]:
    if days is None and coeff is None:
        return None

    try:
        coeff_value = int(coeff) if coeff is not None else 1
    except (TypeError, ValueError):
        coeff_value = 1
    if coeff_value == 0:
        coeff_value = 1

    try:
        days_value = int(days) if days is not None else default_days
    except (TypeError, ValueError):
        days_value = default_days

    return coeff_value * days_value


def _resolve_window_bounds(req: Dict[str, Any]) -> tuple[int, int]:
    if req.get("index_anchor"):
        return (0, 0)

    start_default = 365 if req.get("start_coeff", -1) == -1 else 0
    end_default = 365 if req.get("end_coeff") == 1 else 0
    start_offset = _offset_from_endpoint(req.get("start_days"), req.get("start_coeff"), start_default)
    end_offset = _offset_from_endpoint(req.get("end_days"), req.get("end_coeff"), end_default)

    if start_offset is None and end_offset is None:
        return (0, 0)
    if start_offset is None:
        start_offset = end_offset
    if end_offset is None:
        end_offset = start_offset

    assert start_offset is not None
    assert end_offset is not None
    return tuple(sorted((start_offset, end_offset)))


def _occurrence_count(req: Dict[str, Any]) -> int:
    try:
        count = int(req.get("occurrence_count", 1))
    except (TypeError, ValueError):
        count = 1
    return max(1, count)


def _distribute_event_offsets(req: Dict[str, Any]) -> List[int]:
    count = _occurrence_count(req)
    low, high = _resolve_window_bounds(req)

    if count == 1 or low == high:
        midpoint = low if low == high else int(round((low + high) / 2.0))
        return [midpoint] * count

    span = high - low
    offsets = [int(round(low + (span * i / (count - 1)))) for i in range(count)]
    for i in range(1, len(offsets)):
        if offsets[i] <= offsets[i - 1] and offsets[i - 1] < high:
            offsets[i] = offsets[i - 1] + 1
    offsets[-1] = min(offsets[-1], high)
    return offsets


def _expand_timeline_requirements(requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for req in requirements:
        if req["type"] == "Age":
            continue
        encounter_class = _encounter_class_for_requirement(req)
        for idx, offset in enumerate(_distribute_event_offsets(req)):
            event_req = dict(req)
            event_req["event_offset_days"] = offset
            event_req["encounter_class"] = encounter_class
            event_req["occurrence_index"] = idx
            events.append(event_req)
    events.sort(
        key=lambda req: (
            req["event_offset_days"],
            req["encounter_class"],
            req["type"],
            str(req.get("codeset_id")),
            req.get("occurrence_index", 0),
        )
    )
    return events


def _group_timeline_requirements(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    for req in events:
        absolute_day = req["absolute_day"]
        encounter_class = req["encounter_class"]
        if groups and groups[-1]["absolute_day"] == absolute_day and groups[-1]["encounter_class"] == encounter_class:
            groups[-1]["requirements"].append(req)
            continue
        groups.append(
            {
                "absolute_day": absolute_day,
                "encounter_class": encounter_class,
                "requirements": [req],
            }
        )
    return groups


def _collect_unsupported_semantics(requirements: List[Dict[str, Any]]) -> List[str]:
    reasons: List[str] = []
    unknown_visit_types = sorted(
        {
            str(visit_type).upper()
            for req in requirements
            for visit_type in (req.get("visit_types") or [])
            if str(visit_type).upper() not in ENCOUNTER_CLASS_BY_VISIT_TYPE
        }
    )
    if unknown_visit_types:
        reasons.append(
            "Unsupported VisitType constraints are present: " + ", ".join(unknown_visit_types)
        )
    if any(req.get("range_high_ratio") for req in requirements):
        reasons.append("Unsupported RangeHighRatio constraints are present.")
    if any(
        req.get(key) is not None
        for req in requirements
        for key in (
            "event_end_start_days",
            "event_end_start_coeff",
            "event_end_end_days",
            "event_end_end_coeff",
        )
    ):
        reasons.append("Unsupported EndWindow constraints are present.")
    if any(req.get("use_index_end") for req in requirements):
        reasons.append("Unsupported UseIndexEnd constraints are present.")
    return reasons


def _make_state_for_requirement(req: Dict[str, Any], code: Dict[str, str], encounter_name: str) -> Dict[str, Any]:
    rtype = req["type"]

    if rtype == "ConditionOccurrence":
        return {
            "type": "ConditionOnset",
            "codes": [code],
            "target_encounter": encounter_name,
            "assign_to_attribute": req.get("attribute_key") or f"cond_{code['code']}",
        }

    if rtype == "DrugExposure":
        attr_name = req.get("attribute_key") or f"med_{code['code']}"
        return {
            "type": "MedicationOrder",
            "codes": [code],
            "target_encounter": encounter_name,
            "assign_to_attribute": attr_name,
        }

    if rtype == "ProcedureOccurrence":
        return {
            "type": "Procedure",
            "codes": [code],
            "target_encounter": encounter_name,
        }

    if rtype == "DeviceExposure":
        return {
            "type": "Device",
            "codes": [code],
            "target_encounter": encounter_name,
        }

    # Measurement and Observation become Synthea observation states.
    category = "laboratory" if rtype == "Measurement" else "clinical"
    state: Dict[str, Any] = {
        "type": "Observation",
        "category": category,
        "codes": [code],
        "target_encounter": encounter_name,
    }

    if "value" in req:
        exact = {
            "quantity": req.get("value"),
        }
        state["exact"] = exact

        if req.get("value_unit"):
            state["unit"] = req.get("value_unit")
        else:
            state["unit"] = "unit"

    return state


def _build_timeline_branch_states(
    states: Dict[str, Any],
    branch_name: str,
    requirements: List[Dict[str, Any]],
    gold: Dict[str, Any],
    code_strategy: str,
    rng: random.Random,
) -> int:
    target_min_age = None
    for req in requirements:
        req_min_age = req.get("min_age")
        if req_min_age is not None:
            if target_min_age is None or req_min_age > target_min_age:
                target_min_age = req_min_age

    timeline_events = _expand_timeline_requirements(requirements)
    if not timeline_events:
        states[branch_name + " Start"] = {"type": "Simple", "direct_transition": "Terminal"}
        return 0

    earliest_offset = min(req["event_offset_days"] for req in timeline_events)
    # Add ObservationWindow.PriorDays so the entry event occurs after the
    # required observation lookback period.  Without this, drug_era events
    # land too close to observation_period_start_date and are filtered out.
    prior_days = gold.get("PrimaryCriteria", {}).get("ObservationWindow", {}).get("PriorDays", 0)
    # Add a safety margin (2x) to avoid boundary-value filtering
    obs_window_buffer = int(prior_days * 2) if prior_days else 0
    index_day = max(
        _age_delay_days(target_min_age) if target_min_age is not None else 0,
        -earliest_offset,
        obs_window_buffer,
    )
    for req in timeline_events:
        req["absolute_day"] = index_day + req["event_offset_days"]

    timeline_groups = _group_timeline_requirements(timeline_events)
    first_absolute_day = timeline_groups[0]["absolute_day"]
    start_state_name = branch_name + " Start"
    if first_absolute_day > 0:
        states[start_state_name] = {
            "type": "Delay",
            "exact": {"quantity": first_absolute_day, "unit": "days"},
            "direct_transition": branch_name + " Encounter 0",
        }
        previous_terminal_state = start_state_name
    else:
        states[start_state_name] = {
            "type": "Simple",
            "direct_transition": branch_name + " Encounter 0",
        }
        previous_terminal_state = start_state_name

    previous_absolute_day = first_absolute_day
    branch_event_count = 0

    for group_index, group in enumerate(timeline_groups):
        encounter_name = f"{branch_name} Encounter {group_index}"
        if group_index > 0:
            delay_days = group["absolute_day"] - previous_absolute_day
            if delay_days > 0:
                delay_name = f"{branch_name} Timeline Delay {group_index}"
                states[previous_terminal_state]["direct_transition"] = delay_name
                states[delay_name] = {
                    "type": "Delay",
                    "exact": {"quantity": delay_days, "unit": "days"},
                    "direct_transition": encounter_name,
                }
            else:
                states[previous_terminal_state]["direct_transition"] = encounter_name

        states[encounter_name] = {
            "type": "Encounter",
            "encounter_class": group["encounter_class"],
            "codes": [ENCOUNTER_CODE],
            "direct_transition": f"{branch_name} EncounterEnd {group_index}",
        }

        current_state = encounter_name
        for req in group["requirements"]:
            code = _pick_code(
                gold_json=gold,
                codeset_id=req.get("codeset_id"),
                code_strategy=code_strategy,
                rng=rng,
            )
            if not code:
                continue
            state_name = f"{branch_name} State {branch_event_count}"
            branch_event_count += 1
            states[state_name] = _make_state_for_requirement(req, code, encounter_name)
            states[current_state]["direct_transition"] = state_name
            current_state = state_name

            if req["type"] == "ConditionOccurrence":
                attr_name = states[state_name].get("assign_to_attribute")
                delay_name = f"{branch_name} Condition Delay {branch_event_count}"
                end_name = f"{branch_name} Condition End {branch_event_count}"
                states[state_name]["direct_transition"] = delay_name
                states[delay_name] = {
                    "type": "Delay",
                    "exact": {"quantity": 1, "unit": "days"},
                    "direct_transition": end_name,
                }
                states[end_name] = {
                    "type": "ConditionEnd",
                    "referenced_by_attribute": attr_name,
                }
                current_state = end_name

            if req["type"] == "DrugExposure" and req.get("era_length_days"):
                attr_name = states[state_name].get("assign_to_attribute")
                delay_name = f"{branch_name} Medication Delay {branch_event_count}"
                end_name = f"{branch_name} Medication End {branch_event_count}"
                states[state_name]["direct_transition"] = delay_name
                # Apply a safety multiplier so ETL date rounding never
                # produces boundary-value drug_eras that fail >= checks.
                # A 3x multiplier is generous without being unrealistic
                # (e.g. 7-day minimum → 21-day prescription).
                raw_days = int(req["era_length_days"])
                era_days = max(raw_days * 3, raw_days + 7)
                states[delay_name] = {
                    "type": "Delay",
                    "exact": {"quantity": era_days, "unit": "days"},
                    "direct_transition": end_name,
                }
                states[end_name] = {
                    "type": "MedicationEnd",
                    "referenced_by_attribute": attr_name,
                }
                current_state = end_name

        encounter_end_name = f"{branch_name} EncounterEnd {group_index}"
        states[current_state]["direct_transition"] = encounter_end_name
        states[encounter_end_name] = {
            "type": "EncounterEnd",
            "direct_transition": "Terminal",
        }
        previous_terminal_state = encounter_end_name
        previous_absolute_day = group["absolute_day"]

    return branch_event_count


def _extract_primary_criteria_reqs(
    gold: Dict[str, Any],
    or_strategy: str = "first",
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    """Extract requirements from PrimaryCriteria (the cohort entry event)."""
    rng = rng or random.Random()
    reqs: List[Dict[str, Any]] = []
    pc = gold.get("PrimaryCriteria", {})
    for cl in pc.get("CriteriaList", []):
        # DrugEra → generate as MedicationOrder
        if "DrugEra" in cl:
            drug_era = cl["DrugEra"]
            if isinstance(drug_era, dict):
                reqs.append({
                    "type": "DrugExposure",
                    "codeset_id": drug_era.get("CodesetId"),
                    "index_anchor": True,
                    "era_length_days": _extract_min_days_from_era_length(drug_era),
                    "min_age": _extract_min_age_from_domain_age(drug_era),
                })
        # ConditionEra → generate as ConditionOnset
        elif "ConditionEra" in cl:
            cond_era = cl["ConditionEra"]
            if isinstance(cond_era, dict):
                reqs.append({
                    "type": "ConditionOccurrence",
                    "codeset_id": cond_era.get("CodesetId"),
                    "index_anchor": True,
                })
        # ConditionOccurrence
        elif "ConditionOccurrence" in cl:
            cond = cl["ConditionOccurrence"]
            if isinstance(cond, dict):
                reqs.append({
                    "type": "ConditionOccurrence",
                    "codeset_id": cond.get("CodesetId"),
                    "index_anchor": True,
                })
        # DrugExposure
        elif "DrugExposure" in cl:
            drug = cl["DrugExposure"]
            if isinstance(drug, dict):
                reqs.append({
                    "type": "DrugExposure",
                    "codeset_id": drug.get("CodesetId"),
                    "index_anchor": True,
                })

    # Also extract from AdditionalCriteria (Correlated Criteria for Entry)
    ac = gold.get("AdditionalCriteria")
    if isinstance(ac, dict):
        ac_reqs = _extract_requirements_from_node(ac, or_strategy, rng)
        # Filter out exclusion criteria if they happen to appear in AdditionalCriteria (usually they don't)
        # We assume they are positive correlated events unless proven otherwise.
        reqs.extend(ac_reqs)

    return reqs


def _extract_primary_criteria_paths(gold: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    base_requirements: List[Dict[str, Any]] = []
    pc = gold.get("PrimaryCriteria", {})
    for cl in pc.get("CriteriaList", []):
        if "DrugEra" in cl:
            drug_era = cl["DrugEra"]
            if isinstance(drug_era, dict):
                base_requirements.append(
                    {
                        "type": "DrugExposure",
                        "codeset_id": drug_era.get("CodesetId"),
                        "index_anchor": True,
                        "era_length_days": _extract_min_days_from_era_length(drug_era),
                        "min_age": _extract_min_age_from_domain_age(drug_era),
                    }
                )
        elif "ConditionEra" in cl:
            cond_era = cl["ConditionEra"]
            if isinstance(cond_era, dict):
                base_requirements.append(
                    {
                        "type": "ConditionOccurrence",
                        "codeset_id": cond_era.get("CodesetId"),
                        "index_anchor": True,
                    }
                )
        elif "ConditionOccurrence" in cl:
            cond = cl["ConditionOccurrence"]
            if isinstance(cond, dict):
                base_requirements.append(
                    {
                        "type": "ConditionOccurrence",
                        "codeset_id": cond.get("CodesetId"),
                        "index_anchor": True,
                    }
                )
        elif "DrugExposure" in cl:
            drug = cl["DrugExposure"]
            if isinstance(drug, dict):
                base_requirements.append(
                    {
                        "type": "DrugExposure",
                        "codeset_id": drug.get("CodesetId"),
                        "index_anchor": True,
                    }
                )

    additional_paths = [[]]
    ac = gold.get("AdditionalCriteria")
    if isinstance(ac, dict):
        additional_paths = _extract_requirement_paths_from_node(ac)

    return _dedupe_requirement_paths([base_requirements + path for path in additional_paths])


def _coalesce_primary_requirement_paths(paths: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
    """Collapse OR-shaped entry paths into one coverage path for best-effort generation.

    Generated modules work better when entry-supporting correlated criteria are emitted
    together instead of splitting the cohort population across many mutually exclusive
    branches. This keeps strict mode semantics untouched while improving non-strict
    generation coverage for trials like ARISTOTLE.
    """
    if len(paths) <= 1:
        return paths

    merged: List[Dict[str, Any]] = []
    seen = set()
    for path in paths:
        for req in path:
            signature = json.dumps(req, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            merged.append(dict(req))
    return [merged]


def _negate_value_in_requirements(reqs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For inverted inclusion rules, negate the value constraint so the
    generated patient SATISFIES the rule (e.g., 'no HbA1c < 7' → generate HbA1c ≥ 7)."""
    for req in reqs:
        if "value" in req and "value_operator" in req:
            original_op = req["value_operator"]
            negated_op = _negate_operator(original_op)
            original_value = req["value"]

            # Undo the operator-based adjustment from _parse_numeric_value_box
            if original_op == "GT":
                original_value = original_value - 0.1
            elif original_op == "LT":
                original_value = original_value + 0.1

            # Apply new adjustment for negated operator
            if negated_op == "GE":
                req["value"] = original_value + 0.5
            elif negated_op == "GT":
                req["value"] = original_value + 1.0
            elif negated_op == "LE":
                req["value"] = max(0.0, original_value - 0.5)
            elif negated_op == "LT":
                req["value"] = max(0.0, original_value - 1.0)
            else:
                req["value"] = original_value

            req["value_operator"] = negated_op
    return reqs


def build_synthea_module(
    gold_json_path: str,
    output_path: str,
    module_name: str,
    or_strategy: str = "first",
    code_strategy: str = "first",
    seed: Optional[int] = None,
    strict: bool = False,
) -> None:
    with open(gold_json_path, "r", encoding="utf-8") as f:
        gold = json.load(f)

    rng = random.Random(seed)

    requirement_paths = _extract_primary_criteria_paths(gold)
    if not strict:
        requirement_paths = _coalesce_primary_requirement_paths(requirement_paths)

    # --- Step 2: InclusionRules (filter by classification) ---
    for rule in gold.get("InclusionRules", []):
        classification = _classify_rule(rule)
        rule_name = rule.get("name", "unnamed")

        if classification == "EXCLUSION":
            # Pure exclusion: don't generate these conditions
            print(f"  [SKIP] Exclusion rule: {rule_name}")
            continue

        rule_paths = extract_requirement_paths(rule)
        if classification == "INVERTED":
            transformed_paths: List[List[Dict[str, Any]]] = []
            for path in rule_paths:
                path_reqs = [r for r in path if r["type"] in ("Measurement", "Observation")]
                path_reqs = _negate_value_in_requirements(path_reqs)
                transformed_paths.append(path_reqs)
            rule_paths = _dedupe_requirement_paths(transformed_paths)
            kept = sum(len(path) for path in rule_paths)
            print(f"  [NEGATE] Inverted rule: {rule_name} ({kept} value reqs kept)")
        else:
            transformed_paths = []
            for path in rule_paths:
                transformed_paths.append([r for r in path if not _is_exclusion_requirement(r)])
            rule_paths = _dedupe_requirement_paths(transformed_paths)
            print(f"  [INCLUDE] Positive rule: {rule_name}")

        requirement_paths = _dedupe_requirement_paths(
            [base + path for base in requirement_paths for path in rule_paths]
        )

    all_requirements = [req for path in requirement_paths for req in path]
    unsupported_reasons = _collect_unsupported_semantics(all_requirements)
    if strict and unsupported_reasons:
        raise ValueError("Unsupported Circe semantics: " + "; ".join(unsupported_reasons))

    states: Dict[str, Any] = {
        "Initial": {"type": "Initial", "direct_transition": "Terminal"},
        "Terminal": {"type": "Terminal"},
    }
    state_i = 0
    if len(requirement_paths) == 1:
        states["Initial"]["direct_transition"] = "Branch 0 Start"
    elif requirement_paths:
        states["Initial"]["direct_transition"] = "Branch Select"
        distribution = 1.0 / len(requirement_paths)
        states["Branch Select"] = {
            "type": "Simple",
            "distributed_transition": [
                {"distribution": distribution, "transition": f"Branch {idx} Start"}
                for idx in range(len(requirement_paths))
            ],
        }

    for idx, path in enumerate(requirement_paths):
        state_i += _build_timeline_branch_states(
            states=states,
            branch_name=f"Branch {idx}",
            requirements=path,
            gold=gold,
            code_strategy=code_strategy,
            rng=rng,
        )

    module = {
        "name": module_name,
        "remarks": [
            "Auto-generated from OHDSI Circe Gold JSON",
            f"or_strategy={or_strategy}",
            f"code_strategy={code_strategy}",
            f"path_count={len(requirement_paths)}",
            *unsupported_reasons,
        ],
        "states": states,
        "gmf_version": 2,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(module, f, indent=2)
        print(f"Generated {output_path} with {state_i} events.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Synthea module from OHDSI Circe/Gold InclusionRules."
    )
    parser.add_argument("--gold", required=True, help="Path to GOLD JSON file")
    parser.add_argument("--out", required=True, help="Output module JSON file")
    parser.add_argument("--name", required=True, help="Module name")
    parser.add_argument(
        "--or-strategy",
        choices=["first", "random"],
        default="first",
        help=(
            "How to resolve Circe ANY / AT_LEAST groups. "
            "'first' picks first branch deterministically (recommended for deterministic generation). "
            "'random' picks branch(es) randomly."
        ),
    )
    parser.add_argument(
        "--code-strategy",
        choices=["first", "random"],
        default="first",
        help="How to select a concept from a concept set.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for deterministic random branch/code selection when using random strategy.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail instead of emitting a best-effort module when unsupported semantics are detected.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    build_synthea_module(
        gold_json_path=args.gold,
        output_path=args.out,
        module_name=args.name,
        or_strategy=args.or_strategy,
        code_strategy=args.code_strategy,
        seed=args.seed,
        strict=args.strict,
    )
