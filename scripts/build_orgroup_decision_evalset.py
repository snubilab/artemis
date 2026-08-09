#!/usr/bin/env python3
"""Build the gold-derived labelled table for the OR-GROUP restatement decision.

``src/agents/agent1/criteria_dedup.py`` answers exactly one question:

    does this criterion restate an alternative that an [OR-GROUP] already offers?

Wrong NO deletes nothing but re-adds the alternative as a top-level rule; Circe
ANDs it and the cohort collapses (the ARISTOTLE 0-patient bug). Wrong YES
deletes a mandatory or EXCLUSION criterion and the cohort silently WIDENS. This
table exists so a proposed replacement -- the LLM judge in
``criteria_dedup_judge.py`` -- can be shown better or worse in BOTH directions.

WHY THIS IS A REWRITE, NOT AN EDIT
----------------------------------
The first oracle paired our criterion text to gold's criterion text by
whole-string difflib. Using string similarity to build the answer key for a
semantic-similarity judgement is circular, and it produced clinically inverted
labels:

* LEADER "Chronic heart failure NYHA class II-III" was labelled DISTINCT because
  difflib scored it 0.895 against the standalone EXCLUSION rule "Chronic heart
  failure (NYHA class IV)" and only 0.723 against the group alternative "Heart
  failure (NYHA II-III)" it actually restates.
* CAROLINA "Type 1 diabetes mellitus", an EXCLUSION, was labelled RESTATEMENT of
  the inclusion alternative "Type 2 diabetes mellitus" at difflib 0.958.

There is therefore NO string similarity anywhere in the label path of this
builder. Candidates are linked to gold BY MEANING -- resolved concept-set
closure overlap, computed by ``src.services.conceptset_closure``, which mirrors
the SQL WebAPI renders for a Circe expression. The only string comparison in the
file is an exact normalised equality used to TAG a row ``verbatim`` vs
``paraphrase`` for reporting; it never decides a label.

WHERE THE PARAPHRASES COME FROM
-------------------------------
Gold alone supplies none. A criterion never appears both inside a disjunctive
group and as a standalone single-criterion rule, so gold holds exactly one
wording per criterion (measured: 0 pairs across all six trials). The second
wording is OUR generated CIRCE's, linked to gold by closure Jaccard.

LABELS, FROM GOLD STRUCTURE ONLY
--------------------------------
    linked gold concept set is a member of a disjunctive group -> restatement
    linked gold concept set belongs to a standalone ALL rule    -> distinct

Five structural facts are load-bearing; each cost a wrong label in the first
attempt and each is pinned by ``tests/test_orgroup_evalset.py``:

1. ``AT_LEAST`` with ``Count >= 2`` is NOT a disjunction. CAROLINA
   ``InclusionRules[1].Groups[3]`` is AT_LEAST/2 ("at least two of the following
   CV risk factors"); a 2-of-6 group entails no individual member, so a criterion
   restating one member is not implied by it. Only ``ANY`` and ``AT_LEAST`` with
   Count in (None, 1) are disjunctive.
2. ``AT_MOST`` is not in the disjunctive set at all. Gold contains zero AT_MOST
   nodes (census: ALL 153, AT_LEAST 27, ANY 18 across all gold files), so
   admitting it is dead code -- and AT_MOST N is an upper bound whose members are
   not interchangeable, so if it ever went live it would INVERT the label.
3. Gold's numeric and temporal constraints are part of the criterion. 30 of 62
   leaf alternatives carry ValueAsNumber / RangeHighRatio / EraLength / DoseValue
   / Unit. Dropping them presented "Systolic blood pressure (SBP)" as an
   alternative where gold means "> 140"; a bare concept name with a dropped
   constraint is a different criterion.
4. Polarity is a hard gate on the LINK. Circe spells an exclusion as
   ``Occurrence.Type == 0, Count == 0`` (exactly zero). A link whose candidate
   bucket differs from the gold criterion's is REFUSED and never labelled -- the
   first attempt merged both buckets into one pool and matched "Congestive heart
   failure of NYHA class III or IV" to "No congestive heart failure ...".
   The GROUP CONTEXT is not filtered by polarity: every row records
   ``candidate_bucket``, ``or_group_polarities`` and ``polarity_relation``
   instead. Filtering would delete every exclusion negative, including the
   CAROLINA "Type 1 diabetes mellitus" vs "Type 2 diabetes mellitus" pair the
   first attempt got backwards. ``enricher`` does dedup the inclusion and
   exclusion lists separately, so ``cross_bucket`` rows are EASIER than
   production; they are counted apart in the summary.
5. A parent group that merely re-wraps its child group is not emitted, and a
   ONE-member ``ANY`` is not a group at all -- PLATO's rule 3 is ``ANY`` over a
   single exclusion criterion, and reading it as a disjunction marked that
   criterion safe to delete.

Nested composite alternatives render their own logic, parenthesised:
``(Age >= 60 and (A or B))``. Flattening them to an unparenthesised "and/or"
string asserts logic gold never wrote.

n IS SMALL AND CONFOUNDED. SAY SO.
----------------------------------
This is a CASE AUDIT, not a benchmark. As shipped it is n = 28 rows (7
restatement, 21 distinct) over 6 trials. Two trivial baselines are written into
the summary so nobody can quote an arm's accuracy without them:

* always answer "distinct" -> 75.0%
* answer "distinct" iff the candidate is an EXCLUSION criterion -> 100.0%

The second is a CONFOUND and a property of gold, not of the arms: every gold
disjunctive group is inclusion-polarity and gold keeps its exclusion criteria as
standalone AND-ed rules, so the label is a function of the bucket. The bucket is
not part of an arm's input -- both arms see only the candidate text and the
alternatives, and "Aspirin" or "pioglitazone" carry no negation -- but it does
mean this table cannot certify inclusion-side over-deletion at all.

NO PAID CALL. The builder reads CIRCE JSON and the vocabulary only; it never
runs the extractor. ``pubmed_fetcher._llm_parse_criteria`` is nonetheless
stubbed to ``[]`` for the whole build (:func:`no_paid_llm`) and the stub asserts
it was never reached, so "no LLM was billed" is enforced rather than asserted in
prose.

Usage::

    .venv/bin/python scripts/build_orgroup_decision_evalset.py
    .venv/bin/python scripts/build_orgroup_decision_evalset.py --dsn ...

Deterministic: content-derived ids, sorted output, no timestamps. Two builds of
an unchanged tree are byte-identical.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Imported, never retyped. tests/test_dry_or_group_contract.py fails if any
# module re-types this format; a builder that guesses it produces a table on
# which every arm scores the same because every probe sees an empty group.
from src.agents.agent1.criteria_dedup import (  # noqa: E402
    OR_GROUP_JOIN,
    OR_GROUP_PREFIX,
    OR_GROUP_SEP,
    or_group_alternatives,
)
from src.services.conceptset_closure import (  # noqa: E402
    DEFAULT_VOCAB_SCHEMA,
    PostgresVocabulary,
    VocabularyLookup,
    concept_set_name,
    items_of_cohort,
    iter_concept_sets,
    resolve_concept_set,
)

SCHEMA_VERSION = "2.0"
OUTPUT_PATH = REPO_ROOT / "data" / "benchmark_data" / "orgroup_decision_evalset.json"
GOLD_ROOT = REPO_ROOT / "data" / "gold"
GENERATED_ROOT = REPO_ROOT / "tmp" / "circe_b"
DEFAULT_DSN = os.environ.get(
    "ARTEMIS_VOCAB_DSN", "postgresql://postgres:mypass@localhost:5432/postgres"
)

# trial -> (gold file under data/gold/, generated CIRCE under tmp/circe_b/).
# The same treatment-arm pairing scripts/conceptset_overlap_eval.py uses: each
# generated cohort's PrimaryCriteria anchors on the study drug, so the arm is
# unambiguous. Gold comparator arms have no generated counterpart.
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
    "EMPA-REG": (
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

# Minimum closure Jaccard for "these two concept sets mean the same criterion".
LINK_JACCARD = 0.50
# When the runner-up gold set is this close, the closure does not decide which
# criterion the candidate restates. Refuse rather than pick.
LINK_MARGIN = 0.05
# A one-member group states a single criterion; it offers no alternative.
MIN_GROUP_ALTERNATIVES = 2

INCLUSION = "inclusion"
EXCLUSION = "exclusion"
MIXED = "mixed"

RESTATEMENT = "restatement"
DISTINCT = "distinct"

# TROY prefixes every curated concept set with its domain namespace. That tag is
# curation bookkeeping, not criterion text.
_TROY_TAG = re.compile(r"^\s*\[TROY[^\]]*\]\s*")
_ALNUM = re.compile(r"[a-z0-9]+")

_OPS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "="}


# --------------------------------------------------------------------------- #
# no paid call
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def no_paid_llm() -> Iterator[list[str]]:
    """Stub the one LLM entry point Agent 1 can reach, and prove it was not used.

    This builder reads CIRCE JSON, so no call is on any code path. The stub is a
    hard gate rather than a comment because ``resolve_model()`` returns
    ``"gpt-4o"`` with no ``vllm/`` prefix, which reaches a PAID provider; the
    project has already shipped one benchmark labelled local that OpenAI served.

    :returns: a list that stays empty; a non-empty list means a call was made.
    """
    import src.agents.agent1.pubmed_fetcher as pubmed_fetcher  # noqa: PLC0415

    calls: list[str] = []
    original = pubmed_fetcher._llm_parse_criteria

    def _stub(*args, **kwargs):
        calls.append("_llm_parse_criteria")
        return []

    pubmed_fetcher._llm_parse_criteria = _stub
    try:
        yield calls
    finally:
        pubmed_fetcher._llm_parse_criteria = original


# --------------------------------------------------------------------------- #
# polarity
# --------------------------------------------------------------------------- #
def occurrence_polarity(criterion: dict) -> str:
    """Read a Circe criteria wrapper's polarity from its Occurrence node.

    Circe spells "the patient must NOT have this" as ``Type 0 / Count 0``
    (exactly zero) or ``Type 1 / Count 0`` (at most zero). Everything else
    requires the event.

    :param criterion: a CIRCE criteria wrapper.
    :returns: :data:`INCLUSION` or :data:`EXCLUSION`.
    """
    occurrence = criterion.get("Occurrence") or {}
    if int(occurrence.get("Count", 1) or 0) == 0 and int(occurrence.get("Type", 2) or 0) in (0, 1):
        return EXCLUSION
    return INCLUSION


def _combine_polarity(values: Iterable[str]) -> str:
    """:param values: leaf polarities. :returns: the shared one, or :data:`MIXED`."""
    seen = set(values)
    if not seen:
        return INCLUSION
    if len(seen) == 1:
        return seen.pop()
    return MIXED


def node_polarity(node: dict) -> str:
    """:param node: a CIRCE group. :returns: the polarity of every leaf beneath it."""
    values = [occurrence_polarity(c) for c in node.get("CriteriaList") or []]
    values += [node_polarity(s) for s in node.get("Groups") or []]
    return _combine_polarity(values)


# --------------------------------------------------------------------------- #
# disjunction
# --------------------------------------------------------------------------- #
def is_disjunctive(node: dict) -> bool:
    """Does satisfying ONE member satisfy this node?

    ``ANY`` and ``AT_LEAST`` with Count in (None, 1) do. ``AT_LEAST`` with
    Count >= 2 does NOT -- CAROLINA's "at least two of the following CV risk
    factors" entails no individual member, so a criterion restating one member is
    not implied and must never be labelled a restatement. ``AT_MOST`` is excluded
    outright: gold has zero of them, and an upper bound's members are not
    interchangeable, so admitting it would invert the label if it ever appeared.

    :param node: a CIRCE group.
    :returns: True when one satisfied member satisfies the node.
    """
    node_type = str(node.get("Type") or "")
    if node_type == "ANY":
        return True
    if node_type == "AT_LEAST":
        return node.get("Count") in (None, 1)
    return False


def is_conjunctive(node: dict) -> bool:
    """:param node: a CIRCE group. :returns: True for ``ALL``."""
    return str(node.get("Type") or "") == "ALL"


def entails_every_member(node: dict) -> bool:
    """Must every member hold for this node to be satisfied?

    ``ALL`` obviously. So does a ONE-member ``ANY`` or ``AT_LEAST``: PLATO's rule
    3 ("a need for oral anticoagulation therapy") is ``ANY`` over a single
    criterion, which is a mandatory criterion wearing a disjunction's Type. Before
    this, that rule made its one member look like a group alternative and the
    candidate that restated it was labelled RESTATEMENT -- an exclusion criterion
    marked safe to delete.

    ``AT_MOST`` is deliberately NOT folded in here even at one member: it is a
    negation, and gold contains none, so guessing would be an inversion for zero
    coverage.

    :param node: a CIRCE group.
    :returns: True when satisfying the node requires every member.
    """
    node_type = str(node.get("Type") or "")
    if node_type == "ALL":
        return True
    return node_type in ("ANY", "AT_LEAST") and _member_count(node) < MIN_GROUP_ALTERNATIVES


def _member_count(node: dict) -> int:
    """:param node: a CIRCE group. :returns: its direct member count."""
    return (len(node.get("CriteriaList") or [])
            + len(node.get("DemographicCriteriaList") or [])
            + len(node.get("Groups") or []))


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def _clean_name(name: str) -> str:
    """:param name: a TROY concept-set name. :returns: it without the domain tag."""
    return _TROY_TAG.sub("", str(name or "")).strip()


def _fmt_number(value) -> str:
    """:param value: a Circe numeric. :returns: it without a trailing ``.0``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def _comparison(spec: dict, suffix: str = "") -> str:
    """Render a Circe ``{"Op": ..., "Value": ..., "Extent": ...}`` node.

    :param spec: the numeric constraint.
    :param suffix: unit or scale text appended to every value.
    :returns: e.g. ``"> 140 mg/dL"`` or ``"not between 6.5 and 10"``.
    """
    op = str(spec.get("Op", "")).lower()
    value = _fmt_number(spec.get("Value"))
    if op in ("bt", "!bt"):
        word = "between" if op == "bt" else "not between"
        return f"{word} {value}{suffix} and {_fmt_number(spec.get('Extent'))}{suffix}"
    return f"{_OPS.get(op, op)} {value}{suffix}".strip()


