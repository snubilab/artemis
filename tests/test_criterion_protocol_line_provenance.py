"""A store criterion records the protocol line it was extracted from.

Thirteen fields describe a stored criterion and none of them said which line of
the protocol produced it. Two things follow, and the second is the serious one.

A **collapse** is invisible. One protocol line can legitimately yield one
criterion or several; without the line, "one criterion here, four there" and
"one criterion because the line warranted one" are the same record. CAROLINA's
liver line is the measured case, and it is in
``tests/fixtures/carolina_liver_line_ir.json``: two recorded Agent 1 runs read
the byte-identical line

    1. Active liver disease or impaired hepatic function, defined by serum
       levels of either ALT (SGPT), AST (SGOT), or alkaline phosphatase above
       3 x upper limit of normal (ULN) as determined at visit 1a

and one emitted three criteria (ALT, AST, ALP) while the other emitted one.
In the store built from the second, ``Aspartate``/``Alkaline`` appear nowhere at
all -- the collapse leaves no trace, so no count of the study can find it.

**Extraction and invention are indistinguishable.** ``3x ULN`` is written in the
line above, so a criterion carrying it is a reading. The same store also holds
criteria carrying ``3x ULN`` under the line ``acute liver disease or impaired
hepatic function``, which names no analyte and no threshold -- there, the number
is the model's own. Scoring the two the same way scores invention as extraction.
``protocolLine`` is what separates them: the criterion carries the line, so the
line can be read next to what was claimed from it.

This is provenance only. Nothing here decides what a suspicious cardinality
means; it makes the cardinality readable.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.api.models.tte import CRITERION_PROTOCOL_LINE_KEY, Criterion
from src.services.tte_service import TTEService

FIXTURE = Path(__file__).parent / "fixtures" / "carolina_liver_line_ir.json"

LIVER_LINE = (
    "1. Active liver disease or impaired hepatic function, defined by serum levels "
    "of either ALT (SGPT), AST (SGOT), or alkaline phosphatase above 3 x upper "
    "limit of normal (ULN) as determined at visit 1a"
)


def _service() -> TTEService:
    """A bare TTEService; the criterion builders touch no I/O and no agent."""
    svc = TTEService.__new__(TTEService)
    svc._store = MagicMock()
    return svc


def _ir_item(**kwargs):
    """An IR criterion stand-in carrying only the attributes the builder reads."""
    defaults = dict(
        name="",
        domain="Measurement",
        entity_text="",
        source_text=None,
        value_constraint=None,
        window=None,
        sub_criteria=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _load_run(tag: str) -> list:
    """The recorded exclusion rules of one cached run, as IR-shaped objects."""
    from src.models.ir import Criteria

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        Criteria.model_validate(rule)
        for rule in data["runs"][tag]["exclusionRules"]
    ]


# ---------------------------------------------------------------------------
# One authoritative home for the key
# ---------------------------------------------------------------------------


class TestKeyHasOneHome:
    def test_constant_is_the_key_the_model_declares(self):
        assert CRITERION_PROTOCOL_LINE_KEY in Criterion.model_fields

    def test_key_is_not_retyped_as_a_literal_outside_its_home(self):
        """The producer imports the constant instead of spelling the key again.

        ``DROPPED_CRITERIA_KEY`` and ``CRITERION_CONCEPT_SET_REFS_KEY`` are spelled
        once each in ``circe_lint.py`` for this reason; a second literal is how a
        renamed key silently half-lands.
        """
        producer = Path("src/services/tte_service.py").read_text(encoding="utf-8")
        assert f'"{CRITERION_PROTOCOL_LINE_KEY}"' not in producer
        assert f"'{CRITERION_PROTOCOL_LINE_KEY}'" not in producer
        assert "CRITERION_PROTOCOL_LINE_KEY" in producer


# ---------------------------------------------------------------------------
# The stamp reaches the store row
# ---------------------------------------------------------------------------


class TestCriterionCarriesItsProtocolLine:
    def test_stamps_the_verbatim_line_the_ir_recorded(self):
        svc = _service()
        item = _ir_item(name="ALT", entity_text="Alanine aminotransferase", source_text=LIVER_LINE)

        row = svc._criterion_dict_from_ir_item(item, 1, "ALT")

        assert row[CRITERION_PROTOCOL_LINE_KEY] == LIVER_LINE

    def test_line_is_distinct_from_source_text(self):
        """``sourceText`` carries the entity, not the line.

        ``_criterion_dict_from_ir_item`` assigns ``source_text = entity_text``, so
        the store's ``sourceText`` column has never held the protocol line -- and
        several consumers read it as a concept-mapping seed. The new field is the
        line; the old one keeps its meaning.
        """
        svc = _service()
        item = _ir_item(name="ALT", entity_text="Alanine aminotransferase", source_text=LIVER_LINE)

        row = svc._criterion_dict_from_ir_item(item, 1, "ALT")

        assert row["sourceText"] == "Alanine aminotransferase"
        assert row[CRITERION_PROTOCOL_LINE_KEY] == LIVER_LINE

    def test_empty_when_the_ir_recorded_no_line(self):
        """A study extracted before ``source_text`` existed loads unchanged.

        ``ir.py`` documents ``source_text`` as Optional for exactly this; an absent
        line is an absent line, never a crash and never a fabricated one.
        """
        svc = _service()
        row = svc._criterion_dict_from_ir_item(_ir_item(name="ALT", entity_text="ALT"), 1, "ALT")

        assert row[CRITERION_PROTOCOL_LINE_KEY] == ""

    def test_absent_attribute_is_tolerated(self):
        """Callers that build IR stand-ins without the attribute keep working."""
        svc = _service()
        item = SimpleNamespace(name="ALT", domain="Measurement", entity_text="ALT",
                               value_constraint=None, window=None)

        row = svc._criterion_dict_from_ir_item(item, 1, "ALT")

        assert row[CRITERION_PROTOCOL_LINE_KEY] == ""

    def test_group_label_and_members_each_carry_their_line(self):
        svc = _service()
        member = _ir_item(
            name="ALT", entity_text="Alanine aminotransferase", source_text=LIVER_LINE
        )
        group = _ir_item(
            name="Liver", entity_text="Liver", source_text=LIVER_LINE, sub_criteria=[member]
        )

        rows = svc._criteria_from_ir([group])

        assert len(rows) == 2
        assert {r[CRITERION_PROTOCOL_LINE_KEY] for r in rows} == {LIVER_LINE}

    def test_survives_the_store_model_round_trip(self):
        """The store persists via ``TTEStudy.model_validate(...).model_dump()``;
        a key that does not survive that hop never reaches ``studies.json``."""
        svc = _service()
        item = _ir_item(name="ALT", entity_text="Alanine aminotransferase", source_text=LIVER_LINE)

        row = svc._criterion_dict_from_ir_item(item, 1, "ALT")
        dumped = Criterion.model_validate(row).model_dump()

        assert dumped[CRITERION_PROTOCOL_LINE_KEY] == LIVER_LINE


# ---------------------------------------------------------------------------
# Additive: nothing else about the row changes
# ---------------------------------------------------------------------------


class TestAdditive:
    def test_every_pre_existing_key_is_unchanged(self):
        svc = _service()
        item = _ir_item(
            name="ALT",
            entity_text="Alanine aminotransferase",
            source_text=LIVER_LINE,
            value_constraint=SimpleNamespace(op="gt", value=3.0, unit_text="x ULN",
                                             reference_bound="uln", unit_concept_id=None),
            window=SimpleNamespace(start=-180, end=0),
        )

        row = svc._criterion_dict_from_ir_item(item, 7, "ALT")

        assert row["id"] == 7
        assert row["description"] == "ALT"
        assert row["domain"] == "Measurement"
        assert row["sourceText"] == "Alanine aminotransferase"
        assert row["window"] == {"start": -180, "end": 0}
        assert row["logicType"] == "PRESENCE"
        assert row["conceptSetId"] is None
        assert row["conceptSetName"] == ""
        assert row["groupId"] is None
        assert row["groupType"] == "ALL"
        assert row["valueConstraint"] == {
            "op": "gt", "value": 3.0, "unitText": "x ULN",
            "referenceBound": "uln", "unitConceptId": None,
        }

    def test_the_only_new_key_is_the_protocol_line(self):
        svc = _service()
        row = svc._criterion_dict_from_ir_item(_ir_item(name="ALT", entity_text="ALT"), 1, "ALT")

        assert set(row) - {
            "id", "description", "domain", "valueConstraint", "sourceText", "window",
            "logicType", "conceptSetId", "conceptSetName", "groupId", "groupType",
        } == {CRITERION_PROTOCOL_LINE_KEY}

    def test_mappable_is_unaffected(self):
        """``mappable`` is computed from description/domain/isGroupLabel; a
        provenance stamp must not move it."""
        svc = _service()
        row = svc._criterion_dict_from_ir_item(
            _ir_item(name="ALT", entity_text="ALT", source_text=LIVER_LINE), 1, "ALT"
        )

        assert Criterion.model_validate(row).mappable is True


# ---------------------------------------------------------------------------
# Provenance survives the decomposition hop
# ---------------------------------------------------------------------------


class TestDecomposedMembersKeepTheLine:
    def test_planner_sub_criteria_inherit_the_parents_line(self):
        """The planner builds each sub-criterion from scratch and inherited
        ``logic_type`` and ``window`` but not ``source_text``, so every member of a
        decomposed group reached the store with no line at all -- which is exactly
        the group where a cardinality would be worth reading. CAROLINA's stored
        ``Coagulopathy (e.g., elevated INR)`` and ``Elevated Bilirubin`` members are
        this shape: neither appears in any recorded Agent 1 cache.

        This carries provenance across the hop. It changes nothing the decomposer
        decides -- not what is decomposed, not the prompt, not any member's own
        ``value_constraint``, which REQ-004/REQ-005 require be grounded in the
        member's own text.
        """
        from src.models.ir import Criteria

        parent = Criteria(
            name="Acute liver disease or impaired hepatic function",
            domain="Condition",
            entity_text="Acute liver disease or impaired hepatic function",
            source_text="27. acute liver disease or impaired hepatic function",
            logic_type="ABSENCE",
        )
        planner = _planner_with_response(
            {
                "decompose": True,
                "sub_criteria": [
                    {"name": "Acute Liver Disease", "entity_text": "Acute hepatitis",
                     "domain": "Condition"},
                    {"name": "Impaired Hepatic Function", "entity_text": "Coagulopathy",
                     "domain": "Measurement"},
                ],
            }
        )

        result = planner._decompose_criterion(parent)

        assert len(result.sub_criteria) == 2
        assert all(
            sc.source_text == "27. acute liver disease or impaired hepatic function"
            for sc in result.sub_criteria
        )

    def test_decomposed_members_reach_the_store_row_with_the_line(self):
        from src.models.ir import Criteria

        parent = Criteria(
            name="Acute liver disease or impaired hepatic function",
            domain="Condition",
            entity_text="Acute liver disease or impaired hepatic function",
            source_text="27. acute liver disease or impaired hepatic function",
            logic_type="ABSENCE",
        )
        planner = _planner_with_response(
            {
                "decompose": True,
                "sub_criteria": [
                    {"name": "Impaired Hepatic Function", "entity_text": "Elevated Bilirubin",
                     "domain": "Measurement"},
                ],
            }
        )
        decomposed = planner._decompose_criterion(parent)

        rows = _service()._criteria_from_ir([decomposed])

        assert [r[CRITERION_PROTOCOL_LINE_KEY] for r in rows] == [
            "27. acute liver disease or impaired hepatic function",
            "27. acute liver disease or impaired hepatic function",
        ]


def _planner_with_response(payload: dict):
    """A CriteriaPlanner whose single LLM call returns ``payload``. No network."""
    from src.agents.planner.decomposer import CriteriaPlanner

    planner = CriteriaPlanner.__new__(CriteriaPlanner)
    planner.llm = MagicMock()
    planner.llm.invoke.return_value = SimpleNamespace(content=json.dumps(payload))
    return planner


# ---------------------------------------------------------------------------
# The recorded CAROLINA case: cardinality becomes readable
# ---------------------------------------------------------------------------


class TestCollapseBecomesReadableOnTheRealCase:
    """Not a collapse detector. These assert only that the evidence a detector
    would need is now present in the store row, and was not before."""

    def test_fixture_pins_the_two_recorded_runs(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert data["nctId"] == "NCT01243424"
        assert set(data["runs"]) == {"fanout_3", "collapsed_1"}

    @pytest.mark.parametrize("tag,expected", [("fanout_3", 3), ("collapsed_1", 1)])
    def test_the_same_line_yields_a_countable_number_of_criteria(self, tag, expected):
        rows = _service()._criteria_from_ir(_load_run(tag))

        from_liver_line = [r for r in rows if r[CRITERION_PROTOCOL_LINE_KEY] == LIVER_LINE]

        assert len(from_liver_line) == expected

    def test_the_two_runs_disagree_on_one_byte_identical_line(self):
        """The collapse, stated as a cardinality over a shared key -- no clinical
        inference, no analyte list, no threshold reasoning."""
        svc = _service()
        counts = {}
        for tag in ("fanout_3", "collapsed_1"):
            rows = svc._criteria_from_ir(_load_run(tag))
            counts[tag] = sum(1 for r in rows if r[CRITERION_PROTOCOL_LINE_KEY] == LIVER_LINE)

        assert counts["fanout_3"] != counts["collapsed_1"]

    def test_the_collapsed_run_loses_two_analytes_without_a_trace_in_any_other_field(self):
        """Why the line has to be the key: in the collapsed run the words
        ``Aspartate`` and ``Alkaline`` survive in no field of any row, so grouping
        by anything the store already carried cannot recover the cardinality."""
        rows = _service()._criteria_from_ir(_load_run("collapsed_1"))

        blob = " ".join(
            str(v) for r in rows for k, v in r.items() if k != CRITERION_PROTOCOL_LINE_KEY
        )
        assert "Aspartate" not in blob
        assert "Alkaline" not in blob
        assert any(r[CRITERION_PROTOCOL_LINE_KEY] == LIVER_LINE for r in rows)

    def test_a_threshold_can_be_checked_against_the_line_that_is_supposed_to_carry_it(self):
        """The second consequence, made checkable: ``3 x ULN`` is written in the
        ``1.`` line and written nowhere in the ``27.`` line. A criterion carrying
        that bound under the ``27.`` line is the model's own; under the ``1.`` line
        it is a reading. Only the stamp tells them apart."""
        rows = _service()._criteria_from_ir(_load_run("fanout_3"))

        bounded = [r for r in rows if r["valueConstraint"] is not None]
        assert bounded, "the recorded run carries the 3x ULN bound"
        for row in bounded:
            line = row[CRITERION_PROTOCOL_LINE_KEY]
            assert "3 x upper limit of normal" in line
