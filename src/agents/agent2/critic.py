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

import logging
import os
from typing import List, Optional, Dict, Any

import openai
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from src.utils.exceptions import LLMConfigurationError
from src.utils.llm import _is_vllm_model, get_llm, resolve_model
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
# ``CriticResult``; ``JsonOutputParser`` still parses the answer.
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
        # 4096 against a largest-legitimate-output of 2,161 tokens, measured on
        # Qwen2.5-7B with the real prompt. Inert for a model that terminates; for
        # one that does not it turns a 25-minute silent runaway into a fast visible
        # parse failure. hari-q3-8b ran an entire benchmark truncating at the
        # context ceiling, and the handler in evaluate() turned every one of those
        # into a seed-only fallback that nothing in the output distinguished from
        # success.
        self._default_llm = get_llm(temperature=0.0, json_mode=True, max_tokens=4096)
        self._cache = CriticCache()
        self._self_reflect = os.environ.get(
            "AGENT2_CRITIC_SELF_REFLECT", "true"
        ).lower() == "true"
        self.parser = JsonOutputParser(pydantic_object=CriticResult)

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
        """
        Evaluate KG-expanded concepts and return selected concept IDs.

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
            List of selected OMOP Concept IDs (multi-select)
        """
        if not kg_concepts and not seed_concept_ids:
            return []

        # If no KG expansion results, return seed concepts as-is
        if not kg_concepts:
            return seed_concept_ids

        # Cache check (REQ-03): early return on cache hit
        cache_key = self._cache.make_key(query, domain_hint)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info(
                f"[CACHE HIT] Critic returning {len(cached)} cached concepts "
                f"for '{query}' (domain={domain_hint})"
            )
            return cached
        
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
            llm = get_llm(model_name=model_name, temperature=0.0, json_mode=True, max_tokens=4096)
            chain = self.prompt | llm | self.parser
        else:
            chain = self._default_chain
        logger.info(f"[Critic] Model: {resolve_model(model_name)} (domain={domain_hint})")

        try:
            result = chain.invoke({
                "query": full_query,
                "candidates_text": candidates_text,
            })
            
            # Extract selected concept IDs
            selected = []
            raw_selections = result.get("selected_concepts", [])

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
                return seed_concept_ids

            # Cache the result for future identical queries
            self._cache.put(cache_key, selected)
            return selected
            
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
            logger.error(f"[Critic] Evaluation failed: {e}")
            return seed_concept_ids  # Fallback to seed


# ── Singleton ──────────────────────────────────────────────
_critic_instance: Optional[ConceptCritic] = None


def get_critic() -> ConceptCritic:
    """Get or create ConceptCritic instance (lazy initialization)."""
    global _critic_instance
    if _critic_instance is None:
        _critic_instance = ConceptCritic()
    return _critic_instance
