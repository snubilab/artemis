import json
import logging
from typing import List, Optional, Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.utils.env_flags import env_flag_enabled
from src.utils.llm import StrictJsonOutputParser, get_llm
from src.agents.agent2.retriever import CandidateConcept

logger = logging.getLogger(__name__)

# Domain-specific abbreviation grounding instructions.
# Toggle: AGENT2_RERANKER_DOMAIN_AWARE (default "true").
# Stated as a rule with no abbreviation glossary and no counterexample: a list of
# expansions is an example (AGENTS.md § PROMPTS AND TEXT RULES, rule 1).
_DOMAIN_GROUNDING_INSTRUCTION = """
When the domain_hint is provided, interpret every medical abbreviation in the sense it has within that domain.
Do NOT select concepts from an unrelated clinical domain, even when a candidate's name shares letters or an abbreviation with the term.
"""

#: The single-select output contract, written out instead of LangChain's
#: ``get_format_instructions()``, which appends a sample object and a counterexample.
#: Field names and meanings follow ``RerankResult``; ``StrictJsonOutputParser`` parses.
_SINGLE_SELECT_OUTPUT = """Return ONLY a JSON object with these keys:
- selected_concept_id: integer, the ID of the best-matching candidate, or null if none fits.
- reasoning: string, a brief explanation of why this concept was selected."""


# The one authoritative top-N prompt. It used to be written out twice — once in
# rerank_topn and once in rerank_topn_batch — and the batch copy is the one the
# pipeline calls, so editing either alone changed unit-test behaviour and nothing else.
#
# The gate is the substantive change. "Select the concepts that BEST match" is a
# superlative, and a superlative over a non-empty candidate list always has an answer:
# `qqzzxx nonexistent clinical term` came back with three myocardial-infarction
# concepts, logged as a successful selection. The prompt states the empty answer as a
# field rule. A few-shot showing it (b437d20) was removed on 2026-10-12 with every other
# prompt example, and the JSON template that showed filled values became a description
# of the two keys.
#
# The first two lines are the original prompt, unchanged, and they stay that way. A
# richer rewrite was measured on ARISTOTLE (2026-08-11) and its extra framing — asking
# whether a candidate "denotes" the term — competed with vocabulary specificity: the
# reranker swapped LOINC `Platelets [#/volume] in Blood` for SNOMED `Platelet count -
# finding`, whose name is the more literal match and whose 177 descendants share
# nothing with the gold lab set. Per-criterion recall on that pair went 0.500 -> 0.000.
# Everything added here is therefore additive to the original wording, never a
# replacement for it.
TOPN_SYSTEM_PROMPT = (
    "You are an expert medical terminologist.\n"
    "Select up to {top_n} OMOP Concept IDs from the candidates that "
    "best match the user's clinical intent. Order by relevance.\n"
    "Return ONLY a JSON object with two keys: query_has_match, a boolean, and "
    "selected_ids, an array of the selected candidate IDs, most relevant first.\n"
    "If none fit, set query_has_match to false and selected_ids to an empty array. "
    "Selecting nothing is a correct answer, not a failure."
)


class RerankerFailed(RuntimeError):
    """The reranker's answer could not be used, so no candidate was selected.

    The message is the single-line failure reason the workflow records on the
    MappingResult. Raised instead of answering, because every answer this module can
    give -- a selection, an empty list, None -- is also what a working reranker says.
    """


def _failure_reason(exc: Exception) -> str:
    """One line naming ``exc``, capped as the critic caps its reason."""
    reason = " ".join(f"{type(exc).__name__}: {exc}".split())
    return reason[:300] + " ..." if len(reason) > 300 else reason


