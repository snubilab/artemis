"""The one home of the vocabulary a mapper refusal is classified by.

A criterion that does not become a rule leaves a record behind, and a consumer of that
record — the delivery gate above all — has to decide whether the loss was DELIBERATE
("the mapper looked and there is nothing to map") or a FAILURE ("something broke on the
way"). Those two need opposite treatment: the first can be permitted with its reason on
file, the second must never pass.

Prose cannot carry that decision. The reason string is written for a human and changes
whenever the message does, so classifying on it means every consumer re-implements a
fragile substring match and they drift. :class:`CriterionRefused` carries a ``code``
from a closed set instead, and the record's ``refusalCode`` is the ONLY classification
key: ``refusalCode is None`` means nothing deliberately refused, which is a failure.

The codes live here and nowhere else, for the same reason
``restated_distinctness.COLLAPSE_REASON`` does: a code retyped at a second site is a
code that will eventually be retyped wrong, and the mismatch is silent — a gate looking
for ``"no-concept-mapping"`` simply never matches ``"no_concept_mapping"`` and blocks a
delivery for a reason nobody can find.

Construction is validated rather than trusted. An empty message would reintroduce the
exact defect this module exists to close (``str(e)`` == ``""``), and an unknown code
would fail at the gate — far from the line that wrote it — instead of here.
"""

from __future__ import annotations

#: The mapper looked and the vocabulary has no counterpart. Every tier ran and matched
#: nothing: a numbered placeholder ("Risk factor 1"), a pointer into the source document
#: ("Table II criteria"), a bare "Contraindication" naming no substance.
REFUSAL_NO_CONCEPT_MAPPING = "no-concept-mapping"

#: The seed names no clinical entity at all, so no vocabulary can ever hold it and no
#: better mapper can ever find it: a numbered placeholder whose content lives elsewhere
#: in the protocol ("Risk factor 1"), a pointer into the source document ("Table II
#: criteria"), a count rather than an entity ("Preexisting Conditions Count"), a bare
#: qualifier naming no substance ("Contraindication").
#:
#: This is the ONE code a delivery gate may permit, and it exists because
#: :data:`REFUSAL_NO_CONCEPT_MAPPING` straddles the line that decides permission. That
#: line is NOT "was the refusal deliberate" — every code here is deliberate — it is "is
#: this loss IRREDUCIBLE given a correct pipeline". Both of these produce
#: ``no-concept-mapping`` today and they need opposite verdicts:
#:
#:     "Table II criteria"                  irreducible — a pointer, not an entity
#:     "Contraindication to clopidogrel"    REDUCIBLE — names a real substance, and a
#:                                          better mapper finds it
#:
#: One code, two opposite verdicts, and no reason string separates them — which is why
#: the split is made HERE, at the raise site that can see the seed, rather than by a
#: gate-side heuristic over English. A gate that guessed would silently permit the
#: second row the day its seed happened to look placeholder-shaped.
REFUSAL_UNMAPPABLE_PLACEHOLDER = "unmappable-placeholder"

#: The intent router could not parse the seed into a clinical entity — usually because
#: the seed still carries a temporal qualifier ("... within 3 years") that belongs in the
#: criterion's ``window``, not in its text. The refusal is correct; the defect is
#: upstream, in whichever text was handed to the mapper. Note where it is NOT: the four
#: CARMELINA rows that produced this code on 2026-09-09 had CORRECT windows, so
#: extraction was right and the seed was the copy that should not have repeated the
#: number. ``src.utils.criterion_seed.criterion_mapper_seed`` is where that is now
#: decided; check it before reaching for the extraction prompt.
REFUSAL_INTENT_UNPARSED = "intent-unparsed"

#: A recommendation came back but its expression holds no concepts, so there is nothing
#: to emit. Distinct from :data:`REFUSAL_NO_CONCEPT_MAPPING`: the search DID return
#: something, and it was empty.
REFUSAL_EMPTY_CONCEPT_SET = "empty-concept-set"

#: The criterion reached the mapper with no seed text at all. Upstream defect; recorded
#: rather than silently skipped so the empty criterion is visible in the artifact.
REFUSAL_EMPTY_SEED = "empty-seed"

