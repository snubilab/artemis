"""Export-time repair: narrow an over-broad absence concept set to the concept its
own name states.

THE DEFECT, measured in the 2026-09-18 cold re-extraction
(``output/site_gap/2026-09-18_verify/DELIVERY/``)::

    codeset 14 'Type 1 diabetes mellitus'
        [4130526 'Disorder of glucose metabolism'], includeDescendants, no isExcluded
    rule #3    'Type 1 diabetes mellitus'
        ConditionOccurrence codeset 14 at Occurrence {Type: 0, Count: 0}

4130526's valid descendant closure is 180 concepts and CONTAINS
``201826 Type 2 diabetes mellitus`` -- the concept the entry event admits patients on.
So the absence rule removes every patient the entry admits and the cohort is empty on
any CDM. Four files carry it: CARMELINA both arms (codeset 14) and CAROLINA both arms
(codeset 34). It is the one remaining FAIL from
``scripts/verify_entry_exclusion_conflict.py`` on that run.

It is a REGRESSION. The same sets in ``deliveries/2026-09-12/`` hold
``201254 Type 1 diabetes mellitus``, whose closure is 25 concepts and excludes 201826.
The set NAME was right in both runs; only the member it resolved to changed.

WHY THIS REPAIRS AT EXPORT TIME, like its three siblings
(:mod:`~src.services.entry_exclusion_repair`,
:mod:`~src.services.range_disjunction_repair`,
:mod:`~src.services.presence_unit_repair`): the payload already carries the answer --
the concept set's own name -- and the fix is a vocabulary lookup plus one substitution.
Re-extracting to reach it would re-roll roughly a third of every other criterion (see
``feedback: prompt edits re-roll a third of criteria``) and spend an LLM pass on what is
a pure name resolution. Whether the upstream mapper should also be fixed is a separate
question this module does not answer; see § UPSTREAM below.

WHERE IT RUNS. FIRST at the export chokepoint, before
:meth:`~src.services.tte_service.TTEService._repair_entry_excluded_by_own_rule`. The two
are the only repairs that touch an absence concept set, and they touch it in opposite
directions: this one REPLACES the over-broad member, that one APPENDS ``isExcluded``
items mirroring the entry set. Run in the other order, the mirror would leave the wrong
concept in place -- still matching the other 179 glucose-metabolism disorders -- and
would then make this repair decline, because an ``isExcluded`` item is one of its
declines (a single-member substitution cannot carry a subtraction someone else added).
Narrowing first is also strictly cheaper for the second repair: once codeset 14 resolves
to 201254 the entry closure is no longer covered, so there is nothing left for the
mirror to fix. Order against the range-disjunction and presence-unit repairs does not
matter: those read only ``Measurement`` criteria, and a Measurement criterion is a
decline here (see condition 4).

WHAT IT WILL NOT DO. A name match alone is nowhere near sufficient -- the drug repair in
:meth:`~src.services.tte_service.TTEService._repair_stale_drug_concept_sets` learned that
from two measured defects, and its DOMAIN and CLOSURE gates are the direct ancestors of
conditions 4 and 3 here. Five conditions must hold together:

1. the set holds EXACTLY ONE item, that item is not ``isExcluded``, and it carries
   ``includeDescendants``. A multi-member set is curated -- the members are a decision,
   not a single resolution to correct -- and an ``isExcluded`` item cannot survive a
   substitution that replaces the one thing it was subtracting from. The count is taken
   over EVERY item rather than the included ones, so the ``isExcluded`` test is what
   declines a set whose single item is the exclusion;
2. a STANDARD, VALID concept exists whose name equals the set name exactly
   (case-insensitively, whitespace-normalised) and is UNIQUE. Two matches means the name
   does not resolve, and guessing between them is what this repair exists to avoid. A
   non-standard or retired match is no match: it cannot appear in a CDM data field;
3. the existing member is a PROPER ANCESTOR of that concept, through
   ``concept_ancestor``. This is the direction that makes the repair a NARROWING to what
   the name says. Reversed -- the member a descendant of the named concept -- the rewrite
   would WIDEN the set, which is a different and unrequested change; unrelated means the
   set is about something else and the name is the unreliable side. ``'Disorder of
   glucose metabolism'`` holding 201254 is the reversed shape and declines;
4. every criterion referencing the set is an ABSENCE criterion
   (``Occurrence {Type: 0, Count: 0}``) whose CDM table can hold the replacement's
   domain, read from :data:`~src.utils.circe_lint.CRITERIA_TYPE_DOMAINS` -- the same
   table the delivery gate reads, so the generator cannot emit a shape that gate
   rejects. A set nothing references declines: the payload does not then say which table
   it is for. An unmodelled criteria type declines for the same reason;
5. the replacement's domain equals the existing member's. Not subsumed by condition 4,
   because a criteria type may admit TWO domains. ``'Stroke'`` is the easy case -- the
   name resolves to ``36210384`` (Meas Value, LOINC) while the set holds ``381316
   Cerebrovascular accident`` (Condition), and condition 4 catches it because
   ``ConditionOccurrence`` admits only Condition. The case only condition 5 catches is a
   ``Death`` criterion, which admits Condition OR Observation: EMPA-REG's ``'Basal cell
   carcinoma'`` holds ``4112752 'Basal cell carcinoma of skin'`` (Condition) while the
   name resolves to ``4028320`` (Observation, a morphologic abnormality). Both would pass
   condition 4 there; the member's own domain is the independent statement that the name
   and the set are about the same kind of thing.

WHY CONDITION 4 REQUIRES ABSENCE, and what that declines. For an absence criterion an
over-broad set is wrong in one direction only: the rule removes a superset of what the
protocol excluded, so narrowing to the named concept can only move the cohort toward the
protocol. For a PRESENCE criterion the same shape is a judgement the file cannot settle.
The measured instance is EMPA-REG codeset 9 ``'Dyslipidemia'``, in BOTH the 2026-09-12
delivery and the 2026-09-18 re-extraction::

    codeset 9 'Dyslipidemia'
        [4170226 'Disorder of lipoprotein AND/OR lipid metabolism']  280 valid desc.
    name resolves to 4159131 'Dyslipidemia'                            6 valid desc.
                     (4170226 is its direct parent, 1 level)
    rule #5   'Hypertension + Coronary Artery Disease + Stroke + Heart Failure +
               Dyslipidemia'  --  Type ANY, this branch at Occurrence {Type: 2, Count: 1}

Conditions 1, 2, 3 and 5 all hold there. Narrowing it would cut a cardiovascular
risk-factor branch from 280 concepts to 6, dropping hyperlipidemia and
hypercholesterolemia -- which a protocol listing "dyslipidemia" as a risk factor
plainly means to include. Unlike the T1DM case there is no defect visible in the file:
4170226's closure is disjoint from the entry closure, so no rule becomes unsatisfiable
either way. It declines and says so at WARNING level, so the set stays visible rather
than being silently either narrowed or forgotten.

UPSTREAM. This is a mapper defect as well as an export defect, and the repair does not
hide that -- every application logs at WARNING with both concept ids. What would
distinguish "mapper is fine, one bad roll-up" from "mapper systematically prefers the
ancestor" is a count over the whole store of sets whose name resolves to a proper
descendant of their single member: 4 of 84 single-member sets in the 2026-09-18 corpus
(plus Dyslipidemia, which this declines), and the same sets were right on 2026-09-12,
which is the shape of a regression in one resolution path rather than a systematic
preference. Fixing it upstream costs a full six-study re-extraction (~132 min measured)
and re-rolls a third of every other criterion; this repair costs a vocabulary lookup and
leaves that decision open.

No database import here. The vocabulary arrives as a
:class:`~src.services.conceptset_closure.VocabularyLookup` and the name/domain lookup as
a :class:`ConceptCatalog`, which is what lets the tests run the real ancestor check with
no database at all.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from src.services.conceptset_closure import VocabularyLookup
from src.utils.circe_lint import (
    CRITERIA_TYPE_DOMAINS,
    _criterion_locations,
    _criterion_references,
)

#: The caption Atlas renders beside ``STANDARD_CONCEPT``. Mirrors
#: ``ConceptSetExpression._standard_concept_caption`` in
#: :mod:`src.agents.conceptset.expression_builder`, which is what wrote the item this
#: repair rewrites -- so a repaired item is indistinguishable in shape from a built one.
_STANDARD_CAPTIONS = {"S": "Standard", "C": "Classification"}


def _by_id(record: "ConceptRecord") -> int:
    """Sort key for a stable, reader-friendly order in the ambiguous-name warning."""
    return record.concept_id


def normalize_name(name: Any) -> str:
    """A concept-set name reduced to its comparison form: whitespace-collapsed, lower.

    The one definition of "the same name", used for both sides of the comparison so a
    trailing space or a double space in a model-written set name cannot decide it.
    """
    return " ".join(str(name or "").split()).lower()


# --------------------------------------------------------------------------
# the name/domain seam
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ConceptRecord:
    """The CONCEPT row fields a Circe concept-set item carries."""

    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str
    standard_concept: str | None
    concept_code: str
    invalid_reason: str | None

    @property
    def is_standard_and_valid(self) -> bool:
        return self.standard_concept == "S" and self.invalid_reason is None

    def as_circe_concept(self) -> dict[str, Any]:
        """The item's ``concept`` object, in the shape the expression builder emits."""
        return {
            "CONCEPT_ID": self.concept_id,
            "CONCEPT_NAME": self.concept_name,
            "DOMAIN_ID": self.domain_id,
            "VOCABULARY_ID": self.vocabulary_id,
            "CONCEPT_CLASS_ID": self.concept_class_id,
            "STANDARD_CONCEPT": self.standard_concept,
            "STANDARD_CONCEPT_CAPTION": _STANDARD_CAPTIONS.get(
                self.standard_concept or "", "Non-Standard"
            ),
            "CONCEPT_CODE": self.concept_code,
            "INVALID_REASON": self.invalid_reason,
            "INVALID_REASON_CAPTION": None,
        }


