from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

REQUIRED_ANALYSIS_IDS = frozenset({200, 400, 600, 700, 800, 1800})
CSV_HEADER = ("analysis_id", "stratum_1", "count_value")
DOMAIN_ANALYSIS_IDS = {
    "VisitOccurrence": 200,
    "VisitDetail": 200,
    "ConditionOccurrence": 400,
    "ConditionEra": 400,
    "ProcedureOccurrence": 600,
    "DrugExposure": 700,
    "DrugEra": 700,
    "Observation": 800,
    "Measurement": 1800,
}


class SnapshotValidationError(ValueError):
    pass


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    site_key: str = Field(alias="siteKey", min_length=1)
    results_schema: str = Field(alias="resultsSchema", min_length=1)
    cdm_version: str = Field(alias="cdmVersion", min_length=1)
    vocabulary_version: str = Field(alias="vocabularyVersion", min_length=1)
    achilles_version: str = Field(alias="achillesVersion", min_length=1)
    achilles_run_date: date = Field(alias="achillesRunDate")
    small_cell_count: int = Field(alias="smallCellCount", ge=0)
    analysis_ids: list[int] = Field(alias="analysisIds")

    @field_validator("analysis_ids")
    @classmethod
    def validate_analysis_ids(cls, value: list[int]) -> list[int]:
        if set(value) != REQUIRED_ANALYSIS_IDS or len(value) != len(
            REQUIRED_ANALYSIS_IDS
        ):
            raise ValueError(
                f"analysisIds must contain exactly {sorted(REQUIRED_ANALYSIS_IDS)}"
            )
        return value