#: A threshold written once on a criteria group's label was an ABSOLUTE bound, so
#: ``resolve_group_member_constraint`` would not hand it down and the member has no
#: constraint of its own. Emitting the member anyway builds an UNFILTERED occurrence:
#: "any glucose measurement at all" where the protocol said "> 240 mg/dL". Distinct
#: from every code above: the mapper SUCCEEDED — a concept set was found — and the
#: refusal is about the number that did not survive the group label, not about the
#: concepts. Distinct from :data:`REFUSAL_UNREADABLE_VALUE_FILTER`: there a filter
#: exists and the table cannot read it; here no filter exists to write.
REFUSAL_STRANDED_GROUP_THRESHOLD = "stranded-group-threshold"

#: The concept set the mapper returned holds only concepts from domains the criterion's
#: own CDM table cannot hold, so the emitted rule would match no row at all — and inside
#: an ABSENCE exclusion, matching nothing means the exclusion never applies to anybody.
#: Distinct from :data:`REFUSAL_NO_CONCEPT_MAPPING`: the vocabulary DID answer, and the
#: answer is from the wrong domain. Raised by
#: :func:`src.utils.circe_lint.refuse_domain_contradiction`.
REFUSAL_DOMAIN_CONTRADICTION = "domain-contradiction"

#: The criterion carries a value condition (``ValueAsNumber``, ``Unit``, ...) that its
#: own criteria type's CDM table has no column for, so Circe silently drops the
#: attribute and the rule matches every occurrence of its concept set while reading as
#: filtered. Distinct from :data:`REFUSAL_STRANDED_GROUP_THRESHOLD`: the threshold
#: reached the criterion intact; it is the TABLE that cannot read it. Raised by
#: :func:`src.utils.circe_lint.refuse_unreadable_value_filter`.
REFUSAL_UNREADABLE_VALUE_FILTER = "unreadable-value-filter"

#: The criterion reached the mapper on a seed that is NOT its own ``entity_text``,
#: because extraction left that mandatory field empty and
#: :func:`src.utils.criterion_seed.criterion_mapper_seed` fell back to ``description``.
#: The loss is booked against EXTRACTION, not against the vocabulary.
#:
#: The distinction this code exists to draw is which half of the pipeline to work on. A
#: row refused as ``no-concept-mapping`` says "the vocabulary was asked and has no
#: counterpart", and that sentence is only true if the vocabulary was asked the right
#: question. It was not: verbatim from the 2026-09-10 grounded delivery, EMPA-REG
#: inclusion 15 refused as "No concept mapping found for 'Drug naive'", where
#: ``'Drug naive'`` is the criterion's human-facing NAME. The line it came from names an
#: antidiabetic drug class; the mapper was never told.
#:
#: Not a hypothesis. Over two independent stores, counting only the criteria that
#: REACH the mapper (store ``mappable``, not skipped) across the six delivered trials,
#: an empty ``entity_text`` multiplies the loss rate by 6x and 20x:
#:
#:     store                        reach   entity present      entity EMPTY
#:       store_grounded (09-10)      293    4/223 = 0.018      8/70 = 0.114
#:       tte_cold6_20260908          274    1/184 = 0.005     10/90 = 0.111
#:
#: The two runs agree on the EMPTY column to within 0.003 and disagree on the present
#: column, so the stable quantity is the ~11% loss on a substituted seed rather than the
#: ratio. Not fatal, though: ~89% of substituted seeds still map, which is why the
#: remedy is a record and a re-coding rather than a refusal.
#:
#: What the code deliberately does NOT claim is that the protocol had an entity to
#: extract. CAROLINA exclusion 72 ("patients considered reliable by the investigator")
#: carries no ``entity_text`` and names no clinical entity either, so its loss is
#: irreducible and the code still reads correctly on it: the mapper was refused on a
#: substituted seed. Deciding WHICH of the two it is means reading the protocol line,
#: which is a judgement no deterministic rule at this site can make -- so the code
#: states the mechanism it can observe and leaves the diagnosis to the reader it routes.
#:
#: NEVER permitted by the delivery gate, and it must not become permitted: the loss is a
#: loss. What changes is which defect a reader is sent to look at.
REFUSAL_MISSING_ENTITY_TEXT = "missing-entity-text"

