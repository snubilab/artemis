#!/usr/bin/env python3
"""Score generated Circe concept sets against gold by concept-set overlap.

WHY THIS EXISTS. Patient counts against ``synthea_cdm_{aristotle,leader,plato}``
are not a quality signal: those CDMs are generated *from* gold by
``scripts/generate_synthea_from_gold.py``, so a count partly measures that
generator. ``AGENTS.md`` (EVALUATION) and
``docs/debugging/2026-08-09_benchmark_cdm_is_not_an_oracle.md`` therefore make
closure overlap against ``data/gold/`` the measure of record.

WHY A SEPARATE ENTRYPOINT FROM ``compare_gold_vs_generated_circe.py``. That
script's advertised contract is "definition-level, no DB", and its
``comparison.json`` is parsed by ``build_diagnosis_data.py`` (and through it the
published dashboard). Closure needs a DSN, a pairing rule, per-set rows, and a
different output schema; folding it in would force a dashboard data producer to
grow a database dependency and would silently change the numbers it publishes.
The two share one definition of "raw item" via
``src.services.conceptset_closure.raw_item_ids``.

TWO MODES, NEVER MIXED SILENTLY.
  raw     -- item ids as listed in the JSON. No database.
  closure -- Circe's resolved closure (direct + descendants + optional mapped,
             minus the excluded anti-join). Requires a vocabulary DSN and fails
             loudly if it cannot get one. It NEVER degrades to ``raw``.
The mode is written into the output JSON and printed in the console header,
because raw and closure differ by 1.5x-3x on every trial.

PAIRING. A best-Jaccard match against a gold set with no real counterpart is
misleading -- a naive run paired gold "CKD 4-ESRD" with generated
"Hypertension" at recall 0.14. Pairing therefore has three outcomes:
  matched_by_name    name_sim >= name_strong, or name_sim >= name_weak with any
                     concept overlap
  matched_by_overlap no name evidence but concept jaccard >= overlap_strong
  no_counterpart     neither
Unmatched gold sets and unmatched generated sets are reported separately.
Many-to-one is allowed: gold splits "Apixaban" and "Apixaban (ATC)" while the
generated cohort has one apixaban set, and a bijection would falsely report one
of them unmatched.

Usage:
    python3 scripts/conceptset_overlap_eval.py --mode closure
    python3 scripts/conceptset_overlap_eval.py --mode raw --trials ARISTOTLE
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parents[1]
if str(ARTEMIS_DIR) not in sys.path:
    sys.path.insert(0, str(ARTEMIS_DIR))

from src.services.conceptset_closure import (  # noqa: E402
    DEFAULT_VOCAB_SCHEMA,
    ClosureResult,
    ConceptSetItem,
    PostgresVocabulary,
    VocabularyLookup,
    concept_set_name,
    items_of_cohort,
    iter_concept_sets,
    raw_item_ids,
    resolve_concept_set,
)

GOLD_DIR = ARTEMIS_DIR / "data" / "gold"
DEFAULT_GENERATED_DIR = ARTEMIS_DIR / "tmp" / "circe_b"
OUT_DIR = ARTEMIS_DIR / "output" / "conceptset_overlap"
DEFAULT_DSN = os.environ.get(
    "ARTEMIS_VOCAB_DSN", "postgresql://postgres:mypass@localhost:5432/postgres"
)

MODES = ("raw", "closure")

# Gold treatment arm <-> the single generated study cohort. The generated
# pipeline emits one cohort per study; each one's PrimaryCriteria DrugEra was
# checked to anchor on the study drug (apixaban / linagliptin / empagliflozin /
# liraglutide / ticagrelor), so the treatment-arm pairing is unambiguous. Gold
# comparator arms (Warfarin, Clopidogrel, Glimepiride, Sulfonylureas, DPP-4)
# have no generated counterpart and are out of scope here, not scored weakly.
TRIALS: dict[str, tuple[str, str]] = {
    "ARISTOTLE": (
        "ARISTOTLE/_TROY v1.1_ Apixaban (ARISTOTLE).json",
        "ARISTOTLE_NCT00412984_study3_circe.json",
    ),
    "CARMELINA": (
        "CARMELINA/[TROY v1.1] Linagliptin (CARMELINA).json",
        "CARMELINA_NCT01897532_study9_circe.json",
    ),
    "CAROLINA": (
        "CAROLINA/[TROY v1.1] Linagliptin (CAROLINA).json",
        "CAROLINA_NCT01243424_study10_circe.json",
    ),
    "EMPA-REG OUTCOME": (
        "EMPA-REG OUTCOME/[TROY v1.1] Empagliflozin (EMPA-REG OUTCOME).json",
        "EMPA-REG_NCT01131676_study8_circe.json",
    ),
    "LEADER": (
        "LEADER/_TROY v1.1_ Liraglutide (LEADER).json",
        "LEADER_NCT01179048_study1_circe.json",
    ),
    "PLATO": (
        "PLATO/_TROY v1.1_ Ticagrelor (PLATO).json",
        "PLATO_NCT00391872_study2_circe.json",
    ),
}


# --------------------------------------------------------------------------
# thresholds
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Thresholds:
    """All tunables in one place; echoed into the output so a run is auditable.

    Calibrated by hand on the ARISTOTLE 38x40 grid. The other trials' pair
    classifications are not hand-validated, which is why every pair row carries
    ``name_sim`` and ``jaccard`` -- any classification can be re-derived from the
    JSON without re-running.
    """

    name_strong: float = 0.50
    name_weak: float = 0.25
    overlap_strong: float = 0.30
    over_expansion_ratio: float = 3.0


DEFAULT_THRESHOLDS = Thresholds()


# --------------------------------------------------------------------------
# resolved sets
# --------------------------------------------------------------------------

@dataclass
class ResolvedSet:
    key: str
    name: str
    concept_ids: set[int]
    n_items: int = 0
    unresolvable_ids: set[int] = field(default_factory=set)

    @property
    def size(self) -> int:
        return len(self.concept_ids)


def resolve_cohort_sets(
    cohort: dict, mode: str, lookup: VocabularyLookup | None
) -> list[ResolvedSet]:
    """Resolve every ConceptSet of a Circe cohort under the requested mode.

    Raises ValueError when ``closure`` is asked for without a vocabulary lookup,
    so the run can never silently produce raw numbers labelled as closure.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    if mode == "closure" and lookup is None:
        raise ValueError(
            "mode 'closure' requires a vocabulary lookup; refusing to fall back to 'raw'"
        )

    out: list[ResolvedSet] = []
    for cs in iter_concept_sets(cohort):
        n_items = len((cs.get("expression") or {}).get("items") or [])
        if mode == "raw":
            out.append(
                ResolvedSet(
                    key=str(cs.get("id")),
                    name=concept_set_name(cs),
                    concept_ids=raw_item_ids(cs),
                    n_items=n_items,
                )
            )
        else:
            resolved: ClosureResult = resolve_concept_set(cs, lookup)
            out.append(
                ResolvedSet(
                    key=str(cs.get("id")),
                    name=concept_set_name(cs),
                    concept_ids=resolved.concept_ids,
                    n_items=n_items,
                    unresolvable_ids=resolved.unresolvable_ids,
                )
            )
    return out


