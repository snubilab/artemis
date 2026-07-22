"""
WebAPI Client for ARTEMIS Pipeline.

Provides WebAPI-based cohort generation using Circe-be engine.
Refactored from scripts/cohort_via_webapi.py for pipeline integration.
"""
import copy
import os
import time
import json
import logging
from typing import Optional, Dict, Any, Set, List
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

# ============================================================
# Configuration (from env or defaults matching Broadsea)
# ============================================================
WEBAPI_URL = os.environ.get("WEBAPI_URL", "http://127.0.0.1/WebAPI")

def _default_source_key() -> str:
    """Derive source key from CDM_SCHEMA env var."""
    schema = os.environ.get("CDM_SCHEMA", "synthea23m")
    return os.environ.get("WEBAPI_SOURCE_KEY", schema.upper())

def _default_results_schema() -> str:
    """Derive results schema from CDM_SCHEMA env var."""
    schema = os.environ.get("CDM_SCHEMA", "synthea23m")
    return os.environ.get("WEBAPI_RESULTS_SCHEMA", f"{schema}_results")

POLL_INTERVAL = int(os.environ.get("WEBAPI_POLL_INTERVAL", "5"))
MAX_POLL_TIME = int(os.environ.get("WEBAPI_MAX_POLL_TIME", "600"))


class WebAPIError(Exception):
    """Raised when WebAPI communication fails."""
    pass


@dataclass
class CohortTableReference:
    """
    Reference to a cohort stored in the results DB table.

    After WebAPI generates a cohort, patients are stored in
    {results_schema}.cohort with this cohort_definition_id.
    Downstream components (OMOPConnector, FeatureExtractor) use
    this reference to join against the cohort table.
    """
    cohort_definition_id: int
    results_schema: str
    person_count: int
    source_key: str
    name: str = ""

    @property
    def table_fqn(self) -> str:
        """Fully qualified table: e.g. synthea23m_results.cohort"""
        return f"{self.results_schema}.cohort"

    @property
    def is_empty(self) -> bool:
        return not self.person_count


def _collect_codeset_ids(node: Any) -> Set[int]:
    """Recursively collect every referenced CodesetId in a Circe expression."""
    codeset_ids: Set[int] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("CodesetId") and isinstance(value, int):
                codeset_ids.add(value)
            codeset_ids.update(_collect_codeset_ids(value))
    elif isinstance(node, list):
        for item in node:
            codeset_ids.update(_collect_codeset_ids(item))
    return codeset_ids


def prune_unused_concept_sets(expression: Dict[str, Any]) -> Dict[str, Any]:
    """
    Drop ConceptSets that are never referenced by CodesetId.

    PLATO entry-only cohorts reproduced a WebAPI bug where sending all Gold
    ConceptSets returned 0 patients, but pruning the unused sets restored the
    expected 140 patients. The execution semantics only depend on referenced
    CodesetIds, so pruning unused sets is safe and keeps SQL generation smaller.
    """
    prepared = copy.deepcopy(expression)
    concept_sets = prepared.get("ConceptSets")
    if not isinstance(concept_sets, list) or not concept_sets:
        return prepared

    expression_without_concept_sets = {
        key: value for key, value in prepared.items() if key != "ConceptSets"
    }
    referenced_ids = _collect_codeset_ids(expression_without_concept_sets)
    if not referenced_ids:
        return prepared

    original_count = len(concept_sets)
    prepared["ConceptSets"] = [
        concept_set
        for concept_set in concept_sets
        if concept_set.get("id") in referenced_ids
    ]
    pruned_count = len(prepared["ConceptSets"])
    if pruned_count != original_count:
        logger.info(
            "[WebAPI] Pruned unused ConceptSets: %s -> %s",
            original_count,
            pruned_count,
        )
    return prepared


