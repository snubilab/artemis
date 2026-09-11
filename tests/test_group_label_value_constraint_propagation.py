"""A group label's threshold must reach its members, but only when it is unit-free.

Measured on ``tmp/tte_cold6_20260907b/studies.json`` (2026-09-07 cold run): three
exclusion groups carry a ``valueConstraint`` on the GROUP LABEL and on no member.
The label row is ``isGroupLabel: true``, the seeded builder refuses it outright
(``_skippedCriteria`` reason ``group-label``), so the only row holding the number
never reaches a cohort and the threshold is silently lost::

    study  8 exclusion  ALL/ABSENCE  "Uncontrolled hyperglycemia"  {gt 240.0 mg/dL}
                                     members: Elevated Fasting Plasma Glucose /
                                              Elevated Random Plasma Glucose / Elevated HbA1c
    study 10 exclusion  ALL/ABSENCE  "Active liver disease or impaired hepatic
                                      function"                    {gt 3.0 "x ULN"}
                                     members: ALT / AST / ALP
    study 10 exclusion  ALL/ABSENCE  "Uncontrolled hyperglycaemia" {gt 240.0 mg/dl}
                                     members: Elevated HbA1c / Elevated Fasting Glucose /
                                              Elevated Random Glucose

Blind propagation is NOT the fix. ``> 240 mg/dL`` copied onto "Elevated HbA1c"
builds a MeasurementOccurrence rule matching zero rows -- HbA1c is reported in %
or mmol/mol and never in mg/dL -- and inside an ABSENCE exclusion that converts
today's visible over-exclusion into a silent zero-match.
``refuse_domain_contradiction`` cannot catch it: both sides are Measurement.

Blanket refusal is not the fix either. ``> 240 mg/dL`` is a perfectly good bound
for the Fasting and Random Plasma Glucose members sharing HbA1c's group, so
refusing all three loses two real filters to protect against one.

Two questions decide it, in order, and both are lookups rather than judgements:

1. Is the bound unit-free? A reference-relative bound is analyte-independent --
   "3 times the upper limit of normal" is meaningful for ALT, AST and ALP alike --
   and reaches every member. That predicate is already encoded in
   ``build_measurement_value_filter``: reference-relative emits ``RangeHighRatio``
   / ``RangeLowRatio``, absolute emits ``ValueAsNumber``, so it is asked of the
   shared builder rather than re-derived.
2. Otherwise: is the member's analyte conventionally reported in the bound's unit?
   ``_ANALYTE_CONVENTIONAL_UNITS`` answers from a table keyed on the same UCUM
   concept_ids the unit vocabulary already uses. An analyte the table does not
   carry refuses; it never falls through to propagate.

The unsafe case must not become silent in the other direction either: refusing to
propagate is recorded, through each builder's existing refusal channel.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.value_constraint import build_measurement_value_filter

REPO_ROOT = Path(__file__).resolve().parent.parent


# `tests/test_parser_paper_status.py` overwrites `src.models.ir.Criteria` and
# `.ValueConstraint` with MagicMocks at import time and never puts them back --
# its teardown only drops modules it *injected*, and it injects nothing when the
# real module is already imported. Importing those classes here would therefore
# make this suite pass or fail on collection order. Both builders reach the IR
# through plain attribute access (`getattr` in tte_service, `rule.x` in the
# assembler) and `value_constraint._field` accepts any object or mapping, so
# these stand-ins are the contract the code actually consumes.
# `test_should_match_the_real_ir_field_names` pins them to the real model.


@dataclass
class _VC:
    """Stand-in for `src.models.ir.ValueConstraint`."""

    op: str
    value: float
    #: Upper bound of an `op="bt"` inclusive range; `value` is the lower one.
    value_high: float | None = None
    reference_bound: str = "absolute"
    unit_text: str | None = None
    unit_concept_id: int | None = None


@dataclass
class _Crit:
    """Stand-in for `src.models.ir.Criteria`, limited to what the builders read."""

    name: str
    domain: str
    entity_text: str | None = None
    source_text: str | None = None
    concept_set_id: int | None = None
    logic_type: str = "PRESENCE"
    window: Any = None
    value_constraint: _VC | None = None
    sub_criteria: list["_Crit"] = field(default_factory=list)
    group_type: str = "ALL"
    conditional: bool = False


def _real_ir_module():
    """Load `src/models/ir.py` under a private name, bypassing the mangled entry.

    Never touches `sys.modules["src.models.ir"]`, so it neither depends on nor
    repairs the pollution described above.
    """
    spec = importlib.util.spec_from_file_location(
        "_ir_for_field_drift_check", REPO_ROOT / "src" / "models" / "ir.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# ---------------------------------------------------------------------------
# Fixtures transcribed verbatim from the 2026-09-07 store.
# ---------------------------------------------------------------------------

# study 10 exclusion group: the SAFE case. `referenceBound` is "absolute" in the
# store and the bound lives in `unitText` -- `split_reference_bound` recovers it,
# which is why the predicate has to ask the builder rather than read the field.
LIVER_LABEL_CONSTRAINT = _VC(op="gt", value=3.0, unit_text="x ULN")
LIVER_MEMBER_NAMES = (
    "Alanine aminotransferase level",
    "Aspartate aminotransferase level",
    "Alkaline phosphatase level",
)

# study 8 exclusion group: the UNSAFE case. mg/dL is meaningful for plasma glucose
# and meaningless for HbA1c, which is a member of this very group.
HYPERGLYCEMIA_LABEL_CONSTRAINT = _VC(op="gt", value=240.0, unit_text="mg/dL")
HYPERGLYCEMIA_MEMBER_NAMES = (
    "Elevated Fasting Plasma Glucose",
    "Elevated Random Plasma Glucose",
    "Elevated HbA1c",
)


def _ir_group(label: str, constraint: _VC, member_names: tuple[str, ...]) -> _Crit:
    """One IR exclusion group: a labelled parent whose members carry no constraint."""
    return _Crit(
        name=label,
        domain="Measurement",
        entity_text=label,
        logic_type="ABSENCE",
        group_type="ALL",
        value_constraint=constraint,
        sub_criteria=[
            _Crit(
                name=name,
                domain="Measurement",
                entity_text=name,
                logic_type="ABSENCE",
                value_constraint=None,
            )
            for name in member_names
        ],
    )


def _liver_group() -> _Crit:
    return _ir_group(
        "Active liver disease or impaired hepatic function",
        LIVER_LABEL_CONSTRAINT,
        LIVER_MEMBER_NAMES,
    )


def _hyperglycemia_group() -> _Crit:
    return _ir_group(
        "Uncontrolled hyperglycemia",
        HYPERGLYCEMIA_LABEL_CONSTRAINT,
        HYPERGLYCEMIA_MEMBER_NAMES,
    )


# ---------------------------------------------------------------------------
# Builder A -- src/services/tte_service.py `_criteria_from_ir` (store rows)
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    """A bare TTEService; `_criteria_from_ir` touches no I/O or agent."""
    from src.services.tte_service import TTEService

    return TTEService.__new__(TTEService)


def _member_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not row.get("isGroupLabel")]


def _label_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [row for row in rows if row.get("isGroupLabel")]
    assert len(labels) == 1, f"expected exactly one group label, got {len(labels)}"
    return labels[0]


class TestStoreRowsInheritOnlyUnitFreeThresholds:
    def test_should_give_every_member_the_ratio_bound_when_group_label_is_reference_relative(
        self, service
    ):
        rows = service._criteria_from_ir([_liver_group()])
        members = _member_rows(rows)

        assert [row["description"] for row in members] == list(LIVER_MEMBER_NAMES)
        for row in members:
            assert row["valueConstraint"] is not None, (
                f"{row['description']!r} lost the group label's '> 3x ULN' threshold; "
                f"the label row is refused as isGroupLabel, so nothing else carries it"
            )
            assert build_measurement_value_filter(row["valueConstraint"]) == {
                "RangeHighRatio": {"Value": 3.0, "Op": "gt"}
            }

    def test_should_split_an_absolute_bound_by_the_analyte_it_can_measure(self, service):
        rows = service._criteria_from_ir([_hyperglycemia_group()])
        members = _member_rows(rows)

        assert [row["description"] for row in members] == list(HYPERGLYCEMIA_MEMBER_NAMES)
        by_name = {row["description"]: row["valueConstraint"] for row in members}
        for glucose in ("Elevated Fasting Plasma Glucose", "Elevated Random Plasma Glucose"):
            assert build_measurement_value_filter(by_name[glucose])["ValueAsNumber"] == {
                "Value": 240.0,
                "Op": "gt",
            }, f"{glucose!r} lost a threshold that mg/dL measures perfectly well"
        assert by_name["Elevated HbA1c"] is None, (
            "HbA1c was given the label's absolute '> 240 mg/dL'. It is reported in % "
            "or mmol/mol, so inside an ABSENCE exclusion that rule matches zero rows "
            "and the exclusion silently stops applying"
        )

    def test_should_not_overwrite_a_member_that_carries_its_own_threshold(self, service):
        group = _liver_group()
        group.sub_criteria[0].value_constraint = _VC(op="gt", value=5.0, unit_text="x ULN")

        members = _member_rows(service._criteria_from_ir([group]))

        assert members[0]["valueConstraint"]["value"] == 5.0
        assert members[1]["valueConstraint"]["value"] == 3.0


# ---------------------------------------------------------------------------
# Visibility -- the refusal must not itself be silent.
# ---------------------------------------------------------------------------


def _eligibility_shell(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "targetCohortName": "T2DM cohort",
        "inclusionCriteria": [],
        "exclusionCriteria": rows,
    }


@pytest.fixture
def seeded_service():
    """A TTEService with the expensive Agent2 / vector-search methods stubbed out."""
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = MagicMock(
        side_effect=lambda name, expected_domain=None, workflow=None, **kw: {
            "name": name,
            "domain": "Measurement",
            "expression": {"items": [{"concept": {"CONCEPT_ID": 99999}}]},
        }
    )
    svc._build_seeded_eligibility_rule = MagicMock(
        side_effect=lambda **kw: {
            "conceptSet": {
                "id": kw["codeset_id"],
                "name": kw["criterion"].get("description", "rule"),
                "expression": {"items": []},
            },
            "rule": {
                "name": kw["criterion"].get("description", "rule"),
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [{
                        "Criteria": {"MeasurementOccurrence": {"CodesetId": kw["codeset_id"]}},
                        "Occurrence": {"Type": 0, "Count": 0},
                    }],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            },
        }
    )
    svc._seeded_primary_criteria_key = MagicMock(return_value="ConditionOccurrence")
    svc._patch_codeset_id_in_rule = MagicMock()
    return svc


def _skip_reasons(result: dict[str, Any], label: str) -> list[str]:
    return [r["reason"] for r in result["_skippedCriteria"] if r["label"] == label]


class TestRefusedPropagationIsRecorded:
    def test_should_record_a_distinct_skip_reason_when_an_absolute_threshold_is_stranded(
        self, service, seeded_service
    ):
        from src.services.value_constraint import STRANDED_GROUP_CONSTRAINT_REASON

        rows = service._criteria_from_ir([_hyperglycemia_group()])
        result = seeded_service._build_seeded_target_circe(_eligibility_shell(rows))

        assert _skip_reasons(result, "Uncontrolled hyperglycemia") == [
            STRANDED_GROUP_CONSTRAINT_REASON
        ], (
            "the label carrying '> 240 mg/dL' was refused under the generic "
            "'group-label' reason, which is indistinguishable from a label that "
            "carried no threshold at all -- the lost number stays invisible"
        )
        assert (
            result["_generationCensus"]["skippedByReason"][STRANDED_GROUP_CONSTRAINT_REASON]
            == 1
        )

    def test_should_keep_the_plain_group_label_reason_when_the_threshold_was_propagated(
        self, service, seeded_service
    ):
        rows = service._criteria_from_ir([_liver_group()])
        result = seeded_service._build_seeded_target_circe(_eligibility_shell(rows))

        assert _skip_reasons(
            result, "Active liver disease or impaired hepatic function"
        ) == ["group-label"], (
            "nothing was lost here -- every member inherited the ratio bound -- so "
            "flagging it would make the stranded reason meaningless"
        )


# ---------------------------------------------------------------------------
# Builder B -- src/agents/agent3/assembler.py composite branch (Circe directly)
# ---------------------------------------------------------------------------


@pytest.fixture
def assembler():
    from src.agents.agent3.assembler import CohortAssembler

    return CohortAssembler.__new__(CohortAssembler)


def _member_criteria(rule: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        next(iter(entry["Criteria"].values()))
        for entry in rule["expression"]["CriteriaList"]
    ]


class TestAssemblerInheritsOnlyUnitFreeThresholds:
    def test_should_emit_range_high_ratio_for_every_member_of_a_reference_relative_group(
        self, assembler
    ):
        rule = assembler._build_inclusion_rule(_liver_group(), [], 0, is_exclusion=True)

        emitted = _member_criteria(rule)
        assert len(emitted) == len(LIVER_MEMBER_NAMES)
        for content in emitted:
            assert content.get("RangeHighRatio") == {"Value": 3.0, "Op": "gt"}, (
                "the composite branch reads only sc.value_constraint, so the group "
                "label's '> 3x ULN' never reaches ALT/AST/ALP and each emits an "
                "unfiltered MeasurementOccurrence"
            )

    def test_should_emit_only_the_members_an_absolute_bound_can_measure(self, assembler):
        """Two members take '> 240 mg/dL'; HbA1c is dropped rather than emitted bare.

        The emitted count is pinned BEFORE the bodies are inspected. The previous
        version of this test looped over `_member_criteria(rule)` asserting an
        absence, and once every member started being dropped the loop iterated zero
        times -- it passed while proving nothing. An emptiness assertion inside a
        loop is only a real assertion when the loop's length is pinned outside it.
        """
        rule = assembler._build_inclusion_rule(
            _hyperglycemia_group(), [], 0, is_exclusion=True
        )

        emitted = _member_criteria(rule)
        assert len(emitted) == 2, (
            f"expected the two plasma-glucose members to emit and HbA1c to be "
            f"dropped; got {len(emitted)}: {emitted}"
        )
        for content in emitted:
            assert content["ValueAsNumber"] == {"Value": 240.0, "Op": "gt"}
            assert [u["CONCEPT_ID"] for u in content["Unit"]] == [8840]
            assert "RangeHighRatio" not in content


# ---------------------------------------------------------------------------
# One implementation, two builders.
# ---------------------------------------------------------------------------


class TestBothBuildersShareOneResolver:
    """A fix applied to one builder and not the other is this tree's repeat defect."""

    def test_should_route_both_builders_through_resolve_group_member_constraint(
        self, service, assembler, monkeypatch
    ):
        import src.agents.agent3.assembler as assembler_mod
        import src.services.tte_service as tte_service_mod
        from src.services import value_constraint as vc_mod

        seen: list[str] = []

        def _spy(caller: str):
            # *args/**kwargs, not a fixed pair: the resolver takes the member's
            # analyte as a keyword, and a spy pinned to the old arity would fail as
            # a TypeError that reads like a defect in the builder it wraps.
            def _wrapped(*args, **kwargs):
                seen.append(caller)
                return vc_mod.resolve_group_member_constraint(*args, **kwargs)

            return _wrapped

        monkeypatch.setattr(
            tte_service_mod, "resolve_group_member_constraint", _spy("tte_service")
        )
        monkeypatch.setattr(
            assembler_mod, "resolve_group_member_constraint", _spy("assembler")
        )

        service._criteria_from_ir([_liver_group()])
        assembler._build_inclusion_rule(_liver_group(), [], 0, is_exclusion=True)

        assert set(seen) == {"tte_service", "assembler"}


