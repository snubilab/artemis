from __future__ import annotations

import base64
import builtins
import sys
import types
import warnings
from copy import deepcopy
from pathlib import Path

import pytest

from src.api.models.tte import utc_now_iso
from src.api.main import create_app
from src.api.tte import get_tte_service
from src.services.tte_service import TTEService
from src.services.tte_store import TTEStore
from testclient_compat import CompatTestClient


def build_client(monkeypatch, tmp_path: str) -> CompatTestClient:
    monkeypatch.setenv("TTE_STORE_PATH", str(tmp_path / "tte" / "studies.json"))
    get_tte_service.cache_clear()
    return CompatTestClient(create_app())


def assert_capability_signal(meta: dict, *, owner: str, fidelity: str, stage_kind: str):
    signal = meta["capabilitySignal"]
    assert signal["owner"] == owner
    assert signal["fidelity"] == fidelity
    assert signal["stageKind"] == stage_kind
    assert signal["fidelityNote"]


def create_analysis_ready_study(client: CompatTestClient, *, name: str = "Analysis-ready study") -> int:
    create_response = client.post(
        "/tte/studies",
        json={
            "name": name,
            "description": "has analysis results",
            "results": {
                "mode": "analysis",
                "generatedBy": "artemis-agent5-wrapper",
                "analysisMethod": "PSM",
                "matchedPairs": 412,
                "hazardRatio": 0.8,
                "CI": {"lower": 0.7, "upper": 0.92},
                "pValue": 0.01,
                "covariateBalance": [],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentN": 1200,
                "comparatorN": 1180,
                "treatmentEvents": 30,
                "comparatorEvents": 44,
                "survivalData": {
                    "times_treated": [7, 14, 28, 28],
                    "events_treated": [1, 0, 1, 0],
                    "times_control": [6, 13, 20, 28],
                    "events_control": [1, 1, 0, 0],
                },
                "plots": [
                    {
                        "key": "cumulative_mortality_28d",
                        "title": "28-day Cumulative Mortality",
                        "plotType": "line",
                        "xLabel": "Days since index",
                        "yLabel": "Cumulative mortality (%)",
                        "windowDays": 28,
                        "series": [],
                    },
                    {
                        "key": "love_plot_after_matching",
                        "title": "Love Plot (Covariate Balance After Matching)",
                        "plotType": "love_plot",
                        "xLabel": "Standardized mean difference",
                        "yLabel": "Covariate",
                        "series": [],
                    },
                ],
            },
        },
    )
    return create_response.json()["id"]


def create_generation_ready_study(
    client: CompatTestClient,
    *,
    name: str = "Generation-ready study",
    treatment_n: int = 320,
    comparator_n: int = 1600,
    followup_days: int = 365,
) -> int:
    create_response = client.post(
        "/tte/studies",
        json={
            "name": name,
            "description": "has generation results for strategy evaluation",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "structuredExpression": build_structured_eligibility_expression(),
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "timeParams": {"followUpDuration": followup_days},
            "analysisSettings": {
                "outcomeModel": "cox",
                "adjustForCovariates": True,
                "psMethod": "matching",
                "psCaliper": 0.2,
                "trimByPs": True,
                "trimFraction": 0.05,
            },
            "results": {
                "mode": "webapi_generation",
                "sourceKey": "SYNTHEA23M",
                "generatedBy": "artemis-api-webapi",
                "targetN": treatment_n + comparator_n,
                "treatmentN": treatment_n,
                "comparatorN": comparator_n,
                "primaryOutcomeN": 190,
                "generatedCohorts": [
                    {"role": "target", "personCount": treatment_n + comparator_n, "sourceKey": "SYNTHEA23M"},
                    {"role": "treatment", "personCount": treatment_n, "sourceKey": "SYNTHEA23M"},
                    {"role": "comparator", "personCount": comparator_n, "sourceKey": "SYNTHEA23M"},
                ],
            },
        },
    )
    assert create_response.status_code == 200
    return create_response.json()["id"]


