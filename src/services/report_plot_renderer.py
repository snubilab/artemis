"""Render AnalysisPlotDescriptor dicts to base64-encoded PNG images."""

from __future__ import annotations

import base64
import io
import logging
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)

_FIGURE_SIZE = (8, 5)
_LOVE_FIGURE_SIZE = (9, 7)
_DPI = 150
_STYLE = "seaborn-v0_8-whitegrid"

# Concept name cache (populated once per render batch)
_concept_name_cache: dict[int, str] = {}


def _resolve_concept_labels(labels: list[str]) -> dict[str, str]:
    """Resolve cond_/drug_/proc_ labels to human-readable OMOP concept names."""
    id_pattern = re.compile(r"^(cond|drug|proc|meas|obs|visit)_(\d+)$")
    ids_to_resolve: list[int] = []
    label_to_id: dict[str, int] = {}

    for label in labels:
        m = id_pattern.match(label)
        if m:
            concept_id = int(m.group(2))
            label_to_id[label] = concept_id
            if concept_id not in _concept_name_cache:
                ids_to_resolve.append(concept_id)

    if ids_to_resolve:
        try:
            from src.analysis.omop_connector import OMOPConnector
            connector = OMOPConnector()
            resolved = connector._resolve_concept_names(ids_to_resolve)
            _concept_name_cache.update(resolved)
        except Exception as exc:
            logger.warning("Could not resolve concept names: %s", exc)

    domain_labels = {"cond": "Condition", "drug": "Drug", "proc": "Procedure", "meas": "Measurement", "obs": "Observation", "visit": "Visit"}
    result: dict[str, str] = {}
    for label in labels:
        m = id_pattern.match(label)
        if m:
            domain = domain_labels.get(m.group(1), m.group(1))
            concept_id = int(m.group(2))
            name = _concept_name_cache.get(concept_id)
            result[label] = name if name else f"{domain} ({concept_id})"
        else:
            # Clean up known labels
            clean = label.replace("_", " ").replace("concept id", "").strip().title()
            result[label] = clean
    return result


def render_plot_descriptors_to_base64(plot_descriptors: list[dict]) -> dict[str, str]:
    """Render plot descriptors to base64-encoded PNG images.

    Args:
        plot_descriptors: List of AnalysisPlotDescriptor dicts from results["plots"]

    Returns:
        Dict mapping plot key to base64-encoded PNG string (no data URI prefix)
    """
    result: dict[str, str] = {}
    for descriptor in plot_descriptors:
        key = descriptor.get("key", "")
        if not key:
            continue
        try:
            png_b64 = _render_one(descriptor)
            if png_b64:
                result[key] = png_b64
        except Exception:
            logger.exception("Failed to render plot key=%s", key)
    return result


def _render_one(descriptor: dict) -> str | None:
    plot_type = descriptor.get("plotType", "line")
    series_list = descriptor.get("series", [])

    if not series_list:
        return None
    if not any(s.get("points") for s in series_list):
        return None

    with plt.style.context(_STYLE):
        figsize = _LOVE_FIGURE_SIZE if plot_type == "love_plot" else _FIGURE_SIZE
        fig, ax = plt.subplots(figsize=figsize)
        try:
            if plot_type == "km_curve":
                _render_km_curve(ax, descriptor)
            elif plot_type == "love_plot":
                _render_love_plot(ax, descriptor)
            elif plot_type == "forest":
                _render_forest(ax, descriptor)
            elif plot_type == "ps_distribution":
                _render_ps_distribution(ax, descriptor)
            else:
                _render_line(ax, descriptor)

            _apply_labels(ax, descriptor)
            fig.tight_layout()
            return _fig_to_base64(fig)
        finally:
            plt.close(fig)


