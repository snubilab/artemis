"""A rule that LOST its threshold looks exactly like one that never had a threshold.

Measured, verbatim, from `output/site_gap/2026-09-08/deliver_20260908/
carolina_treatment.circe.json` -- three sibling absence rules, all
`Occurrence {Type: 0, Count: 0}`:

    rule 30  ALT(36) AST(37) ALP(38)                          keys=['RangeHighRatio']
    rule 33  T4(49) T3(50) TSH(51)                            keys=[]
    rule 37  'Elevated ALT'(71) 'Elevated AST'(72)
             'Elevated Bilirubin'(73) 'Coagulopathy...INR'(74) keys=[]

Rule 30 is right: "3x ULN" survived as a `RangeHighRatio`. Rules 33 and 37 are the same
shape with the number gone, so rule 37 excludes any patient who has ever had an ALT, AST,
bilirubin or INR drawn -- routine panel labs, which in a T2DM cohort is effectively
everyone. The gate reported the file as "78 mapped, 0 unmapped, 32 skipped": the bare
members were counted as MAPPED and nothing anywhere flagged them.

`unreadable_value_filter_criteria` catches a filter PRESENT on a type that cannot read
it, and `domain_mismatched_criteria` catches a concept set the criterion's table cannot
join. Neither can catch a filter that is simply ABSENT, because absence is not a property
of the emitted criterion -- it is a disagreement between the criterion and what its own
NAME claims.

That makes half of this check a heuristic over English, and `docs/mistakes.md` records
exactly what happens to a detector validated on synthetic strings. So the vocabulary is
grounded in two real corpora, and this module runs it against both:

  * the 12 delivered files -- 136 Measurement criteria, 32 of them bare, 26 fire, and
    those 26 are exactly the known lost bounds;
  * the 18 hand-built TROY v1.1 files under `data/gold/` -- 85 Measurement criteria, 4
    of them bare, and all 4 fire on a defect nobody was looking for: ARISTOTLE's
    `Persistent, uncontrolled hypertension (systolic BP > 180 mm Hg, or diastolic BP >
    100 mm Hg)` emits `{CodesetId: 98}` and `{CodesetId: 99}` with no bound at all.

30 firings across two independent corpora, 30 true positives, 0 false. Rule 30 is the
control that makes that mean something: its name matches the vocabulary as loudly as any
of them ("ALT above 3x ULN"), and it does not fire, because the structural half of the
predicate sees the `RangeHighRatio` it carries.

Both corpora are gitignored, so those tests skip on a fresh checkout. The synthetic
shapes below reproduce the same three rules and do not, so the check keeps its teeth
either way.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

# The two private names below are imported deliberately. `_criterion_locations` is the
# walk the check itself uses, so re-implementing it here to count the corpus would let a
# hole in the walk hide from the very test that measures coverage; and
# `_BOUND_ASSERTION_RE` is what makes the rule-30 control an assertion about the
# VOCABULARY rather than about a string somebody guessed matched it.
from src.utils.circe_lint import (
    _BOUND_ASSERTION_RE,
    VALUE_CONDITION_ATTRIBUTES,
    _criterion_locations,
    asserted_bound_missing_criteria,
    unreadable_value_attributes,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
BATCH = REPO / "output" / "site_gap" / "2026-09-08" / "deliver_20260908"
GOLD = REPO / "data" / "gold"

#: The 26 lost bounds, as (file stem, codeset id). CAROLINA's thyroid panel (49-51),
#: glucose panel (66-68) and liver panel (71-74), and EMPA-REG's glucose panel (57-59),
#: on both arms of each.
EXPECTED_BATCH_FINDINGS = {
    (f"carolina_{arm}", codeset)
    for arm in ("treatment", "comparator")
    for codeset in (49, 50, 51, 66, 67, 68, 71, 72, 73, 74)
} | {
    (f"empa-reg_{arm}", codeset)
    for arm in ("treatment", "comparator")
    for codeset in (57, 58, 59)
}


def _measurement_rule(
    rule_name: str, codeset_id: int, *, value: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One absence InclusionRule over one Measurement codeset, in the emitted shape."""
    payload: dict[str, Any] = {"CodesetId": codeset_id}
    payload.update(value or {})
    return {
        "name": rule_name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {
                    "Criteria": {"Measurement": payload},
                    "StartWindow": {"Start": {"Days": 180, "Coeff": -1}, "End": {"Coeff": 1}},
                    "Occurrence": {"Type": 0, "Count": 0},
                }
            ],
        },
    }


