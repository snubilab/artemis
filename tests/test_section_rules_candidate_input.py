"""Agent 1's input for the six evaluated trials, built by the section-locating rules, against the candidate's.

The delivery candidate (output/site_gap/2026-10-12_prompt_f2, code d7dc2bb) built Agent 1's input with the
section-locating and list-splitting rules (S1-S9) and did not lose criterion lines; the LLM segmentation step that
replaced them (fe7839e) did. The user re-admitted those format rules on 2026-10-22. This test renders the input
offline -- every model call raises -- through ``parse_nct`` up to the prompt, and compares it with the candidate's
actual input (``fixtures/section_rules/candidate_agent1_input.json``) list by list.

Every difference is listed in ``fixtures/section_rules/differences.json`` with its cause; anything else fails.
The rules not restored (A6, the LLM split pass, the similarity merges) account for most of them -- see that file
and ``src/agents/agent1/section_rules.py``.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

import src.utils.llm as llm
from src.agents.agent1 import parser as parser_module
from src.agents.agent1 import segmentation
from src.agents.agent1.parser import LogicDecomposer

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = json.loads((ROOT / "tests" / "fixtures" / "section_rules" / "candidate_agent1_input.json").read_text())
KINDS = ("inclusion_criteria", "exclusion_criteria")

# (trial, kind) -> why the rendered list is not the candidate's item for item: its causes, the render-only items
# ("added") and the candidate-only items ("removed"), whitespace-folded. A list named with no added or removed item
# differs in order only.
DIFFERENCES: dict[tuple[str, str], dict] = {
    (entry["trial"], entry["list"]): entry
    for entry in json.loads((ROOT / "tests" / "fixtures" / "section_rules" / "differences.json").read_text())["lists"]
}


class _Stop(Exception):
    pass


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _refuse_model(*args, **kwargs):
    raise AssertionError("a model was asked for while Agent 1's input was being built")


def render(monkeypatch, nct_id: str) -> dict[str, list[str]]:
    """``parse_nct`` up to the prompt with every model call refused; the lists the prompt is built from."""
    got = {}
    normalize = parser_module._normalize_trial_data_for_stable_hash

    def stop(trial_data):
        got["td"] = normalize(trial_data)
        raise _Stop

    monkeypatch.setattr(llm, "get_llm", _refuse_model)
    monkeypatch.setattr(segmentation, "_responder", _refuse_model)
    monkeypatch.setattr(parser_module, "_normalize_trial_data_for_stable_hash", stop)
    with pytest.raises(_Stop):
        LogicDecomposer.__new__(LogicDecomposer).parse_nct(nct_id, enrich_from_pubmed=False)
    return {kind: list(getattr(got["td"], kind)) for kind in KINDS}


@pytest.mark.parametrize("trial", sorted(CANDIDATE["trials"]))
def test_should_equal_the_candidates_input_when_built_by_the_section_rules(monkeypatch, trial):
    entry = CANDIDATE["trials"][trial]
    rendered = render(monkeypatch, entry["nct_id"])
    problems = []
    for kind in KINDS:
        new, cand = rendered[kind], entry[kind]
        diff = DIFFERENCES.get((trial, kind))
        if diff is None:
            if new != cand:
                problems.append(f"{kind}: not the candidate's list\n  new : {new}\n  cand: {cand}")
            continue
        only_new = Counter(map(_fold, new)) - Counter(map(_fold, cand))
        only_cand = Counter(map(_fold, cand)) - Counter(map(_fold, new))
        assert all(cause.strip() for cause in diff["causes"]), (trial, kind)
        if only_new != Counter(map(_fold, diff.get("added", []))):
            problems.append(f"{kind}: unlisted render-only items {sorted(only_new)}")
        if only_cand != Counter(map(_fold, diff.get("removed", []))):
            problems.append(f"{kind}: unlisted candidate-only items {sorted(only_cand)}")
    assert not problems, f"{trial}:\n" + "\n".join(problems)
