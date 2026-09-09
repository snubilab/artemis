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

#: The intent router could not parse the seed into a clinical entity — usually because
#: the seed still carries a temporal qualifier ("... within 3 years") that belongs in the
#: criterion's ``window``, not in its text. The refusal is correct; the defect is
#: upstream, at extraction.
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

#: Every code a record's ``refusalCode`` may hold. A consumer that permits a code not in
#: this set is permitting something no mapper can emit.
REFUSAL_CODES = frozenset(
    {
        REFUSAL_NO_CONCEPT_MAPPING,
        REFUSAL_INTENT_UNPARSED,
        REFUSAL_EMPTY_CONCEPT_SET,
        REFUSAL_EMPTY_SEED,
        REFUSAL_STRANDED_GROUP_THRESHOLD,
        REFUSAL_DOMAIN_CONTRADICTION,
        REFUSAL_UNREADABLE_VALUE_FILTER,
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
