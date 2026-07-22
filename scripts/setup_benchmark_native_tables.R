# Create Synthea native tables for a benchmark schema.
# Called by setup_all_benchmark_sources.sh
#
# Env vars:
#   ARTEMIS_DB_NAME           (default: postgres)
#   BENCHMARK_NATIVE_SCHEMA   (required, e.g. synthea_native_leader)

.libPaths(c("~/R/library", .libPaths()))

library(ETLSyntheaBuilder)
library(DatabaseConnector)

dbName <- Sys.getenv("ARTEMIS_DB_NAME", unset = "postgres")
syntheaSchema <- Sys.getenv("BENCHMARK_NATIVE_SCHEMA")
if (syntheaSchema == "") stop("BENCHMARK_NATIVE_SCHEMA env var required")

cd <- DatabaseConnector::createConnectionDetails(
  dbms = "postgresql",
  server = paste0("localhost/", dbName),
  user = "postgres",
  password = "mypass",
  port = 5432,
  pathToDriver = "/Users/kyh/Workspace/Broadsea/jdbc"
)

cat("Creating Synthea native tables in", syntheaSchema, "...\n")
tryCatch({
  ETLSyntheaBuilder::CreateSyntheaTables(
    connectionDetails = cd,
    syntheaSchema = syntheaSchema,
    syntheaVersion = "3.3.0"
  )
  cat("Done!\n")
}, error = function(e) {
  cat("Tables may already exist:", conditionMessage(e), "\n")
})
