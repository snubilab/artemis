"""One authoritative answer to: is this criterion already represented?

Every duplicate decision in Agent 1 routes through :func:`structural_verdict`,
which answers with DROP, KEEP or UNDECIDED over the two predicates below --
:func:`restates_or_group_alternative` for a flat criterion, and
:func:`or_group_subsumed_by` for a whole group. Four copies of that decision
existed before, all whole-string difflib ratios, none able to see a containment
relation:

    pubmed_fetcher._merge_parsed_items      (>= 0.7 duplicate)
    enricher._merge_criteria                (>= 0.7 duplicate)
    enricher._supplement_priority_merge     (< 0.5 means missing)
    enricher._pick_richer                   (raw count comparison)

Whole-string similarity cannot see that a 66-character alternative is already
stated inside a 330-character group -- the length gap alone puts the ratio
below every threshold. So ARISTOTLE's five stroke risk factors were correctly
collapsed into one ANY node and then re-added as five AND-ed top-level rules.
Circe ANDs rules, so the cohort came back empty against a gold standard of
1,113 patients.

Answering "not a duplicate" is not enough on its own, and that is why
:func:`structural_verdict` exists rather than a bare boolean. A caller that
reads False and then falls through to its own similarity gate reaches the same
wrong answer one line later: a 5-alternative group scores 0.939 against the
4-alternative wording of the same group and was dropped by exactly that route,
in both enricher merge sites, while 30 predicate-level tests stayed green.

The predicate is scoped to [OR-GROUP] items on purpose: it returns False the
moment ``items`` holds no OR-GROUP, so plain criteria lists behave exactly as
they do today. That scoping is what keeps the change to four items corpus-wide.
"""
from __future__ import annotations

import os
import re
from collections.abc import Sequence
from difflib import SequenceMatcher

# A named ablation, not a fallback. Attributing a cohort count to this module
# needs an arm that runs the identical pipeline with the deduplication off, and
# swapping source files mid-experiment leaves the tree broken if the run dies.
# Set ARTEMIS_DISABLE_ORGROUP_DEDUP=1 only to produce that control arm, and say
# so when reporting the number. Default is ON; tests/test_criteria_dedup.py
# pins that.
_ABLATION_ENV = "ARTEMIS_DISABLE_ORGROUP_DEDUP"


def dedup_enabled() -> bool:
    """:returns: False only when the ablation env var is explicitly set to 1."""
    return os.environ.get(_ABLATION_ENV, "").strip() != "1"

# The OR-GROUP wire format, defined once. _collapse_hierarchical_groups emits
# it, _parse_criteria_items splits it out, and this module reads it back.
# tests/test_dry_or_group_contract.py fails if any other module re-types it.
OR_GROUP_PREFIX = "[OR-GROUP] "
OR_GROUP_JOIN = " with any of: "
OR_GROUP_SEP = " | "

# A candidate restates an alternative when this fraction of its content tokens
# is already expressed by the group's alternatives. Measured separation on the
# ARISTOTLE group: lowest true positive 0.750, highest of 23 labelled negatives
# 0.500 ("Gestational diabetes" / "NYHA class IV congestive heart failure").
ALTERNATIVE_COVERAGE = 0.70
# Below this a candidate carries too little content for coverage to mean
# anything. It bounds the "one shared token decides" failure, whose consequence
# -- a mandatory criterion silently dropped, cohort widens -- is worse than the
# leak it permits.
#
# This was briefly relaxed to 1 to make a verbatim one-token alternative like
# "Prior stroke" register. That was unnecessary and unsafe, and both halves were
# measured. Unnecessary: gate (a), normalised identity, already returns True for
# a verbatim alternative floor-free, so every verdict in the negation/conjunction
# probe set is identical at 1 and at 2. Unsafe: against a group offering
# "Hypertension requiring pharmacological treatment | Diabetes mellitus |
# Prior stroke", the bare criteria "Hypertension", "Diabetes" and "Stroke" are
# each retained at 2 and silently DELETED at 1 -- exactly the hazard above,
# re-opened for no gain.
#
# The polarity gate does not subsume this floor either. When a candidate and an
# alternative both carry a negator they land in the SAME polarity pool, polarity
# passes them through, and this floor is the only remaining defence.
MIN_CONTENT_TOKENS = 2
_FUZZY_TOKEN = 0.85

