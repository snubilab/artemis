"""File-backed store for TTE studies, artifacts, and jobs."""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.api.models.tte import TTEArtifact, TTEJob, TTEStudy, utc_now_iso

_log = logging.getLogger(__name__)

try:
    from filelock import FileLock as _FileLockImpl

    class _ReusableFileLock:
        def __init__(self, path: Path):
            self._lock_path = Path(str(path) + ".lock")
            self._lock = _FileLockImpl(str(self._lock_path))

        def __enter__(self) -> Any:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            return self._lock.__enter__()

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
            return self._lock.__exit__(exc_type, exc, tb)

    def _make_file_lock(path: Path) -> Any:
        return _ReusableFileLock(path)

except ImportError:
    try:
        import fcntl

        class _ReusableFileLock:
            def __init__(self, path: Path):
                self._lock_path = Path(str(path) + ".lock")
                self._handle: Any | None = None

            def __enter__(self) -> Any:
                self._lock_path.parent.mkdir(parents=True, exist_ok=True)
                self._handle = self._lock_path.open("w", encoding="utf-8")
                fcntl.flock(self._handle, fcntl.LOCK_EX)
                return self._handle

            def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                assert self._handle is not None
                try:
                    fcntl.flock(self._handle, fcntl.LOCK_UN)
                finally:
                    self._handle.close()
                    self._handle = None
                return False

        def _make_file_lock(path: Path) -> Any:
            return _ReusableFileLock(path)

    except ImportError:
        class _NoopFileLock:
            _warned = False

            def __enter__(self) -> None:
                if not self.__class__._warned:
                    _log.warning(
                        "No file lock available (filelock/fcntl missing); proceeding without file lock"
                    )
                    self.__class__._warned = True
                return None

            def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

        def _make_file_lock(path: Path) -> Any:
            return _NoopFileLock()


def create_sample_study() -> dict[str, Any]:
    """Seed the store with a single example study."""
    return {
        "id": 1,
        "version": 1,
        "name": "SGLT2i vs DPP-4i cardiovascular outcomes (DECLARE-TIMI 58 emulation)",
        "description": (
            "DECLARE-TIMI 58 style emulation comparing dapagliflozin with DPP-4 inhibitors "
            "for cardiovascular outcomes in adults with type 2 diabetes and CV risk."
        ),
        "studyType": "comparative",
        "comparisonMode": "explicit_comparator",
        "status": "completed",
        "createdDate": "2026-03-01T09:00:00Z",
        "modifiedDate": "2026-03-01T09:20:00Z",
        "createdBy": {"name": "TROY Research Team"},
        "eligibility": {
            "targetCohortId": 1787714,
            "targetCohortName": "Type 2 Diabetes Patients with CV Risk",
            "inclusionCriteria": [
                {"id": 1, "description": "Type 2 diabetes mellitus diagnosis"},
                {"id": 2, "description": "Age 40 years or older"},
                {"id": 3, "description": "Established ASCVD or multiple CV risk factors"},
            ],
            "exclusionCriteria": [
                {"id": 1, "description": "Prior SGLT2 inhibitor exposure"},
                {"id": 2, "description": "Type 1 diabetes"},
            ],
        },
        "treatmentArms": [
            {"id": 1, "name": "Dapagliflozin", "cohortId": 143, "cohortName": "New users of dapagliflozin"},
            {"id": 2, "name": "DPP-4 inhibitors", "cohortId": 144, "cohortName": "New users of DPP-4 inhibitors"},
        ],
        "outcomes": {
            "primary": {
                "cohortId": 94,
                "cohortName": "MACE",
                "description": "Composite of cardiovascular death, MI, or ischemic stroke",
            },
            "secondary": [
                {
                    "id": 1,
                    "cohortId": 95,
                    "cohortName": "Heart failure hospitalization",
                    "description": "Hospitalization for heart failure",
                }
            ],
        },
        "timeParams": {
            "followUpDuration": 1460,
            "followUpUnit": "days",
            "washoutPeriod": 180,
            "gracePeriod": 30,
            "minDaysAtRisk": 1,
        },
        "analysisSettings": {
            "outcomeModel": "cox",
            "adjustForCovariates": True,
            "psMethod": "matching",
            "psCaliper": 0.2,
            "trimByPs": True,
            "trimFraction": 0.05,
        },
        "executions": [
            {
                "id": 1709283600000,
                "sourceKey": "SYNTHEA",
                "status": "COMPLETED",
                "startTime": "2026-03-01T09:05:00Z",
                "endTime": "2026-03-01T09:18:00Z",
            }
        ],
        "results": {
            "hazardRatio": 0.83,
            "hrLower95": 0.73,
            "hrUpper95": 0.95,
            "pValue": 0.005,
            "treatmentN": 8582,
            "comparatorN": 8578,
            "treatmentEvents": 417,
            "comparatorEvents": 496,
        },
    }


