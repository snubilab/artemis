"""The environment variables that decide what a mapping run produces.

Nine settings (ten variables -- the route forcing is a pair) change the CONTENT of a
generated concept set. Until this module existed none of them was printed and none was
recorded, so after an export finished there was no way to tell which mode had produced
it. That is the same shape of defect as the one ``src.utils.delivery_mode`` closes for
``TTE_DRUG_ANCHORED_ENTRY``, and this module follows it: resolve, report, record.

There is a second, sharper hazard. ``CriterionResultCache`` keys on
``text | domain | EMBEDDING_MODEL | LLM_MODEL | critic_signature``. Eight of these
variables are in none of those parts, so flipping one changes freshly-mapped criteria
while cached criteria replay the old mode -- **a single export mixing both**, with
nothing in the output saying so. :func:`mapping_signature` folds them into the key for
the same reason :func:`src.agents.agent2.critic.critic_signature` folds in the critic
tier: a mapping computed under one mode must not be replayed under another.

Two of the ten are deliberately NOT in the signature, and the reason is recorded on
each spec rather than left to be re-derived:

* ``EMBEDDING_MODEL`` is already a key part in its own right. Adding it here would give
  one decision two homes, and the two would drift.
* ``TTE_MAPPING_MAX_WORKERS`` is a thread-pool size. Criteria are mapped independently,
  so it moves wall-clock, not content.

An over-inclusive key is its own defect -- it invalidates the cache for changes that
cannot alter the result -- so inclusion is argued per flag at :data:`MAPPING_FLAGS`,
not assumed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: What an unset variable contributes to :func:`mapping_signature`. Distinct from any
#: real value, so "unset" and "set to the empty string" cannot collide.
UNSET = "<unset>"


@dataclass(frozen=True)
class FlagSpec:
    """One environment variable, its fallback, and whether it belongs in the cache key.

    :param default: the value the *consumer* falls back to when the variable is unset,
        or ``None`` when the consumers disagree and no single default is truthful.
        ``default_note`` carries the disagreement.
    """

    name: str
    default: str | None
    keyed: bool
    site: str
    effect: str
    rationale: str
    default_note: str = ""


@dataclass(frozen=True)
class FlagReading:
    """What one variable actually held on this run, and where the value came from."""

    spec: FlagSpec
    raw: str | None
    from_environment: bool

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def source(self) -> str:
        """``"environment"`` or ``"default"`` -- the two facts that used to read alike."""
        return "environment" if self.from_environment else "default"

    @property
    def effective(self) -> str:
        """The value the consumer sees: the environment's, else the consumer's default.

        Set-to-the-default and unset resolve to the same string on purpose. They are
        the same run, so keying them apart would cost a cache miss and buy nothing.
        Where no single default is truthful the sentinel :data:`UNSET` is used, which
        keeps ``REFINER_FOOTPRINT_THRESHOLD=1000`` distinct from unset -- correctly,
        since unset means 3000 in the legacy branch.
        """
        if self.from_environment:
            assert self.raw is not None
            return self.raw
        return self.spec.default if self.spec.default is not None else UNSET

    def describe(self) -> str:
        """One line that distinguishes 'nobody set this' from 'somebody set this'."""
        if self.from_environment:
            return f"explicitly set to {self.raw!r}"
        if self.spec.default is None:
            return f"unset; no single default ({self.spec.default_note})"
        return f"unset, defaulted to {self.spec.default!r}"


#: Every variable that changes what a mapping run emits, with the inclusion argument
#: for each. Ordered as the audit that found them listed them, not alphabetically;
#: :func:`mapping_signature` sorts by name so the key does not depend on this order.
MAPPING_FLAGS: tuple[FlagSpec, ...] = (
    FlagSpec(
        name="ENABLE_REFINER",
        default="1",
        keyed=True,
        site="src/agents/agent2/workflow.py:983,1019",
        effect=(
            "runs ConceptSetRefiner: final_ids becomes ref_result.kept_ids (subsumed "
            "ancestors dropped) and overbroad_ids is emitted, which tte_service.py turns "
            "into includeDescendants=False on those items"
        ),
        rationale=(
            "KEYED: changes both halves of what the entry stores -- the concept id list "
            "and the expression"
        ),
    ),
    FlagSpec(
        name="KG_EXPAND_MODE",
        default="clinical_anchor",
        keyed=True,
        site="src/agents/agent2/workflow.py:860",
        effect=(
            "selects anchor-only expansion against legacy full expansion: different "
            "per-domain KG limits, an extra ancestor_climb pass in legacy only, and the "
            "critic skip only in anchor mode"
        ),
        rationale="KEYED: selects which concepts are expanded and whether the critic runs",
    ),
    FlagSpec(
        name="INCLUDE_DESC_SEEDS_ONLY",
        default="1",
        keyed=True,
        site="src/agents/agent2/concept_set_refiner.py:196",
        effect=(
            "switches the includeDescendants policy between relationship-aware "
            "(ancestors false, rest true) and the legacy static descendant-count threshold"
        ),
        rationale="KEYED: rewrites includeDescendants in the stored expression",
    ),
    FlagSpec(
        name="FORCE_SLOW_PATH",
        default="",
        keyed=True,
        site="src/agents/agent2/workflow.py:462",
        effect=(
            "forces the slow route, so LLM reranking runs and different candidates "
            "reach the critic"
        ),
        rationale=(
            "KEYED: decides route_path, which selects the candidate set AND is itself a "
            "stored field on the cache entry"
        ),
    ),
    FlagSpec(
        name="FORCE_FAST_PATH",
        default="",
        keyed=True,
        site="src/agents/agent2/workflow.py:463",
        effect="forces the fast route, so LLM reranking is skipped",
        rationale="KEYED: same reason as FORCE_SLOW_PATH -- it selects the route",
    ),
    FlagSpec(
        name="EMBEDDING_MODEL",
        default="",
        keyed=False,
        site="src/settings.py:62, src/utils/vector.py:59, criterion_cache.py:_embedding_model",
        effect=(
            "selects the ChromaDB collection the retriever searches: 'medcpt' uses the "
            "MedCPT bi-encoder collection, every other value the built-in all-MiniLM-L6-v2"
        ),
        rationale=(
            "NOT KEYED HERE -- already a key part of its own, canonicalised by "
            "canonical_embedding_model(). Adding it a second time would give one decision "
            "two homes and let them drift"
        ),
    ),
    FlagSpec(
        name="DOMAIN_PRECHECK",
        default="0",
        keyed=True,
        site="src/agents/agent2/workflow.py:346",
        effect=(
            "lets a ChromaDB top-1 vote override the caller's domain_hint (the LEADER "
            "benchmark recorded 6 harmful overrides, e.g. Insulin Drug -> Procedure)"
        ),
        rationale=(
            "KEYED, and this one is not optional: the cache is keyed on the domain the "
            "CALLER passed, and the override happens downstream of the lookup inside "
            "process_with_details. So the override changes the result under an unchanged key"
        ),
    ),
    FlagSpec(
        name="FOOTPRINT_GUARD_IN_HYBRID",
        default="0",
        keyed=True,
        site="src/agents/agent2/concept_set_refiner.py:232",
        effect=(
            "adds refiner Pass 3, flagging sibling/maps_to concepts whose descendant "
            "count exceeds the threshold as overbroad -> includeDescendants=False"
        ),
        rationale="KEYED: adds a pass that rewrites the stored expression",
    ),
    FlagSpec(
        name="REFINER_FOOTPRINT_THRESHOLD",
        default=None,
        default_note=(
            "1000 at concept_set_refiner.py:235 (hybrid Pass 3), 3000 at :268 (legacy "
            "mode, via FOOTPRINT_THRESHOLD) -- the two readers disagree"
        ),
        keyed=True,
        site="src/agents/agent2/concept_set_refiner.py:235,268",
        effect="sets the descendant-count cut above which a concept is called overbroad",
        rationale=(
            "KEYED, with the cost stated: under the shipped defaults "
            "(FOOTPRINT_GUARD_IN_HYBRID=0, INCLUDE_DESC_SEEDS_ONLY=1) neither reader is "
            "reached, so setting this alone invalidates the cache for no behaviour change. "
            "The alternative -- keying it only when one of those two flags makes it "
            "reachable -- copies the refiner's branch structure into the cache module, "
            "where it would go stale silently the next time the refiner is edited. A "
            "cache miss is cheap; a replayed mapping from the wrong mode is the defect"
        ),
    ),
    FlagSpec(
        name="TTE_MAPPING_MAX_WORKERS",
        default="48",
        keyed=False,
        site="src/services/tte_service.py:4843",
        effect="caps the ThreadPoolExecutor that maps criteria in parallel",
        rationale=(
            "NOT KEYED: a pool size. Each criterion is mapped independently by "
            "_map_criterion, so concurrency moves wall-clock and DB pressure, not the "
            "concept set. Keying it would invalidate the cache on a purely operational knob"
        ),
    ),
)


def canonical_embedding_model(value: str | None) -> str:
    """Collapse the spellings of one embedding backend onto one name.

    ``src/settings.py`` defaults ``EMBEDDING_MODEL`` to ``"default"`` while
    ``criterion_cache.py`` defaulted it to ``"minilm"``. Both name the same model:
    ``vector.get_collection`` branches on ``== "medcpt"`` and sends everything else to
    the built-in all-MiniLM-L6-v2 collection. So setting the variable to the literal
    ``"default"`` re-namespaced the whole criterion cache without changing a single
    embedding -- a full cold run bought by a spelling.

    The comparison is exact, with no strip or lower, because ``get_collection`` compares
    exactly. Folding ``"MedCPT"`` in here would newly route it to the MedCPT collection,
    which is a behaviour change and not what this function is for.
    """
    return "medcpt" if value == "medcpt" else "minilm"


def read_flag(spec: FlagSpec) -> FlagReading:
    """Read one variable, recording presence rather than truthiness.

    Presence, not emptiness: ``FORCE_SLOW_PATH=""`` was set by somebody and behaves like
    unset, and those are different facts. Recording only the behaviour would lose the one
    that explains the run.
    """
    return FlagReading(
        spec=spec,
        raw=os.environ.get(spec.name),
        from_environment=spec.name in os.environ,
    )


def read_mapping_flags() -> list[FlagReading]:
    """Every flag in :data:`MAPPING_FLAGS`, as read from this process's environment."""
    return [read_flag(spec) for spec in MAPPING_FLAGS]


