import re
from typing import Optional, Literal

class CodePatternMatcher:
    """
    Detects if an input string looks like a clinical code (ICD-10, RxNorm, etc.)
    to bypass vector search and perform direct DB lookup.
    """

    # ICD-10-CM Pattern: 
    # Starts with A-Z (excluding U in some contexts, but general is A-Z)
    # Followed by 2 digits.
    # Optional dot and more digits.
    # Examples: I21, I21.9, E11.9
    ICD10_PATTERN = re.compile(r"^[A-Z][0-9]{2}(\.[0-9]{1,})?$")

    # Generic Numeric Code (could be RxNorm, SNOMED, NDC)
    # Just a sequence of digits, usually length 4 to 18
    NUMERIC_PATTERN = re.compile(r"^\d{4,18}$")

    @classmethod
    def detect(cls, text: str) -> Optional[Literal["ICD10", "NUMERIC_CODE"]]:
        clean_text = text.strip()
        
        if cls.ICD10_PATTERN.match(clean_text):
            return "ICD10"
        
        if cls.NUMERIC_PATTERN.match(clean_text):
            return "NUMERIC_CODE"
            
        return None

def is_potential_code(text: str) -> bool:
    return CodePatternMatcher.detect(text) is not None
