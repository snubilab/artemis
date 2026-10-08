"""Check (w): a delivered file must not carry an inclusion rule another inclusion rule already says.

And the permit beside it: a ``_restatedRuleCollapse`` record is the producer's own claim that a
rule it removed was redundant, so the gate re-derives that claim on the file it is handed with the
same predicate the producer used (``src.services.restated_rules.rule_relation``) instead of taking
it. Measured motivation: ``deliveries/2026-09-23`` CARMELINA #11 / #14 / #15.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.verify_circe_delivery import restated_rule_collapse_violations
from src.services.restated_rules import (
    IDENTICAL_REASON,
    RESTATED_RULE_COLLAPSE_KEY,
    collapse_redundant_inclusion_rules,
    redundant_inclusion_rule_findings,
)
from tests.test_restated_rule_collapse import _carmelina_shape

REPO = Path(__file__).resolve().parents[1]
DELIVERY_0923 = REPO / "deliveries" / "2026-09-23"


def _delivered(name: str) -> dict[str, Any]:
    return json.loads((DELIVERY_0923 / f"{name}.circe.json").read_text())


class TestRedundantRuleCheck:
    @pytest.mark.parametrize("arm", ["treatment", "comparator"])
    def test_should_fail_carmelina_0923_when_rules_14_and_15_restate_rule_11(self, arm):
        findings = redundant_inclusion_rule_findings(_delivered(f"carmelina_{arm}"))
        assert len(findings) == 2, findings
        assert findings[0].startswith("#14 'Use of GLP-1 receptor agonists")
        assert "is identical to #11 'Exclusion of GLP-1 receptor agonists if recent" in findings[0]
        assert findings[1].startswith("#15 'DPP-4 inhibitors' is implied by")
        assert "#11 'Exclusion of GLP-1 receptor agonists if recent" in findings[1]

    @pytest.mark.parametrize("arm", ["treatment", "comparator"])
    def test_should_pass_carmelina_0923_once_the_collapse_has_run(self, arm):
        expression = _delivered(f"carmelina_{arm}")
        collapse_redundant_inclusion_rules(expression)
        assert redundant_inclusion_rule_findings(expression) == []
        assert restated_rule_collapse_violations(expression) == []


class TestCollapseRecordIsRejudged:
    @staticmethod
    def _collapsed() -> dict[str, Any]:
        expression = _carmelina_shape()
        collapse_redundant_inclusion_rules(expression)
        return expression

    def test_should_accept_records_the_file_bears_out(self):
        assert restated_rule_collapse_violations(self._collapsed()) == []

    def test_should_accept_a_file_that_predates_the_record(self):
        expression = _carmelina_shape()
        assert RESTATED_RULE_COLLAPSE_KEY not in expression
        assert restated_rule_collapse_violations(expression) == []

    def test_should_fail_when_the_removed_rule_differs_from_its_survivor(self):
        """Misuse: a record laundering a rule out of the file whose window was not the
        survivor's -- the rule was NOT redundant, so its removal lost a criterion."""
        expression = self._collapsed()
        record = expression[RESTATED_RULE_COLLAPSE_KEY][0]
        record["expression"]["Groups"][0]["CriteriaList"][0]["StartWindow"]["Start"]["Days"] = 90
        violations = restated_rule_collapse_violations(expression)
        assert len(violations) == 1, violations
        assert "'Use of'" in violations[0] and "does not make it redundant" in violations[0]

    def test_should_fail_when_the_recorded_reason_is_not_the_relation_found(self):
        expression = self._collapsed()
        expression[RESTATED_RULE_COLLAPSE_KEY][1]["reason"] = IDENTICAL_REASON
        violations = restated_rule_collapse_violations(expression)
        assert len(violations) == 1, violations
        assert "'implied'" in violations[0] and IDENTICAL_REASON in violations[0]

    def test_should_fail_when_the_reason_is_unknown(self):
        expression = self._collapsed()
        expression[RESTATED_RULE_COLLAPSE_KEY][0]["reason"] = "restated-distinctness-duplicate"
        violations = restated_rule_collapse_violations(expression)
        assert any("unknown reason" in v for v in violations), violations

    def test_should_fail_when_the_named_survivor_is_not_in_the_file(self):
        expression = self._collapsed()
        expression["InclusionRules"][0]["name"] = "renamed"
        violations = restated_rule_collapse_violations(expression)
        assert len(violations) == 2, violations
        assert all("does not carry" in v for v in violations), violations

    def test_should_fail_when_the_removed_rule_reads_a_concept_set_the_file_lacks(self):
        expression = self._collapsed()
        expression["ConceptSets"] = [cs for cs in expression["ConceptSets"] if cs["id"] != 8]
        violations = restated_rule_collapse_violations(expression)
        assert any("codeset 8" in v for v in violations), violations

    def test_should_fail_when_a_record_carries_no_expression(self):
        expression = self._collapsed()
        del expression[RESTATED_RULE_COLLAPSE_KEY][0]["expression"]
        violations = restated_rule_collapse_violations(expression)
        assert any("carries no expression" in v for v in violations), violations


class TestGateWiring:
    @staticmethod
    def _run(monkeypatch, tmp_path, capsys, delivered: dict[str, Any], stored: dict[str, Any]):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        import scripts.verify_circe_delivery as gate

        study = {
            "id": 9,
            "name": "Study 9",
            "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "entry"}, {"name": "Placebo"}],
            "eligibility": {"structuredExpression": stored},
        }
        for role in ("treatment", "comparator"):
            (tmp_path / f"carmelina_{role}.circe.json").write_text(json.dumps(delivered))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))
        rc = gate.main(["--dir", str(tmp_path), "--store", str(store), "--map", "carmelina=9"])
        return rc, capsys.readouterr().out

    def test_should_fail_the_delivery_when_a_rule_restates_another(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _carmelina_shape()
        rc, out = self._run(monkeypatch, tmp_path, capsys, cohort, deepcopy(cohort))
        assert rc == 1, out
        assert "redundant inclusion rules (2)" in out, out

    def test_should_pass_the_delivery_once_the_rules_are_collapsed(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _carmelina_shape()
        collapse_redundant_inclusion_rules(cohort)
        rc, out = self._run(monkeypatch, tmp_path, capsys, cohort, deepcopy(cohort))
        assert "redundant inclusion rules" not in out and "restated rule collapse" not in out, out
        assert rc == 0, out

    def test_should_fail_the_delivery_when_a_collapse_record_is_not_borne_out(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _carmelina_shape()
        collapse_redundant_inclusion_rules(cohort)
        cohort[RESTATED_RULE_COLLAPSE_KEY][0]["expression"]["Groups"][0]["CriteriaList"][0][
            "Occurrence"
        ] = {"Type": 2, "Count": 1}
        rc, out = self._run(monkeypatch, tmp_path, capsys, cohort, deepcopy(cohort))
        assert rc == 1, out
        assert "restated rule collapse (1)" in out, out
