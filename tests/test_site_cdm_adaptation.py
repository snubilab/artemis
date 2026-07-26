from __future__ import annotations

import copy
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from src.services.site_cdm_adaptation import (
    REQUIRED_ANALYSIS_IDS,
    SnapshotValidationError,
    compile_site_adaptation,
    concept_evidence,
    load_achilles_snapshot,
)


def _manifest(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "siteKey": "hospital_a",
        "resultsSchema": "hospital_a_results",
        "cdmVersion": "5.4",
        "vocabularyVersion": "2026-06-30",
        "achillesVersion": "1.7.2",
        "achillesRunDate": "2026-07-24",
        "smallCellCount": 5,
        "analysisIds": sorted(REQUIRED_ANALYSIS_IDS),
    }
    value.update(overrides)
    return value


def _csv_bytes(
    rows: list[tuple[object, object, object]],
    header: tuple[str, ...] = ("analysis_id", "stratum_1", "count_value"),
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode()


def _snapshot_zip(
    tmp_path: Path,
    *,
    manifest: dict[str, object] | None = None,
    rows: list[tuple[object, object, object]] | None = None,
    header: tuple[str, ...] = ("analysis_id", "stratum_1", "count_value"),
    extra_member: str | None = None,
) -> Path:
    path = tmp_path / "snapshot.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest or _manifest()))
        archive.writestr(
            "achilles_prevalence.csv",
            _csv_bytes(rows or [(400, "201826", 819)], header),
        )
        if extra_member:
            archive.writestr(extra_member, b"unexpected")
    return path


@pytest.mark.parametrize("member", ["notes.txt", "../manifest.json", "nested/file.csv"])
def test_snapshot_rejects_extra_or_unsafe_archive_members(
    tmp_path: Path, member: str
) -> None:
    with pytest.raises(SnapshotValidationError, match="exactly"):
        load_achilles_snapshot(_snapshot_zip(tmp_path, extra_member=member))


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        (_manifest(siteKey=""), "siteKey"),
        (_manifest(achillesRunDate="not-a-date"), "achillesRunDate"),
        (_manifest(smallCellCount=-1), "smallCellCount"),
        (_manifest(analysisIds=[200, 400]), "analysisIds"),
    ],
)
def test_snapshot_validates_manifest(
    tmp_path: Path, manifest: dict[str, object], message: str
) -> None:
    with pytest.raises(SnapshotValidationError, match=message):
        load_achilles_snapshot(_snapshot_zip(tmp_path, manifest=manifest))


def test_snapshot_requires_exact_csv_header(tmp_path: Path) -> None:
    with pytest.raises(SnapshotValidationError, match="header"):
        load_achilles_snapshot(
            _snapshot_zip(
                tmp_path,
                header=("analysis_id", "stratum_1", "count_value", "stratum_2"),
            )
        )


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([(400, "abc", 2)], "concept ID"),
        ([(400, "0", 2)], "concept ID"),
        ([(400, "-1", 2)], "concept ID"),
        ([(400, "201826", 0)], "count_value"),
        ([(400, "201826", -1)], "count_value"),
        ([(999, "201826", 2)], "analysis_id"),
        ([(400, "201826", 2), (400, "201826", 3)], "duplicate"),
    ],
)
def test_snapshot_rejects_invalid_csv_rows(
    tmp_path: Path,
    rows: list[tuple[object, object, object]],
    message: str,
) -> None:
    with pytest.raises(SnapshotValidationError, match=message):
        load_achilles_snapshot(_snapshot_zip(tmp_path, rows=rows))


def test_snapshot_signature_is_deterministic(tmp_path: Path) -> None:
    first = load_achilles_snapshot(
        _snapshot_zip(tmp_path, rows=[(400, "201826", 819), (1800, "3001802", 820)])
    )
    second_path = tmp_path / "second.zip"
    with zipfile.ZipFile(second_path, "w") as archive:
        archive.writestr(
            "achilles_prevalence.csv",
            _csv_bytes([(400, "201826", 819), (1800, "3001802", 820)]),
        )
        archive.writestr("manifest.json", json.dumps(_manifest(), indent=2))
    second = load_achilles_snapshot(second_path)

    assert first.signature == second.signature
    assert len(first.signature) == 64


def test_concept_evidence_classifies_all_states(tmp_path: Path) -> None:
    suppressed = load_achilles_snapshot(_snapshot_zip(tmp_path))
    assert concept_evidence(
        suppressed, analysis_id=400, concept_id=201826, concept_exists=True
    ).state == "populated_exact_concept"
    missing = concept_evidence(
        suppressed, analysis_id=400, concept_id=123, concept_exists=True
    )
    assert (missing.state, missing.upper_bound) == ("suppressed_or_absent", 5)
    assert concept_evidence(
        suppressed, analysis_id=400, concept_id=123, concept_exists=False
    ).state == "unknown_vocabulary"

    zero_path = tmp_path / "zero.zip"
    zero_path.write_bytes(
        _snapshot_zip(
            tmp_path,
            manifest=_manifest(smallCellCount=0),
        ).read_bytes()
    )
    assert concept_evidence(
        load_achilles_snapshot(zero_path),
        analysis_id=400,
        concept_id=123,
        concept_exists=True,
    ).state == "exact_concept_zero"


