# ETL-Synthea: Per-study benchmark schema ETL
# Called by setup_all_benchmark_sources.sh
#
# Assumes native schema is already populated with CSV data.
# Runs: CDM tables, vocab views, mapping, indices, event tables.
#
# Env vars:
#   ARTEMIS_DB_NAME           (default: postgres)
#   BENCHMARK_CDM_SCHEMA      (required, e.g. synthea_cdm_leader)
#   BENCHMARK_NATIVE_SCHEMA   (required, e.g. synthea_native_leader)

.libPaths(c("~/R/library", .libPaths()))

library(ETLSyntheaBuilder)
library(DatabaseConnector)

dbName <- Sys.getenv("ARTEMIS_DB_NAME", unset = "postgres")
cdmSchema <- Sys.getenv("BENCHMARK_CDM_SCHEMA")
syntheaSchema <- Sys.getenv("BENCHMARK_NATIVE_SCHEMA")

if (cdmSchema == "") stop("BENCHMARK_CDM_SCHEMA env var required")
if (syntheaSchema == "") stop("BENCHMARK_NATIVE_SCHEMA env var required")

cdmVersion <- "5.4"
syntheaVersion <- "3.3.0"

cd <- DatabaseConnector::createConnectionDetails(
  dbms = "postgresql",
  server = paste0("localhost/", dbName),
  user = "postgres",
  password = "mypass",
  port = 5432,
  pathToDriver = "/Users/kyh/Workspace/Broadsea/jdbc"
)

cat("========================================\n")
cat("ETL-Synthea: Per-Study Benchmark\n")
cat("  CDM schema:    ", cdmSchema, "\n")
cat("  Native schema: ", syntheaSchema, "\n")
cat("  Database:      ", dbName, "\n")
cat("========================================\n\n")

# Step 1: Create CDM Tables
cat("[1/5] Creating CDM tables...\n")
tryCatch({
  ETLSyntheaBuilder::CreateCDMTables(
    connectionDetails = cd,
    cdmSchema = cdmSchema,
    cdmVersion = cdmVersion
  )
}, error = function(e) {
  cat("CDM tables may already exist:", conditionMessage(e), "\n")
})
cat("Done!\n\n")

# Step 2: Create vocabulary VIEWs referencing synthea23m
cat("[2/5] Creating vocabulary views from synthea23m...\n")
conn <- DatabaseConnector::connect(cd)
vocab_tables <- c(
  "concept", "concept_ancestor", "concept_relationship",
  "concept_synonym", "vocabulary", "domain", "concept_class",
  "relationship", "drug_strength"
)
for (vt in vocab_tables) {
  tryCatch({
    sql <- paste0("DROP TABLE IF EXISTS ", cdmSchema, ".", vt, " CASCADE;")
    DatabaseConnector::executeSql(conn, sql)
    sql <- paste0("DROP VIEW IF EXISTS ", cdmSchema, ".", vt, " CASCADE;")
    DatabaseConnector::executeSql(conn, sql)
    sql <- paste0("CREATE VIEW ", cdmSchema, ".", vt, " AS SELECT * FROM synthea23m.", vt, ";")
    DatabaseConnector::executeSql(conn, sql)
  }, error = function(e) {
    cat("  Warning for", vt, ":", conditionMessage(e), "\n")
  })
}
DatabaseConnector::disconnect(conn)
cat("Done!\n\n")

# Step 3: Create Mapping Tables
cat("[3/5] Creating mapping and rollup tables...\n")
ETLSyntheaBuilder::CreateMapAndRollupTables(
  connectionDetails = cd,
  cdmSchema = cdmSchema,
  syntheaSchema = syntheaSchema,
  cdmVersion = cdmVersion,
  syntheaVersion = syntheaVersion
)
cat("Done!\n\n")

# Step 4: Create Extra Indices
cat("[4/5] Creating extra indices...\n")
ETLSyntheaBuilder::CreateExtraIndices(
  connectionDetails = cd,
  cdmSchema = cdmSchema,
  syntheaSchema = syntheaSchema,
  syntheaVersion = syntheaVersion
)
cat("Done!\n\n")

# Step 5: Load Event Tables
cat("[5/5] Loading event tables...\n")
tryCatch({
  ETLSyntheaBuilder::LoadEventTables(
    connectionDetails = cd,
    cdmSchema = cdmSchema,
    syntheaSchema = syntheaSchema,
    cdmVersion = cdmVersion,
    syntheaVersion = syntheaVersion
  )
}, error = function(e) {
  cat("Error during LoadEventTables:", conditionMessage(e), "\n")
})
cat("Done!\n\n")

cat("ETL complete for ", cdmSchema, "!\n")
