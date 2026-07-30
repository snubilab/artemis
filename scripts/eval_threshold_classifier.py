#!/usr/bin/env python3
"""Held-out evaluation of the stage-2 criterion classifier (ADR-032 D9).

    python scripts/eval_threshold_classifier.py
    python scripts/eval_threshold_classifier.py --every-numeral

Read-only apart from the classifier's own content-addressed cache. Reports only the
three quantities D9 says the corpus can support -- span recall, MEASUREMENT_VALUE
accuracy (held-out n=85) and NON_CRITERION accuracy (n=4) -- and prints the held-out
count per class so the five classes with zero held-out instances are visible as
undefined rather than being read as a score. Precision is not reported at all: the
corpus samples spans per line rather than inventorying them, so a span the classifier
emits that the corpus lacks cannot be told from a gap in the corpus.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import sys
import json
import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.agent1.threshold_classifier import (  # noqa: E402
    ThresholdSpan,
    _normalise,
    classify_criteria,
    deescape,
)
from src.utils.llm import resolve_model  # noqa: E402


def taxonomy_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_value_taxonomy", ROOT / "scripts" / "build_value_taxonomy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def locate(haystack: str, phrase: str) -> tuple[int, int] | None:
    """Where a phrase sits in the normalised line, or None."""
    needle = _normalise(phrase)
    at = haystack.find(needle)
    return None if at < 0 or not needle else (at, at + len(needle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--every-numeral", action="store_true")
    # Lowered from 8 when the vLLM server is shared with someone else's benchmark:
    # the correctness columns here are structural at temperature 0, but the batch
    # pressure inflates a wall clock the other run reports.
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument(
        "--save",
        type=Path,
        default=None,
        help="Write the headline numbers as JSON. A run that only prints leaves "
             "nothing to compare against later.",
    )
    args = parser.parse_args()

    tax = taxonomy_module()
    # The rendered prompt prints 23 corpus entries verbatim. Scoring on those measures
    # the prompt, not the classifier, so they are removed before anything is counted.
    leaked = {i for c in tax.CLASSES for i in c["example_ids"]}
    leaked |= {f["entry_ids"][0] for f in tax.NON_CRITERION_FAMILIES}
    entries = tax.load_entries()
    held_out = [e for e in entries if e["id"] not in leaked]
    gold = {e["id"]: tax.class_of(e) for e in entries}

    lines = sorted({e["source_text"] for e in held_out})
    print(f"corpus {len(entries)} entries, {len(leaked)} embedded in the prompt, "
          f"{len(held_out)} held out over {len(lines)} distinct source lines", flush=True)

    started = time.monotonic()
    results = classify_criteria(
        lines, every_numeral=args.every_numeral, max_workers=args.max_workers
    )
    by_line = dict(zip(lines, results))
    print(f"wall {time.monotonic() - started:.0f}s  every_numeral={args.every_numeral}"
          f"  model={resolve_model(None)}  workers={args.max_workers}\n")

    # A corpus phrase counts as recovered when some output span overlaps it in the
    # source line. Exact string equality would be the wrong test: the corpus records
    # "above 3 x upper limit of normal (ULN)" where the model returns "> 3 x ULN",
    # and both hand stage 3 the same constraint.
    matched: list[tuple[dict[str, Any], ThresholdSpan | None]] = []
    for entry in held_out:
        line = _normalise(entry["source_text"])
        want = locate(line, entry["threshold_phrase"])
        best: tuple[ThresholdSpan, tuple[int, int]] | None = None
        for span in by_line[entry["source_text"]]:
            got = locate(line, span.threshold_phrase)
            if want and got and got[0] < want[1] and want[0] < got[1]:
                if best is None or got[1] - got[0] > best[1][1] - best[1][0]:
                    best = (span, got)
        matched.append((entry, best[0] if best else None))

    # Decomposed on purpose. A corpus phrase "covered" by a synthesised recall-net
    # REVIEW is a span the model dropped, not a span it found -- reporting the two
    # together would hide exactly the failure ADR-032 says dominates.
    recovered = [row for row in matched if row[1] is not None]
    by_model = [row for row in recovered if row[1].origin == "model"]
    print(f"span recall  {len(recovered)}/{len(matched)} corpus phrases covered by some span"
          f"\n  by a model span   {len(by_model)}/{len(matched)}"
          f"\n  only by the net   {len(recovered) - len(by_model)}/{len(matched)}"
          f"  (model dropped these; they surface as REVIEW instead of vanishing)"
          f"\n  covered by none   {len(matched) - len(recovered)}/{len(matched)}")

    confusion: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for entry, span in matched:
        confusion[gold[entry["id"]]][span.span_class if span else "MISSED"] += 1

    print(f"\n{'gold class':<20} {'held-out':>8} {'correct':>8}   confusion")
    for name in sorted(confusion, key=lambda k: -sum(confusion[k].values())):
        counts = confusion[name]
        total = sum(counts.values())
        note = "" if total >= 5 else "   <- n<5, not a score"
        print(f"{name:<20} {total:>8} {counts[name]:>8}   "
              + ", ".join(f"{k}:{v}" for k, v in counts.most_common() if k != name) + note)
    absent = sorted({c["id"] for c in tax.CLASSES} - set(confusion))
    print(f"\nclasses with zero held-out instances (accuracy undefined): {absent}")

    spans = [s for batch in results for s in batch]
    net = [s for s in spans if s.origin == "recall_net"]
    print(f"\nspans emitted {len(spans)}; REVIEW {sum(1 for s in spans if s.span_class == 'REVIEW')}"
          f" of which recall_net {len(net)}; lines carrying a recall_net span "
          f"{sum(1 for b in results if any(s.origin == 'recall_net' for s in b))}/{len(lines)}")
    demotions = collections.Counter(
        (s.review_reason or "").split(":")[0] for s in spans
        if s.span_class == "REVIEW" and s.origin == "model"
    )
    print("gate demotions:", demotions.most_common() or "none")

    wrong = [(e, s) for e, s in matched if s is not None and s.span_class != gold[e["id"]]]
    print(f"\n--- misclassified ({len(wrong)}) ---")
    for entry, span in wrong:
        print(f"[{entry['id']}] gold={gold[entry['id']]} got={span.span_class}"
              f"  reason={span.review_reason}"
              f"\n  line   : {deescape(entry['source_text'])[:160]}"
              f"\n  corpus : {entry['threshold_phrase']!r}"
              f"\n  span   : {span.threshold_phrase!r} head={span.head!r}")

    if args.save:
        # A 52-minute GPU measurement that exists only in a terminal is a
        # measurement nobody can check. This run's numbers were reported from a
        # transcript once, with no artifact to verify them against, and that is the
        # shape every silent defect in this codebase has taken.
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(
            json.dumps(
                {
                    "model": resolve_model(),
                    "every_numeral": args.every_numeral,
                    "max_workers": args.max_workers,
                    "git_rev": os.environ.get("ARTEMIS_GIT_REV"),
                    "wall_s": round(time.monotonic() - started),
                    "corpus_entries": len(entries),
                    "prompt_embedded": len(leaked),
                    "held_out": len(matched),
                    "covered_by_any_span": len(recovered),
                    "spans_emitted": len(spans),
                    "review_spans": sum(1 for sp in spans if sp.span_class == "REVIEW"),
                    # Built from `confusion`, not from the `name`/`counts` left over
                    # by the print loop above -- that leak recorded one arbitrary
                    # confusion row and read as a per-class score. Six models were
                    # saved under it before anyone compared the JSON to the table.
                    "per_class_correct": {g: confusion[g][g] for g in confusion},
                    "per_class_held_out": {g: sum(confusion[g].values()) for g in confusion},
                    "gate_demotions": dict(demotions),
                    "misclassified": len(wrong),
                    "uncovered": len(matched) - len(recovered),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(f"\nsaved {args.save}")

    print(f"\n--- not covered by any span ({len(matched) - len(recovered)}) ---")
    for entry, span in matched:
        if span is None:
            out = by_line[entry["source_text"]]
            print(f"[{entry['id']}] gold={gold[entry['id']]}"
                  f"\n  line   : {deescape(entry['source_text'])[:160]}"
                  f"\n  corpus : {entry['threshold_phrase']!r}"
                  f"\n  spans  : {[(s.span_class, s.threshold_phrase) for s in out]}")


if __name__ == "__main__":
    main()