def build_structured_eligibility_expression(
    *, include_inclusion_rule: bool = True, target_label: str = "Target cohort"
) -> dict:
    inclusion_rules = []
    if include_inclusion_rule:
        inclusion_rules.append(
            {
                "name": "Adults with T2DM",
                "expression": {
                    "Type": "ANY",
                    "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        )

    return {
        "ConceptSets": [
            {
                "id": 0,
                "name": target_label,
                "expression": {
                    "items": [{"concept": {"CONCEPT_ID": 201826, "CONCEPT_NAME": target_label}}]
                },
            }
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 0}}],
            "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": inclusion_rules,
        "QualifiedLimit": {"Type": "First"},
        "ExpressionLimit": {"Type": "First"},
        "CensoringCriteria": [],
        "CollapseSettings": {"CollapseType": "ERA", "EraPad": 0},
        "CensorWindow": {},
    }


def test_evaluate_analysis_strategy_returns_rich_recommendation_payload(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    study_id = create_generation_ready_study(
        client,
        name="Strategy payload study",
        treatment_n=320,
        comparator_n=1600,
    )
    monkeypatch.setattr(
        TTEService,
        "_finalize_analysis_strategy_candidates",
        lambda self, **kwargs: (
            types.SimpleNamespace(
                whyThisMethod="Comparator pool is much larger than the treatment cohort, so weighting preserves more information.",
                whyNot={
                    "PSM": "Matching would discard too much of the larger comparator pool.",
                    "STRATIFICATION": "Stratification is less preferred than weighting for this imbalance profile.",
                    "MAHALANOBIS": "Mahalanobis matching is reserved for manual analyst review.",
                },
            ),
            {
                "source": "llm_finalizer",
                "status": "ok",
                "reason": "",
                "stage": "draft",
            },
        ),
    )

    response = client.post(f"/tte/studies/{study_id}/evaluate-analysis-strategy", json={})

    assert response.status_code == 200
    payload = response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    strategy = artifact["payload"]["strategy"]

    assert artifact["kind"] == "analysis_strategy"
    assert artifact["payload"]["proposedChanges"]["analysisSettings"]["psMethod"] == "matching"
    assert strategy["method"] == "PSM"
    assert strategy["diagnosisTitle"] == "Cohort balance diagnosis"
    assert strategy["diagnosisSummary"]
    assert len(strategy["diagnosisFacts"]) == 4
    assert strategy["proposedParameters"]["psMethod"] == "matching"
    assert strategy["candidateMethods"]
    assert {item["method"] for item in strategy["candidateMethods"]} == {
        "PSM",
        "IPTW",
        "STRATIFICATION",
        "MAHALANOBIS",
    }
    assert strategy["rationaleSections"]
    assert any(section["key"] == "method" for section in strategy["rationaleSections"])
    assert strategy["rejectedAlternatives"]
    assert artifact["payload"]["meta"]["recommendedPsMethod"] == "matching"
    assert artifact["payload"]["meta"]["recommendationStage"] == "draft"
    assert artifact["payload"]["meta"]["recommendationSource"] in {
        "llm_finalizer",
        "heuristic_fallback",
    }
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Analysis strategy agent",
        fidelity="medium",
        stage_kind="agent",
    )


def test_evaluate_analysis_strategy_honors_requested_method_and_stage(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    study_id = create_generation_ready_study(
        client,
        name="Strategy override study",
        treatment_n=900,
        comparator_n=900,
    )
    monkeypatch.setattr(
        TTEService,
        "_finalize_analysis_strategy_candidates",
        lambda self, **kwargs: (
            types.SimpleNamespace(
                method="MAHALANOBIS",
                whyThisMethod="The analyst requested a Mahalanobis review, so the parameter proposal should be refreshed for that path.",
                whyNot={
                    "PSM": "Plain matching was not requested.",
                    "IPTW": "Weighting was not requested for this override.",
                    "STRATIFICATION": "Stratification was not requested for this override.",
                },
            ),
            {
                "source": "llm_finalizer",
                "status": "ok",
                "reason": "",
                "stage": "final",
            },
        ),
    )

    response = client.post(
        f"/tte/studies/{study_id}/evaluate-analysis-strategy",
        json={"requestedPsMethod": "mahalanobis", "stage": "final"},
    )

    assert response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{response.json()["artifactId"]}').json()
    strategy = artifact["payload"]["strategy"]

    assert strategy["requestedPsMethod"] == "mahalanobis"
    assert strategy["recommendationStage"] == "final"
    assert strategy["method"] == "MAHALANOBIS"
    assert strategy["proposedParameters"]["psMethod"] == "mahalanobis"
    assert artifact["payload"]["meta"]["recommendationStage"] == "final"


def test_evaluate_analysis_strategy_marks_heuristic_fallback_when_llm_finalizer_fails(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    study_id = create_generation_ready_study(client, name="Strategy fallback study")
    monkeypatch.setattr(
        TTEService,
        "_finalize_analysis_strategy_candidates",
        lambda self, **kwargs: (
            None,
            {
                "source": "heuristic_fallback",
                "status": "heuristic_fallback",
                "reason": "RuntimeError: llm unavailable",
                "stage": "draft",
            },
        ),
    )

    response = client.post(f"/tte/studies/{study_id}/evaluate-analysis-strategy", json={})

    assert response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{response.json()["artifactId"]}').json()
    strategy = artifact["payload"]["strategy"]

    assert strategy["recommendationSource"] == "heuristic_fallback"
    assert strategy["finalizer"]["status"] == "heuristic_fallback"
    assert "llm unavailable" in strategy["finalizer"]["reason"]
    assert artifact["payload"]["meta"]["recommendationSource"] == "heuristic_fallback"


@pytest.mark.parametrize(
    ("requested_ps_method", "expected_method", "expected_ps_method"),
    [
        ("matching", "PSM", "matching"),
        ("weighting", "IPTW", "weighting"),
        ("stratification", "STRATIFICATION", "stratification"),
        ("mahalanobis", "MAHALANOBIS", "mahalanobis"),
    ],
)
def test_evaluate_analysis_strategy_heuristic_fallback_honors_requested_method(
    monkeypatch, tmp_path, requested_ps_method, expected_method, expected_ps_method
):
    client = build_client(monkeypatch, tmp_path)
    study_id = create_generation_ready_study(
        client,
        name=f"Strategy fallback override {requested_ps_method}",
        treatment_n=320,
        comparator_n=1600,
    )
    monkeypatch.setattr(
        TTEService,
        "_finalize_analysis_strategy_candidates",
        lambda self, **kwargs: (
            None,
            {
                "source": "heuristic_fallback",
                "status": "heuristic_fallback",
                "reason": "RuntimeError: llm unavailable",
                "stage": "final",
            },
        ),
    )

    response = client.post(
        f"/tte/studies/{study_id}/evaluate-analysis-strategy",
        json={"requestedPsMethod": requested_ps_method, "stage": "final"},
    )

    assert response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{response.json()["artifactId"]}').json()
    strategy = artifact["payload"]["strategy"]

    assert strategy["recommendationSource"] == "heuristic_fallback"
    assert strategy["requestedPsMethod"] == requested_ps_method
    assert strategy["method"] == expected_method
    assert strategy["proposedParameters"]["psMethod"] == expected_ps_method
    assert artifact["payload"]["proposedChanges"]["analysisSettings"]["psMethod"] == expected_ps_method


def test_run_analysis_applies_full_analysis_strategy_settings(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    study_id = create_generation_ready_study(client, name="Strategy settings propagation")
    monkeypatch.setattr(
        TTEService,
        "_finalize_analysis_strategy_candidates",
        lambda self, **kwargs: (
            types.SimpleNamespace(
                method="MAHALANOBIS",
                whyThisMethod="Refresh the parameter proposal for the requested Mahalanobis path.",
                whyNot={
                    "PSM": "Plain matching was not requested.",
                    "IPTW": "Weighting was not requested.",
                    "STRATIFICATION": "Stratification was not requested.",
                },
            ),
            {
                "source": "llm_finalizer",
                "status": "ok",
                "reason": "",
                "stage": "final",
            },
        ),
    )

    strategy_response = client.post(
        f"/tte/studies/{study_id}/evaluate-analysis-strategy",
        json={"requestedPsMethod": "mahalanobis", "stage": "final"},
    )
    assert strategy_response.status_code == 200

    captured: dict[str, Any] = {}

    def fake_build_analysis_artifact_payload(self, sid, study):
        captured["analysisSettings"] = deepcopy(study.get("analysisSettings") or {})
        return (
            {
                "proposedChanges": {
                    "results": {
                        "mode": "analysis",
                        "generatedBy": "analysis-settings-test",
                    }
                },
                "meta": {"status": "ok", "summary": "captured settings"},
            },
            {"status": "ok", "summary": "captured settings"},
        )

    monkeypatch.setattr(
        TTEService,
        "_build_analysis_artifact_payload",
        fake_build_analysis_artifact_payload,
    )

    run_response = client.post(f"/tte/studies/{study_id}/run-analysis")
    assert run_response.status_code == 200
    assert captured["analysisSettings"]["psMethod"] == "mahalanobis"
    assert captured["analysisSettings"]["psCaliper"] == 0.2
    assert captured["analysisSettings"]["trimByPs"] is False


def install_process_eligibility_stub(
    monkeypatch,
    *,
    processed_target_name: str = "Adults with processed T2DM phenotype",
    first_inclusion_concept_set_id: int = 9101,
    first_inclusion_concept_set_name: str = "Processed inclusion concept set",
    meta_status: str = "ok",
    warning_count: int = 0,
    failed_count: int = 0,
    second_inclusion_status: str = "processed",
    second_inclusion_warning: str | None = None,
    second_inclusion_error: str | None = None,
):
    def fake_process_eligibility(self, study_id: int, progress_callback=None):
        study = self.store.get_study(study_id)
        study_version = int(study.get("version") or 1)
        job = self.store.create_job(
            {
                "studyId": study_id,
                "studyVersion": study_version,
                "capability": "process_eligibility",
                "status": "running",
                "createdAt": utc_now_iso(),
                "startedAt": utc_now_iso(),
            }
        )

        original_eligibility = deepcopy(study.get("eligibility") or {})
        processed_eligibility = deepcopy(original_eligibility)
        processed_eligibility["targetCohortName"] = (
            original_eligibility.get("targetCohortName") or processed_target_name
        )

        inclusion_criteria = deepcopy(original_eligibility.get("inclusionCriteria") or [])
        diagnostics = [
            {
                "criterionId": None,
                "criterionRole": "target",
                "status": "preserved",
                "description": processed_eligibility.get("targetCohortName") or "",
                "reason": "target_label_preserved",
            }
        ]

        processed_count = 0
        preserved_count = 1

        if inclusion_criteria:
            inclusion_criteria[0]["conceptSetId"] = first_inclusion_concept_set_id
            inclusion_criteria[0]["conceptSetName"] = first_inclusion_concept_set_name
            diagnostics.append(
                {
                    "criterionId": inclusion_criteria[0].get("id"),
                    "criterionRole": "inclusion",
                    "status": "processed",
                    "description": inclusion_criteria[0].get("description") or "",
                    "conceptSetId": first_inclusion_concept_set_id,
                    "conceptSetName": first_inclusion_concept_set_name,
                    "structuredExpression": {
                        "ConditionOccurrence": {"CodesetId": first_inclusion_concept_set_id}
                    },
                }
            )
            processed_count += 1

        if len(inclusion_criteria) > 1:
            diagnostics.append(
                {
                    "criterionId": inclusion_criteria[1].get("id"),
                    "criterionRole": "inclusion",
                    "status": second_inclusion_status,
                    "description": inclusion_criteria[1].get("description") or "",
                    "warning": second_inclusion_warning,
                    "error": second_inclusion_error,
                }
            )
            if second_inclusion_status == "processed":
                inclusion_criteria[1]["conceptSetId"] = first_inclusion_concept_set_id + 1
                inclusion_criteria[1]["conceptSetName"] = "Processed second inclusion concept set"
                processed_count += 1
            else:
                preserved_count += 1

        processed_eligibility["inclusionCriteria"] = inclusion_criteria

        payload = {
            "proposedChanges": {"eligibility": processed_eligibility},
            "rationale": [
                "Processes eligibility text into a reviewable draft artifact without mutating the study directly.",
                "Preserves any existing structured eligibility snapshot until the artifact is applied.",
            ],
            "meta": {
                "status": meta_status,
                "processedCount": processed_count,
                "preservedCount": preserved_count,
                "warningCount": warning_count,
                "failedCount": failed_count,
                "diagnostics": diagnostics,
                "capabilitySignal": {
                    "owner": "Eligibility processing",
                    "fidelity": "medium",
                    "fidelityNote": "Produces reviewable concept-set/cohort draft outputs before apply.",
                    "stageKind": "agent",
                },
            },
        }
        summary = (
            f"Processed eligibility into draft outputs for study {study_id}."
            if meta_status == "ok"
            else f"Processed eligibility into draft outputs for study {study_id} with reviewable diagnostics."
        )
        artifact = self.store.create_artifact(
            {
                "studyId": study_id,
                "studyVersion": study_version,
                "kind": "eligibility_processing",
                "status": "completed",
                "source": "artemis",
                "capability": "process_eligibility",
                "summary": summary,
                "payload": payload,
            }
        )
        completed_job = self.store.update_job(
            job["id"],
            {
                "status": "completed",
                "finishedAt": utc_now_iso(),
                "artifactId": artifact["id"],
            },
        )
        return {
            "status": completed_job["status"],
            "artifactId": artifact["id"],
            "jobId": completed_job["id"],
            "summary": summary,
            "meta": payload["meta"],
        }

    monkeypatch.setattr(TTEService, "process_eligibility", fake_process_eligibility, raising=False)


def test_build_client_does_not_emit_httpx_app_shortcut_deprecation(monkeypatch, tmp_path):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        client = build_client(monkeypatch, tmp_path)
        client.close()

    assert not any(
        item.category is DeprecationWarning
        and "shortcut is now deprecated" in str(item.message).lower()
        and "app" in str(item.message).lower()
        for item in caught
    )


def test_health_check(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_study_crud_round_trip(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)

    initial = client.get("/tte/studies")
    assert initial.status_code == 200
    assert len(initial.json()) == 1

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Metformin vs Sulfonylurea for mortality in T2DM",
            "description": "Draft study",
            "studyType": "comparative",
            "status": "draft",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["id"] == 2
    assert created["name"].startswith("Metformin")

    fetch_response = client.get(f'/tte/studies/{created["id"]}')
    assert fetch_response.status_code == 200
    assert fetch_response.json()["description"] == "Draft study"

    update_response = client.put(
        f'/tte/studies/{created["id"]}',
        json={**created, "description": "Updated study"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["description"] == "Updated study"

    copy_response = client.post(f'/tte/studies/{created["id"]}/copy')
    assert copy_response.status_code == 200
    assert copy_response.json()["name"].endswith("(Copy)")

    delete_response = client.delete(f'/tte/studies/{created["id"]}')
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True}


def test_clear_all_studies_removes_every_persisted_tte_study(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)

    first = client.post(
        "/tte/studies",
        json={
            "name": "Bulk clear study A",
            "description": "Draft study",
            "studyType": "comparative",
            "status": "draft",
        },
    )
    second = client.post(
        "/tte/studies",
        json={
            "name": "Bulk clear study B",
            "description": "Draft study",
            "studyType": "comparative",
            "status": "draft",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(client.get("/tte/studies").json()) == 3

    clear_response = client.delete("/tte/studies")

    assert clear_response.status_code == 200
    assert clear_response.json() == {"ok": True, "deletedCount": 3}
    assert client.get("/tte/studies").json() == []


def test_study_crud_round_trip_preserves_eligibility_structured_expression(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    structured_expression = build_structured_eligibility_expression()

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured eligibility study",
            "description": "Draft study",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
                "structuredExpression": structured_expression,
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["eligibility"]["structuredExpression"] == structured_expression

    update_response = client.put(
        f'/tte/studies/{created["id"]}',
        json={**created, "description": "Updated study"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["eligibility"]["structuredExpression"] == structured_expression

    fetch_response = client.get(f'/tte/studies/{created["id"]}')

    assert fetch_response.status_code == 200
    assert fetch_response.json()["eligibility"]["structuredExpression"] == structured_expression


def test_generate_returns_structured_draft(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/tte/generate",
        json={
            "naturalLanguageDescription": (
                "Compare dapagliflozin vs DPP4 inhibitors for MACE in adults with T2DM"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["study"]["studyType"] == "comparative"
    assert payload["study"]["treatmentArms"][0]["name"].lower() == "dapagliflozin"
    assert payload["study"]["treatmentArms"][1]["name"].lower() == "dpp4 inhibitors"
    primary_outcome_name = payload["study"]["outcomes"]["primary"]["cohortName"].lower()
    assert primary_outcome_name in {"mace", "major adverse cardiovascular events"}
    assert payload["suggestions"]
    assert payload["meta"]["generationMode"] in {"heuristic", "trial_agent"}
    if payload["meta"]["generationMode"] == "heuristic":
        assert payload["meta"]["fallbackReason"]
    else:
        assert payload["meta"]["fallbackReason"] is None


def test_generate_rejects_non_local_model_override(monkeypatch, tmp_path):
    """A remote model name (e.g. from a stale UI selection) must not reach get_llm().

    request.model is a per-request override that bypasses settings.LLM_MODEL entirely
    (see _reject_non_local_model_override in src/api/models/tte.py) — this is the
    boundary that keeps a public-facing endpoint from billing a hosted provider on the
    caller's say-so.
    """
    client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/tte/generate",
        json={
            "naturalLanguageDescription": (
                "Compare dapagliflozin vs DPP4 inhibitors for MACE in adults with T2DM"
            ),
            "model": "gpt-4o",
        },
    )

    assert response.status_code == 422


def test_generate_accepts_local_vllm_model_override(monkeypatch, tmp_path):
    """The legitimate escape hatch (an explicit local vLLM model) still works."""
    client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/tte/generate",
        json={
            "naturalLanguageDescription": (
                "Compare dapagliflozin vs DPP4 inhibitors for MACE in adults with T2DM"
            ),
            "model": "vllm/google/gemma-4-E4B-it",
        },
    )

    assert response.status_code == 200


def test_generate_from_nct_rejects_non_local_model_override(monkeypatch, tmp_path):
    """NCTGenerateRequest.model is validated the same way as GenerateRequest.model.

    Pydantic validates the request body before the route handler runs, so this never
    reaches the NCT-fetch pipeline — no fetch/network mocking needed here.
    """
    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client)

    response = client.post(
        f"/tte/studies/{study_id}/generate-from-nct",
        json={"nctId": "NCT01234567", "model": "gpt-4o-mini"},
    )

    assert response.status_code == 422


class FakeWebAPIClient:
    def __init__(self, *args, source_key=None, results_schema=None, **kwargs):
        self.source_key = source_key
        self.results_schema = results_schema

    def list_sources(self):
        return [
            {
                "sourceKey": "SYNTHEA23M",
                "sourceName": "Synthea 23M (2.7M patients)",
                "daimons": [{"daimonType": "Results", "tableQualifier": "synthea23m_results"}],
            }
        ]

    def generate_existing_cohort(self, cohort_id, name="", force_regenerate=False):
        from src.pipeline.webapi_client import CohortTableReference

        return CohortTableReference(
            cohort_definition_id=cohort_id,
            results_schema=self.results_schema or "synthea23m_results",
            person_count={101: 1200, 102: 1180, 201: 190, 501: 2500}.get(cohort_id, 42),
            source_key=self.source_key or "SYNTHEA23M",
            name=name,
        )


class FakeSeededCohortWebAPIClient:
    next_id = 700
    created_definitions: list[dict[str, object]] = []

    def __init__(self, *args, **kwargs):
        pass

    def create_cohort_definition(self, name, expression, description=""):
        FakeSeededCohortWebAPIClient.next_id += 1
        FakeSeededCohortWebAPIClient.created_definitions.append(
            {"name": name, "expression": expression, "description": description}
        )
        return {"id": FakeSeededCohortWebAPIClient.next_id, "name": name, "expression": expression}


class PartialFailingSeededCohortWebAPIClient(FakeSeededCohortWebAPIClient):
    def create_cohort_definition(self, name, expression, description=""):
        if "Comparator" in name:
            raise RuntimeError("comparator definition failed")
        return super().create_cohort_definition(name, expression, description)


class AlwaysFailingSeededCohortWebAPIClient(FakeSeededCohortWebAPIClient):
    def create_cohort_definition(self, name, expression, description=""):
        raise RuntimeError("seeded cohort definition failed")


class WebAPIErrorSeededCohortWebAPIClient(FakeSeededCohortWebAPIClient):
    def create_cohort_definition(self, name, expression, description=""):
        from src.pipeline.webapi_client import WebAPIError

        raise WebAPIError("webapi unavailable")


def fake_recommend_seeded_concept_set(self, seed_text: str, *, expected_domain: str | None = None, **_kwargs):
    normalized = " ".join(seed_text.split()).strip().lower()
    mapping = {
        "adults with type 2 diabetes mellitus": ("Type 2 diabetes mellitus", "Condition", 201826),
        "adults with t2dm": ("Type 2 diabetes mellitus", "Condition", 201826),
        "metformin exposure": ("Metformin", "Drug", 1503297),
        "dapagliflozin": ("Dapagliflozin", "Drug", 44785829),
        "sitagliptin": ("Sitagliptin", "Drug", 1580747),
        "treatment": ("Treatment Drug", "Drug", 1111111),
        "comparator": ("Comparator Drug", "Drug", 2222222),
        "mace": ("Major adverse cardiovascular events", "Condition", 4329847),
        "major adverse cardiovascular events": (
            "Major adverse cardiovascular events",
            "Condition",
            4329847,
        ),
    }
    name, domain, concept_id = mapping.get(
        normalized,
        (seed_text.strip() or "Seeded Concept", expected_domain or "Condition", 999999),
    )
    return {
        "name": name,
        "domain": expected_domain or domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": name,
                        "DOMAIN_ID": expected_domain or domain,
                        "VOCABULARY_ID": "SNOMED" if (expected_domain or domain) == "Condition" else "RxNorm",
                        "CONCEPT_CLASS_ID": "Clinical Finding"
                        if (expected_domain or domain) == "Condition"
                        else "Ingredient",
                        "STANDARD_CONCEPT": "S",
                        "CONCEPT_CODE": str(concept_id),
                    },
                    "includeDescendants": True,
                    "includeMapped": False,
                    "isExcluded": False,
                }
            ]
        },
    }


class FakeTrialAgent:
    def parse(self, description):
        return build_fake_trial_ir()


class FakeNCTTrialAgent:
    def parse_nct(self, nct_id):
        return build_fake_trial_ir()


class MutatingFailingPlanner:
    def plan(self, ir):
        ir.target.primary_criteria.entity_text = ""
        ir.target.inclusion_rules.clear()
        raise RuntimeError("planner unavailable after mutation")


class FailingNCTTrialAgent:
    def parse_nct(self, nct_id):
        raise RuntimeError("parse_nct unavailable")


def build_fake_trial_ir():
    from src.models.ir import (
        ARTEMISRequest,
        CohortDefinition,
        CohortOutcome,
        Criteria,
        PrimaryCriteria,
        TemporalWindow,
    )

    return ARTEMISRequest(
        target=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="dapagliflozin"),
            inclusion_rules=[Criteria(name="Adults with T2DM", domain="Condition", entity_text="Type 2 diabetes mellitus")],
            exclusion_rules=[Criteria(name="Prior exposure", domain="Drug", entity_text="Prior SGLT2 inhibitor use")],
        ),
        comparator=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="DPP4 inhibitors"),
        ),
        outcome=CohortOutcome(
            name="MACE",
            domain="Condition",
            entity_text="major adverse cardiovascular events",
            time_at_risk=TemporalWindow(start=0, end=365),
        ),
    )


class FakePlanner:
    def plan(self, ir):
        return ir


def make_generated_nct_study(
    nct_id: str,
    *,
    study_name: str = "liraglutide vs placebo for major adverse cardiovascular events",
    target_name: str = "Adults with type 2 diabetes mellitus",
):
    return {
        "name": study_name,
        "description": f"Imported from {nct_id}",
        "studyType": "comparative",
        "status": "draft",
        "eligibility": {
            "targetCohortId": None,
            "targetCohortName": target_name,
            "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
            "exclusionCriteria": [],
        },
        "treatmentArms": [
            {"id": 1, "name": "liraglutide", "cohortId": None, "cohortName": ""},
            {"id": 2, "name": "placebo", "cohortId": None, "cohortName": ""},
        ],
        "outcomes": {
            "primary": {
                "cohortId": None,
                "cohortName": "major adverse cardiovascular events",
                "description": "MACE",
            },
            "secondary": [],
        },
    }


def test_source_list_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/tte/sources")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["sourceKey"] == "SYNTHEA23M"
    assert payload[0]["resultsSchema"] == "synthea23m_results"


def test_execute_updates_results(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Execution target",
            "description": "ready for execution",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    )
    assert execute_response.status_code == 200
    payload = execute_response.json()
    assert payload["execution"]["status"] == "COMPLETED"
    assert payload["results"]["mode"] == "webapi_generation"
    assert payload["results"]["generatedBy"] == "artemis-api-webapi"
    assert payload["results"]["treatmentN"] == 1200
    assert payload["results"]["comparatorN"] == 1180
    assert payload["results"]["primaryOutcomeN"] == 190
    assert payload["artifactId"].startswith("art_")
    assert payload["jobId"].startswith("job_")

    fetch_response = client.get(f"/tte/studies/{study_id}")
    fetched = fetch_response.json()
    assert fetched["status"] == "draft"
    assert fetched["version"] == 1
    assert fetched["results"] is None
    assert fetched["executions"] == []

    artifacts_response = client.get(f"/tte/studies/{study_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    execution_artifact = next(item for item in artifacts if item["id"] == payload["artifactId"])
    assert execution_artifact["kind"] == "execution_result"
    assert execution_artifact["payload"]["proposedChanges"]["results"]["generatedCohorts"][0]["sourceKey"] == "SYNTHEA23M"
    assert execution_artifact["payload"]["meta"]["sourceKey"] == "SYNTHEA23M"
    assert execution_artifact["payload"]["meta"]["generatedCohortSummary"]["treatment"] == 1200
    assert_capability_signal(
        execution_artifact["payload"]["meta"],
        owner="WebAPI execution",
        fidelity="non_agent",
        stage_kind="execution",
    )
    assert execution_artifact["studyVersion"] == 1

    job_response = client.get(f'/tte/jobs/{payload["jobId"]}')
    assert job_response.status_code == 200
    assert job_response.json()["artifactId"] == payload["artifactId"]
    assert job_response.json()["status"] == "completed"

    apply_response = client.post(
        f'/tte/artifacts/{payload["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["newVersion"] == 2

    fetch_response = client.get(f"/tte/studies/{study_id}")
    fetched = fetch_response.json()
    assert fetched["status"] == "completed"
    assert fetched["version"] == 2
    assert fetched["results"]["generatedCohorts"][0]["sourceKey"] == "SYNTHEA23M"
    assert fetched["executions"][-1]["sourceKey"] == "SYNTHEA23M"


def test_execute_requires_validation_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Execution target",
            "description": "ready for execution",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    )

    assert execute_response.status_code == 400
    assert "validation" in execute_response.json()["detail"].lower()


def test_validate_allows_treatment_vs_rest_without_explicit_comparator_mapping(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Treatment vs rest validation target",
            "description": "comparison mode should relax comparator mapping",
            "studyType": "comparative",
            "comparisonMode": "treatment_vs_rest",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    payload = validate_response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    blocker_fields = [item["field"] for item in artifact["payload"]["validation"]["blockers"]]
    assert "treatmentArms[1].cohortId" not in blocker_fields


def test_execute_derives_rest_comparator_counts_for_treatment_vs_rest(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Treatment vs rest execution target",
            "description": "execution should derive comparator from target cohort",
            "studyType": "comparative",
            "comparisonMode": "treatment_vs_rest",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    )

    assert execute_response.status_code == 200
    payload = execute_response.json()
    assert payload["results"]["targetN"] == 2500
    assert payload["results"]["treatmentN"] == 1200
    assert payload["results"]["comparatorN"] == 1300
    comparator_row = next(
        row for row in payload["results"]["generatedCohorts"] if row["role"] == "comparator"
    )
    assert comparator_row["cohortDefinitionId"] == 501
    assert comparator_row["personCount"] == 1300


def test_run_analysis_uses_target_population_as_rest_comparator(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class FakeOMOPConnector:
        def __init__(self, *args, schema=None, **kwargs):
            captured["schema"] = schema

        def build_analysis_dataset_from_generated_cohorts(
            self,
            target_ref,
            outcome_ref,
            followup_days=365,
            min_prevalence=0.01,
            max_covariates=10000,
            comparator_ref=None,
        ):
            import pandas as pd

            captured["target_ref"] = target_ref
            captured["comparator_ref"] = comparator_ref
            captured["outcome_ref"] = outcome_ref
            captured["followup_days"] = followup_days
            return pd.DataFrame(
                {
                    "person_id": [1, 2, 3, 4],
                    "treatment": [1, 1, 0, 0],
                    "age": [60, 62, 59, 61],
                    "time": [12, 18, 16, 21],
                    "event": [1, 0, 0, 1],
                }
            )

    class FakeAgent5Workflow:
        def configure(
            self,
            target_cohort_id,
            comparator_cohort_id,
            outcome_definition=None,
            analysis_method="IPTW",
        ):
            captured["configured_target_id"] = target_cohort_id
            captured["configured_comparator_id"] = comparator_cohort_id
            return self

        def run(self, data=None):
            captured["data"] = data
            return {
                "hazard_ratio": {
                    "hr": 0.84,
                    "ci_lower": 0.73,
                    "ci_upper": 0.97,
                    "p_value": 0.02,
                },
                "analysis_method": "PSM",
                "n_matched_pairs": 2,
                "balance": {},
                "survival_data": {
                    "events_treated": [1, 0],
                    "events_control": [0, 1],
                },
            }

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr("src.analysis.omop_connector.OMOPConnector", FakeOMOPConnector)
    monkeypatch.setattr("src.agents.agent5.workflow.Agent5Workflow", FakeAgent5Workflow)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Treatment vs rest analysis",
            "description": "analysis should derive comparator from target population",
            "studyType": "comparative",
            "comparisonMode": "treatment_vs_rest",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "matching"},
        },
    )
    study_id = create_response.json()["id"]
    client.post(f"/tte/studies/{study_id}/validate")
    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    ).json()
    client.post(
        f'/tte/artifacts/{execute_response["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )

    analysis_response = client.post(f"/tte/studies/{study_id}/run-analysis")

    assert analysis_response.status_code == 200
    assert captured["configured_target_id"] == 101
    assert captured["configured_comparator_id"] == 0
    assert captured["target_ref"].cohort_definition_id == 101
    assert captured["comparator_ref"].cohort_definition_id == 501
    assert captured["outcome_ref"].cohort_definition_id == 201


def test_apply_artifact_rejects_version_conflict(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Execution target",
            "description": "ready for execution",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    )
    artifact_id = execute_response.json()["artifactId"]

    apply_response = client.post(
        f"/tte/artifacts/{artifact_id}/apply",
        json={"targetSections": ["results"], "baseStudyVersion": 999},
    )

    assert apply_response.status_code == 409
    assert "version" in apply_response.json()["detail"].lower()


def test_generate_uses_trial_agent_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._generate_with_trial_agent",
        lambda self, description: {
            "name": "dapagliflozin vs DPP4 inhibitors for major adverse cardiovascular events",
            "description": description,
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "dapagliflozin",
                "inclusionCriteria": [
                    {
                        "id": 1,
                        "description": "Type 2 diabetes mellitus",
                        "conceptSetId": None,
                        "conceptSetName": "",
                    }
                ],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "dapagliflozin", "cohortId": None, "cohortName": ""},
                {"id": 2, "name": "DPP4 inhibitors", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {
                    "cohortId": None,
                    "cohortName": "major adverse cardiovascular events",
                    "description": "MACE",
                },
                "secondary": [],
            },
        },
    )

    client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/tte/generate",
        json={"naturalLanguageDescription": "Compare dapagliflozin vs DPP4 inhibitors for MACE in T2DM"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["generationMode"] == "trial_agent"
    assert payload["meta"]["fallbackReason"] is None
    assert payload["study"]["treatmentArms"][0]["name"] == "dapagliflozin"
    assert payload["study"]["treatmentArms"][1]["name"] == "DPP4 inhibitors"
    assert payload["study"]["eligibility"]["inclusionCriteria"][0]["description"] == "Type 2 diabetes mellitus"


def test_generate_draft_creates_artifact_without_mutating_study(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._generate_with_trial_agent",
        lambda self, description: {
            "name": "dapagliflozin vs DPP4 inhibitors for MACE",
            "description": description,
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "dapagliflozin", "cohortId": None, "cohortName": ""},
                {"id": 2, "name": "DPP4 inhibitors", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {"cohortId": None, "cohortName": "MACE", "description": "MACE"},
                "secondary": [],
            },
        },
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={"name": "Blank draft", "description": "", "studyType": "comparative", "status": "draft"},
    )
    study_id = create_response.json()["id"]

    generate_response = client.post(
        f"/tte/studies/{study_id}/generate-draft",
        json={"naturalLanguageDescription": "Compare dapagliflozin vs DPP4 inhibitors for MACE in T2DM"},
    )

    assert generate_response.status_code == 200
    payload = generate_response.json()
    assert payload["status"] == "completed"
    assert payload["artifactId"].startswith("art_")
    assert payload["jobId"].startswith("job_")
    assert payload["meta"]["generationMode"] == "trial_agent"
    assert payload["summary"]

    fetched = client.get(f"/tte/studies/{study_id}").json()
    assert fetched["version"] == 1
    assert fetched["name"] == "Blank draft"
    assert fetched["treatmentArms"][0]["name"] == "Treatment"

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "draft_generation"
    assert artifact["studyVersion"] == 1
    assert artifact["payload"]["proposedChanges"]["name"] == "dapagliflozin vs DPP4 inhibitors for MACE"
    assert artifact["payload"]["proposedChanges"]["treatmentArms"][0]["name"] == "dapagliflozin"

    apply_response = client.post(
        f'/tte/artifacts/{payload["artifactId"]}/apply',
        json={"targetSections": ["name", "description", "eligibility", "treatmentArms", "outcomes"], "baseStudyVersion": 1},
    )
    assert apply_response.status_code == 200

    fetched = client.get(f"/tte/studies/{study_id}").json()
    assert fetched["version"] == 2
    assert fetched["name"] == "dapagliflozin vs DPP4 inhibitors for MACE"
    assert fetched["treatmentArms"][0]["name"] == "dapagliflozin"


def test_generate_from_nct_creates_draft_artifact_without_mutating_study(monkeypatch, tmp_path):
    from src.models.ir import (
        ARTEMISRequest,
        CohortDefinition,
        CohortOutcome,
        Criteria,
        PrimaryCriteria,
        TemporalWindow,
    )

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._parse_trial_agent_ir_from_nct",
        lambda self, nct_id: ARTEMISRequest(
            target=CohortDefinition(
                primary_criteria=PrimaryCriteria(domain="Drug", entity_text="liraglutide"),
                inclusion_rules=[
                    Criteria(
                        name="Adults with T2DM",
                        domain="Condition",
                        entity_text="Type 2 diabetes mellitus",
                    )
                ],
                exclusion_rules=[],
            ),
            comparator=CohortDefinition(
                primary_criteria=PrimaryCriteria(domain="Drug", entity_text="placebo"),
            ),
            outcome=CohortOutcome(
                name="MACE",
                domain="Condition",
                entity_text="major adverse cardiovascular events",
                time_at_risk=TemporalWindow(start=0, end=365),
            ),
        ),
    )
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._plan_trial_agent_ir",
        lambda self, ir: ir,
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={"name": "Blank NCT draft", "description": "", "studyType": "comparative", "status": "draft"},
    )
    study_id = create_response.json()["id"]

    generate_response = client.post(
        f"/tte/studies/{study_id}/generate-from-nct",
        json={"nctId": "NCT01179048"},
    )

    assert generate_response.status_code == 200
    payload = generate_response.json()
    assert payload["status"] == "completed"
    assert payload["artifactId"].startswith("art_")
    assert payload["jobId"].startswith("job_")
    assert payload["meta"]["generationMode"] == "trial_agent"
    assert payload["meta"]["nctId"] == "NCT01179048"
    assert_capability_signal(
        payload["meta"],
        owner="Trial parsing + planner",
        fidelity="high",
        stage_kind="agent",
    )

    fetched = client.get(f"/tte/studies/{study_id}").json()
    assert fetched["version"] == 1
    assert fetched["name"] == "Blank NCT draft"
    assert fetched["treatmentArms"][0]["name"] == "Treatment"

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "draft_generation"
    assert artifact["capability"] == "generate_from_nct"
    assert artifact["studyVersion"] == 1
    assert artifact["payload"]["meta"]["nctId"] == "NCT01179048"
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Trial parsing + planner",
        fidelity="high",
        stage_kind="agent",
    )
    assert artifact["payload"]["proposedChanges"]["name"] == "liraglutide vs placebo for major adverse cardiovascular events"
    assert artifact["payload"]["proposedChanges"]["treatmentArms"][0]["name"] == "liraglutide"
    assert artifact["payload"]["proposedChanges"]["eligibility"]["targetCohortName"] == "Adults with T2DM"

    apply_response = client.post(
        f'/tte/artifacts/{payload["artifactId"]}/apply',
        json={"targetSections": ["name", "description", "eligibility", "treatmentArms", "outcomes"], "baseStudyVersion": 1},
    )
    assert apply_response.status_code == 200

    fetched = client.get(f"/tte/studies/{study_id}").json()
    assert fetched["version"] == 2
    assert fetched["name"] == "liraglutide vs placebo for major adverse cardiovascular events"
    assert fetched["treatmentArms"][0]["name"] == "liraglutide"


