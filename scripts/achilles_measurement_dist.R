#!/usr/bin/env Rscript
# Populate ACHILLES analysis 1815 ("Distribution of numeric values, by
# measurement_concept_id and unit_concept_id") for one CDM schema.
#
# Why this exists
# ---------------
# The assembly-time threshold-scale gate (see src/services/measurement_scale.py)
# needs a per-measurement-concept value distribution to decide whether a protocol
# threshold and the CDM's stored values are expressed in the same unit. ARISTOTLE
# is the motivating case: the protocol says "platelet count <= 100,000/mm3", the
# CDM stores 101 (x10^3/uL, i.e. 101,000/mm3 -- deliberately just ABOVE the
# cutoff), and unit_concept_id is 0. Compared as bare numbers, 101 <= 100000 is
# true, so every patient carrying the lab is excluded and the cohort collapses.
#
# ACHILLES is the OHDSI-canonical home for that distribution, so the gate reads
# 1815 rather than growing its own scan of MEASUREMENT.
#
# Two deliberate parameter choices
# --------------------------------
# smallCellCount = 0
#   The Achilles default of 5 SUPPRESSES strata below the threshold. That is a
#   privacy control for shared result sets; here it would silently delete exactly
#   the rare-measurement rows the gate must reason about, and a missing stratum is
#   indistinguishable from "no scale problem". These are synthetic benchmark CDMs,
#   so nothing is suppressed.
#
# defaultAnalysesOnly = FALSE
#   Combined with an explicit analysisIds, this stops Achilles from re-filtering
#   the requested list against its own default set.
#
# Usage
#   Rscript achilles_measurement_dist.R <cdm_schema> [results_schema]
# Example
#   Rscript achilles_measurement_dist.R synthea_cdm_aristotle
#
# Runs inside the broadsea-hades container, which carries Achilles + the JDBC
# drivers. It writes ONLY achilles_* tables; the WebAPI/Heracles tables that share
# the results schema are untouched.

suppressPackageStartupMessages({
  library(DatabaseConnector)
  library(Achilles)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("usage: achilles_measurement_dist.R <cdm_schema> [results_schema]")
}
cdmSchema <- args[1]
resultsSchema <- if (length(args) >= 2) args[2] else paste0(cdmSchema, "_results")

# Analysis 1815 is the payload. 1807 (record counts by concept + unit) is kept
# because it is what distinguishes "this concept has one unit" from "this concept
# is recorded in two different units", which changes whether a single scale factor
# is even meaningful.
ANALYSIS_IDS <- c(1807, 1815)

MEASUREMENT_DIST_ANALYSIS <- 1815

host <- Sys.getenv("ATLASDB_HOST", "broadsea-atlasdb")
port <- as.integer(Sys.getenv("ATLASDB_PORT", "5432"))
db <- Sys.getenv("ATLASDB_NAME", "postgres")
user <- Sys.getenv("ATLASDB_USER", "postgres")
pw <- Sys.getenv("ATLASDB_PASSWORD", "mypass")

outputFolder <- file.path("/tmp/achilles_out", cdmSchema)
dir.create(outputFolder, recursive = TRUE, showWarnings = FALSE)

started <- format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")
cat(sprintf(
  "[achilles] start=%s cdm=%s results=%s analyses=%s output=%s pid=%s\n",
  started, cdmSchema, resultsSchema,
  paste(ANALYSIS_IDS, collapse = ","), outputFolder, Sys.getpid()
))

connectionDetails <- createConnectionDetails(
  dbms = "postgresql",
  server = paste0(host, "/", db),
  user = user,
  password = pw,
  port = port
)

# Fail fast and loud on a missing/empty source rather than producing an empty
# 1815 that the gate would read as "no scale problem".
# Read the value positionally. DatabaseConnector 7 does not force column names to
# upper case the way earlier versions did, so a `$N` accessor silently yields NULL
# and the guard below fails with "argument is of length zero" -- the precheck
# breaking instead of the thing it checks.
con <- connect(connectionDetails)
measWithValue <- querySql(con, sprintf(
  "SELECT count(*) AS n FROM %s.measurement WHERE value_as_number IS NOT NULL", cdmSchema
))[[1]][1]
disconnect(con)
cat(sprintf("[achilles] precheck: %s.measurement rows with a numeric value = %d\n",
            cdmSchema, measWithValue))
if (measWithValue == 0) {
  stop(sprintf("%s.measurement has no numeric values; analysis %d would be empty",
               cdmSchema, MEASUREMENT_DIST_ANALYSIS))
}

result <- achilles(
  connectionDetails = connectionDetails,
  cdmDatabaseSchema = cdmSchema,
  resultsDatabaseSchema = resultsSchema,
  vocabDatabaseSchema = cdmSchema,
  sourceName = cdmSchema,
  analysisIds = ANALYSIS_IDS,
  defaultAnalysesOnly = FALSE,
  createTable = TRUE,
  smallCellCount = 0,
  cdmVersion = "5",
  createIndices = FALSE,
  numThreads = 1,
  outputFolder = outputFolder,
  verboseMode = TRUE
)

# Verify the payload landed, and say what it contains. A run that "succeeds" and
# writes zero distribution rows is the failure this check exists to catch.
con <- connect(connectionDetails)
n <- querySql(con, sprintf(
  "SELECT count(*) AS n FROM %s.achilles_results_dist WHERE analysis_id = %d",
  resultsSchema, MEASUREMENT_DIST_ANALYSIS
))[[1]][1]
cat(sprintf("[achilles] analysis %d rows written: %d\n", MEASUREMENT_DIST_ANALYSIS, n))
if (n > 0) {
  print(querySql(con, sprintf(
    "SELECT stratum_1 AS measurement_concept_id, stratum_2 AS unit_concept_id,
            count_value, min_value, median_value, max_value
     FROM %s.achilles_results_dist
     WHERE analysis_id = %d
     ORDER BY count_value DESC",
    resultsSchema, MEASUREMENT_DIST_ANALYSIS
  )))
}
disconnect(con)

if (n == 0) {
  stop(sprintf("analysis %d produced no rows", MEASUREMENT_DIST_ANALYSIS))
}
cat(sprintf("[achilles] done=%s\n", format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")))
