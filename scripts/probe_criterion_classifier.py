#!/usr/bin/env python3
"""Probe the stage-2 criterion classifier design against the live vLLM model.

Reproduces every model-derived number in ADR-032. Read-only: it writes nothing
under ``src/``, touches no store and creates no cohort.

    python scripts/probe_criterion_classifier.py --budget      # context arithmetic
    python scripts/probe_criterion_classifier.py --run         # one call per probe case
    python scripts/probe_criterion_classifier.py --repeat 3    # determinism check
    python scripts/probe_criterion_classifier.py --elided      # elided-head frequency

The prompt is the taxonomy renderer's output verbatim (``build_value_taxonomy
--prompt``) plus a fixed instruction tail, so this probe cannot drift from the
artifact the classifier would ship with.
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.settings import settings  # noqa: E402
from src.services.value_constraint import normalize_unit  # noqa: E402
from src.utils.llm import get_llm  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

MODEL = "vllm/snuh/hari-q3-8b"
MAX_MODEL_LEN = 16384

# The instruction tail is the only hand-written part of the prompt. Everything
# above it is rendered from docs/daily_notes/tte_value_taxonomy.json.
INSTRUCTION_TAIL = """
HEAD IS REQUIRED
  head must be a verbatim substring of the CRITERION below -- copy it, never paraphrase
  and never supply a word the text does not contain.
  If the criterion does not name what the number measures, set head to null and class to
  "REVIEW". A parent bullet you cannot see is not a licence to guess.
  Do NOT supply "age" as a head for a bare unit. If the text does not say age/aged/years
  old, it is not an AGE span.