_LIST_MARKER = re.compile(r"^\s*[\(\[]?(?:[a-z]|[ivx]{1,4}|\d{1,2})[.)\]]\s+", re.IGNORECASE)
_WORD = re.compile(r"[a-z]+|\d+(?:\.\d+)?|<=|>=|[<>]")
_ABBREV = re.compile(r"\b[A-Z]{2,6}\b")
_STOPWORDS = frozenset("""a an the of or and with to for in on at by is are was were be
been being that this those these not no if as from than then must may can shall should
will either both any all each per within prior previous documented enough least one more
year years yrs old due cause separate occasions apart month months week weeks patient
patients subject subjects who has have had time""".split())

# Words that flip a criterion's polarity. Every one of these is ALSO a stopword
# or is stripped as noise by _content_tokens, which is exactly how the negated
# form came to tokenise identically to the positive one it negates.
#
# Deliberately matched against the RAW token stream (see _is_negated), not
# against content tokens: that is what makes polarity independent of both
# MIN_CONTENT_TOKENS and ALTERNATIVE_COVERAGE, and it is the ordering that lets
# the token floor drop to 1 safely.
#
# Two known imprecisions, both stated so the next reader does not file them as
# bugs. (1) This is a bag of words over the whole string with no scope, so an
# incidental negation ("atrial fibrillation not due to a reversible cause")
# marks the item negated and it is RETAINED rather than deduplicated. (2) _WORD
# is [a-z]+, so "non" fires on the hyphenated "non-valvular" but not on the
# fused "nonvalvular". Both failure modes only ever over-retain a criterion;
# neither can delete one. Over-retention is the safe direction here -- a dropped
# exclusion widens the cohort silently, a kept duplicate does not.
_NEGATORS = frozenset("""no not without absence absent free never neither nor non
excluding exclude excluded lack lacking unable negative""".split())


def _normalize(text: str) -> str:
    """Strip list markers, fold comparison glyphs, casefold.

    :param text: raw criterion text.
    :returns: normalised form used for tokenisation.
    """
    s = _LIST_MARKER.sub("", str(text).strip())
    s = s.replace("≤", "<=").replace("≥", ">=")
    s = re.sub(r"\s+", " ", s)
    return s.strip().strip("*-• ").rstrip(".;,:").casefold()


def _content_tokens(text: str) -> list[str]:
    """:param text: raw criterion text. :returns: meaning-bearing tokens, in order."""
    return [t for t in _WORD.findall(_normalize(text))
            if len(t) > 1 and t not in _STOPWORDS]


def _raw_tokens(text: str) -> list[str]:
    """Every token of ``text``, stopwords included.

    :param text: raw criterion text.
    :returns: the normalised token stream before any content filtering.
    """
    return _WORD.findall(_normalize(text))


def _is_negated(text: str) -> bool:
    """:param text: raw criterion text. :returns: True when it carries a negation word."""
    return any(t in _NEGATORS for t in _raw_tokens(text))


# Conjunction spellings a trial protocol actually uses. Keying only on the token
# "and" left "Type 2 diabetes PLUS established cardiovascular disease" and its
# siblings classified as restatements and silently deleted -- the very harm this
# gate exists to stop, since a dropped conjunctive criterion widens the cohort.
#
# Bare "with" is deliberately absent: it is far more often descriptive
# ("atrial fibrillation with rapid ventricular response") than conjunctive, and
# treating it as a conjunction would suppress real restatements.
_CONJUNCTION_MARKER = re.compile(
    r"\band\b|\bplus\b|\bas well as\b|\bcombined with\b|\btogether with\b"
    r"|\balong with\b|\bin addition to\b|\baccompanied by\b|\bconcomitant\b",
)
_DISJUNCTION_MARKER = re.compile(r"\bor\b|\beither\b|\bany of\b")