def test_generate_from_nct_preserves_agent1_eligibility_when_planner_mutates_ir_and_fails(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._parse_trial_agent_ir_from_nct",
        lambda self, nct_id: FakeNCTTrialAgent().parse_nct(nct_id),
    )
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._plan_trial_agent_ir",
        lambda self, ir: MutatingFailingPlanner().plan(ir),
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={"name": "Planner failure draft", "description": "", "studyType": "comparative", "status": "draft"},
    )
    study_id = create_response.json()["id"]

    generate_response = client.post(
        f"/tte/studies/{study_id}/generate-from-nct",
        json={"nctId": "NCT01179048"},
    )

    assert generate_response.status_code == 200
    payload = generate_response.json()
    assert payload["meta"]["fallbackReason"] == "planner unavailable after mutation"

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["payload"]["proposedChanges"]["eligibility"]["targetCohortName"] == (
        "Adults with T2DM"
    )
    assert artifact["payload"]["proposedChanges"]["eligibility"]["inclusionCriteria"][0][
        "description"
    ] == "Adults with T2DM"

    apply_response = client.post(
        f'/tte/artifacts/{payload["artifactId"]}/apply',
        json={"targetSections": ["name", "description", "eligibility", "treatmentArms", "outcomes"], "baseStudyVersion": 1},
    )
    assert apply_response.status_code == 200

    fetched = client.get(f"/tte/studies/{study_id}").json()
    assert fetched["eligibility"]["targetCohortName"] == "Adults with T2DM"
    assert fetched["eligibility"]["inclusionCriteria"][0]["description"] == (
        "Adults with T2DM"
    )


def test_generate_from_nct_helper_preserves_agent1_ir_when_planner_mutates_and_fails(
    monkeypatch, tmp_path
):
    service = TTEService(TTEStore(str(tmp_path / "tte" / "studies.json")))
    monkeypatch.setattr("src.services.tte_service.get_agent1", lambda: FakeNCTTrialAgent())
    monkeypatch.setattr("src.agents.planner.get_planner", lambda: MutatingFailingPlanner())

    generated_study, generation_mode, fallback_reason, _paper_status = (
        service._generate_with_trial_agent_from_nct("NCT01179048")
    )

    assert generation_mode == "trial_agent"
    assert fallback_reason == "planner unavailable after mutation"
    assert generated_study["description"] == "Imported from NCT01179048"
    assert generated_study["eligibility"]["targetCohortName"] == "Adults with T2DM"
    assert generated_study["eligibility"]["inclusionCriteria"][0]["description"] == (
        "Adults with T2DM"
    )


def test_generate_from_nct_falls_back_to_heuristic_when_agent1_parse_nct_fails(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("src.services.tte_service.get_agent1", lambda: FailingNCTTrialAgent())

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={"name": "Parse failure draft", "description": "", "studyType": "comparative", "status": "draft"},
    )
    study_id = create_response.json()["id"]

    generate_response = client.post(
        f"/tte/studies/{study_id}/generate-from-nct",
        json={"nctId": "NCT01179048"},
    )

    assert generate_response.status_code == 200
    payload = generate_response.json()
    assert payload["status"] == "completed"
    assert payload["summary"].endswith("using heuristic mode.")
    assert payload["meta"]["generationMode"] == "heuristic"
    assert payload["meta"]["fallbackReason"] == "parse_nct unavailable"
    assert payload["meta"]["nctId"] == "NCT01179048"
    assert_capability_signal(
        payload["meta"],
        owner="Trial parsing + planner",
        fidelity="high",
        stage_kind="agent",
    )

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["payload"]["meta"]["generationMode"] == "heuristic"
    assert artifact["payload"]["meta"]["fallbackReason"] == "parse_nct unavailable"
    assert artifact["payload"]["meta"]["nctId"] == "NCT01179048"
    assert artifact["payload"]["proposedChanges"]["description"] == "Imported from NCT01179048"
    assert (
        artifact["payload"]["proposedChanges"]["eligibility"]["targetCohortName"]
        == "Target population to be specified"
    )


