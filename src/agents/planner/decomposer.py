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
from src.services.value_constraint import parse_value_constraint
from src.agents.agent1.threshold_classifier import deescape
from src.utils.naming_words import naming_words


def _comparison_form(text: str) -> str:
    """Comparison form for the substring check: de-escaped, whitespace-folded, lowered.

    Same convention as ``threshold_classifier._normalise``, which owns it for ADR-032
    threshold spans; this is the same decision applied to sub-term spans. Tolerating
    case and whitespace drift is safe -- a model that re-wraps a line still copied it
    -- while an analyte the line never mentions is absent under any of these forms.
    """
    return " ".join(deescape(text).split()).lower()


# Moved to `src.utils.naming_words` so `src/utils/circe_lint.py` can ask the same
# question of a whole stored criterion without importing this module's model stack. The
# alias is kept because gate 2 below and every existing caller read the private name.
#
# The moved version does NOT route through `_comparison_form`, and that is an identity
# rather than a tolerance: `deescape` only removes backslashes, and the split pattern
# treats a backslash as a separator like every other non-alphanumeric character, so the
# two agree on every possible input. Re-checked against the 1,910 criterion strings of
# the 2026-09-14 store: zero differ.
_naming_words = naming_words


def _grounded_span(claimed: object, source_text: str, sub_term_text: str) -> Optional[str]:
    """The fragment of the protocol line that names this sub-term, or None.

    The prompt ASKS the model to copy the naming fragment verbatim. This function is
    what makes the answer worth anything: the model's own account of where a term came
    from is exactly what cannot be taken on trust here, since ``stated: true`` on an
    invented analyte is indistinguishable from the truth. Two gates, and a span has to
    pass both:

    1. **Really present in the line**, under :func:`_comparison_form`. Not a fuzzy
       match: fuzz is how an invention scores as a reading.
    2. **Shares a naming word with the sub-term it claims to name.**

    Gate 2 is not belt-and-braces; gate 1 alone is insufficient, and CAROLINA is the
    case that shows it. Asked for a span off ``acute liver disease or impaired hepatic
    function``, the model returned ``impaired hepatic function`` for an *ALT* sub-term.
    That span is a perfectly real substring -- it passes gate 1 -- and it names the
    umbrella, not the analyte. Since every elaborated member can cite the umbrella it
    was elaborated FROM, gate 1 alone would let the whole failure through wearing a
    grounding mark, which is worse than no mark at all. Gate 2 refuses it: the span
    shares no word with "Alanine aminotransferase (ALT) elevation".

    Gate 2 also subsumes the operand case. ``> 2X ULN`` is a real substring of a line
    that states a threshold and names nothing; it shares no word with the analyte. (The
    obvious alternative, :func:`~src.agents.agent1.threshold_classifier.is_headless`,
    does NOT catch it -- measured: it returns False, because ``ULN`` is not a unit
    ``normalize_unit`` recognises.)

    Known and deliberate false negative: a line that names the sub-term by a synonym
    the sub-term does not repeat -- ``SGPT`` decomposed into ``Alanine
    aminotransferase`` -- shares no word and is marked elaboration though it is really
    a reading. The asymmetry is the right way round. An under-credited reading loses
    nothing, because the sub-term is kept either way; an over-credited elaboration is
    the defect being fixed.

    Never raises, and never drops a sub-term. Failing both gates marks the member as
    the model's own; refusing it outright would delete a criterion the pipeline exists
    to recover.
    """
    # `sub_term_text` is deliberately not optional. Defaulted to "", gate 2 would refuse
    # every span, so a caller that forgot the argument would silently mark every member
    # as elaboration -- and a marking that says "all elaboration" reads exactly like one
    # that is working.
    if not isinstance(claimed, str):
        return None
    span = claimed.strip()
    if not span or span.lower() in {"null", "none", "nil"}:
        return None
    if not source_text:
        return None
    if _comparison_form(span) not in _comparison_form(source_text):
        return None
    span_words = _naming_words(span)
    if not span_words or not (span_words & _naming_words(sub_term_text)):
        return None
    return span