#: The codes a SUBSTITUTED SEED can cause, and therefore the only ones
#: :data:`REFUSAL_MISSING_ENTITY_TEXT` may re-code. Every one of them is a verdict ON
#: THE SEED: the vocabulary was asked this text and had nothing, or answered from the
#: wrong domain, or the intent router could not parse it, or the search returned an
#: empty expression. Change the seed and every one of them can change.
#:
#: An allow-list rather than a deny-list, and the direction is the load-bearing part. A
#: refusal wrongly re-coded sends a reader to extraction for a defect that lives
#: somewhere else; a refusal left alone merely keeps the record it already had. So a
#: code not named here is never re-coded, including any added later.
#:
#: Three codes are deliberately absent:
#:
#: * :data:`REFUSAL_UNMAPPABLE_PLACEHOLDER` -- the ONE code the delivery gate permits,
#:   and these rows earn it on the seed's own words. "Investigational drug use"
#:   (ARISTOTLE exclusion 26, empty ``entity_text``) names a role in the study rather
#:   than a substance, so no ``entity_text`` would have helped and the loss is
#:   irreducible either way. Re-coding it would take a real permit away and flip both
#:   ARISTOTLE arms from PASS to FAIL for a row nothing is wrong with.
#: * :data:`REFUSAL_STRANDED_GROUP_THRESHOLD` and
#:   :data:`REFUSAL_UNREADABLE_VALUE_FILTER` -- both are refused AFTER the mapper
#:   answered, and both are about the NUMBER rather than the concepts. A different seed
#:   changes neither.
#:
#: :data:`REFUSAL_EMPTY_SEED` is absent for a different reason: it already says the
#: stronger thing ("no seed text at all"), so re-coding would lose information.
SEED_CAUSED_REFUSAL_CODES = frozenset(
    {
        REFUSAL_NO_CONCEPT_MAPPING,
        REFUSAL_INTENT_UNPARSED,
        REFUSAL_EMPTY_CONCEPT_SET,
        REFUSAL_DOMAIN_CONTRADICTION,
    }
)


#: Every code a record's ``refusalCode`` may hold. A consumer that permits a code not in
#: this set is permitting something no mapper can emit.
REFUSAL_CODES = frozenset(
    {
        REFUSAL_NO_CONCEPT_MAPPING,
        REFUSAL_UNMAPPABLE_PLACEHOLDER,
        REFUSAL_INTENT_UNPARSED,
        REFUSAL_EMPTY_CONCEPT_SET,
        REFUSAL_EMPTY_SEED,
        REFUSAL_STRANDED_GROUP_THRESHOLD,
        REFUSAL_DOMAIN_CONTRADICTION,
        REFUSAL_UNREADABLE_VALUE_FILTER,
        REFUSAL_MISSING_ENTITY_TEXT,
    }
)


# N818 wants an `Error` suffix. Not here: this is not an error, it is a VERDICT --
# the mapper looked and decided no -- and the whole point of the class is that a
# consumer can tell it apart from the failures. Naming it like one would invite exactly
# the conflation `refusalCode` exists to prevent. The name is also already in the
# contract the delivery-gate consumer was written against.
class CriterionRefused(ValueError):  # noqa: N818
    """A DELIBERATE mapper refusal, carrying why in a form a machine can read.

    Subclasses :class:`ValueError` so the existing ``except Exception`` handlers and the
    tests that assert on the message text keep working unchanged; what it adds is the
    ``code``, which is what a consumer classifies on.

    :param message: the human-readable reason. Must be non-empty — a refusal that says
        nothing is the defect this class exists to prevent.
    :param code: one of :data:`REFUSAL_CODES`.
    :param detail: the verbatim upstream explanation when one exists (the intent
        router's own ``fallback_reason``, say), kept apart from ``message`` so a
        consumer can surface it without re-parsing the sentence it was folded into.
    :raises ValueError: when ``message`` is blank or ``code`` is not in the vocabulary.
    """

    def __init__(self, message: str, *, code: str, detail: str | None = None) -> None:
        if not (message or "").strip():
            raise ValueError(
                "CriterionRefused needs a reason: an empty message is the defect this "
                "class exists to prevent"
            )
        if code not in REFUSAL_CODES:
            raise ValueError(
                f"CriterionRefused code {code!r} is not in the vocabulary; "
                f"add it to REFUSAL_CODES in this module rather than at the call site "
                f"(known: {', '.join(sorted(REFUSAL_CODES))})"
            )
        super().__init__(message)
        self.code = code
        self.detail = detail