def censoring_only_codeset_keys(cohort: dict) -> set[str]:
    """:returns: keys of concept sets this cohort references ONLY from CensoringCriteria.

    The header of this module already states that gold's treatment- and comparator-arm
    drug sets "have no generated counterpart and are out of scope here, not scored
    weakly". Nothing enforced it, so all 17 such sets across the six trials were being
    paired: gold censors at initiation of either arm's drug, while the generated
    artifact is the eligibility cohort and carries no CensoringCriteria section at all.
    Pairing them scores our eligibility sets against a part of gold that the artifact
    does not attempt -- CAROLINA's exclusion "Hypersensitivity to investigational
    product or glimepiride" was matched, by name alone, to gold's glimepiride censoring
    set.

    A set referenced from CensoringCriteria *and* anywhere else stays in scope; only
    censoring-exclusive sets are dropped.
    """
    sections: dict[int, set[str]] = {}

    def walk(node: object, section: str) -> None:
        if isinstance(node, dict):
            codeset_id = node.get("CodesetId")
            if isinstance(codeset_id, int):
                sections.setdefault(codeset_id, set()).add(section)
            for value in node.values():
                walk(value, section)
        elif isinstance(node, list):
            for value in node:
                walk(value, section)

    expression = cohort.get("expression") if isinstance(cohort.get("expression"), dict) else cohort
    for section, subtree in expression.items():
        if section == "ConceptSets":
            continue
        walk(subtree, section)

    return {str(cid) for cid, secs in sections.items() if secs == {"CensoringCriteria"}}


