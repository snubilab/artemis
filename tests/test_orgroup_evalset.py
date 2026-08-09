"""Contract tests for the gold-derived OR-GROUP decision eval set.

The eval set is the answer key for one predicate,
``criteria_dedup.restates_or_group_alternative``, and for the LLM judge that
competes with it. A wrong label here is worse than no table: it moves the
measured number while the artifact still looks complete.

Every failure below already produced a wrong label in the first attempt, so each
is pinned rather than described:

* Labelling ``AT_LEAST/N`` (N >= 2) as a disjunction. CAROLINA's "at least two of
  the following CV risk factors" entails no individual member, so a criterion
  restating one member would be marked safe to delete.
* Treating ``AT_MOST`` as a disjunction. Gold has none, so it is dead code that
  would INVERT the label the day it went live.
* Reading a ONE-member ``ANY`` as a group. PLATO's rule 3 is exactly that, over
  an exclusion criterion.
* Dropping gold's numeric/temporal constraints, which presents "Systolic blood
  pressure (SBP)" where gold means "> 140".
* Linking across polarity, which paired an exclusion criterion to an inclusion
  alternative.
* Retyping the wire format, which makes ``or_group_alternatives`` return ``[]``,
  every probe answer False, and every arm score identically.
* Unstable ids, which make a table change indistinguishable from an arm change.

DB-free: every test builds from synthetic gold/generated dicts against a stubbed
vocabulary. Nothing here needs Postgres or a PDF.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_orgroup_decision_evalset import (
    DISTINCT,
    EXCLUSION,
    INCLUSION,
    LINK_JACCARD,
    MIN_GROUP_ALTERNATIVES,
    OUTPUT_PATH,
    RESTATEMENT,
    build,
    collect_gold_groups,
    entails_every_member,
    generated_candidates,
    gold_placements,
    is_disjunctive,
    link_by_closure,
    occurrence_polarity,
    render_leaf,
    render_node_inline,
    Resolved,
)
from src.agents.agent1.criteria_dedup import (
    OR_GROUP_JOIN,
    OR_GROUP_PREFIX,
    OR_GROUP_SEP,
    or_group_alternatives,
    restates_or_group_alternative,
)
from src.services.conceptset_closure import PrefetchedVocabulary


# --------------------------------------------------------------------------- #
# fixtures: synthetic CIRCE
# --------------------------------------------------------------------------- #
def _criterion(codeset_id: int, *, exclude: bool = False, payload: dict | None = None) -> dict:
    """:param codeset_id: concept set id. :param exclude: emit an exclusion occurrence.
    :param payload: extra domain-payload keys (ValueAsNumber, EraLength, ...).
    :returns: a minimal CIRCE criteria wrapper."""
    body = {"CodesetId": codeset_id}
    body.update(payload or {})
    return {
        "Criteria": {"ConditionOccurrence": body},
        "Occurrence": {"Type": 0, "Count": 0} if exclude else {"Type": 2, "Count": 1},
    }


def _group(node_type: str, criteria: list[dict], *, count: int | None = None,
           groups: list[dict] | None = None, demographics: list[dict] | None = None) -> dict:
    """:returns: a CIRCE group node."""
    node = {
        "Type": node_type,
        "CriteriaList": criteria,
        "DemographicCriteriaList": demographics or [],
        "Groups": groups or [],
    }
    if count is not None:
        node["Count"] = count
    return node


def _concept_sets(spec: dict[int, str]) -> list[dict]:
    """:param spec: id -> bare name. :returns: TROY-shaped ConceptSets."""
    return [{"id": i, "name": f"[TROY condition] {n}"} for i, n in sorted(spec.items())]


def _cohort(concept_sets: list[dict], rules: list[dict]) -> dict:
    """:returns: a CIRCE cohort definition."""
    return {"ConceptSets": concept_sets, "InclusionRules": rules}


def _rule(name: str, expression: dict) -> dict:
    """:returns: one InclusionRule."""
    return {"name": name, "expression": expression}


def _vocab(concept_ids: dict[int, list[int]]) -> PrefetchedVocabulary:
    """Stubbed vocabulary where every listed id exists and is valid.

    :param concept_ids: unused mapping kept for call-site readability; only the
        union of ids is needed by the closure resolver.
    :returns: a :class:`PrefetchedVocabulary`.
    """
    everything = {cid: None for ids in concept_ids.values() for cid in ids}
    return PrefetchedVocabulary(concept_invalid_reason=everything)


def _expression_items(ids: list[int]) -> dict:
    """:param ids: concept ids. :returns: a Circe concept-set expression."""
    return {"items": [{"concept": {"CONCEPT_ID": i}} for i in ids]}


# --------------------------------------------------------------------------- #
# disjunction detection
# --------------------------------------------------------------------------- #
def test_should_treat_any_and_at_least_one_as_disjunctive():
    """The two spellings gold actually uses for "one of these is enough"."""
    assert is_disjunctive(_group("ANY", [_criterion(1), _criterion(2)])) is True
    assert is_disjunctive(_group("AT_LEAST", [_criterion(1), _criterion(2)], count=1)) is True
    assert is_disjunctive(_group("AT_LEAST", [_criterion(1), _criterion(2)])) is True


def test_should_not_treat_at_least_two_as_disjunctive():
    """CAROLINA's "at least two of the following CV risk factors" is AT_LEAST/2.

    A 2-of-6 group entails no individual member, so a criterion restating one
    member is NOT implied by it. Reading it as a disjunction labels that criterion
    a restatement and marks a real requirement safe to delete.
    """
    node = _group("AT_LEAST", [_criterion(i) for i in (1, 2, 3)], count=2)
    assert is_disjunctive(node) is False

    gold = _cohort(
        _concept_sets({1: "a", 2: "b", 3: "c"}),
        [_rule("at least two CV risk factors", node)],
    )
    groups, census = collect_gold_groups(gold, "T")
    assert groups == []
    assert census["at_least_n"] == 1

    placements = gold_placements(gold, "T", [])
    assert [p.kind for p in placements[1]] == ["at_least_n_member"]
    assert placements[1][0].label is None


def test_should_never_treat_at_most_as_disjunctive():
    """AT_MOST is an upper bound; its members are not interchangeable.

    Gold contains zero AT_MOST nodes, so admitting it buys nothing and would
    invert the label if one ever appeared.
    """
    assert is_disjunctive(_group("AT_MOST", [_criterion(1), _criterion(2)], count=1)) is False
    gold = _cohort(_concept_sets({1: "a", 2: "b"}),
                   [_rule("no more than one", _group("AT_MOST", [_criterion(1), _criterion(2)],
                                                     count=1))])
    groups, _ = collect_gold_groups(gold, "T")
    assert groups == []


def test_should_treat_single_member_any_as_mandatory_not_disjunctive():
    """PLATO rule 3 ("a need for oral anticoagulation therapy") is ANY over one criterion.

    One member must hold either way, so it is a standalone AND-ed criterion. Read
    as a group it made its own member look like an offered alternative.
    """
    node = _group("ANY", [_criterion(1, exclude=True)])
    assert entails_every_member(node) is True
    gold = _cohort(_concept_sets({1: "anticoagulants"}),
                   [_rule("a need for oral anticoagulation therapy", node)])
    groups, census = collect_gold_groups(gold, "PLATO")
    assert groups == []
    assert census["singleton_or_empty"] == 1
    placements = gold_placements(gold, "PLATO", [])
    assert placements[1][0].kind == "standalone_all_rule"
    assert placements[1][0].label == DISTINCT


def test_should_not_emit_a_parent_group_that_merely_rewraps_its_child():
    """The child already covers the decision.

    The first attempt emitted a group at every nesting level and counted the same
    criteria up to three times.
    """
    child = _group("ANY", [_criterion(1), _criterion(2)])
    parent = _group("ANY", [], groups=[child])
    gold = _cohort(_concept_sets({1: "a", 2: "b"}), [_rule("one of", parent)])
    groups, census = collect_gold_groups(gold, "T")
    assert [g.alternatives for g in groups] == [("a", "b")]
    assert census["singleton_or_empty"] == 1


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def test_should_render_gold_numeric_constraint_into_the_alternative_text():
    """A bare concept name with a dropped threshold is a different criterion."""
    names = {1: "[TROY lab] Systolic blood pressure (SBP)"}
    criterion = _criterion(1, payload={"ValueAsNumber": {"Value": 140, "Op": "gt"}})
    assert render_leaf(criterion, names) == "Systolic blood pressure (SBP) > 140"


@pytest.mark.parametrize("payload,expected", [
    ({"ValueAsNumber": {"Value": 6.5, "Extent": 10, "Op": "!bt"}},
     "HbA1c not between 6.5 and 10"),
    ({"RangeHighRatio": {"Value": 2, "Op": "gte"}},
     "HbA1c >= 2x upper limit of normal"),
    ({"EraLength": {"Value": 7, "Op": "gt"}},
     "HbA1c era length > 7 days"),
    ({"ValueAsNumber": {"Value": 135, "Op": "gte"},
      "Unit": [{"CONCEPT_CODE": "mg/dL"}]},
     "HbA1c >= 135 mg/dL"),
])
def test_should_render_every_constraint_shape_gold_uses(payload, expected):
    """30 of 62 leaf alternatives carry one of these; the first attempt dropped all."""
    assert render_leaf(_criterion(1, payload=payload), {1: "[TROY lab] HbA1c"}) == expected


def test_should_render_an_excluded_leaf_with_its_polarity():
    """An alternative that gold negates must not read as its positive form."""
    text = render_leaf(_criterion(1, exclude=True), {1: "[TROY condition] heart failure"})
    assert text == "absence of heart failure"


def test_should_parenthesise_a_nested_composite_alternative():
    """``ALL(Age >= 60, AT_LEAST1(A, B))`` is not "Age >= 60 and A or B".

    The unparenthesised flattening the first attempt produced asserts different
    logic than gold wrote.
    """
    nested = _group("ALL", [], demographics=[{"Age": {"Value": 60, "Op": "gte"}}],
                    groups=[_group("AT_LEAST", [_criterion(1), _criterion(2)], count=1)])
    assert render_node_inline(nested, {1: "[TROY condition] a", 2: "[TROY condition] b"}) == (
        "(Age >= 60 and (a or b))"
    )


def test_should_render_at_least_n_as_a_counted_composite_not_a_disjunction():
    """When AT_LEAST/N appears as an alternative, its logic is stated honestly."""
    node = _group("AT_LEAST", [_criterion(1), _criterion(2), _criterion(3)], count=2)
    names = {1: "[TROY condition] a", 2: "[TROY condition] b", 3: "[TROY condition] c"}
    assert render_node_inline(node, names) == "(at least 2 of: a, b, c)"


# --------------------------------------------------------------------------- #
# wire format
# --------------------------------------------------------------------------- #
def test_should_round_trip_the_wire_format_through_the_module_parser():
    """A retyped separator makes every probe see an empty group and answer False."""
    gold = _cohort(_concept_sets({1: "a", 2: "b", 3: "c"}),
                   [_rule("one or more of", _group("ANY", [_criterion(i) for i in (1, 2, 3)]))])
    groups, _ = collect_gold_groups(gold, "T")
    wire = groups[0].wire
    assert wire.startswith(OR_GROUP_PREFIX)
    assert OR_GROUP_JOIN in wire
    assert OR_GROUP_SEP.strip() in wire
    assert or_group_alternatives(wire) == list(groups[0].alternatives) == ["a", "b", "c"]


def test_should_drive_the_real_predicate_when_probed_with_the_rendered_item():
    """Without this, every other assertion can hold while the table measures nothing."""
    gold = _cohort(_concept_sets({1: "diabetes mellitus", 2: "hypertension"}),
                   [_rule("one or more of", _group("AT_LEAST", [_criterion(1), _criterion(2)],
                                                   count=1))])
    groups, _ = collect_gold_groups(gold, "T")
    item = groups[0].wire
    assert restates_or_group_alternative("diabetes mellitus", [item]) is True
    assert restates_or_group_alternative("severe hepatic impairment", [item]) is False


# --------------------------------------------------------------------------- #
# polarity
# --------------------------------------------------------------------------- #
def test_should_read_polarity_from_the_circe_occurrence_node():
    """Circe spells an exclusion as "exactly zero occurrences"."""
    assert occurrence_polarity(_criterion(1)) == INCLUSION
    assert occurrence_polarity(_criterion(1, exclude=True)) == EXCLUSION


def test_should_refuse_a_link_that_crosses_polarity():
    """An exclusion criterion must never be labelled against an inclusion alternative.

    This is the failure that produced "Congestive heart failure of NYHA class
    III or IV" -> "No congestive heart failure ..." at difflib 0.970.
    """
    ids = list(range(100, 110))
    gold = _cohort(
        [{"id": 1, "name": "[TROY condition] Type 2 diabetes mellitus",
          "expression": _expression_items(ids)}],
        [_rule("one or more of", _group("ANY", [_criterion(1), _criterion(2)]))],
    )
    gold["ConceptSets"].append(
        {"id": 2, "name": "[TROY condition] other", "expression": _expression_items([999])})
    generated = _cohort(
        [{"id": 1, "name": "Type 1 diabetes mellitus", "expression": _expression_items(ids)}],
        [_rule("Type 1 diabetes mellitus", _group("ALL", [_criterion(1, exclude=True)]))],
    )
    lookup = _vocab({"all": ids + [999]})
    artifact = build([("T", Path("gold.json"), Path("gen.json"), gold, generated)], lookup)

    assert artifact["rows"] == []
    reasons = [u["reason"] for u in artifact["unscorable"]]
    assert any("polarity crossing refused" in r for r in reasons), reasons


def test_should_record_the_bucket_of_every_scored_row():
    """A row without its bucket cannot be read for the cohort-widening direction."""
    artifact = _two_label_artifact()
    for row in artifact["rows"]:
        assert row["candidate_bucket"] in {INCLUSION, EXCLUSION}
        assert row["polarity_relation"] in {"same_bucket", "cross_bucket"}
        assert row["or_group_polarities"]


# --------------------------------------------------------------------------- #
# linking
# --------------------------------------------------------------------------- #
def test_should_refuse_a_link_below_the_jaccard_threshold():
    """No gold counterpart by meaning means no row, never a guessed label."""
    generated = Resolved(1, "x", {1, 2, 3, 4})
    gold = {9: Resolved(9, "[TROY] y", {4, 5, 6, 7})}
    link, reason = link_by_closure(generated, gold)
    assert link is None
    assert f"< {LINK_JACCARD}" in reason


def test_should_refuse_an_ambiguous_link_when_two_gold_sets_are_within_the_margin():
    """The closure does not decide which gold criterion the candidate restates."""
    generated = Resolved(1, "x", {1, 2, 3, 4})
    gold = {8: Resolved(8, "[TROY] a", {1, 2, 3, 4}), 9: Resolved(9, "[TROY] b", {1, 2, 3, 4})}
    link, reason = link_by_closure(generated, gold)
    assert link is None
    assert "ambiguous link" in reason


def test_should_link_by_closure_and_never_by_name():
    """Two sets with disjoint names but identical closures are the same criterion."""
    generated = Resolved(1, "intermittent claudication", set(range(20)))
    gold = {9: Resolved(9, "[TROY condition] Ankle brachial index less than 0.9",
                        set(range(20)))}
    link, reason = link_by_closure(generated, gold)
    assert reason == "linked"
    assert link is not None
    assert link.jaccard == 1.0


# --------------------------------------------------------------------------- #
# labels end to end
# --------------------------------------------------------------------------- #
def _two_label_artifact() -> dict:
    """A synthetic trial producing exactly one restatement row and one distinct row."""
    group_ids = list(range(100, 120))
    standalone_ids = list(range(200, 220))
    other_ids = list(range(300, 320))
    gold = _cohort(
        [
            {"id": 1, "name": "[TROY condition] prior stroke",
             "expression": _expression_items(group_ids)},
            {"id": 2, "name": "[TROY condition] diabetes mellitus",
             "expression": _expression_items(other_ids)},
            {"id": 3, "name": "[TROY condition] active endocarditis",
             "expression": _expression_items(standalone_ids)},
        ],
        [
            _rule("One or more of the following risk factor(s) for stroke",
                  _group("AT_LEAST", [_criterion(1), _criterion(2)], count=1)),
            _rule("Active infective endocarditis", _group("ALL", [_criterion(3)])),
        ],
    )
    generated = _cohort(
        [
            {"id": 7, "name": "Stroke, TIAs, and systemic embolism",
             "expression": _expression_items(group_ids)},
            {"id": 8, "name": "endocarditis", "expression": _expression_items(standalone_ids)},
        ],
        [
            _rule("Prior stroke, TIA or systemic embolus", _group("ALL", [_criterion(7)])),
            _rule("Active infective endocarditis", _group("ALL", [_criterion(8)])),
        ],
    )
    lookup = _vocab({"all": group_ids + standalone_ids + other_ids})
    return build([("T", Path("gold.json"), Path("gen.json"), gold, generated)], lookup)


def test_should_label_a_group_member_restatement_and_a_standalone_rule_distinct():
    """The two structural labels, read straight off the gold tree."""
    artifact = _two_label_artifact()
    by_candidate = {r["candidate"]: r for r in artifact["rows"]}
    assert by_candidate["Prior stroke, TIA or systemic embolus"]["label"] == RESTATEMENT
    assert by_candidate["Active infective endocarditis"]["label"] == DISTINCT


def test_should_name_the_alternative_a_restatement_row_restates():
    """A restatement row that cannot say WHICH alternative is unreviewable."""
    artifact = _two_label_artifact()
    row = next(r for r in artifact["rows"] if r["label"] == RESTATEMENT)
    assert row["restated_alternative"] == "prior stroke"
    assert row["restated_alternative"] in row["alternatives"]


def test_should_carry_the_link_evidence_on_every_row():
    """A label whose Jaccard and both set names are not on the row cannot be audited."""
    for row in _two_label_artifact()["rows"]:
        link = row["link"]
        assert link["jaccard"] >= LINK_JACCARD
        assert link["gold_concept_set"] and link["generated_concept_set"]
        assert "string" not in link["method"] or "no string similarity" in link["method"]


def test_should_never_label_an_unscorable_candidate():
    """A guessed label is worse than no row: it moves the number silently."""
    artifact = _two_label_artifact()
    for entry in artifact["unscorable"]:
        assert "label" not in entry
        assert entry["reason"]
    assert {row["label"] for row in artifact["rows"]} <= {RESTATEMENT, DISTINCT}


def test_should_report_n_and_the_always_distinct_floor():
    """No downstream reader may quote an arm's accuracy without the trivial baseline."""
    summary = _two_label_artifact()["summary"]
    assert summary["n_rows"] == sum(summary["label_balance"].values())
    assert summary["n_rows"] == summary["n_unique_trial_candidate"]
    floor = summary["trivial_baselines"]["always_distinct"]
    assert floor["n"] == summary["n_rows"]
    assert floor["accuracy"] == pytest.approx(
        summary["label_balance"][DISTINCT] / summary["n_rows"]
    )
    assert "candidate_bucket_only" in summary["trivial_baselines"]


