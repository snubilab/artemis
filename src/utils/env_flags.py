"""Boolean environment switches that default on and only accept the word true.

A cold run has to be a deliberate act. Comparing against ``\"true\"`` (not
against ``\"false\"``) means ``\"0\"``, ``\"yes\"``, a typo, or an empty string
all disable the flag — a slower run rather than one that silently replayed
cached results while claiming to be cold.

Agent 1's IR cache and Agent 2's criterion cache share this convention so a
cold pipeline is two variables and no file surgery.
"""
from __future__ import annotations

import os


def env_flag_enabled(name: str, default: str = "true") -> bool:
    """Return True only when *name* is unset-with-default or set to ``true``.

    :param name: environment variable to read.
    :param default: value used when the variable is unset. The caches pass
        ``\"true\"`` so the default is on.
    """
    return os.environ.get(name, default).lower() == "true"
