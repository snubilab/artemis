"""
LLM Critic — Multi-select concept evaluator for KG-RAG pipeline.

After KG expansion returns candidate concepts from Neo4j, the Critic
evaluates each candidate and selects ALL relevant concepts (multi-select).

Architecture reference: KRAGEN (Bioinformatics, 2024)
  - Chain-of-Thought (CoT) prompting, with no few-shot examples (AGENTS.md rule 1)
  - Multi-select with reasoning
  - JSON structured output

Pipeline position:
  Vector Search → KG Expansion (Neo4j) → **LLM Critic** → Final Concept IDs
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

import openai
from langchain_core.exceptions import OutputParserException
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.utils.exceptions import LLMConfigurationError
from src.utils.llm import (
    CRITIC_MAX_TOKENS,
    StrictJsonOutputParser,
    _is_vllm_model,
    finish_reason,
    get_llm,
    resolve_model,
    token_usage,
)
from src.agents.agent2.kg_expander import KGConcept
from src.agents.agent2.critic_cache import CriticCache

logger = logging.getLogger(__name__)

# Well-defined domains where gpt-4o-mini is sufficient for concept evaluation
_WELL_DEFINED_DOMAINS = frozenset({"Condition", "Drug", "Measurement"})

# What people type when they mean "turn the override off". Every one of these used
# to be accepted as a literal model name and sent to OpenRouter, at real cost,
# while LLM_MODEL said local. There is no model called "off".
_NOT_A_MODEL_NAME = frozenset({
    "none", "null", "off", "false", "true", "0", "1", "no", "yes", "disable", "disabled",
})

# Status codes that mean the model or credential is wrong for *every* call, not
# just this one, so retrying or degrading gracefully is the wrong answer.
_UNSERVABLE_STATUS = frozenset({401, 403, 404})

# Bump by hand on any edit to the prompt, the few-shot examples or the output schema.
# Both caches key on critic_signature() and neither hashes the prompt, so without this
# a mapping computed under one prompt replays under another — silently corrupting the
# exact before/after the cache is supposed to make cheap. This was added while trying a
# grouped output schema (2026-08-11); that schema was measured and reverted, but the
# hole it exposed is real and the guard stays.
_CRITIC_PROMPT_VERSION = "2026-10-12-no-library-format-instructions"

# The reply budget, in completion tokens. A reply judges each candidate in its own entry,
# and google/gemma-4-E4B-it often lists every candidate. Measured 2026-10-14 in the critic
# A/B (333 calls): the 24 replies that ended finish_reason "length" at the former 4096 were
# all on 49-, 51- and 54-candidate inputs and had reached entry 41-45 at 91-100 tokens per
# entry, so the full list needs ~4.7-5.4k tokens; complete replies ran at a median of 120
# tokens per entry. In P3 arms A and B, 16/159 and 20/200 critic calls (45-54 candidates)
# show the same cut in their logs, and the strict parser rejects every cut reply, so each of
# those criteria kept its seeds alone. Prompts reach ~4k tokens; prompt + 8192 stays far
# inside the served 65536 context. The cap stays finite on purpose: a model that never stops
# (hari-q3-8b once ran a whole benchmark into the context ceiling) fails fast and visibly.
# Raised to 22,528 on 2026-10-23 by the one rule in src/utils/llm.py (4x the largest of 12,502
# replies, 5,543); the constant lives there with the other caps.
_CRITIC_MAX_TOKENS = CRITIC_MAX_TOKENS


def _concept_rows(concept_ids: List[int]) -> Dict[int, tuple]:
    """(concept_name, domain_id, vocabulary_id) per id, from the OMOP concept table."""
    import psycopg2
    from src.settings import settings

    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT concept_id, concept_name, domain_id, vocabulary_id "
                f"FROM {settings.CDM_SCHEMA}.concept WHERE concept_id = ANY(%s)",
                (list(concept_ids),),
            )
            return {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}
    finally:
        conn.close()


def critic_signature() -> str:
    """Everything about the critic that changes its answer, as one cache-key part.

    Both mapping caches keyed only on resolve_model(), i.e. LLM_MODEL. Agent 2's
    critic does not necessarily use that model: AGENT2_CRITIC_MODEL_TIER overrides
    it per domain. Probed live with LLM_MODEL held constant, tier None / "auto" /
    "gpt-4o" selected critic models None / gpt-4o-mini / gpt-4o and produced the
    SAME cache key, so a mapping computed under one provider replays under another
    while provenance reports the current configuration. That silently invalidates
    exactly the model comparison the cache is supposed to make cheap.

    Self-reflection is included because it filters concepts out of the result, so
    two runs that differ only in that flag are not interchangeable.

    The prompt enters as a hand-maintained version string, not a hash. Hashing a 9 KB
    template on every key would cost more than the collision it guards against, but
    omitting it entirely meant a prompt edit silently staled nothing and replayed
    everything — which is precisely the trap the 2026-08-11 schema experiment walked
    into. _CRITIC_PROMPT_VERSION must be bumped with any prompt edit.
    """
    tier = os.environ.get("AGENT2_CRITIC_MODEL_TIER") or ""
    reflect = os.environ.get("AGENT2_CRITIC_SELF_REFLECT", "true").lower()
    # The domain-resolved model, not the tier string: "auto" means different models
    # for different domains, and the domain is already part of every key.
    return f"tier={tier}|reflect={reflect}|prompt={_CRITIC_PROMPT_VERSION}"


def select_critic_model(domain_hint: str | None = None) -> str | None:
    """Which model the Critic should use, or None to follow LLM_MODEL.

    Default is None so one setting moves the whole pipeline. This used to return
    the literal "gpt-4o-mini" for Condition, Drug and Measurement — the three
    domains carrying nearly every criterion — which has no vllm/ prefix and so
    fell through to OpenRouter regardless of what LLM_MODEL said. A benchmark
    labelled with a local model would have been mostly executed by OpenAI, and
    nothing in the output would have shown it.

    Tiering is still available, but it is now opt-in via AGENT2_CRITIC_MODEL_TIER:
      - unset or "follow" (default, case-insensitive): use LLM_MODEL, whatever it is
      - "auto" (case-insensitive): the old domain-based split between gpt-4o and gpt-4o-mini
      - any other value: that literal model name, case preserved

    The sentinels are matched case-insensitively because "Follow", "AUTO" and
    "None" used to be read as literal model names and sent to OpenRouter, where
    they 404 — and the 404 was swallowed one frame down, so the run completed
    with Agent 2 degraded to plain vector search.

    Args:
        domain_hint: OMOP domain (e.g., "Condition", "Drug", "Observation").

    Returns:
        A model name, or None meaning "whatever LLM_MODEL is set to".

    Raises:
        LLMConfigurationError: the value is a boolean-ish word, not a model name.
    """
    tier = os.environ.get("AGENT2_CRITIC_MODEL_TIER", "follow").strip()
    sentinel = tier.lower()

    if sentinel in ("", "follow"):
        return None

    if sentinel in _NOT_A_MODEL_NAME:
        raise LLMConfigurationError(
            f"AGENT2_CRITIC_MODEL_TIER={tier!r} is not a model name. Use 'follow' "
            "(default — the critic follows LLM_MODEL), 'auto' (domain-based "
            "tiering), or an actual model id."
        )

    if sentinel == "auto":
        # Cost tiering: gpt-4o-mini was judged sufficient on well-defined domains.
        # Only meaningful when LLM_MODEL is an OpenAI model in the first place.
        model = "gpt-4o-mini" if domain_hint and domain_hint in _WELL_DEFINED_DOMAINS else "gpt-4o"
    else:
        model = tier  # model ids are case-sensitive; keep exactly what was written

    _warn_if_critic_leaves_local(model)
    return model


def _warn_if_critic_leaves_local(critic_model: str) -> None:
    """One visible line when the critic and the rest of the pipeline split providers.

    A tier override while LLM_MODEL is local is a legitimate opt-in, but it is
    also how a benchmark ends up labelled with a local model and executed
    remotely on the 90% domains. Make the divergence say so out loud.
    """
    pipeline_model = resolve_model(None)
    if _is_vllm_model(critic_model) or not _is_vllm_model(pipeline_model):
        return
    logger.warning(
        "[Critic] AGENT2_CRITIC_MODEL_TIER routes the critic to %r while LLM_MODEL "
        "is %r — the critic will not run on the local server.",
        critic_model, pipeline_model,
    )


@dataclass(frozen=True)
class CriticCompletion:
    """How one critic reply ended, as the server reported it; None where it said nothing.

    :param finish_reason: ``stop`` for a reply that ended, ``length`` for one cut at the budget.
    :param completion_tokens: tokens the reply used.
    :param prompt_tokens: tokens the request used.
    """

    finish_reason: Optional[str] = None
    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None

    @classmethod
    def of(cls, message: Any) -> "CriticCompletion":
        """Read the counts off a model message; any other object reads as unreported."""
        usage = token_usage(message)
        return cls(
            finish_reason(message), usage.get("completion_tokens"), usage.get("prompt_tokens")
        )

    def describe(self) -> str:
        return f"finish_reason={self.finish_reason}, completion_tokens={self.completion_tokens}"


@dataclass(frozen=True)
class CriticOutcome:
    """What one critic call produced.

    :param concept_ids: the selection, or the seeds alone when ``failure`` is set.
    :param failure: why the critic's answer could not be used (one line), or None.
    :param completion: how the model's reply ended; None when no model call was made
        (cache hit, nothing to judge) or the call raised before a reply arrived.
    """

    concept_ids: List[int]
    failure: Optional[str] = None
    completion: Optional[CriticCompletion] = None


@dataclass(frozen=True)
class _CriticReply:
    """The parsed reply together with how it ended."""

    value: Any
    completion: CriticCompletion


class _CriticReplyParser(StrictJsonOutputParser):
    """``StrictJsonOutputParser`` that keeps how the reply ended next to what it said.

    The parser is the last step that sees the model's message, which is where the server's
    ``finish_reason`` and token counts live. It returns them with the parsed value, and
    attaches them to a parse failure as ``critic_completion``, so the critic can log them for
    every call and name them in the failure it records. Parsing itself is unchanged: a cut
    or malformed reply is still ``Invalid json output``, never repaired.
    """

    def parse_result(self, result: list, *, partial: bool = False) -> Any:
        completion = CriticCompletion.of(getattr(result[0], "message", None))
        try:
            value = super().parse_result(result, partial=partial)
        except OutputParserException as e:
            e.critic_completion = completion
            raise
        return _CriticReply(value, completion)


def _log_completion(
    completion: Optional[CriticCompletion], reply: str, *,
    query: str, domain_hint: Optional[str], model: str, n_candidates: int,
) -> None:
    """One ``[Critic] Completion {json}`` line per model call, so a run counts cut replies directly.

    :param reply: ``parsed`` (the reply was JSON), ``unparseable`` (it was not), or ``none``
        (the call raised before a reply arrived).
    """
    c = completion or CriticCompletion()
    logger.info("[Critic] Completion %s", json.dumps({
        "query": query, "domain": domain_hint, "model": model, "candidates": n_candidates,
        "max_tokens": _CRITIC_MAX_TOKENS, "finish_reason": c.finish_reason,
        "completion_tokens": c.completion_tokens, "prompt_tokens": c.prompt_tokens, "reply": reply,
    }, ensure_ascii=False, sort_keys=True))


def _ask(chain: Any, payload: Dict[str, str], **call: Any) -> tuple:
    """Invoke the critic chain once and log how its reply ended.

    :returns: (the parsed reply, its :class:`CriticCompletion`); the completion is None when
        the chain is not the critic's own (it then returns the parsed value alone).
    :raises: whatever the chain raised; a parse failure carries ``critic_completion``.
    """
    try:
        reply = chain.invoke(payload)
    except Exception as e:
        completion = getattr(e, "critic_completion", None)
        _log_completion(completion, "none" if completion is None else "unparseable", **call)
        raise
    if isinstance(reply, _CriticReply):
        _log_completion(reply.completion, "parsed", **call)
        return reply.value, reply.completion
    _log_completion(None, "parsed", **call)
    return reply, None


# ── Output Schema ──────────────────────────────────────────
class CriticSelection(BaseModel):
    """Schema for a single concept evaluation.

    When self-reflection is enabled (AGENT2_CRITIC_SELF_REFLECT=true),
    the additional fields (confidence, potential_issue, assessment,
    recommended_action) are populated by the reflection pass.
    """
    concept_id: int = Field(description="The OMOP Concept ID")
    relevant: bool = Field(description="True if this concept is relevant to the clinical query")
    reasoning: str = Field(description="Brief reasoning for inclusion/exclusion")
    confidence: float = Field(default=1.0, description="Confidence 0.0-1.0 in the relevance judgment")
    potential_issue: str = Field(
        default="none",
        description="Issue type: abbreviation_confusion, domain_mismatch, too_specific, vocab_mismatch, none"
    )
    assessment: str = Field(
        default="correct",
        description="Self-reflection assessment: correct, partially_supported, contradicted"
    )
    recommended_action: str = Field(
        default="keep",
        description="Recommended action: keep, drop, rerank"
    )


class CriticResult(BaseModel):
    """Schema for the full critic output."""
    selected_concepts: List[CriticSelection] = Field(
        description="List of evaluated concepts with relevance judgments"
    )
    overall_reasoning: str = Field(
        description="Overall reasoning about the clinical query and concept selection"
    )


# ── No few-shot examples ──
# The prompt carries no examples and no concept, disease, drug or lab names: general
# selection rules only. Chosen by prompt evolution on fixed critic inputs (2026-10-11);
# the examples it replaced scored lower per criterion against gold.


# Self-reflection instructions appended when AGENT2_CRITIC_SELF_REFLECT=true.
_SELF_REFLECTION_INSTRUCTIONS = """

