"""
ComplexityRouter - Criteria complexity classification for Fast/Slow path routing.

Implements the "Complexity Triage" strategy:
- Fast Path (Simple): Single noun phrases, clear medical terms → Direct Athena lookup
- Slow Path (Complex): Logical operators, negations, temporal constraints → LLM decomposition

Ported from artemis_agent with enhancements.
"""

from typing import Tuple, Dict, List, Set
import logging
import re

logger = logging.getLogger(__name__)

# Lazy load spacy to avoid import overhead if not used
_nlp = None


def get_nlp():
    """Lazy load SpaCy model."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
            logger.info("SpaCy en_core_web_sm loaded successfully")
        except Exception as e:
            logger.warning(f"SpaCy not available, using rule-based fallback: {e}")
            _nlp = "fallback"
    return _nlp


class ComplexityRouter:
    """
    Criteria complexity classification for Fast/Slow path routing.
    
    Classification criteria:
    - Simple: Single noun phrase, clear medical term, no logical operators
    - Complex: Contains logical operators, negations, temporal constraints, relational phrases
    
    Usage:
        router = ComplexityRouter()
        path = router.route("Type 2 diabetes")  # Returns "fast"
        path = router.route("History of MI except silent ischemia")  # Returns "slow"
    """
    
    # Patterns that indicate complex criteria (need LLM decomposition)
    COMPLEX_PATTERNS = {
        # Negation patterns
        "negation": [
            r"\bno\s+(?:history|evidence|sign|symptom)",
            r"\bwithout\b",
            r"\bnot\s+(?:have|having|had)",
            r"\bfree\s+of\b",
            r"\bdenies?\b",
            r"\babsence\s+of\b",
            r"\bexcluding\b",
        ],
        # Exception patterns
        "exception": [
            r"\bexcept\b",
            r"\bunless\b",
            r"\bbut\s+not\b",
            r"\bother\s+than\b",
            r"\bexcluding\b",
        ],
        # Causal/relational patterns
        "relational": [
            r"\bsecondary\s+to\b",
            r"\bdue\s+to\b",
            r"\bcaused\s+by\b",
            r"\bcompatible\s+with\b",
            r"\bassociated\s+with\b",
            r"\bresulting\s+from\b",
        ],
        # Temporal patterns
        "temporal": [
            r"\bwithin\s+\d+",
            r"\bprior\s+to\b",
            r"\bbefore\b",
            r"\bafter\b",
            r"\bduring\b",
            r"\b(?:in\s+the\s+(?:last|past))\s+\d+\s+(?:day|week|month|year)",
            r"\bat\s+(?:the\s+)?time\s+of\b",
        ],
        # Conditional patterns
        "conditional": [
            r"\bif\s+",
            r"\bwhen\s+",
            r"\bprovided\s+that\b",
            r"\bin\s+case\s+of\b",
        ],
        # Compound logical patterns
        "compound": [
            r"\s+and/or\s+",
            r"\s+or\s+",
            r",\s+or\s+",
            r";\s+",  # Semicolon often separates complex clauses
        ],
        # Mathematical/Quantitative patterns (Critical for clinical trials)
        "quantitative": [
            r"[<>]=?",             # Mathematical operators (<, >, <=, >=)
            r"\b(?:at\s+least|greater\s+than|less\s+than|more\s+than)\b",
            r"\b\d+\s*-\s*\d+\b",  # Ranges like "18-65"
            r"\bbetween\s+\d+\s+and\s+\d+\b",
        ],
        # Units often imply a measurement constraint
        "units": [
            r"\b(?:mg|kg|ml|dl|mmhg|cm|m2|%|iu|mmol|µmol|ng|mcg)(?:/[a-z]+)?\b",
        ],
    }
    
    # Ambiguous terms that can belong to multiple domains
    # These REQUIRE LLM context disambiguation
    AMBIGUOUS_TERMS: Set[str] = {
        # Medical vs Non-medical ambiguity
        "insult",       # 모욕(Social) vs 손상/ischemic insult (Condition)
        "culture",      # 배양(Procedure) vs 문화(Social)
        "positive",     # 양성(Measurement) vs 긍정적(Observation)
        "negative",     # 음성(Measurement) vs 부정적(Observation)
        
        # Domain ambiguity within medicine
        "mass",         # 덩어리/종양(Condition) vs 질량(Unit)
        "stage",        # 병기(Condition qualifier) vs 단계(General)
        "discharge",    # 분비물(Observation) vs 퇴원(Visit)
        "pressure",     # 혈압(Measurement) vs 스트레스(Observation)
        "block",        # 차단(Condition) vs 약물 차단(Drug)
        "level",        # 수치(Measurement) vs 수준(General)
        "study",        # 검사(Procedure) vs 연구(Administrative)
        "unit",         # 단위(Unit) vs 병동/ICU(Visit)
        "function",     # 기능(Measurement) vs 역할(General)
        "status",       # 상태(Observation) vs 지표(Measurement)
        "grade",        # 등급(Measurement) vs 정도(General)
        "treatment",    # 치료(Procedure) vs 약물치료(Drug)
    }
    
    # Maximum text length for "simple" classification (longer texts are often complex)
    MAX_SIMPLE_LENGTH = 60
    
    def __init__(self, use_spacy: bool = True):
        """
        Initialize ComplexityRouter.
        
        Args:
            use_spacy: Whether to use SpaCy for enhanced analysis.
                       Falls back to rule-based if SpaCy not available.
        """
        self.use_spacy = use_spacy
        self._nlp = None
        
        # Compile regex patterns
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        for category, patterns in self.COMPLEX_PATTERNS.items():
            self._compiled_patterns[category] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
    
    def route(self, text: str) -> str:
        """
        Determine processing path for criteria text.
        
        Args:
            text: Clinical criteria text
            
        Returns:
            "fast" for simple criteria (direct Athena lookup)
            "slow" for complex criteria (LLM decomposition needed)
        """
        # Ambiguity check first
        text_lower = text.lower()
        for term in self.AMBIGUOUS_TERMS:
            if term in text_lower:
                logger.debug(f"[Router] Forcing slow path due to ambiguous term '{term}'")
                return "slow"
        
        complexity, _ = self.classify(text)
        return "fast" if complexity == "Simple" else "slow"
    
    def classify(self, text: str) -> Tuple[str, Dict[str, any]]:
        """
        Classify criteria complexity with details.
        
        Args:
            text: Clinical criteria text
            
        Returns:
            Tuple of (complexity_level, details_dict)
            - complexity_level: "Simple" or "Complex"
            - details_dict: Contains matched patterns, confidence, etc.
        """
        text = text.strip()
        
        if not text:
            return ("Simple", {"reason": "empty_text", "confidence": 1.0})
        
        details = {
            "text_length": len(text),
            "matched_patterns": [],
            "has_negation": False,
            "has_exception": False,
            "has_temporal": False,
            "has_relational": False,
            "has_compound": False,
            "has_quantitative": False,
            "confidence": 0.0,
        }
        
        # Pattern-based analysis
        complexity_score = 0.0
        
        for category, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    details["matched_patterns"].append(category)
                    complexity_score += self._get_category_weight(category)
                    
                    # Set specific flags
                    if category == "negation":
                        details["has_negation"] = True
                    elif category == "exception":
                        details["has_exception"] = True
                    elif category == "temporal":
                        details["has_temporal"] = True
                    elif category == "relational":
                        details["has_relational"] = True
                    elif category == "compound":
                        details["has_compound"] = True
                    elif category == "quantitative":
                        details["has_quantitative"] = True
                    break  # Only count once per category
        
        # Length-based adjustment
        if len(text) > self.MAX_SIMPLE_LENGTH:
            complexity_score += 0.2
        if len(text) > 100:
            complexity_score += 0.2
        
        # SpaCy-based analysis (if available)
        if self.use_spacy:
            spacy_score = self._analyze_with_spacy(text, details)
            complexity_score += spacy_score
        
        # Determine final classification
        details["complexity_score"] = complexity_score
        details["confidence"] = min(1.0, 0.5 + complexity_score)
        
        # Threshold: 0.3+ is complex
        if complexity_score >= 0.3:
            return ("Complex", details)
        else:
            return ("Simple", details)
    
    def _get_category_weight(self, category: str) -> float:
        """Get weight for each pattern category."""
        weights = {
            "negation": 0.4,       # Negation is critical
            "exception": 0.5,      # Exception handling is complex
            "relational": 0.4,     # Causal relations need decomposition
            "temporal": 0.3,       # Temporal constraints
            "conditional": 0.4,    # Conditional logic
            "compound": 0.3,       # Compound statements
            "quantitative": 0.5,   # Math operators are hard for search engines
            "units": 0.3,          # Units imply measurement constraints
        }
        return weights.get(category, 0.2)
    
    def _analyze_with_spacy(self, text: str, details: Dict) -> float:
        """
        Use SpaCy for enhanced linguistic analysis.
        
        Returns additional complexity score based on:
        - Number of noun chunks (more = potentially compound)
        - Sentence structure complexity
        - Named entity count
        """
        nlp = get_nlp()
        
        if nlp == "fallback":
            return 0.0
        
        try:
            doc = nlp(text)
            
            # Count noun chunks
            noun_chunks = list(doc.noun_chunks)
            details["noun_chunk_count"] = len(noun_chunks)
            
            # Multiple noun chunks suggest compound criteria
            if len(noun_chunks) >= 3:
                return 0.2
            elif len(noun_chunks) >= 2:
                return 0.1
            
            # Check for complex sentence structure
            # (multiple ROOT verbs or complex dependencies)
            root_count = sum(1 for token in doc if token.dep_ == "ROOT")
            if root_count > 1:
                details["multiple_clauses"] = True
                return 0.2
            
            return 0.0
            
        except Exception as e:
            logger.warning(f"SpaCy analysis failed: {e}")
            return 0.0
    
    def batch_classify(self, texts: List[str]) -> List[Tuple[str, str, Dict]]:
        """
        Classify multiple texts efficiently.
        
        Args:
            texts: List of clinical criteria texts
            
        Returns:
            List of (text, path, details) tuples
        """
        results = []
        for text in texts:
            complexity, details = self.classify(text)
            path = "fast" if complexity == "Simple" else "slow"
            results.append((text, path, details))
        return results
    
    def get_stats(self, texts: List[str]) -> Dict[str, any]:
        """
        Get classification statistics for a batch of texts.
        
        Returns:
            Dict with counts, percentages, and pattern frequencies
        """
        results = self.batch_classify(texts)
        
        fast_count = sum(1 for _, path, _ in results if path == "fast")
        slow_count = len(results) - fast_count
        
        pattern_counts: Dict[str, int] = {}
        for _, _, details in results:
            for pattern in details.get("matched_patterns", []):
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        
        return {
            "total": len(results),
            "fast_path": fast_count,
            "slow_path": slow_count,
            "fast_percentage": fast_count / len(results) * 100 if results else 0,
            "slow_percentage": slow_count / len(results) * 100 if results else 0,
            "pattern_frequencies": pattern_counts,
        }


# Lazy singleton
_router_instance = None


def get_router() -> ComplexityRouter:
    """Get or create ComplexityRouter instance (lazy initialization)."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ComplexityRouter()
    return _router_instance