Answer with one JSON object and nothing else:
{"spans": [{"threshold_phrase": "...", "head": "..." or null, "class": "...", "family": null}]}
"""

# Same request, with the head requirement removed. Isolates how much of the
# elided-head behaviour comes from the taxonomy prompt alone.
ABLATION_TAIL = """
Answer with one JSON object and nothing else:
{"spans": [{"threshold_phrase": "...", "head": "..." or null, "class": "...", "family": null}]}
"""

# Probe cases. Each is a real eligibility line; `why` records what it tests.
# `expect` is the human reading, used only for reporting -- the probe does not score.
CASES: list[dict[str, Any]] = [
    {
        "id": "multi-5-span",
        "why": "densest corpus line: 5 thresholds, one of them an implicit-multiplier LLN",
        "text": (
            "White blood cell count \\<3×10\\^9/L; neutrophil count\\<1.5×10\\^9/L; "
            "platelet count\\<90×10\\^9/L; hemoglobin below the lower limit of normal; "
            "serum creatine kinase (CK) \\>3×ULN"
        ),
        "expect": "5 spans, all MEASUREMENT_VALUE",
    },
    {
        "id": "lvef-value-plus-window",
        "why": "the multi-label case the taxonomy limits call out: one line, two destinations",
        "text": "LVEF \\< 40% measured within 6 months prior to randomization",
        "expect": "2 spans: MEASUREMENT_VALUE (LVEF) + TEMPORAL_WINDOW (6 months)",
    },
    {
        "id": "elided-head-child",
        "why": "THE failure this design exists to stop: child bullet, analyte in an unseen parent",
        "text": "\\> 1500/mm3",
        "expect": "1 span, class REVIEW, head null",
    },
    {
        "id": "elided-head-child-platelet",
        "why": "same, with a count that looks like nothing else",
        "text": "\\< 100,000/mm3",
        "expect": "1 span, class REVIEW, head null",
    },
    {
        "id": "elided-head-time-unit",
        "why": "the elided-head rule's own trigger: a bare time unit with no head at all",
        "text": "\\>= 6 months",
        "expect": "1 span, class REVIEW, head null -- NOT AGE",
    },
    {
        "id": "elided-head-with-parent",
        "why": "control for the above: identical threshold, parent line supplied",
        "text": "Adequate organ function, defined as: absolute neutrophil count \\> 1500/mm3",
        "expect": "1 span, MEASUREMENT_VALUE, head 'absolute neutrophil count'",
    },
    {
        "id": "age-explicit",
        "why": "the head test must beat the anchor: 'at screening' is present but age wins",
        "text": "Age \\>= 18 years at screening",
        "expect": "1 span, AGE",
    },
    {
        "id": "qtc-time-unit",
        "why": "time unit whose head is a measurement -- must not go AGE or TEMPORAL_WINDOW",
        "text": "QTc interval \\> 470 msec on screening ECG",
        "expect": "1 span, MEASUREMENT_VALUE",
    },
    {
        "id": "stat-ci",
        "why": "highest-risk false positive: one word from 'upper limit of normal'",
        "text": (
            "the upper boundary of the two-sided 95.02% confidence interval "
            "for the hazard ratio was less than 1.3"
        ),
        "expect": "NON_CRITERION / statistical_decision_rule",
    },
    {
        "id": "hiv-duration",
        "why": "ADR-031-A's fourth destination: state duration, plus a drug-duration twin",
        "text": (
            "Patients with long-standing (\\>5 years) HIV on antiretroviral therapy "
            "\\> 1 month (undetectable HIV viral load and CD4 count \\> 150 cells/microL) "
            "may be eligible"
        ),
        "expect": "STATE_DURATION x2 + MEASUREMENT_VALUE (CD4)",
    },
    {
        "id": "blood-donation",
        "why": "EVENT_QUANTITY: laboratory-shaped volume attached to an event, not a specimen",
        "text": "Blood donation or blood loss \\> 500 mL within 3 months prior to screening",
        "expect": "EVENT_QUANTITY + TEMPORAL_WINDOW",
    },
    {
        "id": "cups-review",
        "why": "genuine threshold with no CDM destination",
        "text": (
            "Consumption of excessive amounts of tea, coffee, or caffeine-containing "
            "beverages (more than 8 cups per day, 1 cup = 250 mL)"
        ),
        "expect": "REVIEW + NON_CRITERION/definitional_equality",
    },
    {
        "id": "ecog",
        "why": "SCORE_GRADE: no unit may be attached",
        "text": "ECOG performance status \\<= 2",
        "expect": "SCORE_GRADE",
    },
]


def render_taxonomy_prompt() -> str:
    """Import the generator by path (scripts/ is not a package) and render."""
    spec = importlib.util.spec_from_file_location(
        "build_value_taxonomy", ROOT / "scripts" / "build_value_taxonomy.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/build_value_taxonomy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_prompt(module.build())


def token_count(text: str) -> int:
    """Ask the serving vLLM for an exact count; estimation would defeat the point."""
    base = (settings.VLLM_BASE_URL or "").rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    response = httpx.post(
        f"{root}/tokenize",
        json={"model": "snuh/hari-q3-8b", "prompt": text},
        headers={"Authorization": f"Bearer {settings.VLLM_API_KEY or 'EMPTY'}"},
        timeout=60,
    )
    response.raise_for_status()
    return int(response.json()["count"])


def deescape(text: str) -> str:
    """Strip ClinicalTrials.gov comparator escapes before the model ever sees them.

    A verbatim-copy instruction plus an input containing ``\\<`` makes the model
    emit ``"\\<"`` inside a JSON string, which is an invalid escape sequence and
    fails json.loads. Measured: 8 of 12 probe cases, first run.
    """
    return text.replace("\\", "")


def build_messages(system: str, criterion: str, head_rules: bool = True) -> list[Any]:
    tail = INSTRUCTION_TAIL if head_rules else ABLATION_TAIL
    return [
        SystemMessage(content=system),
        HumanMessage(content=f"CRITERION\n{criterion}\n{tail}"),
    ]


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(raw: str) -> dict[str, Any] | None:
    match = _JSON_OBJECT.search(raw)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalise(text: str) -> str:
    """Substring comparison form: de-escape, fold whitespace and case."""
    return " ".join(text.replace("\\", "").split()).lower()


_COMPARATOR = re.compile(
    r"(=?[<>]=?|≤|≥|at or below|equal or above|times higher than|higher than"
    r"|at least|more than|above|below|less than|greater than|no more than)",
    re.IGNORECASE,
)


def operand_region(phrase: str) -> str:
    """The part of a threshold phrase from the comparator onward: op + value + unit.

    A head found only inside this region is not a head -- it is the unit or a digit
    the model reused to satisfy the substring requirement. Measured behaviour, not
    a hypothetical: with the head rules removed the model answered head='mm3' for
    '> 1500/mm3' and head='months' for '>= 6 months'.
    """
    match = _COMPARATOR.search(phrase)
    return normalise(phrase[match.start() :]) if match else normalise(phrase)


def is_headless(criterion: str) -> bool:
    """Nothing is left once the comparator, the numerals and the units are removed.

    Runs before the model answer is read, so a criterion the decomposer stripped of
    its parent bullet cannot acquire a class no matter what the model returns.

    Position is deliberately not used. 'at least 18 years old' puts its head after
    the comparator and is a perfectly resolvable AGE span; 38 of the 1,511
    threshold-bearing lines in data/nct_cache have no word before the comparator and
    most of them are exactly that shape.
    """
    text = _COMPARATOR.sub(" ", criterion)
    for token in re.split(r"[\s,;:()]+", text):
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


def validate(criterion: str, payload: dict[str, Any]) -> list[str]:
    """Return the validation failures ADR-032 D5 would route to REVIEW."""
    problems: list[str] = []
    haystack = normalise(criterion)
    if is_headless(criterion):
        return ["criterion is headless before the comparator -> all spans REVIEW (gate 1)"]
    spans = payload.get("spans")
    if not isinstance(spans, list):
        return ["spans is not a list"]
    for index, span in enumerate(spans):
        if not isinstance(span, dict):
            problems.append(f"span[{index}] is not an object")
            continue
        phrase = span.get("threshold_phrase")
        head = span.get("head")
        klass = span.get("class")
        # Observed: the model sometimes writes the JSON literal null as the string
        # "null". Folding it here is not leniency -- both mean "no head".
        if isinstance(head, str) and head.strip().lower() in ("null", "none", ""):
            head = None
        if not isinstance(phrase, str) or normalise(phrase) not in haystack:
            problems.append(f"span[{index}] threshold_phrase not a substring: {phrase!r}")
        if head is None:
            if klass not in ("REVIEW", "NON_CRITERION"):
                problems.append(f"span[{index}] null head but class={klass}")
        elif not isinstance(head, str) or normalise(head) not in haystack:
            problems.append(f"span[{index}] head not a substring: {head!r}")
        elif isinstance(phrase, str) and normalise(head) in operand_region(phrase):
            problems.append(f"span[{index}] head lies inside the operand: {head!r} (gate 2)")
        elif klass == "AGE" and not re.search(
            r"\b(age|aged|years? old|year-old|older|younger|adult)\b", haystack
        ):
            problems.append(f"span[{index}] AGE without an age word in the text")
    return problems


def numeral_recall(criterion: str, payload: dict[str, Any]) -> list[str]:
    """Numbers present in the criterion but claimed by no span (ADR-032 D6)."""
    text = criterion.replace("\\", "")
    claimed = " ".join(
        str(s.get("threshold_phrase", "")) for s in payload.get("spans", []) if isinstance(s, dict)
    ).replace("\\", "")
    missed: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z\d])\d[\d,]*(?:\.\d+)?", text):
        numeral = match.group(0)
        # A numeral inside scientific notation belongs to the unit, not to a span.
        if re.match(r"\^?\d", text[match.end() : match.end() + 2]) and numeral in ("10",):
            continue
        if numeral not in claimed:
            missed.append(numeral)
    return missed


MAX_OUTPUT_TOKENS = 1024


def run_cases(repeat: int, limit: int | None, head_rules: bool, only: str | None) -> None:
    system = render_taxonomy_prompt()
    llm = get_llm(MODEL)
    cases = [c for c in CASES if only is None or c["id"] == only]
    cases = cases[:limit] if limit else cases
    parsed_ok = 0
    for case in cases:
        criterion = deescape(case["text"])
        print("=" * 78)
        print(f"[{case['id']}] {case['why']}")
        print(f"  input : {criterion}")
        print(f"  human : {case['expect']}")
        outputs: list[str] = []
        for attempt in range(repeat):
            started = time.monotonic()
            response = llm.invoke(
                build_messages(system, criterion, head_rules), max_tokens=MAX_OUTPUT_TOKENS
            )
            elapsed = time.monotonic() - started
            raw = response.content if isinstance(response.content, str) else str(response.content)
            outputs.append(raw)
            if attempt:
                continue
            finish = (response.response_metadata or {}).get("finish_reason")
            payload = extract_json(raw)
            print(f"  wall  : {elapsed:.1f}s  out={token_count(raw)}tok  finish={finish}")
            if payload is None:
                print(f"  PARSE FAILURE\n{raw[:400]}")
                continue
            parsed_ok += 1
            print("  model :", json.dumps(payload, ensure_ascii=False))
            problems = validate(criterion, payload)
            missed = numeral_recall(criterion, payload)
            print("  valid :", "ok" if not problems else "; ".join(problems))
            print("  recall:", "ok" if not missed else f"unclaimed numerals {missed}")
        if repeat > 1:
            identical = len(set(outputs)) == 1
            print(f"  repeat: {repeat} calls, byte-identical={identical}")
            if not identical:
                for i, out in enumerate(outputs):
                    print(f"    [{i}] {out[:300]}")
    print(f"\nparsed {parsed_ok}/{len(cases)}  head_rules={head_rules}")


def budget() -> None:
    system = render_taxonomy_prompt()
    tail = token_count(INSTRUCTION_TAIL)
    system_tokens = token_count(system)
    print(f"taxonomy prompt        : {system_tokens:>6} tokens ({len(system.splitlines())} lines)")
    print(f"instruction tail       : {tail:>6} tokens")
    print(f"max_model_len          : {MAX_MODEL_LEN:>6}")

    lines: list[str] = []
    sizes: list[int] = []
    for path in sorted(glob.glob(str(ROOT / "data" / "nct_cache" / "*.json"))):
        with open(path) as handle:
            data = json.load(handle)
        text = (data.get("protocolSection", {}).get("eligibilityModule", {}) or {}).get(
            "eligibilityCriteria"
        )
        if not text:
            continue
        sizes.append(len(text))
        lines.extend(line.strip() for line in text.split("\n") if line.strip())
    longest_study = max(
        (
            (data.get("protocolSection", {}).get("eligibilityModule", {}) or {}).get(
                "eligibilityCriteria"
            )
            or ""
            for data in (
                json.load(open(p))
                for p in sorted(glob.glob(str(ROOT / "data" / "nct_cache" / "*.json")))
            )
        ),
        key=len,
    )
    longest_line = max(lines, key=len)
    print(f"\ncached protocols       : {len(sizes)}")
    print(f"eligibility chars      : median {statistics.median(sizes):.0f}, max {max(sizes)}")
    print(f"longest study tokens   : {token_count(longest_study)}")
    print(f"criterion lines        : {len(lines)}")
    print(f"line chars             : median {statistics.median(len(x) for x in lines):.0f}, max {len(longest_line)}")
    print(f"longest line tokens    : {token_count(longest_line)}")
    per_criterion = system_tokens + tail + token_count(longest_line)
    per_study = system_tokens + tail + token_count(longest_study)
    print(f"\nper-criterion input    : {per_criterion} -> {MAX_MODEL_LEN - per_criterion} for output")
    print(f"per-study input        : {per_study} -> {MAX_MODEL_LEN - per_study} for output")


def elided_head_frequency() -> None:
    """How often does a threshold line carry no analyte name of its own?

    Approximate by construction: a line that has a comparator and a number but no
    alphabetic token before the comparator has nothing for the head test to find.
    """
    total = 0
    headless = 0
    examples: list[str] = []
    for path in sorted(glob.glob(str(ROOT / "data" / "nct_cache" / "*.json"))):
        with open(path) as handle:
            data = json.load(handle)
        text = (data.get("protocolSection", {}).get("eligibilityModule", {}) or {}).get(
            "eligibilityCriteria"
        )
        if not text:
            continue
        for raw_line in text.split("\n"):
            line = deescape(raw_line.strip())
            if not _COMPARATOR.search(line) or not re.search(r"\d", line):
                continue
            total += 1
            if is_headless(line):
                headless += 1
                if len(examples) < 15:
                    examples.append(line[:110])
    share = headless / total if total else 0.0
    print(f"threshold-bearing lines: {total}")
    print(f"no head before the comparator: {headless} ({share:.1%})")
    for example in examples:
        print(f"  {example!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", action="store_true", help="context arithmetic only")
    parser.add_argument("--run", action="store_true", help="one model call per probe case")
    parser.add_argument("--repeat", type=int, default=1, help="calls per case (determinism)")
    parser.add_argument("--limit", type=int, default=None, help="first N cases only")
    parser.add_argument("--elided", action="store_true", help="elided-head frequency scan")
    parser.add_argument("--prompt", action="store_true", help="print the full prompt")
    parser.add_argument("--only", type=str, default=None, help="run a single case id")
    parser.add_argument(
        "--no-head-rules",
        action="store_true",
        help="ablation: drop the head requirement from the instruction tail",
    )
    args = parser.parse_args()

    if args.prompt:
        print(render_taxonomy_prompt() + INSTRUCTION_TAIL)
        return
    if args.budget:
        budget()
        return
    if args.elided:
        elided_head_frequency()
        return
    if args.run or args.repeat > 1 or args.only:
        run_cases(args.repeat, args.limit, not args.no_head_rules, args.only)
        return
    parser.print_help()


if __name__ == "__main__":
    main()