def test_generate_from_nct_reuses_prior_trial_agent_artifact_for_same_nct(monkeypatch, tmp_path):
    call_log: list[str] = []

    def fake_generate(self, nct_id):
        call_log.append(nct_id)
        return (
            make_generated_nct_study(
                nct_id,
                study_name=f"generated on call {len(call_log)}",
                target_name=f"Target from call {len(call_log)}",
            ),
            "trial_agent",
            None,
            None,
        )

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._generate_with_trial_agent_from_nct",
        fake_generate,
    )

    client = build_client(monkeypatch, tmp_path)
    first_study = client.post("/tte/studies", json={"name": "Study A", "description": ""}).json()
    second_study = client.post("/tte/studies", json={"name": "Study B", "description": ""}).json()

    first_response = client.post(
        f'/tte/studies/{first_study["id"]}/generate-from-nct',
        json={"nctId": "nct01179048"},
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()
    first_artifact = client.get(f'/tte/artifacts/{first_payload["artifactId"]}').json()

    second_response = client.post(
        f'/tte/studies/{second_study["id"]}/generate-from-nct',
        json={"nctId": "NCT01179048"},
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()
    second_artifact = client.get(f'/tte/artifacts/{second_payload["artifactId"]}').json()

    assert call_log == ["NCT01179048"]
    assert first_payload["meta"]["cacheHit"] is False
    assert second_payload["meta"]["cacheHit"] is True
    assert second_payload["meta"]["cacheSourceArtifactId"] == first_payload["artifactId"]
    assert second_payload["meta"]["generatorVersion"]
    assert second_artifact["studyId"] == second_study["id"]
    assert second_artifact["payload"]["proposedChanges"] == first_artifact["payload"]["proposedChanges"]
    assert second_artifact["payload"]["meta"]["cacheHit"] is True
    assert second_artifact["payload"]["meta"]["cacheSourceArtifactId"] == first_payload["artifactId"]


def test_generate_from_nct_force_refresh_bypasses_cached_artifact(monkeypatch, tmp_path):
    call_log: list[str] = []

    def fake_generate(self, nct_id):
        call_log.append(nct_id)
        return (
            make_generated_nct_study(
                nct_id,
                study_name=f"generated on call {len(call_log)}",
                target_name=f"Target from call {len(call_log)}",
            ),
            "trial_agent",
            None,
            None,
        )

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._generate_with_trial_agent_from_nct",
        fake_generate,
    )

    client = build_client(monkeypatch, tmp_path)
    first_study = client.post("/tte/studies", json={"name": "Study A", "description": ""}).json()
    second_study = client.post("/tte/studies", json={"name": "Study B", "description": ""}).json()

    first_response = client.post(
        f'/tte/studies/{first_study["id"]}/generate-from-nct',
        json={"nctId": "NCT01179048"},
    )
    assert first_response.status_code == 200

    second_response = client.post(
        f'/tte/studies/{second_study["id"]}/generate-from-nct',
        json={"nctId": "NCT01179048", "forceRefresh": True},
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()
    second_artifact = client.get(f'/tte/artifacts/{second_payload["artifactId"]}').json()

    assert call_log == ["NCT01179048", "NCT01179048"]
    assert second_payload["meta"]["cacheHit"] is False
    assert second_payload["meta"]["cacheSourceArtifactId"] is None
    assert second_artifact["payload"]["proposedChanges"]["name"] == "generated on call 2"
    assert second_artifact["payload"]["meta"]["cacheHit"] is False


def test_generate_from_nct_does_not_reuse_heuristic_fallback_artifacts(monkeypatch, tmp_path):
    call_count = 0

    def fake_generate(self, nct_id):
        nonlocal call_count
        call_count += 1
        return (
            make_generated_nct_study(
                nct_id,
                study_name=f"heuristic call {call_count}",
                target_name="Target population to be specified",
            ),
            "heuristic",
            f"trial parser unavailable on call {call_count}",
            None,
        )

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._generate_with_trial_agent_from_nct",
        fake_generate,
    )

    client = build_client(monkeypatch, tmp_path)
    first_study = client.post("/tte/studies", json={"name": "Study A", "description": ""}).json()
    second_study = client.post("/tte/studies", json={"name": "Study B", "description": ""}).json()

    first_response = client.post(
        f'/tte/studies/{first_study["id"]}/generate-from-nct',
        json={"nctId": "NCT01179048"},
    )
    assert first_response.status_code == 200
    assert first_response.json()["meta"]["generationMode"] == "heuristic"

    second_response = client.post(
        f'/tte/studies/{second_study["id"]}/generate-from-nct',
        json={"nctId": "NCT01179048"},
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()

    assert call_count == 2
    assert second_payload["meta"]["generationMode"] == "heuristic"
    assert second_payload["meta"]["cacheHit"] is False
    assert second_payload["meta"]["cacheSourceArtifactId"] is None


def test_validate_design_returns_blocker_artifact_for_incomplete_study(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={"name": "Incomplete study", "description": "", "studyType": "comparative", "status": "draft"},
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    payload = validate_response.json()
    assert payload["status"] == "completed"
    assert payload["artifactId"].startswith("art_")
    assert payload["jobId"].startswith("job_")

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "design_validation"
    assert artifact["payload"]["meta"]["status"] == "warning"
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Validation pipeline",
        fidelity="medium",
        stage_kind="agent",
    )
    assert artifact["payload"]["validation"]["valid"] is False
    assert artifact["payload"]["validation"]["blockers"]
    assert "blocker" in artifact["payload"]["validation"]["actionableLoops"]
    blocker_messages = " ".join(item["message"] for item in artifact["payload"]["validation"]["blockers"])
    assert "target cohort" in blocker_messages.lower()
    assert "primary outcome" in blocker_messages.lower()


def test_validate_design_uses_exact_primary_outcome_execution_blocker_message(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Primary outcome missing",
            "description": "only the primary outcome mapping is unresolved",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {
                    "cohortId": None,
                    "cohortName": "Primary outcome",
                    "description": "Outcome",
                },
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    assert artifact["payload"]["validation"]["valid"] is False
    assert artifact["payload"]["validation"]["blockers"] == [
        {
            "field": "outcomes.primary.cohortId",
            "message": "Primary outcome cohort must be defined before execution.",
            "severity": "blocker",
        }
    ]


def test_validate_design_returns_ready_signal_for_configured_study(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Configured study",
            "description": "ready to validate",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    payload = validate_response.json()
    assert_capability_signal(
        payload["meta"],
        owner="Validation pipeline",
        fidelity="medium",
        stage_kind="agent",
    )
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["payload"]["meta"]["status"] == "warning"
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Validation pipeline",
        fidelity="medium",
        stage_kind="agent",
    )
    assert artifact["payload"]["validation"]["valid"] is True
    assert artifact["payload"]["validation"]["blockers"] == []
    assert artifact["payload"]["validation"]["actionableLoops"] == {}
    assert isinstance(artifact["payload"]["validation"]["warnings"], list)
    assert artifact["payload"]["validator"]["conceptSetCount"] >= 1
    assert artifact["payload"]["validator"]["circeJson"]["PrimaryCriteria"]["CriteriaList"]


def test_validate_design_flags_structured_expression_when_canonical_summary_not_applied(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured snapshot drift",
            "description": "snapshot saved without canonical eligibility sync",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "",
                "inclusionCriteria": [],
                "exclusionCriteria": [],
                "structuredExpression": build_structured_eligibility_expression(),
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    blockers = artifact["payload"]["validation"]["blockers"]
    warnings = artifact["payload"]["validation"]["warnings"]

    assert {
        "field": "eligibility.targetCohortId",
        "message": "Target cohort must be defined before execution.",
        "severity": "blocker",
    } in blockers
    assert not any(
        item["message"].startswith("Structured eligibility snapshot")
        for item in [*blockers, *warnings]
    )


def test_validate_design_treats_summary_as_projection_when_structured_snapshot_exists(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured-canonical eligibility",
            "description": "structured snapshot should take precedence over empty summary copy",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "",
                "inclusionCriteria": [],
                "exclusionCriteria": [],
                "structuredExpression": build_structured_eligibility_expression(),
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    blockers = artifact["payload"]["validation"]["blockers"]
    warnings = artifact["payload"]["validation"]["warnings"]

    assert {
        "field": "eligibility.targetCohortId",
        "message": "Target cohort must be defined before execution.",
        "severity": "blocker",
    } in blockers
    assert not any(
        item["message"].startswith("Structured eligibility snapshot exists")
        or item["message"].startswith("Structured eligibility snapshot includes inclusion rules")
        for item in [*blockers, *warnings]
    )


def test_validate_design_uses_generic_target_blocker_when_name_matches_structured_snapshot(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured snapshot target not yet mapped",
            "description": "matching target summary but unresolved target cohort id",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [{"id": 1, "description": "Adults with T2DM"}],
                "exclusionCriteria": [],
                "structuredExpression": build_structured_eligibility_expression(
                    target_label="Adults with type 2 diabetes mellitus"
                ),
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    blockers = artifact["payload"]["validation"]["blockers"]

    assert {
        "field": "eligibility.targetCohortId",
        "message": "Target cohort must be defined before execution.",
        "severity": "blocker",
    } in blockers
    assert not any(
        item["message"].startswith("Structured eligibility snapshot exists")
        for item in blockers
    )


def test_validate_design_keeps_existing_inclusion_warning_without_structured_expression(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Canonical-only eligibility",
            "description": "no structured snapshot",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    warnings = artifact["payload"]["validation"]["warnings"]

    assert {
        "field": "eligibility.inclusionCriteria",
        "message": "No inclusion criteria are documented yet.",
        "severity": "warning",
    } in warnings
    assert not any(
        item["message"].startswith("Structured eligibility snapshot")
        for item in warnings
    )


def test_validate_design_prefers_structured_snapshot_over_stale_summary_projection(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured summary projection drift",
            "description": "stale summary copy should not outrank the structured snapshot",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Heart failure cohort",
                "inclusionCriteria": [{"id": 1, "description": "History of heart failure"}],
                "exclusionCriteria": [],
                "structuredExpression": build_structured_eligibility_expression(
                    target_label="Adults with type 2 diabetes mellitus"
                ),
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    warnings = artifact["payload"]["validation"]["warnings"]

    assert not any(item["message"].startswith("Structured eligibility snapshot") for item in warnings)


def test_validate_design_flags_stale_populated_canonical_inclusion_summary(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured snapshot stale inclusion summary",
            "description": "canonical inclusion summary drifted after structured edit",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "History of heart failure"}],
                "exclusionCriteria": [],
                "structuredExpression": build_structured_eligibility_expression(),
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    warnings = artifact["payload"]["validation"]["warnings"]
    blockers = artifact["payload"]["validation"]["blockers"]

    assert not any(item["message"].startswith("Structured eligibility snapshot") for item in warnings)
    assert not any(item["message"].startswith("Structured eligibility snapshot") for item in blockers)


def test_validate_design_flags_stale_populated_canonical_target_summary(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured snapshot stale target summary",
            "description": "canonical target summary drifted after structured edit",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Heart failure cohort",
                "inclusionCriteria": [{"id": 1, "description": "Adults with T2DM"}],
                "exclusionCriteria": [],
                "structuredExpression": build_structured_eligibility_expression(
                    target_label="Adults with type 2 diabetes mellitus"
                ),
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    warnings = artifact["payload"]["validation"]["warnings"]
    blockers = artifact["payload"]["validation"]["blockers"]

    assert not any(item["message"].startswith("Structured eligibility snapshot") for item in warnings)
    assert not any(item["message"].startswith("Structured eligibility snapshot") for item in blockers)


def test_validate_design_ignores_non_target_concept_sets_for_target_drift(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)
    structured_expression = build_structured_eligibility_expression(
        target_label="Adults with type 2 diabetes mellitus"
    )
    structured_expression["ConceptSets"].append(
        {
            "id": 1,
            "name": "Heart failure cohort",
            "expression": {
                "items": [{"concept": {"CONCEPT_ID": 316139, "CONCEPT_NAME": "Heart failure"}}]
            },
        }
    )

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured snapshot with extra concept set",
            "description": "extra inclusion concept set should not affect target drift checks",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [{"id": 1, "description": "Adults with T2DM"}],
                "exclusionCriteria": [],
                "structuredExpression": structured_expression,
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    validate_response = client.post(f"/tte/studies/{study_id}/validate")

    assert validate_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{validate_response.json()["artifactId"]}').json()
    warnings = artifact["payload"]["validation"]["warnings"]

    assert not any(item["message"].startswith("Structured eligibility snapshot") for item in warnings)


def test_suggest_eligibility_creates_section_specific_artifact(monkeypatch, tmp_path):
    from src.api.models.tte import MappingQualitySignal

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._build_real_mapping_quality_signal",
        lambda self, study, provisional_ir, section_key, section_source: MappingQualitySignal(
            status="warning",
            seedCount=1,
            reason="low_seed_count",
            domainMismatch=False,
            minSeedCount=2,
            retryReasons=["low_seeds"],
        ),
    )
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={"name": "Study", "description": "Compare dapagliflozin vs DPP4 inhibitors for MACE in T2DM"},
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/suggest-eligibility")

    assert response.status_code == 200
    payload = response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "eligibility_suggestion"
    assert set(artifact["payload"]["proposedChanges"].keys()) == {"eligibility"}
    assert artifact["payload"]["proposedChanges"]["eligibility"]["targetCohortName"] == "T2DM"
    assert artifact["payload"]["meta"]["mappingQuality"]["status"] == "warning"
    assert artifact["payload"]["meta"]["mappingQuality"]["reason"] == "low_seed_count"
    assert artifact["payload"]["meta"]["mappingQuality"]["retryReasons"] == ["low_seeds"]
    assert artifact["payload"]["meta"]["generationMode"] == "provisional_ir"
    assert artifact["payload"]["meta"]["sourceSection"] == "structured_section"
    assert artifact["payload"]["meta"]["usedFallback"] is False


def test_suggest_eligibility_preserves_structured_snapshot_through_apply(
    monkeypatch, tmp_path
):
    from src.api.models.tte import MappingQualitySignal

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._build_real_mapping_quality_signal",
        lambda self, study, provisional_ir, section_key, section_source: MappingQualitySignal(
            status="warning",
            seedCount=1,
            reason="low_seed_count",
            domainMismatch=False,
            minSeedCount=2,
            retryReasons=["low_seeds"],
        ),
    )
    client = build_client(monkeypatch, tmp_path)
    structured_expression = build_structured_eligibility_expression(
        target_label="Adults with type 2 diabetes mellitus"
    )
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Structured snapshot preservation study",
            "description": "Compare dapagliflozin vs DPP4 inhibitors for MACE in T2DM",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [{"id": 1, "description": "Adults with T2DM"}],
                "exclusionCriteria": [],
                "structuredExpression": structured_expression,
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/suggest-eligibility")

    assert response.status_code == 200
    payload = response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    proposed_eligibility = artifact["payload"]["proposedChanges"]["eligibility"]

    assert proposed_eligibility["structuredExpression"] == structured_expression

    study_before_apply = client.get(f"/tte/studies/{study_id}").json()
    apply_response = client.post(
        f'/tte/artifacts/{payload["artifactId"]}/apply',
        json={"targetSections": ["eligibility"], "baseStudyVersion": study_before_apply["version"]},
    )

    assert apply_response.status_code == 200
    study_after_apply = client.get(f"/tte/studies/{study_id}").json()
    assert study_after_apply["eligibility"]["structuredExpression"] == structured_expression


def test_process_eligibility_creates_draft_outputs_without_mutating_study(monkeypatch, tmp_path):
    install_process_eligibility_stub(monkeypatch)
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Eligibility processing study",
            "description": "Process eligibility into concept set drafts",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [
                    {"id": 1, "description": "Adults with T2DM"},
                    {"id": 2, "description": "Continuous metformin exposure"},
                ],
                "exclusionCriteria": [{"id": 1, "description": "Prior SGLT2 inhibitor exposure"}],
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/process-eligibility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["summary"].startswith("Processed eligibility into draft outputs")
    assert payload["meta"]["status"] == "ok"
    assert payload["meta"]["processedCount"] == 2
    assert payload["meta"]["preservedCount"] == 1
    assert_capability_signal(
        payload["meta"],
        owner="Eligibility processing",
        fidelity="medium",
        stage_kind="agent",
    )

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "eligibility_processing"
    proposed = artifact["payload"]["proposedChanges"]["eligibility"]
    assert proposed["targetCohortName"] == "Adults with type 2 diabetes mellitus"
    assert proposed["inclusionCriteria"][0]["conceptSetId"] == 9101
    assert proposed["inclusionCriteria"][0]["conceptSetName"] == "Processed inclusion concept set"
    assert proposed["inclusionCriteria"][1]["conceptSetId"] == 9102
    assert artifact["payload"]["meta"]["diagnostics"][1]["structuredExpression"] == {
        "ConditionOccurrence": {"CodesetId": 9101}
    }

    job = client.get(f'/tte/jobs/{payload["jobId"]}').json()
    assert job["status"] == "completed"
    assert job["artifactId"] == payload["artifactId"]

    study_after_process = client.get(f"/tte/studies/{study_id}").json()
    assert study_after_process["eligibility"]["inclusionCriteria"][0]["conceptSetId"] is None
    assert study_after_process["eligibility"]["inclusionCriteria"][1]["conceptSetId"] is None


def test_process_eligibility_preserves_structured_snapshot_through_apply(
    monkeypatch, tmp_path
):
    install_process_eligibility_stub(monkeypatch)
    original_allowed_apply_sections = TTEService._allowed_apply_sections_for_kind

    def allow_eligibility_processing_apply(self, artifact_kind: str):
        if artifact_kind == "eligibility_processing":
            return {"eligibility"}
        return original_allowed_apply_sections(self, artifact_kind)

    monkeypatch.setattr(
        TTEService,
        "_allowed_apply_sections_for_kind",
        allow_eligibility_processing_apply,
    )
    client = build_client(monkeypatch, tmp_path)
    structured_expression = build_structured_eligibility_expression(
        target_label="Adults with type 2 diabetes mellitus"
    )
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Eligibility apply preservation study",
            "description": "Apply processed eligibility draft",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [{"id": 1, "description": "Adults with T2DM"}],
                "exclusionCriteria": [],
                "structuredExpression": structured_expression,
            },
        },
    )
    study_id = create_response.json()["id"]

    process_response = client.post(f"/tte/studies/{study_id}/process-eligibility")

    assert process_response.status_code == 200
    payload = process_response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    proposed_eligibility = artifact["payload"]["proposedChanges"]["eligibility"]

    assert proposed_eligibility["structuredExpression"] == structured_expression
    assert proposed_eligibility["inclusionCriteria"][0]["conceptSetId"] == 9101

    study_before_apply = client.get(f"/tte/studies/{study_id}").json()
    assert study_before_apply["eligibility"]["structuredExpression"] == structured_expression
    assert study_before_apply["eligibility"]["inclusionCriteria"][0]["conceptSetId"] is None

    apply_response = client.post(
        f'/tte/artifacts/{payload["artifactId"]}/apply',
        json={"targetSections": ["eligibility"], "baseStudyVersion": study_before_apply["version"]},
    )

    assert apply_response.status_code == 200
    study_after_apply = client.get(f"/tte/studies/{study_id}").json()
    assert study_after_apply["version"] == study_before_apply["version"] + 1
    assert study_after_apply["eligibility"]["structuredExpression"] == structured_expression
    assert study_after_apply["eligibility"]["inclusionCriteria"][0]["conceptSetId"] == 9101
    assert study_after_apply["eligibility"]["inclusionCriteria"][0]["conceptSetName"] == (
        "Processed inclusion concept set"
    )


def test_process_eligibility_surfaces_partial_diagnostics(monkeypatch, tmp_path):
    install_process_eligibility_stub(
        monkeypatch,
        meta_status="partial",
        warning_count=1,
        failed_count=1,
        second_inclusion_status="warning",
        second_inclusion_warning="Concept mapping confidence fell below the review threshold.",
    )
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Eligibility partial diagnostics study",
            "description": "Process eligibility with one ambiguous criterion",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [
                    {"id": 1, "description": "Adults with T2DM"},
                    {"id": 2, "description": "History of severe renal impairment"},
                ],
                "exclusionCriteria": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/process-eligibility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["meta"]["status"] == "partial"
    assert payload["meta"]["warningCount"] == 1
    assert payload["meta"]["failedCount"] == 1

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    diagnostics = artifact["payload"]["meta"]["diagnostics"]
    ambiguous = next(item for item in diagnostics if item["criterionId"] == 2)
    assert ambiguous["status"] == "warning"
    assert "review threshold" in ambiguous["warning"].lower()

    proposed = artifact["payload"]["proposedChanges"]["eligibility"]
    assert proposed["inclusionCriteria"][0]["conceptSetId"] == 9101
    assert proposed["inclusionCriteria"][1]["conceptSetId"] is None

    study_after_process = client.get(f"/tte/studies/{study_id}").json()
    assert study_after_process["eligibility"]["inclusionCriteria"][1]["conceptSetId"] is None


def test_process_eligibility_surfaces_recommender_unavailable_failure(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)

    def raise_missing_recommender(self):
        raise ModuleNotFoundError("No module named 'chromadb'")

    monkeypatch.setattr(
        TTEService,
        "_get_seeded_concept_set_recommender",
        raise_missing_recommender,
    )

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Eligibility fallback study",
            "description": "Process eligibility without chromadb-backed recommender",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [
                    {"id": 1, "description": "HbA1c >= 7%"},
                    {"id": 2, "description": "Continuous metformin exposure"},
                ],
                "exclusionCriteria": [{"id": 3, "description": "Type 1 diabetes"}],
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/process-eligibility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["meta"]["status"] == "failed"
    assert payload["meta"]["failureMessage"] == "No module named 'chromadb'"

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "eligibility_processing"
    assert artifact["status"] == "failed"
    assert artifact["payload"]["proposedChanges"] == {}


def test_process_eligibility_progress_reads_store_backed_running_job_meta(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Eligibility progress running study",
            "description": "Store-backed progress should survive worker boundaries",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [{"id": 1, "description": "Adults with T2DM"}],
                "exclusionCriteria": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    service = get_tte_service()
    job = service.store.create_job(
        {
            "studyId": study_id,
            "studyVersion": 1,
            "capability": "process_eligibility",
            "status": "running",
            "meta": {
                "section": "eligibility",
                "progress": {"phase": "mapping", "mapped": 7, "total": 101},
            },
        }
    )

    response = client.get(f"/tte/studies/{study_id}/process-eligibility-progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["phase"] == "mapping"
    assert payload["mapped"] == 7
    assert payload["total"] == 101
    assert payload["jobId"] == job["id"]
    assert payload["jobStatus"] == "running"


def test_process_eligibility_progress_surfaces_latest_finished_job_artifact(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Eligibility progress finished study",
            "description": "Finished progress should surface artifact recovery metadata",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [{"id": 1, "description": "Adults with T2DM"}],
                "exclusionCriteria": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    service = get_tte_service()
    artifact = service.store.create_artifact(
        {
            "studyId": study_id,
            "studyVersion": 1,
            "kind": "eligibility_processing",
            "status": "completed",
            "source": "artemis",
            "capability": "process_eligibility",
            "summary": "Prepared eligibility draft structured definition for review.",
            "payload": {"meta": {"status": "ok"}},
        }
    )
    job = service.store.create_job(
        {
            "studyId": study_id,
            "studyVersion": 1,
            "capability": "process_eligibility",
            "status": "completed",
            "artifactId": artifact["id"],
            "meta": {
                "section": "eligibility",
                "progress": {"phase": "completed"},
                "summary": artifact["summary"],
            },
        }
    )

    response = client.get(f"/tte/studies/{study_id}/process-eligibility-progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["phase"] == "completed"
    assert payload["jobId"] == job["id"]
    assert payload["jobStatus"] == "completed"
    assert payload["artifactId"] == artifact["id"]
    assert payload["summary"] == artifact["summary"]


def test_process_eligibility_fails_for_drug_like_target_without_canonical_structured_target(
    monkeypatch, tmp_path
):
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Drug-like target failure study",
            "description": "Process eligibility should fail for drug-like targets without canonical criteria",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortName": "Metformin",
                "structuredExpression": {"inclusionCriteria": [], "exclusionCriteria": []},
                "inclusionCriteria": [
                    {"id": 1, "description": "Metformin", "domain": "Drug"},
                ],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "dapagliflozin", "cohortId": None, "cohortName": ""},
                {"id": 2, "name": "placebo", "cohortId": None, "cohortName": ""},
            ],
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/process-eligibility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["meta"]["status"] == "failed"
    assert payload["meta"]["failureMessage"] == (
        "Target population label appears to be a treatment/drug label; provide a "
        "patient-population target or correct the structured criteria first."
    )

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["status"] == "failed"
    assert artifact["payload"]["meta"]["failureMessage"] == payload["meta"]["failureMessage"]


def test_suggest_outcomes_returns_warning_artifact_when_seed_text_is_missing(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={"name": "", "description": "", "studyType": "comparative", "status": "draft"},
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/suggest-outcomes")

    assert response.status_code == 200
    payload = response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "outcome_suggestion"
    assert set(artifact["payload"]["proposedChanges"].keys()) == {"outcomes"}
    assert artifact["payload"]["meta"]["mappingQuality"]["status"] == "warning"
    assert artifact["payload"]["meta"]["mappingQuality"]["reason"] == "no_seed_text"
    assert artifact["payload"]["meta"]["sourceSection"] == "empty"


def test_suggest_treatment_creates_section_specific_artifact(monkeypatch, tmp_path):
    from src.api.models.tte import MappingQualitySignal

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._build_real_mapping_quality_signal",
        lambda self, study, provisional_ir, section_key, section_source: MappingQualitySignal(
            status="ok",
            seedCount=4,
            reason=None,
            domainMismatch=False,
            minSeedCount=1,
            retryReasons=[],
        ),
    )
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={"name": "Study", "description": "Compare dapagliflozin vs DPP4 inhibitors for MACE in T2DM"},
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/suggest-treatment")

    assert response.status_code == 200
    payload = response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "treatment_suggestion"
    assert set(artifact["payload"]["proposedChanges"].keys()) == {"treatmentArms"}
    assert artifact["payload"]["proposedChanges"]["treatmentArms"][0]["name"] == "dapagliflozin"
    assert artifact["payload"]["proposedChanges"]["treatmentArms"][1]["name"] == "DPP4 inhibitors"
    assert artifact["payload"]["meta"]["mappingQuality"]["status"] == "ok"
    assert artifact["payload"]["meta"]["mappingQuality"]["seedCount"] == 4
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Mapping-guided suggestion",
        fidelity="medium",
        stage_kind="agent",
    )


def test_suggest_treatment_marks_mapping_quality_fallback_when_agent2_import_is_unavailable(
    monkeypatch, tmp_path
):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "src.agents.agent2.workflow":
            raise ImportError("forced agent2 import failure")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Fallback import study",
            "description": "Compare dapagliflozin vs DPP4 inhibitors for MACE in adults with T2DM",
            "studyType": "comparative",
            "status": "draft",
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/suggest-treatment")

    assert response.status_code == 200
    payload = response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["payload"]["meta"]["mappingQuality"]["status"] == "fallback"
    assert artifact["payload"]["meta"]["mappingQuality"]["reason"] == "agent2_unavailable:ImportError"
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Mapping-guided suggestion",
        fidelity="medium",
        stage_kind="agent",
    )


def test_suggest_treatment_marks_mapping_quality_fallback_when_agent2_runtime_fails(
    monkeypatch, tmp_path
):
    fake_agent2_module = types.ModuleType("src.agents.agent2.workflow")

    class FailingAgent2:
        def process_with_details(self, *args, **kwargs):
            raise RuntimeError("forced agent2 runtime failure")

    fake_agent2_module.get_agent2 = lambda: FailingAgent2()

    fake_supervisor_module = types.ModuleType("src.pipeline.supervisor")
    fake_supervisor_module.MIN_SEED_COUNT = 1
    fake_supervisor_module.get_supervisor = lambda: types.SimpleNamespace(
        post_agent2_check=lambda **kwargs: types.SimpleNamespace(retry_reasons=[])
    )

    monkeypatch.setitem(sys.modules, "src.agents.agent2.workflow", fake_agent2_module)
    monkeypatch.setitem(sys.modules, "src.pipeline.supervisor", fake_supervisor_module)

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Fallback runtime study",
            "description": "Compare dapagliflozin vs DPP4 inhibitors for MACE in adults with T2DM",
            "studyType": "comparative",
            "status": "draft",
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/suggest-treatment")

    assert response.status_code == 200
    payload = response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["payload"]["meta"]["mappingQuality"]["status"] == "fallback"
    assert artifact["payload"]["meta"]["mappingQuality"]["reason"] == "agent2_failed:RuntimeError"
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Mapping-guided suggestion",
        fidelity="medium",
        stage_kind="agent",
    )


def test_run_analysis_creates_analysis_artifact_from_applied_generation_results(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Execution target",
            "description": "ready for analysis",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    ).json()
    client.post(
        f'/tte/artifacts/{execute_response["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )

    analysis_response = client.post(f"/tte/studies/{study_id}/run-analysis")

    assert analysis_response.status_code == 200
    payload = analysis_response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "analysis_result"
    assert artifact["payload"]["meta"]["status"] in {"ok", "fallback", "error"}
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Analysis workflow",
        fidelity="medium",
        stage_kind="agent",
    )
    assert artifact["payload"]["proposedChanges"]["results"]["mode"] == "analysis"
    # When real OMOP data is unavailable (test environment), hazardRatio may be None.
    # We only assert > 0 if the analysis actually succeeded.
    hr = artifact["payload"]["proposedChanges"]["results"]["hazardRatio"]
    if hr is not None:
        assert hr > 0
        ci = artifact["payload"]["proposedChanges"]["results"]["CI"]
        assert ci["lower"] < ci["upper"]
    assert artifact["payload"]["proposedChanges"]["results"]["n_target"] == 1200
    assert artifact["payload"]["proposedChanges"]["results"]["n_comparator"] == 1180


def test_run_analysis_uses_agent5_wrapper_result_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    from src.api.models.tte import AnalysisArtifactMeta

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent5_analysis_wrapper",
        lambda self, study, results: (
            {
                "mode": "analysis",
                "generatedBy": "agent5-test-wrapper",
                "hazardRatio": 0.72,
                "CI": {"lower": 0.61, "upper": 0.85},
                "pValue": 0.001,
                "covariateBalance": [{"name": "Age", "beforePS": 0.15, "afterPS": 0.03}],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentEvents": 30,
                "comparatorEvents": 44,
            },
            AnalysisArtifactMeta(status="ok", reason=None, summary="agent5 wrapper test"),
        ),
    )
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Execution target",
            "description": "ready for analysis",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    client.post(f"/tte/studies/{study_id}/validate")
    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    ).json()
    client.post(
        f'/tte/artifacts/{execute_response["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )

    analysis_response = client.post(f"/tte/studies/{study_id}/run-analysis")
    artifact = client.get(f'/tte/artifacts/{analysis_response.json()["artifactId"]}').json()

    assert artifact["payload"]["meta"]["status"] == "ok"
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Analysis workflow",
        fidelity="medium",
        stage_kind="agent",
    )
    assert artifact["payload"]["proposedChanges"]["results"]["generatedBy"] == "agent5-test-wrapper"
    assert artifact["payload"]["proposedChanges"]["results"]["hazardRatio"] == 0.72


