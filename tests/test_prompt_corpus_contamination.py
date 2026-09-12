"""A prompt must not quote the studies the pipeline is scored on.

A few-shot example lifted from an evaluated trial breaks the measurement in two
directions at once. The source study's score is inflated, because its answer is
sitting in the prompt and a correct output may be a copy rather than a read. And
every *other* study is polluted, because the example is a template the model
transplants: measured on 2026-09-12, the planner prompt carried ARISTOTLE's own
exclusion "ALT or AST > 2X ULN or Total Bilirubin >= 1.5X ULN" verbatim, and
CARMELINA acquired a total-bilirubin exclusion at exactly 1.5 that appears zero
times in its PDFs, its ClinicalTrials.gov record, and all eleven of its Agent-1
IR caches.

Substituting one analyte for another does not fix that; it moves it. This file
is the rule instead of the substitution: every string that reaches an LLM is
compared, character by character, against the six evaluated trials' own text.

WHAT IS COMPARED
----------------
Prompt side: every non-docstring string literal under ``src/`` that reaches an
LLM, found mechanically (see ``_PROMPT_NAME``) rather than from a hand-kept list,
so a prompt added in a new module is covered on the day it lands.

Corpus side: the six trials' ClinicalTrials.gov eligibility text, their gold
criterion names and descriptions, and — when ``pdftotext`` is on PATH — the
protocol PDFs under ``data/papers/``. All three are plain file reads; nothing
here needs an LLM, a database, or the GPU.

MATCHING RULE, AND WHAT IT MISSES
---------------------------------
Both sides are NFKC-normalised, lowercased, ASCII-folded for dashes and quotes,
and have every whitespace run collapsed to one space. Exact substring matching
on the raw text is too strict -- production converts PDFs with plain
``pdftotext``, which breaks criterion sentences mid-phrase, so "Troponin I or T
or CK-MB greater\nthan the upper limit of normal" would not match a prompt that
writes it on one line. Token-overlap scoring is too loose -- it would score
"HbA1c" against a diabetes-trial prompt that has every reason to say "HbA1c".

The rule therefore finds maximal *character* spans shared by a prompt string and
a corpus document, seeded on a 12-character window. It misses: a shared span
shorter than 12 characters; a paraphrase (the model was told the meaning of a
criterion in different words); a number quoted without its analyte more than 11
characters away; and a paraphrase of a number ("two times" for "2x"). ``≥`` and
``>=`` ARE folded together -- see ``_TRANSLATE`` -- because a protocol writes one
and a prompt author types the other, and leaving them unfolded silently lost
CARMELINA's own "Age >= 18 years. For Japan only: Age >= 20 years" from the
sweep.

THE TWO GATES, AND WHY THERE IS NO SINGLE THRESHOLD
---------------------------------------------------
There is no span length that separates contamination from legitimate clinical
vocabulary. Measured on this tree: the longest *benign* shared span is 48
characters ("placebo-controlled cardiovascular outcome trial", in the comparator
prompt) and the longest in the abbreviation glossary is 47 (", eGFR = estimated
glomerular filtration rate, "), while real contamination started as low as 32
("moderate or severe liver disease", PLATO's own exclusion). A length-only gate
set safely above the vocabulary ceiling would sit above a third of the real
findings. So the gates key on SHAPE as well as length:

  Gate A -- a shared span of >= 12 characters carrying a comparator and a
  complete number (one not cut by the span boundary -- see
  ``_carries_a_whole_number``). This is the mechanism measured above: a
  threshold bound to an analyte. A clinical *term* never contains a comparator,
  so this gate has no vocabulary false-positive class at all.

  Gate B -- a shared span of >= 30 characters carrying at least one protocol
  connective (``_CONNECTIVES``). A term is a noun phrase; a criterion is a
  sentence, and the connectives are what make it one. Measured on this tree the
  longest benign connective-bearing shared span is 29 characters ("not
  statistically significant", in a report-narrative prompt), so the margin here
  is ONE character. That is thin, and it is why ``ALLOWED_SPANS`` exists: the
  honest way to absorb a benign 30-character connective-bearing phrase is to
  name it there with a reason, not to raise the threshold until the gate stops
  finding things.

WHAT THIS MEASURED
------------------
Against the tree as of commit 4aa1f08, Gate A fired on 18 distinct spans and
Gate B on 27, across ARISTOTLE, PLATO, CAROLINA, CARMELINA and LEADER. After the
replacements that landed with this file, both fire on zero, with two spans named
in ``ALLOWED_SPANS``.

``ALLOWED_SPANS`` is not a knob for silencing a finding -- adding an entry is a
claim that a span is universal clinical or structural English, and that claim
belongs next to the entry in writing.

WHAT THIS STILL WILL NOT CATCH
------------------------------
Two real HEAD findings escaped BOTH gates and were only visible because another
fragment of the same sentence did fire: "ing an acceptable method of birth
control" (41 characters) and "pre-menopausal women (last menstruation "
(40) -- noun-phrase fragments of a criterion, carrying neither a threshold nor a
connective. A gate tuned to catch those on their own would also catch
"placebo-controlled cardiovascular outcome trial" (48) and ", eGFR = estimated
glomerular filtration rate, " (47), which are not borrowings at all. Recall here
is per-sentence, not per-fragment.

PER-TRIAL COUNTS CANNOT BE READ OFF A COMBINED RUN
--------------------------------------------------
``_shared_spans`` keeps only the MAXIMAL span at each prompt position and
attributes it to one document. Where several trials word a criterion alike, the
trial with the longest wording wins the attribution and the others vanish from
the output entirely -- they are masked, not absent.

Measured: on the pre-sweep tree the combined run attributed ZERO spans to
EMPA-REG OUTCOME, and it looked like the one clean trial. Run against EMPA-REG's
corpus ALONE, the same detector flags six, including its own exclusions
"uncontrolled hyperglycaemia with a glucose level " (49) and "e of thyroid
hormones within 6 weeks prior " (43). CAROLINA and CARMELINA simply state those
criteria at greater length and took the attribution.

So: this file answers "is any evaluated trial's text in the prompts", which is
what the gates need. It does NOT answer "is trial X's text in the prompts". For
that, re-run ``_shared_spans`` with the corpus filtered to X, and never quote a
per-trial zero from a combined run as evidence that X is uncontaminated.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: The six trials the pipeline is scored against, and their protocol directories.
EVALUATED_TRIALS = {
    "ARISTOTLE": "NCT00412984",
    "PLATO": "NCT00391872",
    "LEADER": "NCT01179048",
    "CAROLINA": "NCT01243424",
    "EMPA-REG OUTCOME": "NCT01131676",
    "CARMELINA": "NCT01897532",
}

SEED = 12
GATE_A_MIN_LEN = 12
GATE_B_MIN_LEN = 30

#: Benign spans, each with the reason it is benign. An entry is a CLAIM that the
#: span is universal clinical or structural English rather than a criterion the
#: pipeline is scored on -- write the reason beside it, and note that a false
#: justification here is the one way a real finding can be hidden.
#:
#: Spans are compared in normalized form: lowercased, whitespace-collapsed, with
#: "≥"/"≤" folded to ">="/"<=".
ALLOWED_SPANS: frozenset[str] = frozenset(
    {
        # The adult-age floor. It is ARISTOTLE's and CARMELINA's inclusion
        # criterion, and also almost every other trial's, so a prompt using it as
        # a Demographics example is not borrowing from a scored study. Unlike a
        # lab multiplier, it cannot mint a wrong criterion: transplanting "adults
        # only" into another trial changes nothing, because that trial has it too.
        "age >= 18 years",
        # A bare enumeration quantifier with no clinical content of its own. It
        # heads composite-OR criteria in most of the corpus and in the Pattern E
        # instruction alike; the members after the colon are what carry meaning,
        # and those are synthesised.
        " with >=1 of",
    }
)

_COMPARATOR = re.compile(
    r"(>=|<=|>|<|≥|≤|\bgreater than\b|\bless than\b|\bat least\b|"
    r"\bat most\b|\bno more than\b|\babove\b|\bbelow\b|\bx uln\b|\bx lln\b)"
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _carries_a_whole_number(span: str) -> bool:
    """True when a complete number sits strictly inside ``span``.

    A digit run touching either edge was cut by the span boundary, so the two
    sides did not actually share that number. Without this, a prompt saying
    "duration > 14 years" matches CAROLINA's "duration > 10 years" on the
    13-character prefix "duration > 1" and reports a threshold nobody shares.
    """
    return any(
        match.start() > 0 and match.end() < len(span)
        for match in _NUMBER.finditer(span)
    )

#: The words that turn a noun phrase into a protocol sentence. Deliberately
#: small: every addition widens Gate B and every omission narrows it.
_CONNECTIVES = frozenset(
    """or and with without who not than within prior after before unless must
    using either least greater above below per whose while during""".split()
)

#: A string literal reaches an LLM when it is assigned to a name of this shape,
#: or is a message-tuple / message-object argument (see ``_prompt_strings``).
_PROMPT_NAME = re.compile(
    r"(?i)(^|[._])(prompt|template|instruction|instructions|examples?|rubric"
    r"|guidance|few_?shot|system|user)s?($|[._(])"
)

_TRANSLATE = {}
for _ch in "‐‑‒–—―−":
    _TRANSLATE[ord(_ch)] = "-"
for _ch in "‘’‛′":
    _TRANSLATE[ord(_ch)] = "'"
for _ch in "“”„″":
    _TRANSLATE[ord(_ch)] = '"'
#: A protocol writes "≥" and a prompt author types ">=". They are the same
#: operator, and thresholds are exactly where the borrowing happens, so the two
#: renderings are folded. This expands one character into two -- it does NOT
#: turn ">" into ">=", because ">" is left alone.
_TRANSLATE[ord("≥")] = ">="
_TRANSLATE[ord("≤")] = "<="


def _normalize(text: str) -> tuple[str, list[int], str]:
    """Fold the two renderings together; keep a map back to the source.

    Returns ``(normalized, offsets, source)`` where ``source`` is the NFKC form
    of ``text`` and ``offsets[i]`` is the index in ``source`` that
    ``normalized[i]`` came from, so a finding can be quoted close to how it was
    written rather than as it was compared.

    ``source`` is returned rather than the caller re-using ``text`` because both
    steps here can change length: NFKC expands compatibility characters, and
    ``str.lower`` is not always length-preserving (``"İ".lower()`` is two code
    points). An offset list built as if either were 1:1 drifts silently and
    quotes the wrong span of the wrong document -- which is how this function
    was first written, and the drift only showed up because a failing gate
    printed a corpus quote that had nothing to do with its prompt quote.
    """
    source = unicodedata.normalize("NFKC", text)
    out: list[str] = []
    offsets: list[int] = []
    prev_space = True
    for index, char in enumerate(source):
        folded = char.translate(_TRANSLATE)
        if folded.isspace():
            if prev_space:
                continue
            out.append(" ")
            offsets.append(index)
            prev_space = True
            continue
        prev_space = False
        for lowered in folded.lower():
            out.append(lowered)
            offsets.append(index)
    while out and out[-1] == " ":
        out.pop()
        offsets.pop()
    assert len(out) == len(offsets)
    return "".join(out), offsets, source


def _llm_bound_literals(tree: ast.AST) -> set[int]:
    """ids of the string Constants in ``tree`` that end up in an LLM message."""
    bound: set[int] = set()

    def claim(node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                bound.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            names += [t.attr for t in targets if isinstance(t, ast.Attribute)]
            if node.value is not None and any(_PROMPT_NAME.search(n) for n in names):
                claim(node.value)
        elif isinstance(node, ast.Tuple) and len(node.elts) == 2:
            role, content = node.elts
            if isinstance(role, ast.Constant) and role.value in (
                "system",
                "user",
                "human",
                "assistant",
            ):
                claim(content)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None) or ""
            if name in (
                "SystemMessage",
                "HumanMessage",
                "AIMessage",
                "from_template",
                "from_messages",
            ):
                claim(node)
            elif name and _PROMPT_NAME.search(name):
                for keyword in node.keywords:
                    claim(keyword.value)
    return bound


def _docstring_literals(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _prompt_strings() -> list[dict]:
    """Every string literal under ``src/`` that reaches an LLM."""
    rows: list[dict] = []
    for path in sorted(REPO.glob("src/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bound = _llm_bound_literals(tree)
        docstrings = _docstring_literals(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) not in bound or id(node) in docstrings:
                continue
            if len(node.value.strip()) < SEED:
                continue
            rows.append(
                {
                    "file": str(path.relative_to(REPO)),
                    "line": node.lineno,
                    "text": node.value,
                }
            )
    seen: set[tuple] = set()
    unique = []
    for row in rows:
        key = (row["file"], row["line"], row["text"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def _gold_criterion_text(payload) -> list[str]:
    """The human-written fields of a gold study: names and descriptions."""
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in ("name", "description") and isinstance(value, str):
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def _corpus() -> dict[str, str]:
    """The evaluated trials' own text, by source. Plain file reads only."""
    docs: dict[str, str] = {}

    for trial, nct in EVALUATED_TRIALS.items():
        record = REPO / "data" / "nct_cache" / f"{nct}.json"
        if record.exists():
            payload = json.loads(record.read_text(encoding="utf-8"))
            criteria = (
                payload.get("protocolSection", {})
                .get("eligibilityModule", {})
                .get("eligibilityCriteria", "")
            )
            if criteria:
                docs[f"{trial} / ClinicalTrials.gov eligibility"] = criteria

    gold_root = REPO / "data" / "gold"
    if gold_root.is_dir():
        for study_dir in sorted(gold_root.iterdir()):
            if not study_dir.is_dir():
                continue
            for definition in sorted(study_dir.glob("*.json")):
                text = "\n".join(
                    _gold_criterion_text(json.loads(definition.read_text(encoding="utf-8")))
                )
                if text:
                    docs[f"{study_dir.name} / gold:{definition.name}"] = text

    if shutil.which("pdftotext"):
        for trial, nct in EVALUATED_TRIALS.items():
            for pdf in sorted((REPO / "data" / "papers" / nct).glob("*.pdf")):
                completed = subprocess.run(
                    ["pdftotext", str(pdf), "-"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.stdout:
                    docs[f"{trial} / pdf:{pdf.name}"] = completed.stdout
    return docs


def _shared_spans(prompts: list[dict], docs: dict[str, str]) -> list[dict]:
    """Maximal character spans shared by a prompt string and a corpus document."""
    normalized_prompts = []
    for row in prompts:
        text, offsets, source = _normalize(row["text"])
        if len(text) >= SEED:
            normalized_prompts.append(
                {**row, "norm": text, "offsets": offsets, "source": source}
            )

    wanted: set[str] = set()
    for row in normalized_prompts:
        text = row["norm"]
        for i in range(len(text) - SEED + 1):
            wanted.add(text[i : i + SEED])

    normalized_docs: dict[str, tuple[str, list[int], str]] = {}
    index: dict[str, list[tuple[str, int]]] = {}
    for name, raw in docs.items():
        text, offsets, source = _normalize(raw)
        normalized_docs[name] = (text, offsets, source)
        for i in range(len(text) - SEED + 1):
            gram = text[i : i + SEED]
            if gram in wanted:
                index.setdefault(gram, []).append((name, i))

    findings: list[dict] = []
    for row in normalized_prompts:
        text, raw, offsets = row["norm"], row["source"], row["offsets"]
        spans: dict[tuple[int, int], tuple[str, int]] = {}
        for i in range(len(text) - SEED + 1):
            for doc_name, doc_pos in index.get(text[i : i + SEED], ())[:40]:
                doc_text, _, _ = normalized_docs[doc_name]
                right_p, right_d = i + SEED, doc_pos + SEED
                while (
                    right_p < len(text)
                    and right_d < len(doc_text)
                    and text[right_p] == doc_text[right_d]
                ):
                    right_p += 1
                    right_d += 1
                left_p, left_d = i, doc_pos
                while left_p > 0 and left_d > 0 and text[left_p - 1] == doc_text[left_d - 1]:
                    left_p -= 1
                    left_d -= 1
                spans.setdefault((left_p, right_p), (doc_name, left_d))

        kept: list[tuple[int, int]] = []
        for start, end in sorted(spans, key=lambda k: (k[0], -k[1])):
            if any(start >= a and end <= b for a, b in kept):
                continue
            kept.append((start, end))

        for start, end in kept:
            doc_name, doc_start = spans[(start, end)]
            _, doc_offsets, doc_source = normalized_docs[doc_name]
            length = end - start
            findings.append(
                {
                    "file": row["file"],
                    "line": row["line"],
                    "length": length,
                    "normalized": text[start:end],
                    "prompt_quote": raw[offsets[start] : offsets[end - 1] + 1],
                    "doc": doc_name,
                    "doc_quote": doc_source[
                        doc_offsets[doc_start] : doc_offsets[doc_start + length - 1] + 1
                    ],
                }
            )
    return findings


@lru_cache(maxsize=1)
def _analysis() -> tuple[tuple[dict, ...], tuple[str, ...]]:
    docs = _corpus()
    if not docs:
        pytest.skip(
            "no evaluated-trial corpus on this host: data/nct_cache/, data/gold/ and "
            "data/papers/ are all absent or empty, so nothing can be compared"
        )
    return tuple(_shared_spans(_prompt_strings(), docs)), tuple(sorted(docs))


def _report(findings: list[dict], gate: str) -> str:
    lines = [f"{len(findings)} prompt span(s) failed {gate}:"]
    for finding in sorted(findings, key=lambda f: -f["length"]):
        lines += [
            "",
            f"  {finding['file']}:{finding['line']}  ({finding['length']} chars)",
            f"    prompt: {finding['prompt_quote']!r}",
            f"    corpus: {finding['doc_quote']!r}",
            f"    source: {finding['doc']}",
        ]
    lines += [
        "",
        "Replace the borrowed text with a synthesised line that teaches the same",
        "shape -- an invented protocol sentence cannot be in the corpus by",
        "construction. Substituting one analyte for another moves the defect; it",
        "does not remove it. If the span is genuinely ordinary clinical or",
        "statistical English, add it to ALLOWED_SPANS with the reason written out.",
    ]
    return "\n".join(lines)


def test_the_evaluated_corpus_actually_loaded() -> None:
    """A check with an empty corpus passes everything. Prove it is not empty."""
    findings, sources = _analysis()
    trials_seen = {trial for trial in EVALUATED_TRIALS for s in sources if s.startswith(trial)}
    missing = set(EVALUATED_TRIALS) - trials_seen
    assert not missing, (
        f"no corpus document loaded for {sorted(missing)}; the gates below would "
        f"pass vacuously for those trials. Loaded sources: {list(sources)}"
    )
    assert findings, (
        "the matcher produced no shared spans at all against "
        f"{len(sources)} corpus documents, which is implausible for clinical "
        "prompts and means the matcher, not the prompts, is broken"
    )


def test_no_threshold_bearing_prompt_span_appears_in_the_evaluated_corpus() -> None:
    """Gate A: a shared span carrying a number bound to a comparator."""
    findings, _ = _analysis()
    failures = [
        f
        for f in findings
        if f["length"] >= GATE_A_MIN_LEN
        and f["normalized"] not in ALLOWED_SPANS
        and _carries_a_whole_number(f["normalized"])
        and _COMPARATOR.search(f["normalized"])
    ]
    assert not failures, _report(failures, "Gate A (threshold bound to an analyte)")


def test_no_criterion_shaped_prompt_span_appears_in_the_evaluated_corpus() -> None:
    """Gate B: a shared span long enough, and shaped like a sentence not a term."""
    findings, _ = _analysis()
    failures = []
    for finding in findings:
        if finding["length"] < GATE_B_MIN_LEN or finding["normalized"] in ALLOWED_SPANS:
            continue
        words = re.findall(r"[a-z][a-z-]*", finding["normalized"])
        if any(word in _CONNECTIVES for word in words):
            failures.append(finding)
    assert not failures, _report(failures, "Gate B (criterion-shaped span)")
