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

A second call (:func:`specific_entity_name`) asks whether the line names a narrower form of
the entity than the seed does. Measured on P8 MAIN: EMPA-REG inclusion 1 reads "Diagnosis of
type 2 diabetes mellitus" and Agent 1 seeded 'Diabetes Mellitus', which mapped to 201820
Diabetes mellitus (both gold T2DM rows P 0.45) and left the comparator without its registered
anchor 201826 (DiseaseAnchorError). The model returns the narrower span; code accepts it only
when it is copied verbatim from the line and holds the seed, so nothing outside the line can
become a query. No word list decides what is narrower.

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

#: Bumped whenever either specific-form prompt changes meaning; part of that call's cache key.
ENTITY_SPECIFIC_PROMPT_VERSION = "entity-specific-form-v1"

ENTITY_SPECIFIC_SYSTEM_PROMPT = (
    "You find where a protocol line names a narrower kind of a clinical entity than the entity "
    "name does. Return one JSON object and nothing else."
)

ENTITY_SPECIFIC_PROMPT = """Protocol line:
{line}

Entity extracted from it: {entity}

Field to return:

`specific_span` is the phrase of the protocol line that names a narrower kind of the entity: \
the entity's own words together with the words next to them in the line that say which kind, \
type, form or variant of the entity is meant. Every patient the phrase describes has the \
entity. Copy the phrase character for character from the line. Words that say when, how long, \
how much, how it was diagnosed or treated, whether it is planned, or what is left out of the \
entity do not name a kind and are not part of the phrase. When the line names no narrower kind \
of the entity, `specific_span` is an empty string.

Output JSON:
{{"specific_span": "<the phrase copied from the protocol line, or an empty string>"}}"""

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


def _ask(llm: Any, system: str, prompt: str) -> dict[str, Any] | None:
    """The model's JSON object, or None when the answer is not one."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.utils.llm import extract_answer, raise_if_truncated

    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
    raise_if_truncated(response, what="entity full name")
    cleaned, _strategy = extract_answer(str(response.content))
    payload = json.loads(cleaned)
    return payload if isinstance(payload, dict) else None


def _abbreviation_pairs(payload: dict[str, Any]) -> list[tuple[str, str]] | None:
    """(span, full_term) pairs, or None when ``abbreviations`` is not a list."""
    entries = payload.get("abbreviations")
    if not isinstance(entries, list):
        return None
    return [
        (entry["span"].strip(), " ".join(entry["full_term"].split()))
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("span"), str) and isinstance(entry.get("full_term"), str)
        and entry["span"].strip() and entry["full_term"].strip()
    ]


def _specific_pairs(payload: dict[str, Any]) -> list[tuple[str, str]] | None:
    """One ("", span) pair, the span "" when none; None when ``specific_span`` is no string."""
    span = payload.get("specific_span")
    return [("", " ".join(span.split()))] if isinstance(span, str) else None


def _cached_pairs(entity: str, version: str, system: str, prompt: str, parse: Any,
                  model: str | None, llm: Any) -> list[list[str]] | list[tuple[str, str]] | None:
    """The parsed answer for this prompt, from the cache or one model call; None on failure."""
    from src.agents.agent2.critic import select_critic_model
    from src.utils.llm import get_llm, resolve_model

    resolved = resolve_model(model or select_critic_model(None))
    key = hashlib.sha256(json.dumps([version, system, prompt, resolved]).encode()).hexdigest()
    enabled = os.environ.get(_CACHE_ENABLED_ENV) != "0"
    with _lock:
        pairs = _load().get(key) if enabled else None
    if pairs is not None:
        return pairs
    try:
        payload = _ask(llm if llm is not None else get_llm(model_name=resolved, temperature=0.0, json_mode=True),
                       system, prompt)
        pairs = parse(payload) if payload is not None else None
    except Exception as exc:  # a failed call maps the seed as written, as before this step existed
        logger.warning("[entity-name] no answer for %r (%s: %s); mapped as written", entity, type(exc).__name__, exc)
        return None
    if pairs is None:
        logger.warning("[entity-name] unreadable answer for %r; mapped as written", entity)
        return None
    if enabled:
        with _lock:
            _load()[key] = [list(pair) for pair in pairs]
            path = _cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"key": key, "entity": entity, "pairs": pairs,
                                         "model": resolved}, ensure_ascii=False) + "\n")
    return pairs


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
    pairs = _cached_pairs(entity, ENTITY_NAME_PROMPT_VERSION, ENTITY_NAME_SYSTEM_PROMPT,
                          ENTITY_NAME_PROMPT.format(line=line, entity=entity), _abbreviation_pairs, model, llm)
    if pairs is None:
        return entity
    # Only an entity that IS one abbreviation is renamed. Inside a longer name the other words
    # already steer retrieval, and rewriting part of a string needs token boundaries the code
    # may not compute from text (measured: span 'h' rewrote "therapy", span 'ST' doubled
    # "ST-segment"). A whole-entity span changes nothing but the abbreviation itself.
    full = next((full_term for span, full_term in pairs if span == entity), entity)
    # Letter case is not a different name; a case-only rewrite would re-roll the reranker for nothing.
    return entity if full.casefold() == entity.casefold() else full


def specific_entity_name(entity: str, protocol_line: str | None, *, model: str | None = None,
                         llm: Any = None) -> str:
    """The narrower form of ``entity`` that ``protocol_line`` names, as the line writes it.

    Never raises for a model failure: the entity itself is returned and the failure logged.

    :param entity: the mapper's seed.
    :param protocol_line: the criterion's ``protocolLine``; the model is asked only when the
        line holds the seed (otherwise no answer could pass the check below).
    :param model: model override; defaults to the critic's model.
    :param llm: a chat model handle; built from ``model`` when None.
    :returns: the model's span when it is copied verbatim from the line, holds the seed and is
        more than the seed; otherwise ``entity``.
    """
    entity = " ".join((entity or "").split())
    line = " ".join((protocol_line or "").split())
    if not entity or entity.casefold() not in line.casefold():
        return entity
    pairs = _cached_pairs(entity, ENTITY_SPECIFIC_PROMPT_VERSION, ENTITY_SPECIFIC_SYSTEM_PROMPT,
                          ENTITY_SPECIFIC_PROMPT.format(line=line, entity=entity), _specific_pairs, model, llm)
    span = pairs[0][1] if pairs else ""
    # The structural check, not a judgement of meaning: the span is the line's own text, it
    # holds the seed, and it says more than the seed. Anything else maps the seed as written.
    if span and span in line and entity.casefold() in span.casefold() and span.casefold() != entity.casefold():
        return span
    return entity