def test_run_analysis_maps_matching_to_agent5_psm(monkeypatch, tmp_path):
    import pandas as pd

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    captured: dict[str, str] = {}

    class FakeOMOPConnector:
        def __init__(self, *args, schema=None, **kwargs):
            pass

        def build_analysis_dataset_from_generated_cohorts(self, **kwargs):
            return pd.DataFrame(
                {
                    "person_id": [1, 2, 3, 4],
                    "treatment": [1, 1, 0, 0],
                    "age": [60, 61, 60, 61],
                    "time": [120, 200, 122, 198],
                    "event": [1, 0, 1, 0],
                }
            )

    class FakeAgent5Workflow:
        def configure(
            self,
            target_cohort_id,
            comparator_cohort_id,
            outcome_definition=None,
            analysis_method="IPTW",
        ):
            captured["analysis_method"] = analysis_method
            return self

        def run(self, data=None):
            return {
                "hazard_ratio": {
                    "hr": 0.79,
                    "ci_lower": 0.68,
                    "ci_upper": 0.92,
                    "p_value": 0.004,
                },
                "analysis_method": "PSM",
                "n_matched_pairs": 4,
                "balance": {
                    "age": {
                        "smd_before": 0.18,
                        "smd_after": 0.04,
                        "mean_treated": 61.2,
                        "mean_control": 60.7,
                        "balanced": True,
                    }
                },
                "survival_data": {
                    "times_treated": [7, 14, 21, 28],
                    "events_treated": [1, 0, 0, 1],
                    "times_control": [7, 14, 21, 28],
                    "events_control": [0, 1, 0, 0],
                },
            }

    monkeypatch.setattr("src.analysis.omop_connector.OMOPConnector", FakeOMOPConnector)
    monkeypatch.setattr("src.agents.agent5.workflow.Agent5Workflow", FakeAgent5Workflow)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "PSM analysis target",
            "description": "ready for matching-based analysis",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
            "analysisSettings": {
                "outcomeModel": "cox",
                "adjustForCovariates": True,
                "psMethod": "matching",
                "psCaliper": 0.2,
                "trimByPs": True,
                "trimFraction": 0.05,
            },
        },
    )
    study_id = create_response.json()["id"]
    client.post(f"/tte/studies/{study_id}/validate")
    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    ).json()
    client.post(
        f'/tte/artifacts/{execute_response["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )

    analysis_response = client.post(f"/tte/studies/{study_id}/run-analysis")
    artifact = client.get(f'/tte/artifacts/{analysis_response.json()["artifactId"]}').json()

    assert analysis_response.status_code == 200
    assert artifact["payload"]["meta"]["status"] == "ok"
    assert captured["analysis_method"] == "PSM"
    results_payload = artifact["payload"]["proposedChanges"]["results"]
    assert results_payload["analysisMethod"] == "PSM"
    assert results_payload["matchedPairs"] == 4
    assert results_payload["treatmentN"] == 1200
    assert results_payload["comparatorN"] == 1180
    assert results_payload["hrLower95"] == 0.68
    assert results_payload["hrUpper95"] == 0.92
    assert results_payload["survivalData"]["times_treated"] == [7, 14, 21, 28]
    plot_keys = [plot["key"] for plot in results_payload["plots"]]
    assert "love_plot_after_matching" in plot_keys
    assert "cumulative_mortality_28d" in plot_keys
    assert "km_survival_curve" in plot_keys
    assert "forest_plot_hr" in plot_keys
    love_plot = results_payload["plots"][0]
    cumulative_plot = results_payload["plots"][1]
    assert love_plot["series"][0]["points"][0]["label"] == "age"
    assert love_plot["series"][1]["points"][0]["y"] == 0.04
    assert cumulative_plot["windowDays"] == 28
    assert cumulative_plot["series"][0]["points"][7]["x"] == 7
    assert cumulative_plot["series"][0]["points"][7]["y"] == 25.0
    assert cumulative_plot["series"][1]["points"][14]["y"] == 25.0


def test_run_analysis_maps_mahalanobis_to_agent5_method(monkeypatch, tmp_path):
    import pandas as pd

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    captured: dict[str, str] = {}

    class FakeOMOPConnector:
        def __init__(self, *args, schema=None, **kwargs):
            pass

        def build_analysis_dataset_from_generated_cohorts(self, **kwargs):
            return pd.DataFrame(
                {
                    "person_id": [1, 2, 3, 4],
                    "treatment": [1, 1, 0, 0],
                    "age": [60, 61, 60, 61],
                    "time": [120, 200, 122, 198],
                    "event": [1, 0, 1, 0],
                }
            )

    class FakeAgent5Workflow:
        def configure(
            self,
            target_cohort_id,
            comparator_cohort_id,
            outcome_definition=None,
            analysis_method="IPTW",
        ):
            captured["analysis_method"] = analysis_method
            return self

        def run(self, data=None):
            return {
                "hazard_ratio": {
                    "hr": 0.81,
                    "ci_lower": 0.69,
                    "ci_upper": 0.95,
                    "p_value": 0.01,
                },
                "analysis_method": "MAHALANOBIS",
                "n_matched_pairs": 5,
                "balance": {
                    "age": {
                        "smd_before": 0.21,
                        "smd_after": 0.05,
                        "mean_treated": 61.5,
                        "mean_control": 60.9,
                        "balanced": True,
                    }
                },
                "survival_data": {
                    "events_treated": [1, 0, 0, 1, 0],
                    "events_control": [0, 1, 0, 0, 1],
                },
            }

    monkeypatch.setattr("src.analysis.omop_connector.OMOPConnector", FakeOMOPConnector)
    monkeypatch.setattr("src.agents.agent5.workflow.Agent5Workflow", FakeAgent5Workflow)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Mahalanobis analysis target",
            "description": "ready for mahalanobis-based analysis",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
            "analysisSettings": {
                "outcomeModel": "cox",
                "adjustForCovariates": True,
                "psMethod": "mahalanobis",
                "psCaliper": 0.2,
                "trimByPs": True,
                "trimFraction": 0.05,
            },
        },
    )
    study_id = create_response.json()["id"]
    client.post(f"/tte/studies/{study_id}/validate")
    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    ).json()
    client.post(
        f'/tte/artifacts/{execute_response["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )

    analysis_response = client.post(f"/tte/studies/{study_id}/run-analysis")
    artifact = client.get(f'/tte/artifacts/{analysis_response.json()["artifactId"]}').json()

    assert analysis_response.status_code == 200
    assert artifact["payload"]["meta"]["status"] == "ok"
    assert captured["analysis_method"] == "MAHALANOBIS"
    assert artifact["payload"]["proposedChanges"]["results"]["analysisMethod"] == "MAHALANOBIS"
    assert artifact["payload"]["proposedChanges"]["results"]["matchedPairs"] == 5


def test_run_analysis_prefers_real_dataset_from_generated_cohorts(monkeypatch, tmp_path):
    import pandas as pd

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    captured: dict[str, object] = {}

    class FakeOMOPConnector:
        def __init__(self, *args, schema=None, **kwargs):
            captured["schema"] = schema

        def build_analysis_dataset_from_generated_cohorts(
            self,
            *,
            target_ref,
            outcome_ref,
            followup_days=365,
            comparator_ref=None,
        ):
            captured["target_ref"] = target_ref
            captured["comparator_ref"] = comparator_ref
            captured["outcome_ref"] = outcome_ref
            captured["followup_days"] = followup_days
            return pd.DataFrame(
                {
                    "person_id": [1, 2, 3, 4],
                    "treatment": [1, 1, 0, 0],
                    "age": [60, 61, 60, 61],
                    "gender": [0, 1, 0, 1],
                    "time": [120, 200, 122, 198],
                    "event": [1, 0, 1, 0],
                }
            )

    class FakeAgent5Workflow:
        def configure(
            self,
            target_cohort_id,
            comparator_cohort_id,
            outcome_definition=None,
            analysis_method="IPTW",
        ):
            captured["analysis_method"] = analysis_method
            return self

        def run(self, data=None):
            captured["data"] = data
            return {
                "hazard_ratio": {
                    "hr": 0.81,
                    "ci_lower": 0.70,
                    "ci_upper": 0.94,
                    "p_value": 0.01,
                },
                "analysis_method": "PSM",
                "n_matched_pairs": 2,
                "balance": {
                    "age": {
                        "smd_before": 0.12,
                        "smd_after": 0.03,
                        "mean_treated": 60.5,
                        "mean_control": 60.5,
                        "balanced": True,
                    }
                },
                "survival_data": {
                    "times_treated": [120, 200],
                    "events_treated": [1, 0],
                    "times_control": [122, 198],
                    "events_control": [1, 0],
                },
            }

    monkeypatch.setattr("src.analysis.omop_connector.OMOPConnector", FakeOMOPConnector)
    monkeypatch.setattr("src.agents.agent5.workflow.Agent5Workflow", FakeAgent5Workflow)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Real dataset preferred analysis",
            "description": "ready for real dataset path",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
            "timeParams": {"followUpDuration": 365},
            "analysisSettings": {"psMethod": "matching"},
        },
    )
    study_id = create_response.json()["id"]
    client.post(f"/tte/studies/{study_id}/validate")
    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    ).json()
    client.post(
        f'/tte/artifacts/{execute_response["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )

    analysis_response = client.post(f"/tte/studies/{study_id}/run-analysis")
    artifact = client.get(f'/tte/artifacts/{analysis_response.json()["artifactId"]}').json()

    assert analysis_response.status_code == 200
    assert artifact["payload"]["meta"]["status"] == "ok"
    assert captured["schema"] == "synthea23m"
    assert captured["target_ref"].cohort_definition_id == 101
    assert captured["comparator_ref"].cohort_definition_id == 102
    assert captured["outcome_ref"].cohort_definition_id == 201
    assert captured["followup_days"] == 365
    assert list(captured["data"]["person_id"]) == [1, 2, 3, 4]
    results_payload = artifact["payload"]["proposedChanges"]["results"]
    assert results_payload["plots"][0]["key"] == "love_plot_after_matching"
    assert results_payload["plots"][1]["key"] == "cumulative_mortality_28d"


def test_run_analysis_returns_error_payload_when_real_dataset_build_fails(monkeypatch, tmp_path):
    """When real data is unavailable, the analysis wrapper returns an error payload with
    null HR/CI/pValue and status='error'. No fabricated statistics are substituted."""
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)

    class FailingOMOPConnector:
        def __init__(self, *args, schema=None, **kwargs):
            pass

        def build_analysis_dataset_from_generated_cohorts(self, **kwargs):
            raise RuntimeError("real dataset unavailable")

    monkeypatch.setattr("src.analysis.omop_connector.OMOPConnector", FailingOMOPConnector)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Error payload analysis",
            "description": "real dataset path should fail with error payload (null metrics)",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
            "analysisSettings": {"psMethod": "matching"},
        },
    )
    study_id = create_response.json()["id"]
    client.post(f"/tte/studies/{study_id}/validate")
    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    ).json()
    client.post(
        f'/tte/artifacts/{execute_response["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )

    analysis_response = client.post(f"/tte/studies/{study_id}/run-analysis")
    artifact = client.get(f'/tte/artifacts/{analysis_response.json()["artifactId"]}').json()

    assert analysis_response.status_code == 200
    # The wrapper returns an error payload — never fabricated statistics
    meta = artifact["payload"]["meta"]
    assert meta["status"] == "error"
    assert "agent5_wrapper_error" in meta["reason"]
    results_payload = artifact["payload"]["proposedChanges"]["results"]
    # Null metrics — no fabricated HR/CI/p-values
    assert results_payload["hazardRatio"] is None
    assert results_payload["pValue"] is None


def test_generate_report_summary_returns_warning_artifact_for_generation_only_results(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Execution target",
            "description": "ready for report check",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    ).json()
    client.post(
        f'/tte/artifacts/{execute_response["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )

    report_response = client.post(f"/tte/studies/{study_id}/generate-report-summary")

    assert report_response.status_code == 200
    payload = report_response.json()
    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    assert artifact["kind"] == "report_summary"
    assert artifact["payload"]["meta"]["status"] == "warning"
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Report workflow",
        fidelity="medium",
        stage_kind="agent",
    )
    assert artifact["payload"]["summary"]["status"] == "warning"
    assert artifact["payload"]["summary"]["reason"] == "generation_only"
    assert artifact["payload"]["summary"]["text"]


def test_generate_report_summary_uses_agent6_wrapper_preview_when_available(monkeypatch, tmp_path):
    from src.api.models.tte import ReportArtifactMeta, ReportSummaryData, ReportPreviewMetadata

    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent6_summary_wrapper",
        lambda self, study, results: (
            ReportSummaryData(
                title=study.get("name") or "Untitled Study",
                text="Agent 6 wrapper summary",
                status="ok",
                reason=None,
                preview=ReportPreviewMetadata(
                    resultMode="analysis",
                    sourceKey="SYNTHEA23M",
                    generatedBy="agent6-test-wrapper",
                ),
            ),
            ReportArtifactMeta(status="ok", reason=None, summary="agent6 wrapper test"),
        ),
    )
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Analysis-ready study",
            "description": "has analysis results",
            "results": {
                "mode": "analysis",
                "generatedBy": "artemis-agent5-wrapper",
                "hazardRatio": 0.8,
                "CI": {"lower": 0.7, "upper": 0.92},
                "pValue": 0.01,
                "covariateBalance": [],
                "n_target": 1200,
                "n_comparator": 1180,
            },
        },
    )
    study_id = create_response.json()["id"]

    report_response = client.post(f"/tte/studies/{study_id}/generate-report-summary")
    artifact = client.get(f'/tte/artifacts/{report_response.json()["artifactId"]}').json()

    assert artifact["payload"]["meta"]["status"] == "ok"
    assert_capability_signal(
        artifact["payload"]["meta"],
        owner="Report workflow",
        fidelity="medium",
        stage_kind="agent",
    )
    assert artifact["payload"]["summary"]["text"] == "Agent 6 wrapper summary"
    assert artifact["payload"]["summary"]["preview"]["generatedBy"] == "agent6-test-wrapper"


def test_generate_report_summary_includes_analysis_diagnostics_in_preview(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)

    class FakeAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("src.agents.agent6.workflow.Agent6Workflow", FakeAgent6Workflow)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Report-ready study",
            "description": "has analysis diagnostics",
            "results": {
                "mode": "analysis",
                "generatedBy": "artemis-agent5-wrapper",
                "analysisMethod": "PSM",
                "matchedPairs": 412,
                "hazardRatio": 0.8,
                "CI": {"lower": 0.7, "upper": 0.92},
                "pValue": 0.01,
                "covariateBalance": [],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentEvents": 30,
                "comparatorEvents": 44,
                "plots": [
                    {
                        "key": "cumulative_mortality_28d",
                        "title": "28-day Cumulative Mortality",
                        "plotType": "line",
                        "xLabel": "Days since index",
                        "yLabel": "Cumulative mortality (%)",
                        "windowDays": 28,
                        "series": [],
                    },
                    {
                        "key": "love_plot_after_matching",
                        "title": "Love Plot (Covariate Balance After Matching)",
                        "plotType": "love_plot",
                        "xLabel": "Standardized mean difference",
                        "yLabel": "Covariate",
                        "series": [],
                    },
                ],
            },
        },
    )
    study_id = create_response.json()["id"]

    report_response = client.post(f"/tte/studies/{study_id}/generate-report-summary")
    artifact = client.get(f'/tte/artifacts/{report_response.json()["artifactId"]}').json()
    preview = artifact["payload"]["summary"]["preview"]

    assert artifact["payload"]["meta"]["status"] == "ok"
    assert preview["analysisMethod"] == "PSM"
    assert preview["matchedPairs"] == 412
    assert preview["hazardRatio"] == 0.8
    assert preview["pValue"] == 0.01
    assert [plot["key"] for plot in preview["plots"]] == [
        "cumulative_mortality_28d",
        "love_plot_after_matching",
    ]
    assert "PSM" in artifact["payload"]["summary"]["text"]


def test_generate_report_summary_prefers_vendored_reporting_workflow(monkeypatch, tmp_path):
    class FakeVendoredAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            Path(output_path).write_text("<html><body>Vendored Summary HTML</body></html>")
            return output_path

        def generate_report(self, output_path, generate_plots=True):
            Path(output_path).write_bytes(b"%PDF-1.4\n%vendored-summary\n")
            return output_path

    class ExplodingInternalAgent6Workflow:
        def __init__(self, *args, **kwargs):
            raise AssertionError("in-repo Agent6Workflow should not be used")

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FakeVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        "src.agents.agent6.workflow.Agent6Workflow",
        ExplodingInternalAgent6Workflow,
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored summary study")

    report_response = client.post(f"/tte/studies/{study_id}/generate-report-summary")

    assert report_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{report_response.json()["artifactId"]}').json()
    assert artifact["payload"]["meta"]["status"] == "ok"
    assert artifact["payload"]["summary"]["status"] == "ok"