def _selected_ids(response: Any) -> list:
    """The top-N answer's ids, or [] when the model said no candidate fits.

    A reply that is not an object, or that does not refuse and carries no
    ``selected_ids`` list, is a broken reply, not "nothing fits": read as the latter it
    became a gap recorded like a genuine no-match.

    :raises ValueError: the reply is not the requested answer.
    """
    if not isinstance(response, dict):
        raise ValueError(f"reranker reply is not a JSON object: {json.dumps(response)[:200]}")
    if _refused(response):
        return []
    ids = response.get("selected_ids")
    if not isinstance(ids, list):
        raise ValueError(
            f"reranker reply carries no selected_ids list: {json.dumps(response)[:200]}"
        )
    return ids


def _refused(response: dict) -> bool:
    """Whether the model answered "none of these fit".

    Absent means unanswered, not refused: an older model that ignores the gate must
    keep working. A response that says false while still listing IDs contradicts
    itself, and the branch that maps nothing is the safe one — the criterion is
    dropped and recorded rather than silently assigned the wrong concepts.
    """
    return response.get("query_has_match") is False


class RerankResult(BaseModel):
    selected_concept_id: Optional[int] = Field(description="The Concept ID of the best match, or null if none fit.")
    reasoning: str = Field(description="Brief explanation of why this concept was selected.")


