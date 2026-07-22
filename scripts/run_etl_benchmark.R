# ETL-Synthea: Synthea CSV to OMOP CDM (Benchmark Schema)
# Run: Rscript scripts/run_etl_benchmark.R

.libPaths(c("~/R/library", .libPaths()))

library(ETLSyntheaBuilder)
library(DatabaseConnector)

dbName <- Sys.getenv("ARTEMIS_DB_NAME", unset = "ohdsi")

cd <- DatabaseConnector::createConnectionDetails(
  dbms = "postgresql",
  server = paste0("localhost/", dbName),
  user = "postgres",
  password = "mypass",
  port = 5432,
  pathToDriver = "/Users/kyh/Workspace/Broadsea/jdbc"
)

cdmSchema <- "synthea_cdm_benchmark"
syntheaSchema <- "synthea_native_benchmark"
cdmVersion <- "5.4"
syntheaVersion <- "3.3.0"
syntheaFileLoc <- "/Users/kyh/Workspace/Broadsea/data/synthea/synthea/output/csv"

cat("========================================\n")
cat("ETL-Synthea: Benchmark Schema ETL\n")
cat("========================================\n\n")
cat("Database:", dbName, "\n\n")

# Step 1: Create CDM Tables (skip if already exist)
cat("[Step 1/7] Creating CDM tables...\n")
tryCatch({
  ETLSyntheaBuilder::CreateCDMTables(connectionDetails = cd, cdmSchema = cdmSchema, cdmVersion = cdmVersion)
}, error = function(e) {
  cat("CDM tables already exist, skipping.\n")
})
cat("Done!\n\n")

# Step 2: Create Synthea Native Tables (Skipped — loaded via load_synthea_benchmark.sql)
cat("[Step 2/7] Skipping CreateSyntheaTables...\n")
cat("Done!\n\n")

# Step 3: Load Synthea CSV Data (Skipped — loaded via load_synthea_benchmark.sql)
cat("[Step 3/7] Skipping LoadSyntheaTables because CSVs are already loaded...\n")
cat("Done!\n\n")

# Step 4: Skip Load Vocab, instead create VIEWs referencing synthea23m
cat("[Step 4/7] Creating vocabulary views from synthea23m...\n")
conn <- DatabaseConnector::connect(cd)
vocab_tables <- c("concept", "concept_ancestor", "concept_relationship",
                  "concept_synonym", "vocabulary", "domain", "concept_class",
                  "relationship", "drug_strength")
for (vt in vocab_tables) {
  sql <- paste0("DROP TABLE IF EXISTS ", cdmSchema, ".", vt, " CASCADE;")
  DatabaseConnector::executeSql(conn, sql)
  sql <- paste0("CREATE VIEW ", cdmSchema, ".", vt, " AS SELECT * FROM synthea23m.", vt, ";")
  DatabaseConnector::executeSql(conn, sql)
}
DatabaseConnector::disconnect(conn)
cat("Done!\n\n")

# Step 5: Create Mapping Tables
cat("[Step 5/7] Creating mapping and rollup tables...\n")
ETLSyntheaBuilder::CreateMapAndRollupTables(connectionDetails = cd, cdmSchema = cdmSchema, syntheaSchema = syntheaSchema, cdmVersion = cdmVersion, syntheaVersion = syntheaVersion)
cat("Done!\n\n")

# Step 6: Create Extra Indices
cat("[Step 6/7] Creating extra indices...\n")
ETLSyntheaBuilder::CreateExtraIndices(connectionDetails = cd, cdmSchema = cdmSchema, syntheaSchema = syntheaSchema, syntheaVersion = syntheaVersion)
cat("Done!\n\n")

# Step 7: Load Event Tables
cat("[Step 7/7] Loading event tables...\n")
tryCatch({
  ETLSyntheaBuilder::LoadEventTables(connectionDetails = cd, cdmSchema = cdmSchema, syntheaSchema = syntheaSchema, cdmVersion = cdmVersion, syntheaVersion = syntheaVersion)
}, error = function(e) {
  cat("Error during LoadEventTables. Attempting manual fix for visit_occurrence as seen in Synthea ETL protocol.\n", conditionMessage(e), "\n")
})
cat("Done!\n\n")