class CriteriaPlanner:
    """
    Agent 1.5: Analyzes each criterion from Agent 1's IR output and
    decomposes composite/umbrella terms into specific sub-criteria.
    
    Pipeline: Agent 1 → [Planner] → Agent 2
    """
    
    def __init__(self, model_name: Optional[str] = None):
        self.llm = get_llm(model_name=model_name, temperature=0.0, json_mode=True)
    
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
        # Fail-open on missing source_text (plan-audit D14): a pre-this-field
        # study has source_text=None. Pass an empty string rather than falling
        # back to entity_text, which ir.py documents as normalized and capable
        # of having already lost the threshold entirely — grounding the LLM in
        # text that structurally cannot carry the constraint would silently
        # reintroduce the ungrounded-guess hazard this grounding fix exists to
        # close. An empty Source Text resolves to value_constraint_text: null
        # via the prompt's own instruction, which REQ-007 then turns into None.
        prompt = DECOMPOSITION_PROMPT.format(
            name=criterion.name,
            entity_text=criterion.entity_text,
            domain=criterion.domain,
            logic_type=criterion.logic_type,
            source_text=criterion.source_text or ""
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
                    # REQ-004/REQ-005: a sub-criterion's value_constraint is
                    # determined from its OWN text (the grounding requirement
                    # above), never unconditionally copied from the parent
                    # (decomposer.py:107, pre-fix). REQ-007 fail-open: any
                    # missing field, unparseable phrase, or unexpected error
                    # here leaves value_constraint as None — never the
                    # parent's (possibly wrong) value, never a raised
                    # exception that aborts the whole decomposition.
                    value_constraint = None
                    try:
                        raw_text = sc_data.get("value_constraint_text")
                        if raw_text:
                            value_constraint = parse_value_constraint(raw_text)
                    except Exception as vc_exc:
                        print(f"  ⚠ value_constraint parse failed for "
                              f"{sc_data.get('entity_text', '')!r}: {vc_exc}")
                        value_constraint = None

                    sc = Criteria(
                        name=sc_data.get("name", "Unnamed"),
                        domain=sc_data.get("domain", criterion.domain),
                        entity_text=sc_data.get("entity_text", ""),
                        logic_type=criterion.logic_type,  # Inherit parent's logic
                        window=criterion.window,  # Inherit parent's window
                        # Inherit the parent's protocol line. A sub-criterion is a
                        # reading OF the parent's line, so the line is its provenance
                        # too -- and these members are precisely where a
                        # line-to-criterion cardinality is worth reading, since this
                        # is the hop that turns one line into several criteria.
                        # Leaving it None meant every decomposed member reached the
                        # store carrying no line at all: CAROLINA's stored
                        # "Elevated Bilirubin" and "Coagulopathy (e.g., elevated INR)"
                        # members are this shape, and appear in no recorded Agent 1
                        # cache because the planner, not Agent 1, invented them.
                        #
                        # This carries provenance across the hop and decides nothing:
                        # not what is decomposed, not the prompt, and not the member's
                        # own `value_constraint`, which REQ-004/REQ-005 require be
                        # grounded in the member's OWN text and which is still parsed
                        # from `value_constraint_text` above, never inherited.
                        source_text=criterion.source_text,
                        # Which part of that line this member actually reads -- None
                        # when the line names it nowhere and the member is the model's
                        # own contribution. Verified here rather than believed: see
                        # `_grounded_span`.
                        source_span=_grounded_span(
                            sc_data.get("source_span"),
                            criterion.source_text or "",
                            # Both, because the naming word can live in either: the
                            # line says "Total Bilirubin" while the sub-term is named
                            # "Elevated Bilirubin" and its entity text is "Total
                            # bilirubin elevation".
                            f"{sc_data.get('entity_text', '')} {sc_data.get('name', '')}",
                        ),
                        value_constraint=value_constraint,
                    )
                    sub_criteria.append(sc)
                
                criterion.sub_criteria = sub_criteria
                # De Morgan: negating a disjunction distributes as a conjunction.
                # "cardiovascular disease" (PRESENCE) → any sub-term qualifies → ANY.
                # "no drug abuse" (ABSENCE) → alcohol AND opioid AND cannabis must all
                # be absent → ALL. Using ANY here would let one absent sub-term pass the
                # whole exclusion, silently admitting patients the protocol excludes.
                criterion.group_type = "ALL" if criterion.logic_type == "ABSENCE" else "ANY"

                # Say how many members the protocol line named and how many the model
                # supplied. The counts are printed rather than derived later because a
                # run whose every member is elaboration looks, in the store, exactly
                # like a run that read a line naming all of them -- which is the
                # confusion `source_span` exists to end. Naming it in the log too costs
                # one line and makes the elaboration visible while the run is watched,
                # not only afterwards.
                named = sum(1 for sc in sub_criteria if sc.source_span)
                print(f"  ✂ '{criterion.entity_text}' → "
                      f"{len(sub_criteria)} sub-criteria ({criterion.logic_type}"
                      f"/{criterion.group_type}; {named} named by the line, "
                      f"{len(sub_criteria) - named} supplied by the model): "
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