def _unit_suffix(payload: dict) -> str:
    """:param payload: a Circe domain payload. :returns: ``" mg/dL"`` or ``""``."""
    units = payload.get("Unit") or []
    if isinstance(units, list) and units and isinstance(units[0], dict):
        code = units[0].get("CONCEPT_CODE") or units[0].get("CONCEPT_NAME")
        if code:
            return f" {code}"
    return ""


def render_leaf(criterion: dict, names: dict[int, str]) -> str | None:
    """Render one CriteriaList entry, constraints included.

    The constraints are the point. Gold's "[TROY lab] Systolic blood pressure
    (SBP)" carries ``ValueAsNumber > 140``; presenting the bare concept name as an
    alternative offers the group a criterion gold never wrote.

    :param criterion: a CIRCE criteria wrapper.
    :param names: codeset id -> concept set name, for the same file.
    :returns: rendered text, or None when the entry names no concept set.
    """
    body = criterion.get("Criteria") or {}
    for payload in body.values():
        if not isinstance(payload, dict):
            continue
        codeset_id = payload.get("CodesetId")
        if codeset_id is None:
            continue
        base = _clean_name(names.get(codeset_id, f"ConceptSet {codeset_id}"))
        unit = _unit_suffix(payload)
        parts: list[str] = []
        if isinstance(payload.get("ValueAsNumber"), dict):
            parts.append(_comparison(payload["ValueAsNumber"], unit))
        if isinstance(payload.get("RangeHighRatio"), dict):
            parts.append(_comparison(payload["RangeHighRatio"], "x upper limit of normal"))
        if isinstance(payload.get("EraLength"), dict):
            parts.append(f"era length {_comparison(payload['EraLength'], ' days')}")
        if isinstance(payload.get("DoseValue"), dict):
            parts.append(f"dose {_comparison(payload['DoseValue'])}")
        text = f"{base} {'; '.join(parts)}".strip() if parts else base
        if occurrence_polarity(criterion) == EXCLUSION:
            text = f"absence of {text}"
        return text
    return None