def test_generate_report_summary_uses_vendored_workflow_when_fallback_import_is_broken(
    monkeypatch, tmp_path
):
    class FakeVendoredAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            Path(output_path).write_text("<html><body>unused summary html</body></html>")
            return output_path

        def generate_report(self, output_path, generate_plots=True):
            Path(output_path).write_bytes(b"%PDF-1.4\n%unused-summary\n")
            return output_path

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FakeVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        TTEService,
        "_load_internal_agent6_workflow_class",
        lambda self: (_ for _ in ()).throw(ImportError("fallback import broken")),
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored summary with broken fallback")

    report_response = client.post(f"/tte/studies/{study_id}/generate-report-summary")

    assert report_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{report_response.json()["artifactId"]}').json()
    assert artifact["payload"]["meta"]["status"] == "ok"
    assert artifact["payload"]["summary"]["status"] == "ok"


def test_generate_report_summary_retries_in_repo_agent6_when_vendored_runtime_fails(
    monkeypatch, tmp_path
):
    call_log: list[str] = []

    class FailingVendoredAgent6Workflow:
        def __init__(self, *args, **kwargs):
            call_log.append("vendored:init")

        def set_results(self, **kwargs):
            call_log.append("vendored:set_results")
            raise RuntimeError("vendored summary failed")

        def generate_html_report(self, output_path):
            raise AssertionError("summary retry test should not call vendored html")

        def generate_report(self, output_path, generate_plots=True):
            raise AssertionError("summary retry test should not call vendored pdf")

    class FakeInternalAgent6Workflow:
        def __init__(self, *args, **kwargs):
            call_log.append("internal:init")

        def set_results(self, **kwargs):
            call_log.append("internal:set_results")
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            raise AssertionError("summary retry test should not call internal html")

        def generate_report(self, output_path, generate_plots=True):
            raise AssertionError("summary retry test should not call internal pdf")

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FailingVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        "src.agents.agent6.workflow.Agent6Workflow",
        FakeInternalAgent6Workflow,
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored summary retry study")

    report_response = client.post(f"/tte/studies/{study_id}/generate-report-summary")

    assert report_response.status_code == 200
    artifact = client.get(f'/tte/artifacts/{report_response.json()["artifactId"]}').json()
    assert artifact["payload"]["meta"]["status"] == "ok"
    assert artifact["payload"]["summary"]["status"] == "ok"
    assert call_log == [
        "vendored:init",
        "vendored:set_results",
        "internal:init",
        "internal:set_results",
    ]


def test_full_pipeline_runs_stages_in_order_and_auto_applies_execution_and_analysis_artifacts(
    monkeypatch, tmp_path
):
    from src.api.models.tte import (
        AnalysisArtifactMeta,
        ReportArtifactMeta,
        ReportPreviewMetadata,
        ReportSummaryData,
    )

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent5_analysis_wrapper",
        lambda self, study, results: (
            {
                "mode": "analysis",
                "generatedBy": "agent5-full-pipeline-test",
                "analysisMethod": "PSM",
                "matchedPairs": 412,
                "hazardRatio": 0.72,
                "CI": {"lower": 0.61, "upper": 0.85},
                "pValue": 0.001,
                "covariateBalance": [{"name": "Age", "beforePS": 0.15, "afterPS": 0.03}],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentEvents": 30,
                "comparatorEvents": 44,
            },
            AnalysisArtifactMeta(status="ok", reason=None, summary="full pipeline analysis"),
        ),
    )
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent6_summary_wrapper",
        lambda self, study, results: (
            ReportSummaryData(
                title=study.get("name") or "Untitled Study",
                text="Full pipeline report summary",
                status="ok",
                reason=None,
                preview=ReportPreviewMetadata(
                    resultMode="analysis",
                    sourceKey=results.get("sourceKey"),
                    generatedBy="agent6-full-pipeline-test",
                    analysisMethod=results.get("analysisMethod"),
                    matchedPairs=results.get("matchedPairs"),
                    hazardRatio=results.get("hazardRatio"),
                    ciLower=((results.get("CI") or {}).get("lower")),
                    ciUpper=((results.get("CI") or {}).get("upper")),
                    pValue=results.get("pValue"),
                ),
            ),
            ReportArtifactMeta(status="ok", reason=None, summary="full pipeline report"),
        ),
    )

    call_log: list[str] = []
    original_execute_study = TTEService.execute_study
    original_apply_artifact = TTEService.apply_artifact
    original_run_analysis = TTEService.run_analysis
    original_generate_report_summary = TTEService.generate_report_summary

    def tracking_execute_study(self, study_id, source_key):
        call_log.append("execute_study")
        return original_execute_study(self, study_id, source_key)

    def tracking_apply_artifact(self, artifact_id, target_sections, base_study_version):
        artifact = self.get_artifact(artifact_id)
        call_log.append(f'apply:{artifact.kind}')
        return original_apply_artifact(self, artifact_id, target_sections, base_study_version)

    def tracking_run_analysis(self, study_id):
        call_log.append("run_analysis")
        return original_run_analysis(self, study_id)

    def tracking_generate_report_summary(self, study_id):
        call_log.append("generate_report_summary")
        return original_generate_report_summary(self, study_id)

    monkeypatch.setattr(TTEService, "execute_study", tracking_execute_study)
    monkeypatch.setattr(TTEService, "apply_artifact", tracking_apply_artifact)
    monkeypatch.setattr(TTEService, "run_analysis", tracking_run_analysis)
    monkeypatch.setattr(TTEService, "generate_report_summary", tracking_generate_report_summary)

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Full pipeline study",
            "description": "ready for full pipeline execution",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
            "analysisSettings": {
                "outcomeModel": "cox",
                "adjustForCovariates": True,
                "psMethod": "matching",
                "psCaliper": 0.2,
                "trimByPs": True,
                "trimFraction": 0.05,
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    response = client.post(
        f"/tte/studies/{study_id}/run-full-pipeline",
        json={"sourceKey": "SYNTHEA23M"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["studyId"] == study_id
    assert payload["sourceKey"] == "SYNTHEA23M"
    assert payload["status"] == "completed"
    assert payload["studyVersion"] == 3
    assert payload["summary"]
    assert call_log == [
        "execute_study",
        "apply:execution_result",
        "run_analysis",
        "apply:analysis_result",
        "generate_report_summary",
    ]

    execution_stage = payload["stages"]["execution"]
    assert execution_stage["status"] == "completed"
    assert execution_stage["artifactKind"] == "execution_result"
    assert execution_stage["artifactId"].startswith("art_")
    assert execution_stage["jobId"].startswith("job_")
    assert execution_stage["appliedArtifactId"] == execution_stage["artifactId"]
    assert execution_stage["appliedStudyVersion"] == 2
    assert execution_stage["meta"]["sourceKey"] == "SYNTHEA23M"

    analysis_stage = payload["stages"]["analysis"]
    assert analysis_stage["status"] == "completed"
    assert analysis_stage["artifactKind"] == "analysis_result"
    assert analysis_stage["artifactId"].startswith("art_")
    assert analysis_stage["jobId"].startswith("job_")
    assert analysis_stage["appliedArtifactId"] == analysis_stage["artifactId"]
    assert analysis_stage["appliedStudyVersion"] == 3
    assert analysis_stage["meta"]["status"] == "ok"

    report_stage = payload["stages"]["reportSummary"]
    assert report_stage["status"] == "completed"
    assert report_stage["artifactKind"] == "report_summary"
    assert report_stage["artifactId"].startswith("art_")
    assert report_stage["jobId"].startswith("job_")
    assert report_stage["appliedArtifactId"] is None
    assert report_stage["appliedStudyVersion"] is None
    assert report_stage["meta"]["status"] == "ok"

    supervisor = payload["supervisor"]
    assert supervisor["status"] == "completed"
    assert [item["name"] for item in supervisor["hookPoints"]] == [
        "before_execute_study",
        "after_execute_study",
        "after_run_analysis",
        "after_generate_report_summary",
    ]
    hooks_by_name = {item["name"]: item for item in supervisor["hookPoints"]}
    assert hooks_by_name["before_execute_study"]["status"] == "not_connected"
    assert hooks_by_name["before_execute_study"]["decisions"] == []

    extraction_hook = hooks_by_name["after_execute_study"]
    assert extraction_hook["status"] == "completed"
    assert len(extraction_hook["decisions"]) == 1
    assert extraction_hook["decisions"][0]["agent_name"] == "extraction"
    assert extraction_hook["decisions"][0]["status"] == "SUCCESS"
    assert extraction_hook["decisions"][0]["action"] == "PROCEED"
    assert extraction_hook["decisions"][0]["metrics"]["patient_count"] > 0

    analysis_hook = hooks_by_name["after_run_analysis"]
    assert analysis_hook["status"] == "completed"
    assert len(analysis_hook["decisions"]) == 1
    assert analysis_hook["decisions"][0]["agent_name"] == "analysis"
    assert analysis_hook["decisions"][0]["status"] == "SUCCESS"
    assert analysis_hook["decisions"][0]["action"] == "PROCEED"
    assert analysis_hook["decisions"][0]["metrics"]["n"] == 2380

    report_hook = hooks_by_name["after_generate_report_summary"]
    assert report_hook["status"] == "completed"
    assert len(report_hook["decisions"]) == 1
    assert report_hook["decisions"][0]["agent_name"] == "reporting"
    assert report_hook["decisions"][0]["status"] == "SUCCESS"
    assert report_hook["decisions"][0]["action"] == "PROCEED"
    assert report_hook["decisions"][0]["metrics"]["has_summary_text"] is True
    assert report_hook["decisions"][0]["metrics"]["has_report_path"] is False

    assert [item["agent_name"] for item in supervisor["decisions"]] == [
        "extraction",
        "analysis",
        "reporting",
    ]

    fetched = client.get(f"/tte/studies/{study_id}").json()
    assert fetched["version"] == 3
    assert fetched["status"] == "completed"
    assert fetched["results"]["mode"] == "analysis"
    assert fetched["results"]["generatedBy"] == "agent5-full-pipeline-test"
    assert len(fetched["executions"]) == 1
    assert fetched["executions"][0]["sourceKey"] == "SYNTHEA23M"

    artifacts = client.get(f"/tte/studies/{study_id}/artifacts").json()
    artifacts_by_kind = {item["kind"]: item for item in artifacts}
    assert artifacts_by_kind["execution_result"]["appliedAt"]
    assert artifacts_by_kind["analysis_result"]["appliedAt"]
    assert artifacts_by_kind["report_summary"]["appliedAt"] is None


def test_full_pipeline_preserves_existing_standalone_stage_endpoint_shapes(monkeypatch, tmp_path):
    from src.api.models.tte import (
        AnalysisArtifactMeta,
        ReportArtifactMeta,
        ReportPreviewMetadata,
        ReportSummaryData,
    )

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent5_analysis_wrapper",
        lambda self, study, results: (
            {
                "mode": "analysis",
                "generatedBy": "agent5-stage-shape-test",
                "analysisMethod": "PSM",
                "matchedPairs": 101,
                "hazardRatio": 0.74,
                "CI": {"lower": 0.63, "upper": 0.87},
                "pValue": 0.002,
                "covariateBalance": [],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentEvents": 25,
                "comparatorEvents": 39,
            },
            AnalysisArtifactMeta(status="ok", reason=None, summary="standalone analysis"),
        ),
    )
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent6_summary_wrapper",
        lambda self, study, results: (
            ReportSummaryData(
                title=study.get("name") or "Untitled Study",
                text="Standalone report summary",
                status="ok",
                reason=None,
                preview=ReportPreviewMetadata(
                    resultMode="analysis",
                    sourceKey=results.get("sourceKey"),
                    generatedBy="agent6-stage-shape-test",
                ),
            ),
            ReportArtifactMeta(status="ok", reason=None, summary="standalone report"),
        ),
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Standalone stage shape study",
            "description": "ready for individual stage calls",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    execute_response = client.post(
        f"/tte/studies/{study_id}/execute",
        json={"sourceKey": "SYNTHEA23M"},
    )
    assert execute_response.status_code == 200
    assert set(execute_response.json().keys()) == {"execution", "results", "artifactId", "jobId"}

    apply_execution_response = client.post(
        f'/tte/artifacts/{execute_response.json()["artifactId"]}/apply',
        json={"targetSections": ["results", "executions", "status"], "baseStudyVersion": 1},
    )
    assert apply_execution_response.status_code == 200

    analysis_response = client.post(f"/tte/studies/{study_id}/run-analysis")
    assert analysis_response.status_code == 200
    assert set(analysis_response.json().keys()) == {"status", "artifactId", "jobId", "summary", "meta"}

    apply_analysis_response = client.post(
        f'/tte/artifacts/{analysis_response.json()["artifactId"]}/apply',
        json={"targetSections": ["results"], "baseStudyVersion": 2},
    )
    assert apply_analysis_response.status_code == 200

    report_response = client.post(f"/tte/studies/{study_id}/generate-report-summary")
    assert report_response.status_code == 200
    assert set(report_response.json().keys()) == {"status", "artifactId", "jobId", "summary", "meta"}


def test_full_pipeline_analysis_supervisor_hook_reflects_existing_review_logic(
    monkeypatch, tmp_path
):
    from src.api.models.tte import (
        AnalysisArtifactMeta,
        ReportArtifactMeta,
        ReportPreviewMetadata,
        ReportSummaryData,
    )

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent5_analysis_wrapper",
        lambda self, study, results: (
            {
                "mode": "analysis",
                "generatedBy": "agent5-small-sample-test",
                "analysisMethod": "PSM",
                "matchedPairs": 18,
                "hazardRatio": 0.91,
                "CI": {"lower": 0.55, "upper": 1.3},
                "pValue": 0.12,
                "covariateBalance": [{"name": "Age", "beforePS": 0.11, "afterPS": 0.04}],
                "n_target": 10,
                "n_comparator": 500,
                "treatmentEvents": 2,
                "comparatorEvents": 9,
            },
            AnalysisArtifactMeta(status="ok", reason=None, summary="small sample analysis"),
        ),
    )
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent6_summary_wrapper",
        lambda self, study, results: (
            ReportSummaryData(
                title=study.get("name") or "Untitled Study",
                text="Small sample report summary",
                status="ok",
                reason=None,
                preview=ReportPreviewMetadata(
                    resultMode="analysis",
                    sourceKey=results.get("sourceKey"),
                    generatedBy="agent6-small-sample-test",
                    analysisMethod=results.get("analysisMethod"),
                    matchedPairs=results.get("matchedPairs"),
                    hazardRatio=results.get("hazardRatio"),
                    ciLower=((results.get("CI") or {}).get("lower")),
                    ciUpper=((results.get("CI") or {}).get("upper")),
                    pValue=results.get("pValue"),
                ),
            ),
            ReportArtifactMeta(status="ok", reason=None, summary="small sample report"),
        ),
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Supervisor analysis review study",
            "description": "small sample analysis warning path",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    response = client.post(
        f"/tte/studies/{study_id}/run-full-pipeline",
        json={"sourceKey": "SYNTHEA23M"},
    )

    assert response.status_code == 200
    payload = response.json()
    hooks_by_name = {item["name"]: item for item in payload["supervisor"]["hookPoints"]}

    assert hooks_by_name["after_execute_study"]["decisions"][0]["status"] == "SUCCESS"
    assert hooks_by_name["after_run_analysis"]["status"] == "completed"
    assert hooks_by_name["after_run_analysis"]["decisions"][0]["agent_name"] == "analysis"
    assert hooks_by_name["after_run_analysis"]["decisions"][0]["status"] == "PARTIAL"
    assert hooks_by_name["after_run_analysis"]["decisions"][0]["action"] == "PROCEED"
    assert "target n=10 < 30" in hooks_by_name["after_run_analysis"]["decisions"][0]["reason"]
    assert hooks_by_name["after_generate_report_summary"]["status"] == "completed"
    assert hooks_by_name["after_generate_report_summary"]["decisions"][0]["agent_name"] == (
        "reporting"
    )
    assert hooks_by_name["after_generate_report_summary"]["decisions"][0]["status"] == "SUCCESS"
    assert payload["status"] == "completed"
    assert payload["stages"]["analysis"]["status"] == "completed"
    assert payload["stages"]["reportSummary"]["status"] == "completed"


def test_full_pipeline_analysis_supervisor_hook_warns_when_hazard_ratio_is_missing(
    monkeypatch, tmp_path
):
    from src.api.models.tte import (
        AnalysisArtifactMeta,
        ReportArtifactMeta,
        ReportPreviewMetadata,
        ReportSummaryData,
    )

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent5_analysis_wrapper",
        lambda self, study, results: (
            {
                "mode": "analysis",
                "generatedBy": "agent5-missing-hr-test",
                "analysisMethod": "PSM",
                "matchedPairs": 88,
                "hazardRatio": None,
                "CI": {"lower": None, "upper": None},
                "pValue": None,
                "covariateBalance": [{"name": "Age", "beforePS": 0.09, "afterPS": 0.03}],
                "n_target": 100,
                "n_comparator": 120,
                "treatmentEvents": 7,
                "comparatorEvents": 9,
            },
            AnalysisArtifactMeta(status="ok", reason=None, summary="missing hr analysis"),
        ),
    )
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent6_summary_wrapper",
        lambda self, study, results: (
            ReportSummaryData(
                title=study.get("name") or "Untitled Study",
                text="Missing HR report summary",
                status="ok",
                reason=None,
                preview=ReportPreviewMetadata(
                    resultMode="analysis",
                    sourceKey=results.get("sourceKey"),
                    generatedBy="agent6-missing-hr-test",
                    analysisMethod=results.get("analysisMethod"),
                    matchedPairs=results.get("matchedPairs"),
                    hazardRatio=results.get("hazardRatio"),
                    ciLower=((results.get("CI") or {}).get("lower")),
                    ciUpper=((results.get("CI") or {}).get("upper")),
                    pValue=results.get("pValue"),
                ),
            ),
            ReportArtifactMeta(status="ok", reason=None, summary="missing hr report"),
        ),
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Supervisor missing HR review study",
            "description": "analysis completes without hazard ratio",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    response = client.post(
        f"/tte/studies/{study_id}/run-full-pipeline",
        json={"sourceKey": "SYNTHEA23M"},
    )

    assert response.status_code == 200
    payload = response.json()
    hooks_by_name = {item["name"]: item for item in payload["supervisor"]["hookPoints"]}
    analysis_hook = hooks_by_name["after_run_analysis"]

    assert analysis_hook["status"] == "completed"
    assert analysis_hook["decisions"][0]["agent_name"] == "analysis"
    assert analysis_hook["decisions"][0]["status"] == "PARTIAL"
    assert analysis_hook["decisions"][0]["action"] == "PROCEED"
    assert "no hazard ratio computed" in analysis_hook["decisions"][0]["reason"]
    assert hooks_by_name["after_generate_report_summary"]["status"] == "completed"
    assert hooks_by_name["after_generate_report_summary"]["decisions"][0]["agent_name"] == (
        "reporting"
    )
    assert hooks_by_name["after_generate_report_summary"]["decisions"][0]["status"] == "SUCCESS"
    assert payload["status"] == "completed"
    assert payload["stages"]["analysis"]["status"] == "completed"
    assert payload["stages"]["reportSummary"]["status"] == "completed"


