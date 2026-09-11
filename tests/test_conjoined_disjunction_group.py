"""A group whose protocol line states a disjunction, emitted as a conjunction.

The 2026-09-11 conversion audit (`output/site_gap/2026-09-14/conversion_audit.json`)
counts AND/OR inversion at 7 instances across 4 trials, its largest logical-defect
class. The clearest instance is LEADER store group `4a712697`::

    groupType:    "ALL"
    protocolLine: "Anti-diabetic drug naive or treated with one or more oral
                   anti-diabetic drugs (OADs) or treated with human NPH insulin or
                   long-acting insulin analogue or premixed insulin, ..."

which reaches the delivery as `InclusionRules[2]`, `Type: "ALL"` over three groups:
zero exposures to codeset 10 in [-365,-1], at least one to codeset 11 in [-365,0],
at least one to codeset 12 in [-365,0]. Codesets 10 and 11 hold the identical 71
concept ids, so the first two conjuncts can only both hold for a patient whose sole
exposure falls exactly on the index day. Three mutually exclusive enrolment
alternatives were conjoined.

Why the label's connective is not, on its own, the signal
--------------------------------------------------------
Swept across all six trials (82 groups): 16 groups declare `ALL` under a label whose
text states a disjunction, and 14 of those 16 are correct. An `ALL` over `ABSENCE`
members is the De Morgan encoding of "exclude if ANY of these" -- exactly what
`TTEService._effective_group_type` already produces on the `ANY` side -- so an
exclusion group reading "Stroke or TIA" belongs as `ALL` and must not move. The
connective alone has 2/16 precision against `groupType: "ALL"`.

What separates the two is the members' polarity. The full cross-tabulation::

    groupType x member polarity      groups   defects
    ALL x all-ABSENCE                    47         0     <- De Morgan, correct
    ALL x MIXED                           2         2     <- both audit-flagged
    ALL x all-PRESENCE                    2         0     <- "age AND >=1 of ..."
    ANY x all-PRESENCE                   23         -
    ANY x all-ABSENCE                     6         -
    ANY x MIXED                           2         -

and the two `ALL x all-PRESENCE` groups (LEADER `38a60fc2`, `1157e3c3`) are the
cardinality shape -- "Age >=60 y and >=1 of the following criteria" -- where the
conjunction is half right and a flat flip to `ANY` would admit a patient on age
alone. They are excluded by reading the cardinality construct, not by luck.

Where the correct reading lives
-------------------------------
In `protocolLine`, not in the group label's `description`. The store writes
`description` from the IR `name`, which a prior measurement this session found flips
between runs, and `protocolLine` from the IR `source_text`, which is copied verbatim
from the document. The difference is measurable here rather than inherited: LEADER
`38a60fc2`'s description reads "Age >= 60 years AND at least one of: Prior MI, Prior
stroke or TIA, Prior coronary, carotid or peripheral arterial revascularization",
whose two "or"s sit INSIDE member names and read as a group-level disjunction to any
text test; its protocolLine reads "No Prior cardiovascular disease group: Age >=60 y
and >=1 of the following criteria", which carries no bare disjunction at all. The
verbatim field separates the two cases and the paraphrase does not.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from src.utils.circe_lint import (
    aliased_concept_sets,
    conjoined_disjunction_rules,
    contradictory_presence_absence_criteria,
    states_flat_disjunction,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
BATCH = REPO / "output" / "site_gap" / "2026-09-14" / "DELIVERY"
STORE = REPO / "output" / "site_gap" / "2026-09-14" / "store" / "studies.json"

LEADER_LINE = (
    "Anti-diabetic drug naive or treated with one or more oral anti-diabetic drugs "
    "(OADs) or treated with human NPH insulin or long-acting insulin analogue or "
    "premixed insulin, alone or in combination with OAD(s)"
)
LEADER_CARDINALITY_LINE = (
    "No Prior cardiovascular disease group: Age ≥60 y and ≥1 of the following "
    "criteria:"
)


# ---------------------------------------------------------------------------
# Fixture builders -- the emitted shape, not the store shape
# ---------------------------------------------------------------------------

def _leaf(codeset_id: int, *, absent: bool) -> dict:
    return {
        "Criteria": {"DrugExposure": {"CodesetId": codeset_id}},
        "StartWindow": {
            "Start": {"Days": 365, "Coeff": -1},
            "End": {"Days": 0, "Coeff": 1},
        },
        "Occurrence": {"Type": 0, "Count": 0} if absent else {"Type": 2, "Count": 1},
    }


def _group(codeset_id: int, *, absent: bool) -> dict:
    return {
        "Type": "ALL",
        "CriteriaList": [_leaf(codeset_id, absent=absent)],
        "DemographicCriteriaList": [],
        "Groups": [],
    }


def _expression(group_type: str, polarities: list[bool], *, name: str = "R") -> dict:
    return {
        "ConceptSets": [],
        "InclusionRules": [
            {
                "name": name,
                "expression": {
                    "Type": group_type,
                    "CriteriaList": [],
                    "DemographicCriteriaList": [],
                    "Groups": [
                        _group(10 + i, absent=absent)
                        for i, absent in enumerate(polarities)
                    ],
                },
            }
        ],
    }


def _study(line: str, codeset_ids: list[int], *, group_id: str = "g1") -> dict:
    criteria = [
        {
            "id": 1,
            "description": "group label",
            "protocolLine": line,
            "logicType": "PRESENCE",
            "conceptSetId": None,
            "groupId": group_id,
            "groupType": "ALL",
            "isGroupLabel": True,
        }
    ]
    criteria += [
        {
            "id": 2 + i,
            "description": f"member {i}",
            "protocolLine": line,
            "logicType": "PRESENCE",
            "conceptSetId": codeset_id,
            "groupId": group_id,
            "groupType": "ALL",
            "isGroupLabel": False,
        }
        for i, codeset_id in enumerate(codeset_ids)
    ]
    return {"eligibility": {"inclusionCriteria": criteria, "exclusionCriteria": []}}


# ---------------------------------------------------------------------------


class TestStatesFlatDisjunction:
    """The text predicate on its own. One home, read by the lint and by the fix."""

    def test_should_report_a_disjunction_when_alternatives_are_joined_by_or(self):
        assert states_flat_disjunction(LEADER_LINE) is True

    def test_should_report_a_disjunction_when_the_line_uses_and_slash_or(self):
        assert states_flat_disjunction("Previous PCI and/or CABG") is True

    def test_should_report_a_disjunction_when_the_line_uses_either(self):
        assert states_flat_disjunction("defined by either ALT, AST") is True

    def test_should_not_report_a_disjunction_when_the_line_has_no_connective(self):
        assert states_flat_disjunction("Acute decompensation of glycemic control") is False

    def test_should_not_report_a_disjunction_when_the_line_is_empty(self):
        assert states_flat_disjunction("") is False
        assert states_flat_disjunction(None) is False

    def test_should_not_report_a_disjunction_when_the_line_states_a_cardinality(self):
        """LEADER 38a60fc2/1157e3c3: "Age >=60 y and >=1 of the following criteria".
        The conjunction is half right -- the age bound IS conjoined -- and a flat flip
        to ANY would admit a patient on age alone. A nested Group with a Count is what
        this shape needs, so the check declines it rather than half-fixing it."""
        assert states_flat_disjunction(LEADER_CARDINALITY_LINE) is False
        assert states_flat_disjunction("At least two of the following CV risk factors") is False
        assert states_flat_disjunction("One of the following: (a) age, (b) previous MI") is False

    def test_should_not_read_a_quantity_of_things_as_a_list_cardinality(self):
        """"one or more oral anti-diabetic drugs" counts DRUGS, not group members.
        A cardinality guard that matches the bare phrase silences LEADER's own line,
        which is the defect this check exists for."""
        assert states_flat_disjunction(LEADER_LINE) is True
        assert states_flat_disjunction(
            "treated with one or more oral anti-diabetic drugs or with insulin"
        ) is True


class TestConjoinedDisjunctionRules:
    """The gate check, over inline fixtures."""

    def test_should_fire_when_an_all_group_over_mixed_polarity_states_a_disjunction(self):
        findings = conjoined_disjunction_rules(
            _expression("ALL", [True, False, False]),
            _study(LEADER_LINE, [10, 11, 12]),
        )
        assert len(findings) == 1, findings
        assert "InclusionRules[0]" in findings[0]

    def test_should_stay_silent_on_an_all_group_whose_members_are_every_one_absent(self):
        """De Morgan. "Stroke or TIA" excluded means absent from the UNION, which is
        an ALL over two absences -- correct, and what `_effective_group_type` already
        produces on the ANY side. Flipping it would invert a working exclusion."""
        findings = conjoined_disjunction_rules(
            _expression("ALL", [True, True]),
            _study("Stroke or TIA <= 3 months prior to informed consent", [10, 11]),
        )
        assert findings == []

    def test_should_stay_silent_when_the_emitted_type_is_any(self):
        findings = conjoined_disjunction_rules(
            _expression("ANY", [True, False]), _study(LEADER_LINE, [10, 11])
        )
        assert findings == []

    def test_should_stay_silent_when_the_line_states_a_cardinality(self):
        findings = conjoined_disjunction_rules(
            _expression("ALL", [False, False]),
            _study(LEADER_CARDINALITY_LINE, [10, 11]),
        )
        assert findings == []

    def test_should_stay_silent_on_a_single_group_rule(self):
        """One group is not a combination; there is no connective to get wrong."""
        findings = conjoined_disjunction_rules(
            _expression("ALL", [False]), _study(LEADER_LINE, [10])
        )
        assert findings == []

    def test_should_stay_silent_when_no_store_group_can_be_joined(self):
        """No protocol line is reachable, so nothing is established. Reporting here
        would be an unobserved claim about a line the file does not carry."""
        findings = conjoined_disjunction_rules(
            _expression("ALL", [True, False]), _study(LEADER_LINE, [90, 91])
        )
        assert findings == []

    def test_should_stay_silent_when_the_group_carries_no_protocol_line(self):
        findings = conjoined_disjunction_rules(
            _expression("ALL", [True, False]), _study("", [10, 11])
        )
        assert findings == []


@pytest.mark.skipif(
    not BATCH.is_dir() or not STORE.is_file(),
    reason=f"delivered batch not present: {BATCH}",
)
class TestAgainstTheDeliveredBatch:
    """A green self-test over fixtures this file wrote itself proves nothing about the
    corpus the check was written for -- `docs/mistakes.md`, and why this class exists."""

    @staticmethod
    def _store() -> dict:
        studies = json.loads(STORE.read_text())["studies"]
        return {s["id"]: s for s in studies}

    _SLUG_TO_ID = {
        "carmelina": 9, "empa-reg": 8, "carolina": 10,
        "aristotle": 3, "plato": 2, "leader": 1,
    }

    def _findings_by_file(self) -> dict[str, list[str]]:
        by_id = self._store()
        out: dict[str, list[str]] = {}
        for path in sorted(BATCH.glob("*.circe.json")):
            stem = path.stem.replace(".circe", "")
            slug = stem.rsplit("_", 1)[0]
            out[stem] = conjoined_disjunction_rules(
                json.loads(path.read_text()), by_id[self._SLUG_TO_ID[slug]]
            )
        return out

    def test_should_fire_on_leader_rule_2_in_both_arms(self):
        by_file = self._findings_by_file()
        for arm in ("leader_treatment", "leader_comparator"):
            findings = by_file[arm]
            assert len(findings) == 1, findings
            assert "InclusionRules[2]" in findings[0], findings
            assert "4a712697" in findings[0], findings

    def test_should_stay_silent_on_the_other_ten_delivered_files(self):
        by_file = self._findings_by_file()
        quiet = {k: v for k, v in by_file.items() if not k.startswith("leader_")}
        assert len(quiet) == 10, sorted(quiet)
        assert all(v == [] for v in quiet.values()), quiet

    def test_should_leave_every_all_absence_group_in_the_corpus_alone(self):
        """The constraint that decides whether the check is safe to ship. 181 emitted
        `Type: ALL` rules across the twelve files carry nothing but absences, many of
        them under a protocol line that states "or"; every one must stay silent, or
        the fix built on this predicate would invert a working exclusion."""
        by_id = self._store()
        all_absence_rules = 0
        for path in sorted(BATCH.glob("*.circe.json")):
            stem = path.stem.replace(".circe", "")
            slug = stem.rsplit("_", 1)[0]
            expression = json.loads(path.read_text())
            findings = conjoined_disjunction_rules(
                expression, by_id[self._SLUG_TO_ID[slug]]
            )
            for index, rule in enumerate(expression["InclusionRules"]):
                body = rule["expression"]
                if (body.get("Type") or "").upper() != "ALL":
                    continue
                occurrences = _occurrences(body)
                if not occurrences or not all(o == (0, 0) for o in occurrences):
                    continue
                all_absence_rules += 1
                assert not any(f"InclusionRules[{index}]" in f for f in findings), (
                    stem, index, findings
                )
        assert all_absence_rules == 181, all_absence_rules

    def test_the_polarity_guard_is_what_holds_the_absence_rules_silent(self):
        """A silence nobody can explain is a silence nobody can trust.

        Six emitted `Type: ALL` rules in `leader_treatment` are all-absence AND sit
        under a store line that states a flat disjunction -- "Acute coronary **or**
        cerebrovascular event", "solid organ transplant **or** awaiting solid organ
        transplant", and four more. Every one is correct, and the check is silent on
        every one. Turn a single `Occurrence` from absent to present on the first of
        them and the check fires on exactly that rule and no other, which is what
        separates "the polarity guard is holding this back" from "the connective was
        never read at all"."""
        expression = json.loads((BATCH / "leader_treatment.circe.json").read_text())
        study = self._store()[1]
        before = conjoined_disjunction_rules(expression, study)
        assert len(before) == 1, before

        mutated = copy.deepcopy(expression)
        rule = mutated["InclusionRules"][16]
        assert rule["expression"]["Type"] == "ALL"
        assert len(rule["expression"]["Groups"]) == 2
        first = rule["expression"]["Groups"][0]["CriteriaList"][0]
        assert first["Occurrence"] == {"Type": 0, "Count": 0}
        first["Occurrence"] = {"Type": 2, "Count": 1}

        after = conjoined_disjunction_rules(mutated, study)
        new = [f for f in after if f not in before]
        assert len(new) == 1, after
        assert "InclusionRules[16]" in new[0], new
        assert "Acute coronary or cerebrovascular event" in new[0], new

    def test_flipping_leader_rule_2_to_any_makes_it_satisfiable(self):
        """The direct answer to "does rule 2 become satisfiable", read by an
        INDEPENDENT check rather than by the one added here.

        `_conjoined_entries` does not descend into `ANY`, so after the flip the
        codeset-10 / codeset-11 pair is no longer a conjunction and
        `contradictory_presence_absence_criteria` stops reporting it. A patient with
        zero OAD exposures now satisfies the rule through its first alternative,
        which is what the protocol line asks for.

        All FOUR findings go, not one, and the reason is worth stating rather than
        glossing: every presence the check pairs against lives in rule 2, so the two
        `InclusionRules[24]` findings -- the separate dropped-negation defect, where
        codesets 54 and 56 named "insulin other than X" hold the identical 26 ids as
        codeset 12 -- stop being PROVABLE contradictions once rule 2's presences stop
        being mandatory. The negation defect itself is untouched by the flip, and
        `aliased_concept_sets` still reports it. A reader who took the empty list as
        "rule 24 is fixed" would be reading this backwards."""
        expression = json.loads((BATCH / "leader_treatment.circe.json").read_text())
        before = contradictory_presence_absence_criteria(expression)
        internal = [f for f in before if "codeset 10" in f and "codeset 11" in f]
        assert len(internal) == 1, before
        assert len(before) == 4, before

        flipped = copy.deepcopy(expression)
        flipped["InclusionRules"][2]["expression"]["Type"] = "ANY"

        assert contradictory_presence_absence_criteria(flipped) == []
        assert len(aliased_concept_sets(flipped)) == 1, "the negation defect remains"


