"""A window the pipeline guessed must be visible to whoever reads the delivery.

`c1cb2c0` gave the per-domain criterion-window default one home and recorded every
application in `_defaultedWindowCriteria`. The gate then ignored the key entirely:
injecting it into all 12 files of `output/site_gap/2026-09-09/deliver_v3` changed
nothing -- 12 FAIL before and after, no census break, no mention anywhere in the
report. That inertness is CORRECT and is pinned below: a substituted window is not
criterion loss, so it must never move a verdict.

What it must not stay is invisible. 57 of the 557 criteria in the cold-6 store
(10%, nine of the ten studies) carried no extracted window, so on a real batch a
reviewer reads a file where one criterion in ten had its temporal window guessed
and the report says nothing. That is this file's own doctrine turned on itself --
``criterion_accounting``'s docstring already states it: "a check whose only output
is silence cannot be told from a check that never ran". A record written into the
payload that no reader of the report can see is the same defect one stage further
on.

So the count rides the accounting summary, in the shape ``drop_clause`` already
established next to it, and the three states are kept distinct because they mean
three different things:

    key absent          -> no clause at all. The artifact predates the record; the
                           windows may well have been defaulted and nothing knows.
    key present, empty  -> "0 windows defaulted". The producer ran and substituted
                           nothing. Saying 0 is what separates this from the case
                           above, which is exactly why the producer emits the key
                           present-and-empty rather than omitting it.
    key present, rows   -> "N windows defaulted (...)".

The parenthetical splits the two `source` values `c1cb2c0` recorded precisely so
they could be told apart, and they are not equally interesting. A `domain-default`
row used the value `agent1/prompts.py` told the model to apply -- routine. An
`unlisted-domain-default` row took the judged -9999 for a domain the prompt never
documented, and the constant's own comment calls such a row "the signal that a
domain needs a documented value, not a judged one". Folding them into one number
would hide the signal inside the routine case, so the clause names both.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.utils.circe_lint import (
    DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE,
    DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN,
    DEFAULTED_WINDOW_CRITERIA_KEY,
)
from tests.test_delivery_gate_reads_drop_records import (
    ARISTOTLE_RECORDS,
    CLEAN_RECORDS,
    STORE_CRITERIA,
    _study,
)


def _defaulted(
    criterion_id: str,
    label: str,
    *,
    domain: str = "Condition",
    role: str = "exclusion",
    criteria_type: str = "ConditionOccurrence",
    start: int = -9999,
    source: str = DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE,
) -> dict[str, Any]:
    """One `_defaultedWindowCriteria` row, in the producer's shape."""
    return {
        "criterionId": criterion_id,
        "role": role,
        "label": label,
        "criteriaType": criteria_type,
        "domain": domain,
        "window": {"start": start, "end": 0},
        "source": source,
    }


#: The real shape: a mechanical valve exclusion and a Measurement, both from the
#: ARISTOTLE pair `c1cb2c0` measured, plus one Drug.
DOCUMENTED_ROWS = [
    _defaulted("12", "Prosthetic mechanical heart valve"),
    _defaulted(
        "18",
        "Creatinine clearance",
        domain="Measurement",
        criteria_type="Measurement",
        start=-180,
    ),
    _defaulted(
        "21",
        "Aspirin",
        domain="Drug",
        criteria_type="DrugExposure",
        start=-365,
        role="inclusion",
    ),
]

#: A domain the extraction prompt never documented, so the -9999 is a judgement.
JUDGED_ROW = _defaulted(
    "24",
    "Prior organ transplant",
    domain="Observation",
    criteria_type="Observation",
    source=DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN,
)


@pytest.fixture
def gate(monkeypatch, tmp_path, capsys):
    """Run the delivery gate over both arms carrying `records`."""

    def _run(records: dict[str, Any] | None) -> tuple[int, str]:
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study()
        core = study["eligibility"]["structuredExpression"]
        for role in ("treatment", "comparator"):
            payload = json.loads(json.dumps(core))
            if records is not None:
                payload.update(json.loads(json.dumps(records)))
            (tmp_path / f"aristotle_{role}.circe.json").write_text(json.dumps(payload))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "aristotle=3"])
        return rc, capsys.readouterr().out

    return _run


