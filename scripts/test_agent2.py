import sys
import os
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set dummy API key to pass validations during import
os.environ["GOOGLE_API_KEY"] = "DUMMY_KEY_FOR_TEST"

# Mock LLM libs only if they are not installed or to prevent API usage
sys.modules["langchain_google_genai"] = MagicMock()
sys.modules["langchain_openai"] = MagicMock()

from src.agents.agent2.retriever import CandidateConcept

def main():
    print("--- Starting Agent 2 Test ---")
    
    # ... rest of the main function is the same ...
    # But wait, since I set the dummy key, get_llm will try to instantiate ChatGoogleGenerativeAI
    # which comes from the mocked 'langchain_google_genai'.
    # So it should be fine.

    # Mocking the Reranker's LLM chain
    with patch("src.agents.agent2.reranker.get_llm") as mock_get_llm, \
         patch("src.agents.agent2.retriever.retriever.search") as mock_search:
        
        # Setup Mocks
        mock_get_llm.return_value = MagicMock()
        
        # Mock Search Result
        mock_candidate = CandidateConcept(
            concept_id=12345,
            concept_name="Mock Diabetes",
            domain_id="Condition",
            vocabulary_id="SNOMED",
            concept_class_id="Clinical Finding",
            distance=0.1
        )
        mock_search.return_value = [mock_candidate]
        
        from src.agents.agent2.workflow import agent2
        from src.agents.agent2.reranker import reranker
        from src.agents.agent2.retriever import retriever
        from src.agents.agent2.logic import logician
        
        # Apply runtime mocks to the instances
        retriever.search = MagicMock(return_value=[mock_candidate])
        reranker.rerank = MagicMock(return_value=mock_candidate)
        logician.decompose_combination = MagicMock(return_value=[12345])
        logician.prune_empty_concepts = MagicMock(return_value=[12345])

        # Test Case 1: Plain Text
        query = "Type 2 Diabetes Mellitus"
        print(f"\nTest Query: {query}")
        ids = agent2.process(query)
        print(f"Result IDs: {ids}")
        
        assert ids == [12345]
        print("✅ Test Case 1 Passed")

        # Test Case 2: Code Pattern
        query_code = "I21.9"
        print(f"\nTest Query: {query_code}")
        ids_code = agent2.process(query_code)
        print(f"Result IDs: {ids_code}")
        print("✅ Test Case 2 Passed (Logic Flow)")

    print("\n--- Test Finished ---")

if __name__ == "__main__":
    main()