def render_demographic(demographic: dict) -> str | None:
    """Render one DemographicCriteriaList entry.

    ARISTOTLE's "Age >= 75" is a real alternative of the stroke-risk group, so
    omitting it would make a generated "Age 75 years or older" candidate
    unanswerable by any arm.

    :param demographic: one DemographicCriteriaList entry.
    :returns: rendered text, or None when nothing is constrained.
    """
    parts: list[str] = []
    for field_name, spec in sorted(demographic.items()):
        if isinstance(spec, dict) and "Value" in spec:
            parts.append(f"{field_name} {_comparison(spec)}")
        elif isinstance(spec, list) and spec:
            labels = [str(c.get("CONCEPT_NAME")) for c in spec if isinstance(c, dict)]
            if labels:
                parts.append(f"{field_name} in {', '.join(labels)}")
    return " and ".join(parts) if parts else None


def render_node_inline(node: dict, names: dict[int, str]) -> str | None:
    """Render a nested group as ONE parenthesised alternative of its parent.

    The logic is rendered honestly. ``ALL(Age >= 60, AT_LEAST1(A, B))`` becomes
    ``"(Age >= 60 and (A or B))"``; the first attempt flattened it to an
    unparenthesised "and/or" string that asserts a different requirement.

    :param node: a nested CIRCE group.
    :param names: codeset id -> concept set name.
    :returns: rendered text, or None when the group renders nothing.
    """
    members = _render_members(node, names)
    if not members:
        return None
    if len(members) == 1:
        return members[0]

    node_type = str(node.get("Type") or "")
    count = node.get("Count")
    if is_disjunctive(node):
        body = " or ".join(members)
    elif is_conjunctive(node):
        body = " and ".join(members)
    elif node_type == "AT_LEAST":
        body = f"at least {count} of: " + ", ".join(members)
    elif node_type == "AT_MOST":
        body = f"at most {count} of: " + ", ".join(members)
    else:
        body = f"{node_type or 'group'} of: " + ", ".join(members)
    return f"({body})"


def _render_members(node: dict, names: dict[int, str],
                    leaf_index: dict[int, str] | None = None) -> list[str]:
    """:param node: a CIRCE group. :param names: codeset id -> name.
    :param leaf_index: when given, filled with codeset id -> its rendered alternative,
        so a labelled row can name the exact alternative it restates without
        re-deriving a position.
    :returns: every direct member rendered, in criteria / demographic / group order."""
    members: list[str] = []
    for criterion in node.get("CriteriaList") or []:
        text = render_leaf(criterion, names)
        if text:
            members.append(text)
            if leaf_index is not None:
                for payload in (criterion.get("Criteria") or {}).values():
                    if isinstance(payload, dict) and payload.get("CodesetId") is not None:
                        leaf_index.setdefault(int(payload["CodesetId"]), text)
    for demographic in node.get("DemographicCriteriaList") or []:
        text = render_demographic(demographic)
        if text:
            members.append(text)
    for sub in node.get("Groups") or []:
        text = render_node_inline(sub, names)
        if text:
            members.append(text)
    return members


def sanitise(text: str) -> str:
    """Keep the wire format parseable.

    An alternative containing the separator would split into two on read-back.
    Both substitutions are caught by the round-trip assertion in :func:`render_wire`.

    :param text: rendered alternative text.
    :returns: text safe to place between OR_GROUP_SEP separators.
    """
    return text.replace(OR_GROUP_SEP.strip(), "/").replace(OR_GROUP_JOIN, " with ").strip()


def render_wire(header: str, alternatives: Sequence[str]) -> str:
    """Build the [OR-GROUP] item and assert it reads back unchanged.

    :param header: the group header (the gold rule name).
    :param alternatives: rendered alternative texts.
    :returns: the wire-format item.
    :raises AssertionError: when the item does not round-trip.
    """
    wire = OR_GROUP_PREFIX + header.strip() + OR_GROUP_JOIN + OR_GROUP_SEP.join(alternatives)
    parsed = or_group_alternatives(wire)
    assert parsed == list(alternatives), (
        f"OR-GROUP wire format does not round-trip for {header!r}: "
        f"{parsed!r} != {list(alternatives)!r}"
    )
    return wire


# --------------------------------------------------------------------------- #
# gold structure
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GoldGroup:
    """One disjunctive gold group, rendered to the OR-GROUP wire format."""

    trial: str
    group_key: str
    header: str
    node_type: str
    node_count: int | None
    rule_index: int
    polarity: str
    alternatives: tuple[str, ...]
    # codeset id -> the alternative text it rendered to, for DIRECT leaves only.
    alternative_by_codeset: tuple[tuple[int, str], ...]
    wire: str

    def alternative_for(self, codeset_id: int) -> str | None:
        """:param codeset_id: a gold concept set. :returns: its alternative text, or None."""
        return dict(self.alternative_by_codeset).get(codeset_id)


@dataclass(frozen=True)
class Placement:
    """Where gold puts one concept set, and therefore what the label is."""

    kind: str
    rule_index: int
    rule_name: str
    node_type: str
    node_count: int | None
    polarity: str
    path: str
    group_key: str | None = None

    @property
    def label(self) -> str | None:
        """:returns: the label this placement implies, or None when it decides nothing."""
        if self.kind == "disjunctive_group_member":
            return RESTATEMENT
        if self.kind == "standalone_all_rule":
            return DISTINCT
        return None


# Placement kinds that decide nothing, with the reason a reader needs.
UNDECIDED_PLACEMENTS = {
    "at_least_n_member": (
        "gold places it inside an AT_LEAST/N group with N >= 2; satisfying the group "
        "does not entail this member, so it is neither a restatement nor an AND-ed rule"
    ),
    "composite_alternative_member": (
        "gold places it inside a conjunctive sub-group used as ONE alternative; the "
        "group offers the conjunction, not this member alone"
    ),
    "mixed_rule_member": (
        "gold places it in a rule that also holds a disjunctive group, under conjunctive "
        "ancestors; the rule is neither a clean group nor a standalone AND-ed criterion"
    ),
    "correlated_criteria": (
        "gold uses it only as a CorrelatedCriteria qualifier of another criterion, "
        "not as a criterion of its own"
    ),
}


