"""
ChromaDB Initialization Script for ARTEMIS 3.1.

Initializes ChromaDB with OMOP Vocabulary embeddings for Agent 2 semantic search.
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.vector import get_chroma_client
from src.settings import settings


def init_chromadb():
    """Initialize ChromaDB collections for Agent 2."""
    print("="*60)
    print("ARTEMIS 3.1 - ChromaDB Initialization")
    print("="*60)
    
    # Get ChromaDB client
    persist_dir = settings.CHROMA_PERSIST_DIRECTORY
    print(f"\n📂 Persist Directory: {persist_dir}")
    
    client = get_chroma_client()
    print(f"✅ ChromaDB Client initialized")
    
    # Create/verify collections
    collections = [
        "omop_concepts",      # Main OMOP vocabulary concepts
        "clinical_terms",     # Clinical term variations
    ]
    
    for name in collections:
        col = client.get_or_create_collection(name=name)
        count = col.count()
        print(f"  - {name}: {count} documents")
    
    print("\n" + "="*60)
    print("✅ ChromaDB Ready!")
    print("="*60)
    
    # Check if we need to populate with OMOP vocabulary
    concepts_col = client.get_or_create_collection(name="omop_concepts")
    if concepts_col.count() == 0:
        print("\n⚠️  WARNING: omop_concepts collection is empty!")
        print("   To populate with OMOP vocabulary, run:")
        print("   python scripts/populate_chromadb.py")
        print("\n💡 For now, Agent 2 will use direct DB lookups (Fast Path only)")
    
    return True


if __name__ == "__main__":
    init_chromadb()
