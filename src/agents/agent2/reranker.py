import logging
import os
from typing import List, Optional, Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from src.utils.llm import get_llm
from src.agents.agent2.retriever import CandidateConcept

logger = logging.getLogger(__name__)

# Domain-specific abbreviation grounding instructions.
# Toggle: AGENT2_RERANKER_DOMAIN_AWARE (default "true").
_DOMAIN_GROUNDING_INSTRUCTION = """
When the domain_hint is provided, interpret all medical abbreviations in the context of that domain:
- In Condition domain: MI = Myocardial Infarction, TIA = Transient Ischemic Attack, CHF = Congestive Heart Failure, CKD = Chronic Kidney Disease, CAD = Coronary Artery Disease, PAD = Peripheral Artery Disease, CVA = Cerebrovascular Accident
- In Drug domain: GLP-1 = Glucagon-like peptide-1 receptor agonist, DPP-4 = Dipeptidyl peptidase-4 inhibitor, SGLT2 = Sodium-glucose cotransporter-2 inhibitor
- In Measurement domain: HbA1c = Hemoglobin A1c, eGFR = estimated Glomerular Filtration Rate, LDL = Low-density lipoprotein
Do NOT select concepts from an unrelated clinical domain. For example, "MI" in the Condition domain must NOT match "milia" (a skin condition).
"""


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
        self.parser = JsonOutputParser(pydantic_object=RerankResult)

        domain_aware = os.environ.get("AGENT2_RERANKER_DOMAIN_AWARE", "true").lower() == "true"
        domain_section = _DOMAIN_GROUNDING_INSTRUCTION if domain_aware else ""

        system_msg = (
            "You are an expert medical terminologist. "
            "Your task is to select the single best OMOP Concept ID from a list of candidates "
            "that exactly matches the user's clinical intent.\n"
            "If none of the candidates are appropriate, return null for the ID.\n"
            + domain_section + "\n"
            "\n{format_instructions}"
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_msg),
            ("user", "User Context: {user_query}\n\nCandidates:\n{candidates_text}")
        ])

        self.chain = self.prompt | self.llm | self.parser

    def rerank(self, user_query: str, candidates: List[CandidateConcept]) -> Optional[CandidateConcept]:
        """
        Single query reranking.
        
        Args:
            user_query: The clinical term to find best match for
            candidates: List of candidate concepts from vector search
            
        Returns:
            Best matching CandidateConcept or None
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
                "format_instructions": self.parser.get_format_instructions()
            })
            
            selected_id = result.get("selected_concept_id")
            
            if selected_id:
                # Find the candidate object to return
                for c in candidates:
                    if c.concept_id == selected_id:
                        return c
            
            return None
            
        except Exception as e:
            logger.warning(f"Reranking failed: {e}")
            # Fallback: return None for safety
            return None

    def rerank_topn(
        self, user_query: str, candidates: List[CandidateConcept], top_n: int = 3
    ) -> List[CandidateConcept]:
        """
        Top-N reranking: return up to N best-matching concepts.
        
        Instead of selecting a single best, instructs the LLM to pick the 
        top_n most relevant concepts. This prevents losing correct candidates
        at the reranking bottleneck.
        """
        if not candidates:
            return []

        candidates_text = ""
        for c in candidates:
            candidates_text += (
                f"- ID: {c.concept_id} | Name: {c.concept_name} "
                f"| Class: {c.concept_class_id} | Vocab: {c.vocabulary_id}\n"
            )

        topn_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert medical terminologist.\n"
             "Select up to {top_n} OMOP Concept IDs from the candidates that "
             "best match the user's clinical intent. Order by relevance.\n"
             "Return ONLY a JSON object: {{\"selected_ids\": [id1, id2, ...]}}\n"
             "If none fit, return {{\"selected_ids\": []}}"),
            ("user", "Clinical term: {user_query}\n\nCandidates:\n{candidates_text}")
        ])

        try:
            topn_chain = topn_prompt | self.llm | JsonOutputParser()
            result = topn_chain.invoke({
                "user_query": user_query,
                "candidates_text": candidates_text,
                "top_n": top_n,
            })

            selected_ids = result.get("selected_ids", [])
            if not selected_ids:
                return []

            # Map back to CandidateConcept objects, preserving order
            id_to_candidate = {c.concept_id: c for c in candidates}
            selected = []
            for sid in selected_ids[:top_n]:
                if sid in id_to_candidate:
                    selected.append(id_to_candidate[sid])
            
            logger.info(f"[Reranker] Top-{top_n}: selected {len(selected)} from {len(candidates)} candidates")
            return selected

        except Exception as e:
            logger.warning(f"Top-N reranking failed: {e}, falling back to top-1")
            single = self.rerank(user_query, candidates)
            return [single] if single else []

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
                "format_instructions": self.parser.get_format_instructions()
            })
            original_candidates.append(candidates)
        
        # Filter out None inputs (empty candidates)
        valid_indices = [i for i, x in enumerate(batch_inputs) if x is not None]
        valid_inputs = [batch_inputs[i] for i in valid_indices]
        
        if not valid_inputs:
            return [None] * len(queries_with_candidates)
        
        try:
            # Run batch with concurrency control
            batch_responses = self.chain.batch(
                valid_inputs,
                config={"max_concurrency": max_concurrency},
                return_exceptions=True
            )
            
            # Map results back
            results: List[Optional[CandidateConcept]] = [None] * len(queries_with_candidates)
            
            for result_idx, orig_idx in enumerate(valid_indices):
                response = batch_responses[result_idx]
                candidates = original_candidates[orig_idx]
                
                if isinstance(response, Exception):
                    logger.warning(f"Batch reranking failed for index {orig_idx}: {response}")
                    results[orig_idx] = None
                else:
                    selected_id = response.get("selected_concept_id")
                    if selected_id:
                        for c in candidates:
                            if c.concept_id == selected_id:
                                results[orig_idx] = c
                                break
            
            return results
            
        except Exception as e:
            logger.error(f"Batch reranking failed: {e}")
            return [None] * len(queries_with_candidates)

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
        """
        if not queries_with_candidates:
            return []

        topn_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert medical terminologist.\n"
             "Select up to {top_n} OMOP Concept IDs from the candidates that "
             "best match the user's clinical intent. Order by relevance.\n"
             'Return ONLY a JSON object: {{"selected_ids": [id1, id2, ...]}}\n'
             'If none fit, return {{"selected_ids": []}}'),
            ("user", "Clinical term: {user_query}\n\nCandidates:\n{candidates_text}")
        ])
        topn_chain = topn_prompt | self.llm | JsonOutputParser()

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

        try:
            batch_responses = topn_chain.batch(
                batch_inputs,
                config={"max_concurrency": max_concurrency},
                return_exceptions=True,
            )

            for result_idx, orig_idx in enumerate(valid_indices):
                response = batch_responses[result_idx]
                candidates = original_candidates[orig_idx]

                if isinstance(response, Exception):
                    logger.warning(f"Batch top-N reranking failed for index {orig_idx}: {response}")
                    continue

                selected_ids = response.get("selected_ids", [])
                id_to_candidate = {c.concept_id: c for c in candidates}
                for sid in selected_ids[:top_n]:
                    if sid in id_to_candidate:
                        results[orig_idx].append(id_to_candidate[sid])

            logger.info(
                f"[Reranker] Batch top-{top_n}: processed {len(valid_indices)} queries"
            )
            return results

        except Exception as e:
            logger.error(f"Batch top-N reranking failed: {e}")
            return results


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

