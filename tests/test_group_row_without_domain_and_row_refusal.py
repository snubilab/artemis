"""A group row needs no domain, and one invalid row no longer aborts a whole trial.

Observed 2026-10-12 in the P2 NEW re-extraction of PLATO (NCT00391872). Agent 1 returned
the protocol line "4. ≥2 of the following:" as a parent row carrying five sub_criteria and
``"domain": null, "entity_text": null``. ``Criteria`` declared ``domain: str``, so pydantic
refused the row, and because ``_build_criteria`` is called inside a list comprehension the
ValidationError escaped ``parse_nct`` and the trial produced no IR at all -- every other
criterion of PLATO went with it (``output/site_gap/2026-10-12_p2_new/reingest.log``, PLATO
block from line 12849).

Two separate things were wrong, and they are tested separately:

* A group row emits no rule of its own -- its members do -- so it has no domain to state.
  The previous prompts showed a filled-in parent row with a domain; that example is gone,
  so the null shape is now expected rather than malformed. Nothing is derived for it: no
  reader of a label's domain needs one, and the store builder checks the demographic
  domains BEFORE it checks ``isGroupLabel``, so an inferred domain could only route a
  label into a rule-building branch.
* A leaf that really is invalid is refused and RECORDED, on the same ledger the post-parse
  repairs write (``eligibility._repairAccounting``), and the delivery gate reads that
  record as criterion loss. The rest of the trial is built.

The fixture copies the failing rows verbatim from the raw IR; its ``_provenance`` block
names the source file, its SHA-256 and the JSON pointers. No LLM, database or graph is
reached: the decomposer's LLM is a ``MagicMock`` and every builder used here is in-process.
"""
from __future__ import annotations

import copy
import importlib
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "plato_group_row_without_domain_ir.json"

#: Position of the "4. ≥2 of the following:" row inside the fixture's inclusion_rules
#: (source pointer ``/target/inclusion_rules/3``), between its two document neighbours.
GROUP = 1

_MODULES = (
    "src.models.ir",
    "src.services.value_constraint",
    "src.agents.agent1.parser",
)


@pytest.fixture
def parser_module():
    """Fresh imports, for the reason ``test_repair_accounting_and_inclusive_bounds`` gives:
    another module installs a ``MagicMock`` over ``src.models.ir`` and never restores it."""
    saved = {name: sys.modules.get(name) for name in _MODULES}
    for name in _MODULES:
        sys.modules.pop(name, None)
    try:
        module = None
        for name in _MODULES:
            module = importlib.import_module(name)
        assert not isinstance(sys.modules["src.models.ir"].Criteria, MagicMock)
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


@pytest.fixture
def plato() -> dict:
    data = json.loads(FIXTURE.read_text())
    data.pop("_provenance")
    return data


def _refusals(ledger: list[dict]) -> list[dict]:
    return [record for record in ledger if record.get("disposition") == "refusal"]


def _study(decomposer, data: dict) -> dict:
    from src.services.tte_service import TTEService

    ir = decomposer._build_artemis_request(data)
    return TTEService._study_from_ir(TTEService.__new__(TTEService), ir, "PLATO", source="ai")


# --------------------------------------------------------------------------- the real row