def _render_km_curve(ax: plt.Axes, descriptor: dict) -> None:
    colors = {"Treatment": "steelblue", "Comparator": "crimson"}
    default_colors = ["steelblue", "crimson", "seagreen", "darkorange"]

    all_ys: list[float] = []
    for i, series in enumerate(descriptor.get("series", [])):
        points = series.get("points", [])
        if not points:
            continue
        xs = [p.get("x") for p in points if p.get("x") is not None and p.get("y") is not None]
        ys = [p.get("y") for p in points if p.get("x") is not None and p.get("y") is not None]
        if not xs:
            continue
        all_ys.extend(ys)
        name = series.get("name", f"Series {i}")
        color = colors.get(name, default_colors[i % len(default_colors)])
        ax.step(xs, ys, where="post", label=name, color=color, linewidth=2)

    # Auto-zoom Y axis: if data range is tiny (e.g. 0.996-1.0), zoom in to show detail
    if all_ys:
        y_min, y_max = min(all_ys), max(all_ys)
        y_range = y_max - y_min
        if y_range < 0.05:
            # Very narrow range — zoom in with padding
            pad = max(y_range * 2, 0.005)
            ax.set_ylim(max(0, y_min - pad), min(1.0, y_max + pad))
            ax.set_title(descriptor.get("title", "") + " (zoomed)", fontsize=12, fontweight="bold")
        else:
            ax.set_ylim(0, 1.05)
    else:
        ax.set_ylim(0, 1.05)

    ax.legend()


def _render_love_plot(ax: plt.Axes, descriptor: dict) -> None:
    # Data format: each point has label=covariate_name, y=abs(SMD), x may be None
    series_list = descriptor.get("series", [])
    if not series_list:
        return

    all_labels: list[str] = []
    series_data: dict[str, dict[str, float]] = {}

    for series in series_list:
        name = series.get("name", "")
        series_data[name] = {}
        for point in series.get("points", []):
            label = point.get("label") or ""
            smd = point.get("y") if point.get("y") is not None else point.get("x")
            if label and smd is not None:
                series_data[name][label] = abs(float(smd))
                if label not in all_labels:
                    all_labels.append(label)

    if not all_labels:
        return

    # Resolve concept IDs to human-readable names
    name_map = _resolve_concept_labels(all_labels)
    display_labels = [name_map.get(lbl, lbl) for lbl in all_labels]

    # Sort by "After matching" SMD (or first series) for readability
    after_key = "After matching" if "After matching" in series_data else list(series_data.keys())[-1]
    sort_values = [series_data.get(after_key, {}).get(lbl, 0) for lbl in all_labels]
    sorted_indices = sorted(range(len(all_labels)), key=lambda i: sort_values[i])
    all_labels = [all_labels[i] for i in sorted_indices]
    display_labels = [display_labels[i] for i in sorted_indices]

    y_positions = list(range(len(all_labels)))
    colors_map = {"Before matching": ("#e74c3c", "o"), "After matching": ("#3498db", "D")}
    default_styles = [("#e74c3c", "o"), ("#3498db", "D")]

    for i, (name, data) in enumerate(series_data.items()):
        color, marker = colors_map.get(name, default_styles[i % len(default_styles)])
        smds = [data.get(label, float("nan")) for label in all_labels]
        valid = [(s, y) for s, y in zip(smds, y_positions) if s == s]
        if not valid:
            continue
        vxs, vys = zip(*valid)
        ax.scatter(vxs, vys, color=color, label=name, zorder=3, s=50, marker=marker, edgecolors="white", linewidth=0.5)

    # Threshold line
    ax.axvline(x=0.1, color="#95a5a6", linestyle="--", linewidth=1.2, alpha=0.9, label="Balance threshold (0.1)")

    # Shaded good zone
    ax.axvspan(0, 0.1, alpha=0.06, color="#27ae60")

    ax.set_yticks(y_positions)
    ax.set_yticklabels(display_labels, fontsize=8)
    ax.set_xlabel("Absolute Standardized Mean Difference", fontsize=10)
    ax.set_xlim(left=0)
    ax.legend(fontsize=8, loc="lower right", framealpha=0.9)
    ax.tick_params(axis="y", length=0)