def _is_conjunction_only(text: str) -> bool:
    """True when ``text`` joins its parts conjunctively and never disjunctively.

    Only consulted for candidates that needed two or more alternatives pooled to
    clear the coverage bar. Such a candidate either offers the alternatives
    (harmless, the group already offers them) or REQUIRES them together, which
    narrows the cohort and is a different criterion.

    No structure is parsed, so "A and B or C" reads as disjunctive. That
    asymmetry is deliberate but it is not the safe direction -- an unrecognised
    conjunction is DELETED, not retained -- so the marker set above is a list of
    real protocol spellings rather than a single token.

    :param text: raw criterion text.
    :returns: True when a conjunction marker is present and no disjunction is.
    """
    normalised = _normalize(text)
    return bool(_CONJUNCTION_MARKER.search(normalised)) and not _DISJUNCTION_MARKER.search(normalised)


def _abbreviations(text: str) -> set[str]:
    """Casefolded ALL-CAPS runs in the ORIGINAL text (TIA, SE, LVEF, AF, MI).

    Gating the initialism rule on these is what stops it matching an arbitrary
    two-letter lowercase word against any adjacent word pair.
    """
    return {m.group(0).casefold() for m in _ABBREV.finditer(str(text))}


def _initialism_run(abbr: str, words: Sequence[str]) -> int:
    """Index of the consecutive run of ``words`` whose initials spell ``abbr``, else -1.

    This is what lets "TIA" match "transient ischemic attack" and "SE" match
    "systemic embolus" without any medical abbreviation dictionary.
    """
    n = len(abbr)
    if n < 2 or n > 6 or not abbr.isalpha():
        return -1
    for i in range(0, len(words) - n + 1):
        if "".join(w[0] for w in words[i:i + n]) == abbr:
            return i
    return -1


def or_group_alternatives(item: str) -> list[str]:
    """The alternatives inside an [OR-GROUP] item; empty for every other item.

    The header (everything before OR_GROUP_JOIN) is deliberately excluded: it
    carries the group's own mandatory AND-criteria, e.g. ARISTOTLE's atrial
    fibrillation and age >= 18. Comparing against the whole line instead is the
    already-rejected "naive containment" guard.

    :param item: one criterion string.
    :returns: the group's alternatives, or [] when ``item`` is not an OR-GROUP.
    """
    if not isinstance(item, str) or not item.startswith(OR_GROUP_PREFIX):
        return []
    _, sep, tail = item[len(OR_GROUP_PREFIX):].partition(OR_GROUP_JOIN)
    if not sep:
        return []
    return [c.strip() for c in tail.split(OR_GROUP_SEP) if c.strip()]


def is_or_group(item: str) -> bool:
    """:param item: one criterion string. :returns: True when it is a well-formed OR-GROUP."""
    return bool(or_group_alternatives(item))


def _token_coverage(cand_tokens: Sequence[str], cand_abbr: set[str],
                    ref_tokens: Sequence[str], ref_abbr: set[str]) -> float:
    """Fraction of candidate content tokens already expressed by the reference.

    Asymmetric on purpose: a candidate that ADDS content must not be judged a
    duplicate of a shorter alternative. The reference is the POOLED token bag of
    every alternative, which is load-bearing -- ARISTOTLE's "Diabetes mellitus or
    hypertension requiring pharmacological treatment" spans two alternatives and
    scores only 0.67 against the best single one, below threshold.

    :param cand_tokens: content tokens of the criterion under test.
    :param cand_abbr: ALL-CAPS runs in the candidate's original text.
    :param ref_tokens: content tokens of every alternative, concatenated.
    :param ref_abbr: ALL-CAPS runs across the alternatives' original text.
    :returns: coverage in [0.0, 1.0].
    """
    if len(cand_tokens) < MIN_CONTENT_TOKENS:
        return 0.0
    ref_set = set(ref_tokens)
    covered = [False] * len(cand_tokens)
    for i, tok in enumerate(cand_tokens):
        if tok in ref_set:
            covered[i] = True
        elif any(SequenceMatcher(None, tok, r).ratio() >= _FUZZY_TOKEN for r in ref_set):
            covered[i] = True          # embolism <-> embolus, pharmacologic <-> pharmacological
        elif tok in cand_abbr and _initialism_run(tok, ref_tokens) >= 0:
            covered[i] = True          # candidate "SE" <-> reference "systemic embolus"
    for ref in ref_set & ref_abbr:     # reference "TIA" <-> candidate "transient ischemic attack"
        start = _initialism_run(ref, cand_tokens)
        if start >= 0:
            for k in range(start, start + len(ref)):
                covered[k] = True
    return sum(covered) / float(len(cand_tokens))


