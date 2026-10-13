"""
Agent 1 - TrialData Enricher.
Enriches TrialData from NCT API with criteria from PubMed design papers.

Three strategies:
- "replace": Use PubMed criteria if richer than NCT (default)
- "merge": every criterion of both sources, the held ones first
- "supplement_priority": per section, the PDF's criteria when it yields that section,
  else the criteria already held (the registry's)
"""
import logging
from typing import Dict, List, Literal

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
        strategy: "replace" (use richer source), "merge" (every criterion of both sources),
                  or "supplement_priority" (per section: the PDF's criteria when it
                  yields that section, else the criteria already held)

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
) -> List[str]:
    """Every criterion of both sources: the held ones, then the paper's, each in order.

    No criterion is dropped here as a duplicate of another. A whole-string similarity
    ratio used to decide that (>= 0.7, inventory E7), which reads the wording of two
    criteria to judge whether they state one fact. Measured on the reingest inputs of
    the six evaluated trials it removed one criterion -- PLATO's design-paper
    "Increased risk of bradycardiac events" (0.83 against the main paper's "an
    increased risk of bradycardia,") -- and let at least five restatements in the same
    merge through at 0.23-0.56, so it never gave the guarantee it appeared to.
    A restatement reaches extraction as its own criterion. It is collapsed afterwards
    only where the rules built from both copies select exactly the same thing
    (``restated_rules``); where they do not, both stay and the restatement is visible
    in the IR rather than decided away here. Exact repeats are
    removed with the whitespace cleaning in
    ``parser._normalize_trial_data_for_stable_hash``.

    :param nct_criteria: the criteria already held (the registry's, plus any paper
        merged before this one).
    :param pubmed_criteria: this paper's criteria for the same section.
    :returns: ``nct_criteria`` followed by ``pubmed_criteria``.
    """
    return list(nct_criteria) + list(pubmed_criteria)


def _supplement_priority_merge(
    pdf_criteria: List[str],
    held_criteria: List[str],
) -> List[str]:
    """One section of the trial, from the trial's own document when it yields one.

    Called once per section (inclusion, exclusion) for a PDF whose role is protocol or
    supplement (``LogicDecomposer._strategy_for_role``). When the segmentation step found
    that section in the PDF, the section is the PDF's criteria and nothing else. When
    the PDF yields no criteria for it, the criteria already held stand: the registry's,
    or those of an authoritative PDF processed earlier. ``_discover_pdfs`` orders
    protocol before supplement, so a supplement that yields a section supplies it.

    The registry is not merged into a section the PDF supplies. Its bullets summarise
    the same criteria, and deciding which of them a PDF criterion already covers took a
    string-similarity gate and OR-GROUP containment; on ARISTOTLE every registry bullet
    passed the gate, so the five members of the protocol's risk-factor list came back as
    five further AND-ed inclusion criteria. Choosing the source per section needs no
    comparison of criteria at all.

    :param pdf_criteria: this section's criteria from the PDF.
    :param held_criteria: this section's criteria before the PDF was read.
    :returns: ``pdf_criteria`` when it is non-empty, else ``held_criteria``.
    """
    if pdf_criteria:
        if held_criteria:
            logger.info(
                "[Enricher] supplement_priority: section from the PDF (%d criteria); "
                "%d held criteria not used",
                len(pdf_criteria), len(held_criteria),
            )
        return list(pdf_criteria)
    logger.info("[Enricher] supplement_priority: the PDF yields no criteria for this section; "
                "keeping the %d held", len(held_criteria))
    return list(held_criteria)
