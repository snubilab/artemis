"""
NLU Router Unit Tests

RFC-001 Phase 1 검증
"""
import pytest
from unittest.mock import patch, MagicMock

from src.settings import settings
from src.agents.conceptset.nlu_router import (
    NLURouter,
    IntentResult,
    IntentSeparator,
)

# Phase 8 P4: Check for LLM API key
has_llm_key = any([
    settings.OPENROUTER_API_KEY,
    settings.GOOGLE_API_KEY,
    settings.OPENAI_API_KEY
])


class TestNLURouter:
    """NLU Router 통합 테스트"""
    
    def test_should_pass_the_separator_fallback_through_when_the_model_sets_it(self):
        """Whether a query needs Agent 1 is the separator's ``fallback_to``, not a word list."""
        with patch('src.agents.conceptset.nlu_router.IntentSeparator') as MockSeparator:
            MockSeparator.return_value.separate.return_value = IntentResult(
                include=[], exclude=[], fallback_to="Agent1", fallback_reason="temporal logic"
            )
            router = NLURouter()
            result = router.route("history of MI but currently on Aspirin")

        MockSeparator.return_value.separate.assert_called_once_with(
            "history of MI but currently on Aspirin"
        )
        assert result.fallback_to == "Agent1"
        assert result.fallback_reason == "temporal logic"
    
    def test_simple_include(self):
        """단순 포함 쿼리"""
        with patch('src.agents.conceptset.nlu_router.IntentSeparator') as MockSeparator:
            mock_instance = MockSeparator.return_value
            mock_instance.separate.return_value = IntentResult(
                include=["Heart Failure"],
                exclude=[]
            )
            
            router = NLURouter()
            result = router.route("Heart Failure")
        
        assert result.include == ["Heart Failure"]
        assert result.exclude == []
        assert result.fallback_to is None
    
    def test_include_and_exclude(self):
        """포함 + 제외 쿼리"""
        with patch('src.agents.conceptset.nlu_router.IntentSeparator') as MockSeparator:
            mock_instance = MockSeparator.return_value
            mock_instance.separate.return_value = IntentResult(
                include=["Heart Failure"],
                exclude=["Thiazolidinediones", "Pioglitazone", "Rosiglitazone"]
            )
            
            router = NLURouter()
            result = router.route("Heart Failure but no TZD")
        
        assert "Heart Failure" in result.include
        assert len(result.exclude) == 3
        assert "Thiazolidinediones" in result.exclude


class TestIntentSeparator:
    """Intent Separator LLM 테스트 (Mocked)"""
    
    @patch('src.agents.conceptset.nlu_router.get_llm')
    def test_separator_initialization(self, mock_get_llm):
        """IntentSeparator 초기화"""
        mock_get_llm.return_value = MagicMock()
        separator = IntentSeparator()
        
        assert separator.llm is not None
        assert separator.parser is not None
    
    @patch('src.agents.conceptset.nlu_router.get_llm')
    def test_fallback_on_error(self, mock_get_llm):
        """LLM 실패 시 fallback"""
        mock_get_llm.return_value = MagicMock()
        separator = IntentSeparator()
        
        # Chain이 예외 발생 → fallback
        with patch.object(separator, 'chain') as mock_chain:
            mock_chain.invoke.side_effect = Exception("LLM Error")
            result = separator.separate("test query")
        
        # Fallback: 전체 쿼리를 include로
        assert result.include == ["test query"]
        assert result.exclude == []


class TestIntentResult:
    """IntentResult 모델 테스트"""
    
    def test_default_values(self):
        """기본값 확인"""
        result = IntentResult()
        
        assert result.include == []
        assert result.exclude == []
        assert result.fallback_to is None
        assert result.fallback_reason is None
    
    def test_with_values(self):
        """값 설정 확인"""
        result = IntentResult(
            include=["T2DM"],
            exclude=["TZD"],
            fallback_to="Agent1",
            fallback_reason="Temporal logic"
        )
        
        assert result.include == ["T2DM"]
        assert result.exclude == ["TZD"]
        assert result.fallback_to == "Agent1"


# ============================================================================
# Integration Test (E2E with LLM - 별도 실행)
# ============================================================================

@pytest.mark.integration
@pytest.mark.skipif(not has_llm_key, reason="No LLM API key configured")
class TestNLURouterIntegration:
    """실제 LLM 호출 테스트 (CI에서는 skip)"""
    
    @pytest.fixture
    def router(self):
        return NLURouter()
    
    def test_real_simple_query(self, router):
        """실제 LLM으로 단순 쿼리 테스트"""
        result = router.route("Type 2 Diabetes Mellitus")
        
        assert len(result.include) > 0
        assert result.fallback_to is None
    
    def test_real_exclusion_query(self, router):
        """실제 LLM으로 제외 쿼리 테스트"""
        result = router.route("Heart Failure but exclude TZD")
        
        assert len(result.include) > 0
        assert len(result.exclude) > 0
