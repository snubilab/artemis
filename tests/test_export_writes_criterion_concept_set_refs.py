"""The delivered CIRCE file carries the criterion -> concept-set map the delivery gate reads.

THE DEFECT, P3 dry-rebuild smoke, 2026-10-13, code 5028579
(``output/site_gap/2026-10-12_p3_dry/arm_smoke/checks/gate.txt``)::

    declare_treatment.circe.json  FAIL  stated threshold missing (1): 24 store criteria state
    a verified threshold and the file carries no _criterionConceptSetRefs, so whether each
    emitted a value condition cannot be checked

``_build_seeded_target_circe`` writes ``_criterionConceptSetRefs`` into the expression it
builds, and ``process_eligibility`` pops it out again: the stored ``structuredExpression``
goes without it and the map survives only in that artifact's payload, as
``criterionConceptSetRefs``. ``scripts/export_seeded_cohorts.py`` replays the stored
expression, so no file it exported carried the map. Four readers in the gate went blind:
check (j) failed closed on every file, check (aa) failed closed wherever a pair exists,
the accounting anchor ``mapped == len(refs)`` did not run ("no concept-set links
recorded"), and a restatement-collapsed skip could not be reconciled.

The export now copies the map from the one artifact whose proposed expression IS the
stored expression -- the expression the map's codeset ids were minted in -- and from
nowhere else.

Real data only: ``tests/fixtures/criterion_refs_delivery_cases.json.gz`` holds, verbatim,
the P3 smoke's study 13 and its three artifacts with the file it exported at 5028579, and
the 2026-09-18 verify4 run's CARMELINA (study 9), the only exported files under
``output/`` where check (aa) has a pair to judge. Its ``_provenance`` names each source
and its sha256. No database, no LLM: the build is replaced by its own captured output.
"""

from __future__ import annotations

import gzip
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.verify_atlas_renderable import check_file
from scripts.verify_circe_delivery import (
    absence_forbids_required_values_findings,
    criterion_accounting,
    threshold_without_value_filter_findings,
)
from src.utils.circe_lint import (
    CRITERION_CONCEPT_SET_REFS_KEY,
    VALUE_CONDITION_ATTRIBUTES,
    presence_bound_forbidden_pairs,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "criterion_refs_delivery_cases.json.gz"
)
FIXTURE = json.loads(gzip.decompress(FIXTURE_PATH.read_bytes()))
SMOKE = FIXTURE["p3_smoke_declare"]
CARMELINA = FIXTURE["verify4_carmelina"]