class AchillesSiteSnapshot(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    manifest: SnapshotManifest
    counts: dict[tuple[int, int], int]
    signature: str


EvidenceState = Literal[
    "populated_exact_concept",
    "suppressed_or_absent",
    "exact_concept_zero",
    "unknown_vocabulary",
    "populated_descendant_upper_bound",
]


class ConceptEvidence(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    state: EvidenceState
    analysis_id: int = Field(alias="analysisId")
    concept_id: int = Field(alias="conceptId")
    count_value: int | None = Field(default=None, alias="countValue")
    upper_bound: int | None = Field(default=None, alias="upperBound")


class ProposedChange(BaseModel):
    action: str
    path: str
    concept_id: int = Field(alias="conceptId")
    reason: str


class SiteAdaptationReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["proposed"] = "proposed"
    site: dict[str, Any]
    input_signature: str = Field(alias="inputSignature")
    criteria_evidence: list[dict[str, Any]] = Field(
        default_factory=list, alias="criteriaEvidence"
    )
    comparator_grounding: list[dict[str, Any]] = Field(
        default_factory=list, alias="comparatorGrounding"
    )
    verification_requests: list[dict[str, Any]] = Field(
        default_factory=list, alias="verificationRequests"
    )
    proposed_changes: list[ProposedChange] = Field(
        default_factory=list, alias="proposedChanges"
    )


def load_achilles_snapshot(path: Path) -> AchillesSiteSnapshot:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            expected = {"achilles_prevalence.csv", "manifest.json"}
            if len(names) != 2 or set(names) != expected:
                raise SnapshotValidationError(
                    "snapshot must contain exactly achilles_prevalence.csv "
                    "and manifest.json"
                )
            manifest_bytes = archive.read("manifest.json")
            csv_bytes = archive.read("achilles_prevalence.csv")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise SnapshotValidationError(f"invalid snapshot ZIP: {exc}") from exc

    try:
        manifest = SnapshotManifest.model_validate_json(manifest_bytes)
    except ValidationError as exc:
        raise SnapshotValidationError(f"invalid manifest: {exc}") from exc

    counts = _parse_prevalence_csv(csv_bytes, manifest)
    normalized_manifest = json.dumps(
        manifest.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    normalized_csv = _canonical_csv(counts)
    signature = hashlib.sha256(
        normalized_manifest + b"\0" + normalized_csv
    ).hexdigest()
    return AchillesSiteSnapshot(
        manifest=manifest,
        counts=counts,
        signature=signature,
    )


def _parse_prevalence_csv(
    raw: bytes, manifest: SnapshotManifest
) -> dict[tuple[int, int], int]:
    try:
        stream = io.StringIO(raw.decode("utf-8-sig"), newline="")
    except UnicodeDecodeError as exc:
        raise SnapshotValidationError("CSV must be UTF-8") from exc

    reader = csv.DictReader(stream)
    if tuple(reader.fieldnames or ()) != CSV_HEADER:
        raise SnapshotValidationError(
            f"CSV header must be exactly {','.join(CSV_HEADER)}"
        )

    counts: dict[tuple[int, int], int] = {}
    allowed = set(manifest.analysis_ids)
    for line_number, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise SnapshotValidationError(f"invalid CSV column count at line {line_number}")
        try:
            analysis_id = int(row["analysis_id"])
        except ValueError as exc:
            raise SnapshotValidationError(
                f"analysis_id must be an integer at line {line_number}"
            ) from exc
        if analysis_id not in allowed:
            raise SnapshotValidationError(
                f"analysis_id {analysis_id} is not declared in manifest"
            )

        raw_concept_id = row["stratum_1"]
        if not re.fullmatch(r"[0-9]+", raw_concept_id):
            raise SnapshotValidationError(
                f"stratum_1 must be a positive decimal concept ID at line {line_number}"
            )
        concept_id = int(raw_concept_id)
        if concept_id <= 0:
            raise SnapshotValidationError(
                f"stratum_1 must be a positive decimal concept ID at line {line_number}"
            )

        try:
            count_value = int(row["count_value"])
        except ValueError as exc:
            raise SnapshotValidationError(
                f"count_value must be an integer at line {line_number}"
            ) from exc
        if count_value <= 0:
            raise SnapshotValidationError(
                f"count_value must be positive at line {line_number}"
            )

        key = (analysis_id, concept_id)
        if key in counts:
            raise SnapshotValidationError(
                f"duplicate (analysis_id, concept_id) at line {line_number}"
            )
        counts[key] = count_value
    return counts


def _canonical_csv(counts: Mapping[tuple[int, int], int]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for (analysis_id, concept_id), count_value in sorted(counts.items()):
        writer.writerow((analysis_id, concept_id, count_value))
    return stream.getvalue().encode()


def load_vocabulary_descendants(
    database_url: str,
    vocabulary_schema: str,
    ancestor_ids: set[int],
) -> dict[int, set[int]]:
    if not vocabulary_schema:
        raise ValueError("vocabulary_schema is required")
    descendants = {ancestor_id: set() for ancestor_id in ancestor_ids}
    if not ancestor_ids:
        return descendants

    import psycopg2
    from psycopg2 import sql

    query = sql.SQL(
        "SELECT ancestor_concept_id, descendant_concept_id "
        "FROM {}.concept_ancestor "
        "WHERE ancestor_concept_id = ANY(%s)"
    ).format(sql.Identifier(vocabulary_schema))
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (sorted(ancestor_ids),))
            for ancestor_id, descendant_id in cursor.fetchall():
                descendants[int(ancestor_id)].add(int(descendant_id))
    return descendants


def concept_evidence(
    snapshot: AchillesSiteSnapshot,
    *,
    analysis_id: int,
    concept_id: int,
    concept_exists: bool,
) -> ConceptEvidence:
    if analysis_id not in snapshot.manifest.analysis_ids:
        raise SnapshotValidationError(f"analysis_id {analysis_id} is incomplete")
    count_value = snapshot.counts.get((analysis_id, concept_id))
    if count_value is not None:
        return ConceptEvidence(
            state="populated_exact_concept",
            analysisId=analysis_id,
            conceptId=concept_id,
            countValue=count_value,
        )
    if not concept_exists:
        return ConceptEvidence(
            state="unknown_vocabulary",
            analysisId=analysis_id,
            conceptId=concept_id,
        )
    if snapshot.manifest.small_cell_count > 0:
        return ConceptEvidence(
            state="suppressed_or_absent",
            analysisId=analysis_id,
            conceptId=concept_id,
            upperBound=snapshot.manifest.small_cell_count,
        )
    return ConceptEvidence(
        state="exact_concept_zero",
        analysisId=analysis_id,
        conceptId=concept_id,
        countValue=0,
    )


def compile_site_adaptation(
    circe: dict[str, Any],
    snapshot: AchillesSiteSnapshot,
    descendants: Mapping[int, set[int]],
    *,
    comparator_artifact: dict[str, Any] | None = None,
) -> SiteAdaptationReport:
    concept_sets = _concept_sets(circe)
    evidence_rows: list[dict[str, Any]] = []
    proposals: list[ProposedChange] = []
    requests: list[dict[str, Any]] = []

    def inspect_criterion(
        criterion: dict[str, Any], *, path: str, role: str
    ) -> None:
        domain, body = _criterion_domain(criterion)
        analysis_id = DOMAIN_ANALYSIS_IDS.get(domain)
        if analysis_id is None:
            requests.append({"path": path, "reason": "unsupported_domain"})
            return
        codeset_id = body.get("CodesetId")
        concepts = concept_sets.get(codeset_id, ())
        occurrence = criterion.get("Occurrence", {})
        presence = occurrence.get("Type", 2) != 0

        for concept_id, include_descendants in concepts:
            exact = concept_evidence(
                snapshot,
                analysis_id=analysis_id,
                concept_id=concept_id,
                concept_exists=concept_id in descendants,
            )
            evidence_rows.append(
                {
                    "path": path,
                    "role": role,
                    "polarity": "presence" if presence else "absence",
                    **exact.model_dump(by_alias=True),
                }
            )
            if exact.state in {"suppressed_or_absent", "unknown_vocabulary"}:
                proposals.append(
                    ProposedChange(
                        action="SITE_QUERY_REQUIRED",
                        path=path,
                        conceptId=concept_id,
                        reason=exact.state,
                    )
                )
            elif exact.state == "exact_concept_zero":
                action = (
                    "VERIFY_THEN_REMAP"
                    if role == "entry"
                    else "VERIFY_THEN_DROP"
                    if presence
                    else "BENIGN_KEEP"
                )
                proposals.append(
                    ProposedChange(
                        action=action,
                        path=path,
                        conceptId=concept_id,
                        reason="exact_concept_zero",
                    )
                )

            if include_descendants:
                populated = [
                    descendant_id
                    for descendant_id in descendants.get(concept_id, set())
                    if descendant_id != concept_id
                    and snapshot.counts.get((analysis_id, descendant_id)) is not None
                ]
                if populated:
                    upper_bound = sum(
                        snapshot.counts[(analysis_id, descendant_id)]
                        for descendant_id in populated
                    )
                    evidence_rows.append(
                        ConceptEvidence(
                            state="populated_descendant_upper_bound",
                            analysisId=analysis_id,
                            conceptId=concept_id,
                            upperBound=upper_bound,
                        ).model_dump(by_alias=True)
                        | {"path": path, "role": role}
                    )
                    proposals.append(
                        ProposedChange(
                            action="USE_POPULATED_DESCENDANTS",
                            path=path,
                            conceptId=concept_id,
                            reason="descendant counts are a non-distinct upper bound",
                        )
                    )

        if any(key in body for key in ("ValueAsNumber", "ValueAsConcept", "Unit")):
            requests.append({"path": path, "reason": "value_or_unit_constraint"})
        if any(key in criterion for key in ("StartWindow", "EndWindow")):
            requests.append({"path": path, "reason": "time_window"})

    primary = circe.get("PrimaryCriteria", {})
    for index, criterion in enumerate(primary.get("CriteriaList", [])):
        inspect_criterion(
            criterion,
            path=f"PrimaryCriteria.CriteriaList[{index}]",
            role="entry",
        )

    def walk_expression(expression: dict[str, Any], path: str) -> None:
        criteria = expression.get("CriteriaList", [])
        groups = expression.get("Groups", [])
        if len(criteria) + len(groups) > 1:
            requests.append({"path": path, "reason": "joint_group"})
        for index, criterion in enumerate(criteria):
            inspect_criterion(
                criterion,
                path=f"{path}.CriteriaList[{index}]",
                role="inclusion",
            )
        for index, group in enumerate(groups):
            walk_expression(group, f"{path}.Groups[{index}]")

    for index, rule in enumerate(circe.get("InclusionRules", [])):
        walk_expression(rule.get("expression", {}), f"InclusionRules[{index}].expression")

    grounding = _ground_comparators(snapshot, descendants, comparator_artifact)
    manifest = snapshot.manifest
    return SiteAdaptationReport(
        site={
            "siteKey": manifest.site_key,
            "resultsSchema": manifest.results_schema,
            "achillesRunDate": manifest.achilles_run_date.isoformat(),
            "smallCellCount": manifest.small_cell_count,
        },
        inputSignature=snapshot.signature,
        criteriaEvidence=evidence_rows,
        comparatorGrounding=grounding,
        verificationRequests=requests,
        proposedChanges=proposals,
    )


def _concept_sets(
    circe: Mapping[str, Any],
) -> dict[int, list[tuple[int, bool]]]:
    result: dict[int, list[tuple[int, bool]]] = {}
    for concept_set in circe.get("ConceptSets", []):
        items: list[tuple[int, bool]] = []
        for item in concept_set.get("expression", {}).get("items", []):
            if item.get("isExcluded"):
                continue
            raw_id = item.get("concept", {}).get("CONCEPT_ID")
            if isinstance(raw_id, int) and raw_id > 0:
                items.append((raw_id, bool(item.get("includeDescendants"))))
        result[concept_set.get("id")] = items
    return result


def _criterion_domain(criterion: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    criteria = criterion.get("Criteria", criterion)
    for domain, body in criteria.items():
        if domain in DOMAIN_ANALYSIS_IDS and isinstance(body, dict):
            return domain, body
    return "", {}


def _ground_comparators(
    snapshot: AchillesSiteSnapshot,
    descendants: Mapping[int, set[int]],
    artifact: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    grounded: list[dict[str, Any]] = []
    for candidate in (artifact or {}).get("candidates", []):
        concept_ids = candidate.get("conceptIds", candidate.get("concept_ids", []))
        evidence = [
            concept_evidence(
                snapshot,
                analysis_id=700,
                concept_id=int(concept_id),
                concept_exists=int(concept_id) in descendants,
            )
            for concept_id in concept_ids
        ]
        states = {item.state for item in evidence}
        status = (
            "populated"
            if "populated_exact_concept" in states
            else "site_query_required"
            if "suppressed_or_absent" in states
            else "absent"
        )
        grounded.append(
            {
                "candidate": candidate.get("name", candidate.get("drugClass", "")),
                "conceptIds": [int(value) for value in concept_ids],
                "status": status,
                "evidence": [
                    item.model_dump(by_alias=True) for item in evidence
                ],
            }
        )
    return grounded