def _render_forest(ax: plt.Axes, descriptor: dict) -> None:
    # Data format: series "HR" has 1 point (x=HR), series "CI" has 2 points (x=CI_lower, x=CI_upper)
    series_list = descriptor.get("series", [])
    if not series_list:
        return

    hr_val = None
    ci_lower = None
    ci_upper = None

    for series in series_list:
        name = series.get("name", "")
        points = series.get("points", [])
        if name == "HR" and points:
            hr_val = points[0].get("x")
        elif name == "CI" and len(points) >= 2:
            ci_lower = points[0].get("x")
            ci_upper = points[1].get("x")

    if hr_val is None:
        return

    ax.axvline(x=1.0, color="gray", linestyle="--", linewidth=1.5, alpha=0.8)

    xerr_low = hr_val - ci_lower if ci_lower is not None else 0
    xerr_high = ci_upper - hr_val if ci_upper is not None else 0

    ax.errorbar(
        hr_val, 0, xerr=[[xerr_low], [xerr_high]],
        fmt="D", color="steelblue", capsize=8, markersize=10, linewidth=2.5, capthick=2,
    )

    ci_str = f"({ci_lower:.3f}, {ci_upper:.3f})" if ci_lower is not None and ci_upper is not None else ""
    ax.text(hr_val, 0.25, f"HR = {hr_val:.3f} {ci_str}", ha="center", fontsize=11, fontweight="bold")

    ax.set_ylim(-1, 1)
    ax.set_yticks([])
    ax.axhline(y=0, color="#cccccc", linewidth=0.5)


def _render_ps_distribution(ax: plt.Axes, descriptor: dict) -> None:
    # Data format: pre-binned histogram — x=bin_center, y=count
    colors_map = {"Treated": "steelblue", "Control": "crimson", "Treatment": "steelblue", "Comparator": "crimson"}
    default_colors = ["steelblue", "crimson"]

    for i, series in enumerate(descriptor.get("series", [])):
        points = series.get("points", [])
        if not points:
            continue
        xs = [p.get("x") for p in points if p.get("x") is not None and p.get("y") is not None]
        ys = [p.get("y") for p in points if p.get("x") is not None and p.get("y") is not None]
        if not xs:
            continue
        name = series.get("name", f"Series {i}")
        color = colors_map.get(name, default_colors[i % len(default_colors)])
        # Calculate bar width from bin spacing
        bar_width = (xs[1] - xs[0]) * 0.4 if len(xs) > 1 else 0.05
        offset = -bar_width / 2 if i == 0 else bar_width / 2
        ax.bar([x + offset for x in xs], ys, width=bar_width, alpha=0.7, color=color, label=name, edgecolor="white")

    ax.legend(fontsize=9)


def _render_line(ax: plt.Axes, descriptor: dict) -> None:
    default_colors = ["steelblue", "crimson", "seagreen", "darkorange", "mediumpurple"]

    for i, series in enumerate(descriptor.get("series", [])):
        points = series.get("points", [])
        if not points:
            continue
        xs = [p.get("x") for p in points if p.get("x") is not None and p.get("y") is not None]
        ys = [p.get("y") for p in points if p.get("x") is not None and p.get("y") is not None]
        if not xs:
            continue
        color = default_colors[i % len(default_colors)]
        ax.plot(xs, ys, label=series.get("name", f"Series {i}"), color=color, linewidth=2, marker="o", markersize=3)

    ax.legend()


def _apply_labels(ax: plt.Axes, descriptor: dict) -> None:
    title = descriptor.get("title", "")
    x_label = descriptor.get("xLabel", "")
    y_label = descriptor.get("yLabel", "")
    if title:
        ax.set_title(title, fontsize=12, fontweight="bold")
    if x_label:
        ax.set_xlabel(x_label, fontsize=10)
    if y_label:
        ax.set_ylabel(y_label, fontsize=10)


def _fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