def _occurrences(node: dict) -> list[tuple]:
    found = [
        (
            (c.get("Occurrence") or {}).get("Type"),
            (c.get("Occurrence") or {}).get("Count"),
        )
        for c in node.get("CriteriaList") or []
    ]
    for group in node.get("Groups") or []:
        found.extend(_occurrences(group))
    return found


class TestEffectiveGroupTypeWidensAConjoinedDisjunction:
    """The fix, at the one place that decides what `Type` a group is emitted with.

    `_effective_group_type` already narrows a declared `ANY` to `ALL` for an
    all-ABSENCE group (SPEC-INFRA-003 REQ-004, `tests/test_infra_003_absence_group_
    semantics.py`). This is the symmetric correction on the other side, and it is
    subordinate to that one: the all-ABSENCE guard is checked FIRST, so no group the
    De Morgan rule owns can be reached by this one.

    It is applied here rather than in `agents/agent1/parser.py` because the wrong
    value is already in the store for all six delivered trials, and the parser runs
    only at extraction: a repair there cannot reach a study that has already been
    extracted, and reproducing LEADER through it would need an LLM call. This
    function runs on every build from the store, so it reaches both.
    """

    @staticmethod
    def _members(line: str, logic_types: list[str]) -> list[dict]:
        return [
            {"logicType": lt, "protocolLine": line, "description": f"m{i}"}
            for i, lt in enumerate(logic_types)
        ]

    def test_should_widen_to_any_when_an_all_group_over_mixed_polarity_says_or(self):
        from src.services.tte_service import _effective_group_type

        members = self._members(LEADER_LINE, ["ABSENCE", "PRESENCE", "PRESENCE"])
        assert _effective_group_type("ALL", members) == "ANY"

    def test_should_keep_all_when_every_member_is_absence_even_under_an_or_line(self):
        from src.services.tte_service import _effective_group_type

        members = self._members("Stroke or TIA <= 3 months", ["ABSENCE", "ABSENCE"])
        assert _effective_group_type("ALL", members) == "ALL"

    def test_should_keep_all_when_the_line_states_a_cardinality(self):
        from src.services.tte_service import _effective_group_type

        members = self._members(LEADER_CARDINALITY_LINE, ["PRESENCE", "PRESENCE"])
        assert _effective_group_type("ALL", members) == "ALL"

    def test_should_keep_all_when_members_carry_different_protocol_lines(self):
        """No single line covers the group, so no disjunction between the members was
        stated anywhere. An unestablished group keeps the behavior it already had."""
        from src.services.tte_service import _effective_group_type

        members = [
            {"logicType": "PRESENCE", "protocolLine": "Prior stroke or TIA"},
            {"logicType": "PRESENCE", "protocolLine": "Chronic renal failure"},
        ]
        assert _effective_group_type("ALL", members) == "ALL"

    def test_should_keep_all_when_only_one_member_survived_mapping(self):
        from src.services.tte_service import _effective_group_type

        members = self._members(LEADER_LINE, ["PRESENCE"])
        assert _effective_group_type("ALL", members) == "ALL"

    def test_should_keep_all_when_no_protocol_line_was_recorded(self):
        from src.services.tte_service import _effective_group_type

        members = [{"logicType": "PRESENCE"}, {"logicType": "ABSENCE"}]
        assert _effective_group_type("ALL", members) == "ALL"

    @pytest.mark.skipif(not STORE.is_file(), reason=f"store not present: {STORE}")
    def test_should_widen_the_real_leader_group_from_the_delivered_store(self):
        """The corpus case, read out of the store rather than retyped into a fixture."""
        studies = {s["id"]: s for s in json.loads(STORE.read_text())["studies"]}
        criteria = studies[1]["eligibility"]["inclusionCriteria"]
        group = [
            c for c in criteria
            if (c.get("groupId") or "").startswith("4a712697")
            and not c.get("isGroupLabel")
        ]
        assert len(group) == 3, group
        assert {c["logicType"] for c in group} == {"ABSENCE", "PRESENCE"}

        from src.services.tte_service import _effective_group_type

        assert group[0]["groupType"] == "ALL"
        assert _effective_group_type(group[0]["groupType"], group) == "ANY"