class ConceptReranker:
    """
    LLM-based reranker for selecting best OMOP concept from candidates.
    
    Supports both single and batch reranking for improved throughput.
    Pattern 4 from artemis_agent: Batch Processing.
    """
    
    def __init__(self):
        self.llm = get_llm(temperature=0.0, json_mode=True)
        self.parser = StrictJsonOutputParser(pydantic_object=RerankResult)

        domain_aware = env_flag_enabled("AGENT2_RERANKER_DOMAIN_AWARE")
        domain_section = _DOMAIN_GROUNDING_INSTRUCTION if domain_aware else ""

        system_msg = (
            "You are an expert medical terminologist. "
            "Your task is to select the single best OMOP Concept ID from a list of candidates "
            "that exactly matches the user's clinical intent.\n"
            "If none of the candidates are appropriate, return null for the ID.\n"
            + domain_section + "\n"
            "\n" + _SINGLE_SELECT_OUTPUT
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_msg),
            ("user", "User Context: {user_query}\n\nCandidates:\n{candidates_text}")
        ])

        self.chain = self.prompt | self.llm | self.parser

        # Built once. rerank_topn used to reconstruct this template and chain on every
        # single call, and rerank_topn_batch kept a second copy of the same text.
        self._topn_prompt = ChatPromptTemplate.from_messages([
            ("system", TOPN_SYSTEM_PROMPT),
            ("user", "Clinical term: {user_query}\n\nCandidates:\n{candidates_text}")
        ])
        self._topn_chain = self._topn_prompt | self.llm | StrictJsonOutputParser()

    def rerank(self, user_query: str, candidates: List[CandidateConcept]) -> Optional[CandidateConcept]:
        """
        Single query reranking.
        
        Args:
            user_query: The clinical term to find best match for
            candidates: List of candidate concepts from vector search
            
        Returns:
            Best matching CandidateConcept, or None when the model chose none

        Raises:
            RerankerFailed: the call failed or its reply could not be parsed.
        """
        if not candidates:
            return None

        # Format candidates for the prompt
        candidates_text = ""
        for c in candidates:
            candidates_text += f"- ID: {c.concept_id} | Name: {c.concept_name} | Class: {c.concept_class_id} | Vocab: {c.vocabulary_id}\n"

        try:
            result = self.chain.invoke({
                "user_query": user_query,
                "candidates_text": candidates_text,
            })
        except Exception as e:
            reason = _failure_reason(e)
            logger.warning(f"[Reranker] Reranking failed: {reason}")
            raise RerankerFailed(reason) from e

        selected_id = result.get("selected_concept_id") if isinstance(result, dict) else None
        if selected_id:
            # Find the candidate object to return
            for c in candidates:
                if c.concept_id == selected_id:
                    return c
        return None

    def rerank_topn(
        self, user_query: str, candidates: List[CandidateConcept], top_n: int = 3
    ) -> List[CandidateConcept]:
        """
        Top-N reranking: return up to N best-matching concepts.
        
        Instead of selecting a single best, instructs the LLM to pick the 
        top_n most relevant concepts. This prevents losing correct candidates
        at the reranking bottleneck.

        :returns: the selection, most relevant first; empty when the model said no
            candidate fits.
        :raises RerankerFailed: the call failed, or its reply is not complete JSON
            carrying ``selected_ids`` (one counted "[Reranker] Top-N reranking failed"
            line, nothing selected).
        """
        if not candidates:
            return []

        candidates_text = ""
        for c in candidates:
            candidates_text += (
                f"- ID: {c.concept_id} | Name: {c.concept_name} "
                f"| Class: {c.concept_class_id} | Vocab: {c.vocabulary_id}\n"
            )

        # One call, one answer. A failed call used to fall back to the single-select
        # prompt and use its pick: a second question, answered from a different prompt,
        # recorded as this one's selection.
        try:
            result = self._topn_chain.invoke({
                "user_query": user_query,
                "candidates_text": candidates_text,
                "top_n": top_n,
            })
            selected_ids = _selected_ids(result)
        except Exception as e:
            reason = _failure_reason(e)
            logger.warning(f"[Reranker] Top-N reranking failed: {reason}")
            raise RerankerFailed(reason) from e

        if _refused(result):
            logger.info(
                "[Reranker] '%s': no candidate denotes the term (%d offered) — selecting none",
                user_query, len(candidates),
            )
            return []

        # Map back to CandidateConcept objects, preserving order
        id_to_candidate = {c.concept_id: c for c in candidates}
        selected = [id_to_candidate[sid] for sid in selected_ids[:top_n] if sid in id_to_candidate]

        logger.info(f"[Reranker] Top-{top_n}: selected {len(selected)} from {len(candidates)} candidates")
        return selected

    def rerank_batch(
        self, 
        queries_with_candidates: List[Dict[str, Any]],
        max_concurrency: int = 5
    ) -> List[Optional[CandidateConcept]]:
        """
        Batch reranking with parallel LLM calls.
        
        Pattern 4 from artemis_agent: Batch Processing.
        
        Args:
            queries_with_candidates: List of dicts with 'query' and 'candidates' keys
            max_concurrency: Maximum parallel LLM calls
            
        Returns:
            List of best matching CandidateConcept or None for each query

        Raises:
            RerankerFailed: the batch, or any query in it, failed.
        """
        if not queries_with_candidates:
            return []
        
        # Prepare batch inputs
        batch_inputs = []
        original_candidates = []  # Keep track for result mapping
        
        for item in queries_with_candidates:
            query = item.get("query", "")
            candidates = item.get("candidates", [])
            
            if not candidates:
                batch_inputs.append(None)
                original_candidates.append([])
                continue
            
            # Format candidates
            candidates_text = ""
            for c in candidates:
                candidates_text += f"- ID: {c.concept_id} | Name: {c.concept_name} | Class: {c.concept_class_id} | Vocab: {c.vocabulary_id}\n"
            
            batch_inputs.append({
                "user_query": query,
                "candidates_text": candidates_text,
            })
            original_candidates.append(candidates)
        
        # Filter out None inputs (empty candidates)
        valid_indices = [i for i, x in enumerate(batch_inputs) if x is not None]
        valid_inputs = [batch_inputs[i] for i in valid_indices]
        
        if not valid_inputs:
            return [None] * len(queries_with_candidates)
        
        responses = self._batch(self.chain, valid_inputs, max_concurrency, "Batch reranking")
        results: List[Optional[CandidateConcept]] = [None] * len(queries_with_candidates)
        for response, orig_idx in zip(responses, valid_indices):
            selected_id = response.get("selected_concept_id") if isinstance(response, dict) else None
            if selected_id:
                for c in original_candidates[orig_idx]:
                    if c.concept_id == selected_id:
                        results[orig_idx] = c
                        break
        return results

    def rerank_topn_batch(
        self,
        queries_with_candidates: List[Dict[str, Any]],
        top_n: int = 3,
        max_concurrency: int = 5,
    ) -> List[List[CandidateConcept]]:
        """
        Batch Top-N reranking with parallel LLM calls.
        
        Each item in queries_with_candidates should have 'query' and 'candidates' keys.
        Returns a list of lists, each containing up to top_n CandidateConcept objects.
        Raises RerankerFailed when the batch, or any query in it, failed.
        """
        if not queries_with_candidates:
            return []

        # Prepare inputs
        batch_inputs = []
        original_candidates: List[List[CandidateConcept]] = []
        valid_indices = []

        for i, item in enumerate(queries_with_candidates):
            query = item.get("query", "")
            candidates = item.get("candidates", [])
            original_candidates.append(candidates)

            if not candidates:
                continue

            candidates_text = ""
            for c in candidates:
                candidates_text += (
                    f"- ID: {c.concept_id} | Name: {c.concept_name} "
                    f"| Class: {c.concept_class_id} | Vocab: {c.vocabulary_id}\n"
                )

            batch_inputs.append({
                "user_query": query,
                "candidates_text": candidates_text,
                "top_n": top_n,
            })
            valid_indices.append(i)

        results: List[List[CandidateConcept]] = [[] for _ in queries_with_candidates]

        if not batch_inputs:
            return results

        responses = self._batch(
            self._topn_chain, batch_inputs, max_concurrency, f"Batch top-{top_n} reranking",
            read=_selected_ids,
        )
        for (response, ids), orig_idx in zip(responses, valid_indices):
            candidates = original_candidates[orig_idx]
            if _refused(response):
                logger.info(
                    "[Reranker] '%s': no candidate denotes the term (%d offered) — selecting none",
                    queries_with_candidates[orig_idx].get("query", ""), len(candidates),
                )
                continue
            id_to_candidate = {c.concept_id: c for c in candidates}
            results[orig_idx] = [id_to_candidate[sid] for sid in ids[:top_n] if sid in id_to_candidate]

        logger.info(f"[Reranker] Batch top-{top_n}: processed {len(valid_indices)} queries")
        return results

    @staticmethod
    def _batch(chain, inputs: list, max_concurrency: int, what: str, read=None) -> list:
        """Run ``chain`` over ``inputs``; every answer, or RerankerFailed naming each failure.

        One failed item fails the batch: its slot cannot say "failed" in a list whose
        entries are selections, and an empty slot is what "no candidate fits" looks like.

        :param read: applied to each answer (raising on a broken one); its result is
            paired with the answer when given.
        :raises RerankerFailed: the batch call, or any item's call or answer, failed.
        """
        try:
            responses = chain.batch(
                inputs, config={"max_concurrency": max_concurrency}, return_exceptions=True
            )
        except Exception as e:
            reason = _failure_reason(e)
            logger.warning(f"[Reranker] {what} failed: {reason}")
            raise RerankerFailed(reason) from e

        out, failed = [], []
        for index, response in enumerate(responses):
            try:
                if isinstance(response, Exception):
                    raise response
                out.append((response, read(response)) if read else response)
            except Exception as e:
                failed.append(f"#{index}: {_failure_reason(e)}")
        if failed:
            reason = f"{len(failed)} of {len(inputs)} queries failed: " + "; ".join(failed)
            logger.warning(f"[Reranker] {what} failed: {reason}")
            raise RerankerFailed(reason)
        return out


# Lazy singleton
_reranker_instance = None


def get_reranker() -> ConceptReranker:
    """Get or create ConceptReranker instance (lazy initialization)."""
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = ConceptReranker()
    return _reranker_instance


# Global instance for backward compatibility
reranker = None  # Use get_reranker() instead