# --------------------------------------------------------------------------
# name similarity
# --------------------------------------------------------------------------

_LEADING_BRACKET = re.compile(r"^\s*\[[^\]]*\]\s*")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# 'DPP-4' and 'DPP4' name one drug class. Splitting on every non-alphanumeric
# gave {dpp, 4} against {dpp4} -- no shared token at all -- so gold
# '[TROY intervention] DPP4 inhibitors' scored 0.000 against its real
# counterpart 'DPP-4 inhibitor' and 0.250 against 'SGLT-2 inhibitors', which
# shares only the class noun. The scorer paired it with SGLT-2 and read recall
# 0.07 where the right pair reads 0.62. Only punctuation BETWEEN a letter and a
# digit is folded: '4-ESRD' (digit then letter) and 'DPP-IV' (no digit) are
# left as they were.
_LETTER_DIGIT_PUNCT = re.compile(r"(?<=[a-z])[^a-z0-9\s]+(?=[0-9])")

# 'atc' is a vocabulary label, not a clinical concept: gold's "Apixaban (ATC)"
# and generated "apixaban" are the same set. Parentheticals are otherwise KEPT:
# dropping them collapses "Stroke (hemorrhagic)" to "stroke", which then scores
# 1.00 against "Prior stroke, TIA or systemic embolus".
_STOPWORDS = frozenset(
    {"and", "or", "of", "the", "a", "an", "in", "with", "for", "to", "atc", ""}
)

# Category nouns: they carry meaning inside a name but cannot identify a set on
# their own. "Chronic disease" (1244 concepts) shares exactly one token with
# gold "diseases of the blood" and with "peripheral arterial disease", and its
# size guarantees the non-zero concept overlap that weak name evidence needs --
# so it was claiming golds at recall 0.005 and precision 0.002. These tokens are
# NOT dropped from the token set: "coronary atherosis and other chronic ischemic
# heart disease" -> "Coronary Artery Disease" is a real pair that needs 'disease'
# counted alongside 'coronary'. They are only barred from being the *sole*
# shared token. 'drug' and 'inhibitor' are here for the same reason, both
# observed: gold "anti-obesity drugs" vs "investigational drug", and gold
# "alpha-glucosidase inhibitor" vs "SGLT2 inhibitors".
_GENERIC_TOKENS = frozenset({"disease", "disorder", "drug", "inhibitor"})


