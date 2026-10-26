"""Compile model-stated occurrence thresholds without reading protocol words."""

from collections.abc import Mapping
from math import ceil, floor, isfinite
from numbers import Real
from typing import Any

from src.utils.span_match import span_in_line

FIELD = "occurrence_threshold"
TIME_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
DOMAIN_TYPES = {
    "Condition": "ConditionOccurrence",
    "Procedure": "ProcedureOccurrence",
    "Drug": "DrugExposure",
    "Observation": "Observation",
    "Measurement": "Measurement",
}


def validated_threshold(payload: Any, line: Any) -> dict | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("value")
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        finite = isfinite(value)
    except OverflowError:
        return None
    if not finite or value < 0 or not span_in_line(payload.get("span"), line):
        return None
    if payload.get("op") not in ("lt", "lte", "gt", "gte", "eq"):
        return None
    if payload.get("anchor") not in ("index", "informed_consent", "screening"):
        return None
    target = payload.get("target")
    if target == "event_count":
        if (
            payload.get("unit") != "count"
            or value != int(value)
            or payload["op"] not in ("gt", "gte")
        ):
            return None
    elif target in ("event_age", "first_diagnosis_age", "drug_era_length"):
        if not isinstance(payload.get("unit"), str) or payload["unit"] not in TIME_DAYS:
            return None
    else:
        return None
    return dict(payload)


def occurrence_filter(row: Mapping, *, exclusion: bool = False) -> dict | None:
    annotation = row.get("annotation") or {}
    if not isinstance(annotation, Mapping) or annotation.get("error") or row.get("isGroupLabel"):
        return None
    spec = validated_threshold(annotation.get(FIELD), row.get("protocolLine"))
    if spec is None:
        return None
    threshold_span = annotation.get("threshold_span")
    if not span_in_line(threshold_span, row.get("protocolLine")) or not (
        span_in_line(threshold_span, spec["span"]) or span_in_line(spec["span"], threshold_span)
    ):
        return None
    target, domain = spec["target"], row.get("domain")
    kind = "count" if target == "event_count" else "duration"
    if annotation.get("quantity_kind") != kind or annotation.get("reference_bound") != "none":
        return None
    criteria_type = DOMAIN_TYPES.get(domain)
    if criteria_type is None:
        return None
    result: dict[str, Any] = {"criteriaType": criteria_type, "attributes": {}}
    op, value = spec["op"], spec["value"]
    if target == "event_count":
        count = int(value) + (op == "gt")
        if count < 1:
            return None
        result["Occurrence"] = (
            {"Type": 1, "Count": count - 1} if exclusion else {"Type": 2, "Count": count}
        )
        return result
    days = float(value) * TIME_DAYS[spec["unit"]]
    if not isfinite(days):
        return None
    if target == "drug_era_length":
        if domain != "Drug" or op not in ("gt", "gte"):
            return None
        result.update(
            criteriaType="DrugEra",
            attributes={
                "EraLength": {"Value": days, "Op": op},
                "GapDays": {"Value": 0, "Op": "eq"},
            },
        )
        minimum = floor(days) + 1 if op == "gt" else ceil(days)
        result["StartWindow"] = {
            "Start": {"Coeff": -1},
            "End": {"Days": minimum, "Coeff": -1 if minimum else 1},
        }
        return result
    if target == "first_diagnosis_age":
        if domain != "Condition":
            return None
        result["attributes"]["First"] = True
    # Compare elapsed days, then reverse the bounds onto event dates before index.
    lower = floor(days) + 1 if op == "gt" else ceil(days) if op in ("gte", "eq") else 0
    upper = ceil(days) - 1 if op == "lt" else floor(days) if op in ("lte", "eq") else None
    if upper is not None and upper < lower:
        return None
    result["StartWindow"] = {
        "Start": {"Coeff": -1, **({"Days": upper} if upper is not None else {})},
        "End": {"Days": lower, "Coeff": -1 if lower else 1},
    }
    return result


def matches_occurrence_filter(entry: Mapping, expected: Mapping) -> bool:
    attrs = (entry.get("Criteria") or {}).get(expected["criteriaType"])
    return (
        isinstance(attrs, Mapping)
        and all(attrs.get(k) == v for k, v in expected["attributes"].items())
        and all(entry.get(k) == expected[k] for k in ("StartWindow", "Occurrence") if k in expected)
    )
