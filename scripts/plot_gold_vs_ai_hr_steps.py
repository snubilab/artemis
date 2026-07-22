#!/usr/bin/env python3
"""Plot HR step charts for fixed vs legacy comparator modes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


STUDY_ORDER = ["LEADER", "PLATO", "ARISTOTLE"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Plot Gold-vs-AI HR step charts")
    p.add_argument("--fixed-json", required=True)
    p.add_argument("--legacy-json", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--prefix", default="gold_vs_ai")
    return p.parse_args(argv)


def _load(path: Path):
    return json.loads(path.read_text())


def _series(payload):
    studies = [s for s in STUDY_ORDER if s in payload]
    gold_hr = [payload[s]["gold"].get("hr") for s in studies]
    ai_hr = [payload[s]["ai"].get("hr") for s in studies]
    return studies, gold_hr, ai_hr


def _ci_bounds(payload, studies, arm):
    lows = [payload[s][arm].get("ci_lower") for s in studies]
    highs = [payload[s][arm].get("ci_upper") for s in studies]
    return lows, highs


def _plot_mode(payload, mode_name: str, out_path: Path):
    studies, gold_hr, ai_hr = _series(payload)
    x = list(range(len(studies)))

    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=140)
    ax.step(x, gold_hr, where="mid", label="Gold HR", linewidth=2.2, color="#1f77b4")
    ax.step(x, ai_hr, where="mid", label="AI HR", linewidth=2.2, color="#d62728")
    ax.scatter(x, gold_hr, color="#1f77b4", s=28)
    ax.scatter(x, ai_hr, color="#d62728", s=28)

    g_lo, g_hi = _ci_bounds(payload, studies, "gold")
    a_lo, a_hi = _ci_bounds(payload, studies, "ai")

    for i, y in enumerate(gold_hr):
        if y is not None and g_lo[i] is not None and g_hi[i] is not None:
            ax.vlines(i - 0.06, g_lo[i], g_hi[i], color="#1f77b4", alpha=0.7, linewidth=1.5)
    for i, y in enumerate(ai_hr):
        if y is not None and a_lo[i] is not None and a_hi[i] is not None:
            ax.vlines(i + 0.06, a_lo[i], a_hi[i], color="#d62728", alpha=0.7, linewidth=1.5)

    ax.set_xticks(x)
    ax.set_xticklabels(studies)
    ax.set_ylabel("Hazard Ratio")
    ax.set_title(f"Gold vs AI HR Step Plot ({mode_name})")
    ax.grid(alpha=0.25, linestyle="--", linewidth=0.8)
    ax.legend(loc="best")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _plot_delta(fixed, legacy, out_path: Path):
    studies = [s for s in STUDY_ORDER if s in fixed and s in legacy]
    x = list(range(len(studies)))
    fixed_ai = [fixed[s]["ai"].get("hr") for s in studies]
    legacy_ai = [legacy[s]["ai"].get("hr") for s in studies]

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=140)
    ax.step(x, fixed_ai, where="mid", label="AI HR (fixed comparator)", linewidth=2.2, color="#2ca02c")
    ax.step(x, legacy_ai, where="mid", label="AI HR (legacy comparator)", linewidth=2.2, color="#9467bd")
    ax.scatter(x, fixed_ai, color="#2ca02c", s=28)
    ax.scatter(x, legacy_ai, color="#9467bd", s=28)
    ax.set_xticks(x)
    ax.set_xticklabels(studies)
    ax.set_ylabel("AI Hazard Ratio")
    ax.set_title("AI HR Step Plot: Fixed vs Legacy Comparator")
    ax.grid(alpha=0.25, linestyle="--", linewidth=0.8)
    ax.legend(loc="best")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main(argv=None):
    args = parse_args(argv)
    out_dir = Path(args.output_dir)
    fixed = _load(Path(args.fixed_json))
    legacy = _load(Path(args.legacy_json))

    fixed_png = out_dir / f"{args.prefix}_hr_step_fixed.png"
    legacy_png = out_dir / f"{args.prefix}_hr_step_legacy.png"
    delta_png = out_dir / f"{args.prefix}_hr_step_ai_fixed_vs_legacy.png"

    _plot_mode(fixed, "fixed comparator", fixed_png)
    _plot_mode(legacy, "legacy comparator", legacy_png)
    _plot_delta(fixed, legacy, delta_png)

    print(f"Wrote: {fixed_png}")
    print(f"Wrote: {legacy_png}")
    print(f"Wrote: {delta_png}")


if __name__ == "__main__":
    main()