def _depluralize(token: str) -> str:
    """Drop a trailing plural 's' so 'inhibitors' and 'inhibitor' share a token.

    Deliberately crude rather than a real stemmer: it runs on both sides of every
    comparison, so an over-eager fold ('diabetes' -> 'diabete') costs nothing as
    long as it is consistent. Endings in 'ss', 'us' and 'is' are left alone --
    'loss', 'mellitus' and 'stenosis' are not plurals.

    :param token: A single lower-case alphanumeric token.
    :returns: The token with a plural 's' removed, or the token unchanged.
    """
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def normalize_set_name(name: str) -> frozenset[str]:
    """Tokenise a concept set name for similarity comparison.

    :param name: A gold or generated concept set name, optionally bracket-prefixed.
    :returns: The comparable token set, with letter-digit punctuation folded
        (``DPP-4`` -> ``dpp4``) and trailing plurals dropped.
    """
    text = _LEADING_BRACKET.sub("", str(name or "")).lower()
    text = _LETTER_DIGIT_PUNCT.sub("", text)
    # fold first so the stopword list only ever needs the singular of a word
    folded = (_depluralize(t) for t in _NON_ALNUM.split(text))
    return frozenset(t for t in folded if t not in _STOPWORDS)


def name_similarity(a: str, b: str) -> float:
    """Jaccard over normalised name tokens, with category nouns barred from carrying a match alone.

    :param a: First concept set name.
    :param b: Second concept set name.
    :returns: 0.0 when the names share nothing but category nouns, else the token Jaccard.
    """
    ta, tb = normalize_set_name(a), normalize_set_name(b)
    if not ta or not tb:
        return 0.0
    shared = ta & tb
    if not shared - _GENERIC_TOKENS:
        return 0.0
    return len(shared) / len(ta | tb)


