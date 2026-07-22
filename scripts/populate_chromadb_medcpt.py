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

import psycopg2
from tqdm import tqdm
from src.utils.vector import get_chroma_client
from src.utils.medcpt_embedding import MedCPTEmbeddingFunction
from src.settings import settings


# Domains relevant for clinical trial criteria
RELEVANT_DOMAINS = ['Condition', 'Drug', 'Procedure', 'Measurement', 'Observation', 'Device']

# Per-domain limits (same as default populate script)
DOMAIN_LIMITS = {
    'Condition': None,      # ~105K
    'Drug': 100000,         # 2M → 100K
    'Procedure': None,      # ~58K
    'Measurement': None,    # ~95K
    'Observation': 50000,   # 132K → 50K
    'Device': None,         # ~32K
}

DEFAULT_LIMIT = 50000


def get_db_connection():
    """Get PostgreSQL connection from settings."""
    return psycopg2.connect(settings.DATABASE_URL)


def fetch_concepts(domain: str, limit: int | None = None):
    """Fetch standard concepts from OMOP vocabulary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = f"""
        SELECT 
            concept_id,
            concept_name,
            vocabulary_id,
            concept_class_id,
            domain_id
        FROM {settings.CDM_SCHEMA}.concept
        WHERE domain_id = %s
          AND standard_concept = 'S'
          AND invalid_reason IS NULL
        ORDER BY concept_id
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query, (domain,))
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return rows


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
    
    if collection.count() > 0:
        print("⚠️  Collection already has data. Skipping population.")
        print("   To repopulate, delete the collection first:")
        print(f"   python -c \"import chromadb; c=chromadb.PersistentClient(path='{settings.CHROMA_PERSIST_DIRECTORY}'); c.delete_collection('{collection_name}')\"")
        return
    
    total_added = 0
    
    for domain in RELEVANT_DOMAINS:
        print(f"\n📦 Processing {domain}...")
        
        limit = DOMAIN_LIMITS.get(domain, DEFAULT_LIMIT)
        
        try:
            concepts = fetch_concepts(domain, limit)
        except Exception as e:
            print(f"   ⚠️ Error fetching {domain}: {e}")
            continue
        
        if not concepts:
            print(f"   ⚠️ No concepts found for {domain}")
            continue
        
        print(f"   Found {len(concepts)} concepts")
        
        # Prepare batch data
        ids = []
        documents = []
        metadatas = []
        
        for concept_id, name, vocab, concept_class, dom in concepts:
            ids.append(str(concept_id))
            documents.append(name)
            metadatas.append({
                "concept_id": concept_id,
                "concept_name": name,
                "vocabulary_id": vocab,
                "concept_class_id": concept_class,
                "domain_id": dom,
            })
        
        # Add in smaller batches (MedCPT is heavier than MiniLM)
        # batch_size for DB upsert (not to be confused with model batch_size)
        db_batch_size = 512
        for i in tqdm(range(0, len(ids), db_batch_size), desc=f"  Indexing {domain}"):
            batch_ids = ids[i : i + db_batch_size]
            batch_docs = documents[i : i + db_batch_size]
            batch_meta = metadatas[i : i + db_batch_size]
            
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_meta,
            )
        
        added = len(concepts)
        print(f"   ✅ Added {added} concepts")
        total_added += added
    
    # Switch back to query mode for subsequent use
    ef.set_mode("query")
    
    print("\n" + "=" * 60)
    print(f"✅ MedCPT ChromaDB Population Complete!")
    print(f"   Total concepts indexed: {total_added}")
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