SELF-REFLECTION PASS:
After your initial evaluation, re-check each concept you marked as relevant and update the fields:

1. Abbreviation check: could the query or the concept name be an abbreviation meaning something else here? If yes, set potential_issue="abbreviation_confusion".
2. Domain check: if the concept's domain differs from the target domain, set potential_issue="domain_mismatch".
3. Breadth check: if the concept is broader than the query and would admit patients who do not meet it, set assessment="contradicted" and recommended_action="drop".
4. Quantity check: for a measured quantity, keep only seed result concepts that name the queried analyte. Mark every other selected measurement concept as assessment="contradicted" and recommended_action="drop".

Set confidence (0.0-1.0) after reflection. Use assessment "correct" with recommended_action "keep" when no issue is found, and "partially_supported" with "rerank" for minor concerns.
Concepts with assessment="contradicted" are filtered out."""


# The output contract, written out instead of LangChain's ``get_format_instructions()``.
# That text appended a sample object, a counterexample and this module's own pydantic
# docstrings to the system prompt. Field names and meanings follow ``CriticSelection`` /
# ``CriticResult``; ``StrictJsonOutputParser`` parses the answer.
_OUTPUT_CONTRACT = """Return ONLY a JSON object with these keys:
- selected_concepts: an array with one object per candidate you evaluated. Each object has:
  - concept_id: integer, the candidate's OMOP Concept ID.
  - relevant: boolean, true if the concept is relevant to the clinical query.
  - reasoning: string, brief reasoning for inclusion or exclusion.
  - confidence: number from 0.0 to 1.0, confidence in the relevance judgment.
  - potential_issue: one of abbreviation_confusion, domain_mismatch, too_specific, vocab_mismatch, none.
  - assessment: one of correct, partially_supported, contradicted.
  - recommended_action: one of keep, drop, rerank.