def collect_gold_groups(gold: dict, trial: str) -> tuple[list[GoldGroup], dict[str, int]]:
    """Every disjunctive gold group, rendered once at the level that decides.

    A parent that merely re-wraps its child is not emitted: the child already
    covers the decision, and emitting both counts the same criteria two or three
    times. Detected two ways -- a parent rendering to a single alternative, and a
    parent whose rendered alternative tuple equals a descendant's.

    :param gold: a parsed TROY CIRCE cohort definition.
    :param trial: trial key, used in the group key.
    :returns: (groups, census of what was skipped and why).
    """
    names = {c["id"]: c.get("name") for c in gold.get("ConceptSets") or []}
    groups: list[GoldGroup] = []
    census = {"singleton_or_empty": 0, "rewrap_of_child": 0, "at_least_n": 0, "at_most": 0}
    seen_alternatives: set[tuple[str, ...]] = set()

    def walk(node: dict, rule_index: int, rule_name: str, path: str) -> None:
        node_type = str(node.get("Type") or "")
        if node_type == "AT_MOST":
            census["at_most"] += 1
        if node_type == "AT_LEAST" and node.get("Count") not in (None, 1):
            census["at_least_n"] += 1
        # Depth first: a child group must be registered before its parent is
        # tested for re-wrapping it.
        for i, sub in enumerate(node.get("Groups") or []):
            walk(sub, rule_index, rule_name, f"{path}/g{i}")
        if not is_disjunctive(node):
            return
        leaf_index: dict[int, str] = {}
        alternatives = tuple(sanitise(m) for m in _render_members(node, names, leaf_index))
        if len(alternatives) < MIN_GROUP_ALTERNATIVES:
            census["singleton_or_empty"] += 1
            return
        if alternatives in seen_alternatives:
            census["rewrap_of_child"] += 1
            return
        seen_alternatives.add(alternatives)
        header = rule_name if not path else f"{rule_name} [{path.lstrip('/')}]"
        groups.append(GoldGroup(
            trial=trial,
            group_key=f"{trial}#r{rule_index}{path}",
            header=header,
            node_type=node_type,
            node_count=node.get("Count"),
            rule_index=rule_index,
            polarity=node_polarity(node),
            alternatives=alternatives,
            alternative_by_codeset=tuple(
                (cid, sanitise(text)) for cid, text in sorted(leaf_index.items())
            ),
            wire=render_wire(header, alternatives),
        ))

    for index, rule in enumerate(gold.get("InclusionRules") or []):
        walk(rule.get("expression") or {}, index, str(rule.get("name") or "").strip(), "")
    return groups, census


def gold_placements(gold: dict, trial: str,
                    emitted_group_keys: Sequence[str]) -> dict[int, list[Placement]]:
    """Where gold puts each concept set inside its InclusionRules.

    "Is this a group member?" is answered by the group keys :func:`collect_gold_groups`
    ACTUALLY EMITTED, not by re-deriving the test here. Two definitions of "this
    is a disjunction" drift, and the drift is silent: a placement could be labelled
    RESTATEMENT against a group the artifact never renders, which is a row asking
    about alternatives no arm can see.

    Only two placements decide a label; every other one is recorded with its kind
    so the row lands in ``unscorable`` with a reason instead of a guess.

    :param gold: a parsed TROY CIRCE cohort definition.
    :param trial: trial key, used in the group key.
    :param emitted_group_keys: group keys from :func:`collect_gold_groups`.
    :returns: codeset id -> placements, in traversal order.
    """
    emitted = set(emitted_group_keys)
    out: dict[int, list[Placement]] = {}

    def record(codeset_id: int, placement: Placement) -> None:
        out.setdefault(codeset_id, []).append(placement)

    def rule_has_group(node: dict, path: str, rule_index: int) -> bool:
        if f"{trial}#r{rule_index}{path}" in emitted:
            return True
        return any(rule_has_group(sub, f"{path}/g{i}", rule_index)
                   for i, sub in enumerate(node.get("Groups") or []))

    def walk(node: dict, rule_index: int, rule_name: str, path: str,
             has_group: bool, under_group: bool) -> None:
        group_key = f"{trial}#r{rule_index}{path}"
        is_group = group_key in emitted
        for criterion in node.get("CriteriaList") or []:
            polarity = occurrence_polarity(criterion)
            for payload in (criterion.get("Criteria") or {}).values():
                if not isinstance(payload, dict) or payload.get("CodesetId") is None:
                    continue
                codeset_id = int(payload["CodesetId"])
                if is_group:
                    kind = "disjunctive_group_member"
                elif under_group:
                    kind = "composite_alternative_member"
                elif has_group:
                    kind = "mixed_rule_member"
                elif entails_every_member(node):
                    kind = "standalone_all_rule"
                elif str(node.get("Type")) == "AT_LEAST":
                    kind = "at_least_n_member"
                else:
                    kind = "other_node_member"
                record(codeset_id, Placement(
                    kind=kind, rule_index=rule_index, rule_name=rule_name,
                    node_type=str(node.get("Type") or ""), node_count=node.get("Count"),
                    polarity=polarity, path=path or "/",
                    group_key=group_key if is_group else None,
                ))
                # CorrelatedCriteria are qualifiers of the criterion above, not
                # criteria of their own. Recorded so a concept set that only ever
                # appears there is refused rather than silently absent.
                for sub in _correlated_codeset_ids(payload):
                    record(sub, Placement(
                        kind="correlated_criteria", rule_index=rule_index,
                        rule_name=rule_name, node_type="CorrelatedCriteria",
                        node_count=None, polarity=polarity, path=path or "/",
                    ))
        for i, sub in enumerate(node.get("Groups") or []):
            walk(sub, rule_index, rule_name, f"{path}/g{i}", has_group, under_group or is_group)

    for index, rule in enumerate(gold.get("InclusionRules") or []):
        expression = rule.get("expression") or {}
        walk(expression, index, str(rule.get("name") or "").strip(), "",
             rule_has_group(expression, "", index), False)
    return out


def _correlated_codeset_ids(payload: dict) -> set[int]:
    """:param payload: a Circe domain payload. :returns: codeset ids under CorrelatedCriteria."""
    out: set[int] = set()
    correlated = payload.get("CorrelatedCriteria")
    if not isinstance(correlated, dict):
        return out

    def walk(node: dict) -> None:
        for criterion in node.get("CriteriaList") or []:
            for inner in (criterion.get("Criteria") or {}).values():
                if not isinstance(inner, dict):
                    continue
                if inner.get("CodesetId") is not None:
                    out.add(int(inner["CodesetId"]))
                out.update(_correlated_codeset_ids(inner))
        for sub in node.get("Groups") or []:
            walk(sub)

    walk(correlated)
    return out


# --------------------------------------------------------------------------- #
# generated candidates
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Candidate:
    """One generated criterion: a concept set plus the wording production gives it.

    The unit is the generated CONCEPT SET, because that is what links to gold by
    meaning. Its wording comes from whichever of two places actually carries the
    criterion, recorded per row in ``text_source``:

    ``generated_rule_name``
        the concept set is the sole codeset of an InclusionRule, so the rule name
        IS the flat criterion, thresholds included ("HbA1c 7-10%").
    ``generated_concept_set_name``
        the concept set is one member of a multi-codeset rule -- a collapsed
        OR-GROUP ("A + B + C") -- so the member's own name is its wording.

    Nothing is synthesised: both strings were authored by the pipeline from the
    protocol text, which is the distribution production sees.
    """

    trial: str
    text: str
    text_source: str
    rule_index: int
    codeset_id: int
    polarity: str


def _rule_codeset_ids(node: dict) -> set[int]:
    """:param node: a CIRCE group. :returns: every codeset id anywhere beneath it."""
    out: set[int] = set()
    for criterion in node.get("CriteriaList") or []:
        for payload in (criterion.get("Criteria") or {}).values():
            if isinstance(payload, dict) and payload.get("CodesetId") is not None:
                out.add(int(payload["CodesetId"]))
            if isinstance(payload, dict):
                out |= _correlated_codeset_ids(payload)
    for sub in node.get("Groups") or []:
        out |= _rule_codeset_ids(sub)
    return out


def _leaf_polarities(node: dict, codeset_id: int) -> set[str]:
    """:param node: a CIRCE group. :param codeset_id: the set to look for.
    :returns: the polarities of every criterion beneath ``node`` naming it."""
    out: set[str] = set()
    for criterion in node.get("CriteriaList") or []:
        for payload in (criterion.get("Criteria") or {}).values():
            if isinstance(payload, dict) and payload.get("CodesetId") == codeset_id:
                out.add(occurrence_polarity(criterion))
    for sub in node.get("Groups") or []:
        out |= _leaf_polarities(sub, codeset_id)
    return out


