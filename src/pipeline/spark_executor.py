"""
PySpark-based cohort SQL execution engine.

Uses OHDSI SqlRender's official Spark dialect. Reads CDM tables from
PostgreSQL via JDBC, executes CIRCE SQL in Spark, writes cohort
results back to PostgreSQL.
"""
import glob as _glob
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# CDM tables to register as Spark views from PostgreSQL
CDM_TABLES = [
    "person",
    "observation_period",
    "condition_occurrence",
    "drug_exposure",
    "drug_era",
    "condition_era",
    "measurement",
    "procedure_occurrence",
    "visit_occurrence",
    "observation",
    "device_exposure",
    "death",
]

# Vocabulary tables that may be VIEWs referencing synthea23m.
# Read from the vocab source schema (synthea23m) instead of the CDM schema.
VOCAB_TABLES = [
    "concept",
    "concept_ancestor",
    "concept_relationship",
    "vocabulary",
    "drug_strength",
]

# Regex for valid SQL identifier (schema/table names)
_VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_schema(name: str) -> None:
    """Raise ValueError if name is not a safe SQL identifier."""
    if not _VALID_IDENTIFIER.match(name):
        raise ValueError(
            f"Invalid schema/identifier '{name}': must match ^[a-zA-Z_][a-zA-Z0-9_]*$"
        )


def render_spark_sql(
    spark_sql: str,
    cdm_schema: str,
    results_schema: str,
    cohort_id: int,
    temp_schema: str = "spark_temp",
    vocab_schema: str = "synthea23m",
) -> str:
    """Render a SqlRender Spark-dialect SQL template by substituting all placeholders.

    Substitutes the six standard OHDSI placeholders and strips ``USING DELTA``.
    Vocabulary schema is separate from CDM schema because per-study CDM schemas
    use VIEWs that Spark JDBC cannot read — vocabulary tables are registered
    from the shared ``vocab_schema`` instead.

    Args:
        spark_sql: Raw SQL string from SqlRender with ``@`` placeholders.
        cdm_schema: Schema containing CDM clinical tables.
        results_schema: Schema to write cohort results into.
        cohort_id: Cohort definition ID.
        temp_schema: Spark database for intermediate temp tables.
        vocab_schema: Schema containing vocabulary tables (default ``synthea23m``).

    Returns:
        Rendered SQL string ready for Spark execution.
    """
    _validate_schema(cdm_schema)
    _validate_schema(results_schema)
    _validate_schema(temp_schema)
    _validate_schema(vocab_schema)

    rendered = spark_sql

    # Replace schema placeholders with empty string so all table references
    # become unqualified (e.g. "person" not "synthea_cdm_leader.person").
    # This matches Spark's temp views registered by _register_cdm_tables.
    # The dot after the schema name is also removed.
    rendered = rendered.replace("@vocabulary_database_schema.", "")
    rendered = rendered.replace("@cdm_database_schema.", "")
    # Results schema keeps qualification for cohort INSERT target
    rendered = rendered.replace("@target_database_schema", results_schema)
    rendered = rendered.replace("@target_cohort_table", "cohort")
    rendered = rendered.replace("@target_cohort_id", str(cohort_id))
    rendered = rendered.replace("@temp_database_schema", temp_schema)

    # Strip USING DELTA - Spark managed tables work without Delta Lake runtime
    rendered = rendered.replace(" USING DELTA", "")
    rendered = rendered.replace("\nUSING DELTA", "")
    rendered = rendered.replace("USING DELTA", "")

    return rendered


