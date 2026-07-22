"""
Populate ChromaDB with OMOP Vocabulary for Agent 2 Semantic Search.

Loads concepts from the local PostgreSQL OMOP vocabulary database.
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from tqdm import tqdm
from src.utils.vector import get_chroma_client
from src.settings import settings


# Domains relevant for clinical trial criteria
RELEVANT_DOMAINS = ['Condition', 'Drug', 'Procedure', 'Measurement', 'Observation', 'Device']

# Per-domain limits (None = full load)
# Clinical core domains get full load, others are limited for practical reasons
DOMAIN_LIMITS = {
    'Condition': None,      # 105,666 - 진단 (전체)
    'Drug': 100000,         # 2M 중 상위 100k (메모리 제약)
    'Procedure': None,      # 58,158 - 시술 (전체)
    'Measurement': None,    # 94,798 - 검사 (전체)
    'Observation': 50000,   # 132k 중 50k
    'Device': None,         # 32,168 - 기기 (전체)
}

# Fallback limit if domain not in DOMAIN_LIMITS
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


def populate_chromadb():
    """Populate ChromaDB with OMOP concepts."""
    print("="*60)
    print("ARTEMIS 3.1 - Populate ChromaDB with OMOP Vocabulary")
    print("="*60)
    
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="omop_concepts")
    
    print(f"\n📊 Current documents: {collection.count()}")
    
    if collection.count() > 0:
        print("⚠️  Collection already has data. Skipping population.")
        print("   To repopulate, delete the collection first.")
        return
    
    total_added = 0
    
    for domain in RELEVANT_DOMAINS:
        print(f"\n📦 Processing {domain}...")
        
        # Get per-domain limit
        limit = DOMAIN_LIMITS.get(domain, DEFAULT_LIMIT)
        
        try:
            concepts = fetch_concepts(domain, limit)
        except Exception as e:
            print(f"   ⚠️ Error fetching {domain}: {e}")
            continue
        
        if not concepts:
            print(f"   ⚠️ No concepts found for {domain}")
            continue
        
        # Prepare batch data
        ids = []
        documents = []
        metadatas = []
        
        for concept_id, name, vocab, concept_class, dom in tqdm(concepts, desc=f"  {domain}"):
            ids.append(str(concept_id))
            # Document is the concept name (will be embedded)
            documents.append(name)
            metadatas.append({
                "concept_id": concept_id,
                "vocabulary_id": vocab,
                "concept_class_id": concept_class,
                "domain_id": dom
            })
        
        # Add to collection in batches of 5000
        batch_size = 5000
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i+batch_size]
            batch_docs = documents[i:i+batch_size]
            batch_meta = metadatas[i:i+batch_size]
            
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_meta
            )
        
        print(f"   ✅ Added {len(concepts)} concepts")
        total_added += len(concepts)
    
    print("\n" + "="*60)
    print(f"✅ ChromaDB Population Complete!")
    print(f"   Total concepts indexed: {total_added}")
    print(f"   Collection count: {collection.count()}")
    print("="*60)


def populate_atc_drug_classes():
    """
    Populate a dedicated ChromaDB collection with ATC 4th level concepts.
    
    ATC 4th level (~936 concepts) represents pharmacological drug classes
    (e.g., "GLP-1 receptor agonists", "DPP-4 inhibitors").
    Used by Agent 2 for drug class → ingredient expansion via concept_ancestor.
    
    See RFC-006 for design rationale.
    """
    print("\n" + "="*60)
    print("ARTEMIS 3.1 - Populate ATC Drug Class Collection")
    print("="*60)
    
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="atc_drug_classes")
    
    if collection.count() > 0:
        print(f"⚠️  Collection already has {collection.count()} documents. Skipping.")
        print("   To repopulate, delete the collection first.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(f"""
        SELECT concept_id, concept_name, concept_code, concept_class_id
        FROM {settings.CDM_SCHEMA}.concept
        WHERE vocabulary_id = 'ATC'
          AND concept_class_id IN ('ATC 1st', 'ATC 2nd', 'ATC 3rd', 'ATC 4th')
          AND invalid_reason IS NULL
        ORDER BY concept_code
    """)
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    if not rows:
        print("⚠️  No ATC concepts found in database.")
        return
    
    ids = [str(r[0]) for r in rows]
    documents = [r[1] for r in rows]
    metadatas = [{
        "concept_id": r[0],
        "concept_code": r[2],
        "concept_class_id": r[3],
        "vocabulary_id": "ATC",
    } for r in rows]
    
    # Small enough to add in one batch
    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    
    print(f"✅ ATC Drug Class Collection: {collection.count()} concepts indexed")
    
    # Show breakdown by level
    from collections import Counter
    levels = Counter(r[3] for r in rows)
    for level in sorted(levels):
        print(f"   {level}: {levels[level]} concepts")


if __name__ == "__main__":
    populate_chromadb()
    populate_atc_drug_classes()