class TestTheBoundsKindDecidesBeforeTheAnalyteIsConsulted:
    """With no analyte named, only the bound's kind decides -- and absolute refuses.

    This is the fallback every caller inherits when it cannot say what the member
    measures, including `scripts/verify_circe_delivery.py`, which asks the resolver
    the question with the member left out. It is the pre-analyte behaviour, kept
    verbatim: the analyte table narrows the refusal, it never widens what is emitted.

    There is still no per-trial and no per-NCT branch. The analyte is consulted only
    through `_ANALYTE_CONVENTIONAL_UNITS`, which is a units-of-measure table.
    """

    @pytest.mark.parametrize(
        "constraint,expected_propagation",
        [
            (_VC(op="gt", value=3.0, unit_text="x ULN"), True),
            (_VC(op="gt", value=3.0, reference_bound="uln"), True),
            (_VC(op="lt", value=0.8, reference_bound="lln"), True),
            (_VC(op="gt", value=240.0, unit_text="mg/dL"), False),
            (_VC(op="gt", value=7.0, unit_text="%"), False),
            (_VC(op="gt", value=1.5, unit_text=None), False),
        ],
    )
    def test_should_propagate_only_when_the_bound_is_reference_relative(
        self, constraint, expected_propagation
    ):
        from src.services.value_constraint import resolve_group_member_constraint

        resolution = resolve_group_member_constraint(constraint, None)

        assert resolution.propagated is expected_propagation
        assert (resolution.constraint is constraint) is expected_propagation
        assert (resolution.refusal_reason is None) is expected_propagation