def _expression(rules: list[dict[str, Any]], concept_sets: dict[int, str]) -> dict[str, Any]:
    return {
        "ConceptSets": [
            {"id": codeset_id, "name": name, "expression": {"items": []}}
            for codeset_id, name in concept_sets.items()
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": rules,
    }


class TestTheThreeRealCarolinaRulesReproducedSynthetically:
    """Rules 30, 33 and 37 as the file actually carries them. The one that kept its
    threshold must stay silent while its two siblings fire, or the check is measuring
    the rule name and nothing else."""

    def test_should_stay_silent_on_the_rule_whose_ratio_bound_survived(self):
        expression = _expression(
            [
                _measurement_rule(
                    "ALT above 3x ULN + AST above 3x ULN + Alkaline phosphatase above 3x ULN",
                    36,
                    value={"RangeHighRatio": {"Value": 3, "Op": "gt"}},
                )
            ],
            {36: "Alanine aminotransferase"},
        )
        assert asserted_bound_missing_criteria(expression) == []

    def test_should_confirm_that_silence_is_not_the_name_failing_to_match(self):
        """The control on the control. Rule 30's name asserts a bound as loudly as any
        of the 26; what keeps it silent is the `RangeHighRatio` it carries."""
        expression = _expression(
            [
                _measurement_rule(
                    "ALT above 3x ULN + AST above 3x ULN + Alkaline phosphatase above 3x ULN",
                    36,
                )
            ],
            {36: "Alanine aminotransferase"},
        )
        findings = asserted_bound_missing_criteria(expression)
        assert len(findings) == 1
        assert "ULN" in findings[0]

    def test_should_fire_on_the_thyroid_panel_from_the_rule_name_alone(self):
        """Rule 33. The concept-set names are bare analytes -- "Thyroxine (T4)" -- so a
        check reading only the concept set would miss all three."""
        expression = _expression(
            [
                _measurement_rule(
                    "Thyroxine (T4) level + Triiodothyronine (T3) level + "
                    "Thyroid Stimulating Hormone (TSH) level",
                    codeset,
                )
                for codeset in (49, 50, 51)
            ],
            {49: "Thyroxine (T4)", 50: "Triiodothyronine (T3)", 51: "Thyroid Stimulating Hormone"},
        )
        findings = asserted_bound_missing_criteria(expression)
        assert len(findings) == 3
        assert all("its rule name asserts one" in finding for finding in findings)

    def test_should_fire_on_the_liver_panel_from_the_concept_set_name(self):
        """Rule 37. Reading the concept-set name is load-bearing, not thoroughness: the
        rule name says only "Acute Liver Disease ... Impaired Hepatic Function" while
        the per-analyte assertion lives in the concept sets."""
        expression = _expression(
            [
                _measurement_rule("Acute Liver Disease + Impaired Hepatic Function", codeset)
                for codeset in (71, 72, 73, 74)
            ],
            {
                71: "Elevated Alanine aminotransferase (ALT)",
                72: "Elevated Aspartate aminotransferase (AST)",
                73: "Elevated Bilirubin",
                74: "Coagulopathy (e.g., elevated INR)",
            },
        )
        findings = asserted_bound_missing_criteria(expression)
        assert len(findings) == 4
        assert all("its concept-set name asserts one" in finding for finding in findings)


class TestWhatTheCheckDeliberatelyDoesNotJudge:
    @pytest.mark.parametrize("name", ["Asymptomatic cardiac ischemia", "ECG Ischemia"])
    def test_should_stay_silent_when_the_name_asserts_no_bound(self, name):
        """Three of the six bare criteria in the real batch. A Measurement occurrence
        with no bound is legitimate when nothing claims otherwise."""
        expression = _expression([_measurement_rule(name, 8)], {8: name})
        assert asserted_bound_missing_criteria(expression) == []

    def test_should_stay_silent_on_a_qualitative_assertion(self):
        """PLATO codeset 15. "Positive biomarker" asserts a verdict, not a NUMBER, and
        `ValueAsConcept` is how Circe carries that -- a different repair."""
        expression = _expression(
            [
                _measurement_rule(
                    "Persistent ST-segment + PCI planned + Peripheral artery disease "
                    "+ Positive biomarker",
                    15,
                )
            ],
            {15: "Positive biomarker"},
        )
        assert asserted_bound_missing_criteria(expression) == []

    @pytest.mark.parametrize(
        "concept_set_name",
        ["Low-density lipoprotein (LDL) cholesterol", "High-density lipoprotein (HDL)"],
    )
    def test_should_not_fire_on_high_or_low_inside_an_analyte_name(self, concept_set_name):
        """The measured reason `high` and `low` are OFF the vocabulary. In both corpora
        they occur only as part of an analyte's own name and inside the composite rule
        "High risk of CV events", which asserts no lab bound. Matching them as bare
        words is the false-positive shape this check must not have."""
        expression = _expression(
            [_measurement_rule("High risk of CV events", 20)], {20: concept_set_name}
        )
        assert asserted_bound_missing_criteria(expression) == []

    def test_should_not_judge_a_criteria_type_that_cannot_carry_a_ranged_bound(self):
        """`RangeHigh`/`RangeLow` and their ratio forms are readable only by
        `Measurement`, so a lost bound elsewhere is a different defect with a different
        repair. Out of scope deliberately rather than guessed at."""
        expression = _expression([], {30: "Elevated something"})
        expression["InclusionRules"] = [
            {
                "name": "Elevated marker",
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {"ConditionOccurrence": {"CodesetId": 30}},
                            "Occurrence": {"Type": 0, "Count": 0},
                        }
                    ],
                },
            }
        ]
        assert asserted_bound_missing_criteria(expression) == []

    def test_should_still_fire_when_the_codeset_reference_dangles(self):
        """A missing `ConceptSets` entry removes one of the two name sources; the rule
        name is in the file either way, so the check reads what it has rather than
        returning early."""
        expression = _expression([_measurement_rule("Elevated HbA1c", 99)], {})
        findings = asserted_bound_missing_criteria(expression)
        assert len(findings) == 1
        assert "its rule name asserts one" in findings[0]

    def test_should_report_one_finding_per_criterion_when_both_names_assert(self):
        """Both sides asserting is one defect, not two, and the concept set is quoted
        because it names the analyte rather than the six-way concatenated rule."""
        expression = _expression(
            [_measurement_rule("Elevated HbA1c", 66)], {66: "Elevated Hemoglobin A1c"}
        )
        findings = asserted_bound_missing_criteria(expression)
        assert len(findings) == 1
        assert "its concept-set name asserts one" in findings[0]