def restates_or_group_alternative(
    candidate: str,
    items: Sequence[str],
    threshold: float = ALTERNATIVE_COVERAGE,
) -> bool:
    """True when ``candidate`` adds nothing beyond alternatives already listed in
    an [OR-GROUP] inside ``items``.

    Two early returns carry the whole safety argument:

    1. An OR-GROUP candidate is NEVER a duplicate. Without this, a richer group
       is discarded against a poorer one -- measured: ARISTOTLE's 5-alternative
       PDF group scores 0.722 against the 4-alternative CT.gov group and would
       be dropped, destroying exactly the structure this change exists to keep.
       Whether one GROUP supersedes another is a different question with a
       different answer shape; it lives in :func:`or_group_subsumed_by`, and
       callers reach both through :func:`structural_verdict`.
    2. No OR-GROUP in ``items`` means False. That is why ordinary criteria lists
       -- including the literal-substring case in TestLLMFallback -- are
       untouched, and why the corpus blast radius is four items.

    Three further gates, in the order they run:

    a. Normalised identity is a restatement outright -- threshold-free and
       floor-free. This mirrors the oracle in
       tests/test_and_explosion_invariant._identity_violations, which already
       declared identity a violation the coverage score could not detect.
    b. Polarity must match. The alternatives are partitioned by
       :func:`_is_negated` and only the pool matching the candidate is scored,
       so a negated criterion is never deleted against a positive alternative.
       Dropping an exclusion WIDENS the cohort silently, which is the opposite
       direction from the empty-cohort bug and harder to notice.
    c. A candidate that needed two or more alternatives pooled to clear the bar
       must not be a bare conjunction of them (:func:`_is_conjunction_only`).
       Candidates matched by a single alternative never reach this branch.

    :param candidate: the criterion being considered for addition or retention.
    :param items: the list it would join; the OR-GROUP reference is read from here.
    :param threshold: minimum content-token coverage to call it a restatement.
    :returns: True when the candidate is an alternative the group already states.
    """
    if not dedup_enabled():
        return False
    if not isinstance(candidate, str) or is_or_group(candidate):
        return False
    alternatives: list[str] = []
    for item in items:
        alternatives.extend(or_group_alternatives(item))
    if not alternatives:
        return False

    normalised = _normalize(candidate)
    if any(_normalize(alt) == normalised for alt in alternatives):
        return True

    pool = [alt for alt in alternatives if _is_negated(alt) == _is_negated(candidate)]
    if not pool:
        return False

    cand_tokens = _content_tokens(candidate)
    cand_abbr = _abbreviations(candidate)
    ref_tokens: list[str] = []
    ref_abbr: set[str] = set()
    for alt in pool:
        ref_tokens.extend(_content_tokens(alt))
        ref_abbr |= _abbreviations(alt)
    if _token_coverage(cand_tokens, cand_abbr, ref_tokens, ref_abbr) < threshold:
        return False

    spans_alternatives = all(
        _token_coverage(cand_tokens, cand_abbr, _content_tokens(alt), _abbreviations(alt))
        < threshold for alt in pool
    )
    return not (spans_alternatives and _is_conjunction_only(candidate))


