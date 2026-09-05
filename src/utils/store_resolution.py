"""Resolve the TTE store path an export/verify script will read.

Motivation: on 2026-08-31, three scratch export scripts read
``os.environ.get("TTE_STORE_PATH", <intended-default>)``. The artemis-api
container sets ``TTE_STORE_PATH`` to its own default studies store, so the
environment variable silently won over the script's intended path and twelve
per-arm CIRCE cohort files were exported from a stale store instead of the
corrected one. Nothing warned, and the delivery ledger recorded the wrong
store.

``resolve_store_path`` closes that hole: an explicit ``--store`` path is
mandatory, and any ambient ``TTE_STORE_PATH`` that disagrees with it aborts
the run instead of silently overriding it. There is deliberately no override
flag — the fix is to unset the environment variable or point it at the same
file.
"""

from __future__ import annotations

import os
from pathlib import Path


class StoreMismatchError(RuntimeError):
    """Raised when TTE_STORE_PATH disagrees with an explicit store path."""

    def __init__(self, explicit: Path, env_value: str) -> None:
        explicit_resolved = Path(explicit).resolve()
        env_resolved = Path(env_value).resolve()
        self.explicit = explicit_resolved
        self.env_value = env_value
        self.env_resolved = env_resolved
        message = (
            "TTE_STORE_PATH disagrees with the explicit --store path; refusing to guess "
            "which one was intended.\n"
            f"  explicit (--store):           {explicit_resolved}\n"
            f"  environment (TTE_STORE_PATH): {env_resolved}\n"
            "Unset TTE_STORE_PATH or point it at the same file as --store. There is no "
            "override flag for this mismatch — see the 2026-08-31 stale-store export incident."
        )
        super().__init__(message)


def resolve_store_path(explicit: Path) -> Path:
    """Resolve and validate the studies-store path for an export/verify script.

    ``explicit`` is mandatory. If ``TTE_STORE_PATH`` is set in the environment
    and resolves to a different file than ``explicit``, raises
    :class:`StoreMismatchError`. If it agrees (or is unset), returns
    ``explicit.resolve()`` and sets ``os.environ["TTE_STORE_PATH"]`` to that
    resolved path, so every internal reader (``TTEStore``, ``TTEService``)
    that consults the environment variable agrees with the caller.

    Raises :class:`FileNotFoundError` if the resolved store file does not
    exist.
    """
    explicit_resolved = Path(explicit).resolve()

    env_value = os.environ.get("TTE_STORE_PATH")
    if env_value:
        env_resolved = Path(env_value).resolve()
        if env_resolved != explicit_resolved:
            raise StoreMismatchError(explicit, env_value)

    if not explicit_resolved.exists():
        raise FileNotFoundError(f"Store file does not exist: {explicit_resolved}")

    os.environ["TTE_STORE_PATH"] = str(explicit_resolved)
    return explicit_resolved
