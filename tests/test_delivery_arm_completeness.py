"""A delivery is incomplete when an expected arm produced no file, and that must fail.

The 2026-09-05 wiring-fix export wrote five files, recorded five in `manifest.json`, and
`verify_circe_delivery.py` exited 0 — while EMPA-REG had only a treatment arm. Its
comparator builder had raised `ValueError: No concept mapping found for BI 10773`, and
`_materialize_seeded_cohort_item` caught it with a bare `except Exception: pass`, so a
hard failure became a missing file that no check looked for.

Every check in the gate iterates the files that ARE present, so a dropped arm is
invisible to all of them by construction. These tests pin the absent case.

The expected arm set is derived from the store's own `treatmentArms` rather than assumed
to be two, so a study that legitimately declares a single arm needs no opt-out flag —
which is why none is added. A flag that lets a delivery gate ignore a missing file is a
hole in the gate, and the single-arm case does not need one.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from src.utils.circe_lint import expected_arm_roles, missing_arm_roles


def _study(study_id: int, arm_names: list[str]) -> dict[str, Any]:
    return {
        "id": study_id,
        "name": "Study " + str(study_id),
        "comparisonMode": "target_minus_treatment",
        "treatmentArms": [{"name": n} for n in arm_names],
        "eligibility": {
            "structuredExpression": {
                "ConceptSets": [
                    {
                        "id": 1,
                        "name": "drug",
                        "expression": {
                            "items": [
                                {
                                    "concept": {
                                        "CONCEPT_ID": 45774751,
                                        "CONCEPT_NAME": "empagliflozin",
                                        "DOMAIN_ID": "Drug",
                                        "VOCABULARY_ID": "RxNorm",
                                        "CONCEPT_CLASS_ID": "Ingredient",
                                        "CONCEPT_CODE": "1",
                                    },
                                    "includeDescendants": True,
                                    "isExcluded": False,
                                }
                            ]
                        },
                    }
                ],
                "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
                "InclusionRules": [
                    {"name": "rule one", "expression": {"Type": "ALL", "CriteriaList": []}},
                    {"name": "rule two", "expression": {"Type": "ALL", "CriteriaList": []}},
                ],
            }
        },
    }


class TestExpectedArmRolesComesFromTheStore:
    def test_should_expect_both_arms_when_the_study_declares_two(self):
        assert expected_arm_roles(_study(8, ["BI 10773", "Placebo"])) == ["treatment", "comparator"]

    def test_should_expect_only_treatment_when_the_study_declares_one_arm(self):
        """The single-arm case is answered by the store, not by an opt-out flag."""
        assert expected_arm_roles(_study(8, ["BI 10773"])) == ["treatment"]

    def test_should_expect_nothing_when_the_study_declares_no_arms(self):
        assert expected_arm_roles(_study(8, [])) == []


class TestMissingArmRoles:
    def test_should_report_the_comparator_when_only_a_treatment_file_was_produced(self):
        study = _study(8, ["BI 10773", "Placebo"])
        assert missing_arm_roles(study, ["treatment"]) == ["comparator"]

    def test_should_report_nothing_when_every_expected_arm_was_produced(self):
        study = _study(8, ["BI 10773", "Placebo"])
        assert missing_arm_roles(study, ["treatment", "comparator"]) == []

    def test_should_report_nothing_for_a_single_arm_study_with_its_one_file(self):
        assert missing_arm_roles(_study(8, ["BI 10773"]), ["treatment"]) == []


def _write_export(tmp_path, study, roles):
    """Write one minimal per-arm CIRCE file per role, matching the store shape."""
    se = study["eligibility"]["structuredExpression"]
    for role in roles:
        payload = json.loads(json.dumps(se))
        (tmp_path / ("empa-reg_" + role + ".circe.json")).write_text(json.dumps(payload))


@pytest.fixture
def store_file(tmp_path):
    def _make(study):
        path = tmp_path / "studies.json"
        path.write_text(json.dumps([study]))
        return path
    return _make


class TestTheGateFailsAnIncompleteDirectory:
    def test_should_fail_when_a_two_arm_study_produced_only_a_treatment_file(
        self, tmp_path, store_file, capsys, monkeypatch
    ):
        """The exact 2026-09-05 shape: files present all pass, yet the delivery is short an arm."""
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study(8, ["BI 10773", "Placebo"])
        _write_export(tmp_path, study, ["treatment"])
        path = store_file(study)

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(path), "--map", "empa-reg=8"])
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "comparator" in out
        assert "MISSING" in out

    def test_should_pass_when_both_arms_are_present(
        self, tmp_path, store_file, capsys, monkeypatch
    ):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study(8, ["BI 10773", "Placebo"])
        _write_export(tmp_path, study, ["treatment", "comparator"])
        path = store_file(study)

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(path), "--map", "empa-reg=8"])
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "MISSING" not in out

    def test_should_pass_a_single_arm_study_with_only_its_treatment_file(
        self, tmp_path, store_file, capsys, monkeypatch
    ):
        """No opt-out flag is involved: the store says one arm, one file satisfies it."""
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study(8, ["BI 10773"])
        _write_export(tmp_path, study, ["treatment"])
        path = store_file(study)

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(path), "--map", "empa-reg=8"])
        out = capsys.readouterr().out
        assert rc == 0, out

    def test_should_not_demand_arms_for_a_study_absent_from_the_directory(
        self, tmp_path, store_file, capsys, monkeypatch
    ):
        """The gate verifies the directory it was given, not the whole store — otherwise
        a deliberate single-study export could never pass."""
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study(8, ["BI 10773", "Placebo"])
        other = _study(9, ["linagliptin", "placebo"])
        _write_export(tmp_path, study, ["treatment", "comparator"])
        path = tmp_path / "studies.json"
        path.write_text(json.dumps([study, other]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(path), "--map", "empa-reg=8,carmelina=9"])
        out = capsys.readouterr().out
        assert rc == 0, out


class TestTheExporterRefusesAnIncompleteExport:
    """`export_seeded_cohorts.py` already refuses to write a manifest on a lint
    violation. An arm that produced no cohort is the same class of violation, and used
    not to be treated as one: the 2026-09-05 run wrote `manifest.json` listing five
    files for three two-arm studies and exited 0.
    """

    @staticmethod
    def _install_fake_service(monkeypatch, study, produced_roles):
        """A service that produces cohorts for `produced_roles` only."""
        import src.pipeline.webapi_client as webapi_client
        import src.services.tte_service as tte_service
        import src.services.tte_store as tte_store

        expression = json.loads(json.dumps(study["eligibility"]["structuredExpression"]))

        class _Store:
            def __init__(self, *a, **k):
                pass

            def get_study(self, study_id):
                return study

        class _Service:
            def __init__(self, store):
                self.store = store

            def _build_seeded_cohort_artifact_payload(self, study_id, study_arg):
                labels = {"treatment": "Treatment - drug", "comparator": "Comparator - No drug"}
                for role in produced_roles:
                    webapi_client.WebAPIClient.create_cohort_definition(
                        None, "TTE " + str(study_id) + " " + labels[role], expression
                    )
                return {"generationDiagnostics": []}

        monkeypatch.setattr(tte_service, "TTEService", _Service)
        monkeypatch.setattr(tte_store, "TTEStore", _Store)

    def test_should_exit_non_zero_and_write_no_manifest_when_an_arm_produced_nothing(
        self, tmp_path, store_file, monkeypatch, capsys
    ):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study(8, ["BI 10773", "Placebo"])
        path = store_file(study)
        self._install_fake_service(monkeypatch, study, ["treatment"])
        out_dir = tmp_path / "out"

        from scripts.export_seeded_cohorts import main

        rc = main([
            "--store", str(path), "--out", str(out_dir), "--study-id", "8",
            "--slug-map", "8=empa-reg",
        ])
        err = capsys.readouterr().err
        assert rc == 1, err
        assert "missing_arm" in err
        assert not (out_dir / "manifest.json").exists()

    def test_should_write_a_manifest_recording_expected_and_produced_arms_when_complete(
        self, tmp_path, store_file, monkeypatch, capsys
    ):
        """The omission has to be legible after the fact, so the manifest records both
        sides even on a clean run."""
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study(8, ["BI 10773", "Placebo"])
        path = store_file(study)
        self._install_fake_service(monkeypatch, study, ["treatment", "comparator"])
        out_dir = tmp_path / "out"

        from scripts.export_seeded_cohorts import main

        rc = main([
            "--store", str(path), "--out", str(out_dir), "--study-id", "8",
            "--slug-map", "8=empa-reg",
        ])
        assert rc == 0, capsys.readouterr().err
        manifest = json.loads((out_dir / "manifest.json").read_text())
        (entry,) = manifest["studies"]
        assert entry["expected_arms"] == ["treatment", "comparator"]
        assert entry["produced_arms"] == ["comparator", "treatment"]
        assert entry["arm_names"] == ["BI 10773", "Placebo"]