class TestTheDeliveryGateFailsOnIt:
    """It FAILS a delivery rather than reporting, and the argument is that the emitted
    rule is ACTIVELY WRONG rather than merely absent: an absence rule over "any ALT ever
    drawn" excludes essentially the whole cohort, and a presence rule over "any HbA1c
    ever drawn" includes essentially everybody. A recorded loss at least leaves the claim
    honestly missing; this one ships a rule that reads as filtered and is not.

    The heuristic half does not decide WHETHER something is lost -- that half is
    structural and exact. It decides only whether the name asserts a bound, and on the
    two real corpora it is 30 for 30. A warn-only rollout would also change nothing
    today, since all twelve files already fail; failing is the only form in which this
    check can block a FUTURE delivery, which is the delivery it exists for.
    """

    def test_should_fail_the_delivery_and_name_the_criterion(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        expression = _expression(
            [
                {"name": "rule one", "expression": {"Type": "ALL", "CriteriaList": []}},
                _measurement_rule("Elevated HbA1c", 66),
            ],
            {1: "apixaban", 66: "Hemoglobin A1c"},
        )
        study = {
            "id": 3,
            "name": "Study 3",
            "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "apixaban"}, {"name": "warfarin"}],
            "eligibility": {
                "inclusionCriteria": [],
                "exclusionCriteria": [],
                "structuredExpression": json.loads(json.dumps(expression)),
            },
        }
        study["eligibility"]["structuredExpression"]["ConceptSets"][0]["expression"] = {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": 43013024,
                        "CONCEPT_NAME": "apixaban",
                        "DOMAIN_ID": "Drug",
                        "VOCABULARY_ID": "RxNorm",
                        "CONCEPT_CLASS_ID": "Ingredient",
                        "CONCEPT_CODE": "1",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        }
        core = study["eligibility"]["structuredExpression"]
        for role in ("treatment", "comparator"):
            (tmp_path / f"aristotle_{role}.circe.json").write_text(json.dumps(core))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "aristotle=3"])
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "asserted bound missing (1)" in out
        assert "Hemoglobin A1c" in out


