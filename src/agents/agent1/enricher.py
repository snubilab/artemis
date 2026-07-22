"""
Agent 1 - TrialData Enricher.
Enriches TrialData from NCT API with criteria from PubMed design papers.

Three strategies:
- "replace": Use PubMed criteria if richer than NCT (default)
- "merge": Combine unique criteria from both sources
- "supplement_priority": Use PDF criteria as base, only add clearly missing NCT items
"""
import logging
from typing import Dict, List, Literal
from difflib import SequenceMatcher

from src.agents.agent1.nct_fetcher import TrialData

logger = logging.getLogger(__name__)


def enrich_trial_data(
    trial_data: TrialData,
    pubmed_criteria: Dict[str, List[str]],
    strategy: Literal["replace", "merge", "supplement_priority"] = "replace",
) -> TrialData:
    """
    Enrich TrialData with criteria from PubMed design paper.

    Args:
        trial_data: Original TrialData from NCT API
        pubmed_criteria: Dict with "inclusion" and "exclusion" lists
                         extracted from PubMed paper
        strategy: "replace" (use richer source), "merge" (combine unique),
                  or "supplement_priority" (PDF as base, add missing NCT items)

    Returns:
        Enriched TrialData (new instance, original preserved)
    """
    pub_inc = pubmed_criteria.get("inclusion", [])
    pub_exc = pubmed_criteria.get("exclusion", [])

    if strategy == "supplement_priority":
        new_inc = _supplement_priority_merge(pub_inc, trial_data.inclusion_criteria)
        new_exc = _supplement_priority_merge(pub_exc, trial_data.exclusion_criteria)
    elif strategy == "merge":
        new_inc = _merge_criteria(trial_data.inclusion_criteria, pub_inc)
        new_exc = _merge_criteria(trial_data.exclusion_criteria, pub_exc)
    else:
        # Replace strategy: use the richer source
        new_inc = _pick_richer(trial_data.inclusion_criteria, pub_inc)
        new_exc = _pick_richer(trial_data.exclusion_criteria, pub_exc)

    return TrialData(
        nct_id=trial_data.nct_id,
        title=trial_data.title,
        conditions=trial_data.conditions,
        interventions=trial_data.interventions,
        inclusion_criteria=new_inc,
        exclusion_criteria=new_exc,
        primary_outcomes=trial_data.primary_outcomes,
        study_type=trial_data.study_type,
        phase=trial_data.phase,
    )


def _pick_richer(nct_criteria: List[str], pubmed_criteria: List[str]) -> List[str]:
    """Pick whichever source has more criteria."""
    if len(pubmed_criteria) > len(nct_criteria):
        return pubmed_criteria
    return nct_criteria


def _merge_criteria(
    nct_criteria: List[str],
    pubmed_criteria: List[str],
    similarity_threshold: float = 0.7,
) -> List[str]:
    """
    Merge criteria from two sources, deduplicating by similarity.
    
    Args:
        nct_criteria: Criteria from NCT API
        pubmed_criteria: Criteria from PubMed paper
        similarity_threshold: Min similarity ratio to consider duplicate
        
    Returns:
        Merged list of unique criteria
    """
    merged = list(nct_criteria)
    
    for pub_item in pubmed_criteria:
        is_duplicate = False
        for nct_item in nct_criteria:
            similarity = SequenceMatcher(
                None, pub_item.lower(), nct_item.lower()
            ).ratio()
            if similarity >= similarity_threshold:
                is_duplicate = True
                break
        
        if not is_duplicate:
            merged.append(pub_item)
    
    return merged


def _supplement_priority_merge(
    pdf_criteria: List[str],
    nct_criteria: List[str],
    similarity_threshold: float = 0.5,
) -> List[str]:
    """
    Use PDF (supplement) criteria as the authoritative base.

    Only adds NCT items that are clearly missing from the PDF source
    (similarity < threshold to all PDF items). This preserves the richer,
    more structured supplement criteria while filling genuine gaps.

    Args:
        pdf_criteria: Criteria from supplement PDF (authoritative source)
        nct_criteria: Criteria from NCT API (gap-fill source)
        similarity_threshold: Max similarity to consider an NCT item as missing

    Returns:
        PDF criteria + clearly missing NCT items
    """
    if not pdf_criteria:
        logger.info("[Enricher] supplement_priority: no PDF criteria, falling back to NCT")
        return list(nct_criteria)

    merged = list(pdf_criteria)
    added_count = 0

    for nct_item in nct_criteria:
        max_similarity = 0.0
        for pdf_item in pdf_criteria:
            similarity = SequenceMatcher(
                None, nct_item.lower(), pdf_item.lower()
            ).ratio()
            if similarity > max_similarity:
                max_similarity = similarity
        if max_similarity < similarity_threshold:
            merged.append(nct_item)
            added_count += 1

    if added_count > 0:
        logger.info(
            "[Enricher] supplement_priority: %d PDF base + %d NCT gap-fill = %d total",
            len(pdf_criteria), added_count, len(merged),
        )

    return merged