class ConceptCatalog(Protocol):
    """Concept identity by id and by exact name. Deliberately free of any DB import."""

    def concepts_by_id(self, concept_ids: Iterable[int]) -> dict[int, ConceptRecord]:
        """The CONCEPT rows for these ids. Absent ids are absent from the result."""

    def standard_concepts_by_name(
        self, names: Iterable[str]
    ) -> dict[str, list[ConceptRecord]]:
        """Normalised name -> every STANDARD, VALID concept carrying it.

        Keyed by :func:`normalize_name` of the name. A list rather than one record
        because "more than one" is a decline the caller must be able to see.
        """


@dataclass
class PrefetchedConcepts:
    """Pure-Python :class:`ConceptCatalog` over a bag of :class:`ConceptRecord`."""

    records: dict[int, ConceptRecord] = field(default_factory=dict)

    def concepts_by_id(self, concept_ids: Iterable[int]) -> dict[int, ConceptRecord]:
        return {cid: self.records[cid] for cid in concept_ids if cid in self.records}

    def standard_concepts_by_name(
        self, names: Iterable[str]
    ) -> dict[str, list[ConceptRecord]]:
        wanted = {normalize_name(n) for n in names}
        out: dict[str, list[ConceptRecord]] = {}
        for rec in self.records.values():
            if not rec.is_standard_and_valid:
                continue
            key = normalize_name(rec.concept_name)
            if key in wanted:
                out.setdefault(key, []).append(rec)
        return out


