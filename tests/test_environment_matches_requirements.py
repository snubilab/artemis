"""The interpreter running the tests must match requirements.txt.

`requirements.txt` is the single source of truth: Dockerfile.tte-api installs from it
(`uv pip install --system --no-cache -r requirements.txt`), so the container is correct
by construction. A local `.venv` is not — it is assembled by hand and drifts, and the
drift is silent in the worst way.

What that silence cost, all on 2026-08-10:

- `torch` was absent, so MedCPT embeddings could not load. The vector search failed and
  the error said "Vector search failed (DB might be empty)" — a collection of 440,790
  concepts. A control arm run there produced five mutually disjoint results from five
  identical runs, and would have been reported as an embedding measurement.
- `pandas` and `langgraph` were absent, so ten test modules failed at import and were
  quietly skipped over as "collection errors" in a run that still reported a pass count.
- `numpy` was 2.5.0 against a requirement of 1.26.4. Installing `pandas` on top of it
  turned 213 failures into 321.

None of these announce themselves. Each one lets a run finish and print a number.
"""
from __future__ import annotations

import importlib.metadata as metadata
from pathlib import Path

import pytest

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"

# Packages whose absence has produced a wrong answer rather than a crash. The full-file
# check below covers everything; these are called out so a failure names the consequence.
LOAD_BEARING = {
    "torch": "MedCPT embeddings silently return nothing and the error blames the database",
    "pandas": "test modules fail at import and are reported as collection errors, not failures",
    "numpy": "a major-version mismatch breaks pandas and scipy at runtime, not at install",
    "scipy": "analysis code fails at import",
    "langgraph": "agent workflow modules fail at import",
}


def _declared() -> dict[str, str]:
    """Parse requirements.txt into {canonical name: version} for this interpreter.

    Lines carry environment markers (`; python_version >= "3.10"`); those that do not
    apply to the running interpreter are skipped rather than treated as requirements.
    """
    from packaging.markers import Marker
    from packaging.utils import canonicalize_name

    out: dict[str, str] = {}
    for raw in REQUIREMENTS.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        spec, _, marker_text = line.partition(";")
        if marker_text.strip():
            try:
                if not Marker(marker_text.strip()).evaluate():
                    continue
            except Exception:
                continue
        name, _, version = spec.strip().partition("==")
        name = name.split("[")[0].strip()
        if name and version.strip():
            out[canonicalize_name(name)] = version.strip()
    return out


def _installed(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def test_requirements_file_is_parseable():
    """A guard on the guard: an unparseable file would make every check below vacuous."""
    declared = _declared()
    assert len(declared) > 50, f"only {len(declared)} pinned requirements parsed — check the parser"


@pytest.mark.parametrize("package", sorted(LOAD_BEARING))
def test_load_bearing_package_is_installed(package: str):
    declared = _declared()
    if package not in declared:
        pytest.skip(f"{package} is not pinned for this interpreter")
    got = _installed(package)
    assert got is not None, (
        f"{package} is declared in requirements.txt but missing from this environment. "
        f"Consequence when it is missing: {LOAD_BEARING[package]}. "
        f"Fix: uv pip install --python .venv/bin/python -r requirements.txt"
    )


def test_no_installed_package_contradicts_requirements():
    """Every pinned requirement that IS installed must be at the pinned version.

    Packages that are absent are reported by the parametrized test above; this one is
    about the more dangerous case, where something is present at the wrong version and
    imports fine until it does not.
    """
    declared = _declared()
    mismatched = []
    for name, want in sorted(declared.items()):
        got = _installed(name)
        if got is not None and got != want:
            mismatched.append(f"{name}: installed {got}, requirements.txt pins {want}")
    assert not mismatched, (
        "This environment disagrees with requirements.txt, the file Dockerfile.tte-api "
        "builds the container from:\n  " + "\n  ".join(mismatched)
        + "\nFix: uv pip install --python .venv/bin/python -r requirements.txt"
    )
