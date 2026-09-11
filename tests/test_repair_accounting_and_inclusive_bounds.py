"""Two defects that share one shape: a criterion whose fate nothing records.

**Task A -- a departure with no record.** ``_repair_band_tiers`` drops a band that
restates one already in the run, and until now the only trace was a ``logger.info``.
The store's census (``_unmappedCriteria``, ``_skippedCriteria``, ``_droppedCriteria``)
is computed from the rows the repairs leave behind, so a criterion removed by a repair
reaches none of them: it is not refused, not skipped, not dropped, it simply is not
there. Measured on the real delivery, CAROLINA study 10 inclusion side: the
2026-09-11 store held 52 criteria including six Drug rows refused with a named reason;
the 2026-09-12 store, from the SAME IR cache and the same model, held 32 and no Drug
row, and the six appeared in no record anywhere.

The mechanism was not that the grouping deleted them. Nothing deleted them. The band
repairs demoted ``HbA1c 6.5 - 7.5% (SU/Glinide/Metformin combos)`` from a top-level
rule into an ANY group, and the Criteria Planner iterates top-level rules only
(``_decompose_criterion`` returns early on a criterion that already has
``sub_criteria``) -- so the protocol line naming the six drug regimens stopped being
decomposed and the six were never generated. A gate over departures alone would go
green on that, which is why the ledger records demotions too.

**Task B -- a boundary moved by a wrong negation.** ``<= X`` is ``NOT (> X)``. Agent 1
writes the upper half of a band as an ABSENCE rule carrying ``gte``, which is
``NOT (>= X)`` -- that is ``< X``, and it excludes a patient sitting exactly on the
bound. Measured over the 65 current-model IR caches, both cohorts, 1520 parsed
constraints: 116 of the 191 ABSENCE ``gte`` constraints sit at a value their own
protocol line states as inclusive. Seven are ``Age <= 85``, which as written excluded
85-year-olds from CAROLINA.

The fixture reloads ``src.models.ir`` and ``src.agents.agent1.parser`` for the reason
``tests/test_value_constraint_range_operand.py`` gives: another module installs a
``MagicMock`` over ``sys.modules["src.models.ir"]`` at import time and never restores
it, so an unguarded import asserts against a mock in a full-suite run.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MODULES = (
    "src.models.ir",
    "src.services.value_constraint",
    "src.agents.agent1.parser",
)

CACHE = Path("data/cache/agent1_ir")

#: The caches the 2026-09-12 delivery actually replayed, read from its own
#: ``output/site_gap/2026-09-12/reingest.log``. Using the delivered arm rather than a
#: fixture is the point: a repair has to be shown on the case that motivated it.
DELIVERED = {
    "ARISTOTLE": "NCT00412984_vllm_google_gemma-4-E4B-it_808fc9a4e83ca8db.json",
    "PLATO": "NCT00391872_vllm_google_gemma-4-E4B-it_17d77b5f03f09b73.json",
    "CAROLINA": "NCT01243424_vllm_google_gemma-4-E4B-it_ac7e953e86d338ee.json",
    "EMPA-REG": "NCT01131676_vllm_google_gemma-4-E4B-it_17eaf31c786b5abb.json",
    "CARMELINA": "NCT01897532_vllm_google_gemma-4-E4B-it_7ae74b822cdf141a.json",
    "LEADER": "NCT01179048_vllm_google_gemma-4-E4B-it_e833c06829935f34.json",
}

#: CAROLINA's `Age <= 85` arm. The delivered CAROLINA cache happens to encode the age
#: bound correctly; this one does not, and it is the arm the Age claim is measured on.
AGE_ARM = "NCT01243424_vllm_google_gemma-4-E4B-it_3f2b4ad72058fa31.json"


@pytest.fixture
def parser_module():
    saved = {name: sys.modules.get(name) for name in _MODULES}
    for name in _MODULES:
        sys.modules.pop(name, None)
    try:
        module = None
        for name in _MODULES:
            module = importlib.import_module(name)
        assert not isinstance(sys.modules["src.models.ir"].ValueConstraint, MagicMock)
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture
def models(parser_module):
    return sys.modules["src.models.ir"]


@pytest.fixture
def decomposer(parser_module):
    with patch.object(parser_module, "get_llm", return_value=MagicMock()):
        return parser_module.LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")


def _band(models, name, op, value, line, *, logic="PRESENCE", analyte="HbA1c"):
    return models.Criteria(
        name=name,
        domain="Measurement",
        entity_text=analyte,
        source_text=line,
        logic_type=logic,
        value_constraint=models.ValueConstraint(op=op, value=value, unit_text="%"),
    )


def _closed(models, name, lo, hi, line, *, analyte="HbA1c"):
    return models.Criteria(
        name=name,
        domain="Measurement",
        entity_text=analyte,
        source_text=line,
        logic_type="PRESENCE",
        value_constraint=models.ValueConstraint(
            op="bt", value=lo, value_high=hi, unit_text="%"
        ),
    )


# --------------------------------------------------------------------------- Task A


class TestTheGateFiresOnTheCaseThatMotivatedIt:
    def test_should_raise_when_a_repair_drops_a_criterion_without_recording_it(
        self, parser_module, models
    ):
        """The real pre-fix behaviour, reproduced: drop the restatement, record nothing.

        ``_repair_band_tiers`` called with no ledger keeps its own throwaway one, which
        is exactly what the code did before this change -- the drop happened and
        nothing outside a log line knew. The gate is then handed an EMPTY ledger, and
        has to refuse.
        """
        from src.agents.agent1.repair_accounting import (
            RepairLedger,
            UnaccountedDepartureError,
            assert_repairs_accounted,
        )

        line_a = "Elevated HbA1c: 6.5 - 8.5%, inclusive, if treatment naive"
        line_c = "HbA1c 6.5 - 8.5% while patient is treatment naive or treated"
        rules = [
            _closed(models, "HbA1c 6.5 - 8.5% (Naive/Metformin)", 6.5, 8.5, line_a),
            _closed(models, "HbA1c 6.5 - 7.5% (SU/Glinide)", 6.5, 7.5, line_a),
            _closed(models, "HbA1c 6.5 - 8.5% (Naive/Intolerant/Treated)", 6.5, 8.5, line_c),
        ]

        repaired = parser_module.LogicDecomposer._repair_band_tiers(list(rules))

        with pytest.raises(UnaccountedDepartureError) as raised:
            assert_repairs_accounted(rules, repaired, RepairLedger(), role="inclusion")
        message = str(raised.value)
        assert "HbA1c 6.5 - 8.5% (Naive/Intolerant/Treated)" in message
        # The protocol line is the load-bearing half of the message: it is the only
        # field that says what the cohort has stopped asking about.
        assert line_c[:40] in message

    def test_should_pass_when_the_same_repair_writes_to_the_ledger(
        self, parser_module, models
    ):
        from src.agents.agent1.repair_accounting import (
            RepairLedger,
            assert_repairs_accounted,
        )

        line_a = "Elevated HbA1c: 6.5 - 8.5%, inclusive, if treatment naive"
        line_c = "HbA1c 6.5 - 8.5% while patient is treatment naive or treated"
        rules = [
            _closed(models, "HbA1c 6.5 - 8.5% (Naive/Metformin)", 6.5, 8.5, line_a),
            _closed(models, "HbA1c 6.5 - 7.5% (SU/Glinide)", 6.5, 7.5, line_a),
            _closed(models, "HbA1c 6.5 - 8.5% (Naive/Intolerant/Treated)", 6.5, 8.5, line_c),
        ]
        ledger = RepairLedger()

        repaired = parser_module.LogicDecomposer._repair_band_tiers(list(rules), ledger)

        assert_repairs_accounted(rules, repaired, ledger, role="inclusion")
        dropped = [
            r for r in ledger.records() if r["action"] == "dropped-as-restatement"
        ]
        assert len(dropped) == 1
        assert dropped[0]["criterion"]["name"] == "HbA1c 6.5 - 8.5% (Naive/Intolerant/Treated)"
        assert dropped[0]["criterion"]["sourceText"] == line_c
        assert dropped[0]["survivor"]["name"] == "HbA1c 6.5 - 8.5% (Naive/Metformin)"

    def test_should_record_every_member_a_repair_demotes_into_a_group(
        self, parser_module, models
    ):
        """The demotion is the record that explains CAROLINA's six missing drug criteria.

        Nothing dropped them. The line they were decomposed FROM stopped being a
        top-level rule, and the planner visits nothing else.
        """
        from src.agents.agent1.repair_accounting import RepairLedger

        line = (
            "HbA1c 6.5 - 7.5% while patient is treated with sulphonylurea (SU) "
            "monotherapy, or glinide monotherapy"
        )
        rules = [
            _closed(models, "HbA1c 6.5 - 8.5%", 6.5, 8.5, "HbA1c 6.5 - 8.5%, inclusive"),
            _closed(models, "HbA1c 6.5 - 7.5% (SU/Glinide)", 6.5, 7.5, line),
        ]
        ledger = RepairLedger()

        parser_module.LogicDecomposer._repair_band_tiers(rules, ledger)

        demotions = [r for r in ledger.records() if r["disposition"] == "demotion"]
        assert {r["criterion"]["name"] for r in demotions} == {
            "HbA1c 6.5 - 8.5%",
            "HbA1c 6.5 - 7.5% (SU/Glinide)",
        }
        assert "no longer decomposed" in demotions[0]["reason"]
        assert demotions[1]["criterion"]["sourceText"] == line

    def test_should_fire_on_the_real_carolina_arm_repaired_the_way_head_repaired_it(
        self, decomposer, parser_module
    ):
        """The gate, run against the delivered arm with the repairs recording nothing.

        Calling the repairs without a ledger is byte-for-byte what the code did before
        this change, so this is the pre-fix pipeline on the pre-fix input. The
        criterion the gate names is the one the 2026-09-12 store lost with no record:
        CAROLINA's third HbA1c tier.
        """
        from src.agents.agent1.repair_accounting import (
            RepairLedger,
            UnaccountedDepartureError,
            assert_repairs_accounted,
        )

        path = CACHE / DELIVERED["CAROLINA"]
        if not path.exists():
            pytest.skip(f"IR cache {path.name} is not present")
        data = json.loads(path.read_text())
        before = [
            decomposer._build_criteria(c, rule_name=c.get("name"))
            for c in data["target"]["inclusion_rules"]
        ]
        cls = parser_module.LogicDecomposer

        unrecorded = cls._repair_pattern_e(
            cls._repair_band_tiers(decomposer._repair_split_bands(list(before)))
        )

        with pytest.raises(UnaccountedDepartureError) as raised:
            assert_repairs_accounted(before, unrecorded, RepairLedger(), role="inclusion")
        assert "HbA1c 6.5 - 8.5% (Naïve/Intolerant/Treated)" in str(raised.value)

    def test_should_not_let_a_demotion_excuse_a_later_deletion(self, models):
        """A demotion says the criterion is still here. It cannot answer "where did it go?"."""
        from src.agents.agent1.repair_accounting import (
            RepairLedger,
            UnaccountedDepartureError,
            assert_repairs_accounted,
        )

        criterion = _closed(models, "HbA1c 6.5 - 8.5%", 6.5, 8.5, "HbA1c 6.5 - 8.5%")
        ledger = RepairLedger()
        ledger.demoted(
            criterion, action="demoted-into-band-tier-group",
            group_name="HbA1c band (OR group)", reason="moved into a group",
        )

        with pytest.raises(UnaccountedDepartureError):
            assert_repairs_accounted([criterion], [], ledger, role="inclusion")


class TestEveryDeliveredArmAccountsForEveryDeparture:
    @pytest.mark.parametrize("trial", sorted(DELIVERED))
    def test_should_account_for_every_criterion_that_leaves_the_rule_tree(
        self, decomposer, trial
    ):
        """The pass condition: zero unaccounted departures, on the delivered arms.

        ``_build_cohort_definition`` runs the gate itself after every repair step, so
        an unaccounted departure raises here rather than returning a quietly shorter
        list.
        """
        path = CACHE / DELIVERED[trial]
        if not path.exists():
            pytest.skip(f"IR cache {path.name} is not present")
        data = json.loads(path.read_text())

        for cohort in ("target", "comparator"):
            cohort_def = decomposer._build_cohort_definition(data[cohort])
            assert cohort_def.repair_accounting is not None

    def test_should_name_the_dropped_restatement_on_the_delivered_carolina_arm(
        self, decomposer
    ):
        """The motivating case, end to end: the drop now reaches the study record."""
        path = CACHE / DELIVERED["CAROLINA"]
        if not path.exists():
            pytest.skip(f"IR cache {path.name} is not present")
        data = json.loads(path.read_text())

        ledger = decomposer._build_cohort_definition(data["target"]).repair_accounting

        dropped = [r for r in ledger if r["action"] == "dropped-as-restatement"]
        assert len(dropped) == 1
        assert dropped[0]["criterion"]["name"] == "HbA1c 6.5 - 8.5% (Naïve/Intolerant/Treated)"
        assert dropped[0]["criterion"]["sourceText"].startswith("HbA1c 6.5 - 8.5%")

        # ...and the demotion that explains the six drug criteria names the line that
        # used to produce them.
        demoted = [r for r in ledger if r["disposition"] == "demotion"]
        lines = " ".join(r["criterion"]["sourceText"] or "" for r in demoted)
        assert "sulphonylurea (SU) monotherapy" in lines


class TestTheStudyRecordCarriesTheAccounting:
    def test_should_put_repair_accounting_on_the_stored_eligibility(self, decomposer):
        """A ledger that stops at the IR is a log line with extra steps."""
        from src.services.tte_service import TTEService

        path = CACHE / DELIVERED["CAROLINA"]
        if not path.exists():
            pytest.skip(f"IR cache {path.name} is not present")
        ir = decomposer._build_artemis_request(json.loads(path.read_text()))

        study = TTEService._study_from_ir(
            TTEService.__new__(TTEService), ir, "CAROLINA", source="ai"
        )

        accounting = study["eligibility"]["_repairAccounting"]
        assert [r["action"] for r in accounting].count("dropped-as-restatement") == 1


# --------------------------------------------------------------------------- Task B


class TestReadingTheBoundFromTheProtocolLine:
    @pytest.mark.parametrize(
        "line,expected",
        [
            ("HbA1c of => 6.5% and <= 10.0% at Visit 1 (screening)", 10.0),
            ("age between >= 40 and =< 85 years", 85.0),
            ("Age ≥ 40 and ≤ 85 years at Visit 1a", 85.0),
            ("Elevated HbA1c: 6.5 - 8.5%, inclusive, if treatment naive", 8.5),
            ("HbA1c 6.5 - 7.5% (48 - 58 mmol/mol) while treated with SU", 7.5),
        ],
    )
    def test_should_read_an_inclusive_upper_bound_the_line_states(
        self, parser_module, line, expected
    ):
        assert expected in parser_module.inclusive_upper_bounds(line)

    def test_should_not_read_a_lower_bound_as_an_upper_one(self, parser_module):
        """`>= 7.0` on the same line is a real bound, and flipping at it would invert
        a correct rule rather than correct a wrong one."""
        line = "Glycosylated haemoglobin (HbA1c) of >= 7.0% and <=10% for patients"

        assert parser_module.inclusive_upper_bounds(line) == {10.0}

    def test_should_read_nothing_from_an_exclusion_line_stating_a_lower_bound(
        self, parser_module
    ):
        for line in (
            "ALT or AST > 2X ULN or a Total Bilirubin ≥ 1.5X ULN",
            "Calcitonin ≥50 ng/L",
            "Treatment (≥ 7 consecutive days) with GLP-1 receptor agonists",
        ):
            assert parser_module.inclusive_upper_bounds(line) == set()

    def test_should_read_nothing_from_an_absent_line(self, parser_module):
        assert parser_module.inclusive_upper_bounds(None) == set()


class TestCorrectingTheNegatedUpperBound:
    LINE = "HbA1c of => 6.5% and <= 10.0% at Visit 1 (screening)"

    def test_should_correct_an_absence_gte_that_sits_on_an_inclusive_bound(
        self, decomposer, models
    ):
        rule = _band(models, "HbA1c upper bound (<=10.0%)", "gte", 10.0, self.LINE,
                     logic="ABSENCE")

        out = decomposer._repair_inclusive_upper_bounds([rule])[0]

        assert (out.value_constraint.op, out.value_constraint.value) == ("gt", 10.0)

    def test_should_leave_a_presence_rule_alone(self, decomposer, models):
        """`PRESENCE gte 6.5` is the lower half and is already right."""
        rule = _band(models, "HbA1c lower bound (>=6.5%)", "gte", 6.5, self.LINE)

        out = decomposer._repair_inclusive_upper_bounds([rule])[0]

        assert out is rule

    def test_should_leave_a_bound_the_line_does_not_state_as_inclusive(
        self, decomposer, models
    ):
        """CAROLINA's eGFR pair, pinned as out of scope.

        The line reads `eGFR 30-59`; the model named its own rule `eGFR <= 59` and
        then wrote the constraint as `ABSENCE gte 60.0`. 60 appears nowhere in the
        criterion -- it is invented by the same bad De Morgan applied to `<= 59` --
        so correcting only the operator would give `[30, 60]`, which is still not
        gold's `[30, 59]`. The detector reads the LINE, so it declines, and the
        criterion is left exactly as the model wrote it.
        """
        line = (
            "Moderately impaired renal function (as defined by MDRD formula) with "
            "estimated glomerular filtration rate [eGFR] 30-59 mL/min/1.73 m2"
        )
        rule = _band(models, "eGFR upper bound (<= 59)", "gte", 60.0, line,
                     logic="ABSENCE", analyte="eGFR")

        out = decomposer._repair_inclusive_upper_bounds([rule])[0]

        assert out is rule
        assert out.value_constraint.op == "gte"

    def test_should_reach_a_bound_nested_inside_a_group(self, decomposer, models):
        parent = models.Criteria(
            name="High risk of CV events (OR group)",
            domain="Condition",
            entity_text=None,
            group_type="ANY",
            sub_criteria=[
                _band(models, "HbA1c upper bound", "gte", 10.0, self.LINE, logic="ABSENCE")
            ],
        )

        out = decomposer._repair_inclusive_upper_bounds([parent])[0]

        # The parent keeps its identity -- only the member changed.
        assert out is parent
        assert out.sub_criteria[0].value_constraint.op == "gt"

    def test_should_leave_an_exclusion_rule_alone(self, decomposer, models):
        """`ABSENCE gte X` is the CORRECT encoding of "exclude if >= X"; the repair is
        wired to inclusion rules only so it can never reach one."""
        line = "HbA1c of => 6.5% and <= 10.0% at Visit 1"
        exclusion = decomposer._build_criteria(
            {
                "name": "HbA1c at or above 10.0%",
                "domain": "Measurement",
                "entity_text": "HbA1c",
                "source_text": line,
                "value_constraint": {"op": "gte", "value": 10.0, "unit_text": "%"},
            },
            force_logic_type="ABSENCE",
        )
        data = {"primary_criteria": {"domain": "Drug", "entity_text": "linagliptin"},
                "inclusion_rules": [], "exclusion_rules": []}

        built = decomposer._build_cohort_definition(data)

        assert built.exclusion_rules == []
        assert exclusion.value_constraint.op == "gte"


class TestTheCorrectedBoundMakesTheDeclinedPairMergeable:
    def test_should_merge_the_empa_reg_band_once_its_upper_bound_is_corrected(
        self, decomposer
    ):
        """EMPA-REG's two HbA1c bands were both declined at HEAD for carrying `gte`."""
        path = CACHE / DELIVERED["EMPA-REG"]
        if not path.exists():
            pytest.skip(f"IR cache {path.name} is not present")
        data = json.loads(path.read_text())

        rules = decomposer._build_cohort_definition(data["target"]).inclusion_rules

        bands = sorted(
            (c.value_constraint.value, c.value_constraint.value_high)
            for rule in rules
            for c in ([rule] + list(rule.sub_criteria or []))
            if c.value_constraint is not None and c.value_constraint.op == "bt"
        )
        assert bands == [(7.0, 9.0), (7.0, 10.0)]

    def test_should_merge_the_carmelina_band_to_the_band_gold_states(self, decomposer):
        """Gold: ``ValueAsNumber {Value: 6.5, Extent: 10, Op: "!bt"}``."""
        path = CACHE / DELIVERED["CARMELINA"]
        if not path.exists():
            pytest.skip(f"IR cache {path.name} is not present")
        data = json.loads(path.read_text())

        rules = decomposer._build_cohort_definition(data["target"]).inclusion_rules

        bands = [
            (c.value_constraint.value, c.value_constraint.value_high)
            for rule in rules
            for c in ([rule] + list(rule.sub_criteria or []))
            if c.value_constraint is not None and c.value_constraint.op == "bt"
        ]
        assert bands == [(6.5, 10.0)]

    def test_should_include_an_eighty_five_year_old_after_the_age_bound_is_corrected(
        self, decomposer
    ):
        """`Age <= 85` written as `ABSENCE gte 85` excludes a patient aged exactly 85.

        Seven constraints in the corpus carry this. The arm below is one of them; the
        delivered CAROLINA arm happens to encode the same bound correctly, which is
        why the claim is measured here and not there.
        """
        path = CACHE / AGE_ARM
        if not path.exists():
            pytest.skip(f"IR cache {path.name} is not present")
        data = json.loads(path.read_text())
        raw = [
            decomposer._build_criteria(c, rule_name=c.get("name"))
            for c in data["target"]["inclusion_rules"]
        ]
        before = [
            c for c in raw
            if c.logic_type == "ABSENCE" and c.value_constraint is not None
            and c.value_constraint.value == 85.0
        ]
        assert [(c.value_constraint.op, c.value_constraint.value) for c in before] == [
            ("gte", 85.0)
        ], "the arm no longer carries the mis-encoded age bound this test is about"

        rules = decomposer._build_cohort_definition(data["target"]).inclusion_rules

        after = [
            c for rule in rules for c in ([rule] + list(rule.sub_criteria or []))
            if c.logic_type == "ABSENCE" and c.value_constraint is not None
            and c.value_constraint.value == 85.0
        ]
        assert [c.value_constraint.op for c in after] == ["gt"]