class PostgresConceptCatalog:
    """:class:`ConceptCatalog` over an OMOP vocabulary, two batched queries.

    ``psycopg2`` is imported inside ``__init__`` so importing this module -- and
    therefore ``python -m src.boot_check`` -- never needs a database driver, exactly as
    :class:`~src.services.conceptset_closure.PostgresVocabulary` does.
    """

    _COLUMNS = (
        "concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
        "standard_concept, concept_code, invalid_reason"
    )

    def __init__(self, dsn: str, schema: str) -> None:
        import psycopg2  # noqa: PLC0415 -- deliberately lazy; see docstring

        self.schema = schema
        self._conn = psycopg2.connect(dsn)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PostgresConceptCatalog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _rows(self, sql: str, params: tuple) -> list[ConceptRecord]:
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
            return [ConceptRecord(*row) for row in cur.fetchall()]
        finally:
            cur.close()

    def concepts_by_id(self, concept_ids: Iterable[int]) -> dict[int, ConceptRecord]:
        ids = sorted({int(c) for c in concept_ids})
        if not ids:
            return {}
        rows = self._rows(
            f"SELECT {self._COLUMNS} FROM {self.schema}.concept WHERE concept_id = ANY(%s)",
            (ids,),
        )
        return {r.concept_id: r for r in rows}

    def standard_concepts_by_name(
        self, names: Iterable[str]
    ) -> dict[str, list[ConceptRecord]]:
        wanted = sorted({n for n in (normalize_name(x) for x in names) if n})
        if not wanted:
            return {}
        # The comparison is done in SQL on the same normalisation the caller applies:
        # lower() plus a whitespace collapse, so a vocabulary name carrying a double
        # space still matches a set name that does not.
        rows = self._rows(
            f"SELECT {self._COLUMNS} FROM {self.schema}.concept "
            f"WHERE standard_concept = 'S' AND invalid_reason IS NULL "
            f"AND regexp_replace(btrim(lower(concept_name)), '\\s+', ' ', 'g') = ANY(%s)",
            (wanted,),
        )
        out: dict[str, list[ConceptRecord]] = {}
        for rec in rows:
            out.setdefault(normalize_name(rec.concept_name), []).append(rec)
        return out


