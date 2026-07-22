"""
Rule-Based Extractor - Fast extraction for simple clinical criteria.

Handles simple patterns without LLM calls:
- Demographic: Age, sex, pregnancy status
- Numeric: Operators (>=, <=, etc.), values, units
- Condition: Simple disease/condition names

Pattern 2 from artemis_agent.
"""

from typing import Dict, Any, Optional, Tuple
import logging
import re

logger = logging.getLogger(__name__)


class RuleExtractor:
    """
    Rule-based extraction for simple clinical criteria.
    
    Avoids LLM calls for patterns that can be reliably extracted with regex.
    Falls back to None when rules are insufficient, signaling need for LLM.
    
    Usage:
        extractor = RuleExtractor()
        result = extractor.extract("Age >= 18 years", "Demographic")
        # Returns: {"type": "Demographic", "attribute": "age", "operator": ">=", "value": 18, "unit": "years"}
    """
    
    # Numeric operator patterns
    NUMERIC_PATTERN = re.compile(
        r'([<>=!]+)\s*(\d+\.?\d*)\s*(%|mg|mL|kg|years?|months?|days?|weeks?|mmHg|cm|m2|IU|mmol|ng|mcg|mg/dL|mL/min)?',
        re.IGNORECASE
    )
    
    # Range patterns (between X and Y, X-Y, X to Y)
    RANGE_PATTERN = re.compile(
        r'(\d+\.?\d*)\s*(?:to|-|and)\s*(\d+\.?\d*)\s*(%|mg|years?|months?|days?)?',
        re.IGNORECASE
    )
    
    # Between pattern
    BETWEEN_PATTERN = re.compile(
        r'between\s+(\d+\.?\d*)\s+and\s+(\d+\.?\d*)',
        re.IGNORECASE
    )
    
    # Demographic attribute keywords
    DEMOGRAPHIC_KEYWORDS = {
        "age": ["age", "aged", "years old", "year old"],
        "sex": ["sex", "gender", "male", "female"],
        "pregnancy_status": ["pregnant", "pregnancy", "breastfeeding", "lactating", "nursing"],
        "race": ["race", "ethnicity", "ethnic"],
        "bmi": ["bmi", "body mass index"],
    }
    
    # Operator normalization
    OPERATOR_MAP = {
        ">=": "gte",
        "<=": "lte", 
        ">": "gt",
        "<": "lt",
        "=": "eq",
        "==": "eq",
        "!=": "neq",
        "≥": "gte",
        "≤": "lte",
    }
    
    def extract(self, text: str, domain: str) -> Optional[Dict[str, Any]]:
        """
        Extract structured information from criteria text.
        
        Args:
            text: Clinical criteria text
            domain: Expected domain (Demographic, Measurement, Condition, etc.)
            
        Returns:
            Extraction dict if successful, None if rules insufficient
        """
        extraction = {"type": domain, "text": text}
        
        if domain == "Demographic":
            return self._extract_demographic(text, extraction)
        elif domain == "Measurement":
            return self._extract_measurement(text, extraction)
        elif domain in ["Condition", "Drug", "Procedure", "Observation"]:
            return self._extract_simple_concept(text, extraction)
        else:
            return None
    
    def _extract_demographic(self, text: str, extraction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract demographic criteria."""
        text_lower = text.lower()
        
        # Identify attribute type
        for attr, keywords in self.DEMOGRAPHIC_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                extraction["attribute"] = attr
                break
        
        # Extract numeric constraint
        numeric_result = self._extract_numeric(text)
        if numeric_result:
            extraction.update(numeric_result)
        
        # Check if extraction is complete enough
        if self._is_demographic_complete(extraction):
            return extraction
        
        return None
    
    def _extract_measurement(self, text: str, extraction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract measurement criteria."""
        
        # Extract numeric constraint
        numeric_result = self._extract_numeric(text)
        if numeric_result:
            extraction.update(numeric_result)
            
            # For measurements, we need the test name
            # Try to extract it as the text before the operator
            match = re.search(r'^(.+?)\s*[<>=]', text)
            if match:
                extraction["measurement_name"] = match.group(1).strip()
            
            return extraction
        
        return None
    
    def _extract_simple_concept(self, text: str, extraction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract simple condition/drug/procedure names."""
        
        # For simple concepts, just clean up the text
        # Remove common prefixes
        clean_text = text
        prefixes_to_remove = [
            r"^history of\s+",
            r"^diagnosis of\s+",
            r"^presence of\s+",
            r"^current\s+",
            r"^active\s+",
        ]
        
        for prefix in prefixes_to_remove:
            clean_text = re.sub(prefix, "", clean_text, flags=re.IGNORECASE)
        
        extraction["concept_text"] = clean_text.strip()
        
        # Detect negation (simple cases only)
        if re.search(r'^no\s+|^not\s+|^without\s+', text, re.IGNORECASE):
            extraction["negation"] = True
        
        # Only return if we have meaningful text
        if len(extraction.get("concept_text", "")) >= 3:
            return extraction
        
        return None
    
    def _extract_numeric(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract numeric constraint from text."""
        result = {}
        
        # Try between pattern first
        between_match = self.BETWEEN_PATTERN.search(text)
        if between_match:
            result["operator"] = "between"
            result["value_low"] = float(between_match.group(1))
            result["value_high"] = float(between_match.group(2))
            return result
        
        # Try range pattern (X-Y or X to Y)
        range_match = self.RANGE_PATTERN.search(text)
        if range_match:
            result["operator"] = "between"
            result["value_low"] = float(range_match.group(1))
            result["value_high"] = float(range_match.group(2))
            if range_match.group(3):
                result["unit"] = range_match.group(3).lower()
            return result
        
        # Try single operator pattern
        numeric_match = self.NUMERIC_PATTERN.search(text)
        if numeric_match:
            op = numeric_match.group(1)
            result["operator"] = self.OPERATOR_MAP.get(op, op)
            result["value"] = float(numeric_match.group(2))
            if numeric_match.group(3):
                result["unit"] = numeric_match.group(3).lower()
            return result
        
        return None
    
    def _is_demographic_complete(self, extraction: Dict[str, Any]) -> bool:
        """Check if demographic extraction is complete."""
        has_attribute = "attribute" in extraction
        has_numeric = "operator" in extraction or "value" in extraction
        
        # Age requires numeric
        if extraction.get("attribute") == "age":
            return has_attribute and has_numeric
        
        # Sex/pregnancy status doesn't need numeric
        if extraction.get("attribute") in ["sex", "pregnancy_status"]:
            return has_attribute
        
        return has_attribute and has_numeric
    
    def is_extraction_complete(self, extraction: Optional[Dict[str, Any]], domain: str) -> bool:
        """
        Check if extraction is complete enough to skip LLM.
        
        Args:
            extraction: Extraction result or None
            domain: Expected domain
            
        Returns:
            True if extraction is sufficient, False otherwise
        """
        if not extraction:
            return False
        
        # Demographic: attribute and value/operator for age, attribute only for sex
        if domain == "Demographic":
            return self._is_demographic_complete(extraction)
        
        # Measurement: needs operator and value
        if domain == "Measurement":
            return "operator" in extraction and ("value" in extraction or "value_low" in extraction)
        
        # Condition/Drug/Procedure: text is enough (will be mapped to OMOP)
        if domain in ["Condition", "Drug", "Procedure", "Observation"]:
            return "concept_text" in extraction and len(extraction["concept_text"]) >= 3
        
        # Other domains need LLM
        return False


# Lazy singleton
_extractor_instance = None


def get_extractor() -> RuleExtractor:
    """Get or create RuleExtractor instance (lazy initialization)."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = RuleExtractor()
    return _extractor_instance
