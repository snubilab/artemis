"""The specimen critic: which (System, challenge) options a Measurement criterion states.

RFC-016 step 4 (A17 + C3). Which LOINC lab tests a criterion's concept set may hold depends on
the specimen and the challenge the protocol line states -- serum or urine, fasting or not. The
vocabulary does not decide it: no ``Is a`` edge says a LOINC System is a blood specimen, and
the SNOMED ``Has specimen`` path reaches 15% of the lab tests in the candidate store's sets
(see ``src.services.loinc_specimen``). The word tables that used to decide it are gone. This
LLM call decides it from the candidates and the annotation's ``specimen`` field: it is shown
the protocol line, the analyte, the recorded specimen and its fragment, and the distinct
(System, challenge) options of the set's members and candidates, and answers which options
the criterion states.

Code checks one thing only: every identifier it returns is one it was offered. An answer that
cannot be read is no answer (``None``), never a guess -- the plan then decides no specimen and
removes only what the unit's property contradicts, and the builder records ``judged: false``.

Cache: one JSONL file keyed on the prompt version, the prompt text, the rendered inputs and
the resolved model. ``ARTEMIS_SPECIMEN_CRITIC_CACHE_PATH`` isolates it;
``ARTEMIS_SPECIMEN_CRITIC_CACHE=0`` disables it. Failed calls are never cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.services.loinc_specimen import SpecimenOption

logger = logging.getLogger(__name__)

#: Bumped whenever either prompt below changes meaning; part of the cache key.
SPECIMEN_CRITIC_PROMPT_VERSION = "rfc016-step4-specimen-v1"

FIELD_ACCEPTED = "accepted"

SPECIMEN_CRITIC_SYSTEM_PROMPT = """You judge which laboratory test variants one eligibility \
criterion of a clinical trial protocol refers to.

Each variant is a specimen a laboratory test is performed on, together with the condition the \
test is taken under when it has one. You choose only among the variants listed. Return one \
JSON object and nothing else."""

SPECIMEN_CRITIC_PROMPT = """Protocol line:
{protocol_line}

Measured quantity: {analyte}
Body material the annotation records for this criterion: {specimen}
Fragment of the protocol line that names it: {specimen_span}

Variants:
{variants}

Fields to return:

`accepted` lists the identifiers of the variants this criterion's measurement can be: the \
variant's specimen is the body material the protocol line states, and the variant's condition \
is one the protocol line states, or the variant has no condition. When the recorded body \
material is `any`, the line names none: accept the specimens in which this quantity is \
ordinarily measured to decide a patient's eligibility. A variant whose specimen or condition \
the line contradicts is not accepted.