def _with(records: dict[str, Any], rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    payload = json.loads(json.dumps(records))
    if rows is not None:
        payload[DEFAULTED_WINDOW_CRITERIA_KEY] = json.loads(json.dumps(rows))
    return payload


class TestTheSummaryNamesTheDefaultedWindows:
    def test_should_report_the_count_when_windows_were_defaulted(self, gate):
        rc, out = gate(_with(CLEAN_RECORDS, DOCUMENTED_ROWS))
        assert rc == 0, out
        assert "3 windows defaulted" in out

    def test_should_say_all_documented_when_every_row_used_the_domain_table(self, gate):
        rc, out = gate(_with(CLEAN_RECORDS, DOCUMENTED_ROWS))
        assert rc == 0, out
        assert "3 windows defaulted (all documented)" in out

    def test_should_name_the_judged_rows_separately_when_a_domain_is_unlisted(self, gate):
        """The whole point of the `source` field: a judged default is the signal."""
        rc, out = gate(_with(CLEAN_RECORDS, DOCUMENTED_ROWS + [JUDGED_ROW]))
        assert rc == 0, out
        assert "4 windows defaulted (3 documented, 1 judged)" in out

    def test_should_say_none_documented_when_every_row_was_judged(self, gate):
        rc, out = gate(_with(CLEAN_RECORDS, [JUDGED_ROW]))
        assert rc == 0, out
        assert "1 windows defaulted (none documented)" in out

    def test_should_say_zero_when_the_key_is_present_and_empty(self, gate):
        """Present-and-empty is a claim -- the producer substituted nothing. It is
        not the same as an artifact that never carried the record, and the report
        must not render the two identically."""
        rc, out = gate(_with(CLEAN_RECORDS, []))
        assert rc == 0, out
        assert "0 windows defaulted" in out

    def test_should_omit_the_clause_when_the_artifact_predates_the_record(self, gate):
        """Every file in the 2026-09-09 delivery is one of these. Printing "0" here
        would claim nothing was defaulted, which is not known and is very likely
        false -- 10% of the store's criteria carry no window."""
        rc, out = gate(CLEAN_RECORDS)
        assert rc == 0, out
        assert "windows defaulted" not in out

    def test_should_report_the_count_on_a_failing_row_too(self, gate):
        """A reviewer reading a FAIL still needs to know a tenth of the windows
        were guessed; the clause is not a passing-row decoration."""
        rc, out = gate(_with(ARISTOTLE_RECORDS, DOCUMENTED_ROWS))
        assert rc == 1, out
        assert "3 windows defaulted (all documented)" in out


class TestTheCountChangesNoVerdict:
    """Injecting the key into all 12 real files changed nothing: 12 FAIL before and
    after. A substituted window is a qualifier on a claim, not criterion loss, so it
    must not block a delivery -- only be visible in one."""

    def test_should_keep_a_passing_row_passing_when_windows_were_defaulted(self, gate):
        clean_rc, _ = gate(CLEAN_RECORDS)
        rc, out = gate(_with(CLEAN_RECORDS, DOCUMENTED_ROWS + [JUDGED_ROW]))
        assert clean_rc == 0
        assert rc == 0, out

    def test_should_keep_a_failing_row_failing_for_the_same_reasons(self, gate):
        """Same reasons, not merely the same verdict: the clause adds a report line
        and no violation."""
        before_rc, before = gate(ARISTOTLE_RECORDS)
        after_rc, after = gate(_with(ARISTOTLE_RECORDS, DOCUMENTED_ROWS))
        assert before_rc == 1 and after_rc == 1
        assert before.replace("\n", "") == after.replace(
            ", 3 windows defaulted (all documented)", ""
        ).replace("\n", "")

    def test_should_not_disturb_the_store_anchor_when_windows_were_defaulted(self, gate):
        """A defaulted window is a sub-classification of a criterion that DID map,
        not a fifth accounting bucket, so it enters no census identity."""
        rc, out = gate(_with(CLEAN_RECORDS, DOCUMENTED_ROWS + [JUDGED_ROW]))
        assert rc == 0, out
        assert f"{STORE_CRITERIA} of {STORE_CRITERIA} store criteria accounted for" in out
        assert "census does not balance" not in out

    def test_should_not_fail_when_every_criterion_defaulted_its_window(self, gate):
        """The pathological batch: more defaulted rows than the store has criteria
        cannot make the gate fail, because the count is not an identity."""
        rows = [
            _defaulted(str(i), f"criterion {i}") for i in range(STORE_CRITERIA + 5)
        ]
        rc, out = gate(_with(CLEAN_RECORDS, rows))
        assert rc == 0, out
        assert f"{len(rows)} windows defaulted (all documented)" in out