class SparkCohortExecutor:
    """Execute OHDSI CIRCE cohort SQL via PySpark with JDBC CDM access.

    Reads CDM tables from PostgreSQL via JDBC, executes rendered CIRCE SQL
    in Spark's columnar engine, and writes cohort results back to PostgreSQL.

    Args:
        pg_host: PostgreSQL hostname.
        pg_port: PostgreSQL port (default 5432).
        pg_dbname: PostgreSQL database name.
        pg_user: PostgreSQL username.
        pg_password: PostgreSQL password.
        jdbc_jar_path: Filesystem path to the PostgreSQL JDBC driver JAR.
    """

    # @MX:ANCHOR: Central entry point for PySpark cohort execution
    # @MX:REASON: Called from orchestrator and pipeline modules; owns Spark lifecycle

    def __init__(
        self,
        pg_host: str,
        pg_port: int = 5432,
        pg_dbname: str = "postgres",
        pg_user: str = "postgres",
        pg_password: str = "",
        jdbc_jar_path: str = "/app/jdbc/postgresql-42.7.3.jar",
    ) -> None:
        self.pg_host = pg_host
        self.pg_port = pg_port
        self.pg_dbname = pg_dbname
        self.pg_user = pg_user
        self.pg_password = pg_password
        self.jdbc_jar_path = jdbc_jar_path

        self._spark: Optional[object] = None  # lazy-initialized SparkSession

    @property
    def pg_jdbc_url(self) -> str:
        """Build JDBC connection URL for PostgreSQL."""
        return f"jdbc:postgresql://{self.pg_host}:{self.pg_port}/{self.pg_dbname}"

    def _get_or_create_session(self) -> object:
        """Return the existing SparkSession or create one with JDBC support.

        Lazy import of pyspark to avoid import-time errors in non-Spark environments.
        """
        if self._spark is not None:
            return self._spark

        # Lazy import - pyspark must not be imported at module level
        from pyspark.sql import SparkSession  # type: ignore[import]

        logger.info("Creating SparkSession with JDBC jar: %s", self.jdbc_jar_path)
        self._spark = (
            SparkSession.builder.master("local[*]")
            .config("spark.jars", self.jdbc_jar_path)
            .config("spark.driver.memory", "8g")
            .config("spark.sql.warehouse.dir", "/tmp/spark-warehouse")
            .appName("ArtemisSparkCohortExecutor")
            .getOrCreate()
        )
        return self._spark

    def _jdbc_properties(self) -> dict:
        """Return JDBC connection properties dict for Spark DataFrame reads."""
        return {
            "user": self.pg_user,
            "password": self.pg_password,
            "driver": "org.postgresql.Driver",
        }

    def _register_cdm_tables(
        self,
        spark: object,
        cdm_schema: str,
        vocab_schema: str = "synthea23m",
    ) -> None:
        """Read CDM tables from PostgreSQL via JDBC and register as Spark SQL views.

        Clinical tables (person, drug_era, etc.) are read from ``cdm_schema``.
        Vocabulary tables (concept, concept_ancestor, etc.) are read from
        ``vocab_schema`` because per-study CDM schemas use VIEWs that reference
        the shared vocabulary schema, and Spark JDBC cannot read PostgreSQL VIEWs.

        Args:
            spark: Active SparkSession.
            cdm_schema: PostgreSQL schema containing clinical CDM tables.
            vocab_schema: PostgreSQL schema containing vocabulary tables
                (default: ``"synthea23m"``).
        """
        from pyspark.sql import SparkSession  # type: ignore[import]

        spark = spark  # type: SparkSession

        spark.sql(f"CREATE DATABASE IF NOT EXISTS {cdm_schema}")
        spark.catalog.setCurrentDatabase(cdm_schema)

        props = self._jdbc_properties()
        registered = 0

        # Register clinical tables as temp views (unqualified names).
        # Schema-qualified references are stripped by render_spark_sql.
        for table in CDM_TABLES:
            full_table = f"{cdm_schema}.{table}"
            try:
                df = spark.read.jdbc(
                    url=self.pg_jdbc_url, table=full_table, properties=props,
                )
                df.createOrReplaceTempView(table)
                registered += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not register CDM table %s: %s", full_table, exc)

        # Register vocabulary tables. Large tables (concept_ancestor 75M+)
        # are read from pre-exported Parquet files to avoid JDBC OOM.
        # Smaller vocab tables fall back to JDBC if Parquet not available.
        parquet_dir = os.environ.get("SPARK_PARQUET_DIR", "/app/tmp/parquet")
        for table in VOCAB_TABLES:
            parquet_path = os.path.join(parquet_dir, f"{table}.parquet")
            parquet_glob = os.path.join(parquet_dir, f"{table}_part*.parquet")

            try:
                part_files = sorted(_glob.glob(parquet_glob))
                if part_files:
                    # Multi-part Parquet (e.g. concept_ancestor)
                    df = spark.read.parquet(*part_files)
                    logger.info("Loaded %s from %d Parquet parts", table, len(part_files))
                elif os.path.isfile(parquet_path):
                    df = spark.read.parquet(parquet_path)
                    logger.info("Loaded %s from Parquet", table)
                else:
                    # Fallback to JDBC for small tables
                    full_table = f"{vocab_schema}.{table}"
                    df = spark.read.jdbc(
                        url=self.pg_jdbc_url, table=full_table, properties=props,
                    )
                    logger.info("Loaded %s from JDBC (no Parquet found)", table)

                df.createOrReplaceTempView(table)
                registered += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not register vocab table %s: %s", table, exc)

        total = len(CDM_TABLES) + len(VOCAB_TABLES)
        logger.info(
            "Registered %d/%d tables (CDM from '%s', vocab from '%s')",
            registered, total, cdm_schema, vocab_schema,
        )

    def execute_cohort_sql(
        self,
        rendered_sql: str,
        cdm_schema: str,
        results_schema: str,
        cohort_id: int,
    ) -> int:
        """Execute rendered CIRCE SQL in Spark and return the resulting person count.

        Steps:
            1. Obtain SparkSession.
            2. Register CDM tables from PostgreSQL via JDBC.
            3. Create a Spark database for temp tables used by CIRCE SQL.
            4. Split SQL on ``;`` and execute each non-empty statement.
            5. Count distinct ``subject_id`` values from the cohort result view.
            6. Write cohort results back to PostgreSQL.
            7. Fall back to a direct PostgreSQL count if Spark count fails.

        Args:
            rendered_sql: Fully substituted CIRCE SQL (from ``render_spark_sql``).
            cdm_schema: PostgreSQL schema containing CDM tables.
            results_schema: PostgreSQL schema where cohort results are written.
            cohort_id: Cohort ID used in cohort table writes.

        Returns:
            Number of distinct subjects in the generated cohort.
        """
        spark = self._get_or_create_session()

        # Register CDM tables as Spark views
        self._register_cdm_tables(spark, cdm_schema)

        # Create Spark databases for temp tables and results
        spark.sql("CREATE DATABASE IF NOT EXISTS spark_temp")  # type: ignore[union-attr]
        spark.sql(f"CREATE DATABASE IF NOT EXISTS {results_schema}")  # type: ignore[union-attr]

        # Pre-create cohort table in results database so CIRCE INSERT works.
        # DROP first to avoid LOCATION_ALREADY_EXISTS from prior runs.
        spark.sql(f"DROP TABLE IF EXISTS {results_schema}.cohort")  # type: ignore[union-attr]
        spark.sql(  # type: ignore[union-attr]
            f"CREATE TABLE {results_schema}.cohort ("
            "cohort_definition_id BIGINT, subject_id BIGINT, "
            "cohort_start_date DATE, cohort_end_date DATE)"
        )

        # Execute each SQL statement individually
        statements = [s.strip() for s in rendered_sql.split(";") if s.strip()]
        logger.info("Executing %d SQL statements via Spark", len(statements))

        for i, stmt in enumerate(statements, start=1):
            try:
                spark.sql(stmt)  # type: ignore[union-attr]
                logger.debug("Statement %d/%d OK", i, len(statements))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Statement %d failed (continuing): %s", i, exc)

        # CIRCE SQL INSERTs results into {results_schema}.cohort — which in
        # Spark becomes a managed table under the results_schema database.
        # Try reading from that Spark table first, then fall back to PG.
        spark.sql(f"CREATE DATABASE IF NOT EXISTS {results_schema}")

        person_count = 0
        for table_ref in [
            f"{results_schema}.cohort",
            f"spark_temp.cohort_{cohort_id}",
        ]:
            try:
                count_df = spark.sql(  # type: ignore[union-attr]
                    f"SELECT COUNT(DISTINCT subject_id) AS cnt FROM {table_ref} "
                    f"WHERE cohort_definition_id = {cohort_id}"
                )
                person_count = int(count_df.collect()[0]["cnt"])
                if person_count > 0:
                    logger.info(
                        "Spark cohort count from %s: %d", table_ref, person_count
                    )
                    # Write back to PostgreSQL
                    self._write_cohort_to_pg_from(
                        spark, table_ref, results_schema, cohort_id
                    )
                    return person_count
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not read %s: %s", table_ref, exc)

        if person_count == 0:
            person_count = self._count_from_pg(results_schema, cohort_id)
        return person_count

    def _write_cohort_to_pg_from(
        self,
        spark: object,
        source_table: str,
        results_schema: str,
        cohort_id: int,
    ) -> None:
        """Write cohort results from a Spark table back to PostgreSQL via JDBC."""
        try:
            cohort_df = spark.sql(  # type: ignore[union-attr]
                f"SELECT * FROM {source_table} WHERE cohort_definition_id = {cohort_id}"
            )
            cohort_df.write.jdbc(
                url=self.pg_jdbc_url,
                table=f"{results_schema}.cohort",
                mode="append",
                properties=self._jdbc_properties(),
            )
            logger.info(
                "Wrote cohort %d from %s to %s.cohort via JDBC",
                cohort_id, source_table, results_schema,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write cohort %d to PostgreSQL: %s", cohort_id, exc)

    def _count_from_pg(self, results_schema: str, cohort_id: int) -> int:
        """Fallback: count cohort subjects directly from PostgreSQL via psycopg2.

        Args:
            results_schema: PostgreSQL schema containing the cohort table.
            cohort_id: Cohort definition ID to count.

        Returns:
            Subject count, or 0 on any failure.
        """
        try:
            import psycopg2  # type: ignore[import]

            conn = psycopg2.connect(
                host=self.pg_host,
                port=self.pg_port,
                dbname=self.pg_dbname,
                user=self.pg_user,
                password=self.pg_password,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT COUNT(DISTINCT subject_id) FROM {results_schema}.cohort"
                        f" WHERE cohort_definition_id = %s",
                        (cohort_id,),
                    )
                    row = cur.fetchone()
                    count = int(row[0]) if row else 0
            finally:
                conn.close()

            logger.info(
                "PostgreSQL fallback count for cohort %d: %d", cohort_id, count
            )
            return count

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "PostgreSQL fallback count also failed for cohort %d: %s", cohort_id, exc
            )
            return 0
