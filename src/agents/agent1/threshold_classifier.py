"""Stage 2 of the threshold pipeline: criterion text -> classified spans (ADR-032).

    1. decompose (LLM)   eligibility text -> atomic criteria     src/agents/agent1/
    2. classify  (LLM)   criterion -> spans                      this module
    3. structure (code)  span -> Circe                           src/services/value_constraint.py

The dominant failure here is not the silent zero that ADR-031 fought. It is a
*dropped* span: the criterion quietly disappears, the cohort gets larger, and the
count stays plausible, so nothing downstream notices. Measured on the probe, the
model dropped a span in four of four multi-threshold lines. Everything below is
weighted towards recall rather than class accuracy — the numeral recall net (G7)
is the single most load-bearing gate in the file.

The model is never trusted to decide when it is unsure. ADR-032 D4 drops the
taxonomy's ``confidence`` field on purpose: an 8B model's self-report is noise,
and worse, it becomes the channel through which a low-confidence AGE negotiates
its way past REVIEW. Confidence here is read out of the *shape* of the answer by
code (null head, invented head, head inside the operand, unclaimed numeral), and
every gate failure converges on REVIEW with no path back to a class.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, Optional, get_args

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.services.value_constraint import normalize_unit
from src.utils.llm import get_llm

ROOT = Path(__file__).resolve().parents[3]

# Rendered by ``scripts/build_value_taxonomy.py --prompt``, which is a pure function
# of the taxonomy JSON. Checked in rather than rendered at call time so the classifier
# does not import from scripts/; tests/test_threshold_classifier.py re-renders and
# asserts equality, which is what stops the two from drifting apart.
PROMPT_PATH = ROOT / "docs" / "daily_notes" / "tte_value_taxonomy.prompt.txt"
CACHE_DIR = ROOT / "data" / "cache" / "threshold_spans"
DEFAULT_MODEL = "vllm/snuh/hari-q3-8b"
MAX_OUTPUT_TOKENS = 1024

SpanClass = Literal[
    "MEASUREMENT_VALUE", "AGE", "TEMPORAL_WINDOW", "STATE_DURATION",
    "DRUG_DOSE", "SCORE_GRADE", "EVENT_QUANTITY", "REVIEW", "NON_CRITERION",
]
SPAN_CLASSES = frozenset(get_args(SpanClass))

# classes[id=NON_CRITERION].families[].id in docs/daily_notes/tte_value_taxonomy.json.
# Duplicated here so the gates stay importable without reading any artifact; the
# test suite asserts this set still equals the taxonomy's.
NON_CRITERION_FAMILIES = frozenset({
    "statistical_decision_rule", "inclusive_range", "unit_conversion_restatement",
    "definitional_equality", "protocol_or_procedure_name", "spelled_out_count",
    "carve_out_clause", "non_numeric_grade",
})


class ThresholdSpan(BaseModel):
    """One numeric threshold found in a criterion, ready for stage 3 (ADR-032 D1)."""

    threshold_phrase: str
    head: Optional[str] = None
    span_class: SpanClass
    family: Optional[str] = None
    origin: Literal["model", "recall_net"] = "model"
    review_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# The only hand-written part of the prompt; everything above it is the renderer's
# output verbatim. Kept byte-identical to ADR-032 D3 and scripts/probe_criterion_classifier.py
# so the probe's measurements describe this module and not a variant of it.
_HEAD_RULES = """
HEAD IS REQUIRED
  head must be a verbatim substring of the CRITERION below -- copy it, never paraphrase
  and never supply a word the text does not contain.
  If the criterion does not name what the number measures, set head to null and class to
  "REVIEW". A parent bullet you cannot see is not a licence to guess.
  Do NOT supply "age" as a head for a bare unit. If the text does not say age/aged/years
  old, it is not an AGE span.
"""

_EVERY_NUMERAL = """
EVERY NUMERAL
  Every number in the CRITERION must appear in exactly one span, including numbers you
  think are irrelevant. If a number is not a threshold, still emit a span for it with the
  class that says so (NON_CRITERION with its family, or REVIEW). Do not skip it.
