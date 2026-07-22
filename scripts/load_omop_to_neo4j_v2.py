"""
OMOP CDM → Neo4j v2 Knowledge Graph ETL Script

Loads Standard Concepts and CONCEPT_RELATIONSHIP direct edges (Is a, Maps to)
into Neo4j. NO CONCEPT_ANCESTOR closure — preserves ontology topology.

Architecture:
  - IS_A edges: child → parent (from CONCEPT_RELATIONSHIP where relationship_id = 'Is a')
  - MAPS_TO edges: source → standard (from CONCEPT_RELATIONSHIP where relationship_id = 'Maps to')
  - NO HAS_DESCENDANT: CONCEPT_ANCESTOR is only used via PostgreSQL for IC calculation

Usage:
    NEO4J_URI=bolt://localhost:7688 conda run -n artemis python scripts/load_omop_to_neo4j_v2.py

Prerequisites:
    - PostgreSQL with OMOP CDM running
    - Neo4j v2 running (docker compose -f docker-compose.neo4j-v2.yml up -d)
"""

import os
import time
import logging
from typing import List, Tuple, Dict

import psycopg2
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────
PG_CONFIG = {
    "host": os.getenv("OMOP_DB_HOST", os.getenv("PG_HOST", "localhost")),
    "port": int(os.getenv("OMOP_DB_PORT", os.getenv("PG_PORT", "5432"))),
    "dbname": os.getenv("OMOP_DB_NAME", os.getenv("PG_DBNAME", "ohdsi")),
    "user": os.getenv("OMOP_DB_USER", os.getenv("PG_USER", "postgres")),
    "password": os.getenv("OMOP_DB_PASS", os.getenv("PG_PASSWORD", "mypass")),
}

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7688")  # v2 default port
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "artemis_neo4j")

SCHEMA = os.getenv("CDM_SCHEMA", "synthea23m")
BATCH_SIZE = 50000


# ── Step 1: Extract from PostgreSQL ────────────────────────
def extract_concepts(pg_conn) -> List[Tuple]:
    """Extract Standard Concepts (S) from OMOP CDM."""
    logger.info("Extracting Standard Concepts from PostgreSQL...")
    cur = pg_conn.cursor()
    cur.execute(f"""
        SELECT concept_id, concept_name, domain_id, vocabulary_id, 
               concept_class_id, concept_code
        FROM {SCHEMA}.concept
        WHERE standard_concept = 'S'
          AND invalid_reason IS NULL
    """)
    rows = cur.fetchall()
    logger.info(f"  Extracted {len(rows):,d} Standard Concepts")
    return rows


def extract_is_a_relationships(pg_conn) -> List[Tuple]:
    """Extract 'Is a' relationships from CONCEPT_RELATIONSHIP.
    
    Direction: concept_id_1 IS_A concept_id_2 (child → parent).
    These are the DIRECT edges of the ontology hierarchy.
    """
    logger.info("Extracting 'Is a' relationships from CONCEPT_RELATIONSHIP...")
    cur = pg_conn.cursor()
    cur.execute(f"""
        SELECT cr.concept_id_1, cr.concept_id_2
        FROM {SCHEMA}.concept_relationship cr
        JOIN {SCHEMA}.concept c1 ON cr.concept_id_1 = c1.concept_id
        JOIN {SCHEMA}.concept c2 ON cr.concept_id_2 = c2.concept_id
        WHERE cr.relationship_id = 'Is a'
          AND c1.standard_concept = 'S'
          AND c2.standard_concept = 'S'
          AND c1.invalid_reason IS NULL
          AND c2.invalid_reason IS NULL
          AND cr.invalid_reason IS NULL
          AND cr.concept_id_1 != cr.concept_id_2
    """)
    rows = cur.fetchall()
    logger.info(f"  Extracted {len(rows):,d} 'Is a' relationships (direct edges)")
    return rows


def extract_maps_to_relationships(pg_conn) -> List[Tuple]:
    """Extract 'Maps to' relationships from CONCEPT_RELATIONSHIP."""
    logger.info("Extracting 'Maps to' relationships from CONCEPT_RELATIONSHIP...")
    cur = pg_conn.cursor()
    cur.execute(f"""
        SELECT cr.concept_id_1, cr.concept_id_2
        FROM {SCHEMA}.concept_relationship cr
        JOIN {SCHEMA}.concept c1 ON cr.concept_id_1 = c1.concept_id
        JOIN {SCHEMA}.concept c2 ON cr.concept_id_2 = c2.concept_id
        WHERE cr.relationship_id = 'Maps to'
          AND c1.invalid_reason IS NULL
          AND c2.invalid_reason IS NULL
          AND cr.invalid_reason IS NULL
          AND cr.concept_id_1 != cr.concept_id_2
    """)
    rows = cur.fetchall()
    logger.info(f"  Extracted {len(rows):,d} 'Maps to' relationships")
    return rows