class TestAGroupRowNeedsNoDomain:
    def test_should_build_the_whole_trial_when_a_group_row_carries_no_domain(
        self, decomposer, plato
    ):
        """The event itself: this call raised and took PLATO's whole IR with it."""
        ir = decomposer._build_artemis_request(plato)

        for arm in (ir.target, ir.comparator):
            assert [rule.name for rule in arm.inclusion_rules] == [
                row["name"] for row in plato["target"]["inclusion_rules"]
            ]
            assert _refusals(arm.repair_accounting) == []

    def test_should_keep_every_member_and_the_extracted_group_type_when_the_row_has_no_domain(
        self, decomposer, plato
    ):
        raw = plato["target"]["inclusion_rules"][GROUP]

        group = decomposer._build_artemis_request(plato).target.inclusion_rules[GROUP]

        assert group.domain is None
        assert group.entity_text is None
        assert group.source_text == raw["source_text"]
        # What the IR says about "≥2 of the following": ANY. The cardinality is RFC-016
        # step 2 and is not represented here.
        assert group.group_type == "ANY"
        assert [(m.name, m.domain) for m in group.sub_criteria] == [
            (m["name"], m["domain"]) for m in raw["sub_criteria"]
        ]

    def test_should_write_the_label_row_with_no_domain_when_the_store_is_built(
        self, decomposer, plato
    ):
        rows = _study(decomposer, plato)["eligibility"]["inclusionCriteria"]
        raw = plato["target"]["inclusion_rules"][GROUP]

        labels = [row for row in rows if row.get("isGroupLabel")]
        assert [(row["description"], row["domain"]) for row in labels] == [(raw["name"], "")]
        members = [row for row in rows if row.get("groupId") == labels[0]["groupId"]
                   and not row.get("isGroupLabel")]
        assert [(row["description"], row["domain"]) for row in members] == [
            (m["name"], m["domain"]) for m in raw["sub_criteria"]
        ]

    def test_should_refuse_a_criterion_with_no_domain_when_it_has_no_members(self, models):
        """The relaxation is for group rows only: a leaf emits a rule and needs a domain."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            models.Criteria(name="Persistent ST-segment", domain=None)
        with pytest.raises(ValidationError):
            models.Criteria(name="Persistent ST-segment")


# --------------------------------------------------------------------------- refusal


class TestAnInvalidRowIsRefusedAndRecorded:
    def test_should_refuse_and_record_an_invalid_member_when_its_group_is_built(
        self, decomposer, plato
    ):
        """Negative case from the real row: one member carries the same null domain."""
        member = plato["target"]["inclusion_rules"][GROUP]["sub_criteria"][1]
        member["domain"] = None

        cohort = decomposer._build_cohort_definition(plato["target"])

        group = cohort.inclusion_rules[GROUP]
        assert member["name"] not in [m.name for m in group.sub_criteria]
        assert len(group.sub_criteria) == 4
        [record] = _refusals(cohort.repair_accounting)
        assert record["role"] == "inclusion"
        assert record["criterion"]["name"] == member["name"]
        assert record["criterion"]["sourceText"] == member["source_text"]
        assert "domain" in record["reason"]
        assert record["lostMembers"] == []
        # Built + refused accounts for every row the model emitted under the group.
        assert len(group.sub_criteria) + 1 == len(
            plato["target"]["inclusion_rules"][GROUP]["sub_criteria"]
        )

    def test_should_build_the_rest_of_the_trial_when_a_top_level_leaf_is_refused(
        self, decomposer, plato
    ):
        leaf = plato["target"]["inclusion_rules"][2]
        leaf["domain"] = None

        cohort = decomposer._build_cohort_definition(plato["target"])

        assert [rule.name for rule in cohort.inclusion_rules] == [
            row["name"] for row in plato["target"]["inclusion_rules"][:2]
        ]
        [record] = _refusals(cohort.repair_accounting)
        assert record["criterion"]["name"] == leaf["name"]

    def test_should_record_the_members_lost_with_a_group_row_when_the_row_itself_is_refused(
        self, decomposer, plato
    ):
        group = plato["target"]["inclusion_rules"][GROUP]
        group["logic_type"] = None

        cohort = decomposer._build_cohort_definition(plato["target"])

        assert len(cohort.inclusion_rules) == 2
        [record] = _refusals(cohort.repair_accounting)
        assert record["criterion"]["sourceText"] == group["source_text"]
        assert [m["name"] for m in record["lostMembers"]] == [
            m["name"] for m in group["sub_criteria"]
        ]

    def test_should_refuse_the_group_row_too_when_every_member_is_refused(
        self, decomposer, plato
    ):
        """A label with no members left carries no criterion; it must not survive as one."""
        group = plato["target"]["inclusion_rules"][GROUP]
        for member in group["sub_criteria"]:
            member["domain"] = None

        cohort = decomposer._build_cohort_definition(plato["target"])

        assert group["name"] not in [rule.name for rule in cohort.inclusion_rules]
        refused = _refusals(cohort.repair_accounting)
        assert [r["criterion"]["name"] for r in refused] == [
            m["name"] for m in group["sub_criteria"]
        ] + [group["name"]]
        # Each member is recorded once, by its own record -- not again under the label.
        assert refused[-1]["lostMembers"] == []

    def test_should_refuse_an_exclusion_row_under_its_own_role(self, decomposer, plato):
        row = copy.deepcopy(plato["target"]["inclusion_rules"][2])
        row["domain"] = None
        plato["target"]["exclusion_rules"] = [row]

        cohort = decomposer._build_cohort_definition(plato["target"])

        assert cohort.exclusion_rules == []
        [record] = _refusals(cohort.repair_accounting)
        assert record["role"] == "exclusion"

    def test_should_count_the_refusal_in_the_log_when_a_row_is_refused(
        self, decomposer, plato, caplog
    ):
        member = plato["target"]["inclusion_rules"][GROUP]["sub_criteria"][1]
        member["domain"] = None

        with caplog.at_level(logging.WARNING, logger="src.agents.agent1.parser"):
            decomposer._build_cohort_definition(plato["target"])

        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(member["name"] in m and "refused" in m for m in messages), messages
        assert any("1 criterion row(s)" in m for m in messages), messages


# --------------------------------------------------------------------------- store + gate


class TestTheRefusalReachesTheDeliveryGate:
    def test_should_carry_the_refusal_onto_the_stored_eligibility(self, decomposer, plato):
        member = plato["target"]["inclusion_rules"][GROUP]["sub_criteria"][1]
        member["domain"] = None

        ledger = _study(decomposer, plato)["eligibility"]["_repairAccounting"]

        assert [r["criterion"]["name"] for r in _refusals(ledger)] == [member["name"]]

    def test_should_fail_the_gate_as_criterion_loss_when_a_row_was_refused(
        self, decomposer, plato
    ):
        import scripts.verify_circe_delivery as gate

        member = plato["target"]["inclusion_rules"][GROUP]["sub_criteria"][1]
        member["domain"] = None

        violations, summary = gate.repair_ledger_violations(_study(decomposer, plato))

        assert violations, summary
        assert member["name"] in " ".join(violations)
        assert "1 refusal" in summary

    def test_should_fail_the_gate_on_a_refused_row_that_carries_no_name(
        self, decomposer, plato
    ):
        """A null name is itself a refusal cause; the record must still be loss, named by line."""
        import scripts.verify_circe_delivery as gate

        leaf = plato["target"]["inclusion_rules"][2]
        leaf["name"] = None

        violations, _ = gate.repair_ledger_violations(_study(decomposer, plato))

        assert violations
        assert leaf["source_text"] in " ".join(violations)

    def test_should_pass_the_gate_when_the_group_row_simply_has_no_domain(
        self, decomposer, plato
    ):
        import scripts.verify_circe_delivery as gate

        violations, _ = gate.repair_ledger_violations(_study(decomposer, plato))

        assert violations == []