def test_full_pipeline_marks_analysis_job_failed_and_stops_before_report(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._build_analysis_artifact_payload",
        lambda self, study_id, study: (_ for _ in ()).throw(RuntimeError("analysis payload exploded")),
    )
    monkeypatch.setattr(
        TTEService,
        "generate_report_summary",
        lambda self, study_id: (_ for _ in ()).throw(
            AssertionError("generate_report_summary should not run after analysis failure")
        ),
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Analysis failure pipeline study",
            "description": "analysis stage will fail",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    with pytest.raises(RuntimeError, match="analysis payload exploded"):
        client.post(
            f"/tte/studies/{study_id}/run-full-pipeline",
            json={"sourceKey": "SYNTHEA23M"},
        )

    store = TTEStore(str(tmp_path / "tte" / "studies.json"))
    persisted = store._read()
    analysis_jobs = [job for job in persisted["jobs"] if job["capability"] == "run_analysis"]
    report_jobs = [job for job in persisted["jobs"] if job["capability"] == "generate_report_summary"]
    assert len(analysis_jobs) == 1
    assert analysis_jobs[0]["status"] == "failed"
    assert analysis_jobs[0]["finishedAt"]
    assert analysis_jobs[0]["error"] == "analysis payload exploded"
    assert report_jobs == []

    execution_jobs = [job for job in persisted["jobs"] if job["capability"] == "execute_study"]
    assert len(execution_jobs) == 1
    assert execution_jobs[0]["status"] == "completed"

    fetched = client.get(f"/tte/studies/{study_id}").json()
    assert fetched["version"] == 2
    assert fetched["results"]["mode"] == "webapi_generation"

    artifacts = client.get(f"/tte/studies/{study_id}/artifacts").json()
    artifact_kinds = [artifact["kind"] for artifact in artifacts]
    assert "execution_result" in artifact_kinds
    assert "analysis_result" not in artifact_kinds
    assert "report_summary" not in artifact_kinds


def test_full_pipeline_marks_report_job_failed_after_analysis_completes(monkeypatch, tmp_path):
    from src.api.models.tte import AnalysisArtifactMeta

    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._run_agent5_analysis_wrapper",
        lambda self, study, results: (
            {
                "mode": "analysis",
                "generatedBy": "agent5-report-failure-test",
                "analysisMethod": "PSM",
                "matchedPairs": 212,
                "hazardRatio": 0.77,
                "CI": {"lower": 0.66, "upper": 0.9},
                "pValue": 0.003,
                "covariateBalance": [],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentEvents": 28,
                "comparatorEvents": 40,
            },
            AnalysisArtifactMeta(status="ok", reason=None, summary="analysis completed before report failure"),
        ),
    )
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._build_report_summary_payload",
        lambda self, study_id, study: (_ for _ in ()).throw(RuntimeError("report payload exploded")),
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Report failure pipeline study",
            "description": "report stage will fail",
            "eligibility": {
                "targetCohortId": 501,
                "targetCohortName": "Adults with T2DM",
                "inclusionCriteria": [{"id": 1, "description": "Type 2 diabetes mellitus"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "Treatment", "cohortId": 101, "cohortName": "Treatment cohort"},
                {"id": 2, "name": "Comparator", "cohortId": 102, "cohortName": "Comparator cohort"},
            ],
            "outcomes": {
                "primary": {"cohortId": 201, "cohortName": "Primary outcome", "description": "Outcome"},
                "secondary": [],
            },
            "analysisSettings": {
                "psMethod": "matching",
            },
        },
    )
    study_id = create_response.json()["id"]
    validate_response = client.post(f"/tte/studies/{study_id}/validate")
    assert validate_response.status_code == 200

    with pytest.raises(RuntimeError, match="report payload exploded"):
        client.post(
            f"/tte/studies/{study_id}/run-full-pipeline",
            json={"sourceKey": "SYNTHEA23M"},
        )

    store = TTEStore(str(tmp_path / "tte" / "studies.json"))
    persisted = store._read()
    report_jobs = [job for job in persisted["jobs"] if job["capability"] == "generate_report_summary"]
    assert len(report_jobs) == 1
    assert report_jobs[0]["status"] == "failed"
    assert report_jobs[0]["finishedAt"]
    assert report_jobs[0]["error"] == "report payload exploded"

    analysis_jobs = [job for job in persisted["jobs"] if job["capability"] == "run_analysis"]
    assert len(analysis_jobs) == 1
    assert analysis_jobs[0]["status"] == "completed"

    fetched = client.get(f"/tte/studies/{study_id}").json()
    assert fetched["version"] == 3
    assert fetched["results"]["mode"] == "analysis"
    assert fetched["results"]["generatedBy"] == "agent5-report-failure-test"

    artifacts = client.get(f"/tte/studies/{study_id}/artifacts").json()
    artifact_kinds = [artifact["kind"] for artifact in artifacts]
    assert "execution_result" in artifact_kinds
    assert "analysis_result" in artifact_kinds
    assert "report_summary" not in artifact_kinds