# --------------------------------------------------------------------------- #
# generated candidates
# --------------------------------------------------------------------------- #
def test_should_take_candidate_text_from_the_rule_when_it_owns_one_concept_set():
    """The rule name carries the threshold; the concept set name usually does not."""
    generated = _cohort([{"id": 1, "name": "Glycated hemoglobin"}],
                        [_rule("HbA1c 7-10%", _group("ALL", [_criterion(1)]))])
    candidates, _ = generated_candidates(generated, "T")
    assert [(c.text, c.text_source) for c in candidates] == [
        ("HbA1c 7-10%", "generated_rule_name")
    ]


def test_should_fall_back_to_the_concept_set_name_inside_a_collapsed_group():
    """A multi-codeset rule is "A + B", not a flat criterion; the member name is."""
    generated = _cohort(
        [{"id": 1, "name": "Prior MI"}, {"id": 2, "name": "Prior stroke"}],
        [_rule("Prior MI + Prior stroke", _group("ANY", [_criterion(1), _criterion(2)]))],
    )
    candidates, _ = generated_candidates(generated, "T")
    assert sorted((c.text, c.text_source) for c in candidates) == [
        ("Prior MI", "generated_concept_set_name"),
        ("Prior stroke", "generated_concept_set_name"),
    ]


def test_should_refuse_a_concept_set_no_inclusion_rule_uses():
    """A PrimaryCriteria-only set is not a criterion decision."""
    generated = _cohort([{"id": 1, "name": "apixaban"}], [])
    candidates, refused = generated_candidates(generated, "T")
    assert candidates == []
    assert "no InclusionRule" in refused[0]["reason"]


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
def test_should_produce_identical_artifacts_when_built_twice():
    """Two builds of an unchanged tree must be diffable, byte for byte."""
    first, second = _two_label_artifact(), _two_label_artifact()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_should_produce_unique_sorted_ids_with_no_overlap_between_rows_and_unscorable():
    """A duplicate id silently collapses two decisions into one."""
    artifact = _two_label_artifact()
    ids = [row["id"] for row in artifact["rows"]]
    assert ids == sorted(set(ids))
    assert not set(ids) & {u["id"] for u in artifact["unscorable"]}


