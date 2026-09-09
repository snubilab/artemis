"""
Populate ChromaDB with OMOP Vocabulary using MedCPT embeddings.

Uses MedCPT Article Encoder for document embedding instead of ChromaDB default.
Creates a separate collection (omop_concepts_medcpt) for ablation comparison.

Usage:
    python scripts/populate_chromadb_medcpt.py [--device cpu|cuda|mps] [--batch-size 64]
"""
import sys
import argparse
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.vector import get_chroma_client
from src.utils.medcpt_embedding import MedCPTEmbeddingFunction


# The domain table, the query and the incremental sync are shared with the default
# populate script rather than copied. Production reads omop_concepts_medcpt
# (EMBEDDING_MODEL=medcpt on the host and inside artemis-api), so a second copy of
# DOMAIN_LIMITS here means a cap changed in populate_chromadb.py changes nothing the
# pipeline actually queries. tests/test_populate_chromadb_indexes_every_standard_concept.py
# pins that these are the same objects.
from scripts.populate_chromadb import (  # noqa: E402
    DOMAIN_LIMITS,
    RELEVANT_DOMAINS,
    fetch_concepts,
    sync_collection,
)

__all__ = ["DOMAIN_LIMITS", "RELEVANT_DOMAINS", "fetch_concepts", "sync_collection"]


def populate_medcpt(device: str = "cpu", batch_size: int = 64):
    """Populate ChromaDB with OMOP concepts using MedCPT embeddings."""
    print("=" * 60)
    print("ARTEMIS 3.1 - Populate ChromaDB with MedCPT Embeddings")
    print(f"  Device: {device}, Batch Size: {batch_size}")
    print("=" * 60)

    # Initialize MedCPT embedding function
    ef = MedCPTEmbeddingFunction(device=device, batch_size=batch_size)

    # Set to indexing mode (Article Encoder)
    ef.set_mode("index")
    print("✅ MedCPT embedding function initialized (Article Encoder)")

    # Initialize ChromaDB
    client = get_chroma_client()
    collection_name = "omop_concepts_medcpt"
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=ef,
    )

    print(f"\n📊 Collection '{collection_name}': {collection.count()} documents")

    # Incremental: adds the ids the collection lacks and leaves the rest untouched,
    # so lifting a cap costs the missing rows rather than a full rebuild.
    # db_batch_size 512, not the model batch size above.
    report = sync_collection(
        collection,
        batch_size=512,
        metadata_for=lambda row: {
            "concept_id": row[0],
            "concept_name": row[1],
            "vocabulary_id": row[2],
            "concept_class_id": row[3],
            "domain_id": row[4],
        },
    )

    # Switch back to query mode for subsequent use
    ef.set_mode("query")

    print("\n" + "=" * 60)
    print("✅ MedCPT ChromaDB Population Complete!")
    print(f"   Concepts added this run: {sum(added for _, _, added in report.values())}")
    print(f"   Collection count: {collection.count()}")
    print(f"   Collection name: {collection_name}")
    print("=" * 60)
    print("\n💡 To use MedCPT at runtime, set:")
    print("   export EMBEDDING_MODEL=medcpt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate ChromaDB with MedCPT embeddings")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "mps"],
                        help="Device for MedCPT inference (default: cpu)")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="Model batch size for embedding (default: 64)")
    args = parser.parse_args()

    populate_medcpt(device=args.device, batch_size=args.batch_size)