def _concept_set(
    codeset_id: int, concept_id: int, *, descendants: bool = False
) -> dict[str, object]:
    return {
        "id": codeset_id,
        "name": f"concept-{concept_id}",
        "expression": {
            "items": [
                {
                    "concept": {"CONCEPT_ID": concept_id},
                    "includeDescendants": descendants,
                    "isExcluded": False,
                }
            ]
        },
    }


def _criterion(
    domain: str,
    codeset_id: int,
    *,
    occurrence_type: int = 2,
    value: bool = False,
) -> dict[str, object]:
    criterion: dict[str, object] = {
        "Criteria": {domain: {"CodesetId": codeset_id}},
        "Occurrence": {"Type": occurrence_type, "Count": 1},
        "StartWindow": {
            "Start": {"Days": 365, "Coeff": -1},
            "End": {"Days": 0, "Coeff": 1},
        },
    }
    if value:
        criteria = criterion["Criteria"]
        assert isinstance(criteria, dict)
        body = criteria[domain]
        assert isinstance(body, dict)
        body["ValueAsNumber"] = {
            "Op": "gte",
            "Value": 30,
        }
    return criterion


def test_compile_site_adaptation_is_recursive_and_does_not_mutate_circe(
    tmp_path: Path,
) -> None:
    snapshot = load_achilles_snapshot(
        _snapshot_zip(
            tmp_path,
            manifest=_manifest(smallCellCount=0),
            rows=[(400, "45769905", 17), (700, "19125041", 8)],
        )
    )
    circe = {
        "ConceptSets": [
            _concept_set(1, 999001),
            _concept_set(2, 201826, descendants=True),
            _concept_set(3, 3001802),
            _concept_set(4, 999004),
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugExposure": {"CodesetId": 1}}],
        },
        "InclusionRules": [
            {
                "name": "nested",
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [_criterion("Measurement", 3, value=True)],
                    "Groups": [
                        {
                            "Type": "ANY",
                            "CriteriaList": [
                                _criterion("ConditionOccurrence", 2),
                                _criterion(
                                    "ConditionOccurrence",
                                    4,
                                    occurrence_type=0,
                                ),
                            ],
                            "Groups": [],
                        }
                    ],
                },
            }
        ],
    }
    original = copy.deepcopy(circe)

    report = compile_site_adaptation(
        circe,
        snapshot,
        {
            999001: {999001},
            201826: {201826, 45769905},
            3001802: {3001802},
            999004: {999004},
            19125041: {19125041},
        },
        comparator_artifact={
            "candidates": [
                {"name": "DPP-4 inhibitor", "conceptIds": [19125041]}
            ]
        },
    )
    payload = report.model_dump(by_alias=True)

    assert circe == original
    assert list(payload) == [
        "status",
        "site",
        "inputSignature",
        "criteriaEvidence",
        "comparatorGrounding",
        "verificationRequests",
        "proposedChanges",
    ]
    assert payload["status"] == "proposed"
    assert {
        change["action"] for change in payload["proposedChanges"]
    } >= {
        "VERIFY_THEN_REMAP",
        "VERIFY_THEN_DROP",
        "BENIGN_KEEP",
        "USE_POPULATED_DESCENDANTS",
    }
    assert any(
        evidence["state"] == "populated_descendant_upper_bound"
        and evidence["upperBound"] == 17
        for evidence in payload["criteriaEvidence"]
    )
    assert any(
        request["reason"] == "value_or_unit_constraint"
        for request in payload["verificationRequests"]
    )
    assert any(
        request["reason"] == "time_window"
        for request in payload["verificationRequests"]
    )
    assert any(
        request["reason"] == "joint_group"
        for request in payload["verificationRequests"]
    )
    assert payload["comparatorGrounding"][0]["status"] == "populated"


def test_suppressed_missing_stays_site_query_required(tmp_path: Path) -> None:
    snapshot = load_achilles_snapshot(_snapshot_zip(tmp_path))
    circe = {
        "ConceptSets": [_concept_set(1, 123)],
        "PrimaryCriteria": {"CriteriaList": []},
        "InclusionRules": [
            {
                "name": "criterion",
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [_criterion("ConditionOccurrence", 1)],
                    "Groups": [],
                },
            }
        ],
    }

    report = compile_site_adaptation(circe, snapshot, {123: {123}})

    assert report.proposed_changes[0].action == "SITE_QUERY_REQUIRED"
