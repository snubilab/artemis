"""Pipeline package with lazy exports.

This keeps ``src.pipeline.webapi_client`` lightweight while preserving the
historical ``from src.pipeline import ...`` API used elsewhere in the codebase.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CohortPipeline",
    "PipelineResult",
    "pipeline",
    "CohortExecutor",
    "ArtemisPipeline",
    "ArtemisResult",
    "run_artemis",
]


def __getattr__(name: str):
    if name in {"CohortPipeline", "PipelineResult", "pipeline"}:
        module = import_module("src.pipeline.cohort_pipeline")
        return getattr(module, name)
    if name == "CohortExecutor":
        module = import_module("src.pipeline.cohort_executor")
        return getattr(module, name)
    if name in {"ArtemisPipeline", "ArtemisResult", "run_artemis"}:
        module = import_module("src.pipeline.orchestrator")
        return getattr(module, name)
    raise AttributeError(name)
