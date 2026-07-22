"""
Agent 4 (Validator) - Circe JSON Validation.
Validates JSON structure, ConceptSet references, and OHDSI compatibility.
"""
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel
import json

from src.registry.store import registry


class ValidationError(BaseModel):
    """A single validation error."""
    field: str
    message: str
    severity: str  # "error" or "warning"


class ValidationResult(BaseModel):
    """Result of validation."""
    valid: bool
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []
    concept_set_count: int = 0
    inclusion_rule_count: int = 0


class CirCeValidator:
    """
    Agent 4: Validates Circe-be JSON for ATLAS compatibility.
    """
    
    REQUIRED_TOP_LEVEL = ["ConceptSets", "PrimaryCriteria"]
    REQUIRED_CONCEPT_SET_FIELDS = ["id", "name", "expression"]
    
    def validate(self, circe_json: Dict[str, Any]) -> ValidationResult:
        """
        Validate a Circe-be JSON structure.
        
        Args:
            circe_json: The JSON object to validate
            
        Returns:
            ValidationResult with errors and warnings
        """
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []
        
        # 1. Schema Validation
        schema_errors = self._validate_schema(circe_json)
        errors.extend(schema_errors)
        
        # 2. ConceptSet Validation
        cs_errors, cs_warnings = self._validate_concept_sets(circe_json)
        errors.extend(cs_errors)
        warnings.extend(cs_warnings)
        
        # 3. Reference Integrity
        ref_errors = self._validate_references(circe_json)
        errors.extend(ref_errors)
        
        # 4. Semantic Validation (NEW: CodesetId=0, domain consistency, empty criteria)
        sem_errors, sem_warnings = self._validate_semantic(circe_json)
        errors.extend(sem_errors)
        warnings.extend(sem_warnings)
        
        # 5. Registry Integrity (check if ConceptSets exist in registry)
        registry_warnings = self._validate_registry_integrity(circe_json)
        warnings.extend(registry_warnings)
        
        # Gather stats
        concept_sets = circe_json.get("ConceptSets", [])
        inclusion_rules = circe_json.get("InclusionRules", [])
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            concept_set_count=len(concept_sets),
            inclusion_rule_count=len(inclusion_rules)
        )
    
    def _validate_schema(self, data: Dict[str, Any]) -> List[ValidationError]:
        """Validate required top-level fields."""
        errors = []
        
        for field in self.REQUIRED_TOP_LEVEL:
            if field not in data:
                errors.append(ValidationError(
                    field=field,
                    message=f"Required field '{field}' is missing",
                    severity="error"
                ))
        
        # Validate PrimaryCriteria structure
        if "PrimaryCriteria" in data:
            pc = data["PrimaryCriteria"]
            if "CriteriaList" not in pc:
                errors.append(ValidationError(
                    field="PrimaryCriteria.CriteriaList",
                    message="PrimaryCriteria must have CriteriaList",
                    severity="error"
                ))
            elif len(pc.get("CriteriaList", [])) == 0:
                errors.append(ValidationError(
                    field="PrimaryCriteria.CriteriaList",
                    message="CriteriaList must not be empty",
                    severity="error"
                ))
        
        return errors
    
    def _validate_concept_sets(
        self, 
        data: Dict[str, Any]
    ) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate ConceptSet definitions."""
        errors = []
        warnings = []
        
        concept_sets = data.get("ConceptSets", [])
        seen_ids = set()
        
        for i, cs in enumerate(concept_sets):
            # Check required fields
            for field in self.REQUIRED_CONCEPT_SET_FIELDS:
                if field not in cs:
                    errors.append(ValidationError(
                        field=f"ConceptSets[{i}].{field}",
                        message=f"ConceptSet missing required field '{field}'",
                        severity="error"
                    ))
            
            # Check for duplicate IDs
            cs_id = cs.get("id")
            if cs_id in seen_ids:
                errors.append(ValidationError(
                    field=f"ConceptSets[{i}].id",
                    message=f"Duplicate ConceptSet ID: {cs_id}",
                    severity="error"
                ))
            seen_ids.add(cs_id)
            
            # Check expression has items
            expression = cs.get("expression", {})
            items = expression.get("items", [])
            if len(items) == 0:
                warnings.append(ValidationError(
                    field=f"ConceptSets[{i}].expression.items",
                    message=f"ConceptSet '{cs.get('name', '')}' has no items",
                    severity="warning"
                ))
        
        return errors, warnings
    
    def _validate_references(self, data: Dict[str, Any]) -> List[ValidationError]:
        """Validate that all CodesetId references point to valid ConceptSets."""
        errors = []
        
        # Collect valid ConceptSet IDs
        valid_ids = {cs.get("id") for cs in data.get("ConceptSets", [])}
        
        # Check PrimaryCriteria
        pc = data.get("PrimaryCriteria", {})
        for criteria in pc.get("CriteriaList", []):
            for domain_type, domain_data in criteria.items():
                if isinstance(domain_data, dict):
                    codeset_id = domain_data.get("CodesetId")
                    if codeset_id is not None and codeset_id not in valid_ids:
                        errors.append(ValidationError(
                            field="PrimaryCriteria.CodesetId",
                            message=f"Referenced CodesetId {codeset_id} not found in ConceptSets",
                            severity="error"
                        ))
        
        # Check InclusionRules
        for i, rule in enumerate(data.get("InclusionRules", [])):
            expression = rule.get("expression", {})
            for j, criteria in enumerate(expression.get("CriteriaList", [])):
                criteria_obj = criteria.get("Criteria", {})
                for domain_type, domain_data in criteria_obj.items():
                    if isinstance(domain_data, dict):
                        codeset_id = domain_data.get("CodesetId")
                        if codeset_id is not None and codeset_id not in valid_ids:
                            errors.append(ValidationError(
                                field=f"InclusionRules[{i}].CodesetId",
                                message=f"Referenced CodesetId {codeset_id} not found",
                                severity="error"
                            ))
        
        return errors
    
    def _validate_semantic(
        self, 
        data: Dict[str, Any]
    ) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Semantic validation: CodesetId=0, domain consistency, empty criteria."""
        errors = []
        warnings = []
        
        DEMOGRAPHIC_NAMES = {"age", "gender", "sex", "race", "ethnicity"}
        
        # Scan all CodesetId references for unmapped (=0)
        def scan_codeset_zero(node: Any, path: str):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "CodesetId" and v == 0:
                        errors.append(ValidationError(
                            field=path,
                            message=f"Unmapped CodesetId=0 at {path} — concept set not linked",
                            severity="error"
                        ))
                    scan_codeset_zero(v, f"{path}.{k}" if path else k)
            elif isinstance(node, list):
                for i, item in enumerate(node):
                    scan_codeset_zero(item, f"{path}[{i}]")
        
        scan_codeset_zero(data, "")
        
        # Check domain consistency in InclusionRules
        for i, rule in enumerate(data.get("InclusionRules", [])):
            rule_name = rule.get("name", "").lower()
            expression = rule.get("expression", {})
            
            # Check if demographic-like rule is in CriteriaList instead of DemographicCriteriaList
            criteria_list = expression.get("CriteriaList", [])
            demo_list = expression.get("DemographicCriteriaList", [])
            
            first_word = rule_name.split()[0] if rule_name.split() else ""
            if first_word in DEMOGRAPHIC_NAMES and criteria_list and not demo_list:
                warnings.append(ValidationError(
                    field=f"InclusionRules[{i}]",
                    message=f"Rule '{rule.get('name', '')}' looks demographic but uses CriteriaList instead of DemographicCriteriaList",
                    severity="warning"
                ))
            
            # Check empty criteria (no CriteriaList, no DemographicCriteriaList, no Groups)
            groups = expression.get("Groups", [])
            if not criteria_list and not demo_list and not groups:
                errors.append(ValidationError(
                    field=f"InclusionRules[{i}].expression",
                    message=f"Rule '{rule.get('name', '')}' has no criteria at all",
                    severity="error"
                ))
        
        return errors, warnings
    
    def _validate_registry_integrity(
        self, 
        data: Dict[str, Any]
    ) -> List[ValidationError]:
        """Check if ConceptSets are registered in the global registry."""
        warnings = []
        
        for cs in data.get("ConceptSets", []):
            cs_id = cs.get("id")
            if cs_id and not registry.exists(cs_id):
                warnings.append(ValidationError(
                    field=f"ConceptSets.id={cs_id}",
                    message=f"ConceptSet {cs_id} not found in global registry",
                    severity="warning"
                ))
        
        return warnings
    
    def get_actionable_errors(
        self, result: ValidationResult
    ) -> Dict[str, list]:
        """Classify validation errors by feedback loop type.
        
        Returns:
            Dict mapping loop_id to list of error dicts, e.g.:
            {
                "LOOP_1_REMAP": [{"field": "...", "message": "..."}],
                "LOOP_2_REASSEMBLE": [{"field": "...", "message": "..."}],
            }
        """
        actionable: Dict[str, list] = {}
        
        for err in result.errors:
            if "CodesetId=0" in err.message or "Unmapped" in err.message:
                actionable.setdefault("LOOP_1_REMAP", []).append({
                    "field": err.field,
                    "message": err.message
                })
            elif "not found in ConceptSets" in err.message:
                actionable.setdefault("LOOP_2_REASSEMBLE", []).append({
                    "field": err.field,
                    "message": err.message
                })
        
        return actionable
    
    def format_report(self, result: ValidationResult) -> str:
        """Format validation result as human-readable report."""
        lines = []
        lines.append("=" * 50)
        lines.append("CIRCE JSON VALIDATION REPORT")
        lines.append("=" * 50)
        lines.append(f"Status: {'✅ VALID' if result.valid else '❌ INVALID'}")
        lines.append(f"ConceptSets: {result.concept_set_count}")
        lines.append(f"Inclusion Rules: {result.inclusion_rule_count}")
        lines.append("")
        
        if result.errors:
            lines.append(f"ERRORS ({len(result.errors)}):")
            for e in result.errors:
                lines.append(f"  ❌ [{e.field}] {e.message}")
            lines.append("")
        
        if result.warnings:
            lines.append(f"WARNINGS ({len(result.warnings)}):")
            for w in result.warnings:
                lines.append(f"  ⚠️ [{w.field}] {w.message}")
        
        lines.append("=" * 50)
        return "\n".join(lines)


# Singleton instance
agent4 = CirCeValidator()