class WebAPIClient:
    """
    ATLAS WebAPI client for cohort generation.

    Workflow:
        1. Register Circe JSON as cohort definition
        2. Generate SQL via POST /cohortdefinition/sql
        3. Trigger cohort generation on source
        4. Poll until COMPLETE
        5. Return CohortTableReference for downstream use
    """

    def __init__(
        self,
        base_url: str = WEBAPI_URL,
        source_key: Optional[str] = None,
        results_schema: Optional[str] = None,
        poll_interval: int = POLL_INTERVAL,
        max_poll_time: int = MAX_POLL_TIME,
    ):
        self.base_url = base_url.rstrip("/")
        self.source_key = source_key or _default_source_key()
        self.results_schema = results_schema or _default_results_schema()
        self.poll_interval = poll_interval
        self.max_poll_time = max_poll_time
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._source_cache: dict[str, Dict[str, Any]] = {}

    # ----------------------------------------------------------
    # Health
    # ----------------------------------------------------------
    def check_health(self) -> Dict[str, Any]:
        """Check WebAPI availability. Raises WebAPIError on failure."""
        try:
            resp = self.session.get(f"{self.base_url}/info", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise WebAPIError(f"WebAPI not reachable at {self.base_url}: {e}") from e

    # ----------------------------------------------------------
    # Cohort Definition CRUD
    # ----------------------------------------------------------
    def list_cohort_definitions(self) -> list:
        """List all existing cohort definitions."""
        resp = self.session.get(
            f"{self.base_url}/cohortdefinition", timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def list_sources(self) -> List[Dict[str, Any]]:
        """List available WebAPI sources."""
        resp = self.session.get(f"{self.base_url}/source/sources", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_source(self, source_key: Optional[str] = None) -> Dict[str, Any]:
        """Resolve a WebAPI source object by source key."""
        key = source_key or self.source_key
        if key in self._source_cache:
            return self._source_cache[key]

        for source in self.list_sources():
            if source.get("sourceKey") == key:
                self._source_cache[key] = source
                return source

        raise WebAPIError(f"Source not found in WebAPI: {key}")

    def get_results_schema(self, source_key: Optional[str] = None) -> str:
        """Resolve the Results schema qualifier for a source."""
        source = self.get_source(source_key)
        for daimon in source.get("daimons", []):
            if daimon.get("daimonType") == "Results":
                table_qualifier = daimon.get("tableQualifier")
                if table_qualifier:
                    return table_qualifier
        raise WebAPIError(f"Results daimon not found for source: {source.get('sourceKey')}")

    def create_cohort_definition(self, name: str, expression: Dict[str, Any], description: str = "Auto-generated by ARTEMIS pipeline") -> Dict[str, Any]:
        """
        Register a cohort definition. Reuses existing if name matches.

        Returns:
            WebAPI cohort definition response with 'id' field.
        """
        import uuid

        prepared_expression = prune_unused_concept_sets(expression)
        # Add a UUID to completely bypass the OHDSI WebAPI designHash caching mechanism.
        # This ensures that even if the expression content is identical, WebAPI will
        # treat it as a new definition or update, preventing stale results.
        prepared_expression["_cacheBust"] = str(uuid.uuid4())

        # Check for existing with same name — update expression if found
        existing = self.list_cohort_definitions()
        for d in existing:
            if d["name"] == name:
                cohort_id = d["id"]
                logger.info(f"Reusing existing cohort definition [{cohort_id}] '{name}'")
                # Update expression to ensure latest Circe JSON is used
                current = self._get_cohort_definition(cohort_id)
                current["expression"] = prepared_expression
                resp = self.session.put(
                    f"{self.base_url}/cohortdefinition/{cohort_id}",
                    json=current,
                    timeout=30,
                )
                try:
                    resp.raise_for_status()
                except requests.exceptions.HTTPError as e:
                    logger.error(f"WebAPI Error: {resp.text}")
                    raise e
                logger.info(f"Updated expression for cohort definition [{cohort_id}]")
                self._expression_updated = True
                return resp.json()

        payload = {
            "name": name,
            "description": description,
            "expressionType": "SIMPLE_EXPRESSION",
            "expression": prepared_expression,
        }
        resp = self.session.post(
            f"{self.base_url}/cohortdefinition", json=payload, timeout=30
        )
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error(f"WebAPI Error: {resp.text}")
            raise e
        result = resp.json()
        logger.info(f"Created cohort definition [{result['id']}] '{name}'")
        return result

    def _get_cohort_definition(self, cohort_id: int) -> Dict[str, Any]:
        """Get full cohort definition details."""
        resp = self.session.get(
            f"{self.base_url}/cohortdefinition/{cohort_id}", timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def delete_cohort_definition(self, cohort_id: int) -> None:
        """Delete a cohort definition."""
        resp = self.session.delete(
            f"{self.base_url}/cohortdefinition/{cohort_id}", timeout=30
        )
        resp.raise_for_status()

    # ----------------------------------------------------------
    # SQL Generation (for inspection / debugging)
    # ----------------------------------------------------------
    def generate_sql(self, circe_json: Dict[str, Any]) -> str:
        """
        Generate SQL from Circe JSON without executing.

        Returns:
            Template SQL string with @placeholders.
        """
        payload = {
            "expression": prune_unused_concept_sets(circe_json),
            "options": {"generateStats": True},
            "targetDialect": "postgresql",
        }
        resp = self.session.post(
            f"{self.base_url}/cohortdefinition/sql",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("templateSql", "")

    # ----------------------------------------------------------
    # SqlRender Translation
    # ----------------------------------------------------------
    def translate_sql(self, template_sql: str, target_dialect: str = "postgresql") -> str:
        """
        Translate OHDSI SQL to a target dialect via WebAPI SqlRender.

        Args:
            template_sql: OHDSI SQL string from ``/cohortdefinition/sql``.
            target_dialect: Target dialect (e.g. ``"postgresql"``, ``"spark"``).

        Returns:
            Translated SQL string.
        """
        payload = {"SQL": template_sql, "targetdialect": target_dialect}
        resp = self.session.post(
            f"{self.base_url}/sqlrender/translate", json=payload, timeout=60,
        )
        try:
            resp.raise_for_status()
        except Exception as e:
            raise WebAPIError(f"SqlRender translation failed: {e}") from e
        result = resp.json()
        if isinstance(result, str):
            return result
        target_sql = result.get("targetSQL", "")
        if not target_sql:
            raise WebAPIError("SqlRender returned empty targetSQL")
        return target_sql

    # ----------------------------------------------------------
    # Cohort Generation
    # ----------------------------------------------------------
    def start_generation(self, cohort_id: int) -> Dict[str, Any]:
        """Trigger cohort generation on the configured source."""
        resp = self.session.get(
            f"{self.base_url}/cohortdefinition/{cohort_id}/generate/{self.source_key}",
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_generation_info(self, cohort_id: int) -> list:
        """Get generation status for a cohort definition."""
        resp = self.session.get(
            f"{self.base_url}/cohortdefinition/{cohort_id}/info",
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _matches_source(self, info: Dict[str, Any]) -> bool:
        """Check whether a generation info record belongs to the active source."""
        src = info.get("sourceKey")
        if src:
            return src == self.source_key

        info_id = info.get("id")
        if isinstance(info_id, dict):
            source_id = self.get_source().get("sourceId")
            return info_id.get("sourceId") == source_id

        return True

    def _wait_for_generation(self, cohort_id: int) -> Dict[str, Any]:
        """
        Poll generation status until COMPLETE, FAILED, or timeout.
        Filters by source_key to avoid returning stale results from other sources.
        Detects isValid=false as a failure even when status=COMPLETE.

        Returns:
            Generation info dict with 'status', 'personCount', etc.

        Raises:
            WebAPIError on FAILED or timeout.
        """
        start = time.time()
        while time.time() - start < self.max_poll_time:
            info_list = self.get_generation_info(cohort_id)
            for info in info_list:
                # Filter by our source key to avoid stale results
                if not self._matches_source(info):
                    continue

                status = info.get("status", "")
                if status == "COMPLETE":
                    # Check isValid — WebAPI may report COMPLETE but with failed SQL
                    if info.get("isValid") is False and info.get("failMessage"):
                        msg = info.get("failMessage", "unknown error")
                        raise WebAPIError(
                            f"Cohort generation SQL FAILED for ID={cohort_id}: "
                            f"{msg}"
                        )
                    # Normalize null personCount to 0
                    if info.get("personCount") is None:
                        info["personCount"] = 0
                    return info
                elif status == "FAILED":
                    msg = info.get("failMessage", "unknown error")
                    raise WebAPIError(
                        f"Cohort generation FAILED for ID={cohort_id}: {msg}"
                    )

            elapsed = int(time.time() - start)
            logger.debug(f"Polling cohort {cohort_id}: {elapsed}s elapsed")
            time.sleep(self.poll_interval)

        raise WebAPIError(
            f"Cohort generation timed out after {self.max_poll_time}s for ID={cohort_id}"
        )

    # ----------------------------------------------------------
    # High-level: Generate Cohort (single entry point)
    # ----------------------------------------------------------
    def generate_cohort(
        self,
        circe_json: Dict[str, Any],
        name: str = "ARTEMIS Auto-generated",
        force_regenerate: bool = False,
    ) -> CohortTableReference:
        """
        End-to-end cohort generation: register → generate → poll → return ref.

        This is the primary entry point for the pipeline.

        Args:
            circe_json: Validated Circe-be JSON
            name: Human-readable cohort name
            force_regenerate: If True, regenerate even if already COMPLETE

        Returns:
            CohortTableReference pointing to the results table

        Raises:
            WebAPIError: If any step fails
        """
        # 1. Health check
        self.check_health()
        logger.info("[WebAPI] Health OK")

        # 2. Register cohort definition (may update expression)
        self._expression_updated = False
        definition = self.create_cohort_definition(name, circe_json)
        cohort_id = definition["id"]
        logger.info(f"[WebAPI] Cohort definition ID={cohort_id}")

        # 2.5. Engine selection: spark > webapi (default)
        engine_choice = os.environ.get("COHORT_ENGINE", "webapi")
        if engine_choice == "spark":
            logger.info("[WebAPI] Spark engine selected for cohort_id=%d", cohort_id)
            try:
                return self.generate_cohort_spark(circe_json, cohort_id, name)
            except Exception as exc:
                logger.warning(
                    "[WebAPI] Spark execution failed (%s); falling back to WebAPI", exc,
                )

        # 3. Check if already generated (skip if expression was just updated)
        if not force_regenerate and not self._expression_updated:
            existing_info = self.get_generation_info(cohort_id)
            for info in existing_info:
                src = info.get("sourceKey", "")
                if info.get("status") == "COMPLETE" and self._matches_source(info):
                    person_count = info.get("personCount", 0) or 0
                    logger.info(
                        f"[WebAPI] Already generated on {src or self.source_key}: {person_count} patients"
                    )
                    return CohortTableReference(
                        cohort_definition_id=cohort_id,
                        results_schema=self.results_schema or self.get_results_schema(),
                        person_count=person_count,
                        source_key=self.source_key,
                        name=name,
                    )
                elif info.get("status") == "COMPLETE" and not self._matches_source(info):
                    logger.info(
                        f"[WebAPI] Cached result is for {src}, "
                        f"but we need {self.source_key} → regenerating"
                    )

        # 4. Start generation
        logger.info(f"[WebAPI] Starting cohort generation on {self.source_key}...")
        self.start_generation(cohort_id)

        # 5. Wait for completion
        gen_info = self._wait_for_generation(cohort_id)
        person_count = gen_info.get("personCount", 0)
        duration_ms = gen_info.get("executionDuration", 0)
        logger.info(
            f"[WebAPI] Generation COMPLETE: {person_count} patients "
            f"({duration_ms}ms)"
        )

        return CohortTableReference(
            cohort_definition_id=cohort_id,
            results_schema=self.results_schema or self.get_results_schema(),
            person_count=person_count,
            source_key=self.source_key,
            name=name,
        )

    # ----------------------------------------------------------
    # Spark-based Cohort Generation
    # ----------------------------------------------------------
    def generate_cohort_spark(
        self,
        circe_json: Dict[str, Any],
        cohort_id: int,
        name: str = "ARTEMIS Auto-generated",
    ) -> CohortTableReference:
        """
        Generate a cohort using PySpark's columnar engine.

        Uses OHDSI SqlRender's official Spark dialect. Reads CDM tables
        from PostgreSQL via JDBC, executes CIRCE SQL in Spark, writes
        cohort results back to PostgreSQL.
        """
        from src.pipeline.spark_executor import SparkCohortExecutor, render_spark_sql

        cdm_schema = os.environ.get("CDM_SCHEMA", "synthea23m")
        results_schema = self.results_schema or _default_results_schema()

        # Get OHDSI SQL → translate to Spark dialect
        template_sql = self.generate_sql(circe_json)
        spark_sql = self.translate_sql(template_sql, target_dialect="spark")

        # Render Spark placeholders
        rendered = render_spark_sql(
            spark_sql, cdm_schema, results_schema, cohort_id
        )

        # Execute via PySpark
        start = time.time()
        executor = SparkCohortExecutor()
        person_count = executor.execute_cohort_sql(
            rendered, cdm_schema, results_schema, cohort_id
        )
        exec_seconds = time.time() - start

        logger.info(
            "[WebAPI] Spark COMPLETE: %d patients for cohort_id=%d (%.1fs)",
            person_count, cohort_id, exec_seconds,
        )
        return CohortTableReference(
            cohort_definition_id=cohort_id,
            results_schema=results_schema,
            person_count=person_count,
            source_key=self.source_key,
            name=name,
        )

    def generate_existing_cohort(
        self,
        cohort_id: int,
        name: str = "",
        force_regenerate: bool = False,
    ) -> CohortTableReference:
        """
        Generate an already-registered cohort definition on the configured source.

        Useful when the caller has an existing cohort_definition_id and only needs
        WebAPI generation/polling, not cohort definition registration.
        """
        self.check_health()
        results_schema = self.results_schema or self.get_results_schema()

        try:
            if not force_regenerate:
                existing_info = self.get_generation_info(cohort_id)
                for info in existing_info:
                    if (info.get("status") == "COMPLETE"
                            and self._matches_source(info)
                            and info.get("isValid") is not False):
                        person_count = info.get("personCount", 0) or 0
                        return CohortTableReference(
                            cohort_definition_id=cohort_id,
                            results_schema=results_schema,
                            person_count=person_count,
                            source_key=self.source_key,
                            name=name,
                        )

            self.start_generation(cohort_id)
            gen_info = self._wait_for_generation(cohort_id)
            person_count = gen_info.get("personCount", 0) or 0
            return CohortTableReference(
                cohort_definition_id=cohort_id,
                results_schema=results_schema,
                person_count=person_count,
                source_key=self.source_key,
                name=name,
            )
        except requests.exceptions.HTTPError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise WebAPIError(
                f"WebAPI cohort generation request failed for cohort_definition_id={cohort_id}: {detail}"
            ) from exc