def test_should_carry_no_timestamp_in_the_artifact():
    """A stamped artifact is not byte-comparable across builds."""
    blob = json.dumps(_two_label_artifact())
    for banned in ("generated_at", "timestamp", "built_at", "created_at"):
        assert banned not in blob


# --------------------------------------------------------------------------- #
# the shipped artifact
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not Path(OUTPUT_PATH).exists(), reason="eval set not built yet")
def test_should_round_trip_every_shipped_row_through_the_module_parser():
    """Every shipped probe must present non-empty groups to the predicate."""
    artifact = json.loads(Path(OUTPUT_PATH).read_text())
    assert artifact["rows"], "the shipped eval set is empty"
    for row in artifact["rows"]:
        pooled: list[str] = []
        for item in row["or_group_items"]:
            parsed = or_group_alternatives(item)
            assert len(parsed) >= MIN_GROUP_ALTERNATIVES
            pooled.extend(parsed)
        assert pooled == row["alternatives"]
        assert row["label"] in {RESTATEMENT, DISTINCT}
        assert row["candidate"].strip()
        assert row["link"]["jaccard"] >= LINK_JACCARD


@pytest.mark.skipif(not Path(OUTPUT_PATH).exists(), reason="eval set not built yet")
def test_should_ship_no_row_whose_gold_placement_is_a_counted_or_composite_group():
    """Only the two deciding placements may carry a label."""
    artifact = json.loads(Path(OUTPUT_PATH).read_text())
    kinds = {row["gold_placement"]["kind"] for row in artifact["rows"]}
    assert kinds <= {"disjunctive_group_member", "standalone_all_rule"}
    for row in artifact["rows"]:
        placement = row["gold_placement"]
        if placement["kind"] == "disjunctive_group_member":
            assert placement["node_type"] == "ANY" or (
                placement["node_type"] == "AT_LEAST" and placement["node_count"] in (None, 1)
            )
