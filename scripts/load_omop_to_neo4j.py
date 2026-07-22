"""
OMOP CDM → Neo4j Knowledge Graph ETL Script

Loads Standard Concepts and their hierarchical relationships from PostgreSQL
into Neo4j for KG-RAG in Agent 2.

Usage:
    conda run -n artemis python scripts/load_omop_to_neo4j.py
    
Prerequisites:
    - PostgreSQL with OMOP CDM running (synthea_cdm schema)
    - Neo4j running (docker compose up neo4j)
    - pip install neo4j psycopg2-binary
"""

import os
import time
import logging
from typing import List, Tuple

import psycopg2
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────
PG_CONFIG = {
    "host": os.getenv("PG_HOST", "localhost"),
    "port": int(os.getenv("PG_PORT", "5432")),
    "dbname": os.getenv("PG_DBNAME", "postgres"),
    "user": os.getenv("PG_USER", "postgres"),
    "password": os.getenv("PG_PASSWORD", os.getenv("POSTGRES_PASSWORD", "mypass")),
}

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "artemis_neo4j")

SCHEMA = "synthea_cdm"
BATCH_SIZE = 50000


# ── Step 1: Extract Standard Concepts from PostgreSQL ──────
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


def extract_ancestors(pg_conn) -> List[Tuple]:
    """Extract ancestor-descendant relationships (all separation levels).
    
    NOTE: This loads the FULL transitive closure for accurate IC calculation
    and complete descendant expansion in ancestor_climb. ~70M rows.
    Previous: sep BETWEEN 1 AND 3 (~15M rows) — caused partial desc_count.
    """
    logger.info("Extracting ancestor relationships from PostgreSQL (FULL transitive closure)...")
    cur = pg_conn.cursor()
    cur.execute(f"""
        SELECT ca.ancestor_concept_id, ca.descendant_concept_id, 
               ca.min_levels_of_separation, ca.max_levels_of_separation
        FROM {SCHEMA}.concept_ancestor ca
        JOIN {SCHEMA}.concept c1 ON ca.ancestor_concept_id = c1.concept_id
        JOIN {SCHEMA}.concept c2 ON ca.descendant_concept_id = c2.concept_id
        WHERE c1.standard_concept = 'S'
          AND c2.standard_concept = 'S'
          AND c1.invalid_reason IS NULL
          AND c2.invalid_reason IS NULL
          AND ca.min_levels_of_separation >= 1
          AND ca.ancestor_concept_id != ca.descendant_concept_id
    """)
    rows = cur.fetchall()
    logger.info(f"  Extracted {len(rows):,d} ancestor relationships (all levels)")
    return rows


def extract_relationships(pg_conn) -> List[Tuple]:
    """Extract semantic relationships (Maps to, Is a, etc.)."""
    logger.info("Extracting concept relationships from PostgreSQL...")
    cur = pg_conn.cursor()
    cur.execute(f"""
        SELECT cr.concept_id_1, cr.concept_id_2, cr.relationship_id
        FROM {SCHEMA}.concept_relationship cr
        JOIN {SCHEMA}.concept c1 ON cr.concept_id_1 = c1.concept_id
        JOIN {SCHEMA}.concept c2 ON cr.concept_id_2 = c2.concept_id
        WHERE cr.relationship_id IN ('Maps to', 'Is a', 'Subsumes', 'Mapped from')
          AND c1.invalid_reason IS NULL
          AND c2.invalid_reason IS NULL
          AND cr.invalid_reason IS NULL
    """)
    rows = cur.fetchall()
    logger.info(f"  Extracted {len(rows):,d} relationships")
    return rows


