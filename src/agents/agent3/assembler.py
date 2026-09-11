"""
Agent 3 (Cohort Assembler) - Circe-be JSON Builder.
Assembles ARTEMIS IR + Registry ConceptSets into ATLAS-compatible Circe JSON.
"""
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from src.models.ir import (
    ARTEMISRequest, CohortDefinition, Criteria, PrimaryCriteria, 
    CohortOutcome, TemporalWindow,
    ExitStrategy, CustomEraConfig
)
from src.registry.models import RegisteredConceptSet
from src.agents.agent3.mappings import (
    DOMAIN_TO_CRITERIA_TYPE, DOMAIN_TO_PRIMARY_CRITERIA_TYPE,
    OPERATOR_MAP, OCCURRENCE_TYPE, DEMOGRAPHIC_KEYWORDS
)
from src.services.value_constraint import (
    build_measurement_value_filter,
    resolve_group_member_constraint,
)
from src.utils.circe_lint import default_criterion_window, unreadable_value_attributes
import logging
import copy

logger = logging.getLogger(__name__)

# Toggle disease-based PrimaryCriteria design.
# When True AND the IR target has domain="Drug", the assembler builds:
#   Target:     PrimaryCriteria = disease condition (from first Condition inclusion rule)
#   Treatment:  same as Target + DrugEra PRESENCE for the treatment drug
#   Comparator: same as Target + DrugEra ABSENCE  for the treatment drug
# When False, the existing drug-based PrimaryCriteria behaviour is preserved.
USE_DISEASE_BASED_PRIMARY = True


@dataclass
class HealAction:
    """Records a self-heal decision made during assembly."""
    action: str   # "KEEP" | "PARTIAL" | "SKIP"
    rule_name: str
    entity_text: str
    reason: str
    entity_key: Optional[str] = None  # Stable identity for selective retry


@dataclass
class AssemblyResult:
    """Result of cohort assembly, including explicit failure report."""
    circe_json: Dict[str, Any]
    comparator_circe_json: Optional[Dict[str, Any]] = None
    treatment_circe_json: Optional[Dict[str, Any]] = None
    heal_log: List[HealAction] = field(default_factory=list)

    @property
    def failed_entities(self) -> List[str]:
        """Entity texts of rules that were fully skipped."""
        return [h.entity_text for h in self.heal_log if h.action == "SKIP"]

    @property
    def has_failures(self) -> bool:
        """True if any rule was fully skipped due to missing concepts."""
        return any(h.action == "SKIP" for h in self.heal_log)