class TestTheDeliveryGateRunsTheCheck:
    """A lint nobody calls is indistinguishable from a lint that returns nothing.

    The pattern is `tests/test_unfiltered_measurement_absence_lint.py`: drive
    `verify_circe_delivery.main` over a two-file tmp delivery and read its exit code
    and its reason line, so the wiring is asserted rather than assumed.
    """

    def test_should_fail_the_delivery_and_name_the_rule(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        core = _expression("ALL", [True, False], name="naive or treated")
        core["ConceptSets"] = [
            {
                "id": codeset_id,
                "name": name,
                "expression": {
                    "items": [
                        {
                            "concept": {
                                "CONCEPT_ID": concept_id,
                                "CONCEPT_NAME": name,
                                "DOMAIN_ID": "Drug",
                                "VOCABULARY_ID": "RxNorm",
                                "CONCEPT_CLASS_ID": "Ingredient",
                                "CONCEPT_CODE": str(concept_id),
                            }
                        }
                    ]
                },
            }
            for codeset_id, concept_id, name in ((10, 11, "oral anti-diabetic drugs"),
                                                 (11, 12, "human NPH insulin"))
        ]
        study = _study(LEADER_LINE, [10, 11])
        study.update(
            id=1,
            name="Study 1",
            comparisonMode="target_minus_treatment",
            treatmentArms=[{"name": "liraglutide"}, {"name": "placebo"}],
        )
        study["eligibility"]["structuredExpression"] = json.loads(json.dumps(core))

        for role in ("treatment", "comparator"):
            (tmp_path / f"leader_{role}.circe.json").write_text(json.dumps(core))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "leader=1"])
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "conjoined disjunction (1)" in out, out
        assert "InclusionRules[0]" in out, out