def generated_candidates(generated: dict, trial: str) -> tuple[list[Candidate], list[dict]]:
    """Every generated concept set that an InclusionRule actually uses, with its wording.

    :param generated: a parsed generated CIRCE cohort definition.
    :param trial: trial key.
    :returns: (candidates, refusals with a reason each).
    """
    rules = list(enumerate(generated.get("InclusionRules") or []))
    candidates: list[Candidate] = []
    refused: list[dict] = []

    for concept_set in iter_concept_sets(generated):
        codeset_id = concept_set.get("id")
        if codeset_id is None:
            continue
        codeset_id = int(codeset_id)
        set_name = _clean_name(concept_set_name(concept_set))

        sole: list[tuple[int, str]] = []
        shared: list[int] = []
        polarities: set[str] = set()
        for index, rule in rules:
            expression = rule.get("expression") or {}
            ids = _rule_codeset_ids(expression)
            if codeset_id not in ids:
                continue
            polarities |= _leaf_polarities(expression, codeset_id)
            name = str(rule.get("name") or "").strip()
            if len(ids) == 1 and name:
                sole.append((index, name))
            else:
                shared.append(index)

        if not sole and not shared:
            refused.append({
                "trial": trial, "candidate": set_name, "codeset_id": codeset_id,
                "reason": ("generated concept set is used by no InclusionRule "
                           "(PrimaryCriteria only), so it is not a criterion decision"),
            })
            continue
        if len(polarities) != 1:
            refused.append({
                "trial": trial, "candidate": set_name, "codeset_id": codeset_id,
                "reason": (f"generated cohort uses this concept set with mixed polarity "
                           f"{sorted(polarities)}; the candidate has no single bucket"),
            })
            continue
        polarity = polarities.pop()

        if sole:
            for index, name in sole:
                candidates.append(Candidate(
                    trial=trial, text=name, text_source="generated_rule_name",
                    rule_index=index, codeset_id=codeset_id, polarity=polarity,
                ))
        else:
            candidates.append(Candidate(
                trial=trial, text=set_name, text_source="generated_concept_set_name",
                rule_index=shared[0], codeset_id=codeset_id, polarity=polarity,
            ))
    return candidates, refused


# --------------------------------------------------------------------------- #
# meaning-based linking
# --------------------------------------------------------------------------- #
@dataclass
class Resolved:
    """A concept set resolved to its Circe closure."""

    codeset_id: int
    name: str
    concept_ids: set[int]


@dataclass(frozen=True)
class Link:
    """One generated concept set matched to a gold concept set BY MEANING."""

    gold_codeset_id: int
    gold_name: str
    generated_name: str
    jaccard: float
    runner_up_name: str | None
    runner_up_jaccard: float
    shared: int
    gold_size: int
    generated_size: int


def resolve_all(cohort: dict, lookup: VocabularyLookup) -> dict[int, Resolved]:
    """:param cohort: a CIRCE cohort. :param lookup: vocabulary access.
    :returns: codeset id -> its resolved closure."""
    out: dict[int, Resolved] = {}
    for concept_set in iter_concept_sets(cohort):
        codeset_id = concept_set.get("id")
        if codeset_id is None:
            continue
        out[int(codeset_id)] = Resolved(
            codeset_id=int(codeset_id),
            name=concept_set_name(concept_set),
            concept_ids=resolve_concept_set(concept_set, lookup).concept_ids,
        )
    return out