def mapping_signature() -> str:
    """The keyed flags as one cache-key part, in the shape ``critic_signature`` uses.

    Sorted by name so the part does not depend on the declaration order of
    :data:`MAPPING_FLAGS`, and so re-ordering that tuple cannot silently invalidate
    every cached entry.
    """
    parts = [
        f"{reading.name}={reading.effective}"
        for reading in sorted(read_mapping_flags(), key=lambda r: r.name)
        if reading.spec.keyed
    ]
    return "|".join(parts)


def mapping_flags_manifest() -> dict[str, object]:
    """The recorded section for ``manifest.json``.

    Every flag appears with its value, whether that value came from the environment or
    from a default, and whether it takes part in the criterion cache key. The signature
    is repeated whole so two manifests can be compared without re-deriving it.
    """
    flags: dict[str, object] = {}
    for reading in read_mapping_flags():
        entry: dict[str, object] = {
            "value": reading.raw if reading.from_environment else reading.spec.default,
            "source": reading.source,
            "description": reading.describe(),
            "in_criterion_cache_key": reading.spec.keyed,
            "site": reading.spec.site,
        }
        if reading.spec.default is None:
            entry["default_note"] = reading.spec.default_note
        flags[reading.name] = entry

    return {
        "flags": flags,
        "criterion_cache_key_signature": mapping_signature(),
    }


def mapping_flags_summary() -> str:
    """A printable block, so the mode is said out loud and not only written to disk."""
    lines = ["mapping env flags (value, and where it came from):"]
    for reading in read_mapping_flags():
        keyed = "keyed" if reading.spec.keyed else "not keyed"
        lines.append(f"  {reading.name}: {reading.describe()} [{keyed}]")
    return "\n".join(lines)