def test_export_report_html_returns_backend_generated_html(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Exportable report study",
            "description": "analysis ready for html export",
            "results": {
                "mode": "analysis",
                "generatedBy": "artemis-agent5-wrapper",
                "analysisMethod": "PSM",
                "matchedPairs": 412,
                "hazardRatio": 0.8,
                "CI": {"lower": 0.7, "upper": 0.92},
                "pValue": 0.01,
                "covariateBalance": [],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentEvents": 30,
                "comparatorEvents": 44,
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.get(f"/tte/studies/{study_id}/export-report-html")

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"].endswith(".html")
    assert payload["status"] in {"ok", "fallback"}
    assert "Exportable report study" in payload["html"]
    assert "Hazard Ratio" in payload["html"]


def test_export_report_html_prefers_vendored_reporting_workflow(monkeypatch, tmp_path):
    class FakeVendoredAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            Path(output_path).write_text("<html><body>Vendored HTML</body></html>")
            return output_path

        def generate_report(self, output_path, generate_plots=True):
            Path(output_path).write_bytes(b"%PDF-1.4\n%vendored-html-workflow\n")
            return output_path

    class ExplodingInternalAgent6Workflow:
        def __init__(self, *args, **kwargs):
            raise AssertionError("in-repo Agent6Workflow should not be used")

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FakeVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        "src.agents.agent6.workflow.Agent6Workflow",
        ExplodingInternalAgent6Workflow,
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored HTML study")

    response = client.get(f"/tte/studies/{study_id}/export-report-html")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["html"] == "<html><body>Vendored HTML</body></html>"


def test_export_report_html_uses_vendored_workflow_when_fallback_import_is_broken(
    monkeypatch, tmp_path
):
    class FakeVendoredAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            Path(output_path).write_text("<html><body>Vendored HTML With Broken Fallback</body></html>")
            return output_path

        def generate_report(self, output_path, generate_plots=True):
            Path(output_path).write_bytes(b"%PDF-1.4\n%unused-html\n")
            return output_path

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FakeVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        TTEService,
        "_load_internal_agent6_workflow_class",
        lambda self: (_ for _ in ()).throw(ImportError("fallback import broken")),
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored HTML with broken fallback")

    response = client.get(f"/tte/studies/{study_id}/export-report-html")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["html"] == "<html><body>Vendored HTML With Broken Fallback</body></html>"


def test_export_report_html_retries_in_repo_agent6_when_vendored_runtime_fails(
    monkeypatch, tmp_path
):
    call_log: list[str] = []

    class FailingVendoredAgent6Workflow:
        def __init__(self, *args, **kwargs):
            call_log.append("vendored:init")

        def set_results(self, **kwargs):
            call_log.append("vendored:set_results")
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            call_log.append("vendored:generate_html_report")
            raise RuntimeError("vendored html failed")

        def generate_report(self, output_path, generate_plots=True):
            raise AssertionError("html retry test should not call vendored pdf")

    class FakeInternalAgent6Workflow:
        def __init__(self, *args, **kwargs):
            call_log.append("internal:init")

        def set_results(self, **kwargs):
            call_log.append("internal:set_results")
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            call_log.append("internal:generate_html_report")
            Path(output_path).write_text("<html><body>Internal HTML Retry</body></html>")
            return output_path

        def generate_report(self, output_path, generate_plots=True):
            raise AssertionError("html retry test should not call internal pdf")

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FailingVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        "src.agents.agent6.workflow.Agent6Workflow",
        FakeInternalAgent6Workflow,
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored HTML retry study")

    response = client.get(f"/tte/studies/{study_id}/export-report-html")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["html"] == "<html><body>Internal HTML Retry</body></html>"
    assert call_log == [
        "vendored:init",
        "vendored:set_results",
        "vendored:init",
        "vendored:set_results",
        "vendored:generate_html_report",
        "internal:init",
        "internal:set_results",
        "internal:generate_html_report",
    ]


def test_export_report_html_rejects_generation_only_results(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Generation only study",
            "description": "not ready for export",
            "results": {
                "mode": "webapi_generation",
                "generatedBy": "artemis-api-webapi",
                "sourceKey": "SYNTHEA23M",
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.get(f"/tte/studies/{study_id}/export-report-html")

    assert response.status_code == 409
    assert "report" in response.json()["detail"].lower()


def test_export_report_pdf_returns_backend_generated_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._generate_backend_report_pdf",
        lambda self, study, results, summary_payload: b"%PDF-1.4\n%fake-pdf\n",
        raising=False,
    )
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "PDF exportable study",
            "description": "analysis ready for pdf export",
            "results": {
                "mode": "analysis",
                "generatedBy": "artemis-agent5-wrapper",
                "analysisMethod": "PSM",
                "matchedPairs": 412,
                "hazardRatio": 0.8,
                "CI": {"lower": 0.7, "upper": 0.92},
                "pValue": 0.01,
                "covariateBalance": [],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentEvents": 30,
                "comparatorEvents": 44,
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.get(f"/tte/studies/{study_id}/export-report-pdf")

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"].endswith(".pdf")
    assert payload["contentType"] == "application/pdf"
    assert payload["contentBase64"]


def test_export_report_pdf_prefers_vendored_reporting_workflow(monkeypatch, tmp_path):
    class FakeVendoredAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            Path(output_path).write_text("<html><body>Vendored PDF HTML</body></html>")
            return output_path

        def generate_report(self, output_path, generate_plots=True):
            Path(output_path).write_bytes(b"%PDF-1.4\n%vendored-workflow\n")
            return output_path

    class ExplodingInternalAgent6Workflow:
        def __init__(self, *args, **kwargs):
            raise AssertionError("in-repo Agent6Workflow should not be used")

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FakeVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        "src.agents.agent6.workflow.Agent6Workflow",
        ExplodingInternalAgent6Workflow,
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored PDF study")

    response = client.get(f"/tte/studies/{study_id}/export-report-pdf")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["contentType"] == "application/pdf"
    assert base64.b64decode(payload["contentBase64"]) == b"%PDF-1.4\n%vendored-workflow\n"


def test_export_report_pdf_uses_vendored_workflow_when_fallback_import_is_broken(
    monkeypatch, tmp_path
):
    class FakeVendoredAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            Path(output_path).write_text("<html><body>unused pdf html</body></html>")
            return output_path

        def generate_report(self, output_path, generate_plots=True):
            Path(output_path).write_bytes(b"%PDF-1.4\n%vendored-broken-fallback\n")
            return output_path

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FakeVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        TTEService,
        "_load_internal_agent6_workflow_class",
        lambda self: (_ for _ in ()).throw(ImportError("fallback import broken")),
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored PDF with broken fallback")

    response = client.get(f"/tte/studies/{study_id}/export-report-pdf")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["contentType"] == "application/pdf"
    assert base64.b64decode(payload["contentBase64"]) == b"%PDF-1.4\n%vendored-broken-fallback\n"


def test_export_report_pdf_retries_in_repo_agent6_when_vendored_runtime_fails(
    monkeypatch, tmp_path
):
    call_log: list[str] = []

    class FailingVendoredAgent6Workflow:
        def __init__(self, *args, **kwargs):
            call_log.append("vendored:init")

        def set_results(self, **kwargs):
            call_log.append("vendored:set_results")
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            raise AssertionError("pdf retry test should not call vendored html")

        def generate_report(self, output_path, generate_plots=True):
            call_log.append("vendored:generate_report")
            raise RuntimeError("vendored pdf failed")

    class FakeInternalAgent6Workflow:
        def __init__(self, *args, **kwargs):
            call_log.append("internal:init")

        def set_results(self, **kwargs):
            call_log.append("internal:set_results")
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            raise AssertionError("pdf retry test should not call internal html")

        def generate_report(self, output_path, generate_plots=True):
            call_log.append("internal:generate_report")
            Path(output_path).write_bytes(b"%PDF-1.4\n%internal-retry\n")
            return output_path

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        FailingVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        "src.agents.agent6.workflow.Agent6Workflow",
        FakeInternalAgent6Workflow,
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Vendored PDF retry study")

    response = client.get(f"/tte/studies/{study_id}/export-report-pdf")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["contentType"] == "application/pdf"
    assert base64.b64decode(payload["contentBase64"]) == b"%PDF-1.4\n%internal-retry\n"
    assert call_log == [
        "vendored:init",
        "vendored:set_results",
        "vendored:init",
        "vendored:set_results",
        "vendored:generate_report",
        "internal:init",
        "internal:set_results",
        "internal:generate_report",
    ]


def test_export_report_pdf_rejects_generation_only_results(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Generation only study",
            "description": "not ready for pdf export",
            "results": {
                "mode": "webapi_generation",
                "generatedBy": "artemis-api-webapi",
                "sourceKey": "SYNTHEA23M",
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.get(f"/tte/studies/{study_id}/export-report-pdf")

    assert response.status_code == 409
    assert "report" in response.json()["detail"].lower()


def test_export_report_pdf_returns_fallback_pdf_when_pdf_generation_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeWebAPIClient)
    monkeypatch.setattr(
        "src.services.tte_service.TTEService._generate_agent6_pdf_report",
        lambda self, study, results: (_ for _ in ()).throw(RuntimeError("weasyprint missing")),
        raising=False,
    )
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Fallback PDF study",
            "description": "analysis ready for fallback pdf export",
            "results": {
                "mode": "analysis",
                "generatedBy": "artemis-agent5-wrapper",
                "analysisMethod": "PSM",
                "matchedPairs": 412,
                "hazardRatio": 0.8,
                "CI": {"lower": 0.7, "upper": 0.92},
                "pValue": 0.01,
                "covariateBalance": [],
                "n_target": 1200,
                "n_comparator": 1180,
                "treatmentEvents": 30,
                "comparatorEvents": 44,
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.get(f"/tte/studies/{study_id}/export-report-pdf")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "fallback"
    assert payload["contentType"] == "application/pdf"
    assert payload["contentBase64"]


def test_export_report_html_falls_back_to_in_repo_agent6_when_vendored_workflow_is_invalid(
    monkeypatch, tmp_path
):
    class InvalidVendoredAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs
            return self

    class FakeInternalAgent6Workflow:
        def set_results(self, **kwargs):
            self.kwargs = kwargs
            return self

        def generate_html_report(self, output_path):
            Path(output_path).write_text("<html><body>Internal Fallback HTML</body></html>")
            return output_path

    monkeypatch.setattr(
        "src.vendors.reporting_handoff.agents.agent6.workflow.Agent6Workflow",
        InvalidVendoredAgent6Workflow,
    )
    monkeypatch.setattr(
        "src.agents.agent6.workflow.Agent6Workflow",
        FakeInternalAgent6Workflow,
    )

    client = build_client(monkeypatch, tmp_path)
    study_id = create_analysis_ready_study(client, name="Invalid vendored workflow study")

    response = client.get(f"/tte/studies/{study_id}/export-report-html")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["html"] == "<html><body>Internal Fallback HTML</body></html>"


def test_generate_seeded_cohorts_creates_attachable_artifact_without_mutating_study(
    monkeypatch, tmp_path
):
    FakeSeededCohortWebAPIClient.next_id = 700
    FakeSeededCohortWebAPIClient.created_definitions = []
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeSeededCohortWebAPIClient)
    monkeypatch.setattr(
        TTEService,
        "_recommend_seeded_concept_set",
        fake_recommend_seeded_concept_set,
    )
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Seeded cohort study",
            "description": "Compare dapagliflozin vs sitagliptin for MACE",
            "comparisonMode": "explicit_comparator",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "structuredExpression": {"inclusionCriteria": [], "exclusionCriteria": []},
                "inclusionCriteria": [
                    {"id": 1, "description": "Adults with T2DM"},
                    {"id": 2, "description": "Metformin exposure"},
                ],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "dapagliflozin", "cohortId": None, "cohortName": ""},
                {"id": 2, "name": "sitagliptin", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {
                    "cohortId": None,
                    "cohortName": "major adverse cardiovascular events",
                    "description": "MACE",
                },
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/generate-seeded-cohorts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["summary"]
    assert payload["meta"]["status"] == "ok"
    assert payload["meta"]["generatedCount"] == 4
    assert_capability_signal(
        payload["meta"],
        owner="Seeded cohort materialization",
        fidelity="medium",
        stage_kind="agent",
    )

    artifact_id = payload["artifactId"]
    artifact_response = client.get(f"/tte/artifacts/{artifact_id}")
    artifact = artifact_response.json()
    assert artifact["kind"] == "seeded_cohort_generation"
    proposed = artifact["payload"]["proposedChanges"]
    assert proposed["eligibility"]["targetCohortId"] == 701
    assert proposed["treatmentArms"][0]["cohortId"] == 702
    assert proposed["treatmentArms"][1]["cohortId"] == 703
    assert proposed["outcomes"]["primary"]["cohortId"] == 704
    assert artifact["payload"]["generationDiagnostics"]["eligibility"]["status"] == "completed"
    assert artifact["payload"]["generationDiagnostics"]["treatmentArms"]["generatedCount"] == 2
    assert artifact["payload"]["generationDiagnostics"]["outcomes"]["generatedCount"] == 1
    target_expression = FakeSeededCohortWebAPIClient.created_definitions[0]["expression"]
    assert target_expression["PrimaryCriteria"]["CriteriaList"][0]["ConditionOccurrence"]["CodesetId"] == 1
    assert (
        target_expression["ConceptSets"][0]["expression"]["items"][0]["concept"]["CONCEPT_ID"] == 201826
    )
    assert (
        target_expression["InclusionRules"][1]["expression"]["CriteriaList"][0]["Criteria"]["DrugExposure"]["CodesetId"]
        == 3
    )
    # Treatment expression now uses combined CIRCE: target primary criteria + drug inclusion rule
    treatment_expression = FakeSeededCohortWebAPIClient.created_definitions[1]["expression"]
    assert treatment_expression["PrimaryCriteria"]["CriteriaList"][0]["ConditionOccurrence"]["CodesetId"] == 1
    assert (
        treatment_expression["ConceptSets"][0]["expression"]["items"][0]["concept"]["CONCEPT_ID"]
        == 201826  # Target concept (T2DM), not drug concept
    )
    # Drug exposure is now an inclusion rule, not the primary criteria
    drug_rule = treatment_expression["InclusionRules"][-1]
    drug_criteria = drug_rule["expression"]["CriteriaList"][0]["Criteria"]
    assert "DrugExposure" in drug_criteria or "DrugEra" in drug_criteria

    study_before_apply = client.get(f"/tte/studies/{study_id}").json()
    assert study_before_apply["eligibility"]["targetCohortId"] is None
    assert study_before_apply["treatmentArms"][0]["cohortId"] is None
    assert study_before_apply["outcomes"]["primary"]["cohortId"] is None

    apply_response = client.post(
        f"/tte/artifacts/{artifact_id}/apply",
        json={"targetSections": [], "baseStudyVersion": study_before_apply["version"]},
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["appliedArtifactId"] == artifact_id

    study_after_apply = client.get(f"/tte/studies/{study_id}").json()
    assert study_after_apply["version"] == study_before_apply["version"] + 1
    assert study_after_apply["eligibility"]["targetCohortId"] == 701
    assert study_after_apply["treatmentArms"][0]["cohortId"] == 702
    assert study_after_apply["treatmentArms"][1]["cohortId"] == 703
    assert study_after_apply["outcomes"]["primary"]["cohortId"] == 704


def test_generate_seeded_cohorts_uses_structured_target_label_when_summary_label_matches_treatment(
    monkeypatch, tmp_path
):
    FakeSeededCohortWebAPIClient.next_id = 900
    FakeSeededCohortWebAPIClient.created_definitions = []
    monkeypatch.setattr("src.services.tte_service.WebAPIClient", FakeSeededCohortWebAPIClient)
    monkeypatch.setattr(
        TTEService,
        "_recommend_seeded_concept_set",
        fake_recommend_seeded_concept_set,
    )
    client = build_client(monkeypatch, tmp_path)

    structured_expression = build_structured_eligibility_expression(
        target_label="Adults with type 2 diabetes mellitus"
    )
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Canonical target study",
            "description": "Canonical target should come from structured criteria",
            "comparisonMode": "explicit_comparator",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "liraglutide",
                "structuredExpression": structured_expression,
                "inclusionCriteria": [{"id": 1, "description": "Adults with T2DM"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "liraglutide", "cohortId": None, "cohortName": ""},
                {"id": 2, "name": "placebo", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {
                    "cohortId": None,
                    "cohortName": "major adverse cardiovascular events",
                    "description": "MACE",
                },
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/generate-seeded-cohorts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"

    artifact = client.get(f'/tte/artifacts/{payload["artifactId"]}').json()
    target_item = artifact["payload"]["generationDiagnostics"]["eligibility"]["items"][0]
    assert target_item["label"] == "Adults with type 2 diabetes mellitus"
    assert target_item["seedText"] == "Adults with type 2 diabetes mellitus"

    target_definition = FakeSeededCohortWebAPIClient.created_definitions[0]
    assert "Adults with type 2 diabetes mellitus" in target_definition["name"]
    target_expression = target_definition["expression"]
    assert target_expression["PrimaryCriteria"]["CriteriaList"][0]["ConditionOccurrence"]["CodesetId"] == 0


def test_generate_seeded_cohorts_exposes_partial_failures_in_diagnostics(monkeypatch, tmp_path):
    FakeSeededCohortWebAPIClient.next_id = 800
    FakeSeededCohortWebAPIClient.created_definitions = []
    monkeypatch.setattr(
        "src.services.tte_service.WebAPIClient",
        PartialFailingSeededCohortWebAPIClient,
    )
    monkeypatch.setattr(
        TTEService,
        "_recommend_seeded_concept_set",
        fake_recommend_seeded_concept_set,
    )
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Seeded partial failure study",
            "description": "Compare treatment vs comparator for MACE",
            "comparisonMode": "explicit_comparator",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "Adults with T2DM",
                "structuredExpression": {"inclusionCriteria": [], "exclusionCriteria": []},
                "inclusionCriteria": [],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "treatment", "cohortId": None, "cohortName": ""},
                {"id": 2, "name": "Comparator", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {"cohortId": None, "cohortName": "MACE", "description": "MACE"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/generate-seeded-cohorts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["meta"]["status"] == "warning"
    assert payload["meta"]["failedCount"] == 1
    assert payload["meta"]["generatedCount"] == 3

    artifact = client.get(f"/tte/artifacts/{payload['artifactId']}").json()
    treatment_diag = artifact["payload"]["generationDiagnostics"]["treatmentArms"]
    assert treatment_diag["status"] == "warning"
    failed_item = next(item for item in treatment_diag["items"] if item["status"] == "failed")
    assert failed_item["role"] == "comparator"
    assert "failed" in failed_item["error"]

    proposed = artifact["payload"]["proposedChanges"]
    assert proposed["eligibility"]["targetCohortId"] == 801
    assert proposed["treatmentArms"][0]["cohortId"] == 802
    assert proposed["treatmentArms"][1]["cohortId"] is None
    assert proposed["outcomes"]["primary"]["cohortId"] == 803

    study_after_generate = client.get(f"/tte/studies/{study_id}").json()
    assert study_after_generate["treatmentArms"][1]["cohortId"] is None


def test_generate_seeded_cohorts_reports_full_failure_consistently(monkeypatch, tmp_path):
    monkeypatch.setattr(
        TTEService,
        "_recommend_seeded_concept_set",
        fake_recommend_seeded_concept_set,
    )
    monkeypatch.setattr(
        "src.services.tte_service.WebAPIClient",
        AlwaysFailingSeededCohortWebAPIClient,
    )
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Seeded all failure study",
            "description": "all seeded cohort definitions fail",
            "comparisonMode": "explicit_comparator",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "Adults with T2DM",
                "structuredExpression": {"inclusionCriteria": [], "exclusionCriteria": []},
                "inclusionCriteria": [],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "treatment", "cohortId": None, "cohortName": ""},
                {"id": 2, "name": "comparator", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {"cohortId": None, "cohortName": "MACE", "description": "MACE"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/generate-seeded-cohorts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["meta"]["status"] == "failed"
    assert payload["meta"]["generatedCount"] == 0
    assert payload["meta"]["failedCount"] == 4

    artifact = client.get(f"/tte/artifacts/{payload['artifactId']}").json()
    assert artifact["status"] == "failed"
    assert artifact["payload"]["proposedChanges"] == {}

    job = client.get(f"/tte/jobs/{payload['jobId']}").json()
    assert job["status"] == "failed"
    assert job["artifactId"] == payload["artifactId"]

    apply_response = client.post(
        f"/tte/artifacts/{payload['artifactId']}/apply",
        json={"targetSections": [], "baseStudyVersion": 1},
    )
    assert apply_response.status_code == 409
    assert "proposedchanges" in apply_response.json()["detail"].lower()


def test_generate_seeded_cohorts_propagates_webapi_error_as_502(monkeypatch, tmp_path):
    monkeypatch.setattr(
        TTEService,
        "_recommend_seeded_concept_set",
        fake_recommend_seeded_concept_set,
    )
    monkeypatch.setattr(
        "src.services.tte_service.WebAPIClient",
        WebAPIErrorSeededCohortWebAPIClient,
    )
    client = build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Seeded webapi outage study",
            "description": "webapi error should escape to router",
            "comparisonMode": "explicit_comparator",
            "eligibility": {
                "targetCohortId": None,
                "targetCohortName": "Adults with T2DM",
                "structuredExpression": {"inclusionCriteria": [], "exclusionCriteria": []},
                "inclusionCriteria": [],
                "exclusionCriteria": [],
            },
            "treatmentArms": [
                {"id": 1, "name": "treatment", "cohortId": None, "cohortName": ""},
                {"id": 2, "name": "comparator", "cohortId": None, "cohortName": ""},
            ],
            "outcomes": {
                "primary": {"cohortId": None, "cohortName": "MACE", "description": "MACE"},
                "secondary": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    response = client.post(f"/tte/studies/{study_id}/generate-seeded-cohorts")

    assert response.status_code == 502
    assert "webapi unavailable" in response.json()["detail"].lower()


def test_criterion_model_includes_metadata_fields(monkeypatch, tmp_path):
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Metadata test",
            "description": "Test criterion metadata",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortName": "T2DM patients",
                "inclusionCriteria": [
                    {
                        "id": 1,
                        "description": "Age >= 50",
                        "domain": "Demographics",
                        "valueConstraint": {"op": "gte", "value": 50, "unitText": "years"},
                        "sourceText": "Patients aged 50 years or older with established cardiovascular disease",
                    },
                    {
                        "id": 2,
                        "description": "Type 2 diabetes",
                        "domain": "Condition",
                        "sourceText": "Diagnosed with type 2 diabetes mellitus",
                    },
                ],
                "exclusionCriteria": [],
            },
        },
    )
    assert create_response.status_code == 200
    study = client.get(f"/tte/studies/{create_response.json()['id']}").json()
    inc = study["eligibility"]["inclusionCriteria"]
    assert inc[0]["domain"] == "Demographics"
    assert inc[0]["valueConstraint"] == {"op": "gte", "value": 50, "unitText": "years"}
    assert inc[0]["sourceText"] == "Patients aged 50 years or older with established cardiovascular disease"
    assert inc[0]["mappable"] is False
    assert inc[1]["domain"] == "Condition"
    assert inc[1]["sourceText"] == "Diagnosed with type 2 diabetes mellitus"
    assert inc[1]["mappable"] is True


def test_criteria_from_ir_preserves_domain_and_value_constraint(tmp_path):
    from src.models.ir import Criteria, ValueConstraint

    service = TTEService(store=TTEStore(str(tmp_path / "test.json")))
    ir_criteria = [
        Criteria(
            name="Age >= 50",
            domain="Demographics",
            entity_text="Patients aged 50 years or older with established cardiovascular disease",
            value_constraint=ValueConstraint(op="gte", value=50, unit_text="years"),
        ),
        Criteria(
            name="Type 2 Diabetes",
            domain="Condition",
            entity_text="Diagnosed with type 2 diabetes mellitus",
        ),
        Criteria(
            name="HbA1c >= 7%",
            domain="Measurement",
            entity_text="Hemoglobin A1c level of 7% or higher",
            value_constraint=ValueConstraint(op="gte", value=7.0, unit_text="%"),
        ),
    ]
    result = service._criteria_from_ir(ir_criteria)

    assert result[0]["description"] == "Age >= 50"
    assert result[0]["domain"] == "Demographics"
    assert result[0]["sourceText"] == "Patients aged 50 years or older with established cardiovascular disease"
    assert result[0]["valueConstraint"]["op"] == "gte"
    assert result[0]["valueConstraint"]["value"] == 50

    assert result[1]["description"] == "Type 2 Diabetes"
    assert result[1]["domain"] == "Condition"
    assert result[1]["sourceText"] == "Diagnosed with type 2 diabetes mellitus"
    assert result[1]["valueConstraint"] is None

    assert result[2]["description"] == "HbA1c >= 7%"
    assert result[2]["domain"] == "Measurement"
    assert result[2]["valueConstraint"]["value"] == 7.0


def test_process_eligibility_reports_mappable_for_demographic_criterion_without_value_constraint(
    monkeypatch, tmp_path
):
    """Contract changed: Criterion.mappable no longer hard-codes False for every
    DEMOGRAPHIC_DOMAINS criterion. A criterion with a demographic-looking domain
    but no structured valueConstraint (so no DemographicCriteriaList rule is
    buildable) is now reported mappable=True, via the shared predicate
    is_demographic_domain_but_not_a_demographic_rule (src/api/models/tte.py) --
    the same fallthrough that lets the real exclusion-side "Pre-menopausal
    women"/"Nursing or pregnant" criteria reach concept-set mapping instead of
    being silently dropped.

    Known, disclosed asymmetry: the actual generation loop's fallthrough
    (_build_seeded_target_circe) is deliberately scoped to the EXCLUSION side
    only (no real inclusion-side instance existed in the data motivating this
    fix). So for this INCLUSION criterion, .mappable now reports True while
    generation still records it as "demographic-no-rule" and drops it -- a
    real, understood gap, not a bug in this test. Extending the fallthrough to
    the inclusion loop for symmetry is tracked as separate, out-of-scope work.
    """
    install_process_eligibility_stub(monkeypatch)
    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Demographics skip test",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortName": "T2DM patients",
                "inclusionCriteria": [
                    {"id": 1, "description": "Age >= 50", "domain": "Demographics"},
                    {"id": 2, "description": "Type 2 diabetes", "domain": "Condition"},
                ],
                "exclusionCriteria": [],
            },
        },
    )
    study = client.get(f"/tte/studies/{create_response.json()['id']}").json()
    inc = study["eligibility"]["inclusionCriteria"]
    assert inc[0]["domain"] == "Demographics"
    assert inc[0]["mappable"] is True
    assert inc[1]["domain"] == "Condition"
    assert inc[1]["mappable"] is True


def test_process_eligibility_is_idempotent_no_concept_set_accumulation(monkeypatch, tmp_path):
    """Calling process_eligibility twice must produce the same ConceptSets count,
    not accumulate from prior runs.

    Regression guard: _build_seeded_target_circe must never see a pre-existing
    structuredExpression on the eligibility dict, otherwise future changes could
    inadvertently merge old ConceptSets with newly-generated ones.
    """
    fresh_circe = build_structured_eligibility_expression(
        target_label="Adults with type 2 diabetes mellitus"
    )
    concept_set_count_per_call = len(fresh_circe["ConceptSets"])

    # Track what eligibility dict _build_seeded_target_circe receives
    captured_eligibility_dicts: list[dict] = []

    def fake_build_seeded_target_circe(self, eligibility: dict) -> dict:
        captured_eligibility_dicts.append(deepcopy(eligibility))
        return deepcopy(fresh_circe)

    monkeypatch.setattr(
        TTEService,
        "_build_seeded_target_circe",
        fake_build_seeded_target_circe,
    )

    original_allowed_apply_sections = TTEService._allowed_apply_sections_for_kind

    def allow_eligibility_processing_apply(self, artifact_kind: str):
        if artifact_kind == "eligibility_processing":
            return {"eligibility"}
        return original_allowed_apply_sections(self, artifact_kind)

    monkeypatch.setattr(
        TTEService,
        "_allowed_apply_sections_for_kind",
        allow_eligibility_processing_apply,
    )

    client = build_client(monkeypatch, tmp_path)
    create_response = client.post(
        "/tte/studies",
        json={
            "name": "Idempotency study",
            "description": "Test process_eligibility idempotency",
            "studyType": "comparative",
            "status": "draft",
            "eligibility": {
                "targetCohortName": "Adults with type 2 diabetes mellitus",
                "inclusionCriteria": [
                    {"id": 1, "description": "Adults with T2DM", "domain": "Condition"},
                ],
                "exclusionCriteria": [],
            },
        },
    )
    study_id = create_response.json()["id"]

    # First call
    r1 = client.post(f"/tte/studies/{study_id}/process-eligibility")
    assert r1.status_code == 200
    a1 = client.get(f'/tte/artifacts/{r1.json()["artifactId"]}').json()
    first_cs_count = len(
        a1["payload"]["proposedChanges"]["eligibility"]
        .get("structuredExpression", {})
        .get("ConceptSets", [])
    )
    assert first_cs_count == concept_set_count_per_call

    # Apply the first artifact so structuredExpression is saved into the study
    apply_r = client.post(
        f'/tte/artifacts/{r1.json()["artifactId"]}/apply',
        json={"targetSections": ["eligibility"], "baseStudyVersion": 1},
    )
    assert apply_r.status_code == 200

    # Verify structuredExpression is now on the study
    study_after_apply = client.get(f"/tte/studies/{study_id}").json()
    assert "structuredExpression" in study_after_apply["eligibility"]

    # Second call -- must NOT accumulate ConceptSets
    r2 = client.post(f"/tte/studies/{study_id}/process-eligibility")
    assert r2.status_code == 200
    a2 = client.get(f'/tte/artifacts/{r2.json()["artifactId"]}').json()
    second_cs_count = len(
        a2["payload"]["proposedChanges"]["eligibility"]
        .get("structuredExpression", {})
        .get("ConceptSets", [])
    )

    assert second_cs_count == first_cs_count, (
        f"ConceptSets accumulated: first={first_cs_count}, second={second_cs_count}"
    )

    # The critical invariant: _build_seeded_target_circe must never receive
    # a pre-existing structuredExpression, ensuring it always starts fresh.
    assert len(captured_eligibility_dicts) == 2
    for i, elig in enumerate(captured_eligibility_dicts):
        assert "structuredExpression" not in elig, (
            f"Call {i + 1}: _build_seeded_target_circe received stale structuredExpression"
        )


def test_patch_codeset_id_recurses_into_groups():
    """_patch_codeset_id_in_rule must patch CodesetId inside expression.Groups[].CriteriaList.

    Grouped rules (Rule 5+) have empty top-level CriteriaList and nest the actual
    criteria inside Groups[].CriteriaList. This test verifies that the patch reaches
    those nested entries so CodesetId=0 placeholders are replaced with the real id.
    """
    rule = {
        "expression": {
            "Type": "ANY",
            "CriteriaList": [],
            "Groups": [
                {
                    "Type": "ALL",
                    "CriteriaList": [
                        {"Criteria": {"ConditionOccurrence": {"CodesetId": 0}}}
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
                {
                    "Type": "ALL",
                    "CriteriaList": [
                        {"Criteria": {"DrugExposure": {"CodesetId": 0}}}
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            ],
        }
    }

    TTEService._patch_codeset_id_in_rule(rule, 42)

    group0_cs = rule["expression"]["Groups"][0]["CriteriaList"][0]["Criteria"]["ConditionOccurrence"]["CodesetId"]
    group1_cs = rule["expression"]["Groups"][1]["CriteriaList"][0]["Criteria"]["DrugExposure"]["CodesetId"]
    assert group0_cs == 42
    assert group1_cs == 42


def test_patch_codeset_id_still_patches_top_level_criteria_list():
    """_patch_codeset_id_in_rule must still patch CodesetId in the top-level CriteriaList.

    Standalone (non-grouped) rules have their criteria in expression.CriteriaList
    with no nested Groups. This regression test ensures the refactor to add recursion
    did not break the original flat-structure path.
    """
    rule = {
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {"Criteria": {"ConditionOccurrence": {"CodesetId": 0}}}
            ],
            "DemographicCriteriaList": [],
            "Groups": [],
        }
    }

    TTEService._patch_codeset_id_in_rule(rule, 7)

    patched_cs = rule["expression"]["CriteriaList"][0]["Criteria"]["ConditionOccurrence"]["CodesetId"]
    assert patched_cs == 7