def jaccard(a: set[int], b: set[int]) -> float:
    """:param a: one closure. :param b: another. :returns: |a&b| / |a|b|, 0 when both empty."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def link_by_closure(generated: Resolved, gold_sets: dict[int, Resolved]) -> tuple[Link | None, str]:
    """Match one generated concept set to gold by closure overlap alone.

    No name, no string similarity, no vocabulary heuristics -- only the resolved
    concept ids, which is what Circe actually evaluates against a patient.

    :param generated: the resolved generated concept set.
    :param gold_sets: every resolved gold concept set of the same trial.
    :returns: (link, reason). ``link`` is None when the reason explains why.
    """
    if not generated.concept_ids:
        return None, "generated concept set resolves to an empty closure"
    scored = sorted(
        ((jaccard(generated.concept_ids, g.concept_ids), g.codeset_id, g)
         for g in gold_sets.values() if g.concept_ids),
        key=lambda t: (-t[0], t[1]),
    )
    if not scored:
        return None, "trial has no gold concept set with a non-empty closure"
    best_score, _, best = scored[0]
    runner_score, _, runner = (scored[1] if len(scored) > 1 else (0.0, -1, None))
    if best_score < LINK_JACCARD:
        return None, (
            f"best gold closure Jaccard {best_score:.3f} < {LINK_JACCARD} "
            f"(closest gold set {best.name!r}); no gold counterpart by meaning"
        )
    if runner is not None and best_score - runner_score < LINK_MARGIN:
        return None, (
            f"ambiguous link: {best.name!r} at Jaccard {best_score:.3f} and "
            f"{runner.name!r} at {runner_score:.3f} are within {LINK_MARGIN}; "
            "the closure does not decide which gold criterion this restates"
        )
    return Link(
        gold_codeset_id=best.codeset_id,
        gold_name=best.name,
        generated_name=generated.name,
        jaccard=round(best_score, 4),
        runner_up_name=runner.name if runner is not None else None,
        runner_up_jaccard=round(runner_score, 4),
        shared=len(generated.concept_ids & best.concept_ids),
        gold_size=len(best.concept_ids),
        generated_size=len(generated.concept_ids),
    ), "linked"


# --------------------------------------------------------------------------- #
# rows
# --------------------------------------------------------------------------- #
def _repo_relative(path: Path) -> str:
    """:param path: a definition file. :returns: its repo-relative path when inside
    the repo, else the path as given (tests pass synthetic names)."""
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def _row_id(trial: str, candidate: str) -> str:
    """Content-derived, so ids are stable across builds AND two rules that emit
    the identical criterion text collapse into one row.

    :returns: ``"<trial>-<12 hex chars>"``.
    """
    digest = hashlib.sha1(f"{trial}\x1f{candidate}".encode("utf-8")).hexdigest()[:12]
    return f"{trial}-{digest}"


def _norm_exact(text: str) -> str:
    """Exact normalisation for the verbatim/paraphrase TAG only.

    Never used to derive a label. It answers "would the module's own
    normalised-identity gate solve this row without any semantics?", which a
    reader needs before quoting an accuracy.

    :param text: raw criterion text.
    :returns: lowercase alphanumeric tokens joined by single spaces.
    """
    return " ".join(_ALNUM.findall(str(text).lower()))


@dataclass
class TrialBundle:
    """Everything one trial contributes."""

    trial: str
    gold_file: str
    generated_file: str
    groups: list[GoldGroup]
    group_census: dict[str, int]
    candidates: list[Candidate]
    refused_candidates: list[dict]
    gold_sets: dict[int, Resolved] = field(default_factory=dict)
    generated_sets: dict[int, Resolved] = field(default_factory=dict)
    placements: dict[int, list[Placement]] = field(default_factory=dict)


def load_trials(gold_root: Path, generated_root: Path,
                trials: Sequence[str] | None = None) -> list[tuple[str, Path, Path, dict, dict]]:
    """:returns: (trial, gold path, generated path, gold doc, generated doc) per trial."""
    out = []
    for trial in (trials or sorted(TRIALS)):
        gold_rel, gen_name = TRIALS[trial]
        gold_path = gold_root / gold_rel
        gen_path = generated_root / gen_name
        for path, label in ((gold_path, "gold"), (gen_path, "generated")):
            if not path.exists():
                raise SystemExit(f"missing {label} definition for {trial}: {path}")
        out.append((trial, gold_path, gen_path,
                    json.loads(gold_path.read_text()), json.loads(gen_path.read_text())))
    return out


def build(loaded: Sequence[tuple[str, Path, Path, dict, dict]],
          lookup: VocabularyLookup) -> dict:
    """Build the whole artifact.

    :param loaded: output of :func:`load_trials`.
    :param lookup: vocabulary access for closure resolution. Required: the link
        is the closure, so there is no DB-free mode that produces the same table.
    :returns: the artifact dict, ready to serialise.
    """
    bundles: list[TrialBundle] = []
    rows: list[dict] = []
    unscorable: list[dict] = []

    def unscored(trial: str, candidate: str, reason: str, **extra) -> None:
        unscorable.append({
            "id": _row_id(trial, candidate), "trial": trial,
            "candidate": candidate, "reason": reason, **extra,
        })

    for trial, gold_path, gen_path, gold, generated in loaded:
        groups, census = collect_gold_groups(gold, trial)
        candidates, refused = generated_candidates(generated, trial)
        bundle = TrialBundle(
            trial=trial,
            gold_file=_repo_relative(gold_path),
            generated_file=_repo_relative(gen_path),
            groups=groups, group_census=census,
            candidates=candidates, refused_candidates=refused,
            gold_sets=resolve_all(gold, lookup),
            generated_sets=resolve_all(generated, lookup),
            placements=gold_placements(gold, trial, [g.group_key for g in groups]),
        )
        bundles.append(bundle)

        for entry in refused:
            unscored(trial, entry["candidate"], entry["reason"],
                     codeset_id=entry.get("codeset_id"))

        for candidate in bundle.candidates:
            resolved = bundle.generated_sets.get(candidate.codeset_id)
            if resolved is None:
                unscored(trial, candidate.text,
                         f"generated rule names codeset {candidate.codeset_id}, "
                         "which the cohort does not define")
                continue

            link, reason = link_by_closure(resolved, bundle.gold_sets)
            link_facts = {
                "candidate_bucket": candidate.polarity,
                "generated_concept_set": resolved.name,
                "generated_closure_size": len(resolved.concept_ids),
            }
            if link is None:
                unscored(trial, candidate.text, reason, **link_facts)
                continue

            placements = bundle.placements.get(link.gold_codeset_id) or []
            link_facts |= {
                "gold_concept_set": link.gold_name,
                "link_jaccard": link.jaccard,
                "runner_up_gold_concept_set": link.runner_up_name,
                "runner_up_jaccard": link.runner_up_jaccard,
            }
            if not placements:
                unscored(trial, candidate.text,
                         f"linked gold concept set {link.gold_name!r} appears in no "
                         "InclusionRule (PrimaryCriteria or end-strategy only)", **link_facts)
                continue

            # Polarity gate, before any label. An exclusion criterion linking to
            # an inclusion alternative is the failure that produced
            # "Congestive heart failure of NYHA class III or IV" ->
            # "No congestive heart failure ..." in the first attempt.
            same_polarity = [p for p in placements if p.polarity == candidate.polarity]
            if not same_polarity:
                unscored(trial, candidate.text, (
                    f"polarity crossing refused: candidate is an {candidate.polarity} criterion, "
                    f"gold uses {link.gold_name!r} only as "
                    f"{'/'.join(sorted({p.polarity for p in placements}))}"
                ), gold_placement_polarities=sorted({p.polarity for p in placements}), **link_facts)
                continue

            labels = {p.label for p in same_polarity if p.label is not None}
            if not labels:
                kinds = sorted({p.kind for p in same_polarity})
                unscored(trial, candidate.text, "; ".join(
                    UNDECIDED_PLACEMENTS.get(k, f"gold placement {k!r} decides no label")
                    for k in kinds
                ), gold_placement_kinds=kinds, **link_facts)
                continue
            if len(labels) > 1:
                unscored(trial, candidate.text, (
                    "gold places the linked concept set both inside a disjunctive group and "
                    "as a standalone AND-ed rule; the tree does not decide the question"
                ), gold_placement_kinds=sorted({p.kind for p in same_polarity}), **link_facts)
                continue

            label = labels.pop()
            placement = next(p for p in same_polarity if p.label == label)

            # Context is every disjunctive group the trial's gold defines, which
            # is what `restates_or_group_alternative` pools out of `items`. The
            # groups' polarity is recorded, NOT used to filter: production dedups
            # the inclusion and exclusion lists separately, so a row whose
            # candidate bucket differs from the groups' is EASIER than production
            # and is counted apart in the summary. Filtering it out instead would
            # delete every exclusion negative, including the CAROLINA
            # "Type 1 diabetes mellitus" vs "Type 2 diabetes mellitus" pair the
            # first attempt got backwards.
            context = list(bundle.groups)
            if not context:
                unscored(trial, candidate.text,
                         "gold defines no disjunctive group for this trial, so there is "
                         "nothing for the candidate to restate", **link_facts)
                continue

            alternatives: list[str] = []
            for group in context:
                alternatives.extend(group.alternatives)
            group_polarities = sorted({g.polarity for g in context})
            polarity_relation = ("same_bucket" if group_polarities == [candidate.polarity]
                                 else "cross_bucket")

            restated = None
            if label == RESTATEMENT:
                owner = next((g for g in context if g.group_key == placement.group_key), None)
                # Hard gate: the placement classifier keys off the emitted group
                # keys, so a miss here means the two have drifted apart and a row
                # would be asking about alternatives the artifact never renders.
                assert owner is not None, (
                    f"{trial}: placement names group {placement.group_key!r}, which "
                    "collect_gold_groups did not emit"
                )
                restated = owner.alternative_for(link.gold_codeset_id)

            rows.append({
                "id": _row_id(trial, candidate.text),
                "trial": trial,
                "gold_file": bundle.gold_file,
                "generated_file": bundle.generated_file,
                "candidate": candidate.text,
                "candidate_source": candidate.text_source,
                "candidate_bucket": candidate.polarity,
                "candidate_concept_set": resolved.name,
                "label": label,
                "label_reason": _label_reason(label, placement, link),
                "link": {
                    "method": "resolved concept-set closure Jaccard (no string similarity)",
                    "gold_concept_set": link.gold_name,
                    "gold_codeset_id": link.gold_codeset_id,
                    "generated_concept_set": link.generated_name,
                    "generated_codeset_id": resolved.codeset_id,
                    "jaccard": link.jaccard,
                    "runner_up_gold_concept_set": link.runner_up_name,
                    "runner_up_jaccard": link.runner_up_jaccard,
                    "shared_concepts": link.shared,
                    "gold_closure_size": link.gold_size,
                    "generated_closure_size": link.generated_size,
                },
                "gold_placement": {
                    "kind": placement.kind,
                    "rule_index": placement.rule_index,
                    "rule_name": placement.rule_name,
                    "node_type": placement.node_type,
                    "node_count": placement.node_count,
                    "polarity": placement.polarity,
                    "path": placement.path,
                    "group_key": placement.group_key,
                },
                "or_group_items": [g.wire for g in context],
                "or_group_keys": [g.group_key for g in context],
                "or_group_polarities": group_polarities,
                "polarity_relation": polarity_relation,
                "alternatives": alternatives,
                "restated_alternative": restated,
                "difficulty": (
                    "verbatim"
                    if any(_norm_exact(a) == _norm_exact(candidate.text) for a in alternatives)
                    else "paraphrase"
                ),
            })

    rows, collisions = _collapse(rows)
    for entry in collisions:
        unscorable.append(entry)
    unscorable = _dedupe_sorted(unscorable)
    scored_ids = {r["id"] for r in rows}
    unscorable = [u for u in unscorable if u["id"] not in scored_ids]

    return {
        "schema_version": SCHEMA_VERSION,
        "question": (
            "Given the [OR-GROUP] items already in a trial's criteria list, does the "
            "candidate criterion restate an alternative one of them already offers?"
        ),
        "scale_warning": (
            "THIS IS A CASE AUDIT, NOT A BENCHMARK. Every number below is computed on "
            f"n = {len(rows)} rows. Quote n with every accuracy, and read the "
            "trivial_baselines block before quoting any arm's score."
        ),
        "wire_format": {
            "prefix": OR_GROUP_PREFIX,
            "join": OR_GROUP_JOIN,
            "sep": OR_GROUP_SEP,
            "source": "src/agents/agent1/criteria_dedup.py",
        },
        "label_definitions": {
            RESTATEMENT: (
                "gold places the linked concept set inside a disjunctive group (ANY, or "
                "AT_LEAST with Count in (None, 1)); deleting the candidate is CORRECT"
            ),
            DISTINCT: (
                "gold places the linked concept set in a standalone ALL rule; gold AND-s it "
                "separately, so deleting the candidate WIDENS the cohort silently"
            ),
        },
        "linking": {
            "method": "resolved concept-set closure Jaccard via src/services/conceptset_closure.py",
            "threshold": LINK_JACCARD,
            "ambiguity_margin": LINK_MARGIN,
            "string_similarity_used": False,
            "note": (
                "Gold supplies no paraphrase pairs on its own: a criterion never appears both "
                "inside a disjunctive group and as a standalone single-criterion rule (measured: "
                "0 pairs across all six trials). The second wording is the generated CIRCE's, "
                "linked to gold by meaning. Candidate text is the generated rule name when the "
                "rule owns exactly one concept set, else that concept set's own name; see "
                "summary.by_candidate_text_source. Both were authored by the pipeline from the "
                "protocol, which is the distribution production actually sees."
            ),
        },
        "provenance": {
            "llm_calls": 0,
            "note": (
                "The builder reads CIRCE JSON and the OMOP vocabulary only. "
                "pubmed_fetcher._llm_parse_criteria is stubbed to [] for the whole build and "
                "the stub records any call, so no paid provider can be reached. No model is "
                "resolved here; resolve_model() belongs on the judge's result rows, not on the "
                "answer key."
            ),
        },
        "summary": summarise(bundles, rows, unscorable),
        "rows": rows,
        "unscorable": unscorable,
    }


def _label_reason(label: str, placement: Placement, link: Link) -> str:
    """:returns: one sentence naming the gold structure that produced the label."""
    if label == RESTATEMENT:
        return (
            f"the candidate's concept set matches gold {link.gold_name!r} at closure Jaccard "
            f"{link.jaccard:.3f}, and gold places that set inside {placement.node_type}"
            f"{'' if placement.node_count is None else f'/{placement.node_count}'} group "
            f"{placement.group_key!r} of rule #{placement.rule_index} "
            f"({placement.rule_name!r}); the group already offers it"
        )
    return (
        f"the candidate's concept set matches gold {link.gold_name!r} at closure Jaccard "
        f"{link.jaccard:.3f}, and gold keeps that set in standalone ALL rule "
        f"#{placement.rule_index} ({placement.rule_name!r}), AND-ed on its own; "
        "deleting the candidate widens the cohort"
    )


def _collapse(rows: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse identical (trial, candidate) rows; refuse the ones that disagree.

    Two generated rules can emit the identical criterion text (ARISTOTLE defines
    "Atrial fibrillation/flutter" twice). One decision, one row. If two such rules
    produce DIFFERENT labels the tree contradicts itself and neither row is kept.

    :param rows: candidate rows.
    :returns: (kept rows sorted by id, conflict entries for ``unscorable``).
    """
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["id"], []).append(row)
    kept: list[dict] = []
    conflicts: list[dict] = []
    for row_id, group in sorted(grouped.items()):
        labels = {r["label"] for r in group}
        if len(labels) > 1:
            conflicts.append({
                "id": row_id, "trial": group[0]["trial"], "candidate": group[0]["candidate"],
                "reason": (
                    "two generated rules emit the identical criterion text but link to gold "
                    f"placements with different labels ({sorted(labels)}); refusing to pick"
                ),
            })
            continue
        kept.append(sorted(group, key=lambda r: json.dumps(r, sort_keys=True))[0])
    return kept, conflicts


