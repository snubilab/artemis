"""A concept set whose NAME states an exclusion its MEMBERS do not honour.

The 2026-09-11 conversion audit (`output/site_gap/2026-09-14/conversion_audit.json`)
reports LEADER shipping three concept sets named for an exclusion that was never
applied::

    ConceptSet 12  'human NPH insulin'                            26 ids
    ConceptSet 54  'insulin other than human NPH insulin'         the SAME 26 ids
    ConceptSet 56  'insulin other than premixed insulin'          the SAME 26 ids

`InclusionRules[2]` group G2 requires the patient to HAVE codeset 12;
`InclusionRules[24]` group G0 requires them to have zero exposures to codeset 54.
Identical members, opposite demands, overlapping windows -- the delivered cohort
excludes patients for taking the very insulins the protocol requires them to be on.

Two structural signatures, and neither needs a vocabulary or a database
----------------------------------------------------------------------
Both checks below read only the emitted JSON, which is what lets them run in the
delivery gate beside the seven lints already there.

* :func:`aliased_concept_sets` -- two concept sets in one cohort holding byte-identical
  members under different names. Either one name says more than its members do, or the
  same criterion was mapped twice. Nothing in the file can make identical members mean
  two different things.
* :func:`contradictory_presence_absence_criteria` -- a mandatory presence and a
  mandatory absence over the same (or member-identical) concept set, with overlapping
  windows. CIRCE ANDs every `InclusionRules` entry, so the two are conjoined whether
  they sit in one rule or in two, and the conjunction is empty.

Why the seven existing lints cannot see either
----------------------------------------------
Measured at `953d6b2` on both delivered LEADER arms: `noop_exclusion_rules`,
`contradictory_absence_rules`, `domain_mismatched_criteria`,
`unreadable_value_filter_criteria` and `partially_readable_criteria` return nothing at
all, and the two that do fire (`asserted_bound_missing_criteria`,
`unfiltered_measurement_absence_criteria`) both name only codeset 29 'Elevated HbA1c'
-- a different rule, a different defect.

  * `contradictory_absence_rules` is the near miss. It tests an absence against the
    cohort's own ENTRY concept set; codesets 10/11/12/13/54/56 are none of them.
  * `domain_mismatched_criteria` needs a set the CDM table cannot join. Every one of
    these is `Drug` under `DrugExposure`; the join is perfect.
  * `unfiltered_measurement_absence_criteria` judges `Measurement` only, because
    `value_as_number` is what makes a missing filter a loss. These are drugs.

What the tracing found, and what it did NOT find
------------------------------------------------
The qualifier is not stripped anywhere. `_criterionMappingMetadata` in the store
records `queryUsed` verbatim as `'insulin other than human NPH insulin'`, and the
emitted concept set still carries that name -- the whole string reaches the mapper and
survives into the output. No code under `src/` reads an entity-exclusion operator
("other than", "excluding", "except", "-naive"); the one qualifier-reading hook in the
seeded path, `TTEService._apply_route_subtraction`, reads routes of administration.
So the negation is available and unused rather than lost.

It is also NOT the cause of LEADER's unsatisfiable `InclusionRules[2]`. That rule's
three groups reference codesets 10, 11 and 12, and not one of those names carries an
exclusion qualifier; the contradiction is an OR emitted as `Type: ALL` (store group
`4a712697`, `groupType: "ALL"`, whose own group-label description reads
"... naive OR treated with OADs OR treated with ..."). The negation failure is an
independent second blocker in `InclusionRules[24]`, which is why these are two checks
and not one.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from src.utils.circe_lint import (
    aliased_concept_sets,
    contradictory_presence_absence_criteria,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
BATCH = REPO / "output" / "site_gap" / "2026-09-14" / "DELIVERY"
GOLD = REPO / "data" / "gold"

#: The 26 ids LEADER's codesets 12, 54 and 56 all carry, trimmed to four. The real set
#: is quoted in full nowhere here: the check compares ids, so four prove the same thing
#: twenty-six do, and a fixture nobody can read is a fixture nobody checks.
INSULINS = [
    (1502905, "insulin detemir"),
    (1516976, "insulin glargine"),
    (1567198, "insulin aspart"),
    (1531601, "insulin degludec"),
]


def _concept_set(codeset_id: int, name: str, concepts, domain: str = "Drug") -> dict:
    return {
        "id": codeset_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": cid,
                        "CONCEPT_NAME": cname,
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "RxNorm",
                        "CONCEPT_CLASS_ID": "Ingredient",
                        "STANDARD_CONCEPT": "S",
                    },
                    "includeDescendants": True,
                    "includeMapped": False,
                    "isExcluded": False,
                }
                for cid, cname in concepts
            ]
        },
    }


def _entry(codeset_id: int, *, absent: bool, start: int, end: int, criteria_type="DrugExposure",
           extra: dict | None = None) -> dict:
    payload: dict = {"CodesetId": codeset_id}
    payload.update(extra or {})
    return {
        "Criteria": {criteria_type: payload},
        "StartWindow": {
            "Start": {"Days": abs(start), "Coeff": -1 if start <= 0 else 1},
            "End": {"Days": abs(end), "Coeff": 1 if end >= 0 else -1},
        },
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": {"Type": 0, "Count": 0} if absent else {"Type": 2, "Count": 1},
    }


def _rule(name: str, entries, rule_type: str = "ALL") -> dict:
    return {
        "name": name,
        "expression": {
            "Type": rule_type,
            "CriteriaList": entries,
            "DemographicCriteriaList": [],
            "Groups": [],
        },
    }


class TestAliasedConceptSets:
    def test_should_report_the_pair_when_members_are_identical_and_names_differ(self):
        expression = {
            "ConceptSets": [
                _concept_set(12, "human NPH insulin", INSULINS),
                _concept_set(54, "insulin other than human NPH insulin", INSULINS),
            ],
            "InclusionRules": [],
        }
        findings = aliased_concept_sets(expression)
        assert len(findings) == 1, findings
        assert "12" in findings[0] and "54" in findings[0]
        assert "human NPH insulin" in findings[0]
        assert "insulin other than human NPH insulin" in findings[0]

    def test_should_report_all_three_ids_when_three_sets_share_one_member_set(self):
        expression = {
            "ConceptSets": [
                _concept_set(12, "human NPH insulin", INSULINS),
                _concept_set(54, "insulin other than human NPH insulin", INSULINS),
                _concept_set(56, "insulin other than premixed insulin", INSULINS),
            ],
            "InclusionRules": [],
        }
        findings = aliased_concept_sets(expression)
        assert len(findings) == 1, findings
        for codeset_id in ("12", "54", "56"):
            assert codeset_id in findings[0]

    def test_should_stay_silent_when_the_names_are_the_same(self):
        """LEADER's codesets 10, 11 and 13 are identical AND identically named -- one
        seed mapped three times. Redundant, but nothing in the file contradicts itself,
        and the consequence is what the second check reads."""
        expression = {
            "ConceptSets": [
                _concept_set(10, "oral anti-diabetic drugs", INSULINS),
                _concept_set(11, "oral anti-diabetic drugs", INSULINS),
            ],
            "InclusionRules": [],
        }
        assert aliased_concept_sets(expression) == []

    def test_should_stay_silent_when_one_set_is_a_strict_subset_of_the_other(self):
        """The legitimate shape a narrowing name describes: 'long-acting insulin' really
        does hold fewer members than 'insulin'. The check reads EQUALITY, so a genuine
        subset relation expressed by name never reaches it."""
        expression = {
            "ConceptSets": [
                _concept_set(1, "insulin", INSULINS),
                _concept_set(2, "long-acting insulin analogue", INSULINS[:2]),
            ],
            "InclusionRules": [],
        }
        assert aliased_concept_sets(expression) == []

    def test_should_stay_silent_on_two_empty_concept_sets(self):
        """Two empty sets are equal on members and say nothing. An empty concept set is
        its own defect and `verify_circe_delivery` already fails on one; reporting it
        here as an alias would bury that finding under a wrong headline."""
        expression = {
            "ConceptSets": [
                _concept_set(1, "one", []),
                _concept_set(2, "two", []),
            ],
            "InclusionRules": [],
        }
        assert aliased_concept_sets(expression) == []

    def test_should_separate_sets_that_differ_only_by_an_isexcluded_flag(self):
        """`isExcluded` is the axis the missing negation should have used, so two sets
        over the same ids that disagree about it are genuinely different sets."""
        included = _concept_set(1, "insulin", INSULINS)
        subtracted = _concept_set(2, "insulin other than detemir", INSULINS)
        subtracted["expression"]["items"][0]["isExcluded"] = True
        expression = {"ConceptSets": [included, subtracted], "InclusionRules": []}
        assert aliased_concept_sets(expression) == []


class TestContradictoryPresenceAbsence:
    def test_should_report_a_presence_and_an_absence_on_one_codeset_in_one_rule(self):
        expression = {
            "ConceptSets": [_concept_set(11, "oral anti-diabetic drugs", INSULINS)],
            "InclusionRules": [
                _rule(
                    "naive + treated",
                    [
                        _entry(11, absent=True, start=-365, end=-1),
                        _entry(11, absent=False, start=-365, end=0),
                    ],
                )
            ],
        }
        findings = contradictory_presence_absence_criteria(expression)
        assert len(findings) == 1, findings
        assert "codeset 11" in findings[0]

    def test_should_report_across_two_rules_because_circe_ands_them(self):
        """LEADER's rule 3 ('zero exposures to codeset 13') against rule 2's G1 ('at
        least one exposure to codeset 11'). Two rules, identical members -- and CIRCE
        conjoins every `InclusionRules` entry, so the pair is as empty as a single rule
        carrying both."""
        expression = {
            "ConceptSets": [
                _concept_set(11, "oral anti-diabetic drugs", INSULINS),
                _concept_set(13, "oral anti-diabetic drugs", INSULINS),
            ],
            "InclusionRules": [
                _rule("treated with OADs", [_entry(11, absent=False, start=-365, end=0)]),
                _rule("drug naive", [_entry(13, absent=True, start=-365, end=-1)]),
            ],
        }
        findings = contradictory_presence_absence_criteria(expression)
        assert len(findings) == 1, findings
        assert "codeset 13" in findings[0] and "codeset 11" in findings[0]

    def test_should_stay_silent_when_the_windows_do_not_overlap(self):
        """A washout followed by treatment is ordinary clinical logic: 'no exposure in
        [-365,-91] and at least one in [-30,0]' is satisfiable and common."""
        expression = {
            "ConceptSets": [_concept_set(11, "oral anti-diabetic drugs", INSULINS)],
            "InclusionRules": [
                _rule(
                    "washout then treated",
                    [
                        _entry(11, absent=True, start=-365, end=-91),
                        _entry(11, absent=False, start=-30, end=0),
                    ],
                )
            ],
        }
        assert contradictory_presence_absence_criteria(expression) == []

    def test_should_stay_silent_when_the_presence_sits_under_an_any_group(self):
        """`ANY` offers alternatives, so a contradicted branch does not empty the rule.
        Only a mandatory presence conflicts with a mandatory absence."""
        expression = {
            "ConceptSets": [_concept_set(11, "oral anti-diabetic drugs", INSULINS)],
            "InclusionRules": [
                _rule("drug naive", [_entry(11, absent=True, start=-365, end=0)]),
                {
                    "name": "any of these",
                    "expression": {
                        "Type": "ANY",
                        "CriteriaList": [_entry(11, absent=False, start=-365, end=0)],
                        "DemographicCriteriaList": [],
                        "Groups": [],
                    },
                },
            ],
        }
        assert contradictory_presence_absence_criteria(expression) == []

    def test_should_stay_silent_when_the_absence_carries_a_value_filter(self):
        """An absence narrowed by a threshold selects a SUBSET of its concept set, so
        the presence may live outside it: 'no HbA1c below 6' and 'an HbA1c of at least
        7' are both true of the same patient."""
        expression = {
            "ConceptSets": [_concept_set(17, "HbA1c", INSULINS, domain="Measurement")],
            "InclusionRules": [
                _rule(
                    "bounded",
                    [
                        _entry(
                            17, absent=True, start=-365, end=0, criteria_type="Measurement",
                            extra={"ValueAsNumber": {"Value": 6.0, "Op": "lt"}},
                        ),
                        _entry(
                            17, absent=False, start=-365, end=0, criteria_type="Measurement",
                            extra={"ValueAsNumber": {"Value": 7.0, "Op": "gte"}},
                        ),
                    ],
                )
            ],
        }
        assert contradictory_presence_absence_criteria(expression) == []

    def test_should_report_when_only_the_presence_is_narrowed(self):
        """The other half of the guard, and the reason it is asymmetric: an absence over
        the WHOLE set kills a presence however the presence is qualified. 'No HbA1c on
        record at all' and 'an HbA1c of at least 7 in the last 180 days' cannot both
        hold."""
        expression = {
            "ConceptSets": [_concept_set(17, "HbA1c", INSULINS, domain="Measurement")],
            "InclusionRules": [
                _rule(
                    "never tested",
                    [_entry(17, absent=True, start=-9999, end=0, criteria_type="Measurement")],
                ),
                _rule(
                    "elevated",
                    [
                        _entry(
                            17, absent=False, start=-180, end=0, criteria_type="Measurement",
                            extra={"ValueAsNumber": {"Value": 7.0, "Op": "gte"}},
                        )
                    ],
                ),
            ],
        }
        findings = contradictory_presence_absence_criteria(expression)
        assert len(findings) == 1, findings
        assert "codeset 17" in findings[0]

    def test_should_stay_silent_on_two_different_concept_sets(self):
        expression = {
            "ConceptSets": [
                _concept_set(11, "oral anti-diabetic drugs", INSULINS),
                _concept_set(12, "human NPH insulin", INSULINS[:2]),
            ],
            "InclusionRules": [
                _rule("naive", [_entry(11, absent=True, start=-365, end=0)]),
                _rule("treated", [_entry(12, absent=False, start=-365, end=0)]),
            ],
        }
        assert contradictory_presence_absence_criteria(expression) == []

    def test_should_report_when_a_window_is_unprovable(self):
        """Uncertainty never silences the check -- the same convention
        `_effective_end_days` already applies for `contradictory_absence_rules`."""
        entry = _entry(11, absent=True, start=-365, end=0)
        entry["StartWindow"]["End"] = {"Coeff": -1}
        expression = {
            "ConceptSets": [_concept_set(11, "oral anti-diabetic drugs", INSULINS)],
            "InclusionRules": [
                _rule("naive", [entry]),
                _rule("treated", [_entry(11, absent=False, start=-30, end=0)]),
            ],
        }
        assert len(contradictory_presence_absence_criteria(expression)) == 1


@pytest.mark.skipif(not BATCH.is_dir(), reason=f"delivered batch not present: {BATCH}")
class TestAgainstTheDeliveredBatch:
    """The measurement that decides whether either check is worth anything. A green
    self-test over fixtures this file wrote itself proves nothing about the corpus the
    checks were written for -- `docs/mistakes.md`, and the reason this class exists."""

    @staticmethod
    def _load(stem: str) -> dict:
        return json.loads((BATCH / f"{stem}.circe.json").read_text())

    def test_should_fire_on_leader_insulin_alias_in_both_arms(self):
        for arm in ("leader_treatment", "leader_comparator"):
            findings = aliased_concept_sets(self._load(arm))
            insulin = [f for f in findings if "other than human NPH insulin" in f]
            assert len(insulin) == 1, findings
            assert "human NPH insulin" in insulin[0]
            assert "other than premixed insulin" in insulin[0]

    def test_should_fire_on_leader_rule_24_against_rule_2_in_both_arms(self):
        """The negation defect's own consequence: rule 24 demands zero exposures to
        codeset 54 while rule 2's G2 demands at least one to codeset 12, and the two
        sets are byte-identical."""
        for arm in ("leader_treatment", "leader_comparator"):
            findings = contradictory_presence_absence_criteria(self._load(arm))
            rule_24 = [f for f in findings if "InclusionRules[24]" in f]
            assert len(rule_24) == 2, findings
            assert all("InclusionRules[2]" in f for f in rule_24)

    def test_should_fire_on_leader_rule_2_internal_contradiction_in_both_arms(self):
        """The blocker the audit reports first, and the one the negation failure does
        NOT cause: codesets 10 and 11 are identical, and rule 2 demands zero of one and
        at least one of the other."""
        for arm in ("leader_treatment", "leader_comparator"):
            findings = contradictory_presence_absence_criteria(self._load(arm))
            internal = [
                f for f in findings if "codeset 10" in f and "codeset 11" in f
            ]
            assert len(internal) == 1, findings

    def test_should_find_exactly_four_contradictions_in_leader_and_none_elsewhere(self):
        by_file = {
            path.stem.replace(".circe", ""): contradictory_presence_absence_criteria(
                json.loads(path.read_text())
            )
            for path in sorted(BATCH.glob("*.circe.json"))
        }
        assert len(by_file["leader_treatment"]) == 4, by_file["leader_treatment"]
        assert len(by_file["leader_comparator"]) == 4, by_file["leader_comparator"]
        quiet = {k: v for k, v in by_file.items() if not k.startswith("leader_")}
        assert len(quiet) == 10
        assert all(v == [] for v in quiet.values()), quiet

    def test_should_find_one_alias_group_per_affected_arm_and_none_in_the_other_trials(self):
        """The measured cost of the alias check, stated rather than tuned away. Three
        trials carry a group; all three point at something real, and the two that are
        not the insulin defect are an over-narrow map ('Aspirin and thienopyridine use'
        holding aspirin alone) and one criterion emitted twice (EMPA-REG rules 8 and 9,
        both 'eGFR < 30' with different unit lists)."""
        by_file = {
            path.stem.replace(".circe", ""): aliased_concept_sets(
                json.loads(path.read_text())
            )
            for path in sorted(BATCH.glob("*.circe.json"))
        }
        noisy = {k: v for k, v in by_file.items() if v}
        assert set(noisy) == {
            "aristotle_treatment", "aristotle_comparator",
            "empa-reg_treatment", "empa-reg_comparator",
            "leader_treatment", "leader_comparator",
        }, sorted(noisy)
        assert all(len(v) == 1 for v in noisy.values()), noisy
        assert all(v == [] for k, v in by_file.items() if k not in noisy)


    def test_applying_the_negation_to_the_real_file_silences_only_the_negation_findings(self):
        """The control that separates the two defects, on the real artifact rather than
        on a fixture. Subtracting each 'other than X' set's X as `isExcluded` -- the axis
        CIRCE provides and the pipeline never uses -- drops both `InclusionRules[24]`
        findings and the alias group, and leaves `InclusionRules[2]`/`[3]` contradicting
        each other exactly as before. So the missing negation does NOT cause LEADER's
        unsatisfiable rule 2; that one is an OR emitted as `Type: ALL` over codesets
        whose names carry no qualifier at all, and no negation repair can reach it."""
        expression = copy.deepcopy(self._load("leader_treatment"))
        assert len(aliased_concept_sets(expression)) == 1
        assert len(contradictory_presence_absence_criteria(expression)) == 4

        by_id = {c["id"]: c for c in expression["ConceptSets"]}
        nph = {i["concept"]["CONCEPT_ID"] for i in by_id[12]["expression"]["items"]}
        premixed = {
            i["concept"]["CONCEPT_ID"]
            for i in by_id[56]["expression"]["items"]
            if "protamine" in i["concept"]["CONCEPT_NAME"].lower()
        }
        assert nph and premixed and premixed != nph
        for codeset_id, subtract in ((54, nph), (56, premixed)):
            for item in by_id[codeset_id]["expression"]["items"]:
                if item["concept"]["CONCEPT_ID"] in subtract:
                    item["isExcluded"] = True

        assert aliased_concept_sets(expression) == []
        remaining = contradictory_presence_absence_criteria(expression)
        assert len(remaining) == 2, remaining
        assert not any("InclusionRules[24]" in f for f in remaining)


@pytest.mark.skipif(not GOLD.is_dir(), reason=f"gold corpus not present: {GOLD}")
class TestAgainstTheHandBuiltGold:
    """The 18 TROY v1.1 files are the only hand-authored reference available, so they
    are the closest thing to a false-positive control the repo has."""

    def test_contradiction_check_should_be_silent_on_every_gold_file(self):
        noisy = {
            path.name: contradictory_presence_absence_criteria(
                json.loads(path.read_text())
            )
            for path in sorted(GOLD.glob("*/*.json"))
        }
        assert len(noisy) == 18
        assert all(v == [] for v in noisy.values()), {k: v for k, v in noisy.items() if v}

    def test_alias_check_fires_on_three_gold_files_and_this_is_the_measured_cost(self):
        """Gold's own conventions produce three alias groups: a drug sourced twice
        ('Warfarin' and 'Warfarin (ATC)') and a deliberate Condition/Procedure split
        that lands on one concept. Neither is a negation defect. The gate never reads
        `data/gold/`, so this costs no delivery -- it is recorded so the check's
        precision is a measurement rather than a hope."""
        noisy = {
            path.name: aliased_concept_sets(json.loads(path.read_text()))
            for path in sorted(GOLD.glob("*/*.json"))
        }
        firing = {k: v for k, v in noisy.items() if v}
        assert len(firing) == 3, firing
        assert all(len(v) == 1 for v in firing.values()), firing
