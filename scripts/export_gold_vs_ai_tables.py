#!/usr/bin/env python3
"""Export Gold-vs-AI comparison JSON into CSV/Markdown tables."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

STUDY_ORDER = ["LEADER", "PLATO", "ARISTOTLE"]


def _fmt_float(value, digits=4):
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def _fmt_pct(value):
    if value is None:
        return ""
    return f"{float(value) * 100:.1f}%"


def _fmt_hr_ci(row):
    hr = row.get("hr")
    lo = row.get("ci_lower")
    hi = row.get("ci_upper")
    if hr is None or lo is None or hi is None:
        return ""
    return f"{float(hr):.3f} [{float(lo):.3f}, {float(hi):.3f}]"


def _ci_ratio(ai, gold):
    ai_w = ai.get("ci_width")
    g_w = gold.get("ci_width")
    if ai_w is None or g_w in (None, 0):
        return None
    return float(ai_w) / float(g_w)


def _dlog_hr(ai, gold):
    ai_hr = ai.get("hr")
    g_hr = gold.get("hr")
    if ai_hr in (None, 0) or g_hr in (None, 0):
        return None
    return abs(math.log(float(ai_hr)) - math.log(float(g_hr)))


def _load(path: Path):
    return json.loads(path.read_text())


def _ordered_studies(studies: set[str] | list[str]) -> list[str]:
    existing = set(studies)
    ordered = [s for s in STUDY_ORDER if s in existing]
    remainder = sorted(existing - set(ordered))
    return ordered + remainder


def _write_csv(path: Path, header: list[str], rows: list[list[str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _write_markdown(path: Path, header: list[str], rows: list[list[str]], title: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", "", "| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Export Gold-vs-AI JSON into tables")
    p.add_argument("--fixed-json", required=True)
    p.add_argument("--legacy-json")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--prefix", default="gold_vs_ai")
    return p.parse_args(argv)


def build_fixed_rows(payload):
    rows = []
    for study in _ordered_studies(list(payload.keys())):
        data = payload[study]
        overlap = data.get("overlap", {})
        ai = data.get("ai", {})
        gold = data.get("gold", {})
        rows.append([
            study,
            str(overlap.get("gold_n", "")),
            str(overlap.get("ai_n", "")),
            str(overlap.get("overlap_n", "")),
            _fmt_pct(overlap.get("recall")),
            _fmt_pct(overlap.get("precision")),
            _fmt_hr_ci(gold),
            _fmt_hr_ci(ai),
            _fmt_float(_ci_ratio(ai, gold), 4),
            _fmt_float(_dlog_hr(ai, gold), 4),
        ])
    return rows


def build_delta_rows(fixed, legacy):
    rows = []
    studies = _ordered_studies(set(fixed.keys()) & set(legacy.keys()))
    for study in studies:
        f_ai, f_gold = fixed[study].get("ai", {}), fixed[study].get("gold", {})
        l_ai, l_gold = legacy[study].get("ai", {}), legacy[study].get("gold", {})
        rows.append([
            study,
            _fmt_float(_ci_ratio(f_ai, f_gold), 4),
            _fmt_float(_dlog_hr(f_ai, f_gold), 4),
            _fmt_float(_ci_ratio(l_ai, l_gold), 4),
            _fmt_float(_dlog_hr(l_ai, l_gold), 4),
        ])
    return rows


def main(argv=None):
    args = parse_args(argv)
    out_dir = Path(args.output_dir)
    fixed = _load(Path(args.fixed_json))

    fixed_header = [
        "Study",
        "Gold N",
        "AI N",
        "Overlap",
        "Recall",
        "Precision",
        "Gold HR [95% CI]",
        "Ours HR [95% CI]",
        "CI Ratio (Ours/Gold)",
        "|log(HR_Ours)-log(HR_Gold)|",
    ]
    fixed_rows = build_fixed_rows(fixed)

    fixed_csv = out_dir / f"{args.prefix}_fixed_summary.csv"
    fixed_md = out_dir / f"{args.prefix}_fixed_summary.md"
    _write_csv(fixed_csv, fixed_header, fixed_rows)
    _write_markdown(fixed_md, fixed_header, fixed_rows, "Gold vs AI (Fixed Comparator) Summary")

    print(f"Wrote: {fixed_csv}")
    print(f"Wrote: {fixed_md}")

    if args.legacy_json:
        legacy = _load(Path(args.legacy_json))
        delta_header = [
            "Study",
            "Fixed CI Ratio",
            "Fixed dlogHR",
            "Legacy CI Ratio",
            "Legacy dlogHR",
        ]
        delta_rows = build_delta_rows(fixed, legacy)
        delta_csv = out_dir / f"{args.prefix}_fixed_vs_legacy.csv"
        delta_md = out_dir / f"{args.prefix}_fixed_vs_legacy.md"
        _write_csv(delta_csv, delta_header, delta_rows)
        _write_markdown(delta_md, delta_header, delta_rows, "Fixed vs Legacy Comparator Delta")
        print(f"Wrote: {delta_csv}")
        print(f"Wrote: {delta_md}")


if __name__ == "__main__":
    main()