def _dedupe_sorted(records: Iterable[dict]) -> list[dict]:
    """:param records: unscorable entries. :returns: unique by id, sorted by id."""
    seen: dict[str, dict] = {}
    for record in records:
        seen.setdefault(record["id"], record)
    return sorted(seen.values(), key=lambda r: r["id"])


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
def _bucket_only_accuracy(rows: Sequence[dict]) -> float:
    """:param rows: labelled rows. :returns: accuracy of "exclusion => distinct"."""
    if not rows:
        return 0.0
    hits = sum(
        1 for r in rows
        if (DISTINCT if r["candidate_bucket"] == EXCLUSION else RESTATEMENT) == r["label"]
    )
    return hits / len(rows)


def summarise(bundles: Sequence[TrialBundle], rows: Sequence[dict],
              unscorable: Sequence[dict]) -> dict:
    """Counts a reader needs BEFORE trusting any number computed on this table."""
    labels = {RESTATEMENT: 0, DISTINCT: 0}
    difficulty: dict[str, dict[str, int]] = {}
    buckets: dict[str, dict[str, int]] = {}
    relation: dict[str, dict[str, int]] = {}
    text_sources: dict[str, dict[str, int]] = {}
    for row in rows:
        labels[row["label"]] += 1
        difficulty.setdefault(row["difficulty"], {RESTATEMENT: 0, DISTINCT: 0})[row["label"]] += 1
        buckets.setdefault(row["candidate_bucket"], {RESTATEMENT: 0, DISTINCT: 0})[row["label"]] += 1
        relation.setdefault(row["polarity_relation"], {RESTATEMENT: 0, DISTINCT: 0})[row["label"]] += 1
        text_sources.setdefault(row["candidate_source"],
                                {RESTATEMENT: 0, DISTINCT: 0})[row["label"]] += 1

    per_trial = {}
    for bundle in bundles:
        trial_rows = [r for r in rows if r["trial"] == bundle.trial]
        per_trial[bundle.trial] = {
            "gold_file": bundle.gold_file,
            "generated_file": bundle.generated_file,
            "gold_concept_sets": len(bundle.gold_sets),
            "generated_concept_sets": len(bundle.generated_sets),
            "disjunctive_groups": len(bundle.groups),
            "group_alternatives": sum(len(g.alternatives) for g in bundle.groups),
            "group_polarities": sorted({g.polarity for g in bundle.groups}),
            "groups_skipped": bundle.group_census,
            "flat_generated_criteria": len(bundle.candidates),
            "rows": len(trial_rows),
            RESTATEMENT: sum(1 for r in trial_rows if r["label"] == RESTATEMENT),
            DISTINCT: sum(1 for r in trial_rows if r["label"] == DISTINCT),
            "unscorable": sum(1 for u in unscorable if u["trial"] == bundle.trial),
        }

    reasons: dict[str, int] = {}
    for entry in unscorable:
        head = entry["reason"].split(";")[0].split("(")[0].strip()
        head = re.sub(r"\d+(\.\d+)?", "N", head)
        reasons[head] = reasons.get(head, 0) + 1

    n = len(rows)
    unique_candidates = len({(r["trial"], r["candidate"]) for r in rows})
    floor = max(labels.values()) / n if n else 0.0
    return {
        "n_rows": n,
        "n_unique_trial_candidate": unique_candidates,
        "n_unscorable": len(unscorable),
        "label_balance": labels,
        "by_difficulty": difficulty,
        "by_candidate_bucket": buckets,
        "by_candidate_text_source": text_sources,
        "by_polarity_relation": {
            "note": (
                "cross_bucket rows offer the candidate groups from the other bucket. "
                "Production dedups inclusion and exclusion separately, so those rows are "
                "EASIER than production; they still test the polarity direction, which is "
                "where the first attempt inverted CAROLINA's Type 1 vs Type 2 diabetes."
            ),
            **relation,
        },
        "trivial_baselines": {
            "always_distinct": {
                "verdict": DISTINCT,
                "accuracy": round(labels[DISTINCT] / n, 4) if n else 0.0,
                "n": n,
                "note": (
                    "An arm that answers 'distinct' for every row scores this. Any arm's "
                    "accuracy must be reported next to it or the number is meaningless."
                ),
            },
            "always_restatement": {
                "verdict": RESTATEMENT,
                "accuracy": round(labels[RESTATEMENT] / n, 4) if n else 0.0,
                "n": n,
            },
            "majority_class": round(floor, 4),
            "candidate_bucket_only": {
                "rule": "answer 'distinct' iff the candidate is an EXCLUSION criterion",
                "accuracy": round(_bucket_only_accuracy(rows), 4) if n else 0.0,
                "n": n,
                "note": (
                    "A CONFOUND, reported so nobody mistakes this table for a benchmark. "
                    "It is a property of gold, not of the arms: every gold disjunctive group "
                    "is inclusion-polarity, and gold keeps its exclusion criteria as standalone "
                    "AND-ed rules, so the label is a function of the bucket. The bucket is NOT "
                    "part of an arm's input -- both arms see only the candidate text and the "
                    "alternatives, and texts like 'Aspirin' or 'pioglitazone' carry no negation "
                    "-- so an arm cannot read it off. It does mean the negatives are dominated "
                    "by exclusion criteria and this table cannot certify inclusion-side "
                    "over-deletion at all."
                ),
            },
        },
        "usable_slices": {
            # Says "restatement" when gold AND-s the criterion separately: the
            # criterion is deleted and the cohort silently WIDENS.
            "over_deletion": {
                "filter": f"label == {DISTINCT!r}",
                "rows": labels[DISTINCT],
                "measures": "false positives -- deleting a criterion gold AND-s separately",
            },
            # Says "distinct" when the group already offers it: the alternative is
            # re-added top-level, Circe ANDs it, the cohort collapses.
            "under_deletion": {
                "filter": f"label == {RESTATEMENT!r}",
                "rows": labels[RESTATEMENT],
                "measures": "false negatives -- failing to see a restatement worded differently",
            },
            "hard_negatives": {
                "filter": f"label == {DISTINCT!r} and difficulty == 'paraphrase'",
                "rows": difficulty.get("paraphrase", {}).get(DISTINCT, 0),
                "measures": (
                    "criteria that link to a gold criterion BY MEANING yet gold placed them as "
                    "standalone AND-ed rules -- the negatives a lexical arm cannot separate"
                ),
            },
        },
        "unscorable_reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_trial": per_trial,
        "gold_node_type_census": {
            "note": (
                "AT_MOST is not counted as disjunctive and gold contains none "
                "(ALL 153 / AT_LEAST 27 / ANY 18 across all gold files)."
            ),
            "at_most_nodes_seen": sum(b.group_census["at_most"] for b in bundles),
            "at_least_n_nodes_excluded": sum(b.group_census["at_least_n"] for b in bundles),
            "rewrap_groups_skipped": sum(b.group_census["rewrap_of_child"] for b in bundles),
            "singleton_groups_skipped": sum(b.group_census["singleton_or_empty"] for b in bundles),
        },
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_report(artifact: dict) -> None:
    """Print the inventory and the honesty warnings to stdout."""
    summary = artifact["summary"]
    header = (f"{'trial':<11}{'grp':>4}{'alt':>5}{'flat':>6}{'rows':>6}"
              f"{'rest':>6}{'dist':>6}{'unsc':>6}")
    print(header)
    print("-" * len(header))
    for trial, s in sorted(summary["by_trial"].items()):
        print(f"{trial:<11}{s['disjunctive_groups']:>4}{s['group_alternatives']:>5}"
              f"{s['flat_generated_criteria']:>6}{s['rows']:>6}"
              f"{s[RESTATEMENT]:>6}{s[DISTINCT]:>6}{s['unscorable']:>6}")
    print(f"{'TOTAL':<11}{'':>4}{'':>5}{'':>6}{summary['n_rows']:>6}"
          f"{summary['label_balance'][RESTATEMENT]:>6}"
          f"{summary['label_balance'][DISTINCT]:>6}{summary['n_unscorable']:>6}")

    n = summary["n_rows"]
    print(f"\nn = {n} scorable rows over {summary['n_unique_trial_candidate']} unique "
          f"(trial, candidate) pairs; {summary['n_unscorable']} unscorable.")
    print(f"label balance: {summary['label_balance']}")
    print(f"by difficulty: {summary['by_difficulty']}")
    print(f"by candidate bucket: {summary['by_candidate_bucket']}")
    floor = summary["trivial_baselines"]["always_distinct"]
    bucket = summary["trivial_baselines"]["candidate_bucket_only"]
    print(f"\nTRIVIAL FLOOR -- always answer 'distinct': {floor['accuracy']:.1%} on n={n}. "
          "Any arm scoring at or below this has measured nothing.")
    print(f"CONFOUND -- {bucket['rule']}: {bucket['accuracy']:.1%} on n={n}. "
          "The bucket is not in an arm's input, but the negatives are almost all exclusions, "
          "so this table cannot certify inclusion-side over-deletion.")
    print("\nCASE AUDIT, NOT A BENCHMARK. A two-class table of a few dozen rows cannot "
          "separate two arms by a pooled accuracy; read the per-row verdicts.")
    print("\nunscorable reasons:")
    for reason, count in summary["unscorable_reasons"].items():
        print(f"  {count:>4}  {reason}")
    census = summary["gold_node_type_census"]
    print(f"\ngold structure: AT_MOST nodes seen {census['at_most_nodes_seen']}, "
          f"AT_LEAST/N (N>=2) groups excluded {census['at_least_n_nodes_excluded']}, "
          f"re-wrap parents skipped {census['rewrap_groups_skipped']}, "
          f"singleton groups skipped {census['singleton_groups_skipped']}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """:returns: parsed CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="vocabulary DSN (closure resolution)")
    parser.add_argument("--vocab-schema", default=DEFAULT_VOCAB_SCHEMA)
    parser.add_argument("--gold-root", default=str(GOLD_ROOT))
    parser.add_argument("--generated-root", default=str(GENERATED_ROOT))
    parser.add_argument("--trials", nargs="*", default=None, help="subset; default all six")
    parser.add_argument("--out", default=str(OUTPUT_PATH))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. :returns: process exit code."""
    args = parse_args(argv)
    unknown = [t for t in (args.trials or []) if t not in TRIALS]
    if unknown:
        raise SystemExit(f"unknown trial(s): {unknown}; known: {sorted(TRIALS)}")

    loaded = load_trials(Path(args.gold_root), Path(args.generated_root), args.trials)

    items = []
    for _, _, _, gold, generated in loaded:
        items.extend(items_of_cohort(gold))
        items.extend(items_of_cohort(generated))
    try:
        vocab = PostgresVocabulary(args.dsn, args.vocab_schema)
        lookup = vocab.prefetch(items)
    except Exception as exc:  # noqa: BLE001 -- must fail loudly, never fall back
        raise SystemExit(
            f"closure linking needs the vocabulary at dsn={args.dsn!r} "
            f"schema={args.vocab_schema!r}, but it is unreachable: {exc}\n"
            "There is no string-similarity fallback: that is the defect this rewrite removes."
        ) from exc

    with no_paid_llm() as calls:
        artifact = build(loaded, lookup)
    vocab.close()
    assert not calls, f"an LLM entry point was reached during the build: {calls}"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    _print_report(artifact)
    print(f"\nwrote {out} ({os.path.getsize(out)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
