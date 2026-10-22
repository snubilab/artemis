"""The entity a criterion names, as its protocol line spells it out in full.

The concept retriever embeds the seed as written. A bare abbreviation embeds next to the
wrong things: on the 2026-10-17 P6 SEG-OFF arm, ``TIA`` retrieved 60 candidates without
373503 Transient cerebral ischemia (the reranker then chose 'Infarction of thyroid'), and
``eGFR`` retrieved the Epidermal Growth Factor Receptor family (LEADER shipped six
natriuretic-peptide tests as eGFR). The curated table that used to rewrite four of these
(``query_expander._CURATED_EXPANSIONS``) was a word list and is gone (266971e).

What an abbreviation stands for is decided here by one LLM call, shown the protocol line
and the entity, never by a table or a text test. The model lists the entity's abbreviations
as spans; the entity is renamed only when one span is the whole entity, and an answer
differing from the entity in letter case alone is the entity.

Cache: one JSONL file keyed on the prompt version, both prompts and the resolved model.
``ARTEMIS_ENTITY_NAME_CACHE_PATH`` isolates it; ``ARTEMIS_ENTITY_NAME_CACHE=0`` disables
it. Failed calls are never cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Bumped whenever either prompt below changes meaning; part of the cache key.
ENTITY_NAME_PROMPT_VERSION = "entity-full-name-v3"

ENTITY_NAME_SYSTEM_PROMPT = (
    "You find the abbreviations in the name of a clinical entity and write each one out in full. "
    "Return one JSON object and nothing else."
)

ENTITY_NAME_PROMPT = """Protocol line:
{line}

Entity extracted from it: {entity}

Fields to return:

`abbreviations` lists each abbreviation, acronym or initialism in the entity that the entity \
does not already spell out. A word that is not shortened is not an abbreviation. When the \
entity holds none, `abbreviations` is an empty list.

`span` is the abbreviation alone, exactly as it is written in the entity: only the shortened \
letters, without the words around them.

`full_term` is what those letters stand for, and nothing more. It replaces `span` inside the \
entity, so it does not repeat the words around the span. When the protocol line writes the \
same term out in full, use the line's spelling of it.

Output JSON:
{{"abbreviations": [{{"span": "<the abbreviation as written in the entity>", "full_term": "<what it stands for>"}}]}}"""

_CACHE_PATH_ENV = "ARTEMIS_ENTITY_NAME_CACHE_PATH"
_CACHE_ENABLED_ENV = "ARTEMIS_ENTITY_NAME_CACHE"
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[3] / ".cache" / "entity_full_name" / "names.jsonl"

_lock = threading.Lock()
_memory: dict[str, list[list[str]]] = {}
_loaded_from: str | None = None


def _cache_path() -> Path:
    raw = os.environ.get(_CACHE_PATH_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_PATH


def _load() -> dict[str, list[list[str]]]:
    """Read the cache once per path. Call under the lock."""
    global _loaded_from
    path = _cache_path()
    if _loaded_from != str(path):
        _memory.clear()
        _loaded_from = str(path)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                    _memory[record["key"]] = record["pairs"]
                except (ValueError, KeyError, TypeError):
                    logger.warning("[entity-name] skipping damaged cache line in %s", path)
    return _memory


def reset_for_tests() -> None:
    """Drop the in-process cache. Test helper, not production API."""
    global _loaded_from
    with _lock:
        _loaded_from = None
        _memory.clear()


def _ask(llm: Any, prompt: str) -> list[tuple[str, str]] | None:
    """The model's (span, full_term) pairs, or None when the answer is not a list of them."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.utils.llm import extract_answer, raise_if_truncated

    response = llm.invoke([SystemMessage(content=ENTITY_NAME_SYSTEM_PROMPT), HumanMessage(content=prompt)])
    raise_if_truncated(response, what="entity full name")
    cleaned, _strategy = extract_answer(str(response.content))
    payload = json.loads(cleaned)
    entries = payload.get("abbreviations") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return None
    return [
        (entry["span"].strip(), " ".join(entry["full_term"].split()))
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("span"), str) and isinstance(entry.get("full_term"), str)
        and entry["span"].strip() and entry["full_term"].strip()
    ]


def full_entity_name(entity: str, protocol_line: str | None, *, model: str | None = None, llm: Any = None) -> str:
    """``entity`` with its abbreviations written out as ``protocol_line`` uses them.

    Never raises for a model failure: the entity itself is returned and the failure logged.

    :param entity: the mapper's seed.
    :param protocol_line: the criterion's ``protocolLine``; without one the model is not asked.
    :param model: model override; defaults to the critic's model.
    :param llm: a chat model handle; built from ``model`` when None.
    :returns: the full name, or ``entity`` when it is unchanged, differs only in case, or no
        readable answer came back.
    """
    entity = " ".join((entity or "").split())
    line = " ".join((protocol_line or "").split())
    if not entity or not line:
        return entity
    from src.agents.agent2.critic import select_critic_model
    from src.utils.llm import ENTITY_FULL_NAME_MAX_TOKENS, get_llm, resolve_model

    resolved = resolve_model(model or select_critic_model(None))
    prompt = ENTITY_NAME_PROMPT.format(line=line, entity=entity)
    key = hashlib.sha256(
        json.dumps([ENTITY_NAME_PROMPT_VERSION, ENTITY_NAME_SYSTEM_PROMPT, prompt, resolved]).encode()
    ).hexdigest()
    enabled = os.environ.get(_CACHE_ENABLED_ENV) != "0"
    with _lock:
        pairs = _load().get(key) if enabled else None
    if pairs is None:
        try:
            pairs = _ask(llm if llm is not None else get_llm(model_name=resolved, temperature=0.0, json_mode=True, max_tokens=ENTITY_FULL_NAME_MAX_TOKENS),
                         prompt)
        except Exception as exc:  # a failed call maps the seed as written, as before this step existed
            logger.warning("[entity-name] no full name for %r (%s: %s); mapped as written",
                           entity, type(exc).__name__, exc)
            return entity
        if pairs is None:
            logger.warning("[entity-name] unreadable answer for %r; mapped as written", entity)
            return entity
        if enabled:
            with _lock:
                _load()[key] = [list(pair) for pair in pairs]
                path = _cache_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"key": key, "entity": entity, "pairs": pairs,
                                             "model": resolved}, ensure_ascii=False) + "\n")
    # Only an entity that IS one abbreviation is renamed. Inside a longer name the other words
    # already steer retrieval, and rewriting part of a string needs token boundaries the code
    # may not compute from text (measured: span 'h' rewrote "therapy", span 'ST' doubled
    # "ST-segment"). A whole-entity span changes nothing but the abbreviation itself.
    full = next((full_term for span, full_term in pairs if span == entity), entity)
    # Letter case is not a different name; a case-only rewrite would re-roll the reranker for nothing.
    return entity if full.casefold() == entity.casefold() else full
