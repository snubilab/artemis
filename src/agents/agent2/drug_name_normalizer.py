"""Offline drug-name normalization backed by a local PubChem synonym database.

Why this exists
---------------
Clinical-trial protocols routinely name a drug by its pre-approval development
code ("BI 10773") rather than by its ingredient name ("empagliflozin").  The
OMOP vocabulary carries no such codes -- ``concept_synonym`` has zero rows for
BI 10773 / AZD6140 / LY2189265 -- so the concept mapper falls through to
embedding similarity and silently returns a plausible-looking neighbour.  That
failure is silent and expensive: "BI 10773" resolved to concept 1254065
("CHF-6366 beta-2 metabolite", 1 descendant) and the resulting cohort matched
0 patients at three hospitals, where real empagliflozin (45774751, 375
descendants) matches tens of thousands.

PubChem's synonym graph resolves these codes correctly, but a per-call HTTP
lookup is not acceptable inside the mapper (latency, rate limits, and it must
run air-gapped).  This module reads a pre-built SQLite snapshot instead.

Design notes
------------
* A **miss must be a clean miss**.  ``normalize`` returns ``None`` rather than a
  best-effort guess; fuzzy matching belongs upstream where it can be scored.
* Ambiguity is real (one synonym string can point at many CIDs), so the result
  carries every candidate plus an ``is_ambiguous`` flag instead of quietly
  collapsing to one answer.
* The canonical name returned is PubChem's *Title*, which is the field that
  lines up with an OMOP ingredient name.

Build the database with ``scripts/build_pubchem_synonym_db.py``.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Candidate",
    "DEFAULT_DB_PATH",
    "DrugNameNormalizer",
    "MATCH_CASE_FOLDED",
    "MATCH_EXACT",
    "MATCH_PUNCT_NORMALIZED",
    "NormalizationResult",
    "normalize",
    "normalize_key",
]

# Repository-relative default; ``data/`` is gitignored and holds the built DB.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "pubchem" / "pubchem_synonyms.sqlite"

MATCH_EXACT = "exact"
MATCH_CASE_FOLDED = "case_folded"
MATCH_PUNCT_NORMALIZED = "punctuation_normalized"

# Lower rank == better match, used to pick the representative candidate.
_MATCH_RANK = {MATCH_EXACT: 0, MATCH_CASE_FOLDED: 1, MATCH_PUNCT_NORMALIZED: 2}

# Greek letters are transliterated before punctuation is stripped.  Without
# this, "alpha-tocopherol" and the greek-lettered form would not unify, and
# worse, "α-carotene" and "β-carotene" would both collapse to
# "carotene" and become indistinguishable.
_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi",
    "ρ": "rho", "σ": "sigma", "ς": "sigma", "τ": "tau",
    "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi",
    "ω": "omega",
}
_GREEK_TABLE = str.maketrans(_GREEK)

_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")

# PubChem falls back to a literal "CID 163285897" title when a record has no
# preferred name (~0.9% of titles, and every tirzepatide record).  Handing that
# string to the concept mapper is worse than handing it nothing: it is not a
# drug name, so the embedding fallback would map it to an arbitrary concept --
# precisely the silent failure this module exists to prevent.
_PLACEHOLDER_TITLE_RE = re.compile(r"^CID \d+$")


def normalize_key(name: str) -> str:
    """Collapse a drug name to its lookup key.

    Case, whitespace, hyphens, dots and every other separator are discarded so
    that ``BI 10773``, ``BI-10773`` and ``BI10773`` -- all of which appear in
    real protocols -- land in the same bucket.  NFKD folding strips accents and
    normalizes the CAS-style unicode PubChem sometimes emits.

    This is the single source of truth for key generation: the build script
    imports it, so the stored keys and the query keys can never drift apart.
    """
    folded = unicodedata.normalize("NFKD", name).casefold().translate(_GREEK_TABLE)
    return _NON_ALNUM_RE.sub("", folded)


@dataclass(frozen=True)
class Candidate:
    """One PubChem compound that the queried string could refer to."""

    cid: int
    title: str
    matched_synonym: str
    match_type: str


@dataclass(frozen=True)
class NormalizationResult:
    """Outcome of a successful lookup.

    ``canonical_name``/``cid`` are the best single answer, but callers that care
    about correctness should check ``is_ambiguous`` first: when it is set, the
    query maps to several distinct compounds and picking one is a judgement the
    mapper -- not this module -- should make from ``candidates``.
    """

    query: str
    canonical_name: str
    cid: int
    match_type: str
    is_ambiguous: bool
    candidates: tuple[Candidate, ...]


_QUERY = """
    SELECT s.cid, s.raw, t.title
    FROM synonym s
    JOIN title t ON t.cid = s.cid
    WHERE s.key = ?
