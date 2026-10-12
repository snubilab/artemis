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

**Task B -- a boundary moved by a wrong negation** -- was a repair that read ``<=`` and
``N - M`` out of the protocol line (A1, ``_repair_inclusive_upper_bounds``). It is deleted
with the other rules that read the line's comparators (RFC-016 step 3), and its tests with
it; ``tests/test_quantity_text_rules_removed.py`` pins what that costs.

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