def jaccard(a: set[int], b: set[int]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# --------------------------------------------------------------------------
# pairing
# --------------------------------------------------------------------------

@dataclass
class PairRow:
    gold_key: str
    gold_name: str
    gen_key: str | None
    gen_name: str | None
    outcome: str
    name_sim: float
    jaccard: float
    recall: float
    precision: float
    gold_size: int
    gen_size: int
    shared: int
    expansion_ratio: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PairingResult:
    pairs: list[PairRow]
    unmatched_gold: list[dict]
    unmatched_generated: list[dict]


def _round(value: float) -> float:
    return round(float(value), 4)


def pair_concept_sets(
    gold_sets: list[ResolvedSet],
    generated_sets: list[ResolvedSet],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> PairingResult:
    """Greedy best-counterpart pairing with an explicit ``no_counterpart`` outcome."""
    pairs: list[PairRow] = []
    claimed: set[str] = set()

    for g in gold_sets:
        best: tuple[float, float, ResolvedSet] | None = None
        best_overlap: tuple[float, ResolvedSet] | None = None

        for a in generated_sets:
            nsim = name_similarity(g.name, a.name)
            jac = jaccard(g.concept_ids, a.concept_ids)
            name_evidence = nsim >= thresholds.name_strong or (
                nsim >= thresholds.name_weak and jac > 0
            )
            if name_evidence:
                if best is None or (nsim, jac) > (best[0], best[1]):
                    best = (nsim, jac, a)
            if jac >= thresholds.overlap_strong:
                if best_overlap is None or jac > best_overlap[0]:
                    best_overlap = (jac, a)

        if best is not None:
            partner, outcome = best[2], "matched_by_name"
        elif best_overlap is not None:
            partner, outcome = best_overlap[1], "matched_by_overlap"
        else:
            partner, outcome = None, "no_counterpart"

        if partner is None:
            pairs.append(
                PairRow(
                    gold_key=g.key,
                    gold_name=g.name,
                    gen_key=None,
                    gen_name=None,
                    outcome=outcome,
                    name_sim=0.0,
                    jaccard=0.0,
                    recall=0.0,
                    precision=0.0,
                    gold_size=g.size,
                    gen_size=0,
                    shared=0,
                    expansion_ratio=None,
                )
            )
            continue

        claimed.add(partner.key)
        shared = len(g.concept_ids & partner.concept_ids)
        pairs.append(
            PairRow(
                gold_key=g.key,
                gold_name=g.name,
                gen_key=partner.key,
                gen_name=partner.name,
                outcome=outcome,
                name_sim=_round(name_similarity(g.name, partner.name)),
                jaccard=_round(jaccard(g.concept_ids, partner.concept_ids)),
                recall=_round(shared / g.size) if g.size else 0.0,
                precision=_round(shared / partner.size) if partner.size else 0.0,
                gold_size=g.size,
                gen_size=partner.size,
                shared=shared,
                expansion_ratio=_round(partner.size / g.size) if g.size else None,
            )
        )

    unmatched_gold = [
        {"key": p.gold_key, "name": p.gold_name, "gold_size": p.gold_size}
        for p in pairs
        if p.outcome == "no_counterpart"
    ]
    unmatched_generated = [
        {"key": a.key, "name": a.name, "gen_size": a.size}
        for a in generated_sets
        if a.key not in claimed
    ]
    return PairingResult(pairs, unmatched_gold, unmatched_generated)


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

def per_criterion_macro(pairs: list[PairRow]) -> dict:
    """THE MEASURE OF RECORD: per-criterion 1:1 overlap, macro-averaged.

    Quote this, not :func:`micro_totals`. On this corpus the two disagree in
    direction, not just in magnitude, because a micro average is set by whichever
    concept set happens to be enormous:

        overall     micro recall 0.141 / precision 0.503
                    macro recall 0.542 / precision 0.484
        ARISTOTLE   micro recall 0.087 / precision 0.863   <- "worst recall, best precision"
                    macro recall 0.749 / precision 0.153   <- the opposite, and correct

    ARISTOTLE's micro recall was set by one 111,910-concept antihypertensive set we
    never build; its micro precision by one 10,720-concept aspirin set that matches
    gold exactly. Neither says anything about the other forty criteria. Per criterion,
    48 of 144 matched pairs reach full recall -- a fact the pooled number erases.

    The distribution matters more than the mean. ``recall_histogram`` is reported for
    that reason, and ``zero_overlap`` isolates the sharpest defect class: pairs where
    both sides exist and share NOTHING (e.g. gold Glimepiride 3,422 concepts against
    our 29, or our "linagliptin" set resolving to sitagliptin). Those are invisible in
    any pooled figure.
    """
    matched = [p for p in pairs if str(p.outcome).startswith("matched")]
    if not matched:
        return {"matched_pairs": 0}
    rec = sorted(p.recall for p in matched)
    pre = sorted(p.precision for p in matched)

    def _median(xs: list[float]) -> float:
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

    bands = [(1.0, "1.0"), (0.8, "0.8-1.0"), (0.5, "0.5-0.8"), (0.2, "0.2-0.5"), (0.0, "0-0.2")]
    hist: dict[str, int] = {label: 0 for _, label in bands}
    hist["0.0"] = 0
    for p in matched:
        if p.recall < 1e-9:
            hist["0.0"] += 1
            continue
        for lo, label in bands:
            if p.recall >= lo:
                hist[label] += 1
                break
    return {
        "matched_pairs": len(matched),
        "recall_mean": _round(sum(rec) / len(rec)),
        "recall_median": _round(_median(rec)),
        "precision_mean": _round(sum(pre) / len(pre)),
        "precision_median": _round(_median(pre)),
        "exact_pairs": sum(1 for p in matched if p.recall > 0.999 and p.precision > 0.999),
        "recall_histogram": hist,
        "zero_overlap": [
            {
                "gold_name": p.gold_name,
                "gen_name": p.gen_name,
                "gold_size": p.gold_size,
                "gen_size": p.gen_size,
            }
            for p in matched
            if p.recall < 1e-9
        ],
    }


def micro_totals(gold_sets: list[ResolvedSet], generated_sets: list[ResolvedSet]) -> dict:
    """Union-level totals -- SECONDARY. Concept mass, not criterion quality.

    Never quote this as the headline; see :func:`per_criterion_macro` for why the two
    invert on ARISTOTLE. Micro precision is dominated by the largest sets (aspirin's
    10,720 concepts carry almost all of 0.863), so the over-expanded lab sets barely
    move it.
    """
    gold_union: set[int] = set().union(*(s.concept_ids for s in gold_sets)) if gold_sets else set()
    gen_union: set[int] = (
        set().union(*(s.concept_ids for s in generated_sets)) if generated_sets else set()
    )
    shared = gold_union & gen_union
    return {
        "gold_union": len(gold_union),
        "generated_union": len(gen_union),
        "intersection": len(shared),
        "recall": _round(len(shared) / len(gold_union)) if gold_union else 0.0,
        "precision": _round(len(shared) / len(gen_union)) if gen_union else 0.0,
        "jaccard": _round(len(shared) / len(gold_union | gen_union))
        if (gold_union | gen_union)
        else 0.0,
    }


def over_expansion_rows(pairs: list[PairRow], min_ratio: float) -> list[dict]:
    """Matched pairs where the generated set is at least ``min_ratio`` times gold.

    First-class output, not a micro average: generated lab sets carry 8-34
    concepts where gold carries 1-3 (precision 0.03-0.12), and that asymmetry
    disappears entirely in a size-weighted mean.
    """
    rows = [
        {
            "gold_name": p.gold_name,
            "gen_name": p.gen_name,
            "gold_size": p.gold_size,
            "gen_size": p.gen_size,
            "expansion_ratio": p.expansion_ratio,
            "recall": p.recall,
            "precision": p.precision,
            "outcome": p.outcome,
        }
        for p in pairs
        if p.expansion_ratio is not None and p.expansion_ratio >= min_ratio
    ]
    return sorted(rows, key=lambda r: r["expansion_ratio"], reverse=True)


def build_report(
    trial: str,
    mode: str,
    gold_sets: list[ResolvedSet],
    generated_sets: list[ResolvedSet],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    meta: dict | None = None,
    out_of_scope_gold: list[ResolvedSet] | None = None,
) -> dict:
    pairing = pair_concept_sets(gold_sets, generated_sets, thresholds)
    counts: dict[str, int] = {}
    for p in pairing.pairs:
        counts[p.outcome] = counts.get(p.outcome, 0) + 1

    unresolvable = [
        {"set": s.name, "concept_ids": sorted(s.unresolvable_ids)}
        for s in (gold_sets + generated_sets)
        if s.unresolvable_ids
    ]

    report = {
        "trial": trial,
        "mode": mode,
        "thresholds": asdict(thresholds),
        "gold_concept_sets": len(gold_sets),
        "generated_concept_sets": len(generated_sets),
        "outcome_counts": counts,
        # Ordered deliberately: the macro block is the measure of record and is read
        # first; micro follows as concept mass. Swapping them invites the inversion
        # documented in per_criterion_macro.
        "per_criterion": per_criterion_macro(pairing.pairs),
        "micro": micro_totals(gold_sets, generated_sets),
        "pairs": [p.to_dict() for p in pairing.pairs],
        "unmatched_gold": pairing.unmatched_gold,
        "unmatched_generated": pairing.unmatched_generated,
        # Not "unmatched": never offered for matching. Gold censors at initiation of
        # either arm's drug; the generated artifact is the eligibility cohort and has no
        # CensoringCriteria at all, so these are outside what it attempts.
        "out_of_scope_gold": {
            "reason": "gold concept set referenced only from CensoringCriteria; the generated eligibility cohort has no such section",
            "sets": [
                {"key": s.key, "name": s.name, "size": s.size}
                for s in (out_of_scope_gold or [])
            ],
        },
        "over_expansion": over_expansion_rows(pairing.pairs, thresholds.over_expansion_ratio),
        # Circe's CONCEPT join drops these without an error; reporting them is a
        # fact about gold, not a resolver failure.
        "unresolvable_items": {
            "note": "concept_ids absent from the vocabulary; dropped by Circe, matching WebAPI",
            "sets": unresolvable,
        },
    }
    if meta:
        report.update(meta)
    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=MODES, required=True,
                    help="raw = item ids as listed (no DB); closure = Circe closure (needs DSN)")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    ap.add_argument("--vocab-schema", default=DEFAULT_VOCAB_SCHEMA)
    ap.add_argument("--generated-dir", default=str(DEFAULT_GENERATED_DIR))
    ap.add_argument("--gold-dir", default=str(GOLD_DIR))
    ap.add_argument("--trials", nargs="*", default=None,
                    help="subset of trial labels; default all six")
    ap.add_argument("--name-strong", type=float, default=DEFAULT_THRESHOLDS.name_strong)
    ap.add_argument("--name-weak", type=float, default=DEFAULT_THRESHOLDS.name_weak)
    ap.add_argument("--overlap-strong", type=float, default=DEFAULT_THRESHOLDS.overlap_strong)
    ap.add_argument("--over-expansion-ratio", type=float,
                    default=DEFAULT_THRESHOLDS.over_expansion_ratio)
    ap.add_argument("--out", default=None)
    return ap.parse_args(argv)


def _load(path: Path, label: str) -> dict:
    if not path.exists():
        raise SystemExit(f"missing {label}: {path}")
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    thresholds = Thresholds(
        name_strong=args.name_strong,
        name_weak=args.name_weak,
        overlap_strong=args.overlap_strong,
        over_expansion_ratio=args.over_expansion_ratio,
    )
    gold_dir = Path(args.gold_dir)
    gen_dir = Path(args.generated_dir)
    labels = args.trials or list(TRIALS)
    unknown = [t for t in labels if t not in TRIALS]
    if unknown:
        raise SystemExit(f"unknown trial label(s): {unknown}; known: {list(TRIALS)}")

    loaded = []
    for label in labels:
        gold_rel, gen_name = TRIALS[label]
        gold_path = gold_dir / gold_rel
        gen_path = gen_dir / gen_name
        loaded.append(
            (
                label,
                gold_path,
                gen_path,
                _load(gold_path, f"gold {label}"),
                _load(gen_path, f"generated {label}"),
            )
        )

    lookup = None
    vocab = None
    if args.mode == "closure":
        all_items: list[ConceptSetItem] = []
        for _, _, _, gold, gen in loaded:
            all_items.extend(items_of_cohort(gold))
            all_items.extend(items_of_cohort(gen))
        try:
            vocab = PostgresVocabulary(args.dsn, args.vocab_schema)
            lookup = vocab.prefetch(all_items)
        except Exception as exc:  # noqa: BLE001 -- must fail loudly, never fall back
            raise SystemExit(
                f"mode 'closure' needs the vocabulary at dsn={args.dsn!r} "
                f"schema={args.vocab_schema!r}, but it is unreachable: {exc}\n"
                "Refusing to fall back to --mode raw (raw and closure differ by 1.5x-3x)."
            ) from exc

    reports = []
    for label, gold_path, gen_path, gold, gen in loaded:
        all_gold_sets = resolve_cohort_sets(gold, args.mode, lookup)
        censoring_only = censoring_only_codeset_keys(gold)
        gold_sets = [s for s in all_gold_sets if s.key not in censoring_only]
        out_of_scope = [s for s in all_gold_sets if s.key in censoring_only]
        gen_sets = resolve_cohort_sets(gen, args.mode, lookup)
        reports.append(
            build_report(
                label, args.mode, gold_sets, gen_sets, thresholds,
                meta={
                    "gold_file": gold_path.name,
                    "generated_file": gen_path.name,
                    "generated_md5": _md5(gen_path),
                },
                out_of_scope_gold=out_of_scope,
            )
        )
    if vocab is not None:
        vocab.close()

    payload = {
        "mode": args.mode,
        "vocab_schema": args.vocab_schema if args.mode == "closure" else None,
        "generated_dir": str(gen_dir),
        "gold_dir": str(gold_dir),
        "thresholds": asdict(thresholds),
        "trials": reports,
    }

    out_path = Path(args.out) if args.out else OUT_DIR / f"{args.mode}_{gen_dir.name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    _print_console(payload)
    print(f"\nwrote {out_path}")
    return 0


def _print_console(payload: dict) -> None:
    mode = payload["mode"]
    print(f"MODE={mode}  vocab_schema={payload['vocab_schema']}  "
          f"thresholds={payload['thresholds']}")
    print(f"generated_dir={payload['generated_dir']}")

    # The measure of record goes first and gets the wide columns. The micro table
    # below is concept mass and is labelled as such, because on this corpus the two
    # disagree in DIRECTION (ARISTOTLE macro 0.749/0.153 vs micro 0.087/0.863) and a
    # reader who sees micro first will quote it.
    print("\nPER-CRITERION 1:1 (measure of record -- AGENTS.md EVALUATION)")
    hdr = (f"{'trial':<18}{'pairs':>6}{'rec_mean':>9}{'rec_med':>8}{'prec_mean':>10}"
           f"{'prec_med':>9}{'exact':>6}{'zero':>5}{'no_cp':>6}{'extra':>6}")
    print(hdr)
    print("-" * len(hdr))
    for r in payload["trials"]:
        c = r["outcome_counts"]
        pc = r.get("per_criterion") or {}
        if not pc.get("matched_pairs"):
            print(f"{r['trial']:<18}{'0':>6}   (no matched pairs)")
            continue
        print(f"{r['trial']:<18}{pc['matched_pairs']:>6}{pc['recall_mean']:>9.3f}"
              f"{pc['recall_median']:>8.3f}{pc['precision_mean']:>10.3f}"
              f"{pc['precision_median']:>9.3f}{pc['exact_pairs']:>6}"
              f"{len(pc.get('zero_overlap', [])):>5}"
              f"{c.get('no_counterpart', 0):>6}{len(r['unmatched_generated']):>6}")

    for r in payload["trials"]:
        zo = (r.get("per_criterion") or {}).get("zero_overlap") or []
        if not zo:
            continue
        print(f"\nZERO OVERLAP -- {r['trial']}  [{len(zo)} pairs share no concept at all]")
        for row in sorted(zo, key=lambda x: -(x["gold_size"] or 0)):
            print(f"  gold {row['gold_size']:>6} {row['gold_name'][:44]:<46}"
                  f"ours {row['gen_size']:>6}  {row['gen_name'][:34]}")

    print("\nMICRO (concept mass -- secondary, do not quote as quality)")
    hdr = (f"{'trial':<18}{'gsets':>6}{'asets':>6}{'g|U|':>9}{'a|U|':>8}"
           f"{'rec':>7}{'prec':>7}{'jacc':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in payload["trials"]:
        m = r["micro"]
        print(f"{r['trial']:<18}{r['gold_concept_sets']:>6}{r['generated_concept_sets']:>6}"
              f"{m['gold_union']:>9}{m['generated_union']:>8}"
              f"{m['recall']:>7.3f}{m['precision']:>7.3f}{m['jaccard']:>7.3f}")

    for r in payload["trials"]:
        rows = r["over_expansion"][:8]
        if not rows:
            continue
        print(f"\nover-expansion ({mode}) -- {r['trial']}  "
              f"[{len(r['over_expansion'])} pairs at ratio >= "
              f"{r['thresholds']['over_expansion_ratio']}]")
        for row in rows:
            print(f"  x{row['expansion_ratio']:>7.1f}  {row['gold_size']:>5} -> {row['gen_size']:<5}"
                  f"  rec {row['recall']:.2f} prec {row['precision']:.2f}  "
                  f"{row['gold_name']}  ->  {row['gen_name']}")


if __name__ == "__main__":
    raise SystemExit(main())