- overall_reasoning: string, overall reasoning about the clinical query and concept selection."""


# ── Critic Class ───────────────────────────────────────────
class ConceptCritic:
    """
    LLM-based multi-select critic for OMOP concept evaluation.

    Unlike the Reranker (single-select), the Critic evaluates each candidate
    independently and selects ALL relevant concepts for a clinical query.

    Self-reflection (two-pass): When AGENT2_CRITIC_SELF_REFLECT=true (default),
    the critic includes reflection instructions in the same LLM call, asking
    the model to generate counterevidence for each selection and flag
    abbreviation confusion, domain mismatch, etc.
    """

    def __init__(self):
        # The budget and why: see _CRITIC_MAX_TOKENS.
        self._default_llm = get_llm(temperature=0.0, json_mode=True, max_tokens=_CRITIC_MAX_TOKENS)
        self._cache = CriticCache()
        self._self_reflect = os.environ.get(
            "AGENT2_CRITIC_SELF_REFLECT", "true"
        ).lower() == "true"
        self.parser = _CriticReplyParser(pydantic_object=CriticResult)

        reflection_section = _SELF_REFLECTION_INSTRUCTIONS if self._self_reflect else ""

        self.prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert clinical informaticist specializing in OMOP CDM concept mapping.\n"
             "\n"
             "Your task is to evaluate candidate OMOP concepts and select ALL that are clinically relevant to the given query. This is MULTI-SELECT — you may select multiple concepts.\n"
             "\n"
             "Guidelines:\n"
             "1. First state to yourself the single clinical entity the query names (a disorder, a procedure, a measured quantity, a drug, a status) and how broad the query wording is.\n"
             "2. Judge every candidate by its MEANING, not by the relationship label it was retrieved through. The retrieval label (\"sibling\", \"ancestor\", \"seed\") only describes how a candidate was found.\n"
             "3. SELECT a candidate when it names the same entity as the query, a synonym of it, or a more specific kind (subtype, variant, stage, anatomical or etiological form) of that entity. Subtypes are often listed as siblings or two-hop neighbours; include every one whose meaning falls inside the query. Every patient coded with such a concept satisfies the query.\n"
             "4. REJECT a candidate that is BROADER than the query: a parent category that also covers other entities would admit patients who do not meet the criterion.\n"
             "5. REJECT a candidate that is a different entity, even if related: a complication, cause, predisposing state, test for, treatment of, or neighbouring disorder of the queried entity.\n"
             "6. For a measured quantity, the criterion is about one numeric result. Select the seed result concept and any other candidate that reports exactly the same quantity in the same kind of specimen. Reject grouping or procedure-level measurement concepts, other analytes, ratios, fractions or sub-forms of the analyte, qualitative presence tests, and challenge or timed variants. Fewer, exact concepts are better than many approximate ones.\n"
             "7. For drugs, prefer ingredient-level concepts over formulation or product concepts.\n"
             "8. If the query states a target domain, prefer candidates from that domain."
             + reflection_section +
             "\n\n" + _OUTPUT_CONTRACT),
            ("user",
             "Clinical Query: {query}\n\n"
             "Candidate Concepts:\n{candidates_text}")
        ])

        self._default_chain = self.prompt | self._default_llm | self.parser
    
    def _apply_self_reflection_filter(
        self,
        selections: List[Dict[str, Any]],
        kg_concept_ids: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """Filter contradicted concepts, but preserve KG-validated ones with decent confidence.

        KG-expanded concepts represent graph-validated knowledge relationships. When
        the Critic marks them as "contradicted", it may be over-pruning valid expansions
        (e.g., Stroke subtypes from KG graph). This method preserves such concepts if
        their confidence is above 0.5 to prevent ablation-level over-pruning.

        Args:
            selections: List of selection dicts from LLM output (already filtered by relevant=True).
            kg_concept_ids: Set of concept IDs that came from KG expansion.
                            None means no KG context available; skip the preservation logic.

        Returns:
            Filtered list of selections with KG-validated concepts preserved when appropriate.
        """
        result = []
        for sel in selections:
            should_drop = (
                sel.get("assessment") == "contradicted"
                or sel.get("recommended_action") == "drop"
            )
            if not should_drop:
                result.append(sel)
                continue

            concept_id = sel.get("concept_id")
            is_kg = concept_id in kg_concept_ids if kg_concept_ids else False
            confidence = sel.get("confidence", 1.0)

            if is_kg and confidence > 0.5:
                # KG-validated with decent confidence: preserve despite critic's drop verdict
                logger.info(
                    f"[Critic] Preserved KG concept {concept_id} despite drop "
                    f"(confidence={confidence:.2f}, assessment={sel.get('assessment')})"
                )
                result.append(sel)
            else:
                logger.info(
                    f"[Critic] Self-reflect DROP {concept_id}: "
                    f"issue={sel.get('potential_issue', 'none')}, "
                    f"confidence={confidence:.2f}, "
                    f"reason={sel.get('reasoning', '')}"
                )
        return result

    def evaluate(
        self,
        query: str,
        seed_concept_ids: List[int],
        kg_concepts: List[KGConcept],
        context: Optional[str] = None,
        domain_hint: Optional[str] = None,
        kg_concept_ids: Optional[set] = None,
    ) -> List[int]:
        """The selected concept IDs alone; see :meth:`evaluate_with_outcome`.

        A failed critic returns the seeds here with nothing to say so. The workflow
        calls :meth:`evaluate_with_outcome`, which carries the failure.
        """
        return self.evaluate_with_outcome(
            query, seed_concept_ids, kg_concepts,
            context=context, domain_hint=domain_hint, kg_concept_ids=kg_concept_ids,
        ).concept_ids

    def evaluate_with_outcome(
        self,
        query: str,
        seed_concept_ids: List[int],
        kg_concepts: List[KGConcept],
        context: Optional[str] = None,
        domain_hint: Optional[str] = None,
        kg_concept_ids: Optional[set] = None,
    ) -> CriticOutcome:
        """
        Evaluate KG-expanded concepts and return the selected concept IDs.

        A call that fails, or a reply that is not complete JSON carrying a
        ``selected_concepts`` list, logs one "[Critic] Evaluation failed" line and
        returns the seeds with the reason in ``failure``; it is not cached.

        Args:
            query: Original clinical query text
            seed_concept_ids: Initial concept IDs from vector search
            kg_concepts: Expanded concepts from KG traversal
            context: Optional clinical context
            domain_hint: OMOP domain for model tiering (e.g., "Condition", "Drug")
            kg_concept_ids: Set of concept IDs from KG expansion. When provided,
                            contradicted KG concepts with confidence > 0.5 are
                            preserved to prevent over-pruning of graph-validated
                            expansions. If None, no preservation logic is applied.

        Returns:
            CriticOutcome: the selected OMOP Concept IDs (multi-select), or the seeds
            and the failure reason.

        Raises:
            LLMConfigurationError: the critic model is not servable by its provider.
        """
        if not kg_concepts and not seed_concept_ids:
            return CriticOutcome([])

        # If no KG expansion results, return seed concepts as-is
        if not kg_concepts:
            return CriticOutcome(seed_concept_ids)

        # Cache check (REQ-03): early return on cache hit. Keyed on the candidates too:
        # a key of query + domain alone answered a later call with other seeds from an
        # earlier call's selection (P2 NEW 'CABG', 2026-10-12).
        cache_key = self._cache.make_key(
            query,
            domain_hint,
            context=context,
            seed_concept_ids=seed_concept_ids,
            candidate_concept_ids=[c.concept_id for c in kg_concepts],
            kg_concept_ids=kg_concept_ids,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info(
                f"[CACHE HIT] Critic returning {len(cached)} cached concepts "
                f"for '{query}' (domain={domain_hint})"
            )
            return CriticOutcome(cached)
        
        # Build candidates list: seed + KG expanded
        candidates_text = ""
        all_concept_ids = set()

        # A seed is normally NOT among kg_concepts (workflow.py dedups KG results
        # against the seeds), so without this the seed went out as a bare id while
        # every KG candidate carried a name.
        kg_ids = {c.concept_id for c in kg_concepts}
        unnamed = [cid for cid in seed_concept_ids if cid not in kg_ids]
        seed_rows: Dict[int, tuple] = {}
        if unnamed:
            try:
                seed_rows = _concept_rows(unnamed)
            except Exception as e:
                logger.warning(f"[Critic] Seed concept lookup failed for {unnamed}: {e}")
            missing = [cid for cid in unnamed if cid not in seed_rows]
            if missing:
                logger.warning(f"[Critic] Seeds rendered without a name (not in concept table): {missing}")

        for cid in seed_concept_ids:
            # Find matching KG concept info
            matching = [c for c in kg_concepts if c.concept_id == cid]
            if matching:
                c = matching[0]
                candidates_text += (
                    f"- ID: {cid} | Name: {c.concept_name} | Domain: {c.domain_id} "
                    f"| Vocab: {c.vocabulary_id} | Relationship: seed\n"
                )
            elif cid in seed_rows:
                name, domain, vocab = seed_rows[cid]
                candidates_text += (
                    f"- ID: {cid} | Name: {name} | Domain: {domain} "
                    f"| Vocab: {vocab} | Relationship: seed (vector search top match)\n"
                )
            else:
                candidates_text += f"- ID: {cid} | Relationship: seed (vector search top match)\n"
            all_concept_ids.add(cid)
        
        for c in kg_concepts:
            if c.concept_id not in all_concept_ids:
                candidates_text += (
                    f"- ID: {c.concept_id} | Name: {c.concept_name} | Domain: {c.domain_id} "
                    f"| Vocab: {c.vocabulary_id} | Relationship: {c.relationship}\n"
                )
                all_concept_ids.add(c.concept_id)
        
        full_query = f"{context}: {query}" if context else query

        # Domain-aware model tiering (REQ-02), opt-in via AGENT2_CRITIC_MODEL_TIER.
        # None means "follow LLM_MODEL", which is what _default_chain already holds —
        # the test used to be `!= "gpt-4o"`, which after the default flipped to None
        # rebuilt the model and the chain on every single call.
        model_name = select_critic_model(domain_hint)
        if model_name is not None:
            llm = get_llm(
                model_name=model_name, temperature=0.0, json_mode=True,
                max_tokens=_CRITIC_MAX_TOKENS,
            )
            chain = self.prompt | llm | self.parser
        else:
            chain = self._default_chain
        model = resolve_model(model_name)
        logger.info(f"[Critic] Model: {model} (domain={domain_hint})")

        completion: Optional[CriticCompletion] = None
        try:
            result, completion = _ask(
                chain,
                {"query": full_query, "candidates_text": candidates_text},
                query=query, domain_hint=domain_hint, model=model,
                n_candidates=len(all_concept_ids),
            )

            # A reply without the selections is a broken reply, not "nothing selected":
            # read as the latter it returned the seeds and cached them as the answer.
            if not isinstance(result, dict) or not isinstance(result.get("selected_concepts"), list):
                raise ValueError(
                    "critic reply carries no selected_concepts list: "
                    f"{json.dumps(result)[:200]}"
                )

            # Extract selected concept IDs
            selected = []
            raw_selections = result["selected_concepts"]

            # Split into relevant and non-relevant for logging
            relevant_selections = [s for s in raw_selections if s.get("relevant", False)]
            for sel in raw_selections:
                if not sel.get("relevant", False):
                    logger.debug(
                        f"[Critic] Rejected {sel.get('concept_id')}: "
                        f"{sel.get('reasoning', '')}"
                    )

            # Apply self-reflection filter (preserves KG-validated concepts)
            if self._self_reflect:
                filtered_selections = self._apply_self_reflection_filter(
                    relevant_selections, kg_concept_ids
                )
                contradicted_count = len(relevant_selections) - len(filtered_selections)
            else:
                filtered_selections = relevant_selections
                contradicted_count = 0

            for sel in filtered_selections:
                cid = sel.get("concept_id")
                if cid and cid in all_concept_ids:
                    selected.append(cid)
                    logger.debug(
                        f"[Critic] Selected {cid}: {sel.get('reasoning', '')} "
                        f"(assessment={sel.get('assessment', 'correct')})"
                    )
                elif cid:
                    logger.warning(f"[Critic] Selected ID {cid} not in candidates")

            if contradicted_count:
                logger.info(
                    f"[Critic] Self-reflection filtered out {contradicted_count} "
                    f"contradicted concepts for '{query}'"
                )
            
            overall = result.get("overall_reasoning", "")
            logger.info(
                f"[Critic] Query: '{query}' → Selected {len(selected)}/{len(all_concept_ids)} "
                f"concepts. Reasoning: {overall[:100]}"
            )
            
            # Always include seed concepts as fallback
            if not selected:
                logger.warning("[Critic] No concepts selected, falling back to seed concepts")
                self._cache.put(cache_key, seed_concept_ids)
                return CriticOutcome(seed_concept_ids, completion=completion)

            # Cache the result for future identical queries
            self._cache.put(cache_key, selected)
            return CriticOutcome(selected, completion=completion)

        except Exception as e:
            # A wrong model id or a dead credential fails identically on every
            # item. Degrading to seed concepts there discards KG expansion and
            # still produces a complete, plausible, lower-scoring result set —
            # one ERROR line per item and nothing in the output. Transient
            # failures keep the fallback; a misconfiguration must stop the run.
            if isinstance(e, openai.APIStatusError) and e.status_code in _UNSERVABLE_STATUS:
                raise LLMConfigurationError(
                    f"Critic model {resolve_model(model_name)!r} is not servable by its "
                    f"provider (HTTP {e.status_code}): {e}"
                ) from e
            # Seeds, uncached, with the reason the caller records on the mapping. A parse
            # failure quotes the whole reply, so the recorded reason keeps its head only,
            # followed by how the reply ended: a reply cut at the budget reads
            # "finish_reason=length" where it is recorded, not only in the log.
            reason = " ".join(f"{type(e).__name__}: {e}".split())
            if len(reason) > 300:
                reason = reason[:300] + " ..."
            if completion is None:
                completion = getattr(e, "critic_completion", None)
            if completion is not None:
                reason = f"{reason} ({completion.describe()})"
            logger.error(f"[Critic] Evaluation failed: {reason}")
            return CriticOutcome(list(seed_concept_ids), failure=reason, completion=completion)


# ── Singleton ──────────────────────────────────────────────
_critic_instance: Optional[ConceptCritic] = None


def get_critic() -> ConceptCritic:
    """Get or create ConceptCritic instance (lazy initialization)."""
    global _critic_instance
    if _critic_instance is None:
        _critic_instance = ConceptCritic()
    return _critic_instance