# ── Step 2: Load into Neo4j ────────────────────────────────
def clear_database(driver):
    """Clear existing data in Neo4j."""
    logger.info("Clearing Neo4j database...")
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    logger.info("  Database cleared")


def create_constraints(driver):
    """Create indexes and constraints in Neo4j."""
    logger.info("Creating Neo4j constraints and indexes...")
    with driver.session() as session:
        session.run("""
            CREATE CONSTRAINT concept_id_unique IF NOT EXISTS
            FOR (c:Concept) REQUIRE c.concept_id IS UNIQUE
        """)
        session.run("""
            CREATE INDEX concept_domain IF NOT EXISTS
            FOR (c:Concept) ON (c.domain_id)
        """)
        session.run("""
            CREATE INDEX concept_vocab IF NOT EXISTS
            FOR (c:Concept) ON (c.vocabulary_id)
        """)
        session.run("""
            CREATE INDEX concept_name IF NOT EXISTS
            FOR (c:Concept) ON (c.concept_name)
        """)
        session.run("""
            CREATE INDEX concept_class IF NOT EXISTS
            FOR (c:Concept) ON (c.concept_class_id)
        """)
    logger.info("  Constraints and indexes created")


def load_concepts(driver, concepts: List[Tuple]):
    """Batch load concepts as Neo4j nodes."""
    logger.info(f"Loading {len(concepts):,d} concepts into Neo4j...")
    start = time.time()
    
    with driver.session() as session:
        for i in range(0, len(concepts), BATCH_SIZE):
            batch = concepts[i:i + BATCH_SIZE]
            params = [
                {
                    "concept_id": str(row[0]),  # Store as string for consistency
                    "concept_name": row[1],
                    "domain_id": row[2],
                    "vocabulary_id": row[3],
                    "concept_class_id": row[4],
                    "concept_code": row[5],
                }
                for row in batch
            ]
            session.run("""
                UNWIND $batch AS row
                CREATE (c:Concept {concept_id: row.concept_id})
                SET c.concept_name = row.concept_name,
                    c.domain_id = row.domain_id,
                    c.vocabulary_id = row.vocabulary_id,
                    c.concept_class_id = row.concept_class_id,
                    c.concept_code = row.concept_code
            """, batch=params)
            
            loaded = min(i + BATCH_SIZE, len(concepts))
            if loaded % 100000 == 0 or loaded >= len(concepts):
                elapsed = time.time() - start
                logger.info(f"  Loaded {loaded:,d}/{len(concepts):,d} concepts ({elapsed:.1f}s)")
    
    logger.info(f"  Concepts loaded in {time.time() - start:.1f}s")


def load_is_a_edges(driver, edges: List[Tuple]):
    """Batch load IS_A edges (child → parent)."""
    logger.info(f"Loading {len(edges):,d} IS_A edges into Neo4j...")
    start = time.time()
    
    with driver.session() as session:
        for i in range(0, len(edges), BATCH_SIZE):
            batch = edges[i:i + BATCH_SIZE]
            params = [
                {"child_id": str(row[0]), "parent_id": str(row[1])}
                for row in batch
            ]
            session.run("""
                UNWIND $batch AS row
                MATCH (child:Concept {concept_id: row.child_id})
                MATCH (parent:Concept {concept_id: row.parent_id})
                CREATE (child)-[:IS_A]->(parent)
            """, batch=params)
            
            loaded = min(i + BATCH_SIZE, len(edges))
            if loaded % 100000 == 0 or loaded >= len(edges):
                elapsed = time.time() - start
                logger.info(f"  Loaded {loaded:,d}/{len(edges):,d} IS_A edges ({elapsed:.1f}s)")
    
    logger.info(f"  IS_A edges loaded in {time.time() - start:.1f}s")