@pytest.mark.skipif(not BATCH.is_dir(), reason=f"delivered batch not present: {BATCH}")
class TestAgainstTheRealTwentySix:
    """The measurement that decides whether the vocabulary is worth anything. A green
    self-test over synthetic strings proves nothing about the corpus it was written
    for -- `docs/mistakes.md`, and the reason this class exists."""

    @staticmethod
    def _findings() -> dict[tuple[str, int], str]:
        found: dict[tuple[str, int], str] = {}
        for path in sorted(BATCH.glob("*.circe.json")):
            expression = json.loads(path.read_text())
            for finding in asserted_bound_missing_criteria(expression):
                codeset = int(finding.split("over codeset ")[1].split()[0])
                found[(path.name.removesuffix(".circe.json"), codeset)] = finding
        return found

    def test_should_find_exactly_the_twenty_six_known_lost_bounds(self):
        found = self._findings()
        assert set(found) == EXPECTED_BATCH_FINDINGS
        assert len(found) == 26

    def test_should_leave_the_other_bare_measurement_criteria_alone(self):
        """32 bare criteria in the batch, 26 flagged. The 6 that are not -- LEADER 8,
        PLATO 9 and PLATO 15 on both arms -- assert no numeric bound and are right to
        pass. The counts are re-derived from the files rather than quoted, so a
        vocabulary that widened later would show up here as a shrinking gap."""
        total = bare = 0
        for path in sorted(BATCH.glob("*.circe.json")):
            expression = json.loads(path.read_text())
            for _where, entry in _criterion_locations(expression):
                body = entry.get("Criteria")
                body = body if isinstance(body, dict) else entry
                payload = body.get("Measurement")
                if not isinstance(payload, dict) or "CodesetId" not in payload:
                    continue
                total += 1
                bare += not unreadable_value_attributes("Measurement", payload) and not any(
                    key in VALUE_CONDITION_ATTRIBUTES for key in payload
                )
        assert (total, bare) == (136, 32)
        assert len(self._findings()) == 26

    def test_should_not_fire_on_carolina_rule_30_which_kept_its_ratio_bound(self):
        """The named false positive, and the sharpest one available: rule 30's name is
        "Alanine aminotransferase LEVEL + ..." -- the same vocabulary term that fires on
        its sibling rule 33 ("Thyroxine (T4) level"). What separates them is structural,
        not lexical: rule 30 carries the `RangeHighRatio` that rule 33 lost."""
        expression = json.loads((BATCH / "carolina_treatment.circe.json").read_text())
        rule_30 = expression["InclusionRules"][30]
        assert _BOUND_ASSERTION_RE.search(rule_30["name"]), rule_30["name"]
        payloads = [
            (entry.get("Criteria") or entry)["Measurement"]
            for _where, entry in _criterion_locations({"InclusionRules": [rule_30]})
            if "Measurement" in (entry.get("Criteria") or entry)
        ]
        codesets = {payload["CodesetId"] for payload in payloads}
        assert codesets == {36, 37, 38}
        assert all("RangeHighRatio" in payload for payload in payloads)
        flagged = {key[1] for key in self._findings() if key[0] == "carolina_treatment"}
        assert not (codesets & flagged)


@pytest.mark.skipif(not GOLD.is_dir(), reason=f"gold corpus not present: {GOLD}")
class TestAgainstTheHandBuiltGoldCorpus:
    """An independent corpus the vocabulary was NOT written against -- the strongest
    false-positive surface available. It finds 4, and all 4 are real."""

    @staticmethod
    def _findings() -> list[tuple[str, str]]:
        return [
            (path.name, finding)
            for path in sorted(GOLD.rglob("*.json"))
            for finding in asserted_bound_missing_criteria(json.loads(path.read_text()))
        ]

    def test_should_find_exactly_four_and_only_in_aristotle(self):
        findings = self._findings()
        assert len(findings) == 4
        assert {name for name, _ in findings} == {
            "_TROY v1.1_ Apixaban (ARISTOTLE).json",
            "_TROY v1.1_ Warfarin (ARISTOTLE).json",
        }

    def test_should_name_the_blood_pressure_criteria_whose_bound_the_gold_lost(self):
        """Not a false positive. The rule name carries the numbers verbatim -- "systolic
        BP > 180 mm Hg, or diastolic BP > 100 mm Hg" -- and the emitted criteria are
        `{CodesetId: 98}` and `{CodesetId: 99}` with no value condition, so as absence
        criteria they exclude every patient who has ever had a BP recorded."""
        findings = self._findings()
        assert all("uncontrolled hypertension" in finding for _name, finding in findings)
        assert {finding.split("over codeset ")[1].split()[0] for _n, finding in findings} == {
            "98",
            "99",
        }
