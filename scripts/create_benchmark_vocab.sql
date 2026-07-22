-- ============================================================
-- Replace vocab VIEWs with materialized subset tables
-- ============================================================

-- Drop VIEWs first (they reference synthea23m)
DROP VIEW IF EXISTS synthea_cdm_benchmark.concept CASCADE;
DROP VIEW IF EXISTS synthea_cdm_benchmark.concept_ancestor CASCADE;
DROP VIEW IF EXISTS synthea_cdm_benchmark.concept_relationship CASCADE;
DROP VIEW IF EXISTS synthea_cdm_benchmark.vocabulary CASCADE;
DROP VIEW IF EXISTS synthea_cdm_benchmark.domain CASCADE;
DROP VIEW IF EXISTS synthea_cdm_benchmark.concept_class CASCADE;
DROP VIEW IF EXISTS synthea_cdm_benchmark.relationship CASCADE;
DROP VIEW IF EXISTS synthea_cdm_benchmark.concept_synonym CASCADE;

-- Recreate _expanded_concepts (was dropped in cleanup)
DROP TABLE IF EXISTS synthea_cdm_benchmark._used_concepts;
CREATE TABLE synthea_cdm_benchmark._used_concepts AS
SELECT DISTINCT concept_id FROM (
    SELECT drug_concept_id AS concept_id FROM synthea_cdm_benchmark.drug_era
    UNION SELECT condition_concept_id FROM synthea_cdm_benchmark.condition_occurrence
    UNION SELECT measurement_concept_id FROM synthea_cdm_benchmark.measurement
    UNION SELECT observation_concept_id FROM synthea_cdm_benchmark.observation
    UNION SELECT procedure_concept_id FROM synthea_cdm_benchmark.procedure_occurrence
    UNION SELECT drug_concept_id FROM synthea_cdm_benchmark.drug_exposure
    UNION SELECT visit_concept_id FROM synthea_cdm_benchmark.visit_occurrence
    UNION SELECT gender_concept_id FROM synthea_cdm_benchmark.person
    UNION SELECT race_concept_id FROM synthea_cdm_benchmark.person
    UNION SELECT ethnicity_concept_id FROM synthea_cdm_benchmark.person
) sub WHERE concept_id IS NOT NULL AND concept_id != 0;

DROP TABLE IF EXISTS synthea_cdm_benchmark._expanded_concepts;
CREATE TABLE synthea_cdm_benchmark._expanded_concepts AS
SELECT DISTINCT concept_id FROM (
    SELECT concept_id FROM synthea_cdm_benchmark._used_concepts
    UNION SELECT ca.ancestor_concept_id
    FROM synthea23m.concept_ancestor ca
    JOIN synthea_cdm_benchmark._used_concepts uc ON ca.descendant_concept_id = uc.concept_id
    UNION SELECT ca.descendant_concept_id
    FROM synthea23m.concept_ancestor ca
    JOIN synthea_cdm_benchmark._used_concepts uc ON ca.ancestor_concept_id = uc.concept_id
) expanded;

CREATE INDEX idx_expanded_cid ON synthea_cdm_benchmark._expanded_concepts (concept_id);
ANALYZE synthea_cdm_benchmark._expanded_concepts;

-- Now create real tables
CREATE TABLE synthea_cdm_benchmark.concept AS
SELECT c.* FROM synthea23m.concept c
JOIN synthea_cdm_benchmark._expanded_concepts ec ON c.concept_id = ec.concept_id;
CREATE INDEX idx_bm_concept_id ON synthea_cdm_benchmark.concept (concept_id);
CREATE INDEX idx_bm_concept_code ON synthea_cdm_benchmark.concept (concept_code);

CREATE TABLE synthea_cdm_benchmark.concept_ancestor AS
SELECT ca.* FROM synthea23m.concept_ancestor ca
WHERE ca.ancestor_concept_id IN (SELECT concept_id FROM synthea_cdm_benchmark._expanded_concepts)
  AND ca.descendant_concept_id IN (SELECT concept_id FROM synthea_cdm_benchmark._expanded_concepts);
CREATE INDEX idx_bm_ca_ancestor ON synthea_cdm_benchmark.concept_ancestor (ancestor_concept_id);
CREATE INDEX idx_bm_ca_descendant ON synthea_cdm_benchmark.concept_ancestor (descendant_concept_id);

CREATE TABLE synthea_cdm_benchmark.concept_relationship AS
SELECT cr.* FROM synthea23m.concept_relationship cr
WHERE cr.concept_id_1 IN (SELECT concept_id FROM synthea_cdm_benchmark._expanded_concepts)
  AND cr.concept_id_2 IN (SELECT concept_id FROM synthea_cdm_benchmark._expanded_concepts);
CREATE INDEX idx_bm_cr_1 ON synthea_cdm_benchmark.concept_relationship (concept_id_1);
CREATE INDEX idx_bm_cr_2 ON synthea_cdm_benchmark.concept_relationship (concept_id_2);

CREATE TABLE synthea_cdm_benchmark.vocabulary AS SELECT * FROM synthea23m.vocabulary;
CREATE TABLE synthea_cdm_benchmark.domain AS SELECT * FROM synthea23m.domain;
CREATE TABLE synthea_cdm_benchmark.concept_class AS SELECT * FROM synthea23m.concept_class;
CREATE TABLE synthea_cdm_benchmark.relationship AS SELECT * FROM synthea23m.relationship;
CREATE TABLE synthea_cdm_benchmark.concept_synonym AS
SELECT cs.* FROM synthea23m.concept_synonym cs
JOIN synthea_cdm_benchmark._expanded_concepts ec ON cs.concept_id = ec.concept_id;

-- ANALYZE all
ANALYZE synthea_cdm_benchmark.concept;
ANALYZE synthea_cdm_benchmark.concept_ancestor;
ANALYZE synthea_cdm_benchmark.concept_relationship;
ANALYZE synthea_cdm_benchmark.vocabulary;
ANALYZE synthea_cdm_benchmark.domain;
ANALYZE synthea_cdm_benchmark.concept_class;
ANALYZE synthea_cdm_benchmark.relationship;

-- Cleanup
DROP TABLE IF EXISTS synthea_cdm_benchmark._used_concepts;
DROP TABLE IF EXISTS synthea_cdm_benchmark._expanded_concepts;

-- Report
SELECT tablename, pg_size_pretty(pg_total_relation_size('synthea_cdm_benchmark.' || tablename)) as size
FROM pg_tables WHERE schemaname='synthea_cdm_benchmark'
AND tablename IN ('concept','concept_ancestor','concept_relationship','vocabulary','domain','concept_class','relationship','concept_synonym')
ORDER BY tablename;