class TTEStore:
    """Simple JSON-backed persistence for TTE studies."""

    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._file_lock = _make_file_lock(self.path)

    def _initial_state(self) -> dict[str, Any]:
        return {
            "next_id": 2,
            "next_artifact_id": 1,
            "next_job_id": 1,
            "studies": [create_sample_study()],
            "artifacts": [],
            "jobs": [],
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._initial_state()
        for attempt in range(3):
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
            except json.JSONDecodeError:
                if attempt < 2:
                    _log.warning("studies.json: JSONDecodeError on read (attempt %d), retrying...", attempt + 1)
                    time.sleep(0.1)
                else:
                    _log.error("studies.json: JSONDecodeError after 3 attempts, returning initial state")
                    return self._initial_state()

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
        tmp_path.replace(self.path)

    @contextlib.contextmanager
    def _mutation_lock(self) -> Any:
        with self._lock:
            with self._file_lock:
                yield

    def _create_study_locked(
        self, payload: dict[str, Any], study_data: dict[str, Any]
    ) -> dict[str, Any]:
        study = deepcopy(study_data)
        study["id"] = payload["next_id"]
        study["version"] = int(study.get("version") or 1)
        now = utc_now_iso()
        study["createdDate"] = now
        study["modifiedDate"] = now
        payload["next_id"] += 1
        validated = TTEStudy.model_validate(study).model_dump()
        payload["studies"].append(validated)
        self._write(payload)
        return deepcopy(validated)

    def _save(self, payload: dict[str, Any]) -> None:
        with self._mutation_lock():
            self._write(payload)

    def list_studies(self) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._read()
            return deepcopy(payload["studies"])

    def get_study(self, study_id: int) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            for study in payload["studies"]:
                if int(study["id"]) == int(study_id):
                    return deepcopy(study)
        raise KeyError(f"Study {study_id} not found")

    def create_study(self, study_data: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock():
            payload = self._read()
            return self._create_study_locked(payload, study_data)

    def update_study(self, study_id: int, study_data: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock():
            payload = self._read()
            for index, current in enumerate(payload["studies"]):
                if int(current["id"]) != int(study_id):
                    continue
                incoming = deepcopy(study_data)
                if incoming.get("trialMetadata") is None and current.get("trialMetadata") is not None:
                    incoming.pop("trialMetadata", None)
                merged = {**current, **incoming}
                merged["id"] = int(study_id)
                merged["version"] = int(merged.get("version") or current.get("version") or 1)
                merged["createdDate"] = current.get("createdDate", utc_now_iso())
                merged["modifiedDate"] = utc_now_iso()
                validated = TTEStudy.model_validate(merged).model_dump()
                payload["studies"][index] = validated
                self._write(payload)
                return deepcopy(validated)
        raise KeyError(f"Study {study_id} not found")

    def delete_study(self, study_id: int) -> None:
        with self._mutation_lock():
            payload = self._read()
            before = len(payload["studies"])
            payload["studies"] = [s for s in payload["studies"] if int(s["id"]) != int(study_id)]
            if len(payload["studies"]) == before:
                raise KeyError(f"Study {study_id} not found")
            sid = int(study_id)
            payload["jobs"] = [j for j in payload.get("jobs", []) if int(j.get("studyId", 0)) != sid]
            payload["artifacts"] = [a for a in payload.get("artifacts", []) if int(a.get("studyId", 0)) != sid]
            self._write(payload)

    def clear_studies(self) -> int:
        with self._mutation_lock():
            payload = self._read()
            deleted_count = len(payload["studies"])
            payload["studies"] = []
            self._write(payload)
            return deleted_count

    def purge_all_data(self) -> dict[str, int]:
        with self._mutation_lock():
            payload = self._read()
            counts = {
                "studies": len(payload.get("studies", [])),
                "jobs": len(payload.get("jobs", [])),
                "artifacts": len(payload.get("artifacts", [])),
            }
            payload["studies"] = []
            payload["jobs"] = []
            payload["artifacts"] = []
            self._write(payload)
            return counts

    def copy_study(self, study_id: int) -> dict[str, Any]:
        with self._mutation_lock():
            payload = self._read()
            for original in payload["studies"]:
                if int(original["id"]) != int(study_id):
                    continue
                copied = deepcopy(original)
                copied["id"] = None
                copied["name"] = f'{copied["name"]} (Copy)'
                copied["status"] = "draft"
                copied["version"] = 1
                copied["executions"] = []
                copied["results"] = None
                return self._create_study_locked(payload, copied)
        raise KeyError(f"Study {study_id} not found")

    def list_artifacts(self, study_id: int) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._read()
            return [
                deepcopy(artifact)
                for artifact in payload.get("artifacts", [])
                if int(artifact["studyId"]) == int(study_id)
            ]

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            for artifact in payload.get("artifacts", []):
                if artifact["id"] == artifact_id:
                    return deepcopy(artifact)
        raise KeyError(f"Artifact {artifact_id} not found")

    def create_artifact(self, artifact_data: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock():
            payload = self._read()
            artifact = deepcopy(artifact_data)
            artifact["id"] = f'art_{payload.get("next_artifact_id", 1)}'
            payload["next_artifact_id"] = int(payload.get("next_artifact_id", 1)) + 1
            validated = TTEArtifact.model_validate(artifact).model_dump()
            payload.setdefault("artifacts", []).append(validated)
            self._write(payload)
            return deepcopy(validated)

    def update_artifact(self, artifact_id: str, artifact_data: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock():
            payload = self._read()
            for index, current in enumerate(payload.get("artifacts", [])):
                if current["id"] != artifact_id:
                    continue
                merged = {**current, **deepcopy(artifact_data)}
                merged["id"] = artifact_id
                validated = TTEArtifact.model_validate(merged).model_dump()
                payload["artifacts"][index] = validated
                self._write(payload)
                return deepcopy(validated)
        raise KeyError(f"Artifact {artifact_id} not found")

    def find_latest_generate_from_nct_artifact(
        self, *, nct_id: str, generator_version: str
    ) -> dict[str, Any] | None:
        with self._lock:
            payload = self._read()
            for artifact in reversed(payload.get("artifacts", [])):
                if artifact.get("capability") != "generate_from_nct":
                    continue
                if artifact.get("kind") != "draft_generation":
                    continue
                if artifact.get("status") != "completed":
                    continue

                meta = ((artifact.get("payload") or {}).get("meta") or {})
                if meta.get("nctId") != nct_id:
                    continue
                if meta.get("generatorVersion") != generator_version:
                    continue
                if meta.get("generationMode") != "trial_agent":
                    continue

                return deepcopy(artifact)
        return None

    def create_job(self, job_data: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock():
            payload = self._read()
            job = deepcopy(job_data)
            job["id"] = f'job_{payload.get("next_job_id", 1)}'
            payload["next_job_id"] = int(payload.get("next_job_id", 1)) + 1
            validated = TTEJob.model_validate(job).model_dump()
            payload.setdefault("jobs", []).append(validated)
            self._write(payload)
            return deepcopy(validated)

    def update_job(self, job_id: str, job_data: dict[str, Any]) -> dict[str, Any]:
        with self._mutation_lock():
            payload = self._read()
            for index, current in enumerate(payload.get("jobs", [])):
                if current["id"] != job_id:
                    continue
                merged = {**current, **deepcopy(job_data)}
                merged["id"] = job_id
                validated = TTEJob.model_validate(merged).model_dump()
                payload["jobs"][index] = validated
                self._write(payload)
                return deepcopy(validated)
        raise KeyError(f"Job {job_id} not found")

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            for job in payload.get("jobs", []):
                if job["id"] == job_id:
                    return deepcopy(job)
        raise KeyError(f"Job {job_id} not found")

    def list_jobs(
        self,
        *,
        study_id: int | None = None,
        capability: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._read()
            jobs = payload.get("jobs", [])
            filtered: list[dict[str, Any]] = []
            for job in jobs:
                if study_id is not None and int(job["studyId"]) != int(study_id):
                    continue
                if capability is not None and job.get("capability") != capability:
                    continue
                filtered.append(deepcopy(job))
            return filtered
