"""Survey numeric-threshold phrasings across the cached ClinicalTrials.gov corpus.

Reports (a) distinct comparator/unit/reference-bound phrasings, (b) a saturation
curve so we can tell when fetching more protocols stops yielding new patterns.

Usage:
    .venv/bin/python scripts/survey_threshold_phrases.py [--dump-uln] [--dump-units]
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "data" / "nct_cache"

# A criterion line is a threshold candidate when it pairs a comparator with a number.
COMPARATORS = r"(?:[<>≤≥=]=?|=<|=>|≦|≧|at least|no more than|greater than|less than|exceeding|above|below|under|over)"
NUMBER = r"\d+(?:[.,]\d+)?"
THRESHOLD_RE = re.compile(rf"{COMPARATORS}\s*~?\s*{NUMBER}", re.IGNORECASE)

# Reference-bound phrasings: the multiplier form that must NOT become an absolute value.
REF_BOUND_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:[x×\*]|times|-fold|fold)\s*)?"
    r"(?:the\s+)?(?:institutional\s+|local\s+|laboratory\s+|central\s+lab\s+)?"
    r"(?:upper|lower)\s+limits?\s+of\s+(?:the\s+)?normal"
    r"|(?<![A-Za-z])[xX×]\s*ULN"
    r"|(?<![A-Za-z])ULN(?![A-Za-z])"
    r"|(?<![A-Za-z])LLN(?![A-Za-z])",
    re.IGNORECASE,
)

UNIT_RE = re.compile(
    r"(?<=\d)\s*"
    r"(%|kg/m\s?[²2]|mg/dL|mmol/L|µmol/L|umol/L|mL/min/1\.73\s?m\s?[²2]|mL/min|ml/min|"
    r"g/dL|g/L|U/L|IU/L|mmHg|mV|ng/L|ng/mL|pg/mL|µg/L|10\^9/L|x\s?10\^?9/L|cells/mm3|/mm3|"
    r"kg|cm|years?|months?|weeks?|days?|hours?|mL|L|bpm|mg|IU|mIU/L|mEq/L)",
    re.IGNORECASE,
)


def criteria_lines(text: str) -> list[str]:
    """Split an eligibilityCriteria blob into individual criterion lines."""
    out: list[str] = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip().lstrip("*-•o ").strip()
        if len(line) > 3:
            out.append(line)
    return out


def signature(line: str) -> tuple[str, ...]:
    """A phrasing signature: which comparator/unit/reference tokens the line uses."""
    norm = unicodedata.normalize("NFKC", line)
    toks = set()
    for m in THRESHOLD_RE.finditer(norm):
        comp = re.match(rf"\s*{COMPARATORS}", m.group(0), re.IGNORECASE)
        if comp:
            toks.add("cmp:" + comp.group(0).strip().lower())
    for m in UNIT_RE.finditer(norm):
        toks.add("unit:" + m.group(1).strip().lower())
    for m in REF_BOUND_RE.finditer(norm):
        toks.add("ref:" + re.sub(r"\s+", " ", m.group(0).strip().lower()))
    return tuple(sorted(toks))


def main() -> None:
    files = sorted(CACHE.glob("NCT*.json"))
    seen: set[tuple[str, ...]] = set()
    curve: list[tuple[int, int, int]] = []
    uln_phrases: Counter[str] = Counter()
    units: Counter[str] = Counter()
    comparators: Counter[str] = Counter()
    total_lines = 0

    for idx, path in enumerate(files, 1):
        record = json.loads(path.read_text(encoding="utf-8"))
        text = (
            record.get("protocolSection", {})
            .get("eligibilityModule", {})
            .get("eligibilityCriteria", "")
        )
        for line in criteria_lines(text):
            if not THRESHOLD_RE.search(unicodedata.normalize("NFKC", line)):
                continue
            total_lines += 1
            sig = signature(line)
            if sig:
                seen.add(sig)
            for tok in sig:
                kind, _, val = tok.partition(":")
                {"ref": uln_phrases, "unit": units, "cmp": comparators}[kind][val] += 1
        curve.append((idx, len(seen), total_lines))

    print(f"protocols: {len(files)}   threshold lines: {total_lines}   distinct signatures: {len(seen)}")
    print("\nsaturation curve (protocol#, cumulative distinct signatures, cumulative lines)")
    for i, n, t in curve:
        if i % 5 == 0 or i == len(curve):
            print(f"  {i:3d}  {n:4d}  {t:5d}")

    if "--dump-uln" in sys.argv:
        print("\nreference-bound phrasings:")
        for phrase, n in uln_phrases.most_common():
            print(f"  {n:4d}  {phrase!r}")
    if "--dump-units" in sys.argv:
        print("\nunit spellings:")
        for unit, n in units.most_common():
            print(f"  {n:4d}  {unit!r}")
        print("\ncomparators:")
        for c, n in comparators.most_common():
            print(f"  {n:4d}  {c!r}")


if __name__ == "__main__":
    main()