"""

_ANSWER_FORM = """
Answer with one JSON object and nothing else:
{"spans": [{"threshold_phrase": "...", "head": "..." or null, "class": "...", "family": null}]}
"""


def taxonomy_prompt() -> str:
    """The checked-in system prompt (ADR-032 D3)."""
    return PROMPT_PATH.read_text()


def instruction_tail(every_numeral: bool = False) -> str:
    """The user-message tail. ``every_numeral`` is off by default on purpose.

    ADR-032's open risks record it as an unvalidated prompt change: it lifted recall
    to zero misses on four sentences, but it also doubles-to-quadruples latency and
    makes the model emit overlapping spans. Leaving it off costs nothing in safety —
    a dropped span becomes a REVIEW span at G7 either way — so the flag exists to be
    measured, not to be switched on before it has been.
    """
    body = _HEAD_RULES + (_EVERY_NUMERAL if every_numeral else "")
    return body + _ANSWER_FORM


def deescape(text: str) -> str:
    """Strip ClinicalTrials.gov comparator escapes before the model ever sees them.

    Not optional. ``\\>``/``\\<`` combined with a verbatim-copy instruction makes the
    model write ``"\\<"`` inside a JSON string, which is an invalid escape sequence and
    kills json.loads. Measured on the 13 probe cases: 5/13 parsed with the escapes
    intact, 13/13 without, and all 8 failures had *correct* classifications. Restoring
    the escapes afterwards is unnecessary — stage 3's _clean() drops backslashes anyway.
    """
    return text.replace("\\", "")


# ---------------------------------------------------------------------------
# Gates (ADR-032 D5/D6). Pure code: no model, no I/O.
# ---------------------------------------------------------------------------

# Ordered longest-spelling-first so "no more than" is not read as "more than" and
# "less than or equal to" is not read as "less than". This regex only has to locate
# where the operand starts; stage 3 owns the op itself.
_COMPARATOR = re.compile(
    r"(?:=?[<>]=?|≤|≥"
    r"|greater\s+than\s+or\s+equal(?:\s+to)?|less\s+than\s+or\s+equal(?:\s+to)?"
    r"|(?:equal|at)\s+or\s+(?:above|below|greater|less|higher|lower)"
    r"|no\s+(?:more|less|greater)\s+than|times\s+higher\s+than"
    r"|at\s+least|at\s+most|up\s+to"
    r"|greater\s+than|less\s+than|higher\s+than|lower\s+than|more\s+than"
    r"|above|below|exceeding|exceeds)",
    re.IGNORECASE,
)

_AGE_WORDS = re.compile(r"\b(age|aged|years? old|year-old|older|younger|adult)\b", re.IGNORECASE)

# The lookbehind is load-bearing: without it the "4" of CD4 and the "1" of HbA1c are
# reported as unclaimed numerals, which the first implementation actually did.
_NUMERAL = re.compile(r"(?<![A-Za-z\d])\d[\d,]*(?:\.\d+)?")

# "10" in 3×10^9/L belongs to the unit, not to a span of its own.
_SCIENTIFIC_TAIL = re.compile(r"[\^*]?\d")

_NULLISH = frozenset({"null", "none", "nil", ""})


def _normalise(text: str) -> str:
    """Comparison form for substring checks: de-escaped, whitespace-folded, lowercased."""
    return " ".join(deescape(text).split()).lower()


def is_headless(criterion: str) -> bool:
    """G1: nothing but comparators, numerals and units is left in the criterion.

    This is the gate the design exists for. It runs on the criterion alone, so a line
    the decomposer stripped of its parent bullet cannot acquire a class no matter what
    the model answers — including the answers the ablation produced, where dropping the
    head requirement made the model put the *unit* in the head slot (head="mm3" for
    "> 1500/mm3", head="months" for ">= 6 months"). Both are real substrings, so a
    substring check alone lets them through.

    Position is deliberately not used. "no word before the comparator" catches 38 of
    1,511 threshold lines and most of them are ordinary AGE sentences ("at least 18
    years old") whose head simply follows the comparator. The unit-aware rule here
    catches 2 of 1,716 (0.1%) — the false-alarm cost was measured before the gate was
    turned on.
    """
    for token in re.split(r"[\s,;:()]+", _COMPARATOR.sub(" ", deescape(criterion))):
        token = token.strip(".-•*")
        if not token or not re.search(r"[A-Za-z]", token):
            continue
        if normalize_unit(token) is not None:
            continue
        # A numeral glued to its unit: 1500/mm3, 4mg/ml, 3×10^9/L.
        tail = re.sub(r"^[\d.,]*(?:[×xX*][\d.,^]*)?", "", token)
        if tail and normalize_unit(tail) is not None:
            continue
        return False
    return True


def _operand_region(phrase: str) -> str:
    """The part of a phrase from its comparator onward: op + value + unit.

    G4 forbids the head from living here. "head must not be inside the phrase" would be
    wrong — "White blood cell count <3×10^9/L" legitimately contains its own head — so
    only the region *after* the comparator is off limits.
    """
    match = _COMPARATOR.search(phrase)
    return _normalise(phrase[match.start():] if match else phrase)


def _review(phrase: str, reason: str, head: str | None = None) -> ThresholdSpan:
    return ThresholdSpan(
        threshold_phrase=phrase, head=head, span_class="REVIEW", review_reason=reason
    )


def _gate_span(raw: Any, criterion: str, haystack: str) -> tuple[ThresholdSpan, tuple[int, int] | None]:
    """G2-G5 on one model span. Returns the span and where it sits in the criterion.

    The range is None when the phrase could not be located, which keeps an
    unlocatable span out of overlap resolution and out of the recall accounting —
    it claims no numerals, so anything it purported to cover is picked up by G7.
    """
    if not isinstance(raw, Mapping):
        return _review(criterion, f"span is not an object (gate 2): {raw!r}"), None

    phrase = raw.get("threshold_phrase")
    klass = raw.get("class")
    head = raw.get("head")
    family = raw.get("family")
    # Observed in 2 of 3 elided-head probe cases: the model writes the JSON literal
    # null as the string "null". Folding it is not leniency, both mean "no head".
    if isinstance(head, str) and head.strip().lower() in _NULLISH:
        head = None
    if not isinstance(head, str):
        head = None

    # G3 first: an unlocatable phrase makes every later check meaningless.
    if not isinstance(phrase, str) or not _normalise(phrase):
        return _review(criterion, f"threshold_phrase is not text (gate 3): {phrase!r}"), None
    phrase = deescape(phrase).strip()
    needle = _normalise(phrase)
    start = haystack.find(needle)
    if start < 0:
        # head is dropped rather than carried: it has not been checked yet, and
        # ThresholdSpan.head promises a verbatim substring.
        return _review(phrase, "threshold_phrase is not a substring of the criterion (gate 3)"), None
    where = (start, start + len(needle))

    if klass not in SPAN_CLASSES:
        return _review(phrase, f"unknown class (gate 2): {klass!r}", head), where
    if klass == "NON_CRITERION":
        if family not in NON_CRITERION_FAMILIES:
            return _review(phrase, f"unknown NON_CRITERION family (gate 2): {family!r}", head), where
    else:
        family = None  # meaningless outside NON_CRITERION (D1); drop rather than reject

    if head is None:
        # A missing head is only honest for the two classes that need no destination.
        if klass not in ("REVIEW", "NON_CRITERION"):
            return _review(phrase, f"null head but class={klass} (gate 4)"), where
    elif _normalise(head) not in haystack:
        return _review(phrase, f"head is not a substring of the criterion (gate 4): {head!r}"), where
    elif _normalise(head) in _operand_region(phrase):
        return _review(phrase, f"head lies inside the operand (gate 4): {head!r}", head), where
    elif klass == "AGE" and not _AGE_WORDS.search(haystack):
        return _review(phrase, "AGE without an age word in the criterion (gate 5)", head), where

    return ThresholdSpan(threshold_phrase=phrase, head=head, span_class=klass, family=family), where


def _unclaimed_numerals(haystack: str, claimed: Sequence[tuple[int, int]]) -> list[str]:
    """G7: numerals in the criterion that no surviving span covers (ADR-032 D6).

    Coverage is checked by offset, not by substring: asking whether "5" appears in the
    concatenated phrases would let a span claiming "150" silently absorb an unrelated
    "5" — and a wrongly-absorbed numeral is exactly the dropped span this net exists
    to catch.
    """
    missed: list[str] = []
    for match in _NUMERAL.finditer(haystack):
        if match.group(0) == "10" and _SCIENTIFIC_TAIL.match(haystack, match.end()):
            continue
        if any(lo <= match.start() and match.end() <= hi for lo, hi in claimed):
            continue
        missed.append(match.group(0))
    return missed


def apply_gates(criterion: str, payload: Mapping[str, Any] | None) -> list[ThresholdSpan]:
    """Run G1-G7 over one model answer. Pure: this is where REVIEW is decided.

    Every failure converges on REVIEW and none of them can produce a class, which is
    the property the whole design is for. A criterion carrying no numeral can return
    an empty list: ADR-032 puts numeral-free conditions ("undetectable", "NYHA III/IV")
    out of scope, and synthesising a REVIEW for each of them would bury the gap report
    under every prose criterion in the protocol.
    """
    criterion = deescape(criterion)
    haystack = _normalise(criterion)

    if is_headless(criterion):
        return [_review(criterion, "criterion is headless (gate 1)")]

    spans = payload.get("spans") if isinstance(payload, Mapping) else None
    if not isinstance(spans, list):
        return [_review(criterion, "model returned no span list (gate 0)")]

    located: list[tuple[tuple[int, int], ThresholdSpan]] = []
    unlocated: list[ThresholdSpan] = []
    for raw in spans:
        span, where = _gate_span(raw, criterion, haystack)
        if where is None:
            unlocated.append(span)
        elif _NUMERAL.search(haystack, *where) or _COMPARATOR.search(haystack[where[0]:where[1]]):
            located.append((where, span))
        # else: a phrase with neither numeral nor comparator ("prior to screening").
        # EVERY NUMERAL makes the model emit these; they carry no threshold, and the
        # numerals they should have covered come back through G7.

    # G6: overlapping phrases are one threshold described twice ("blood donation or
    # blood loss > 500 mL" and "> 500 mL"). Longest wins.
    kept: list[tuple[tuple[int, int], ThresholdSpan]] = []
    for where, span in sorted(located, key=lambda item: item[0][0] - item[0][1]):
        if not any(where[0] < hi and lo < where[1] for lo, hi in (k[0] for k in kept)):
            kept.append((where, span))
    kept.sort(key=lambda item: item[0])

    result = [span for _, span in kept] + unlocated
    result += [
        ThresholdSpan(
            threshold_phrase=numeral,
            span_class="REVIEW",
            origin="recall_net",
            review_reason="unclaimed numeral",
        )
        for numeral in _unclaimed_numerals(haystack, [where for where, _ in kept])
    ]
    return result


# ---------------------------------------------------------------------------
# Model call + content-addressed cache (ADR-032 D2/D7)
# ---------------------------------------------------------------------------

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict[str, Any] | None:
    match = _JSON_OBJECT.search(raw)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _cache_path(cache_dir: Path, prompt: str, criterion: str, model: str) -> Path:
    """sha256(prompt + criterion + model). Prompt changes invalidate the cache for free.

    temperature=0 plus a seed is not reproducibility: vLLM's continuous batching lets
    reduction order vary with batch composition, so two identical requests can differ.
    Determinism here comes from the cache, following data/cache/agent1_ir/.
    """
    digest = hashlib.sha256(f"{prompt}\x00{criterion}\x00{model}".encode()).hexdigest()[:16]
    return cache_dir / f"{model.replace('/', '_')}_{digest}.json"


def _complete(criterion: str, llm: BaseChatModel, model: str, every_numeral: bool,
              cache_dir: Path | None) -> dict[str, Any] | None:
    """G0: one criterion, one call, one retry on unparseable output."""
    system = taxonomy_prompt()
    tail = instruction_tail(every_numeral)
    prompt = system + tail

    path = _cache_path(cache_dir, prompt, criterion, model) if cache_dir else None
    if path is not None and path.exists():
        return _extract_json(json.loads(path.read_text())["raw"])

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"CRITERION\n{criterion}\n{tail}"),
    ]
    raw = ""
    payload = None
    for _ in range(2):
        content = llm.invoke(messages, max_tokens=MAX_OUTPUT_TOKENS).content
        raw = content if isinstance(content, str) else str(content)
        payload = _extract_json(raw)
        if payload is not None:
            break

    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"model": model, "criterion": criterion, "raw": raw}, ensure_ascii=False, indent=2
        ))
    return payload


def classify_criterion(
    text: str,
    llm: BaseChatModel | None = None,
    *,
    model: str = DEFAULT_MODEL,
    every_numeral: bool = False,
    cache_dir: Path | None = CACHE_DIR,
) -> list[ThresholdSpan]:
    """Classify one criterion line into threshold spans (ADR-032 D1).

        for span in classify_criterion(criterion.source_text):
            if span.span_class != "MEASUREMENT_VALUE":
                continue                      # D8: REVIEW never reaches stage 3
            for vc in parse_value_constraints(span.threshold_phrase):
                criteria_attrs.update(build_measurement_value_filter(vc))

    One criterion per call, never a whole study: a truncated JSON answer is a parse
    failure, and batching makes one truncation erase every span in the study. The
    taxonomy prefix costs 0.3s per call to resend, which is the entire saving batching
    would have bought.
    """
    criterion = deescape(text)
    return apply_gates(
        criterion,
        _complete(criterion, llm or get_llm(model), model, every_numeral, cache_dir),
    )


def classify_criteria(
    texts: Sequence[str],
    llm: BaseChatModel | None = None,
    *,
    model: str = DEFAULT_MODEL,
    every_numeral: bool = False,
    cache_dir: Path | None = CACHE_DIR,
    max_workers: int = 8,
) -> list[list[ThresholdSpan]]:
    """Classify a batch of criteria, output aligned to input order (ADR-016).

    A shared model object is reused across the pool; ``Executor.map`` is what makes
    the ordering deterministic regardless of completion order.
    """
    shared = llm or get_llm(model)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(
            lambda text: classify_criterion(
                text, shared, model=model, every_numeral=every_numeral, cache_dir=cache_dir
            ),
            texts,
        ))
