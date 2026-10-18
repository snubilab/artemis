"""AGENT1_INPUT_REPLAY: Agent 1's input read from a file instead of built.

The arm this serves holds Agent 1's input equal to an earlier run's (the criteria lists
that run's IR meta files record) so that only what comes after the input differs. In that
mode nothing that builds the input may run: not the registry segmentation, not a PDF.
"""
import json

import pytest

import src.agents.agent1.nct_fetcher as nct_fetcher
import src.agents.agent1.parser as parser_module
from src.agents.agent1.parser import LogicDecomposer

NCT = "NCT00000001"
RECORD = {
    "nct_id": NCT,
    "title": "A trial",
    "conditions": ["Diabetes Mellitus, Type 2"],
    "interventions": ["Drug: x"],
    "primary_outcomes": ["MACE"],
    "inclusion_criteria": ["Zeta inclusion", "Alpha inclusion"],
    "exclusion_criteria": ["Exclusion one"],
}


class _Stop(Exception):
    pass


def _input_sent(monkeypatch, tmp_path, records):
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    monkeypatch.setenv("AGENT1_INPUT_REPLAY", str(path))

    def forbidden(*args, **kwargs):
        raise AssertionError("the input was built although a replay file names the trial")

    for name in ("fetch_or_load_trial_data", "load_trial_data_from_file"):
        monkeypatch.setattr(parser_module, name, forbidden)
    monkeypatch.setattr(parser_module, "segment_eligibility", forbidden)
    monkeypatch.setattr(nct_fetcher, "segment_eligibility", forbidden)
    monkeypatch.setattr(LogicDecomposer, "_enrich_from_pdf", forbidden)
    monkeypatch.setattr(LogicDecomposer, "_enrich_from_pubmed", forbidden)

    captured = {}

    def stop(trial_data):
        captured["trial_data"] = trial_data
        raise _Stop

    monkeypatch.setattr(parser_module, "_normalize_trial_data_for_stable_hash", stop)
    decomposer = LogicDecomposer.__new__(LogicDecomposer)
    with pytest.raises(_Stop):
        decomposer.parse_nct(NCT)
    return captured["trial_data"]


def test_should_send_the_replayed_criteria_in_file_order_when_the_replay_file_names_the_trial(
    monkeypatch, tmp_path
):
    sent = _input_sent(monkeypatch, tmp_path, {NCT: RECORD})

    assert sent.inclusion_criteria == ["Zeta inclusion", "Alpha inclusion"]
    assert sent.exclusion_criteria == ["Exclusion one"]
    assert sent.title == "A trial"
    assert sent.primary_outcomes == ["MACE"]


def test_should_fail_when_the_replay_file_does_not_name_the_trial(monkeypatch, tmp_path):
    with pytest.raises(KeyError, match=NCT):
        _input_sent(monkeypatch, tmp_path, {"NCT99999999": {**RECORD, "nct_id": "NCT99999999"}})