class CohortAssembler:
    """
    Agent 3: Assembles ARTEMIS IR into Circe-be JSON format.
    """
    
    def __init__(self):
        self.concept_set_counter = 0
    
    def assemble(
        self, 
        ir: ARTEMISRequest, 
        concept_sets: List[RegisteredConceptSet]
    ) -> AssemblyResult:
        """
        Assemble full Circe-be JSON from IR and resolved ConceptSets.
        
        Args:
            ir: ARTEMISRequest with target/comparator/outcome definitions
            concept_sets: List of resolved ConceptSets from registry
            
        Returns:
            AssemblyResult with circe_json and heal_log
        """
        # Build ConceptSet definitions
        circe_concept_sets = self._build_concept_sets(concept_sets)

        # Disease-based primary criteria path: when the IR target uses a Drug
        # domain, swap PrimaryCriteria to the first Condition inclusion rule
        # and build Treatment (drug PRESENCE) / Comparator (drug ABSENCE).
        if (
            USE_DISEASE_BASED_PRIMARY
            and ir.target.primary_criteria.domain == "Drug"
        ):
            return self._assemble_disease_based(ir, concept_sets, circe_concept_sets)

        # --- Legacy drug-based PrimaryCriteria path ---
        # Build cohort definition for target
        target_cohort, heal_log = self._build_cohort_definition(
            ir.target, concept_sets, "Target Cohort"
        )

        circe_json = {
            "ConceptSets": circe_concept_sets,
            "PrimaryCriteria": target_cohort["PrimaryCriteria"],
            "AdditionalCriteria": target_cohort.get("AdditionalCriteria"),
            "QualifiedLimit": {"Type": "First"},
            "ExpressionLimit": {"Type": "First"},
            "InclusionRules": target_cohort.get("InclusionRules", []),
            "EndStrategy": self._build_end_strategy(ir.target.exit_strategy),
            "CensoringCriteria": [],
            "CollapseSettings": {
                "CollapseType": "ERA",
                "EraPad": 0
            },
            "CdmVersionRange": ""
        }

        # Build comparator cohort (same inclusion rules, different primary criteria)
        comparator_circe_json = None
        if ir.comparator and ir.comparator.primary_criteria.entity_text:
            comparator_cohort, comp_heal = self._build_cohort_definition(
                ir.comparator, concept_sets, "Comparator Cohort"
            )
            comparator_circe_json = {
                "ConceptSets": circe_concept_sets,
                "PrimaryCriteria": comparator_cohort["PrimaryCriteria"],
                "AdditionalCriteria": comparator_cohort.get("AdditionalCriteria"),
                "QualifiedLimit": {"Type": "First"},
                "ExpressionLimit": {"Type": "First"},
                "InclusionRules": comparator_cohort.get("InclusionRules", []),
                "EndStrategy": self._build_end_strategy(
                    ir.comparator.exit_strategy if hasattr(ir.comparator, 'exit_strategy') else None
                ),
                "CensoringCriteria": [],
                "CollapseSettings": {
                    "CollapseType": "ERA",
                    "EraPad": 0
                },
                "CdmVersionRange": ""
            }
            heal_log.extend(comp_heal)
            logger.info("[Agent3] Comparator cohort assembled")

        return AssemblyResult(
            circe_json=circe_json,
            comparator_circe_json=comparator_circe_json,
            heal_log=heal_log,
        )

    def _assemble_disease_based(
        self,
        ir: ARTEMISRequest,
        concept_sets: List[RegisteredConceptSet],
        circe_concept_sets: List[Dict[str, Any]],
    ) -> AssemblyResult:
        """Assemble using disease-based PrimaryCriteria.

        Target  = disease condition PrimaryCriteria + original inclusion rules
        Treatment  = Target + DrugEra PRESENCE for the treatment drug
        Comparator = Target + DrugEra ABSENCE  for the treatment drug
        """
        drug_pc = ir.target.primary_criteria
        drug_entity_text = drug_pc.entity_text
        drug_cs_id = self._find_concept_set_id(drug_entity_text, concept_sets)

        # Find the first Condition-domain inclusion rule to use as PrimaryCriteria
        disease_rule = self._find_first_condition_inclusion(ir.target)
        if disease_rule is None:
            logger.warning(
                "[Agent3] Disease-based mode: no Condition inclusion rule found, "
                "falling back to drug-based PrimaryCriteria"
            )
            # Fall back to legacy path by recursing with flag disabled
            target_cohort, heal_log = self._build_cohort_definition(
                ir.target, concept_sets, "Target Cohort"
            )
            return AssemblyResult(
                circe_json=self._wrap_cohort_json(
                    circe_concept_sets, target_cohort,
                    self._build_end_strategy(ir.target.exit_strategy),
                ),
                heal_log=heal_log,
            )

        disease_entity_text = disease_rule.entity_text
        disease_cs_id = self._find_concept_set_id(disease_entity_text, concept_sets)

        # Build disease-based PrimaryCriteria
        disease_primary = {
            "CriteriaList": [
                {"ConditionOccurrence": {"CodesetId": disease_cs_id, "First": True}}
            ],
            "ObservationWindow": {
                "PriorDays": drug_pc.observation_window.get("prior", 365) if drug_pc.observation_window else 365,
                "PostDays": drug_pc.observation_window.get("post", 0) if drug_pc.observation_window else 0,
            },
            "PrimaryCriteriaLimit": {"Type": "First"},
        }

        # Build inclusion rules, excluding the condition rule we promoted
        target_cohort, heal_log = self._build_cohort_definition(
            ir.target, concept_sets, "Target Cohort"
        )
        target_inclusion_rules = [
            rule for rule in target_cohort.get("InclusionRules", [])
            if not self._rule_matches_entity(rule, disease_entity_text)
        ]

        end_strategy = self._build_end_strategy(ir.target.exit_strategy)

        # --- Target cohort ---
        target_json = {
            "ConceptSets": circe_concept_sets,
            "PrimaryCriteria": copy.deepcopy(disease_primary),
            "AdditionalCriteria": target_cohort.get("AdditionalCriteria"),
            "QualifiedLimit": {"Type": "First"},
            "ExpressionLimit": {"Type": "First"},
            "InclusionRules": copy.deepcopy(target_inclusion_rules),
            "EndStrategy": end_strategy,
            "CensoringCriteria": [],
            "CollapseSettings": {"CollapseType": "ERA", "EraPad": 0},
            "CdmVersionRange": "",
        }

        # Drug rule template for Treatment / Comparator.
        #
        # The 9999 below is NOT the criterion-window default `_start_window` resolves
        # from `circe_lint.DEFAULT_WINDOW_START_DAYS_BY_DOMAIN`, and must not be routed
        # through it. This rule asks "was this patient ever on the arm's drug", which
        # is what assigns a patient to an arm; a per-domain lookback would turn it into
        # "was on it within the last year" and silently move patients between arms.
        # Same number, different decision -- it has no null-window branch to default.
        drug_presence_rule = {
            "name": drug_entity_text or "Treatment drug",
            "expression": {
                "Type": "ALL",
                "CriteriaList": [
                    {
                        "Criteria": {"DrugEra": {"CodesetId": drug_cs_id}},
                        "StartWindow": {
                            "Start": {"Days": 9999, "Coeff": -1},
                            "End": {"Days": 0, "Coeff": 1},
                        },
                        "RestrictVisit": False,
                        "IgnoreObservationPeriod": False,
                        "Occurrence": {"Type": 2, "Count": 1},  # at least 1
                    }
                ],
                "DemographicCriteriaList": [],
                "Groups": [],
            },
        }
        drug_absence_rule = copy.deepcopy(drug_presence_rule)
        drug_absence_rule["name"] = f"No {drug_entity_text or 'treatment drug'}"
        drug_absence_rule["expression"]["CriteriaList"][0]["Occurrence"] = {
            "Type": 0, "Count": 0,  # exactly 0
        }

        # --- Treatment cohort = Target + drug PRESENCE ---
        treatment_json = copy.deepcopy(target_json)
        treatment_json["InclusionRules"] = (
            copy.deepcopy(target_inclusion_rules) + [copy.deepcopy(drug_presence_rule)]
        )

        # --- Comparator cohort = Target + drug ABSENCE ---
        comparator_json = copy.deepcopy(target_json)
        comparator_json["InclusionRules"] = (
            copy.deepcopy(target_inclusion_rules) + [copy.deepcopy(drug_absence_rule)]
        )

        logger.info(
            "[Agent3] Disease-based assembly: Target(disease=%s), "
            "Treatment(+drug PRESENCE %s), Comparator(+drug ABSENCE %s)",
            disease_entity_text, drug_entity_text, drug_entity_text,
        )
        return AssemblyResult(
            circe_json=target_json,
            treatment_circe_json=treatment_json,
            comparator_circe_json=comparator_json,
            heal_log=heal_log,
        )

    @staticmethod
    def _find_first_condition_inclusion(cohort: CohortDefinition) -> Optional[Criteria]:
        """Find the first Condition-domain inclusion rule in a cohort definition."""
        for rule in cohort.inclusion_rules:
            if rule.domain and rule.domain.lower() == "condition":
                return rule
        return None

    @staticmethod
    def _rule_matches_entity(built_rule: Dict[str, Any], entity_text: Optional[str]) -> bool:
        """Check whether a built inclusion rule originated from a given entity_text."""
        if not entity_text:
            return False
        rule_name = (built_rule.get("name") or "").strip().lower()
        return rule_name == entity_text.strip().lower()

    @staticmethod
    def _wrap_cohort_json(
        concept_sets: List[Dict[str, Any]],
        cohort: Dict[str, Any],
        end_strategy: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Wrap a _build_cohort_definition result into a full CIRCE JSON."""
        return {
            "ConceptSets": concept_sets,
            "PrimaryCriteria": cohort["PrimaryCriteria"],
            "AdditionalCriteria": cohort.get("AdditionalCriteria"),
            "QualifiedLimit": {"Type": "First"},
            "ExpressionLimit": {"Type": "First"},
            "InclusionRules": cohort.get("InclusionRules", []),
            "EndStrategy": end_strategy,
            "CensoringCriteria": [],
            "CollapseSettings": {"CollapseType": "ERA", "EraPad": 0},
            "CdmVersionRange": "",
        }
    
    def _build_concept_sets(
        self, 
        concept_sets: List[RegisteredConceptSet]
    ) -> List[Dict[str, Any]]:
        """Build Circe ConceptSet definitions."""
        result = []
        for cs in concept_sets:
            items = []
            for concept in cs.concepts:
                items.append({
                    "concept": {
                        "CONCEPT_ID": concept.concept_id,
                        "CONCEPT_NAME": concept.concept_name,
                        "DOMAIN_ID": concept.domain_id,
                        "VOCABULARY_ID": concept.vocabulary_id,
                        "CONCEPT_CLASS_ID": concept.concept_class_id,
                        "STANDARD_CONCEPT": concept.standard_concept,
                        "CONCEPT_CODE": "",
                        "INVALID_REASON": None,
                        "INVALID_REASON_CAPTION": None,
                        "STANDARD_CONCEPT_CAPTION": "Standard"
                    },
                    "includeDescendants": concept.include_descendants,
                    "isExcluded": concept.is_excluded,
                    "includeMapped": True
                })
            
            result.append({
                "id": cs.id,
                "name": cs.name,
                "expression": {"items": items}
            })
        
        return result
    
    def _build_cohort_definition(
        self,
        cohort: CohortDefinition,
        concept_sets: List[RegisteredConceptSet],
        name: str
    ) -> Tuple[Dict[str, Any], List[HealAction]]:
        """Build cohort definition structure with explicit failure tracking.
        
        Returns:
            Tuple of (cohort_dict, heal_log) where heal_log records
            every rule's validation outcome.
        """
        # Primary Criteria
        primary = self._build_primary_criteria(cohort.primary_criteria, concept_sets)
        
        # Inclusion Rules (from inclusion_rules)
        inclusion_rules = []
        heal_log: List[HealAction] = []
        
        for i, rule in enumerate(cohort.inclusion_rules):
            # Skip conditional criteria (subgroup-gated rules like "females must have pregnancy test")
            if rule.conditional:
                heal_log.append(HealAction(action="SKIP", rule_name=rule.name, entity_text=rule.entity_text or "", reason="conditional criterion skipped"))
                continue
            built = self._build_inclusion_rule(rule, concept_sets, i)
            action = self._validate_and_heal(
                built, rule.name, rule.entity_text or ""
            )
            heal_log.append(action)
            if action.action != "SKIP":
                inclusion_rules.append(built)

        # Exclusion Rules (convert to inclusion with ABSENCE logic)
        for i, rule in enumerate(cohort.exclusion_rules):
            # Skip conditional criteria
            if rule.conditional:
                heal_log.append(HealAction(action="SKIP", rule_name=rule.name, entity_text=rule.entity_text or "", reason="conditional criterion skipped"))
                continue
            exclusion_as_inclusion = self._build_inclusion_rule(
                rule, concept_sets, len(inclusion_rules) + i, is_exclusion=True
            )
            action = self._validate_and_heal(
                exclusion_as_inclusion, rule.name, rule.entity_text or ""
            )
            heal_log.append(action)
            if action.action != "SKIP":
                inclusion_rules.append(exclusion_as_inclusion)
        
        return {
            "PrimaryCriteria": primary,
            "InclusionRules": inclusion_rules
        }, heal_log
    
    def _build_primary_criteria(
        self,
        pc: PrimaryCriteria,
        concept_sets: List[RegisteredConceptSet]
    ) -> Dict[str, Any]:
        """Build PrimaryCriteria structure."""
        # Find matching concept set
        cs_id = self._find_concept_set_id(pc.entity_text, concept_sets)
        
        criteria_type = DOMAIN_TO_PRIMARY_CRITERIA_TYPE.get(pc.domain, "ConditionOccurrence")
        
        criteria_content = {
            "CodesetId": cs_id,
            "First": pc.limit == "First"
        }
        
        return {
            "CriteriaList": [
                {criteria_type: criteria_content}
            ],
            "ObservationWindow": {
                "PriorDays": pc.observation_window.get("prior", 365) if pc.observation_window else 365,
                "PostDays": pc.observation_window.get("post", 0) if pc.observation_window else 0
            },
            "PrimaryCriteriaLimit": {"Type": "First" if pc.limit == "First" else "All"}
        }
    
    def _validate_and_heal(
        self, built_rule: Dict[str, Any], rule_name: str, entity_text: str
    ) -> HealAction:
        """Validate a built rule and return an explicit HealAction.
        
        Replaces the old _has_valid_criteria() which silently dropped rules.
        Now returns a structured record of the decision for pipeline-level
        feedback loop support (RFC-001 Loop 1).
        
        Returns:
            HealAction with action="KEEP", "PARTIAL", or "SKIP".
        """
        expr = built_rule.get("expression", {})
        criteria_list = expr.get("CriteriaList", [])
        demo_list = expr.get("DemographicCriteriaList", [])
        
        # Demographic-only rules are always valid
        if demo_list and not criteria_list:
            return HealAction("KEEP", rule_name, entity_text, "demographic-only")
        
        # Filter out criteria with CodesetId=0
        valid_criteria = []
        for crit_entry in criteria_list:
            crit_obj = crit_entry.get("Criteria", {})
            codeset_id = 0
            for domain_key, content in crit_obj.items():
                codeset_id = content.get("CodesetId", 0)
                break
            
            if codeset_id != 0:
                valid_criteria.append(crit_entry)
            else:
                logger.warning(
                    f"[Agent3] CodesetId=0 detected in rule '{rule_name}' — "
                    f"entity '{entity_text}'"
                )
        
        if not valid_criteria and not demo_list:
            logger.warning(
                f"[Agent3] SKIP rule '{rule_name}' — "
                f"no valid concept sets resolved"
            )
            return HealAction(
                "SKIP", rule_name, entity_text,
                "no valid concept sets resolved"
            )
        
        if len(valid_criteria) < len(criteria_list):
            # Partial heal: some sub-criteria removed
            removed_count = len(criteria_list) - len(valid_criteria)
            expr["CriteriaList"] = valid_criteria
            logger.info(
                f"[Agent3] PARTIAL heal for rule '{rule_name}' — "
                f"{removed_count} sub-criteria removed"
            )
            return HealAction(
                "PARTIAL", rule_name, entity_text,
                f"{removed_count} sub-criteria with CodesetId=0 removed"
            )
        
        # All criteria valid
        return HealAction("KEEP", rule_name, entity_text, "all criteria valid")

    @staticmethod
    def _is_demographic(domain: Optional[str], entity_text: Optional[str]) -> bool:
        """Check if this criteria should be a DemographicCriteria."""
        if domain and domain.lower() == "demographics":
            return True
        if entity_text:
            first_word = entity_text.strip().split()[0].lower() if entity_text.strip() else ""
            if first_word in DEMOGRAPHIC_KEYWORDS:
                return True
        return False

    @staticmethod
    def _offset_to_circe_window(offset_days: int) -> Dict[str, int]:
        """Convert IR offset (days relative to index) to Circe-be window element.
        
        Circe-be convention:
          - Days: always non-negative (magnitude)
          - Coeff: -1 = before index, +1 = after index
          - Effective position = Days * Coeff (negative = before, positive = after)
        
        Examples:
          offset=-365 → {"Days": 365, "Coeff": -1}  (365 days before)
          offset=0    → {"Days": 0,   "Coeff": 1}   (index date)
          offset=30   → {"Days": 30,  "Coeff": 1}   (30 days after)
        """
        if offset_days < 0:
            return {"Days": abs(offset_days), "Coeff": -1}
        elif offset_days > 0:
            return {"Days": offset_days, "Coeff": 1}
        else:
            return {"Days": 0, "Coeff": 1}
    
    def _start_window(self, rule: Criteria, domain: Optional[str]) -> Dict[str, Any]:
        """The ``StartWindow`` for one emitted criterion of ``rule``.

        A rule that carries its own window shares it across every criterion it emits:
        the protocol stated one time frame and it applies to the whole group.

        A rule that carries none takes its DOMAIN's documented lookback, from
        ``circe_lint.DEFAULT_WINDOW_START_DAYS_BY_DOMAIN`` -- the same table
        ``TTEService._build_seeded_target_circe`` reads and the same one
        ``agent1/prompts.py`` renders its four statements of these values from. Until
        2026-09-10 this builder answered a null window with a flat ``9999`` for every
        domain: it agreed with the table on Condition and Procedure and disagreed on
        Drug (365) and Measurement (180), so the same decision had two homes and this
        one won silently whenever the model omitted ``window`` -- which it does for 57
        of the 557 criteria in the cold-6 store, 10%, in nine of the ten studies.

        Both builders read one table because both consume IR from Agent 1, and all
        four Agent 1 prompts state these defaults to the model. A window the model was
        told to apply and did not is reconstructed here; it is not a second opinion
        about how long a lookback should be.

        ``domain`` is the domain of the criterion being emitted, not of the rule: a
        composite group's members carry their own, and one shared window would put one
        domain's default on another domain's member. An absent or unlisted domain
        takes ``DEFAULT_WINDOW_START_DAYS_UNLISTED_DOMAIN`` ("all prior history"), the
        only reading that cannot silently NARROW a criterion the protocol left
        unbounded -- and, being -9999, byte-identical to the literal that was here.

        The default arrives in the IR's own ``{"start", "end"}`` shape so it runs
        through ``_offset_to_circe_window`` like an extracted window does. There is one
        conversion, so a defaulted window cannot be converted differently from an
        extracted one.
        """
        if rule.window:
            start_days, end_days = rule.window.start, rule.window.end
        else:
            window, _source = default_criterion_window(domain)
            start_days, end_days = window["start"], window["end"]
        return self._validate_window({
            "Start": self._offset_to_circe_window(start_days),
            "End": self._offset_to_circe_window(end_days),
        })

    @staticmethod
    def _validate_window(window: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that StartWindow has Start <= End (temporally).
        
        If inverted (start after end), swap them and log a warning.
        """
        start_eff = window["Start"]["Days"] * window["Start"]["Coeff"]
        end_eff = window["End"]["Days"] * window["End"]["Coeff"]
        if start_eff > end_eff:
            logger.warning(
                f"[Agent3] Inverted time window detected: "
                f"start={start_eff} > end={end_eff}. Swapping."
            )
            window["Start"], window["End"] = window["End"], window["Start"]
        return window

    def _build_inclusion_rule(
        self,
        rule: Criteria,
        concept_sets: List[RegisteredConceptSet],
        index: int,
        is_exclusion: bool = False
    ) -> Dict[str, Any]:
        """Build an Inclusion Rule. Handles both atomic and composite criteria."""
        # Determine occurrence type
        if is_exclusion or rule.logic_type == "ABSENCE":
            occurrence = OCCURRENCE_TYPE["ABSENCE"]
        else:
            occurrence = OCCURRENCE_TYPE["PRESENCE"]
        
        # The temporal window is now resolved per EMITTED CRITERION rather than once
        # per rule, by `_start_window` below. A rule that carries a window still shares
        # it across every member (the protocol stated one time frame for the group); a
        # rule that does not takes each member's own domain default, so a mixed group
        # cannot put one domain's lookback on another domain's member.
        #
        # EndWindow intentionally omitted — Circe treats missing EndWindow as
        # unconstrained.  Previous {Days:0} required the condition to exist
        # on exactly the index date, which incorrectly filtered all patients.
        
        # Handle composite criteria (sub_criteria fan-out)
        if rule.sub_criteria:
            criteria_list = []
            demographic_list = []
            for sc in rule.sub_criteria:
                if self._is_demographic(sc.domain, sc.entity_text):
                    # Route to DemographicCriteriaList (Age, Gender, etc.)
                    demo_entry = self._build_demographic_criteria(sc)
                    demographic_list.append(demo_entry)
                else:
                    sc_cs_id = self._find_concept_set_id(sc.entity_text, concept_sets)
                    sc_criteria_type = DOMAIN_TO_CRITERIA_TYPE.get(sc.domain, "ConditionOccurrence")
                    sc_content: Dict[str, Any] = {"CodesetId": sc_cs_id}
                    # A threshold written once on the group label belongs to the
                    # members it can honestly measure. Reading `sc.value_constraint`
                    # alone dropped CAROLINA's "> 3x ULN" from ALT/AST/ALP entirely;
                    # copying it down blindly would put "> 240 mg/dL" on HbA1c, which
                    # matches zero rows -- so the member's own analyte text goes in
                    # too, and the same bound reaches the plasma glucoses beside it.
                    # `resolve_group_member_constraint` is the one place that decides,
                    # shared with `services/tte_service.py`.
                    resolution = resolve_group_member_constraint(
                        rule.value_constraint,
                        sc.value_constraint,
                        member_analyte=(
                            getattr(sc, "entity_text", None) or getattr(sc, "name", None)
                        ),
                    )
                    if resolution.refusal_reason:
                        # Logging it and emitting anyway was the defect: an unfiltered
                        # occurrence inside an ABSENCE rule is "exclude anyone with any
                        # result at all", which is strictly broader than the threshold
                        # the protocol wrote and silently drops patients the study
                        # required. The member is NOT emitted -- the same refusal
                        # channel `sc_unreadable` uses below: a member that cannot be
                        # emitted honestly is left out, and a rule left with no criteria
                        # is SKIPped by `_validate_and_heal`. Raising is wrong here; the
                        # store row this assembler reads must survive so the threshold
                        # can be re-grounded per sub-criterion at extraction.
                        logger.warning(
                            "[Agent3] %s: group %r carries %s %s %s and it is NOT applied "
                            "to member %r -- %s. Applying it anyway would match zero rows, "
                            "so the member is NOT emitted; ground the threshold per "
                            "sub-criterion at extraction to recover it.",
                            resolution.refusal_reason,
                            rule.name,
                            rule.value_constraint.op,
                            rule.value_constraint.value,
                            rule.value_constraint.unit_text or "(no unit)",
                            sc.name,
                            resolution.refusal_explanation,
                        )
                        continue
                    # Flat merge: Unit is a sibling of ValueAsNumber in Circe.
                    sc_value_filter = build_measurement_value_filter(resolution.constraint)
                    # ...but only onto a criteria type whose CDM table reads those
                    # keys. Circe silently ignores an unreadable one, so the member
                    # would match every occurrence of its concept set while reading
                    # as filtered. Skipping it is this builder's own refusal channel:
                    # a member that contributes nothing is left out, and a rule left
                    # with no criteria is SKIPped by `_validate_and_heal`.
                    sc_unreadable = unreadable_value_attributes(
                        sc_criteria_type, sc_value_filter
                    )
                    if sc_unreadable:
                        logger.warning(
                            "[Agent3] %s: member %r is a %s, which cannot read %s, so "
                            "its value condition would be dropped by Circe and the "
                            "member would match every occurrence of its concept set. "
                            "The member is NOT emitted; map it to a criteria type that "
                            "reads the constraint to recover it.",
                            rule.name, sc.name, sc_criteria_type,
                            ", ".join(sc_unreadable),
                        )
                        continue
                    sc_content.update(sc_value_filter)
                    criteria_list.append({
                        "Criteria": {sc_criteria_type: sc_content},
                        "StartWindow": self._start_window(rule, sc.domain),
                        "RestrictVisit": False,
                        "IgnoreObservationPeriod": False,
                        "Occurrence": occurrence
                    })
            return {
                "name": rule.name,
                "expression": {
                    "Type": rule.group_type,
                    "CriteriaList": criteria_list,
                    "DemographicCriteriaList": demographic_list,
                    "Groups": []
                }
            }
        
        # Atomic criteria — check if demographic
        if self._is_demographic(rule.domain, rule.entity_text):
            demo_entry = self._build_demographic_criteria(rule)
            return {
                "name": rule.name,
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [],
                    "DemographicCriteriaList": [demo_entry],
                    "Groups": []
                }
            }
        
        # Atomic criteria (no sub_criteria) — standard logic
        cs_id = self._find_concept_set_id(rule.entity_text, concept_sets)
        criteria_type = DOMAIN_TO_CRITERIA_TYPE.get(rule.domain, "ConditionOccurrence")
        criteria_content: Dict[str, Any] = {"CodesetId": cs_id}
        value_filter = build_measurement_value_filter(rule.value_constraint)
        # Same gate as the composite branch above, at the second of this module's two
        # merge sites. An atomic rule has nothing left once its only criterion is
        # refused, so it is returned with an empty CriteriaList and `_validate_and_heal`
        # records the SKIP -- reusing this assembler's refusal ledger rather than
        # raising past it.
        unreadable = unreadable_value_attributes(criteria_type, value_filter)
        if unreadable:
            logger.warning(
                "[Agent3] SKIP rule '%s' — %s cannot read %s, so its value condition "
                "would be dropped by Circe and the rule would match every occurrence "
                "of its concept set",
                rule.name, criteria_type, ", ".join(unreadable),
            )
            return {
                "name": rule.name,
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        criteria_content.update(value_filter)

        return {
            "name": rule.name,
            "expression": {
                "Type": "ALL",
                "CriteriaList": [
                    {
                        "Criteria": {criteria_type: criteria_content},
                        "StartWindow": self._start_window(rule, rule.domain),
                        "RestrictVisit": False,
                        "IgnoreObservationPeriod": False,
                        "Occurrence": occurrence
                    }
                ],
                "DemographicCriteriaList": [],
                "Groups": []
            }
        }
    
    def _build_end_strategy(
        self, strategy: Union[str, ExitStrategy]
    ) -> Optional[Dict[str, Any]]:
        """Build cohort end strategy. Supports str (backward compat) and ExitStrategy."""
        # Handle ExitStrategy model
        if isinstance(strategy, ExitStrategy):
            if strategy.strategy_type == "OBSERVATION_END":
                return None
            elif strategy.strategy_type == "FIXED_DURATION":
                return {
                    "DateOffset": {
                        "DateField": "StartDate",
                        "Offset": strategy.date_offset_days or 365
                    }
                }
            elif strategy.strategy_type == "CUSTOM_ERA" and strategy.custom_era:
                return {
                    "CustomEra": {
                        "DrugCodesetId": strategy.custom_era.drug_codeset_id,
                        "GapDays": strategy.custom_era.gap_days,
                        "Offset": strategy.custom_era.offset
                    }
                }
            return None
        
        # Handle legacy string format (backward compat)
        if strategy == "OBSERVATION_END":
            return None
        elif strategy == "FIXED_DURATION":
            return {
                "DateOffset": {
                    "DateField": "StartDate",
                    "Offset": 365
                }
            }
        return None
    
    def _build_demographic_criteria(self, rule: Criteria) -> Dict[str, Any]:
        """Build a DemographicCriteria entry for age/gender rules."""
        entry: Dict[str, Any] = {}
        entity = (rule.entity_text or "").lower()
        
        # Age constraint
        if "age" in entity and rule.value_constraint:
            vc = rule.value_constraint
            op = OPERATOR_MAP.get(vc.op, "gte")
            entry["Age"] = {
                "Value": vc.value,
                "Op": op
            }
            # An inclusive range's upper bound. CIRCE's Age NumericRange reads it as
            # `Extent`; emitting `{"Value": 40, "Op": "bt"}` alone is a half-written
            # node on a rule that reads as fully translated.
            if op == "bt" and vc.value_high is not None:
                entry["Age"]["Extent"] = vc.value_high
        
        # Gender constraint
        if "gender" in entity or "sex" in entity:
            from src.agents.agent3.mappings import GENDER_MAP
            for key, concept_id in GENDER_MAP.items():
                if key.lower() in entity:
                    entry["Gender"] = [{"CONCEPT_ID": concept_id}]
                    break
        
        return entry

    def _find_concept_set_id(
        self, 
        entity_text: Optional[str],
        concept_sets: List[RegisteredConceptSet]
    ) -> int:
        """Find ConceptSet ID by source entity text with fuzzy matching."""
        if not entity_text:
            return 0
        
        query = entity_text.lower().strip()
        
        # Pass 1: Exact match on source_entity_text or name
        for cs in concept_sets:
            if cs.source_entity_text == entity_text:
                return cs.id
            if cs.name.lower() == query:
                return cs.id
        
        # Pass 2: Substring/contains match (handles plurals, minor differences)
        best_match = None
        best_score = 0
        for cs in concept_sets:
            cs_name = cs.name.lower()
            cs_src = (cs.source_entity_text or "").lower()
            # Check if query is contained in name or vice versa
            if query in cs_name or cs_name in query:
                score = len(set(query.split()) & set(cs_name.split()))
                if score > best_score:
                    best_score = score
                    best_match = cs
            elif query in cs_src or cs_src in query:
                score = len(set(query.split()) & set(cs_src.split()))
                if score > best_score:
                    best_score = score
                    best_match = cs
        
        if best_match:
            logger.info(f"[Agent3] Fuzzy matched '{entity_text}' → '{best_match.name}' (id={best_match.id})")
            return best_match.id
        
        # Fallback: log warning and return 0
        logger.warning(f"[Agent3] No ConceptSet found for entity '{entity_text}' — CodesetId=0")
        return 0


# Singleton instance
agent3 = CohortAssembler()