Output JSON:
{{"accepted": ["<variant identifier>"]}}"""

OptionKey = tuple[int | None, str | None, str | None]


def _text(value: Any) -> str:
    rendered = " ".join(str(value).split()) if value is not None else ""
    return rendered or "none"


def render_prompt(
    *,
    protocol_line: str | None,
    analyte: str,
    specimen: str,
    specimen_span: str | None,
    options: Sequence[SpecimenOption],
) -> tuple[str, dict[str, SpecimenOption]]:
    """The user message, and the identifier each option is shown under.

    :returns: ``(prompt, identifier -> option)``; identifiers follow the options' order.
    """
    identified = {f"V{n}": option for n, option in enumerate(options, start=1)}
    variants = "\n".join(
        f"- {ident}: specimen {_text(option.system)}; condition {_text(option.challenge)}"
        for ident, option in identified.items()
    )
    prompt = SPECIMEN_CRITIC_PROMPT.format(
        protocol_line=_text(protocol_line),
        analyte=_text(analyte),
        specimen=_text(specimen),
        specimen_span=_text(specimen_span),
        variants=variants,
    )
    return prompt, identified


def accepted_keys(
    payload: Any, identified: Mapping[str, SpecimenOption]
) -> frozenset[OptionKey] | None:
    """The offered options the answer accepts; None when the answer is not a readable list.

    An identifier that was not offered is dropped and logged -- never matched loosely.
    """
    entries = payload.get(FIELD_ACCEPTED) if isinstance(payload, Mapping) else None
    if not isinstance(entries, list):
        return None
    unknown = [
        entry for entry in entries if not isinstance(entry, str) or entry.strip() not in identified
    ]
    if unknown:
        logger.warning("[specimen-critic] dropped identifiers it was not offered: %s", unknown)
    return frozenset(
        identified[entry.strip()].key
        for entry in entries
        if isinstance(entry, str) and entry.strip() in identified
    )


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

_CACHE_PATH_ENV = "ARTEMIS_SPECIMEN_CRITIC_CACHE_PATH"
_CACHE_ENABLED_ENV = "ARTEMIS_SPECIMEN_CRITIC_CACHE"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_PATH = _REPO_ROOT / ".cache" / "specimen_critic" / "judgements.jsonl"

_cache_lock = threading.Lock()
_memory: dict[str, dict[str, Any]] = {}
_loaded_from: str | None = None


def cache_path() -> Path:
    """:returns: the JSONL file backing the cache."""
    raw = os.environ.get(_CACHE_PATH_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_PATH


def _cache_enabled() -> bool:
    return os.environ.get(_CACHE_ENABLED_ENV) != "0"


def cache_key(prompt: str, model: str) -> str:
    """A stable key over the prompt version, both prompts and the resolved model."""
    payload = json.dumps(
        [SPECIMEN_CRITIC_PROMPT_VERSION, SPECIMEN_CRITIC_SYSTEM_PROMPT, prompt, model],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load() -> dict[str, dict[str, Any]]:
    """Read the cache once per path. Call under the lock."""
    global _loaded_from
    path = cache_path()
    if _loaded_from == str(path):
        return _memory
    _memory.clear()
    _loaded_from = str(path)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    _memory[record["key"]] = record
                except (ValueError, KeyError, TypeError):
                    logger.warning(
                        "[specimen-critic] skipping damaged cache line %s:%d", path, number
                    )
    return _memory


def _cache_get(key: str) -> dict[str, Any] | None:
    if not _cache_enabled():
        return None
    with _cache_lock:
        return _load().get(key)


def _cache_put(key: str, record: dict[str, Any]) -> None:
    if not _cache_enabled():
        return
    with _cache_lock:
        _load()[key] = record
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"key": key, **record}, ensure_ascii=False) + "\n")


def reset_for_tests() -> None:
    """Drop the in-process cache. Test helper, not production API."""
    global _loaded_from
    with _cache_lock:
        _loaded_from = None
        _memory.clear()


# --------------------------------------------------------------------------- #
# The call
# --------------------------------------------------------------------------- #


def _build_llm(model: str) -> Any:
    """Separate so a test substitutes a stub without reaching a network."""
    from src.utils.llm import get_llm

    return get_llm(model_name=model, temperature=0.0, json_mode=True)


def _complete(llm: Any, prompt: str) -> Any:
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.utils.llm import _last_json_value, extract_answer, raise_if_truncated

    response = llm.invoke(
        [SystemMessage(content=SPECIMEN_CRITIC_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    )
    raise_if_truncated(response, what="specimen critic")
    cleaned, _strategy = extract_answer(str(response.content))
    try:
        return json.loads(cleaned)
    except ValueError:
        value = _last_json_value(cleaned)
        if value is None:
            raise
        return json.loads(value)


def judge_specimen_options(
    *,
    protocol_line: str | None,
    analyte: str,
    specimen: str,
    specimen_span: str | None,
    options: Sequence[SpecimenOption],
    model: str | None = None,
    llm: Any = None,
) -> frozenset[OptionKey] | None:
    """Which of ``options`` the criterion states. Never raises for a model failure.

    :param protocol_line: the criterion's ``protocolLine``.
    :param analyte: the LOINC component the set measures.
    :param specimen: the annotation's verified ``specimen`` value (``any`` when none).
    :param specimen_span: its fragment of the line, None for ``any``.
    :param options: the (System, challenge) options of the members and candidates.
    :param model: model override; defaults to the critic's model.
    :param llm: a chat model handle; built from ``model`` when None.
    :returns: the accepted option keys, or None when the model gave no readable answer.
    """
    if not options:
        return frozenset()
    from src.agents.agent2.critic import select_critic_model
    from src.utils.llm import resolve_model

    resolved = resolve_model(model or select_critic_model("Measurement"))
    prompt, identified = render_prompt(
        protocol_line=protocol_line,
        analyte=analyte,
        specimen=specimen,
        specimen_span=specimen_span,
        options=options,
    )
    key = cache_key(prompt, resolved)
    cached = _cache_get(key)
    if cached is not None:
        payload = cached.get("payload")
    else:
        try:
            payload = _complete(llm if llm is not None else _build_llm(resolved), prompt)
        except Exception as exc:
            logger.warning(
                "[specimen-critic] no judgement for %r (%s: %s); the specimen is left undecided",
                analyte,
                type(exc).__name__,
                exc,
            )
            return None
        if accepted_keys(payload, identified) is not None:
            _cache_put(
                key,
                {
                    "payload": payload,
                    "model": resolved,
                    "promptVersion": SPECIMEN_CRITIC_PROMPT_VERSION,
                },
            )
    accepted = accepted_keys(payload, identified)
    if accepted is None:
        logger.warning("[specimen-critic] unreadable answer for %r: %r", analyte, payload)
    return accepted