class TestAnAbsoluteBoundGoesToTheAnalytesMeasuredInItsUnit:
    """The table lookup, exercised directly. Every "no" is a refusal with a reason."""

    ABSOLUTE_MG_DL = _VC(op="gt", value=240.0, unit_text="mg/dL")

    @pytest.mark.parametrize(
        "analyte",
        [
            "Fasting Plasma Glucose",
            "Random Plasma Glucose",
            "Elevated Fasting Glucose",
            "blood glucose",
        ],
        ids=["fpg", "rpg", "elevated-fasting", "lowercase"],
    )
    def test_should_hand_the_bound_to_an_analyte_reported_in_that_unit(self, analyte):
        from src.services.value_constraint import resolve_group_member_constraint

        resolution = resolve_group_member_constraint(
            self.ABSOLUTE_MG_DL, None, member_analyte=analyte
        )

        assert resolution.propagated is True
        assert resolution.constraint is self.ABSOLUTE_MG_DL
        assert resolution.refusal_reason is None

    @pytest.mark.parametrize(
        "analyte",
        ["Hemoglobin A1c", "Elevated HbA1c", "Glycosylated haemoglobin", "HbA1c"],
        ids=["hemoglobin-a1c", "elevated-hba1c", "glycosylated", "abbreviation"],
    )
    def test_should_refuse_an_analyte_reported_in_another_unit(self, analyte):
        """The whole point of the table: mg/dL on HbA1c matches zero rows, and inside
        an ABSENCE exclusion a rule matching zero rows stops excluding anybody."""
        from src.services.value_constraint import (
            STRANDED_GROUP_CONSTRAINT_REASON,
            resolve_group_member_constraint,
        )

        resolution = resolve_group_member_constraint(
            self.ABSOLUTE_MG_DL, None, member_analyte=analyte
        )

        assert resolution.propagated is False
        assert resolution.constraint is None
        assert resolution.refusal_reason == STRANDED_GROUP_CONSTRAINT_REASON
        assert "% (percent)" in resolution.refusal_explanation
        assert "mg/dL" in resolution.refusal_explanation

    def test_should_not_let_the_haemoglobin_row_capture_hemoglobin_a1c(self):
        """The trap the table sets for itself: "Hemoglobin A1c" contains "hemoglobin",
        whose row is g/dL. Resolving to it would hand a g/dL bound to HbA1c -- a wrong
        propagation, which is the silent direction. Longest-key-wins is what prevents
        it, so both directions are pinned here."""
        from src.services.value_constraint import resolve_group_member_constraint

        g_per_dl = _VC(op="lt", value=10.0, unit_text="g/dL")

        assert resolve_group_member_constraint(
            g_per_dl, None, member_analyte="Haemoglobin"
        ).propagated is True
        assert resolve_group_member_constraint(
            g_per_dl, None, member_analyte="Hemoglobin A1c"
        ).propagated is False

    def test_should_refuse_an_analyte_the_table_does_not_carry(self):
        """Never guess and never fall through: an unknown analyte is refused, and the
        message says it is the TABLE that is short, not the protocol."""
        from src.services.value_constraint import (
            STRANDED_GROUP_CONSTRAINT_REASON,
            resolve_group_member_constraint,
        )

        resolution = resolve_group_member_constraint(
            self.ABSOLUTE_MG_DL, None, member_analyte="Microalbuminuria or proteinuria"
        )

        assert resolution.propagated is False
        assert resolution.constraint is None
        assert resolution.refusal_reason == STRANDED_GROUP_CONSTRAINT_REASON
        assert "not in the analyte/unit table" in resolution.refusal_explanation

    def test_should_refuse_a_text_that_names_two_analytes_with_different_units(self):
        """One bound cannot filter two analytes measured in two units."""
        from src.services.value_constraint import resolve_group_member_constraint

        resolution = resolve_group_member_constraint(
            self.ABSOLUTE_MG_DL, None, member_analyte="Haemoglobin and platelet count"
        )

        assert resolution.propagated is False
        assert "not in the analyte/unit table" in resolution.refusal_explanation

    def test_should_refuse_when_the_labels_own_unit_does_not_resolve(self):
        """`normalize_unit` returns None rather than a nearest concept (ADR-031 D5), so
        there is nothing to check the analyte against and nothing may be handed down."""
        from src.services.value_constraint import resolve_group_member_constraint

        resolution = resolve_group_member_constraint(
            _VC(op="gt", value=110.0, unit_text="bpm"), None, member_analyte="Glucose"
        )

        assert resolution.propagated is False
        assert "resolves to no UCUM unit" in resolution.refusal_explanation

    def test_should_still_not_overwrite_a_member_that_carries_its_own_threshold(self):
        """The analyte table decides what an INHERITED bound may measure. It never
        gets a vote on a threshold the decomposer already grounded in the member's own
        source text -- even one the table would call incompatible."""
        from src.services.value_constraint import resolve_group_member_constraint

        own = _VC(op="gte", value=6.5, unit_text="%")

        resolution = resolve_group_member_constraint(
            self.ABSOLUTE_MG_DL, own, member_analyte="Hemoglobin A1c"
        )

        assert resolution.constraint is own
        assert resolution.propagated is False
        assert resolution.refusal_reason is None

    def test_should_read_the_unit_the_same_way_the_emitted_filter_does(self):
        """One derivation, not two. If the check and the emitted `Unit` disagreed about
        which concept a bound is in, a member could be approved against one unit and
        filtered by another -- and nothing downstream would notice."""
        from src.services.value_constraint import (
            absolute_unit_concept_id,
            build_measurement_value_filter,
        )

        for spelling in ("mg/dL", "mg/dl", "mmol/L", "%", "[U]/L"):
            constraint = _VC(op="gt", value=1.0, unit_text=spelling)
            emitted = build_measurement_value_filter(constraint)["Unit"]
            assert [u["CONCEPT_ID"] for u in emitted] == [
                absolute_unit_concept_id(constraint)
            ], spelling