class TestTheDivergenceFromGoldIsDeliberate:
    def test_should_correct_empa_reg_in_a_direction_its_gold_does_not_take(
        self, decomposer
    ):
        """Pinned so the decision stays visible rather than buried in a diff.

        EMPA-REG's protocol line reads "HbA1c of >= 7.0% and <=10% for patients on
        background therapy or HbA1c >= 7.0% and <= 9.0% for drug naive patients" --
        inclusive at both upper bounds. TROY v1.1 gold encodes it as a zero-occurrence
        Measurement carrying ``{"Value": 10, "Op": "gte"}``, which is ``< 10`` and
        excludes a patient at exactly 10.0%: the same off-by-one, in the gold. The
        protocol line is the authority here, so this pipeline now emits the inclusive
        band and gold does not match it. That is a deliberate divergence, not a
        regression, and this test fails if either side moves.
        """
        gold = json.loads(
            Path(
                "data/gold/EMPA-REG OUTCOME/"
                "[TROY v1.1] Empagliflozin (EMPA-REG OUTCOME).json"
            ).read_text()
        )
        rule = gold["InclusionRules"][1]
        gold_ops = [
            g["Groups"][0]["CriteriaList"][0]["Criteria"]["Measurement"]["ValueAsNumber"]
            for g in rule["expression"]["Groups"]
        ]
        assert [(v["Op"], v["Value"]) for v in gold_ops] == [("gte", 10), ("gte", 10)]

        path = CACHE / DELIVERED["EMPA-REG"]
        if not path.exists():
            pytest.skip(f"IR cache {path.name} is not present")
        rules = decomposer._build_cohort_definition(
            json.loads(path.read_text())["target"]
        ).inclusion_rules
        ours = sorted(
            (c.value_constraint.value, c.value_constraint.value_high)
            for rule_ in rules
            for c in ([rule_] + list(rule_.sub_criteria or []))
            if c.value_constraint is not None and c.value_constraint.op == "bt"
        )

        assert ours == [(7.0, 9.0), (7.0, 10.0)]
