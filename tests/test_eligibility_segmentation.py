"""The eligibility segmentation step slices the document by the fragments the model quotes.

RFC-016 §5 replaces the heading vocabulary, terminator lists, bullet/comma splitting,
sponsor-name header filter, superscript rejoin and OR-group collapse (inventory rows
S1-S8, A6) with one LLM step: for the inclusion and the exclusion section the model
returns the starting and ending fragments, the starting and ending fragment of every
criterion, and the lines that interrupt the section (page furniture). Code checks that
each fragment is a substring of the text and slices by it; a fragment that is not in the
text is not used, and the rejection is recorded.

INPUTS ARE REAL. Each source is one production reads on a reingest of the six evaluated
trials: the NCT record's ``eligibilityCriteria`` (``data/nct_cache``) and every PDF
``parse_nct`` discovers under ``data/papers/<NCT>`` and does not skip (a ``main`` PDF is
skipped when a supplement exists). PDFs are rendered the way production renders them --
plain ``pdftotext`` with no ``-layout``, form feeds as newlines -- and the SHA-256 of
that text is pinned in ``tests/fixtures/segmentation/corpus_truth.json``, so a poppler
change that moves the text fails here first instead of silently moving the fragments.

THE MODEL IS STUBBED by an oracle that answers each part of the document from the
fixture: the fragments a correct reader returns, written by hand from the production
rendering and checked against it. What is under test is everything after the model: the
substring check, the part (chunk) assembly across overlaps, the null "continues" fields,
the interruption removal, and the rejection record. What is NOT under test is whether
the live model returns these fragments -- that needs the vLLM run this file never makes.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from src.agents.agent1 import segmentation
from src.agents.agent1.segmentation import (
    REASON_CALL_FAILED,
    REASON_INVALID,
    REASON_NOT_FOUND,
    REASON_OUTSIDE_SECTION,
    Chunk,
    segment_eligibility,
    split_into_chunks,
)

ROOT = Path(__file__).resolve().parents[1]
TRUTH = json.loads(
    (ROOT / "tests" / "fixtures" / "segmentation" / "corpus_truth.json").read_text(encoding="utf-8")
)["sources"]
SOURCES = {source["id"]: source for source in TRUTH}
KINDS = ("inclusion", "exclusion")

#: Item counts per source and section, read off the fixture by hand (first section of each
#: kind; CAROLINA's supplement states both lists twice and the second statement is unused).
EXPECTED_COUNTS = {
    "ARISTOTLE.nct": (5, 0),
    "PLATO.nct": (2, 3),
    "LEADER.nct": (4, 3),
    "CAROLINA.nct": (7, 20),
    "EMPA-REG.nct": (7, 15),
    "CARMELINA.nct": (8, 13),
    "ARISTOTLE.protocol": (5, 23),
    "ARISTOTLE.appendix": (0, 0),
    "PLATO.main": (3, 5),
    "PLATO.supplement": (0, 0),
    "PLATO.design": (3, 16),
    "LEADER.appendix": (5, 14),
    "CAROLINA.supplement": (8, 20),
    "EMPA-REG.appendix": (0, 17),
    "CARMELINA.supplement": (8, 13),
}


# --------------------------------------------------------------------------- #
# Production text
# --------------------------------------------------------------------------- #


def production_text(source: dict[str, Any]) -> str:
    """The text production hands to the step for this source."""
    path = ROOT / source["path"]
    if source["kind"] == "pdf":
        raw = subprocess.run(
            ["pdftotext", str(path), "-"], capture_output=True, text=True, check=True
        ).stdout
        return raw.replace("\f", "\n")
    from src.agents.agent1.nct_fetcher import eligibility_source_text

    data = json.loads(path.read_text(encoding="utf-8"))
    return eligibility_source_text(
        data["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]
    )


_TEXTS: dict[str, str] = {}


def text_of(source_id: str) -> str:
    if source_id not in _TEXTS:
        source = SOURCES[source_id]
        text = production_text(source)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert digest == source["sha256"], (
            f"{source_id}: the production rendering of {source['path']} changed "
            f"({digest} != {source['sha256']}); re-derive the fixture fragments from the new text"
        )
        _TEXTS[source_id] = text
    return _TEXTS[source_id]


# --------------------------------------------------------------------------- #
# Oracle: a correct reader's answer for each part, from the fixture
# --------------------------------------------------------------------------- #


def _fold(text: str) -> tuple[str, list[int]]:
    """Whitespace and private-use glyphs as one space, format characters dropped,
    lower case; with the original offset of every kept character."""
    form: list[str] = []
    index: list[int] = []
    pending = False
    for position, char in enumerate(text):
        category = unicodedata.category(char)
        if category == "Cf":
            continue
        if char.isspace() or category == "Co":
            pending = bool(form)
            continue
        if pending:
            form.append(" ")
            index.append(position)
            pending = False
        lower = char.lower()
        form.append(lower if len(lower) == 1 else char)
        index.append(position)
    return "".join(form), index


class _Located:
    """One section of the fixture placed in its source text."""

    def __init__(self, text: str, section: dict[str, Any], lo: int) -> None:
        self.section = section
        form, index = _fold(text)

        def find(fragment: str, start: int) -> tuple[int, int]:
            probe = _fold(fragment)[0]
            k = form.find(probe, bisect.bisect_left(index, start))
            assert k >= 0, f"fixture fragment not in text: {fragment!r}"
            return index[k], index[k + len(probe) - 1] + 1

        recorded_start, recorded_end = section["span"]
        assert recorded_start >= lo
        self.start = find(section["start"], recorded_start)
        cursor = recorded_start
        self.items: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for item in section["items"]:
            head = find(item["start"], cursor)
            tail = find(item["end"], head[0])
            self.items.append((head, tail))
            cursor = tail[1]
        self.end = find(section["end"], self.items[-1][0][0])
        assert (self.start[0], self.end[1]) == (recorded_start, recorded_end)
        lines = {_fold(line)[0] for line in section["interruptions"]}
        self.interruption_lines = lines

    @property
    def span(self) -> tuple[int, int]:
        return self.start[0], self.end[1]


def locate(source_id: str) -> dict[str, list[_Located]]:
    text = text_of(source_id)
    located: dict[str, list[_Located]] = {}
    for kind in KINDS:
        lo = 0
        located[kind] = []
        for section in SOURCES[source_id][kind]:
            placed = _Located(text, section, lo)
            located[kind].append(placed)
            lo = placed.span[1]
    return located


class TruthOracle:
    """Answers one part of the document the way a correct reader would.

    It reports, per kind, the first fixture section that overlaps the part: its
    ``start`` when the section begins inside the part, its ``end`` when it ends inside
    the part, every criterion that begins inside the part (``end`` null when the
    criterion runs past it), and the interruption lines that sit inside the part.
    """

    def __init__(self, source_id: str, edit=None) -> None:
        self.text = text_of(source_id)
        self.located = locate(source_id)
        self.edit = edit
        self.calls: list[int] = []

    def __call__(self, chunk: Chunk) -> dict[str, Any]:
        self.calls.append(chunk.index)
        lo, hi = chunk.offset, chunk.offset + len(chunk.text)
        assert self.text[lo:hi] == chunk.text
        payload: dict[str, Any] = {}
        for kind in KINDS:
            section = next(
                (s for s in self.located[kind] if s.span[0] < hi and s.span[1] > lo), None
            )
            if section is None:
                payload[kind] = None
                continue
            inside = lambda span: span[0] >= lo and span[1] <= hi  # noqa: E731
            items = []
            for (head, tail), fragments in zip(section.items, section.section["items"]):
                if inside(head):
                    items.append(
                        {
                            "start": fragments["start"],
                            "end": fragments["end"] if inside(tail) else None,
                        }
                    )
            chunk_lines = {
                _fold(line)[0]
                for line in self.text[max(lo, section.span[0]) : min(hi, section.span[1])].split(
                    "\n"
                )
            }
            payload[kind] = {
                "start": section.section["start"] if inside(section.start) else None,
                "end": section.section["end"] if inside(section.end) else None,
                "items": items,
                "interruptions": [
                    line
                    for line in section.section["interruptions"]
                    if _fold(line)[0] in chunk_lines
                ],
            }
        if self.edit is not None:
            payload = self.edit(chunk, payload)
        return payload


def _one_line(text: str) -> str:
    """Whitespace runs and private-use glyphs (PDF symbol-font bullets) as one space."""
    spaced = "".join(" " if unicodedata.category(c) == "Co" else c for c in text)
    return " ".join(spaced.split())


def expected_items(source_id: str, kind: str) -> list[str]:
    """The criteria of the first section of ``kind``, sliced from the fixture."""
    sections = locate(source_id)[kind]
    if not sections:
        return []
    section = sections[0]
    text = text_of(source_id)
    out = []
    for head, tail in section.items:
        lines = text[head[0] : tail[1]].split("\n")
        kept = [line for line in lines if _fold(line)[0] not in section.interruption_lines]
        out.append(_one_line("\n".join(kept)))
    return out


# --------------------------------------------------------------------------- #
# The corpus
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source_id", sorted(SOURCES))
def test_should_slice_every_section_to_its_criteria_when_the_fragments_are_correct(source_id):
    oracle = TruthOracle(source_id)
    result = segment_eligibility(text_of(source_id), respond=oracle)
    criteria = result.criteria()

    assert sorted(oracle.calls) == list(range(result.parts)), "every part reaches the model once"
    for kind in KINDS:
        assert criteria[kind] == expected_items(source_id, kind), kind
    counts = (len(criteria["inclusion"]), len(criteria["exclusion"]))
    assert counts == EXPECTED_COUNTS[source_id]
    # A correct answer leaves nothing rejected, except the restatement a document makes
    # of a list it already stated (CAROLINA's protocol body after its synopsis): that is
    # recorded, not used.
    unexpected = [r for r in result.rejected if r.reason != REASON_OUTSIDE_SECTION]
    assert unexpected == []
    restated = sum(len(sections) - 1 for sections in locate(source_id).values() if sections)
    assert bool(restated) == any(r.reason == REASON_OUTSIDE_SECTION for r in result.rejected)


def test_should_split_long_documents_into_overlapping_parts_that_cover_the_text():
    text = text_of("CAROLINA.supplement")
    chunks = split_into_chunks(text)
    assert len(chunks) > 1
    assert chunks[0].offset == 0
    assert chunks[-1].offset + len(chunks[-1].text) == len(text)
    for before, after in zip(chunks, chunks[1:]):
        assert after.offset < before.offset + len(before.text), "consecutive parts overlap"
        assert text[after.offset : after.offset + len(after.text)] == after.text
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.count == len(chunks) for c in chunks)


def test_should_send_short_text_as_one_part():
    text = text_of("EMPA-REG.nct")
    chunks = split_into_chunks(text)
    assert len(chunks) == 1 and chunks[0].text == text


# --------------------------------------------------------------------------- #
# Real events the step has to end
# --------------------------------------------------------------------------- #


def test_should_end_aristotle_exclusion_at_its_last_criterion_not_at_a_character_cap():
    """The old extractor ran ARISTOTLE's section 26,404 chars into section 5.4 (surgery
    management) and cut it at its 20,000-char cap, dropping 6,454 chars. The step has no
    cap: the section ends where its last criterion ends."""
    result = segment_eligibility(
        text_of("ARISTOTLE.protocol"), respond=TruthOracle("ARISTOTLE.protocol")
    )
    exclusion = result.criteria()["exclusion"]
    assert exclusion[-1].endswith("prior to administration of investigational product.")
    joined = " ".join(result.criteria()["inclusion"] + exclusion)
    assert "Invasive Procedures and Surgery" not in joined
    assert "Eligibility criteria for this study have been carefully considered" not in joined


def test_should_keep_page_furniture_out_of_criteria_when_the_model_names_it():
    """ARISTOTLE's risk-factor list crosses a page; the old splitter could glue the
    running header and the page number into it."""
    result = segment_eligibility(
        text_of("ARISTOTLE.protocol"), respond=TruthOracle("ARISTOTLE.protocol")
    )
    risk_factors = result.criteria()["inclusion"][2]
    assert risk_factors.startswith("One or more of the following risk factor(s) for stroke:")
    assert risk_factors.endswith("e) Hypertension requiring pharmacological treatment")
    for furniture in ("Revised Protocol No.", "Approved v 8.0", "930018272", "CV185030", " 37 "):
        assert furniture not in risk_factors


def test_should_not_append_the_page_number_to_leaders_last_exclusion():
    """The old splitter returned 'Personal history of non-familial medullary thyroid
    carcinoma 39' -- the page number glued on. The criterion's end fragment stops it."""
    result = segment_eligibility(text_of("LEADER.appendix"), respond=TruthOracle("LEADER.appendix"))
    assert (
        result.criteria()["exclusion"][-1]
        == "Personal history of non-familial medullary thyroid carcinoma"
    )


def test_should_keep_a_list_header_and_its_members_in_one_criterion():
    """A6 collapsed headers into ``[OR-GROUP]`` strings; LEADER's ``o`` bullets never
    matched it, so its eleven members reached Agent 1 as top-level rules. The step keeps
    the header and every member in one criterion line for extraction to group."""
    result = segment_eligibility(text_of("LEADER.appendix"), respond=TruthOracle("LEADER.appendix"))
    cohort = result.criteria()["inclusion"][3]
    assert cohort.startswith(
        "Prior cardiovascular disease cohort: age ≥50 and ≥1 of the following criteria:"
    )
    assert "o Prior MI" in cohort and cohort.endswith("eGFR <60 mL/min (Cockcroft-Gault formula)")
    assert not any("[OR-GROUP]" in c for kind in KINDS for c in result.criteria()[kind])


def test_should_leave_the_hoisted_exponent_where_pdftotext_put_it():
    """S6 (stranded-superscript rejoin) is deleted. pdftotext hoists ARISTOTLE's '3' of
    'mm3' above the criterion, and a slice cannot reach back for it: the criterion reads
    '/ mm'. Pinned so the consequence of the deletion is visible, not discovered."""
    result = segment_eligibility(
        text_of("ARISTOTLE.protocol"), respond=TruthOracle("ARISTOTLE.protocol")
    )
    assert "Platelet count ≤ 100,000/ mm" in result.criteria()["exclusion"]


# --------------------------------------------------------------------------- #
# A fragment that is not in the text is recorded and not used
# --------------------------------------------------------------------------- #


def _edit_item(kind: str, item_start: str, field: str, value: Any):
    def edit(chunk: Chunk, payload: dict[str, Any]) -> dict[str, Any]:
        section = payload.get(kind)
        for item in (section or {}).get("items", []):
            if item["start"] == item_start:
                item[field] = value
        return payload

    return edit


def test_should_drop_a_criterion_whose_start_fragment_is_not_in_the_text():
    """A model normalising the protocol's '≤' to '<=' quotes text the document does not
    contain. That criterion is not sliced, the rejection says why, and nothing else moves."""
    source = "ARISTOTLE.protocol"
    baseline = segment_eligibility(text_of(source), respond=TruthOracle(source)).criteria()
    altered = "Severe comorbid condition with life expectancy of <= 1 year"
    oracle = TruthOracle(
        source,
        edit=_edit_item(
            "exclusion",
            "Severe comorbid condition with life expectancy of ≤ 1 year",
            "start",
            altered,
        ),
    )
    result = segment_eligibility(text_of(source), respond=oracle)

    dropped = "Severe comorbid condition with life expectancy of ≤ 1 year"
    assert result.criteria()["exclusion"] == [c for c in baseline["exclusion"] if c != dropped]
    assert result.criteria()["inclusion"] == baseline["inclusion"]
    rejected = [r for r in result.rejected if r.fragment == altered]
    assert rejected and all(
        r.reason == REASON_NOT_FOUND and r.field == "items.start" for r in rejected
    )
    assert all(r.kind == "exclusion" for r in rejected)


def test_should_end_a_criterion_at_the_next_one_when_its_end_fragment_is_not_in_the_text():
    source = "LEADER.appendix"
    baseline = segment_eligibility(text_of(source), respond=TruthOracle(source)).criteria()
    oracle = TruthOracle(
        source, edit=_edit_item("exclusion", "Calcitonin ≥50 ng/L", "end", "Calcitonin >=50 ng/L")
    )
    result = segment_eligibility(text_of(source), respond=oracle)

    assert result.criteria()["exclusion"] == baseline["exclusion"], (
        "the next criterion's start still bounds it, so the slice is the same"
    )
    # Recorded once per part that showed the criterion (parts overlap).
    assert {(r.field, r.reason, r.fragment) for r in result.rejected} == {
        ("items.end", REASON_NOT_FOUND, "Calcitonin >=50 ng/L")
    }


def test_should_record_a_section_end_that_is_not_in_the_text_and_bound_by_the_criteria():
    source = "EMPA-REG.appendix"
    baseline = segment_eligibility(text_of(source), respond=TruthOracle(source)).criteria()

    def edit(chunk, payload):
        if payload.get("exclusion") and payload["exclusion"]["end"]:
            payload["exclusion"]["end"] = "blood pressure > 160/100 mmHg at screening"
        return payload

    result = segment_eligibility(text_of(source), respond=TruthOracle(source, edit=edit))
    assert result.criteria()["exclusion"] == baseline["exclusion"]
    assert any(r.field == "end" and r.reason == REASON_NOT_FOUND for r in result.rejected)


def test_should_record_a_failed_part_and_use_nothing_else_in_its_place():
    """A part whose call fails contributes nothing. There is no fallback to a word-list
    splitter: with every part failing, the source yields no criteria at all."""
    source = "LEADER.nct"

    def failing(chunk: Chunk):
        raise RuntimeError("connection refused")

    result = segment_eligibility(text_of(source), respond=failing)
    assert result.criteria() == {"inclusion": [], "exclusion": []}
    assert [(r.field, r.reason) for r in result.rejected] == [("*", REASON_CALL_FAILED)]
    assert "connection refused" in str(result.rejected[0].fragment)


def test_should_record_a_response_that_is_not_the_requested_object():
    source = "PLATO.nct"
    result = segment_eligibility(text_of(source), respond=lambda chunk: ["not", "an", "object"])
    assert result.criteria() == {"inclusion": [], "exclusion": []}
    assert [r.reason for r in result.rejected] == [REASON_INVALID]


def test_should_reject_a_criterion_reported_outside_its_section():
    """A criterion the model files under the wrong section boundary is not used."""
    source = "PLATO.nct"

    def edit(chunk, payload):
        payload["inclusion"]["items"].append(
            {
                "start": "Persons with moderate or severe liver disease",
                "end": "Persons with moderate or severe liver disease",
            }
        )
        return payload

    result = segment_eligibility(text_of(source), respond=TruthOracle(source, edit=edit))
    assert len(result.criteria()["inclusion"]) == 2
    assert [(r.kind, r.reason) for r in result.rejected] == [("inclusion", REASON_OUTSIDE_SECTION)]


def test_should_describe_rejections_for_the_run_log():
    source = "LEADER.appendix"
    oracle = TruthOracle(
        source, edit=_edit_item("exclusion", "Calcitonin ≥50 ng/L", "end", "Calcitonin >=50 ng/L")
    )
    result = segment_eligibility(text_of(source), respond=oracle)
    line = result.describe_rejections()
    assert "items.end" in line and "Calcitonin >=50 ng/L" in line and REASON_NOT_FOUND in line


# --------------------------------------------------------------------------- #
# The model call
# --------------------------------------------------------------------------- #


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        self.prompts.append("\n".join(str(m.content) for m in messages))
        return AIMessage(content=self.reply)


def test_should_send_each_part_to_the_model_and_cache_the_answer(monkeypatch, tmp_path):
    reply = json.dumps(
        {
            "inclusion": {
                "start": "Inclusion Criteria:",
                "end": "potential ACS",
                "items": [{"start": "Male or female 18 years", "end": "potential ACS"}],
                "interruptions": [],
            },
            "exclusion": None,
        }
    )
    fake = _FakeLLM(reply)
    monkeypatch.setattr(segmentation, "_build_llm", lambda model: fake)
    monkeypatch.setenv("ARTEMIS_SEGMENTATION_CACHE_PATH", str(tmp_path / "segments.jsonl"))
    monkeypatch.delenv("ARTEMIS_SEGMENTATION_CACHE", raising=False)
    segmentation.reset_cache_for_tests()
    text = text_of("PLATO.nct")

    first = segment_eligibility(text, model="stub-model")
    assert first.criteria()["inclusion"] == [
        "Male or female 18 years or older who has been hospitalised for chest pain "
        "and potential ACS"
    ]
    assert len(fake.prompts) == 1 and text in fake.prompts[0]

    segmentation.reset_cache_for_tests()
    second = segment_eligibility(text, model="stub-model")
    assert len(fake.prompts) == 1, "the second run is answered from the cache"
    assert second.criteria() == first.criteria()


def test_should_not_call_the_model_for_empty_text(monkeypatch):
    monkeypatch.setattr(segmentation, "_build_llm", lambda model: pytest.fail("model reached"))
    result = segment_eligibility("   \n ")
    assert result.criteria() == {"inclusion": [], "exclusion": []} and result.parts == 0


# --------------------------------------------------------------------------- #
# The three places production reads eligibility text
# --------------------------------------------------------------------------- #


def _use_oracle(monkeypatch, oracle: TruthOracle) -> None:
    monkeypatch.setattr(segmentation, "_responder", lambda model=None: oracle)


def test_should_enrich_from_a_protocol_pdf_through_the_step(monkeypatch, capsys):
    """``LogicDecomposer._enrich_from_pdf`` is the PDF path ``parse_nct`` runs for every
    discovered PDF. The oracle asserts each part it is shown is a slice of the fixture
    text, so this also proves the PDF path hands the step the production rendering."""
    from src.agents.agent1.nct_fetcher import TrialData
    from src.agents.agent1.parser import LogicDecomposer

    source = "LEADER.appendix"
    _use_oracle(monkeypatch, TruthOracle(source))
    decomposer = LogicDecomposer.__new__(LogicDecomposer)
    enriched = decomposer._enrich_from_pdf(
        TrialData(nct_id="NCT01179048"), str(ROOT / SOURCES[source]["path"]), role="supplement"
    )
    assert enriched.inclusion_criteria == expected_items(source, "inclusion")
    assert enriched.exclusion_criteria == expected_items(source, "exclusion")
    out = capsys.readouterr().out
    assert "eligibility segmented: 5 inclusion, 14 exclusion" in out
    assert "⚠" not in out


def test_should_announce_rejected_fragments_on_the_pdf_path(monkeypatch, capsys):
    from src.agents.agent1.nct_fetcher import TrialData
    from src.agents.agent1.parser import LogicDecomposer

    source = "LEADER.appendix"
    _use_oracle(
        monkeypatch,
        TruthOracle(
            source,
            edit=_edit_item("exclusion", "Malignant neoplasm", "start", "Malignant neoplasms"),
        ),
    )
    decomposer = LogicDecomposer.__new__(LogicDecomposer)
    enriched = decomposer._enrich_from_pdf(
        TrialData(nct_id="NCT01179048"), str(ROOT / SOURCES[source]["path"]), role="supplement"
    )
    assert "Malignant neoplasm" not in enriched.exclusion_criteria
    out = capsys.readouterr().out
    degraded = [line for line in out.splitlines() if "⚠" in line]
    assert degraded and "Malignant neoplasms" in degraded[0] and REASON_NOT_FOUND in degraded[0]


def test_should_segment_the_registry_text_when_loading_an_nct_record(monkeypatch):
    """EMPA-REG's exclusion 11 lists two sub-bullets under 'Pre-menopausal women ... who:'.
    The old splitter cut on every bullet and returned 17 exclusion items; the step keeps
    them inside their criterion: 15."""
    from src.agents.agent1.nct_fetcher import load_trial_data_from_file

    source = "EMPA-REG.nct"
    _use_oracle(monkeypatch, TruthOracle(source))
    trial = load_trial_data_from_file(str(ROOT / SOURCES[source]["path"]))
    assert trial.inclusion_criteria == expected_items(source, "inclusion")
    assert trial.exclusion_criteria == expected_items(source, "exclusion")
    assert len(trial.exclusion_criteria) == 15
    assert trial.exclusion_criteria[10].endswith("double barrier method and vasectomised partner")


def test_should_segment_pmc_full_text_through_the_step(monkeypatch):
    from src.agents.agent1 import pmc_fetcher

    source = "CARMELINA.supplement"
    _use_oracle(monkeypatch, TruthOracle(source))
    monkeypatch.setattr(pmc_fetcher, "pmid_to_pmcid", lambda pmid, timeout=10: "PMC0")
    monkeypatch.setattr(
        pmc_fetcher, "fetch_pmc_fulltext", lambda pmcid, timeout=30: text_of(source)
    )
    criteria = pmc_fetcher.get_pmc_eligibility("0")
    assert criteria == {kind: expected_items(source, kind) for kind in KINDS}
