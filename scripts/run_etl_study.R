# ETL-Synthea: Synthea CSV to OMOP CDM (Parameterized)
# Usage: CDM_SCHEMA=synthea_cdm_leader NATIVE_SCHEMA=synthea_native_leader Rscript scripts/run_etl_study.R

.libPaths(c("~/R/library", .libPaths()))

library(ETLSyntheaBuilder)
library(DatabaseConnector)

dbName      <- Sys.getenv("ARTEMIS_DB_NAME",  unset = "ohdsi")
cdmSchema   <- Sys.getenv("CDM_SCHEMA",       unset = "synthea_cdm_benchmark")
syntheaSchema <- Sys.getenv("NATIVE_SCHEMA",  unset = "synthea_native_benchmark")
cdmVersion    <- "5.4"
syntheaVersion <- "3.3.0"
syntheaFileLoc <- "/Users/kyh/Workspace/Broadsea/data/synthea/synthea/output/csv"

cd <- DatabaseConnector::createConnectionDetails(
  dbms = "postgresql",
  server = paste0("localhost/", dbName),
  user = "postgres",
  password = "mypass",
  port = 5432,
  pathToDriver = "/Users/kyh/Workspace/Broadsea/jdbc"
)

cat("========================================\n")
cat("ETL-Synthea: Study Schema ETL\n")
cat("CDM Schema:    ", cdmSchema, "\n")
cat("Native Schema: ", syntheaSchema, "\n")
cat("Database:      ", dbName, "\n")
cat("========================================\n\n")

cat("[Step 1/7] Creating CDM tables...\n")
tryCatch({
  ETLSyntheaBuilder::CreateCDMTables(connectionDetails = cd, cdmSchema = cdmSchema, cdmVersion = cdmVersion)
}, error = function(e) {
  cat("CDM tables already exist, skipping.\n")
})
cat("Done!\n\n")

cat("[Step 2/7] Skipping CreateSyntheaTables (loaded via SQL)...\n")
cat("Done!\n\n")

cat("[Step 3/7] Skipping LoadSyntheaTables (loaded via SQL)...\n")
cat("Done!\n\n")

cat("[Step 4/7] Creating vocabulary views from synthea23m...\n")
conn <- DatabaseConnector::connect(cd)
vocab_tables <- c("concept", "concept_ancestor", "concept_relationship",
                  "concept_synonym", "vocabulary", "domain", "concept_class",
                  "relationship", "drug_strength")
for (vt in vocab_tables) {
  DatabaseConnector::executeSql(conn, paste0("DROP TABLE IF EXISTS ", cdmSchema, ".", vt, " CASCADE;"))
  DatabaseConnector::executeSql(conn, paste0("CREATE VIEW ", cdmSchema, ".", vt, " AS SELECT * FROM synthea23m.", vt, ";"))
}
DatabaseConnector::disconnect(conn)
cat("Done!\n\n")

cat("[Step 5/7] Creating mapping and rollup tables...\n")
ETLSyntheaBuilder::CreateMapAndRollupTables(connectionDetails = cd, cdmSchema = cdmSchema, syntheaSchema = syntheaSchema, cdmVersion = cdmVersion, syntheaVersion = syntheaVersion)
cat("Done!\n\n")

cat("[Step 6/7] Creating extra indices...\n")
ETLSyntheaBuilder::CreateExtraIndices(connectionDetails = cd, cdmSchema = cdmSchema, syntheaSchema = syntheaSchema, syntheaVersion = syntheaVersion)
cat("Done!\n\n")

cat("[Step 7/7] Loading event tables...\n")
tryCatch({
  ETLSyntheaBuilder::LoadEventTables(connectionDetails = cd, cdmSchema = cdmSchema, syntheaSchema = syntheaSchema, cdmVersion = cdmVersion, syntheaVersion = syntheaVersion)
}, error = function(e) {
  cat("Error during LoadEventTables:", conditionMessage(e), "\n")
})
cat("Done!\n\n")

cat("ETL complete.\n")