def or_group_subsumed_by(
    candidate: str,
    items: Sequence[str],
    threshold: float = ALTERNATIVE_COVERAGE,
) -> bool:
    """True when ``candidate`` is an OR-GROUP whose every alternative another group states.

    "Richer" is superset-of-alternatives, never union. Unioning a 5-alternative
    protocol group with a 4-alternative registry group yields an ANY node of 9
    that no source wrote: on an inclusion group that admits patients the
    protocol excludes, on an exclusion group it narrows the cohort. It also
    duplicates alternatives inside one node, because the two sources word the
    same risk factor differently. A superset invents nothing.

    Subsumption is therefore computed with :func:`restates_or_group_alternative`
    rather than by set operations on the raw alternative strings -- the two
    sources are paraphrases ("Prior stroke, TIA or systemic embolus" against
    "transient ischemic attack (TIA) or Systemic Embolism (SE)"), and the fuzzy
    token plus initialism machinery is exactly what relates them.

    When NEITHER group subsumes the other, both are kept. Two ANY nodes AND-ed
    is stricter than either alone, and it is what the two sources jointly
    assert; it is also already today's behaviour whenever the similarity ratio
    happens to fall below threshold.

    No ``item is candidate`` guard: callers exclude the candidate positionally.
    An identity guard makes two identical groups mutually subsume, and BOTH
    vanish.

    :param candidate: the group being considered for removal.
    :param items: the other criteria it sits alongside.
    :param threshold: minimum coverage for one alternative to restate another.
    :returns: True when some group in ``items`` already offers every alternative.
    """
    if not dedup_enabled():
        return False
    alternatives = or_group_alternatives(candidate)
    if not alternatives:
        return False
    for item in items:
        if not or_group_alternatives(item):
            continue
        if all(restates_or_group_alternative(alt, [item], threshold) for alt in alternatives):
            return True
    return False


# What a caller must do with an item. UNDECIDED is the only verdict that hands
# control back to the caller's own legacy similarity gate; DROP and KEEP are
# both final, and KEEP is the half that fixes the defect -- it says the legacy
# gate has NO authority over this item. Without it, both enricher merge sites
# obeyed the predicate's "an OR-GROUP is never a duplicate" and then dropped the
# group anyway on a 0.939 whole-string ratio two lines later.
DROP = "drop"
KEEP = "keep"
UNDECIDED = "undecided"


def structural_verdict(
    candidate: str,
    items: Sequence[str],
    threshold: float = ALTERNATIVE_COVERAGE,
) -> str:
    """The one authoritative answer to "what should this merge site do with this item?".

    :param candidate: the criterion being considered for addition or retention.
    :param items: the criteria it would sit alongside, excluding itself.
    :param threshold: minimum content-token coverage to call it a restatement.
    :returns: :data:`DROP`, :data:`KEEP`, or :data:`UNDECIDED`.
    """
    if not dedup_enabled():
        return UNDECIDED
    if is_or_group(candidate):
        return DROP if or_group_subsumed_by(candidate, items, threshold) else KEEP
    return DROP if restates_or_group_alternative(candidate, items, threshold) else UNDECIDED


def prune_superseded(items: Sequence[str], threshold: float = ALTERNATIVE_COVERAGE) -> list[str]:
    """Drop items superseded by something else in the same list.

    Progressive on purpose: each item is judged against the survivors so far
    plus the items not yet examined, NOT against "everything except me". Under
    the latter, two identical groups each subsume the other and both disappear.

    The cost of the progressive form is that the result is order-dependent when
    two groups mutually subsume -- the later one wins. That is pinned by
    tests/test_or_group_subsumption.py so a future reorder cannot change which
    group survives by accident.

    :param items: a merged criteria list.
    :param threshold: minimum content-token coverage to call it a restatement.
    :returns: the surviving items, in their original order.
    """
    kept: list[str] = []
    for i, item in enumerate(items):
        if structural_verdict(item, kept + list(items[i + 1:]), threshold) != DROP:
            kept.append(item)
    return kept