# ── Step 2: Load into Neo4j ────────────────────────────────
def create_constraints(driver):
    """Create indexes and constraints in Neo4j."""
    logger.info("Creating Neo4j constraints and indexes...")
    with driver.session() as session:
        # Unique constraint on concept_id
        session.run("""
            CREATE CONSTRAINT concept_id_unique IF NOT EXISTS
            FOR (c:Concept) REQUIRE c.concept_id IS UNIQUE
        """)
        # Index on domain_id for fast filtering
        session.run("""
            CREATE INDEX concept_domain IF NOT EXISTS
            FOR (c:Concept) ON (c.domain_id)
        """)
        # Index on vocabulary_id
        session.run("""
            CREATE INDEX concept_vocab IF NOT EXISTS
            FOR (c:Concept) ON (c.vocabulary_id)
        """)
        # Index on concept_name for text search
        session.run("""
            CREATE INDEX concept_name IF NOT EXISTS
            FOR (c:Concept) ON (c.concept_name)
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
                    "concept_id": row[0],
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
            
            if (i + BATCH_SIZE) % 50000 == 0 or i + BATCH_SIZE >= len(concepts):
                elapsed = time.time() - start
                logger.info(f"  Loaded {min(i + BATCH_SIZE, len(concepts)):,d}/{len(concepts):,d} "
                          f"concepts ({elapsed:.1f}s)")
    
    logger.info(f"  Concepts loaded in {time.time() - start:.1f}s")


def load_ancestors(driver, ancestors: List[Tuple]):
    """Batch load ancestor-descendant relationships."""
    logger.info(f"Loading {len(ancestors):,d} ancestor relationships into Neo4j...")
    start = time.time()
    
    with driver.session() as session:
        for i in range(0, len(ancestors), BATCH_SIZE):
            batch = ancestors[i:i + BATCH_SIZE]
            params = [
                {
                    "ancestor_id": row[0],
                    "descendant_id": row[1],
                    "min_sep": row[2],
                    "max_sep": row[3],
                }
                for row in batch
            ]
            session.run("""
                UNWIND $batch AS row
                MATCH (a:Concept {concept_id: row.ancestor_id})
                MATCH (d:Concept {concept_id: row.descendant_id})
                MERGE (a)-[r:HAS_DESCENDANT]->(d)
                SET r.min_levels_of_separation = row.min_sep,
                    r.max_levels_of_separation = row.max_sep
            """, batch=params)
            
            if (i + BATCH_SIZE) % 50000 == 0 or i + BATCH_SIZE >= len(ancestors):
                elapsed = time.time() - start
                logger.info(f"  Loaded {min(i + BATCH_SIZE, len(ancestors)):,d}/{len(ancestors):,d} "
                          f"ancestors ({elapsed:.1f}s)")
    
    logger.info(f"  Ancestors loaded in {time.time() - start:.1f}s")


def load_relationships(driver, relationships: List[Tuple]):
    """Batch load semantic relationships."""
    logger.info(f"Loading {len(relationships):,d} relationships into Neo4j...")
    start = time.time()
    
    with driver.session() as session:
        for i in range(0, len(relationships), BATCH_SIZE):
            batch = relationships[i:i + BATCH_SIZE]
            params = [
                {
                    "id1": row[0],
                    "id2": row[1],
                    "rel_type": row[2],
                }
                for row in batch
            ]
            # Use APOC to create dynamic relationship types
            session.run("""
                UNWIND $batch AS row
                MATCH (c1:Concept {concept_id: row.id1})
                MATCH (c2:Concept {concept_id: row.id2})
                CALL apoc.merge.relationship(c1, row.rel_type, {}, {}, c2) YIELD rel
                RETURN count(rel)
            """, batch=params)
            
            if (i + BATCH_SIZE) % 50000 == 0 or i + BATCH_SIZE >= len(relationships):
                elapsed = time.time() - start
                logger.info(f"  Loaded {min(i + BATCH_SIZE, len(relationships)):,d}/{len(relationships):,d} "
                          f"relationships ({elapsed:.1f}s)")
    
    logger.info(f"  Relationships loaded in {time.time() - start:.1f}s")


# ── Step 3: Verify ─────────────────────────────────────────
def verify_graph(driver):
    """Print graph statistics."""
    logger.info("Verifying Neo4j graph...")
    with driver.session() as session:
        # Node count
        result = session.run("MATCH (c:Concept) RETURN count(c) AS cnt")
        node_count = result.single()["cnt"]
        
        # Relationship count
        result = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
        rel_count = result.single()["cnt"]
        
        # Domain distribution
        result = session.run("""
            MATCH (c:Concept) 
            RETURN c.domain_id AS domain, count(c) AS cnt 
            ORDER BY cnt DESC LIMIT 10
        """)
        domains = [(r["domain"], r["cnt"]) for r in result]
        
        # Vocabulary distribution
        result = session.run("""
            MATCH (c:Concept) 
            RETURN c.vocabulary_id AS vocab, count(c) AS cnt 
            ORDER BY cnt DESC LIMIT 10
        """)
        vocabs = [(r["vocab"], r["cnt"]) for r in result]
    
    logger.info(f"  Nodes: {node_count:,d}")
    logger.info(f"  Relationships: {rel_count:,d}")
    logger.info(f"  Top domains: {domains}")
    logger.info(f"  Top vocabs: {vocabs}")
    
    # Test query: Find descendants of "Stroke"
    with driver.session() as session:
        result = session.run("""
            MATCH (a:Concept {concept_name: 'Cerebrovascular disease'})-[:HAS_DESCENDANT]->(d:Concept)
            WHERE d.domain_id = 'Condition'
            RETURN d.concept_id, d.concept_name
            LIMIT 10
        """)
        descendants = [(r["d.concept_id"], r["d.concept_name"]) for r in result]
        logger.info(f"  Test query (Cerebrovascular disease descendants): {len(descendants)} found")
        for cid, cname in descendants[:5]:
            logger.info(f"    {cid}: {cname}")


# ── Main ───────────────────────────────────────────────────
def main():
    total_start = time.time()
    logger.info("=" * 60)
    logger.info("OMOP CDM → Neo4j Knowledge Graph ETL")
    logger.info("=" * 60)
    
    # Connect to PostgreSQL
    logger.info(f"Connecting to PostgreSQL: {PG_CONFIG['host']}:{PG_CONFIG['port']}")
    pg_conn = psycopg2.connect(**PG_CONFIG)
    
    # Connect to Neo4j
    logger.info(f"Connecting to Neo4j: {NEO4J_URI}")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    logger.info("  Connected to both databases")
    
    try:
        # Extract from PostgreSQL
        concepts = extract_concepts(pg_conn)
        ancestors = extract_ancestors(pg_conn)
        relationships = extract_relationships(pg_conn)
        
        # Load into Neo4j
        create_constraints(driver)
        load_concepts(driver, concepts)
        load_ancestors(driver, ancestors)
        load_relationships(driver, relationships)
        
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