def load_maps_to_edges(driver, edges: List[Tuple]):
    """Batch load MAPS_TO edges."""
    logger.info(f"Loading {len(edges):,d} MAPS_TO edges into Neo4j...")
    start = time.time()
    
    with driver.session() as session:
        for i in range(0, len(edges), BATCH_SIZE):
            batch = edges[i:i + BATCH_SIZE]
            params = [
                {"src_id": str(row[0]), "tgt_id": str(row[1])}
                for row in batch
            ]
            session.run("""
                UNWIND $batch AS row
                MATCH (src:Concept {concept_id: row.src_id})
                MATCH (tgt:Concept {concept_id: row.tgt_id})
                CREATE (src)-[:MAPS_TO]->(tgt)
            """, batch=params)
            
            loaded = min(i + BATCH_SIZE, len(edges))
            if loaded % 100000 == 0 or loaded >= len(edges):
                elapsed = time.time() - start
                logger.info(f"  Loaded {loaded:,d}/{len(edges):,d} MAPS_TO edges ({elapsed:.1f}s)")
    
    logger.info(f"  MAPS_TO edges loaded in {time.time() - start:.1f}s")


# ── Step 3: Verify ─────────────────────────────────────────
def verify_graph(driver):
    """Print graph statistics and run sample queries."""
    logger.info("Verifying Neo4j v2 graph...")
    with driver.session() as session:
        # Node count
        node_count = session.run("MATCH (c:Concept) RETURN count(c) AS cnt").single()["cnt"]
        
        # Edge counts by type
        result = session.run("""
            MATCH ()-[r]->() 
            RETURN type(r) AS rel_type, count(r) AS cnt 
            ORDER BY cnt DESC
        """)
        edge_counts = [(r["rel_type"], r["cnt"]) for r in result]
        
        # Domain distribution
        result = session.run("""
            MATCH (c:Concept) 
            RETURN c.domain_id AS domain, count(c) AS cnt 
            ORDER BY cnt DESC LIMIT 10
        """)
        domains = [(r["domain"], r["cnt"]) for r in result]
    
    logger.info(f"  Nodes: {node_count:,d}")
    for rel_type, cnt in edge_counts:
        logger.info(f"  {rel_type} edges: {cnt:,d}")
    logger.info(f"  Top domains: {domains}")
    
    # Test: Traverse IS_A hierarchy for a known concept
    with driver.session() as session:
        # Ancestors of "Cerebral infarction" via IS_A
        result = session.run("""
            MATCH (c:Concept {concept_name: 'Cerebral infarction'})-[:IS_A*1..5]->(ancestor:Concept)
            RETURN ancestor.concept_name AS name, 
                   ancestor.concept_class_id AS class
            LIMIT 20
        """)
        ancestors = [(r["name"], r["class"]) for r in result]
        logger.info(f"  Test: Cerebral infarction ancestors (IS_A path, up to 5 hops):")
        for name, cls in ancestors:
            logger.info(f"    → {name} [{cls}]")
        
        # Descendants of "Cerebrovascular disease" via reverse IS_A (max 2 hops)
        result = session.run("""
            MATCH (parent:Concept {concept_name: 'Cerebrovascular disease'})<-[:IS_A*1..2]-(child:Concept)
            WHERE child.domain_id = 'Condition'
            RETURN child.concept_name AS name
            LIMIT 20
        """)
        descendants = [r["name"] for r in result]
        logger.info(f"  Test: Cerebrovascular disease descendants (2-hop IS_A): {len(descendants)} found")
        for name in descendants[:10]:
            logger.info(f"    ← {name}")


# ── Main ───────────────────────────────────────────────────
def main():
    total_start = time.time()
    logger.info("=" * 60)
    logger.info("OMOP CDM → Neo4j v2 ETL (CONCEPT_RELATIONSHIP direct edges)")
    logger.info("=" * 60)
    
    # Connect to PostgreSQL
    logger.info(f"Connecting to PostgreSQL: {PG_CONFIG['host']}:{PG_CONFIG['port']}")
    pg_conn = psycopg2.connect(**PG_CONFIG)
    
    # Connect to Neo4j v2
    logger.info(f"Connecting to Neo4j: {NEO4J_URI}")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    logger.info("  Connected to both databases")
    
    try:
        # Extract from PostgreSQL
        concepts = extract_concepts(pg_conn)
        is_a_edges = extract_is_a_relationships(pg_conn)
        maps_to_edges = extract_maps_to_relationships(pg_conn)
        
        # Load into Neo4j
        clear_database(driver)
        create_constraints(driver)
        load_concepts(driver, concepts)
        load_is_a_edges(driver, is_a_edges)
        load_maps_to_edges(driver, maps_to_edges)
        
        # Verify
        verify_graph(driver)
        
    finally:
        pg_conn.close()
        driver.close()
    
    total_time = time.time() - total_start
    logger.info(f"\n{'=' * 60}")
    logger.info(f"ETL complete in {total_time:.1f}s")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