class TestRangeOperand:
    """An inclusive range is a real threshold that Circe has always been able to carry."""

    def test_should_emit_value_and_extent_when_the_constraint_is_a_range(self):
        """Pinned against the TROY v1.1 gold for the very criterion this repairs.

        ``data/gold/CAROLINA/[TROY v1.1] Linagliptin (CAROLINA).json`` encodes
        "eGFR 30-59" as ``ValueAsNumber {Value: 30, Extent: 59, Op: "bt"}``. `Value`
        is the LOW bound there, which is the half a hand-written emitter gets wrong.
        """
        emitted = build_measurement_value_filter(
            _VC(op="bt", value=30.0, value_high=59.0, unit_text="mL/min/1.73 m2")
        )

        assert emitted["ValueAsNumber"] == {"Value": 30.0, "Extent": 59.0, "Op": "bt"}
        assert [u["CONCEPT_ID"] for u in emitted["Unit"]] == [720870]

    def test_should_emit_nothing_when_a_range_reaches_circe_without_its_upper_bound(self):
        """Half a range would emit ``{Value: 30, Op: "bt"}``, which Circe cannot complete."""
        assert build_measurement_value_filter(_VC(op="bt", value=30.0)) == {}

    def test_should_read_the_upper_bound_from_a_camel_case_store_row(self):
        """The TTE store writes `valueHigh`; the IR model writes `value_high`."""
        emitted = build_measurement_value_filter(
            {"op": "bt", "value": 6.5, "valueHigh": 8.5, "unitText": "%"}
        )

        assert emitted["ValueAsNumber"] == {"Value": 6.5, "Extent": 8.5, "Op": "bt"}


class TestStandInsMatchTheRealIR:
    """The stand-ins above are only honest while they carry the real field names."""

    def test_should_match_the_real_ir_field_names(self):
        import dataclasses

        ir = _real_ir_module()

        assert {f.name for f in dataclasses.fields(_VC)} == set(
            ir.ValueConstraint.model_fields
        )
        assert {f.name for f in dataclasses.fields(_Crit)} <= set(
            ir.Criteria.model_fields
        )

    def test_should_accept_the_real_value_constraint_model(self):
        from src.services.value_constraint import resolve_group_member_constraint

        ir = _real_ir_module()
        relative = ir.ValueConstraint(op="gt", value=3.0, unit_text="x ULN")
        absolute = ir.ValueConstraint(op="gt", value=240.0, unit_text="mg/dL")

        assert resolve_group_member_constraint(relative, None).propagated is True
        assert resolve_group_member_constraint(absolute, None).propagated is False
