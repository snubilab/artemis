"""
Criteria Planner (Agent 1.5) - Clinical Criteria Decomposer.
Decomposes composite clinical criteria into granular, OMOP-searchable sub-criteria.
"""
import json
from typing import Optional, List
from langchain_core.messages import SystemMessage, HumanMessage

from src.utils.llm import get_llm
from src.models.ir import ARTEMISRequest, CohortDefinition, Criteria
from src.agents.planner.prompts import PLANNER_SYSTEM_PROMPT, DECOMPOSITION_PROMPT


class CriteriaPlanner:
    """
    Agent 1.5: Analyzes each criterion from Agent 1's IR output and
    decomposes composite/umbrella terms into specific sub-criteria.
    
    Pipeline: Agent 1 → [Planner] → Agent 2
    """
    
    def __init__(self, model_name: Optional[str] = None):
        self.llm = get_llm(model_name=model_name, temperature=0.0)
    
    def plan(self, ir: ARTEMISRequest) -> ARTEMISRequest:
        """
        Process the IR and decompose composite criteria in both target 
        and comparator cohorts.
        
        Args:
            ir: ARTEMISRequest from Agent 1
            
        Returns:
            ARTEMISRequest with decomposed criteria
        """
        print("[Planner] Analyzing criteria for decomposition...")
        
        # Process target cohort
        ir.target = self._process_cohort(ir.target, "target")
        
        # Process comparator cohort
        ir.comparator = self._process_cohort(ir.comparator, "comparator")
        
        return ir
    
    def _process_cohort(self, cohort: CohortDefinition, label: str) -> CohortDefinition:
        """Process a single cohort's inclusion and exclusion rules."""
        # Process inclusion rules
        new_inclusion = []
        for rule in cohort.inclusion_rules:
            processed = self._decompose_criterion(rule)
            new_inclusion.append(processed)
        cohort.inclusion_rules = new_inclusion
        
        # Process exclusion rules
        new_exclusion = []
        for rule in cohort.exclusion_rules:
            processed = self._decompose_criterion(rule)
            new_exclusion.append(processed)
        cohort.exclusion_rules = new_exclusion
        
        total_sub = sum(len(r.sub_criteria) for r in cohort.inclusion_rules + cohort.exclusion_rules)
        print(f"[Planner] {label}: {len(cohort.inclusion_rules)} inclusion, "
              f"{len(cohort.exclusion_rules)} exclusion rules "
              f"({total_sub} sub-criteria generated)")
        
        return cohort
    
    def _decompose_criterion(self, criterion: Criteria) -> Criteria:
        """
        Analyze a single criterion and decompose if composite.
        
        If the LLM determines the criterion is composite, populates
        sub_criteria and sets group_type to "ANY".
        """
        # Skip if entity_text is None or already has sub_criteria
        if not criterion.entity_text or criterion.sub_criteria:
            return criterion
        
        # Call LLM
        prompt = DECOMPOSITION_PROMPT.format(
            name=criterion.name,
            entity_text=criterion.entity_text,
            domain=criterion.domain,
            logic_type=criterion.logic_type
        )
        
        messages = [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            result = self._extract_json(response.content)
            
            if result.get("decompose", False) and result.get("sub_criteria"):
                # Build sub-criteria list
                sub_criteria = []
                for sc_data in result["sub_criteria"]:
                    sc = Criteria(
                        name=sc_data.get("name", "Unnamed"),
                        domain=sc_data.get("domain", criterion.domain),
                        entity_text=sc_data.get("entity_text", ""),
                        logic_type=criterion.logic_type,  # Inherit parent's logic
                        window=criterion.window,  # Inherit parent's window
                        value_constraint=criterion.value_constraint,  # Inherit parent's value filter
                    )
                    sub_criteria.append(sc)
                
                criterion.sub_criteria = sub_criteria
                # De Morgan: negating a disjunction distributes as a conjunction.
                # "cardiovascular disease" (PRESENCE) → any sub-term qualifies → ANY.
                # "no drug abuse" (ABSENCE) → alcohol AND opioid AND cannabis must all
                # be absent → ALL. Using ANY here would let one absent sub-term pass the
                # whole exclusion, silently admitting patients the protocol excludes.
                criterion.group_type = "ALL" if criterion.logic_type == "ABSENCE" else "ANY"

                print(f"  ✂ '{criterion.entity_text}' → "
                      f"{len(sub_criteria)} sub-criteria ({criterion.logic_type}"
                      f"/{criterion.group_type}): "
                      f"{[sc.entity_text for sc in sub_criteria[:5]]}...")
            else:
                print(f"  ✓ '{criterion.entity_text}' → atomic (no decomposition)")
                
        except Exception as e:
            print(f"  ⚠ Decomposition failed for '{criterion.entity_text}': {e}")
            # On failure, keep the original criterion unchanged
        
        return criterion
    
    def _extract_json(self, content: str) -> dict:
        """Extract and parse JSON from LLM response content."""
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            print(f"[Planner] JSON parsing error: {e}")
            return {"decompose": False, "sub_criteria": []}


# Lazy singleton
_planner_instance = None

def get_planner(model_name: str | None = None) -> CriteriaPlanner:
    """Get or create Planner instance (lazy initialization).

    When model_name is provided, returns a fresh instance using that model.
    When model_name is None, returns (or creates) the cached singleton.
    """
    global _planner_instance
    if model_name is not None:
        return CriteriaPlanner(model_name=model_name)
    if _planner_instance is None:
        _planner_instance = CriteriaPlanner()
    return _planner_instance
