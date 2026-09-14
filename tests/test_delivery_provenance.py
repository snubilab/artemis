"""Every delivery the user said was sent must stay recoverable from its tag.

This is the mechanical half of .claude/rules/broadsea/delivery-provenance.md.
The rule's prose says a send gets a recovery point; this test is what makes a
lost one fail the suite instead of going unnoticed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "verify_delivery_provenance.py"
LEDGER = ROOT / "deliveries" / "INDEX.json"


def test_should_keep_every_recorded_send_recoverable_when_gate_runs():
    result = subprocess.run(
        [sys.executable, str(GATE)], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, (
        "delivery provenance gate failed -- a sent delivery is no longer "
        f"recoverable:\n{result.stdout}\n{result.stderr}"
    )


def test_should_record_a_version_note_when_code_version_is_absent():
    """A null code version is allowed; a null WITHOUT a stated reason is not.

    The gap itself is honest -- 2026-06-24 predates the repository and 2026-08-31
    was exported from a stale store. What must never happen is a blank field a
    later reader cannot tell apart from a guess.
    """
    sends = json.loads(LEDGER.read_text())["sends"]
    for s in sends:
        if s["content_code_version"] is None or s["head_at_send"] is None:
            assert s.get("version_note"), (
                f"{s['date']}: code version is null with no version_note explaining why"
            )


@pytest.mark.parametrize("field", ["date", "tag", "sent_confirmed_by_user", "files"])
def test_should_carry_the_required_ledger_fields_when_a_send_is_recorded(field):
    for s in json.loads(LEDGER.read_text())["sends"]:
        assert field in s, f"{s.get('date', '?')}: ledger entry is missing {field!r}"
