"""
OMOP CDM Data Connector.
Phase 5: Real data integration for ARTEMIS 3.1.
"""
from typing import Optional, List, Dict, Any
import logging
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class OMOPConnector:
    """
    Connect to OMOP CDM database and extract cohort data.
    """
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        schema: str = "synthea23m"
    ):
        """
        Initialize OMOP connector.
        
        Args:
            connection_string: PostgreSQL connection string
            schema: OMOP CDM schema name (default: synthea_cdm)
        """
        import os
        self.connection_string = connection_string or os.getenv("DATABASE_URL", "postgresql://postgres:mypass@localhost:5432/ohdsi")
        self.schema = schema
        self.vocab_schema = "omop_vocab"
        self._engine: Optional[Engine] = None
    
    @property
    def engine(self) -> Engine:
        """Lazy engine initialization."""
        if self._engine is None:
            self._engine = create_engine(self.connection_string)
        return self._engine
    
    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                return result.fetchone()[0] == 1
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def get_person_count(self) -> int:
        """Get total person count."""
        query = f"SELECT COUNT(*) FROM {self.schema}.person"
        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            return result.fetchone()[0]
    
    def extract_drug_cohort(
        self,
        drug_concept_ids: List[int],
        min_exposure_days: int = 0
    ) -> pd.DataFrame:
        """
        Extract cohort of patients exposed to specific drugs.
        
        Args:
            drug_concept_ids: List of OMOP drug concept IDs
            min_exposure_days: Minimum exposure duration
            
        Returns:
            DataFrame with person_id, cohort_start_date, cohort_end_date
        """
        concept_ids_str = ",".join(map(str, drug_concept_ids))
        
        query = f"""
        SELECT DISTINCT
            de.person_id,
            MIN(de.drug_exposure_start_date) as cohort_start_date,
            MAX(de.drug_exposure_end_date) as cohort_end_date
        FROM {self.schema}.drug_exposure de
        WHERE de.drug_concept_id IN ({concept_ids_str})
        GROUP BY de.person_id
        HAVING MAX(de.drug_exposure_end_date) - MIN(de.drug_exposure_start_date) >= {min_exposure_days}
        """
        
        with self.engine.connect() as conn:
            return pd.read_sql(query, conn)
    
    def extract_demographics(self, person_ids: List[int]) -> pd.DataFrame:
        """
        Extract demographic features for persons.
        
        Args:
            person_ids: List of person IDs
            
        Returns:
            DataFrame with person_id, age (from year_of_birth), gender
        """
        ids_str = ",".join(map(str, person_ids))
        
        query = f"""
        SELECT 
            p.person_id,
            EXTRACT(YEAR FROM CURRENT_DATE) - p.year_of_birth as age,
            CASE WHEN p.gender_concept_id = 8507 THEN 1 ELSE 0 END as gender_male,
            p.race_concept_id
        FROM {self.schema}.person p
        WHERE p.person_id IN ({ids_str})
        """
        
        with self.engine.connect() as conn:
            return pd.read_sql(query, conn)
    
    def extract_conditions(
        self, 
        person_ids: List[int],
        lookback_days: int = 365
    ) -> pd.DataFrame:
        """
        Extract condition occurrences as binary features.
        
        Returns:
            DataFrame with person_id, has_condition_{concept_id} columns
        """
        ids_str = ",".join(map(str, person_ids))
        
        query = f"""
        SELECT 
            person_id,
            condition_concept_id,
            1 as has_condition
        FROM {self.schema}.condition_occurrence
        WHERE person_id IN ({ids_str})
        GROUP BY person_id, condition_concept_id
        """
        
        with self.engine.connect() as conn:
            df = pd.read_sql(query, conn)
        
        # Pivot to wide format
        if len(df) > 0:
            pivot = df.pivot_table(
                index="person_id", 
                columns="condition_concept_id", 
                values="has_condition",
                fill_value=0
            )
            pivot.columns = [f"cond_{c}" for c in pivot.columns]
            return pivot.reset_index()
        return pd.DataFrame({"person_id": person_ids})
    
    def extract_outcome(
        self,
        person_ids: List[int],
        outcome_concept_ids: List[int],
        index_dates: Dict[int, Any],
        followup_days: int = 365
    ) -> pd.DataFrame:
        """
        Extract time-to-event outcome data.
        
        Args:
            person_ids: List of person IDs
            outcome_concept_ids: Condition concept IDs for outcome
            index_dates: Dict of person_id -> index_date
            followup_days: Maximum follow-up period
            
        Returns:
            DataFrame with person_id, time (days), event (0/1)
        """
        ids_str = ",".join(map(str, person_ids))
        concepts_str = ",".join(map(str, outcome_concept_ids))
        
        # Get first outcome occurrence after index (include descendants via concept_ancestor)
        query = f"""
        SELECT
            co.person_id,
            MIN(co.condition_start_date) as event_date
        FROM {self.schema}.condition_occurrence co
        JOIN {self.vocab_schema}.concept_ancestor ca
          ON ca.descendant_concept_id = co.condition_concept_id
        WHERE co.person_id IN ({ids_str})
          AND ca.ancestor_concept_id IN ({concepts_str})
        GROUP BY co.person_id
        """
        
        with self.engine.connect() as conn:
            events_df = pd.read_sql(query, conn)
        
        # Build outcome table
        outcomes = []
        for pid in person_ids:
            index_date = pd.to_datetime(index_dates.get(pid))
            event_row = events_df[events_df["person_id"] == pid]
            
            if len(event_row) > 0 and event_row.iloc[0]["event_date"]:
                event_date = pd.to_datetime(event_row.iloc[0]["event_date"])
                if event_date > index_date:
                    days_to_event = (event_date - index_date).days
                    if days_to_event <= followup_days:
                        outcomes.append({
                            "person_id": pid,
                            "time": days_to_event,
                            "event": 1
                        })
                        continue
            
            # Censored at followup_days
            outcomes.append({
                "person_id": pid,
                "time": followup_days,
                "event": 0
            })
        
        return pd.DataFrame(outcomes)
    
    def build_analysis_dataset(
        self,
        target_drug_ids: List[int],
        comparator_drug_ids: List[int],
        outcome_concept_ids: List[int],
        followup_days: int = 365
    ) -> pd.DataFrame:
        """
        Build a complete analysis dataset for two drug cohorts.
        
        Returns:
            DataFrame ready for Agent 5 analysis
        """
        # Extract target cohort
        target_cohort = self.extract_drug_cohort(target_drug_ids)
        comparator_cohort = self.extract_drug_cohort(comparator_drug_ids)
        
        if target_cohort.empty or comparator_cohort.empty:
            print("[OMOPConnector] Warning: One or both cohorts are empty!")
            return pd.DataFrame()
        
        target_ids = target_cohort['person_id'].tolist()
        comparator_ids = comparator_cohort['person_id'].tolist()
        
        # Extract demographics
        all_ids = list(set(target_ids + comparator_ids))
        demographics = self.extract_demographics(all_ids)
        
        # Build index dates
        index_dates = {}
        for _, row in target_cohort.iterrows():
            index_dates[row['person_id']] = row['cohort_start_date']
        for _, row in comparator_cohort.iterrows():
            index_dates[row['person_id']] = row['cohort_start_date']
        
        # Extract outcomes
        outcomes = self.extract_outcome(
            all_ids, outcome_concept_ids, index_dates, followup_days
        )
        
        # Merge
        target_df = demographics[demographics['person_id'].isin(target_ids)].copy()
        target_df['treatment'] = 1
        comp_df = demographics[demographics['person_id'].isin(comparator_ids)].copy()
        comp_df['treatment'] = 0
        
        data = pd.concat([target_df, comp_df], ignore_index=True)
        data = data.merge(outcomes, on='person_id', how='left')
        data['time'] = data['time'].fillna(followup_days)
        data['event'] = data['event'].fillna(0).astype(int)
        
        return data
    
    def diagnose_concepts(
        self,
        concept_ids: List[int],
        domains: Optional[Dict[int, str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Diagnose whether concepts have patients in the CDM (Loop 4).
        
        For each concept_id, queries the relevant domain table to count
        patients. Returns diagnostic info to guide concept expansion.
        
        Args:
            concept_ids: List of OMOP concept IDs to check
            domains: Optional dict mapping concept_id → domain name
            
        Returns:
            List of dicts with concept_id, concept_name, patient_count,
            domain, suggestion
        """
        diagnostics = []
        
        domain_table_map = {
            "Drug": ("drug_exposure", "drug_concept_id"),
            "Condition": ("condition_occurrence", "condition_concept_id"),
            "Measurement": ("measurement", "measurement_concept_id"),
            "Procedure": ("procedure_occurrence", "procedure_concept_id"),
            "Observation": ("observation", "observation_concept_id"),
        }
        
        try:
            engine = self.engine
        except Exception as e:
            logger.warning(
                "[OMOPConnector] Failed to initialize DB engine during diagnostics; "
                f"returning fallback diagnostics. error_type={type(e).__name__} error={e}"
            )
            # Return empty diagnostics if DB not available
            return [
                {
                    "concept_id": cid,
                    "concept_name": "",
                    "patient_count": -1,
                    "domain": domains.get(cid, "Unknown") if domains else "Unknown",
                    "suggestion": "CHECK_MAPPING"
                }
                for cid in concept_ids
            ]
        
        for cid in concept_ids:
            domain = (domains or {}).get(cid, "Drug")  # Default to Drug
            table, col = domain_table_map.get(domain, ("drug_exposure", "drug_concept_id"))
            
            try:
                query = text(f"""
                    SELECT 
                        COUNT(DISTINCT person_id) as patient_count
                    FROM {self.schema}.{table}
                    WHERE {col} = :concept_id
                """)
                
                with engine.connect() as conn:
                    row = conn.execute(query, {"concept_id": cid}).fetchone()
                    patient_count = row[0] if row else 0
                
                # Determine suggestion
                if patient_count == 0:
                    suggestion = "EXPAND_DESCENDANTS"
                elif patient_count < 10:
                    suggestion = "CHECK_MAPPING"
                else:
                    suggestion = "OK"
                
                # Get concept name
                try:
                    name_q = text(f"""
                        SELECT concept_name FROM {self.schema}.concept
                        WHERE concept_id = :concept_id
                    """)
                    with engine.connect() as conn:
                        name_row = conn.execute(name_q, {"concept_id": cid}).fetchone()
                        concept_name = name_row[0] if name_row else ""
                except Exception as e:
                    logger.warning(
                        "[OMOPConnector] Failed to fetch concept_name; "
                        f"using empty name. concept_id={cid} "
                        f"error_type={type(e).__name__} error={e}"
                    )
                    concept_name = ""
                
                diagnostics.append({
                    "concept_id": cid,
                    "concept_name": concept_name,
                    "patient_count": patient_count,
                    "domain": domain,
                    "suggestion": suggestion
                })
                
            except Exception as e:
                logger.warning(
                    "[OMOPConnector] Concept diagnostic query failed; "
                    f"using fallback diagnostic row. concept_id={cid} domain={domain} "
                    f"error_type={type(e).__name__} error={e}"
                )
                diagnostics.append({
                    "concept_id": cid,
                    "concept_name": "",
                    "patient_count": -1,
                    "domain": domain,
                    "suggestion": "CHECK_MAPPING"
                })
        
        return diagnostics

    # ----------------------------------------------------------
    # HDPS Covariate Extraction (Phase 2)
    # ----------------------------------------------------------

    def extract_drugs(
        self,
        person_ids: List[int],
        lookback_days: int = 365,
    ) -> pd.DataFrame:
        """
        Extract drug exposures as binary features for HDPS covariates.

        Returns:
            DataFrame with person_id + drug_{concept_id} binary columns
        """
        ids_str = ",".join(map(str, person_ids))

        query = f"""
        SELECT
            person_id,
            drug_concept_id,
            1 as has_drug
        FROM {self.schema}.drug_exposure
        WHERE person_id IN ({ids_str})
          AND drug_concept_id != 0
        GROUP BY person_id, drug_concept_id
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(query, conn)

        if len(df) > 0:
            pivot = df.pivot_table(
                index="person_id",
                columns="drug_concept_id",
                values="has_drug",
                fill_value=0,
            )
            pivot.columns = [f"drug_{c}" for c in pivot.columns]
            return pivot.reset_index()
        return pd.DataFrame({"person_id": person_ids})

    def extract_procedures(
        self,
        person_ids: List[int],
        lookback_days: int = 365,
    ) -> pd.DataFrame:
        """
        Extract procedure occurrences as binary features for HDPS covariates.

        Returns:
            DataFrame with person_id + proc_{concept_id} binary columns
        """
        ids_str = ",".join(map(str, person_ids))

        query = f"""
        SELECT
            person_id,
            procedure_concept_id,
            1 as has_procedure
        FROM {self.schema}.procedure_occurrence
        WHERE person_id IN ({ids_str})
          AND procedure_concept_id != 0
        GROUP BY person_id, procedure_concept_id
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(query, conn)

        if len(df) > 0:
            pivot = df.pivot_table(
                index="person_id",
                columns="procedure_concept_id",
                values="has_procedure",
                fill_value=0,
            )
            pivot.columns = [f"proc_{c}" for c in pivot.columns]
            return pivot.reset_index()
        return pd.DataFrame({"person_id": person_ids})

    # ----------------------------------------------------------
    # V2: Cohort-table-based analysis dataset
    # ----------------------------------------------------------

    def build_analysis_dataset_from_cohort(
        self,
        cohort_ref: "CohortTableReference",
        outcome_concept_ids: List[int],
        followup_days: int = 365,
        min_prevalence: float = 0.01,
        max_covariates: int = 10000,
        comparator_ref: "CohortTableReference" = None,
    ) -> pd.DataFrame:
        """
        Build analysis dataset from WebAPI-generated cohort table(s).

        Single-arm mode (comparator_ref=None):
            All patients get treatment=1.

        Dual-arm mode (comparator_ref provided):
            Target cohort → treatment=1, Comparator cohort → treatment=0.
            Duplicate patients (in both) are kept as target only.

        Args:
            cohort_ref: Reference to the target cohort in results table
            outcome_concept_ids: OMOP concept IDs for outcome
            followup_days: Maximum follow-up period
            min_prevalence: Drop covariates below this prevalence
            max_covariates: Maximum number of covariate columns
            comparator_ref: Optional reference to comparator cohort

        Returns:
            DataFrame ready for Agent 5 analysis
        """
        from src.pipeline.webapi_client import CohortTableReference

        results_schema = cohort_ref.results_schema

        # ---- Read target cohort ----
        cohort_query = f"""
        SELECT
            subject_id as person_id,
            cohort_definition_id,
            cohort_start_date,
            cohort_end_date
        FROM {results_schema}.cohort
        WHERE cohort_definition_id = :cohort_id
        """

        with self.engine.connect() as conn:
            target_df = pd.read_sql(
                text(cohort_query), conn,
                params={"cohort_id": cohort_ref.cohort_definition_id},
            )

        if target_df.empty:
            print("[OMOPConnector] Target cohort is empty")
            return pd.DataFrame()

        target_df["treatment"] = 1
        target_ids = set(target_df["person_id"].unique())
        print(f"[OMOPConnector] Target cohort: {len(target_ids)} patients")

        # ---- Read comparator cohort (if provided) ----
        if comparator_ref is not None:
            with self.engine.connect() as conn:
                comp_df = pd.read_sql(
                    text(cohort_query), conn,
                    params={"cohort_id": comparator_ref.cohort_definition_id},
                )

            if comp_df.empty:
                print("[OMOPConnector] Comparator cohort is empty")
                return pd.DataFrame()

            comp_df["treatment"] = 0
            comp_ids = set(comp_df["person_id"].unique())

            # Remove duplicates: patients in both cohorts stay as target
            overlap = target_ids & comp_ids
            if overlap:
                print(
                    f"[OMOPConnector] {len(overlap)} patients in both cohorts "
                    f"→ keeping as target"
                )
                comp_df = comp_df[~comp_df["person_id"].isin(overlap)]
                comp_ids -= overlap

            cohort_df = pd.concat([target_df, comp_df], ignore_index=True)
            all_person_ids = list(target_ids | comp_ids)
            print(
                f"[OMOPConnector] Comparator cohort: {len(comp_ids)} patients "
                f"(after dedup)"
            )
        else:
            cohort_df = target_df
            all_person_ids = list(target_ids)

        # ---- Extract features ----
        demographics = self.extract_demographics(all_person_ids)
        conditions = self.extract_conditions(all_person_ids)
        drugs = self.extract_drugs(all_person_ids)
        procedures = self.extract_procedures(all_person_ids)

        # Build index dates from cohort start
        index_dates = {}
        for _, row in cohort_df.iterrows():
            index_dates[row["person_id"]] = row["cohort_start_date"]

        # Extract outcomes
        outcomes = self.extract_outcome(
            all_person_ids, outcome_concept_ids, index_dates, followup_days
        )

        # ---- Merge into analysis dataset ----
        # Start with demographics, then assign treatment from cohort_df
        treatment_map = (
            cohort_df.drop_duplicates(subset=["person_id"], keep="first")
            .set_index("person_id")["treatment"]
        )
        data = demographics.copy()
        data["treatment"] = data["person_id"].map(treatment_map).fillna(0).astype(int)

        # Merge covariates
        for cov_df in [conditions, drugs, procedures]:
            if not cov_df.empty and "person_id" in cov_df.columns:
                data = data.merge(cov_df, on="person_id", how="left")

        # Merge outcomes
        data = data.merge(outcomes, on="person_id", how="left")
        data["time"] = data["time"].fillna(followup_days)
        data["event"] = data["event"].fillna(0).astype(int)

        # Fill NaN covariates with 0
        data = data.fillna(0)

        # ---- Apply prevalence filter ----
        covariate_cols = [
            c for c in data.columns
            if c.startswith(("cond_", "drug_", "proc_"))
        ]
        if covariate_cols and min_prevalence > 0:
            prevalences = data[covariate_cols].mean()
            keep_cols = prevalences[prevalences >= min_prevalence].index.tolist()
            drop_cols = [c for c in covariate_cols if c not in keep_cols]
            if drop_cols:
                data = data.drop(columns=drop_cols)
                covariate_cols = keep_cols

        # Limit max covariates (keep highest prevalence)
        if len(covariate_cols) > max_covariates:
            prevalences = data[covariate_cols].mean().sort_values(ascending=False)
            keep = prevalences.head(max_covariates).index.tolist()
            drop = [c for c in covariate_cols if c not in keep]
            data = data.drop(columns=drop)

        # Resolve raw covariate column names to human-readable concept names.
        data = self._rename_covariates_to_concept_names(data)

        n_covariates = len([
            c for c in data.columns
            if c not in ("person_id", "treatment", "time", "event", "age", "gender_male", "race_concept_id")
            and c.startswith(("Cond:", "Drug:", "Proc:", "cond_", "drug_", "proc_"))
        ])
        n_target = int((data["treatment"] == 1).sum())
        n_comp = int((data["treatment"] == 0).sum())
        print(
            f"[OMOPConnector] Analysis dataset: {len(data)} patients "
            f"(target={n_target}, comparator={n_comp}), "
            f"{n_covariates} HDPS covariates"
        )

        return data

    def extract_outcome_from_cohort(
        self,
        person_ids: List[int],
        outcome_ref: "CohortTableReference",
        index_dates: Dict[int, Any],
        followup_days: int = 365,
    ) -> pd.DataFrame:
        """
        Extract time-to-event outcomes from a generated outcome cohort table.

        Args:
            person_ids: List of person IDs
            outcome_ref: Outcome cohort reference stored in results schema
            index_dates: Dict of person_id -> index_date
            followup_days: Maximum follow-up period

        Returns:
            DataFrame with person_id, time (days), event (0/1)
        """
        if not person_ids:
            return pd.DataFrame(columns=["person_id", "time", "event"])

        indexed_rows: list[str] = []
        query_params: Dict[str, Any] = {
            "cohort_id": outcome_ref.cohort_definition_id,
            "followup_days": int(followup_days),
        }
        for index, pid in enumerate(person_ids):
            index_date = pd.to_datetime(index_dates.get(pid))
            if pd.isna(index_date):
                continue
            pid_key = f"pid_{index}"
            index_key = f"index_date_{index}"
            indexed_rows.append(f"(:{pid_key}, :{index_key})")
            query_params[pid_key] = int(pid)
            query_params[index_key] = index_date.date()

        events_df = pd.DataFrame(columns=["person_id", "event_date"])
        if indexed_rows:
            diagnostic_query = text(
                f"""
                SELECT COUNT(*) AS outcome_row_count
                FROM {outcome_ref.results_schema}.cohort
                WHERE cohort_definition_id = :cohort_id
                """
            )
            diagnostic_sql = (
                f"SELECT COUNT(*) FROM {outcome_ref.results_schema}.cohort "
                f"WHERE cohort_definition_id = {outcome_ref.cohort_definition_id};"
            )
            query = f"""
            WITH indexed_person(person_id, index_date) AS (
                VALUES {", ".join(indexed_rows)}
            )
            SELECT
                idx.person_id,
                MIN(cohort_row.cohort_start_date) AS event_date
            FROM indexed_person idx
            JOIN {outcome_ref.results_schema}.cohort cohort_row
              ON cohort_row.subject_id = idx.person_id
            WHERE cohort_row.cohort_definition_id = :cohort_id
              AND cohort_row.cohort_start_date > idx.index_date
              AND cohort_row.cohort_start_date <= (
                  idx.index_date + (CAST(:followup_days AS INTEGER) * INTERVAL '1 day')
              )
            GROUP BY idx.person_id
            """

            with self.engine.connect() as conn:
                outcome_row_count = conn.execute(
                    diagnostic_query,
                    {"cohort_id": outcome_ref.cohort_definition_id},
                ).scalar()
                if int(outcome_row_count or 0) == 0:
                    logger.warning(
                        "[OMOPConnector] Outcome cohort %s has 0 rows in %s.cohort; "
                        "events will all censor. Diagnostic SQL: %s",
                        outcome_ref.cohort_definition_id,
                        outcome_ref.results_schema,
                        diagnostic_sql,
                    )

                # Diagnostic query for suspected empty outcome cohorts such as
                # 841, 943, or 1128 in the results schema cohort table:
                # SELECT COUNT(*) FROM <results_schema>.cohort WHERE cohort_definition_id = <outcome_id>;
                events_df = pd.read_sql(
                    text(query),
                    conn,
                    params=query_params,
                )

        outcomes = []
        event_dates = (
            events_df.set_index("person_id")["event_date"].to_dict()
            if not events_df.empty
            else {}
        )
        for pid in person_ids:
            index_date = pd.to_datetime(index_dates.get(pid))
            event_date = pd.to_datetime(event_dates.get(pid))

            if pd.notna(index_date) and pd.notna(event_date):
                days_to_event = (event_date - index_date).days
                if event_date > index_date and days_to_event <= followup_days:
                    outcomes.append({"person_id": pid, "time": days_to_event, "event": 1})
                    continue

            outcomes.append({"person_id": pid, "time": followup_days, "event": 0})

        return pd.DataFrame(outcomes)

    def build_analysis_dataset_from_generated_cohorts(
        self,
        target_ref: "CohortTableReference",
        outcome_ref: "CohortTableReference",
        followup_days: int = 365,
        min_prevalence: float = 0.01,
        max_covariates: int = 10000,
        comparator_ref: "CohortTableReference" = None,
        comparator_person_ids: Optional[List[int]] = None,
        comparator_index_date_override: Optional[Any] = None,
        comparator_sample_seed: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Build analysis dataset from generated treatment/comparator/outcome cohort tables.

        This is similar to build_analysis_dataset_from_cohort(...), but it derives
        event times from an already generated outcome cohort reference rather than
        OMOP outcome concept IDs.
        """
        results_schema = target_ref.results_schema

        cohort_query = f"""
        SELECT
            subject_id as person_id,
            cohort_definition_id,
            cohort_start_date,
            cohort_end_date
        FROM {results_schema}.cohort
        WHERE cohort_definition_id = :cohort_id
        """

        with self.engine.connect() as conn:
            target_df = pd.read_sql(
                text(cohort_query),
                conn,
                params={"cohort_id": target_ref.cohort_definition_id},
            )

        if target_df.empty:
            print("[OMOPConnector] Target cohort is empty")
            return pd.DataFrame()

        target_df["treatment"] = 1
        target_ids = set(target_df["person_id"].unique())

        if comparator_ref is not None:
            with self.engine.connect() as conn:
                comp_df = pd.read_sql(
                    text(cohort_query),
                    conn,
                    params={"cohort_id": comparator_ref.cohort_definition_id},
                )

            if comp_df.empty:
                print("[OMOPConnector] Comparator cohort is empty")
                return pd.DataFrame()

            comp_df["treatment"] = 0
            comp_ids = set(comp_df["person_id"].unique())
            overlap = target_ids & comp_ids
            if overlap:
                comp_df = comp_df[~comp_df["person_id"].isin(overlap)]
                comp_ids -= overlap

            cohort_df = pd.concat([target_df, comp_df], ignore_index=True)
            all_person_ids = list(target_ids | comp_ids)
        else:
            # treatment_vs_rest: comparator = all CDM persons minus treatment
            if comparator_person_ids is not None:
                comp_ids = set(comparator_person_ids) - target_ids
                all_cdm_count = len(comp_ids) + len(target_ids)
            else:
                all_cdm_query = f"SELECT DISTINCT person_id FROM {self.schema}.person"
                with self.engine.connect() as conn:
                    all_cdm_df = pd.read_sql(text(all_cdm_query), conn)
                comp_ids = set(all_cdm_df["person_id"].tolist()) - target_ids
                all_cdm_count = len(all_cdm_df)
            if not comp_ids:
                logger.warning("[OMOPConnector] No REST comparator persons found in CDM")
                return pd.DataFrame()
            # Cap comparator pool at 10× treatment size for PSM viability
            max_comparator = len(target_ids) * 10
            if len(comp_ids) > max_comparator:
                import random as _random
                if comparator_sample_seed is None:
                    comp_ids = set(_random.sample(sorted(comp_ids), max_comparator))
                else:
                    rng = _random.Random(comparator_sample_seed)
                    comp_ids = set(rng.sample(sorted(comp_ids), max_comparator))
                logger.info(
                    "[OMOPConnector] Capped REST comparator pool: %d → %d (10× treatment)",
                    all_cdm_count - len(target_ids),
                    max_comparator,
                )
            comp_index_date = comparator_index_date_override or target_df["cohort_start_date"].min()
            comp_df = pd.DataFrame({
                "person_id": list(comp_ids),
                "cohort_start_date": comp_index_date,
                "treatment": 0,
            })
            cohort_df = pd.concat([target_df, comp_df], ignore_index=True)
            all_person_ids = list(target_ids | comp_ids)

        demographics = self.extract_demographics(all_person_ids)
        conditions = self.extract_conditions(all_person_ids)
        drugs = self.extract_drugs(all_person_ids)
        procedures = self.extract_procedures(all_person_ids)

        index_dates = {}
        for _, row in cohort_df.iterrows():
            index_dates[row["person_id"]] = row["cohort_start_date"]

        outcomes = self.extract_outcome_from_cohort(
            all_person_ids,
            outcome_ref,
            index_dates,
            followup_days,
        )

        treatment_map = (
            cohort_df.drop_duplicates(subset=["person_id"], keep="first")
            .set_index("person_id")["treatment"]
        )
        data = demographics.copy()
        data["treatment"] = data["person_id"].map(treatment_map).fillna(0).astype(int)

        for cov_df in [conditions, drugs, procedures]:
            if not cov_df.empty and "person_id" in cov_df.columns:
                data = data.merge(cov_df, on="person_id", how="left")

        data = data.merge(outcomes, on="person_id", how="left")
        data["time"] = data["time"].fillna(followup_days)
        data["event"] = data["event"].fillna(0).astype(int)
        data = data.fillna(0)

        covariate_cols = [
            c for c in data.columns
            if c.startswith(("cond_", "drug_", "proc_"))
        ]
        if covariate_cols and min_prevalence > 0:
            prevalences = data[covariate_cols].mean()
            keep_cols = prevalences[prevalences >= min_prevalence].index.tolist()
            drop_cols = [c for c in covariate_cols if c not in keep_cols]
            if drop_cols:
                data = data.drop(columns=drop_cols)
                covariate_cols = keep_cols

        if len(covariate_cols) > max_covariates:
            prevalences = data[covariate_cols].mean().sort_values(ascending=False)
            keep = prevalences.head(max_covariates).index.tolist()
            drop = [c for c in covariate_cols if c not in keep]
            data = data.drop(columns=drop)

        # Resolve raw covariate column names (cond_312327, drug_40170911, etc.)
        # to human-readable OMOP concept names.
        data = self._rename_covariates_to_concept_names(data)

        return data

    def _rename_covariates_to_concept_names(self, data: pd.DataFrame) -> pd.DataFrame:
        """Rename covariate columns from cond_/drug_/proc_ IDs to concept names."""
        covariate_cols = [
            c for c in data.columns
            if c.startswith(("cond_", "drug_", "proc_"))
        ]
        if not covariate_cols:
            return data

        concept_ids: list[int] = []
        for col in covariate_cols:
            parts = col.split("_", 1)
            if len(parts) == 2:
                try:
                    concept_ids.append(int(parts[1]))
                except ValueError:
                    pass

        if not concept_ids:
            return data

        name_map = self._resolve_concept_names(concept_ids)
        rename_map: dict[str, str] = {}
        for col in covariate_cols:
            parts = col.split("_", 1)
            if len(parts) == 2:
                try:
                    cid = int(parts[1])
                except ValueError:
                    continue
                concept_name = name_map.get(cid)
                if concept_name:
                    prefix = parts[0]
                    domain_label = {"cond": "Cond", "drug": "Drug", "proc": "Proc"}.get(prefix, prefix)
                    rename_map[col] = f"{domain_label}: {concept_name}"

        if rename_map:
            data = data.rename(columns=rename_map)

        return data

    def _resolve_concept_names(self, concept_ids: List[int]) -> Dict[int, str]:
        """Query the OMOP vocabulary for concept names by ID."""
        if not concept_ids:
            return {}
        ids_str = ",".join(map(str, concept_ids))
        query = f"""
        SELECT concept_id, concept_name
        FROM {self.vocab_schema}.concept
        WHERE concept_id IN ({ids_str})
        """
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(text(query)).fetchall()
            return {int(row[0]): str(row[1]) for row in rows if row[1]}
        except Exception as exc:
            logger.warning(
                "[OMOPConnector] Failed to resolve concept names: %s", exc
            )
            return {}

    # ----------------------------------------------------------
    # V3: Cohort-level Overlap Evaluation (Agent 3 P0)
    # ----------------------------------------------------------

    def get_cohort_overlap_metrics(
        self,
        gold_cohort_id: int,
        agent_cohort_id: int,
        results_schema: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate overlap metrics (True Positives, Jaccard Similarity, etc.)
        between two cohorts directly in the database.
        
        Args:
            gold_cohort_id: WebAPI cohort definition ID for the gold standard
            agent_cohort_id: WebAPI cohort definition ID for the agent generated json
            results_schema: Override results schema if needed
        
        Returns:
            Dict containing counts and metrics:
            - gold_total, agent_total
            - intersection_count, gold_only_count, agent_only_count
            - precision, recall, f1_score, jaccard_similarity
        """
        schema = results_schema or f"{self.schema}_results"
        
        query = text(f"""
        WITH gold AS (
            SELECT DISTINCT subject_id AS person_id
            FROM {schema}.cohort
            WHERE cohort_definition_id = :gold_id
        ),
        agent AS (
            SELECT DISTINCT subject_id AS person_id
            FROM {schema}.cohort
            WHERE cohort_definition_id = :agent_id
        )
        SELECT
            (SELECT COUNT(*) FROM gold) AS gold_total,
            (SELECT COUNT(*) FROM agent) AS agent_total,
            (SELECT COUNT(*) FROM gold INNER JOIN agent USING (person_id)) AS intersection_count,
            (SELECT COUNT(*) FROM gold LEFT JOIN agent USING (person_id) WHERE agent.person_id IS NULL) AS gold_only_count,
            (SELECT COUNT(*) FROM agent LEFT JOIN gold USING (person_id) WHERE gold.person_id IS NULL) AS agent_only_count
        """)
        
        with self.engine.connect() as conn:
            row = conn.execute(query, {"gold_id": gold_cohort_id, "agent_id": agent_cohort_id}).fetchone()
        
        if not row:
            return {}
            
        gold_total = row[0]
        agent_total = row[1]
        intersection = row[2]
        gold_only = row[3]
        agent_only = row[4]
        
        precision = intersection / agent_total if agent_total > 0 else 0.0
        recall = intersection / gold_total if gold_total > 0 else 0.0
        
        union_count = gold_total + agent_total - intersection
        jaccard = intersection / union_count if union_count > 0 else 0.0
        
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return {
            "gold_total": gold_total,
            "agent_total": agent_total,
            "intersection_count": intersection,
            "gold_only_count": gold_only,
            "agent_only_count": agent_only,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "jaccard_similarity": round(jaccard, 4),
            "f1_score": round(f1, 4)
        }
