"""The ledger checks in ``tests/test_no_text_rules.py``, each shown failing on its own case.

A check that only ever passes is indistinguishable from one that does nothing, so every
check here is driven into its failure, from the real event where one exists.
"""

from __future__ import annotations

import json

import pytest

from tests import test_no_text_rules as guard

# The pending list as it stood before the 2026-10-13 guard extension: the two A7 regexes.
PRE_EXTENSION_KEYS = [
    ["src/agents/agent1/criteria_dedup.py", "_CONJUNCTION_MARKER", "re"],
    ["src/agents/agent1/criteria_dedup.py", "_DISJUNCTION_MARKER", "re"],
]
# The keys the 2026-10-14 growth added (the baseline's ``grown`` record): lookups the
# extended ``lookup`` sink found that no id or position join could replace in that change.
GROWTH_2026_10_14_KEYS = [
    ["src/agents/agent2/retriever.py", "BatchSearchResults.__init__", "lookup"],
    ["src/services/restated_distinctness.py", "analyze_restated_groups", "lookup"],
    ["src/services/tte_service.py", "TTEService._recommend_seeded_concept_set", "lookup"],
]


def _rejected_growth(tmp_path, monkeypatch, at_growth_keys, before_keys) -> int:
    """How many pending keys check 4 rejects when ``at_growth_keys`` meets ``before_keys``.

    The ledger is built from the recorded baseline keys rather than the live ledger, so the
    case survives the pending rules being removed one by one.
    """
    at_growth = [
        {
            "file": file,
            "symbol": symbol,
            "sink": sink,
            "kind": "pending",
            "inventory_id": "recorded",
            "status": "dormant",
            "decides": "as recorded",
            "reason": "the pending list as a growth recorded it",
        }
        for file, symbol, sink in at_growth_keys
    ]
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"keys": before_keys}), encoding="utf-8")
    monkeypatch.setattr(guard, "_ledger_entries", lambda: at_growth)
    monkeypatch.setattr(guard, "BASELINE_PATH", baseline)
    monkeypatch.setattr(guard, "PENDING_BASELINE_SHA256", guard.baseline_digest(before_keys))
    with pytest.raises(AssertionError, match="the pending list only shrinks") as raised:
        guard.test_should_not_grow_the_pending_list_when_the_baseline_is_unchanged()
    return str(raised.value).count("  (")


def test_should_reject_the_2026_10_13_growth_when_the_baseline_predates_it(tmp_path, monkeypatch):
    """The ledger as the 2026-10-13 growth recorded it, held to the baseline before it."""
    recorded = json.loads(guard.BASELINE_PATH.read_text(encoding="utf-8"))["keys"]
    at_growth = [k for k in recorded if k not in GROWTH_2026_10_14_KEYS]
    grown = _rejected_growth(tmp_path, monkeypatch, at_growth, PRE_EXTENSION_KEYS)
    added = {tuple(k) for k in at_growth} - {tuple(k) for k in PRE_EXTENSION_KEYS}
    assert grown == len(added) == 31


def test_should_reject_the_2026_10_14_growth_when_the_baseline_predates_it(tmp_path, monkeypatch):
    """The ledger as the 2026-10-14 growth recorded it, held to the baseline before it."""
    recorded = json.loads(guard.BASELINE_PATH.read_text(encoding="utf-8"))["keys"]
    assert all(key in recorded for key in GROWTH_2026_10_14_KEYS)
    before = [k for k in recorded if k not in GROWTH_2026_10_14_KEYS]
    assert _rejected_growth(tmp_path, monkeypatch, recorded, before) == 3


def test_should_reject_a_baseline_edit_when_the_pinned_hash_is_unchanged(tmp_path, monkeypatch):
    recorded = json.loads(guard.BASELINE_PATH.read_text(encoding="utf-8"))
    recorded["keys"].append(["src/services/tte_service.py", "TTEService.any_method", "literal"])
    edited = tmp_path / "baseline.json"
    edited.write_text(json.dumps(recorded), encoding="utf-8")
    monkeypatch.setattr(guard, "BASELINE_PATH", edited)
    with pytest.raises(AssertionError, match="PENDING_BASELINE_SHA256"):
        guard.test_should_not_grow_the_pending_list_when_the_baseline_is_unchanged()


def test_should_report_a_pending_rule_as_gone_when_no_site_of_its_sink_remains_in_its_symbol(
    monkeypatch,
):
    stale = {
        "file": "src/agents/agent1/criteria_dedup.py",
        "symbol": "dedup_enabled",
        "sink": "re",
        "kind": "pending",
        "inventory_id": "A7",
        "status": "dormant",
        "decides": "nothing: dedup_enabled holds no regex",
        "reason": "negative case for check 2",
    }
    entries = [*guard._ledger_entries(), stale]
    monkeypatch.setattr(guard, "_ledger_entries", lambda: entries)
    with pytest.raises(AssertionError, match="dedup_enabled re"):
        guard.test_should_find_every_pending_rule_in_the_code_when_it_is_still_listed()


def test_should_keep_a_pending_rule_pending_when_its_pattern_is_edited_and_not_removed(
    tmp_path, monkeypatch
):
    """Keyed by fingerprint, an edited regex left its pending entry 'removed' and its new
    text unlisted; keyed by (file, symbol, sink) it stays pending until the sink is gone."""
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    module = tmp_path / "rule.py"
    pending = {("rule.py", "_CONJUNCTION_MARKER", "re")}
    module.write_text(
        'import re\n_CONJUNCTION_MARKER = re.compile(r"\\band\\b|\\bplus\\b")\n', encoding="utf-8"
    )
    before = guard.scan_paths([module])
    module.write_text(
        'import re\n_CONJUNCTION_MARKER = re.compile(r"\\band\\b")\n', encoding="utf-8"
    )
    edited = guard.scan_paths([module])
    assert before[0].fingerprint != edited[0].fingerprint
    assert all(guard._covered(site, set(), pending) for site in edited)
    module.write_text("_CONJUNCTION_MARKER = None\n", encoding="utf-8")
    assert not {(s.file, s.symbol, s.sink) for s in guard.scan_paths([module])} & pending


def test_should_fail_when_a_rule_module_holds_no_pending_rule(monkeypatch):
    # The real event: both modules sat in RULE_MODULES after their rules were removed
    # (criterion_seed A10, disease_anchor C8 in 37bd1d8), so check 3 checked nothing.
    stale = frozenset({"src/utils/criterion_seed.py", "src/utils/disease_anchor.py"})
    monkeypatch.setattr(guard, "RULE_MODULES", stale)
    with pytest.raises(AssertionError, match="hold no pending rule"):
        guard.test_should_not_allow_any_site_when_it_lives_in_a_rule_module()


def test_should_scan_a_file_when_only_the_ledger_names_it(monkeypatch):
    named = {"file": "scripts/prompt_ab.py", "fingerprint": "re:x", "kind": "allowed"}
    monkeypatch.setattr(guard, "_ledger_entries", lambda: [named])
    assert guard.ROOT / "scripts" / "prompt_ab.py" in guard.scanned_files()