def _artifact(case: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    return next(a for a in case["artifacts"] if a["id"] == artifact_id)


def _refs(case: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    return _artifact(case, artifact_id)["payload"]["criterionConceptSetRefs"]


def _export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: dict[str, Any],
    *,
    study: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    captured: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Path]:
    """Run ``export_seeded_cohorts.main`` on one real case; return the written treatment file.

    The store is a real ``TTEStore`` over the case's study and artifacts. Only the build is
    replaced: it hands the export the expression the real build captured at 5028579 -- the
    delivered file itself -- through the same ``create_cohort_definition`` seam.
    """
    import src.pipeline.webapi_client as webapi_client
    import src.services.tte_service as tte_service

    study = deepcopy(study if study is not None else case["study"])
    artifacts = deepcopy(artifacts if artifacts is not None else case["artifacts"])
    captured = deepcopy(captured if captured is not None else case["delivered"])
    store_path = tmp_path / "studies.json"
    store_path.write_text(json.dumps({"studies": [study], "artifacts": artifacts, "jobs": []}))

    class _Service:
        def __init__(self, store: Any) -> None:
            self.store = store

        def _build_seeded_cohort_artifact_payload(self, study_id: int, study_arg: dict) -> dict:
            arm = (study_arg.get("treatmentArms") or [{}])[0].get("name")
            webapi_client.WebAPIClient.create_cohort_definition(
                None, f"TTE {study_id} Treatment - {arm}", captured
            )
            return {"generationDiagnostics": []}

    monkeypatch.setattr(tte_service, "TTEService", _Service)
    monkeypatch.delenv("TTE_STORE_PATH", raising=False)
    monkeypatch.setenv("TTE_DRUG_ANCHORED_ENTRY", "1")

    from scripts.export_seeded_cohorts import main

    out_dir = tmp_path / "out"
    main([
        "--store", str(store_path), "--out", str(out_dir),
        "--study-id", str(study["id"]), "--slug-map", f"{study['id']}={case['slug']}",
    ])
    written = out_dir / f"{case['slug']}_treatment.circe.json"
    return json.loads(written.read_text()), written


class TestTheFilesExportedBeforeTheMapTravelled:
    """What the gate could say about the real files, as they were delivered."""

    def test_should_fail_j_closed_when_the_smoke_file_carries_no_map(self):
        assert CRITERION_CONCEPT_SET_REFS_KEY not in SMOKE["delivered"]
        [finding] = threshold_without_value_filter_findings(
            SMOKE["delivered"], SMOKE["study"]
        ).failures
        assert "24 store criteria state a verified threshold" in finding
        assert f"carries no {CRITERION_CONCEPT_SET_REFS_KEY}" in finding

    def test_should_fail_aa_closed_when_the_carmelina_file_carries_no_map(self):
        assert CRITERION_CONCEPT_SET_REFS_KEY not in CARMELINA["delivered"]
        [finding] = absence_forbids_required_values_findings(
            CARMELINA["delivered"], CARMELINA["study"]
        )
        assert "2 presence/absence pair(s)" in finding
        assert f"carries no {CRITERION_CONCEPT_SET_REFS_KEY}" in finding

    def test_should_record_no_concept_set_link_when_the_smoke_file_carries_no_map(self):
        _violations, summary = criterion_accounting(SMOKE["delivered"], SMOKE["study"])
        assert "no concept-set links recorded" in summary


class TestTheExportWritesTheMap:
    def test_should_write_the_map_of_the_artifact_that_proposed_the_stored_expression(
        self, monkeypatch, tmp_path, capsys
    ):
        """art_220 proposed exactly the stored expression; art_219, an earlier run of the
        same capability for the same study, proposed a different one with a different map."""
        written, _path = _export(monkeypatch, tmp_path, SMOKE)
        assert written[CRITERION_CONCEPT_SET_REFS_KEY] == _refs(SMOKE, "art_220")
        assert written[CRITERION_CONCEPT_SET_REFS_KEY] != _refs(SMOKE, "art_219")
        assert "art_220" in capsys.readouterr().err

    def test_should_change_nothing_else_in_the_exported_file(self, monkeypatch, tmp_path):
        """The harness reproduces the 5028579 file exactly; the map is the only difference."""
        written, _path = _export(monkeypatch, tmp_path, SMOKE)
        written.pop(CRITERION_CONCEPT_SET_REFS_KEY)
        assert written == SMOKE["delivered"]

    def test_should_judge_j_on_the_smoke_file(self, monkeypatch, tmp_path):
        """Judged, not skipped: the two recurrence counts (exclusions #33/#34, 'three or
        more') are kept without a filter and recorded, so they WARN; every lab threshold
        emitted its filter, so nothing FAILs."""
        written, _path = _export(monkeypatch, tmp_path, SMOKE)
        findings = threshold_without_value_filter_findings(written, SMOKE["study"])
        assert findings.failures == []
        assert [w.split(":")[0] for w in findings.warnings] == [
            "exclusion #33 'chronic cystitis'",
            "exclusion #34 'recurrent urinary tract infections'",
        ]

    def test_should_judge_aa_on_the_smoke_file(self, monkeypatch, tmp_path):
        """This file has no presence/absence pair, so (aa) passes on its own evidence."""
        written, _path = _export(monkeypatch, tmp_path, SMOKE)
        assert presence_bound_forbidden_pairs(written) == []
        assert absence_forbids_required_values_findings(written, SMOKE["study"]) == []

    def test_should_judge_aa_and_fail_carmelinas_hba1c_range(self, monkeypatch, tmp_path):
        """Both pairs come from the one line 'HbA1c of >= 6.5% and <= 10.0%': the presence
        requires 6.5..10.0 and the absences forbid >= 6.5 and <= 10.0 -- the defect (aa)
        exists for, now reported as a finding instead of 'cannot be checked'."""
        written, _path = _export(monkeypatch, tmp_path, CARMELINA)
        assert written[CRITERION_CONCEPT_SET_REFS_KEY] == _refs(CARMELINA, "art_217")
        findings = absence_forbids_required_values_findings(written, CARMELINA["study"])
        assert len(findings) == 2
        for finding in findings:
            assert "absence forbids the values the presence requires" in finding
            assert "cannot be checked" not in finding
            assert "HbA1c" in finding

    def test_should_anchor_the_mapped_count_to_the_map(self, monkeypatch, tmp_path):
        written, _path = _export(monkeypatch, tmp_path, SMOKE)
        _violations, summary = criterion_accounting(written, SMOKE["study"])
        assert "32 of 32 mapped concept-set linked" in summary

    def test_should_reconcile_carmelinas_restated_skips_once_the_survivors_are_known(
        self, monkeypatch, tmp_path
    ):
        """Without the map no collapsed member can show its survivor emitted, so two skips
        read as unreconciled; with it they reconcile."""
        before, _ = criterion_accounting(CARMELINA["delivered"], CARMELINA["study"])
        assert any("does not hold" in v for v in before)
        written, _path = _export(monkeypatch, tmp_path, CARMELINA)
        after, summary = criterion_accounting(written, CARMELINA["study"])
        assert not any("does not hold" in v for v in after)
        assert "38 of 38 mapped concept-set linked" in summary

    def test_should_leave_the_file_renderable_by_atlas(self, monkeypatch, tmp_path):
        _written, path = _export(monkeypatch, tmp_path, SMOKE)
        assert check_file(path) == []


class TestTheMapComesOnlyFromTheExpressionItDescribes:
    def test_should_write_no_map_when_no_artifact_proposed_the_stored_expression(
        self, monkeypatch, tmp_path, capsys
    ):
        """art_219's map was minted for another expression; carried over, it would point
        the gate at the wrong codesets. Without art_220 the file carries no map, and (j)
        says so instead of judging the wrong rows."""
        artifacts = [a for a in SMOKE["artifacts"] if a["id"] != "art_220"]
        written, _path = _export(monkeypatch, tmp_path, SMOKE, artifacts=artifacts)
        assert CRITERION_CONCEPT_SET_REFS_KEY not in written
        [finding] = threshold_without_value_filter_findings(written, SMOKE["study"]).failures
        assert f"carries no {CRITERION_CONCEPT_SET_REFS_KEY}" in finding
        assert "no artifact" in capsys.readouterr().err

    def test_should_write_no_map_when_two_artifacts_for_the_stored_expression_disagree(
        self, monkeypatch, tmp_path, capsys
    ):
        rival = deepcopy(_artifact(SMOKE, "art_220"))
        rival["id"] = "art_rival"
        rival["payload"]["criterionConceptSetRefs"].pop("inclusion:1")
        written, _path = _export(
            monkeypatch, tmp_path, SMOKE, artifacts=[*SMOKE["artifacts"], rival]
        )
        assert CRITERION_CONCEPT_SET_REFS_KEY not in written
        err = capsys.readouterr().err
        assert "art_220" in err and "art_rival" in err

    def test_should_keep_the_map_the_stored_expression_already_carries(
        self, monkeypatch, tmp_path
    ):
        """A store built without the draft path keeps the map in the expression, and the
        build copies it into every arm; the export must not swap it for an artifact's."""
        refs = _refs(SMOKE, "art_220")
        study = deepcopy(SMOKE["study"])
        study["eligibility"]["structuredExpression"][CRITERION_CONCEPT_SET_REFS_KEY] = refs
        captured = deepcopy(SMOKE["delivered"])
        captured[CRITERION_CONCEPT_SET_REFS_KEY] = refs
        written, _path = _export(
            monkeypatch, tmp_path, SMOKE, study=study, artifacts=[], captured=captured
        )
        assert written[CRITERION_CONCEPT_SET_REFS_KEY] == refs


class TestJFailsOnTheFileWhenAThresholdLostItsFilter:
    def test_should_fail_j_when_the_hba1c_criterion_emits_no_value_filter(
        self, monkeypatch, tmp_path
    ):
        """Inclusion #11 'HbA1C >= 6.5%' minted codeset 6 and emitted ValueAsNumber on it.
        Strip the value condition from every criterion over codeset 6 and (j) must name it."""
        written, _path = _export(monkeypatch, tmp_path, SMOKE)
        codeset = written[CRITERION_CONCEPT_SET_REFS_KEY]["inclusion:11"]
        stripped = 0

        def strip(node: Any) -> None:
            nonlocal stripped
            if isinstance(node, dict):
                if node.get("CodesetId") == codeset:
                    for key in VALUE_CONDITION_ATTRIBUTES & set(node):
                        del node[key]
                        stripped += 1
                for value in node.values():
                    strip(value)
            elif isinstance(node, list):
                for value in node:
                    strip(value)

        strip(written["InclusionRules"])
        assert stripped > 0
        [finding] = threshold_without_value_filter_findings(written, SMOKE["study"]).failures
        assert finding.startswith("inclusion #11 ")
        assert f"codeset {codeset} carries no value condition" in finding
        assert "it is applied as a value filter, and none was emitted" in finding
