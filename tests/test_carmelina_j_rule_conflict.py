"""Recorded CARMELINA rows: arm repairs must not invalidate a rule collapse."""

import json
from copy import deepcopy
from pathlib import Path

from scripts.verify_circe_delivery import (
    reconcile_dropped_rules,
    restated_rule_collapse_violations,
)
from src.services.restated_rules import rule_relation
from src.services.tte_service import TTEService, _rewrite_with_collapsed_rules
from src.utils.circe_lint import contradictory_absence_rules, rule_names

FIXTURE = Path(__file__).parent / "fixtures/carmelina_j_rule_conflict.json"


def recorded():
    return json.loads(FIXTURE.read_text())


def before_arm_repair():
    expression = recorded()
    # The store precedes the arm exception and the index-boundary shift.
    for cs in expression["ConceptSets"]:
        cs["expression"]["items"] = [
            item for item in cs["expression"]["items"] if not item["isExcluded"]
        ]
    for body in [
        expression["InclusionRules"][0]["expression"],
        expression["_restatedRuleCollapse"][0]["expression"],
    ]:

        def reset(group):
            for entry in group["CriteriaList"]:
                entry["StartWindow"]["End"] = {"Days": 0, "Coeff": 1}
            for child in group["Groups"]:
                reset(child)

        reset(body)
    return expression


def replay_recorded_exception(expression):
    excluded = recorded()["ConceptSets"][1]["expression"]["items"][-1]
    for cs in expression["ConceptSets"]:
        if cs["id"] == 4:
            cs["expression"]["items"].append(deepcopy(excluded))


def test_should_restore_dpp4_when_arm_repair_breaks_structural_implication():
    expression = before_arm_repair()
    record = expression["_restatedRuleCollapse"][0]
    assert (
        rule_relation(
            record["expression"],
            expression["InclusionRules"][0]["expression"],
            expression["ConceptSets"],
        )
        == "implied"
    )
    _rewrite_with_collapsed_rules(expression, replay_recorded_exception)
    emitted = TTEService._build_emittable_expression(lambda: expression)
    assert "DPP-4 inhibitors" in rule_names(emitted)
    assert emitted["_restatedRuleCollapse"] == []
    assert restated_rule_collapse_violations(emitted) == []
    assert contradictory_absence_rules(emitted) == []
    expected, violations = reconcile_dropped_rules(emitted, [record["survivorRule"]])
    assert violations == []
    assert sorted(expected) == sorted(rule_names(emitted))


def test_should_keep_collapse_when_rewrite_preserves_implication():
    expression = before_arm_repair()
    _rewrite_with_collapsed_rules(expression, lambda _: None)
    assert len(expression["_restatedRuleCollapse"]) == 1
    assert len(expression["InclusionRules"]) == 1


def test_should_reject_unimplied_collapse_when_recorded_baseline_is_checked():
    expression = recorded()
    assert len(restated_rule_collapse_violations(expression)) == 1


def test_should_remove_index_collision_when_real_dpp4_rule_is_emitted():
    expression = before_arm_repair()
    record = expression["_restatedRuleCollapse"].pop()
    expression["InclusionRules"].append(
        {"name": record["rule"], "expression": record["expression"]}
    )
    assert contradictory_absence_rules(expression)
    emitted = TTEService._build_emittable_expression(lambda: expression)
    assert contradictory_absence_rules(emitted) == []
    assert emitted["InclusionRules"][1]["expression"]["CriteriaList"][0]["StartWindow"]["End"] == {
        "Days": 1,
        "Coeff": -1,
    }


def test_should_reject_restoration_when_carried_rule_is_missing():
    expression = recorded()
    expression["_restoredRuleCollapses"] = expression.pop("_restatedRuleCollapse")
    _, violations = reconcile_dropped_rules(expression, rule_names(expression))
    assert violations


def vocabulary():
    from src.services.conceptset_closure import PrefetchedVocabulary

    data = recorded()["vocabulary"]
    return PrefetchedVocabulary(
        {int(k): v for k, v in data["concept_invalid_reason"].items()},
        {int(k): set(v) for k, v in data["ancestor_edges"].items()},
        {},
    )


def test_should_end_combination_product_washout_before_index_when_closures_overlap():
    from src.utils.circe_lint import (
        absence_overlap_findings,
        end_entry_colliding_washouts_before_index,
    )

    expression = recorded()
    lookup = vocabulary()
    assert len(absence_overlap_findings(expression, lookup)[1]) == 1
    end_entry_colliding_washouts_before_index(expression, lookup)
    assert absence_overlap_findings(expression, lookup) == ([], [])
    groups = expression["InclusionRules"][0]["expression"]["Groups"]
    assert groups[0]["CriteriaList"][0]["StartWindow"]["End"] == {"Days": 0, "Coeff": 1}
    assert groups[2]["CriteriaList"][0]["StartWindow"]["End"] == {"Days": 1, "Coeff": -1}


def test_should_preserve_future_window_when_combination_product_closures_overlap():
    from src.utils.circe_lint import end_entry_colliding_washouts_before_index

    expression = recorded()
    entry = expression["InclusionRules"][0]["expression"]["Groups"][2]["CriteriaList"][0]
    entry["StartWindow"]["End"] = {"Days": 30, "Coeff": 1}
    end_entry_colliding_washouts_before_index(expression, vocabulary())
    assert entry["StartWindow"]["End"] == {"Days": 30, "Coeff": 1}


def test_should_shift_class_overlap_when_arm_export_has_no_entity_exception(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from src.utils.circe_lint import absence_overlap_findings

    expression = recorded()
    lookup = vocabulary()
    monkeypatch.setattr(
        "src.services.conceptset_closure.PostgresVocabulary",
        lambda *args: nullcontext(SimpleNamespace(prefetch=lambda _: lookup)),
    )
    service = object.__new__(TTEService)
    service._repair_entry_excluded_by_own_rule(expression, {})
    assert absence_overlap_findings(expression, lookup) == ([], [])


def test_should_reject_empty_mapping_when_restoration_records_must_be_a_list():
    expression = recorded()
    expression["_restoredRuleCollapses"] = {}
    assert reconcile_dropped_rules(expression, rule_names(expression))[1]


def test_should_reject_restoration_when_record_has_no_expression():
    expression = recorded()
    expression["_restoredRuleCollapses"] = [{"rule": "DPP-4 inhibitors"}]
    assert reconcile_dropped_rules(expression, rule_names(expression))[1]


def test_should_preserve_window_when_overlap_is_subtracted_from_class():
    from src.utils.circe_lint import end_entry_colliding_washouts_before_index

    expression = recorded()
    sets = {cs["id"]: cs for cs in expression["ConceptSets"]}
    item = deepcopy(sets[1]["expression"]["items"][0])
    item["isExcluded"] = True
    sets[29]["expression"]["items"].append(item)
    end_entry_colliding_washouts_before_index(expression, vocabulary())
    end = expression["InclusionRules"][0]["expression"]["Groups"][2]["CriteriaList"][0][
        "StartWindow"
    ]["End"]
    assert end == {"Days": 0, "Coeff": 1}