# --------------------------------------------------------------------------
# the DB-free pre-gate
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OverbroadCandidate:
    """A set satisfying condition 1 and the known-criteria-type half of 4.

    ``absence_only`` carries the rest of condition 4. It is recorded rather than
    filtered here on purpose: the presence case is the one decline a reader most needs
    to see (EMPA-REG's ``'Dyslipidemia'``), and it is only worth reporting once the
    vocabulary has established that the set WOULD otherwise have been narrowed. Gating
    it in the pre-gate would make that decline silent.
    """

    concept_set: dict[str, Any]
    codeset_id: int
    set_name: str
    item: dict[str, Any]
    member_id: int
    criteria_types: frozenset[str]
    allowed_domains: frozenset[str]
    absence_only: bool


def _is_absence(entry: Mapping[str, Any]) -> bool:
    """``Occurrence {Type: 0, Count: 0}`` -- Circe's "exactly zero of these".

    A ``PrimaryCriteria`` or ``CensoringCriteria`` entry carries no ``Occurrence`` at
    all, so it reads False: an entry event is never an absence, and a set that is also
    the entry event must not be rewritten under an absence-only rule.
    """
    occurrence = entry.get("Occurrence")
    if not isinstance(occurrence, Mapping):
        return False
    return occurrence.get("Type") == 0 and occurrence.get("Count") == 0


def _single_included_item(concept_set: Mapping[str, Any]) -> dict[str, Any] | None:
    """Condition 1: the set's one included ``includeDescendants`` item, or None.

    All three checks are separate and each one declines on its own. The item count is
    taken over EVERY item, not over the included ones: a set with one included member
    and one ``isExcluded`` member is curated, and replacing the member the exclusion was
    subtracting from would silently change what that exclusion means. The
    ``isExcluded`` test is therefore not subsumed by the count -- it is what declines a
    set whose SINGLE item is the excluded one.
    """
    items = [i for i in (concept_set.get("expression") or {}).get("items") or []
             if isinstance(i, dict)]
    if len(items) != 1:
        return None
    item = items[0]
    if item.get("isExcluded"):
        return None
    if not item.get("includeDescendants"):
        return None
    concept_id = (item.get("concept") or {}).get("CONCEPT_ID")
    return item if isinstance(concept_id, int) else None


