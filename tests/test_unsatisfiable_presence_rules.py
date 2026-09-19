"""A mandatory presence rule whose every disjunct is forbidden by a mandatory absence.

The real event, `deliveries/2026-09-12/carmelina_comparator.circe.json` (byte-identical
in `carmelina_treatment`), rules 12 and 13 as the hospital received them::

    #12 'HbA1c at least 6.5% + HbA1c at most 10.0%'      <- ANY over two ALL groups
        ANY( Occurrence{Type:2,Count:1} Measurement cs8  gte 6.5  unit[8554] win -180..0
           , Occurrence{Type:2,Count:1} Measurement cs9  lte 10.0 unit[8554] win -180..0 )

    #13 'HbA1c below lower limit + HbA1c above upper limit'   <- ALL over two ALL groups
        ALL( Occurrence{Type:0,Count:0} Measurement cs10 gte 6.5  unit[8554] win -180..0
           , Occurrence{Type:0,Count:0} Measurement cs11 lte 10.0 unit[8554] win -180..0 )

Concept sets 8, 9, 10 and 11 are all named `'HbA1c'` and all carry the identical five
members `[3004410, 3007263, 3034639, 4197971, 44793001]`. CIRCE conjoins every
`InclusionRules` entry, so #13 forbids exactly the two predicates #12's two disjuncts
require: every disjunct of #12 is forbidden, so #12 selects nobody on any CDM with any
data. The hospital's per-rule counts corroborate it -- #12 and #13 sum to the entry
count exactly in all four measured arms.

The upstream cause is not repaired here and is not what these tests read: the extractor
negated an exclusion without inverting the comparison operator, so the stored criterion
carries `op: gte 6.5, logicType: ABSENCE`. These checks detect the emitted shape.

Why the two nearest existing lints are blind, measured rather than assumed
-------------------------------------------------------------------------
Both return `[]` on the real file:

* `aliased_concept_sets` requires identical members under DIFFERENT names, and
  deliberately excludes identical names. All four sets are named `'HbA1c'`.
* `contradictory_presence_absence_criteria` already pairs by member set as well as by
  codeset id, so the "same members, different id" hole is NOT what blinds it. Two
  documented silences do: `_unnarrowed_codeset` drops #13's absences because they carry
  a value bound and a unit (an absence narrowed by a bound forbids only part of its set,
  so in general it contradicts nothing), and `_conjoined_entries` does not descend #12's
  top-level `ANY` (one contradicted alternative does not empty a disjunction). Both
  silences are right in general; what closes the gap is comparing the BOUNDS, which is
  what the two checks below do.

Two tiers, because the two shapes carry different certainty
-----------------------------------------------------------
* `unsatisfiable_presence_rules` (FAIL) -- every required signature in a rule is
  forbidden verbatim. Provably empty from the file alone, no CDM needed.
* `bound_contradicted_presence_criteria` (lower severity) -- the weaker shape the first
  correctly does not catch. `2026-09-18_verify4` rewrote #12 to `bt 6.5..10` with the
  unit filter dropped, so the signature no longer matches what #13 forbids; #13 is
  untouched, so a patient whose in-range HbA1c is recorded in `%` still satisfies #12
  and fails #13. The intersection is "only patients whose HbA1c carries a non-% unit",
  which at a site recording in `%` is effectively zero but is not provably empty.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.utils.circe_lint import (
    bound_contradicted_presence_criteria,
    contradictory_presence_absence_criteria,
    unsatisfiable_presence_rules,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
DELIVERY_2026_09_12 = REPO / "deliveries" / "2026-09-12"

#: The five ids concept sets 8, 9, 10 and 11 all carry in the delivered file, quoted in
#: full because the whole defect is that they are identical and a trimmed fixture would
#: be proving something smaller than the real event.
HBA1C_MEMBERS = [3004410, 3007263, 3034639, 4197971, 44793001]

#: Verbatim from the delivered file. The unit concept is what `verify4` dropped from the
#: presence side while leaving it on the absence side, which is the whole of tier 2.
PERCENT = {
    "CONCEPT_CODE": "%",
    "CONCEPT_ID": 8554,
    "CONCEPT_NAME": "percent",
    "DOMAIN_ID": "Unit",
    "INVALID_REASON_CAPTION": "Unknown",
    "STANDARD_CONCEPT_CAPTION": "Unknown",
    "VOCABULARY_ID": "UCUM",
}

#: `-180..0`, verbatim from every one of the four criteria.
WINDOW_180_DAYS = {"Start": {"Days": 180, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}}


def _hba1c_set(codeset_id: int, name: str = "HbA1c") -> dict:
    return {
        "id": codeset_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": "Hemoglobin A1c",
                        "DOMAIN_ID": "Measurement",
                        "VOCABULARY_ID": "LOINC",
                        "STANDARD_CONCEPT": "S",
                    },
                    "includeDescendants": True,
                    "includeMapped": False,
                    "isExcluded": False,
                }
                for concept_id in HBA1C_MEMBERS
            ]
        },
    }


def _measurement(
    codeset_id: int,
    *,
    absent: bool,
    op: str,
    value: float,
    extent: float | None = None,
    units: tuple[dict, ...] = (PERCENT,),
) -> dict:
    payload: dict = {"CodesetId": codeset_id, "ValueAsNumber": {"Value": value, "Op": op}}
    if extent is not None:
        payload["ValueAsNumber"]["Extent"] = extent
        payload["ValueAsNumber"] = {"Value": value, "Extent": extent, "Op": op}
    if units:
        payload["Unit"] = list(units)
    return {
        "Criteria": {"Measurement": payload},
        "StartWindow": dict(WINDOW_180_DAYS),
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": {"Type": 0, "Count": 0} if absent else {"Type": 2, "Count": 1},
    }


def _group(entries, group_type: str = "ALL") -> dict:
    return {
        "Type": group_type,
        "CriteriaList": list(entries),
        "DemographicCriteriaList": [],
        "Groups": [],
    }


def _rule(name: str, groups, group_type: str) -> dict:
    """A rule whose top node is ``group_type`` over one ``ALL`` group per entry.

    That nesting is the delivered shape -- both #12 and #13 wrap each criterion in its
    own single-member ``ALL`` group rather than listing them in one ``CriteriaList`` --
    and it is load-bearing for the mandatory-path reading, so the fixture keeps it.
    """
    return {
        "name": name,
        "expression": {
            "Type": group_type,
            "CriteriaList": [],
            "DemographicCriteriaList": [],
            "Groups": [_group([entry]) for entry in groups],
        },
    }


def _delivered_shape(
    *,
    presence_type: str = "ANY",
    absence_type: str = "ALL",
    presences=None,
    absences=None,
) -> dict:
    """The real 2026-09-12 CARMELINA rules 12 and 13, with the axes the tests vary."""
    return {
        "ConceptSets": [_hba1c_set(codeset_id) for codeset_id in (8, 9, 10, 11)],
        "PrimaryCriteria": {},
        "InclusionRules": [
            _rule(
                "HbA1c at least 6.5% + HbA1c at most 10.0%",
                presences
                if presences is not None
                else [
                    _measurement(8, absent=False, op="gte", value=6.5),
                    _measurement(9, absent=False, op="lte", value=10.0),
                ],
                presence_type,
            ),
            _rule(
                "HbA1c below lower limit + HbA1c above upper limit",
                absences
                if absences is not None
                else [
                    _measurement(10, absent=True, op="gte", value=6.5),
                    _measurement(11, absent=True, op="lte", value=10.0),
                ],
                absence_type,
            ),
        ],
    }


def _legitimate_shape() -> dict:
    """"At least one HbA1c in 6.5..10, and none above 10" -- satisfiable, and common.

    The absence forbids `> 10` strictly, so nothing it forbids is anything the presence
    requires. Both tiers must stay silent: tier 1 because the signatures differ, tier 2
    because the intervals do not share a value.
    """
    return {
        "ConceptSets": [_hba1c_set(codeset_id) for codeset_id in (8, 10)],
        "PrimaryCriteria": {},
        "InclusionRules": [
            _rule(
                "HbA1c within range",
                [_measurement(8, absent=False, op="bt", value=6.5, extent=10.0)],
                "ALL",
            ),
            _rule(
                "HbA1c above upper limit",
                [_measurement(10, absent=True, op="gt", value=10.0)],
                "ALL",
            ),
        ],
    }


class TestUnsatisfiablePresenceRules:
    """Tier 1 -- FAIL. Every required signature in the rule is forbidden verbatim."""

    def test_should_report_rule_12_when_every_disjunct_is_forbidden_by_rule_13(self):
        findings = unsatisfiable_presence_rules(_delivered_shape())
        assert len(findings) == 1, findings
        assert "HbA1c at least 6.5% + HbA1c at most 10.0%" in findings[0]
        assert "InclusionRules[0]" in findings[0]

    def test_should_report_the_real_delivered_carmelina_files(self):
        """The same predicate against the bytes the hospital actually received."""
        for name in ("carmelina_comparator", "carmelina_treatment"):
            path = DELIVERY_2026_09_12 / f"{name}.circe.json"
            findings = unsatisfiable_presence_rules(json.loads(path.read_text()))
            assert len(findings) == 1, (name, findings)
            assert "HbA1c at least 6.5% + HbA1c at most 10.0%" in findings[0], name

    def test_should_stay_silent_when_the_absence_bound_misses_the_presence_bound(self):
        assert unsatisfiable_presence_rules(_legitimate_shape()) == []

    def test_should_stay_silent_when_the_absence_sits_under_an_any_group(self):
        """`ANY` over absences forbids nothing -- one branch holding is enough, so
        neither absence is reached through a mandatory path and neither is forbidden."""
        assert unsatisfiable_presence_rules(_delivered_shape(absence_type="ANY")) == []

    def test_should_stay_silent_when_only_one_disjunct_is_forbidden(self):
        """The rule is still satisfiable through the disjunct nobody forbade."""
        findings = unsatisfiable_presence_rules(
            _delivered_shape(absences=[_measurement(10, absent=True, op="gte", value=6.5)])
        )
        assert findings == [], findings


class TestBoundContradictedPresenceCriteria:
    """Tier 2 -- the weaker shape tier 1 correctly does not catch."""

    def test_should_report_the_verify4_shape_when_the_absence_covers_the_presence(self):
        """`2026-09-18_verify4`: the presence was rewritten to `bt 6.5..10` with the unit
        filter dropped, so no signature matches what #13 forbids -- but `gte 6.5` over
        the same members and window forbids EVERY value in `6.5..10`, and a presence with
        no unit filter is compatible with an absence filtered to `%`."""
        findings = bound_contradicted_presence_criteria(
            _delivered_shape(
                presence_type="ALL",
                presences=[
                    _measurement(8, absent=False, op="bt", value=6.5, extent=10.0, units=())
                ],
            )
        )
        assert findings, findings
        assert any("HbA1c at least 6.5% + HbA1c at most 10.0%" in f for f in findings)

    def test_should_stay_silent_when_the_absence_only_clips_the_presence(self):
        assert bound_contradicted_presence_criteria(_legitimate_shape()) == []


class TestContradictoryPresenceAbsencePairsByMembers:
    def test_should_pair_two_codesets_with_identical_members_under_different_ids(self):
        """The general "same members, different id" pairing, on the measurement shape.

        An UNNARROWED absence over codeset 10 against a presence over codeset 8: the two
        ids are distinct and the member sets are byte-identical, and the pair is reported
        on the members alone. This is the hole the brief expected to be open; it is not
        -- see the module docstring for what actually blinds this check on the real file.
        """
        expression = {
            "ConceptSets": [_hba1c_set(8), _hba1c_set(10)],
            "InclusionRules": [
                _rule(
                    "HbA1c at least 6.5%",
                    [_measurement(8, absent=False, op="gte", value=6.5)],
                    "ALL",
                ),
                {
                    "name": "no HbA1c on record",
                    "expression": _group(
                        [
                            {
                                "Criteria": {"Measurement": {"CodesetId": 10}},
                                "StartWindow": dict(WINDOW_180_DAYS),
                                "RestrictVisit": False,
                                "IgnoreObservationPeriod": False,
                                "Occurrence": {"Type": 0, "Count": 0},
                            }
                        ]
                    ),
                },
            ],
        }
        findings = contradictory_presence_absence_criteria(expression)
        assert len(findings) == 1, findings
        assert "codeset 10" in findings[0] and "codeset 8" in findings[0]
        assert "IDENTICAL" in findings[0]


@pytest.mark.parametrize("name", ["carmelina_comparator", "carmelina_treatment"])
def test_should_leave_the_existing_presence_absence_check_silent_on_the_real_files(name):
    """The before/after control for the widening question: the existing check reports
    nothing on the two defective files, and nothing is what it reported before."""
    path = DELIVERY_2026_09_12 / f"{name}.circe.json"
    assert contradictory_presence_absence_criteria(json.loads(path.read_text())) == []
