#!/bin/bash
# Neo4j CSV Bulk Import for ARTEMIS
# 10-100x faster than Cypher-based loading
#
# Steps:
#   1. Export concepts + relationships from PostgreSQL → CSV
#   2. Stop artemis-neo4j
#   3. neo4j-admin database import from CSV
#   4. Start artemis-neo4j

set -euo pipefail

SCHEMA="synthea_cdm"
PG_HOST="${OMOP_DB_HOST:-localhost}"
PG_PORT="${OMOP_DB_PORT:-5432}"
PG_DB="${OMOP_DB_NAME:-postgres}"
PG_USER="${OMOP_DB_USER:-postgres}"
PGPASSWORD="${OMOP_DB_PASS:-mypass}"
export PGPASSWORD

CONTAINER="artemis-neo4j"
CSV_DIR="/tmp/neo4j_import"
mkdir -p "$CSV_DIR"

echo "=== Step 1: Export CSVs from PostgreSQL ==="

echo "  Exporting concepts..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "\COPY (
    SELECT concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, concept_code
    FROM ${SCHEMA}.concept
    WHERE standard_concept = 'S' AND invalid_reason IS NULL
) TO '$CSV_DIR/concepts.csv' WITH (FORMAT CSV, HEADER)"

CONCEPT_COUNT=$(wc -l < "$CSV_DIR/concepts.csv")
echo "  Exported $((CONCEPT_COUNT - 1)) concepts"

echo "  Exporting ancestor relationships (FULL transitive closure)..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "\COPY (
    SELECT ca.ancestor_concept_id, ca.descendant_concept_id,
           ca.min_levels_of_separation, ca.max_levels_of_separation
    FROM ${SCHEMA}.concept_ancestor ca
    JOIN ${SCHEMA}.concept c1 ON ca.ancestor_concept_id = c1.concept_id
    JOIN ${SCHEMA}.concept c2 ON ca.descendant_concept_id = c2.concept_id
    WHERE c1.standard_concept = 'S'
      AND c2.standard_concept = 'S'
      AND c1.invalid_reason IS NULL
      AND c2.invalid_reason IS NULL
      AND ca.min_levels_of_separation >= 1
      AND ca.ancestor_concept_id != ca.descendant_concept_id
) TO '$CSV_DIR/ancestors.csv' WITH (FORMAT CSV, HEADER)"

ANCESTOR_COUNT=$(wc -l < "$CSV_DIR/ancestors.csv")
echo "  Exported $((ANCESTOR_COUNT - 1)) ancestor relationships"

echo "  Exporting semantic relationships..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "\COPY (
    SELECT cr.concept_id_1, cr.concept_id_2, cr.relationship_id
    FROM ${SCHEMA}.concept_relationship cr
    JOIN ${SCHEMA}.concept c1 ON cr.concept_id_1 = c1.concept_id
    JOIN ${SCHEMA}.concept c2 ON cr.concept_id_2 = c2.concept_id
    WHERE cr.relationship_id IN ('Maps to', 'Is a', 'Subsumes', 'Mapped from')
      AND c1.invalid_reason IS NULL
      AND c2.invalid_reason IS NULL
      AND cr.invalid_reason IS NULL
) TO '$CSV_DIR/relationships.csv' WITH (FORMAT CSV, HEADER)"

REL_COUNT=$(wc -l < "$CSV_DIR/relationships.csv")
echo "  Exported $((REL_COUNT - 1)) relationships"

echo ""
echo "=== Step 2: Create neo4j-admin import header files ==="

# Node header
cat > "$CSV_DIR/concepts_header.csv" << 'EOF'
concept_id:ID(Concept),concept_name,domain_id,vocabulary_id,concept_class_id,concept_code
EOF

# HAS_DESCENDANT relationship header
cat > "$CSV_DIR/ancestors_header.csv" << 'EOF'
:START_ID(Concept),:END_ID(Concept),min_levels_of_separation:int,max_levels_of_separation:int
EOF

# Semantic relationship header
cat > "$CSV_DIR/relationships_header.csv" << 'EOF'
:START_ID(Concept),:END_ID(Concept),:TYPE
EOF

echo "  Headers created"

echo ""
echo "=== Step 3: Copy CSVs into container ==="
docker cp "$CSV_DIR/." "$CONTAINER:/var/lib/neo4j/import/"
echo "  Files copied to $CONTAINER:/var/lib/neo4j/import/"

echo ""
echo "=== Step 4: Stop Neo4j and run bulk import ==="
docker stop "$CONTAINER"

# Drop existing database and import
docker run --rm \
    -v artemis_neo4j_data:/data \
    -v "$CSV_DIR:/import" \
    neo4j:5-community \
    neo4j-admin database import full \
    --overwrite-destination \
    --nodes=Concept="/import/concepts_header.csv,/import/concepts.csv" \
    --relationships=HAS_DESCENDANT="/import/ancestors_header.csv,/import/ancestors.csv" \
    --skip-bad-relationships=true \
    --skip-duplicate-nodes=true \
    neo4j

echo ""
echo "=== Step 5: Start Neo4j ==="
docker start "$CONTAINER"

echo ""
echo "  Waiting for Neo4j to be ready..."
for i in $(seq 1 30); do
    if docker exec "$CONTAINER" cypher-shell -u neo4j -p artemis_neo4j "RETURN 1" 2>/dev/null; then
        echo "  Neo4j is ready!"
        break
    fi
    sleep 2
done

echo ""
echo "=== Step 6: Create indexes ==="
docker exec "$CONTAINER" cypher-shell -u neo4j -p artemis_neo4j "
CREATE INDEX concept_domain IF NOT EXISTS FOR (c:Concept) ON (c.domain_id);
CREATE INDEX concept_vocab IF NOT EXISTS FOR (c:Concept) ON (c.vocabulary_id);
CREATE INDEX concept_name IF NOT EXISTS FOR (c:Concept) ON (c.concept_name);
CREATE CONSTRAINT concept_id_unique IF NOT EXISTS FOR (c:Concept) REQUIRE c.concept_id IS UNIQUE;
"

echo ""
echo "=== Step 7: Verify ==="
docker exec "$CONTAINER" cypher-shell -u neo4j -p artemis_neo4j "
MATCH (c:Concept) RETURN count(c) AS nodes;
"
docker exec "$CONTAINER" cypher-shell -u neo4j -p artemis_neo4j "
MATCH ()-[r:HAS_DESCENDANT]->() RETURN count(r) AS relationships;
"

echo ""
echo "=== Done! ==="
