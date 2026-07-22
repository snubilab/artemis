"""
Post-Mapping Consolidator.
Merges sibling ConceptSets into common ancestor ConceptSets
using OMOP concept_ancestor hierarchy.

Modes:
- Default: max_separation=5, standard LCA merging
- Aggressive (KG_CONSOLIDATOR_AGGRESSIVE=true): max_separation=8,
  IC guard (rejects LCA with IC < 6.0 to prevent merging to generic concepts)
"""
import os
import logging
from typing import List, Optional, Dict, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConceptSetConsolidator:
    """
    Consolidates over-decomposed ConceptSets by finding their
    Lowest Common Ancestor (LCA) in the OMOP concept hierarchy.
    
    Pipeline position: Agent 2 → [Consolidator] → Registry
    """
    
    def __init__(self, ontology_search=None, max_separation: int = 5):
        """
        Args:
            ontology_search: OntologySearch instance for ancestor lookups
            max_separation: Maximum hierarchy levels to search for ancestors
        """
        self.ontology_search = ontology_search
        
        # Aggressive mode (lab meeting 2026-03-05):
        # Broader hierarchy search with IC-based guard
        aggressive = os.environ.get("KG_CONSOLIDATOR_AGGRESSIVE", "").strip().lower()
        if aggressive in ("true", "1", "yes"):
            self.max_separation = 8
            self.aggressive = True
            self.min_ic_threshold = 6.0  # Reject LCA with IC < 6.0
            logger.info(
                f"[Consolidator] Aggressive mode: max_sep={self.max_separation}, "
                f"IC threshold={self.min_ic_threshold}"
            )
        else:
            self.max_separation = max_separation
            self.aggressive = False
            self.min_ic_threshold = 0.0
    
    def find_lowest_common_ancestor(self, concept_ids: List[int]) -> Optional[int]:
        """
        Find the Lowest Common Ancestor (LCA) of a set of concept IDs.
        
        The LCA is the most specific concept that is an ancestor of ALL
        given concept IDs. We pick the one with the smallest total 
        separation distance.
        
        Args:
            concept_ids: List of OMOP concept IDs
            
        Returns:
            Ancestor concept_id if found, None otherwise
        """
        if not concept_ids or len(concept_ids) < 2:
            return None
        
        # Get ancestor sets for each concept
        ancestor_sets = []
        for cid in concept_ids:
            ancestors = self.ontology_search.get_ancestors(
                cid, max_levels=self.max_separation
            )
            if not ancestors:
                return None  # If any concept has no ancestors, can't merge
            ancestor_sets.append(set(ancestors))
        
        # Find intersection (common ancestors)
        common = ancestor_sets[0]
        for s in ancestor_sets[1:]:
            common = common & s
        
        if not common:
            return None
        
        # Pick the lowest (most specific) common ancestor
        # = the one that appears earliest in individual ancestor lists
        # (get_ancestors returns ordered by min_levels_of_separation ASC)
        first_ancestors = self.ontology_search.get_ancestors(
            concept_ids[0], max_levels=self.max_separation
        )
        for ancestor_id in first_ancestors:
            if ancestor_id in common:
                return ancestor_id
        
        # Fallback: return any common ancestor
        return next(iter(common))
    
    def consolidate(self, mapped_sets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Consolidate mapped concept sets by merging siblings with common ancestors.
        
        Sets are grouped by `parent_rule`. Within each group, if a common
        ancestor is found, the group is merged into a single ConceptSet.
        
        Args:
            mapped_sets: List of mapped concept set dicts from pipeline
            
        Returns:
            Consolidated list (fewer items if merging occurred)
        """
        # Group by parent_rule
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        ungrouped: List[Dict[str, Any]] = []
        
        for ms in mapped_sets:
            parent = ms.get("parent_rule")
            if parent:
                groups[parent].append(ms)
            else:
                ungrouped.append(ms)
        
        result = list(ungrouped)
        
        for parent_rule, group in groups.items():
            if len(group) < 2:
                # Single item, no consolidation needed
                result.extend(group)
                continue
            
            # Collect all concept_ids from the group
            all_concept_ids = []
            for ms in group:
                all_concept_ids.extend(ms.get("concept_ids", []))
            
            if not all_concept_ids:
                result.extend(group)
                continue
            
            # Try to find LCA
            lca = self.find_lowest_common_ancestor(all_concept_ids)
            
            if lca is not None:
                # Aggressive mode IC guard: reject LCA if too generic
                if self.aggressive and self.min_ic_threshold > 0:
                    ic = None
                    if hasattr(self.ontology_search, 'get_ic'):
                        ic = self.ontology_search.get_ic(lca)
                    if ic is not None and ic < self.min_ic_threshold:
                        # LCA is too generic (e.g., "Disease"), keep individual sets
                        # but mark them with includeDescendants=true
                        for ms in group:
                            ms["include_descendants"] = True
                        result.extend(group)
                        logger.info(
                            f"  ⚠️ LCA {lca} rejected (IC={ic:.1f} < {self.min_ic_threshold}). "
                            f"Keeping {len(group)} sets with includeDescendants for '{parent_rule}'"
                        )
                        continue
                
                # Merge into single ConceptSet with ancestor
                ancestor_name = parent_rule  # Default name
                if hasattr(self.ontology_search, 'get_concept_name'):
                    name = self.ontology_search.get_concept_name(lca)
                    if name:
                        ancestor_name = name
                
                merged = {
                    "id": group[0]["id"],
                    "name": ancestor_name,
                    "domain": group[0]["domain"],
                    "concept_ids": [lca],
                    "source": group[0]["source"],
                    "include_descendants": True,
                    "parent_rule": parent_rule,
                    "merged_from": len(group),
                }
                result.append(merged)
                logger.info(
                    f"  🔗 Consolidated {len(group)} sets → '{ancestor_name}' "
                    f"(ancestor={lca}, includeDescendants=true)"
                )
            else:
                # No common ancestor, keep individual sets
                result.extend(group)
                logger.info(
                    f"  ℹ No common ancestor for '{parent_rule}' "
                    f"({len(group)} sets kept)"
                )
        
        return result