"""


class DrugNameNormalizer:
    """Read-only, network-free lookup over the pre-built PubChem snapshot."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"PubChem synonym DB not found at {self.db_path}. "
                "Build it with scripts/build_pubchem_synonym_db.py"
            )
        # Read-only URI keeps a stray write from corrupting a multi-GB build,
        # and check_same_thread=False lets the FastAPI worker share one handle.
        self._conn = sqlite3.connect(
            f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False
        )

    def close(self) -> None:
        self._conn.close()

    def normalize(self, name: str) -> NormalizationResult | None:
        """Resolve ``name`` to its PubChem canonical title, or ``None``.

        ``None`` means "not in PubChem under any spelling we index" -- it is
        never a degraded guess.
        """
        if not name or not name.strip():
            return None
        key = normalize_key(name)
        if not key:
            return None

        rows = self._conn.execute(_QUERY, (key,)).fetchall()
        if not rows:
            return None

        stripped = name.strip()
        folded = stripped.casefold()
        # Deduplicate on (cid, title): the same compound is reached through many
        # spellings, and we only want the strongest match type per compound.
        best: dict[int, Candidate] = {}
        for cid, raw, title in rows:
            if _PLACEHOLDER_TITLE_RE.match(title):
                continue
            if raw == stripped:
                match_type = MATCH_EXACT
            elif raw.casefold() == folded:
                match_type = MATCH_CASE_FOLDED
            else:
                match_type = MATCH_PUNCT_NORMALIZED
            current = best.get(cid)
            if current is None or _MATCH_RANK[match_type] < _MATCH_RANK[current.match_type]:
                best[cid] = Candidate(cid=cid, title=title, matched_synonym=raw, match_type=match_type)

        if not best:
            # Every record for this string is a nameless placeholder, so we have
            # no canonical name to offer.  A clean miss, not a fabricated one.
            return None

        # Ambiguity is judged on distinct *titles*, not CIDs: PubChem routinely
        # holds several CIDs (salt, hydrate, stereoisomer records) that all carry
        # the same title, and for OMOP ingredient mapping those are one answer.
        title_counts = Counter(c.title for c in best.values())
        candidates = sorted(
            best.values(),
            key=lambda c: (_MATCH_RANK[c.match_type], -title_counts[c.title], c.cid),
        )
        top = candidates[0]
        return NormalizationResult(
            query=name,
            canonical_name=top.title,
            cid=top.cid,
            match_type=top.match_type,
            is_ambiguous=len(title_counts) > 1,
            candidates=tuple(candidates),
        )


_default: DrugNameNormalizer | None = None


def normalize(name: str, db_path: Path | str = DEFAULT_DB_PATH) -> NormalizationResult | None:
    """Module-level convenience wrapper reusing one lazily-opened connection."""
    global _default
    if _default is None or _default.db_path != Path(db_path):
        _default = DrugNameNormalizer(db_path)
    return _default.normalize(name)


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    import sys

    for arg in sys.argv[1:]:
        result = normalize(arg)
        if result is None:
            print(f"{arg!r}: NOT FOUND")
        else:
            flag = " [AMBIGUOUS]" if result.is_ambiguous else ""
            print(
                f"{arg!r} -> {result.canonical_name} "
                f"(CID {result.cid}, {result.match_type}, "
                f"{len(result.candidates)} candidate(s)){flag}"
            )