def _readers(base: Mapping[str, Any]) -> dict[Any, tuple[frozenset[str], bool]]:
    """``CodesetId`` -> (criteria types that read it, whether ALL of them are absences).

    Only codesets read exclusively by criteria that HAVE an ``Occurrence`` appear at all.
    A ``PrimaryCriteria`` or ``CensoringCriteria`` entry carries none, so an entry event's
    concept set -- the commonest single-member set in these files -- is excluded outright
    rather than being reported as a presence-read candidate. Whether the remaining
    references are all absences is the second element, which the caller reports on rather
    than filtering, so its decline can name what it would have narrowed.

    The criteria walk is :mod:`src.utils.circe_lint`'s, so this and the delivery gate
    cannot disagree about what references a set.
    """
    types: dict[Any, set[str]] = {}
    presence: set[Any] = set()
    disqualified: set[Any] = set()
    for _where, entry in _criterion_locations(base):
        occurrence = entry.get("Occurrence") if isinstance(entry, Mapping) else None
        for criteria_type, codeset_id in _criterion_references(entry):
            if not isinstance(occurrence, Mapping):
                disqualified.add(codeset_id)
                continue
            types.setdefault(codeset_id, set()).add(criteria_type)
            if not _is_absence(entry):
                presence.add(codeset_id)
    return {
        cid: (frozenset(t), cid not in presence)
        for cid, t in types.items()
        if cid not in disqualified
    }


def iter_overbroad_candidates(base: Mapping[str, Any]) -> Iterator[OverbroadCandidate]:
    """Sets this repair could fire on, judged without a vocabulary.

    Applies condition 1 and the known-criteria-type half of condition 4, so a payload
    with no single-member set that any modelled criterion reads -- which is every file in
    the 2026-06-24 and 2026-08-31 deliveries -- costs no database round trip. Conditions
    2, 3, 5, the domain half of 4 and the absence half of 4 need the vocabulary (the last
    only so that its decline can name the concept it would have narrowed to) and are
    applied by :func:`repair_overbroad_absence_sets`.
    """
    readers = _readers(base)
    for concept_set in base.get("ConceptSets") or []:
        if not isinstance(concept_set, dict) or "id" not in concept_set:
            continue
        set_name = normalize_name(concept_set.get("name"))
        if not set_name:
            continue
        item = _single_included_item(concept_set)
        if item is None:
            continue
        read = readers.get(concept_set["id"])
        if not read:
            continue
        criteria_types, absence_only = read
        allowed: set[str] | None = None
        for criteria_type in criteria_types:
            domains = CRITERIA_TYPE_DOMAINS.get(criteria_type)
            if domains is None:
                allowed = None
                break
            allowed = set(domains) if allowed is None else (allowed & set(domains))
        if not allowed:
            continue
        yield OverbroadCandidate(
            concept_set=concept_set,
            codeset_id=int(concept_set["id"]),
            set_name=str(concept_set.get("name")).strip(),
            item=item,
            member_id=int(item["concept"]["CONCEPT_ID"]),
            criteria_types=criteria_types,
            allowed_domains=frozenset(allowed),
            absence_only=absence_only,
        )


# --------------------------------------------------------------------------
# the repair
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OverbroadSetRepair:
    """One applied narrowing, for the caller to log and to record."""

    codeset_id: int
    set_name: str
    previous_concept_id: int
    previous_concept_name: str
    concept_id: int
    concept_name: str
    criteria_types: tuple[str, ...]


def repair_overbroad_absence_sets(
    base: dict[str, Any], lookup: VocabularyLookup, catalog: ConceptCatalog
) -> list[OverbroadSetRepair]:
    """Narrow each over-broad absence set to the concept its name states. Mutates ``base``.

    :param base: a Circe cohort expression (ConceptSets / PrimaryCriteria /
        InclusionRules), mutated in place.
    :param lookup: vocabulary access, used only for the ``concept_ancestor`` direction
        test in condition 3.
    :param catalog: concept identity by id and by exact name (conditions 2 and 5).
    :returns: one record per applied narrowing; empty means nothing satisfied all five
        conditions, which is the expected answer for almost every file.
    """
    candidates = list(iter_overbroad_candidates(base))
    if not candidates:
        return []

    by_name = catalog.standard_concepts_by_name(c.set_name for c in candidates)
    members = catalog.concepts_by_id(c.member_id for c in candidates)

    applied: list[OverbroadSetRepair] = []
    for candidate in candidates:
        label = f"codeset {candidate.codeset_id} {candidate.set_name!r}"
        matches = by_name.get(normalize_name(candidate.set_name)) or []

        # Condition 2.
        if len(matches) != 1:
            if len(matches) > 1:
                logging.warning(
                    "[TTE] overbroad-set repair declines %s: its name is carried by %d "
                    "standard concepts (%s), so the name does not resolve",
                    label, len(matches),
                    ", ".join(str(m.concept_id) for m in sorted(matches, key=_by_id)),
                )
            else:
                logging.info(
                    "[TTE] overbroad-set repair declines %s: no standard, valid concept "
                    "carries that name", label,
                )
            continue
        target = matches[0]

        if target.concept_id == candidate.member_id:
            continue  # already the concept its name states

        member = members.get(candidate.member_id)
        if member is None:
            logging.warning(
                "[TTE] overbroad-set repair declines %s: its member %d does not resolve "
                "in the vocabulary, so its domain cannot be compared",
                label, candidate.member_id,
            )
            continue

        # Condition 5.
        if member.domain_id != target.domain_id:
            logging.warning(
                "[TTE] overbroad-set repair declines %s: the name resolves to %d %r in "
                "domain %s while the set holds %d %r in domain %s -- the name and the "
                "set are not about the same kind of thing",
                label, target.concept_id, target.concept_name, target.domain_id,
                member.concept_id, member.concept_name, member.domain_id,
            )
            continue

        # Condition 4, domain half.
        if target.domain_id not in candidate.allowed_domains:
            logging.warning(
                "[TTE] overbroad-set repair declines %s: read by %s, which cannot hold "
                "the %s concept the repair would put there",
                label, ", ".join(sorted(candidate.criteria_types)), target.domain_id,
            )
            continue

        # Condition 3 -- the direction that makes this a narrowing.
        if target.concept_id not in lookup.descendants_of([candidate.member_id]):
            logging.warning(
                "[TTE] overbroad-set repair declines %s: %d %r is not a proper "
                "descendant of the set's member %d %r, so replacing it would not be a "
                "narrowing to what the name says",
                label, target.concept_id, target.concept_name,
                member.concept_id, member.concept_name,
            )
            continue

        # Condition 4, absence half. Applied LAST so the decline can name the concept
        # the set would have been narrowed to and the closure sizes involved -- the whole
        # point of reporting it rather than filtering it out earlier.
        if not candidate.absence_only:
            logging.warning(
                "[TTE] overbroad-set repair declines %s: it holds %d %r, a proper "
                "ancestor of the %d %r its name states, but it is read by a criterion "
                "that is not an absence (%s). Narrowing a presence criterion is a "
                "population change, not the repair of a rule that can never be "
                "satisfied, and the payload does not say which reading the protocol "
                "intended -- left as it is, deliberately",
                label, member.concept_id, member.concept_name,
                target.concept_id, target.concept_name,
                ", ".join(sorted(candidate.criteria_types)),
            )
            continue

        candidate.item["concept"] = target.as_circe_concept()
        applied.append(
            OverbroadSetRepair(
                codeset_id=candidate.codeset_id,
                set_name=candidate.set_name,
                previous_concept_id=member.concept_id,
                previous_concept_name=member.concept_name,
                concept_id=target.concept_id,
                concept_name=target.concept_name,
                criteria_types=tuple(sorted(candidate.criteria_types)),
            )
        )
        logging.warning(
            "[TTE] overbroad-set repair: %s held %d %r, a proper ancestor of the %d %r "
            "its own name states, and is read only by %s absence criteria -- the member "
            "is replaced, narrowing the set to what the name says",
            label, member.concept_id, member.concept_name,
            target.concept_id, target.concept_name,
            ", ".join(sorted(candidate.criteria_types)),
        )
    return applied
