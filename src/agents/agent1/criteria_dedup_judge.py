"""The LLM arm of "does this criterion restate an [OR-GROUP] alternative?".

:mod:`src.agents.agent1.criteria_dedup` answers that question with hand-tuned
lexical rules -- a stopword list, a 0.85 fuzzy-token threshold, an initialism
rule, a negator word list, a conjunction-phrase list and a 0.70 coverage bar.
That list was grown one case at a time and cannot close: keying conjunction on
the token "and" missed "plus", adding "plus" missed "as well as". It was also
tuned against a corpus holding exactly ONE OR-GROUP, so it is not falsifiable.

This module is the competing arm, not a replacement. Both arms answer the same
question with the same signature so a harness can score them against the same
labelled table; :func:`judge_arm` picks which one runs, and the lexical arm
stays the default until a measurement says otherwise.

Why the answer matters in both directions:

* wrongly NO -- the alternative is re-added as a top-level rule, Circe ANDs it
  with the group, and the cohort collapses (the ARISTOTLE 0-patient bug).
* wrongly YES -- a mandatory or EXCLUSION criterion is deleted and the cohort
  silently WIDENS. This is the more dangerous direction because nothing looks
  broken, which is why the prompt tells the model to answer ``distinct`` when it
  is unsure.

Three properties are load-bearing and are pinned by
``tests/test_criteria_dedup_judge.py``:

1. **No gold.** This module never reads ``data/gold/``. Gold labels belong to
   the scoring harness only. A judge that needs gold cannot be moved to the
   hospital data the user intends to validate on next.
2. **No word lists.** No negator list, no conjunction-marker list, no phrase
   table. Those are the defect being removed, not a thing to port. Every
   semantic call is the model's.
3. **No silent fallback.** An LLM error or an unparseable response yields the
   :data:`ERROR` verdict with ``is_restatement`` set to ``None`` -- never
   ``False``. Falling back to the lexical rule would make the LLM arm partly the
   baseline arm and the comparison meaningless; falling back to ``False`` would
   look like a "keep" verdict the model never gave.

The two structural early returns in :func:`judge_or_group_restatement` are kept
verbatim from the lexical arm because they are contract, not heuristics: an
OR-GROUP candidate is never a duplicate (whether one GROUP supersedes another is
a different question, answered by ``criteria_dedup.or_group_subsumed_by``), and
no OR-GROUP in ``items`` means there is nothing to restate. Everything past them
goes to the model.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from src.agents.agent1 import criteria_dedup
from src.agents.agent1.criteria_dedup import is_or_group, or_group_alternatives

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Arm selection
# --------------------------------------------------------------------------- #

# Named-ablation pattern, following criteria_dedup.dedup_enabled(). Attributing a
# cohort count -- or a precision/recall row -- to one arm needs the other arm run
# through the identical pipeline, and swapping source files mid-experiment leaves
# the tree broken if the run dies.
_ARM_ENV = "ARTEMIS_ORGROUP_JUDGE"

ARM_LEXICAL = "lexical"
ARM_LLM = "llm"
ARM_OFF = "off"
ARMS = (ARM_LEXICAL, ARM_LLM, ARM_OFF)

# Default is the lexical baseline, so importing this module cannot move
# production behaviour. Only an explicit env var switches arms.
DEFAULT_ARM = ARM_LEXICAL


class JudgeConfigurationError(ValueError):
    """The arm env var names an arm that does not exist."""


class JudgeError(RuntimeError):
    """The LLM arm could not produce a verdict.

    Raised at the boolean boundary rather than returning ``False``: a caller that
    reads ``False`` cannot tell "the model said keep" from "the model was not
    reached", and every downstream count would silently absorb the difference.
    """


def judge_arm() -> str:
    """Which arm answers the restatement question.

    An unrecognised value raises instead of defaulting. A typo in a benchmark
    launcher would otherwise produce a whole run labelled ``llm`` and executed by
    ``lexical`` -- the same class of provenance failure as a model name without
    its ``vllm/`` prefix reaching a paid remote provider.

    :returns: one of :data:`ARMS`.
    :raises JudgeConfigurationError: when the env var holds an unknown arm.
    """
    raw = os.environ.get(_ARM_ENV, "").strip()
    if not raw:
        return DEFAULT_ARM
    arm = raw.lower()
    if arm not in ARMS:
        raise JudgeConfigurationError(
            f"{_ARM_ENV}={raw!r} is not a known arm. Expected one of {', '.join(ARMS)}."
        )
    return arm


# --------------------------------------------------------------------------- #
# Verdicts
# --------------------------------------------------------------------------- #

# A bare boolean throws away exactly the information needed to read a
# disagreement between the arms: WHY the judge kept a criterion. These four are
# the model's answer space; ERROR is ours.
RESTATEMENT = "restatement"
CONJUNCTION_OF_ALTERNATIVES = "conjunction_of_alternatives"
NEGATION_OF_ALTERNATIVE = "negation_of_alternative"
DISTINCT = "distinct"
ERROR = "error"

MODEL_VERDICTS = (RESTATEMENT, CONJUNCTION_OF_ALTERNATIVES, NEGATION_OF_ALTERNATIVE, DISTINCT)

# Only RESTATEMENT deletes a criterion. A conjunction of alternatives is STRICTER
# than the group it appears to echo, and a negation is the opposite polarity;
# deleting either widens the cohort, so both map to "keep".
_VERDICT_TO_BOOL: dict[str, bool] = {
    RESTATEMENT: True,
    CONJUNCTION_OF_ALTERNATIVES: False,
    NEGATION_OF_ALTERNATIVE: False,
    DISTINCT: False,
}

# Where the verdict came from, recorded per row so the harness can separate a
# model judgement from a structural one it never paid for.
SOURCE_STRUCTURAL = "structural"
SOURCE_LLM = "llm"
SOURCE_CACHE = "cache"
SOURCE_LEXICAL = "lexical"
SOURCE_OFF = "off"


@dataclass(frozen=True)
class JudgeResult:
    """One restatement decision, with the provenance a result row needs.

    :ivar verdict: one of :data:`MODEL_VERDICTS` or :data:`ERROR`.
    :ivar is_restatement: the boolean the drop-in contract exposes; ``None`` for
        :data:`ERROR`, which is what makes "no verdict" impossible to confuse
        with "keep".
    :ivar arm: the arm that answered, from :func:`judge_arm`.
    :ivar model: ``src.utils.llm.resolve_model()`` read at call time, never a
        literal. A row whose provenance names one model while the traffic went to
        another is a discarded row.
    :ivar llm_called: False for structural early returns, cache hits, the lexical
        arm and the off arm. ``model`` is still recorded for those rows because it
        identifies the configuration, not because a call happened.
    :ivar matched_alternatives: the alternatives the model says the candidate
        refers to.
    :ivar reason: the model's one-line justification.
    :ivar error: populated only for :data:`ERROR`.
    :ivar warnings: non-fatal parse problems, e.g. an out-of-range alternative
        index. Recorded rather than swallowed.
    """

    verdict: str
    is_restatement: bool | None
    arm: str
    model: str
    source: str
    llm_called: bool = False
    matched_alternatives: tuple[str, ...] = ()
    reason: str = ""
    error: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #

# Bumping this invalidates every cached verdict, because a cached verdict is only
# reproducible under the prompt that produced it.
PROMPT_VERSION = "v1"

# No word lists here on purpose. The four verdicts are described by what they
# MEAN for patient eligibility; which surface forms express them is the model's
# problem, and offloading it is the entire point of this arm.
_JUDGE_PROMPT = """\
You are checking a clinical trial's eligibility criteria for redundancy.

The criteria list already contains a disjunctive group: a patient satisfies it \
by meeting AT LEAST ONE of these alternatives.

{alternatives}

Candidate criterion under review:
{candidate}

Judge by meaning, not wording. Paraphrases, abbreviations and their expansions, \
and different phrasings or units of the same clinical requirement all state the \
same requirement.

Choose exactly one verdict:

- "restatement": the candidate states a requirement the group already offers as \
an alternative, and adds nothing beyond it. Keeping it as its own separate rule \
would change nothing about who qualifies.
- "conjunction_of_alternatives": the candidate requires two or more of the \
alternatives to hold AT THE SAME TIME. That is stricter than the group, which \
accepts any one of them alone.
- "negation_of_alternative": the candidate asserts the absence, exclusion or \
opposite of an alternative rather than its presence.
- "distinct": the candidate carries a requirement none of the alternatives \
expresses.

If you are not confident the candidate is genuinely already covered, answer \
"distinct". Wrongly calling it a restatement deletes a real requirement and \
silently admits patients the trial excludes.

Return ONLY this JSON object, with no other text:
{{"verdict": "restatement | conjunction_of_alternatives | negation_of_alternative | distinct",
 "matched_alternatives": [1-based indices of the alternatives above the candidate refers to, [] if none],
 "reason": "one short sentence"}}
"""


def _render_prompt(candidate: str, alternatives: Sequence[str]) -> str:
    """:param candidate: criterion under review. :param alternatives: the group's
    alternatives. :returns: the rendered judge prompt."""
    listing = "\n".join(f"{i}. {alt}" for i, alt in enumerate(alternatives, start=1))
    return _JUDGE_PROMPT.format(alternatives=listing, candidate=candidate)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

# A re-run must not re-bill, and two runs of the same table must produce the same
# rows. Keyed on (prompt version, candidate, alternatives, resolved model): every
# one of those changes the answer, and the model is in the key for the same
# reason it is in every result row.
_CACHE_PATH_ENV = "ARTEMIS_ORGROUP_JUDGE_CACHE_PATH"
_CACHE_ENABLED_ENV = "ARTEMIS_ORGROUP_JUDGE_CACHE"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_PATH = _REPO_ROOT / ".cache" / "orgroup_judge" / "verdicts.jsonl"

_memory: dict[str, dict] = {}
_loaded_from: str | None = None
_llm = None
_llm_model: str | None = None


def cache_path() -> Path:
    """:returns: the JSONL file backing the verdict cache (env-overridable)."""
    raw = os.environ.get(_CACHE_PATH_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_PATH


def cache_enabled() -> bool:
    """:returns: False only when the cache env var is explicitly set to 0."""
    return os.environ.get(_CACHE_ENABLED_ENV, "").strip() != "0"


def cache_key(candidate: str, alternatives: Sequence[str], model: str) -> str:
    """:param candidate: criterion under review. :param alternatives: the group's
    alternatives, in order. :param model: the resolved model string.
    :returns: a stable SHA256 key."""
    payload = json.dumps(
        [PROMPT_VERSION, candidate, list(alternatives), model],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_cache() -> dict[str, dict]:
    """Read the JSONL cache once per process, reloading if the path env changes."""
    global _loaded_from
    path = cache_path()
    if _loaded_from == str(path):
        return _memory
    _memory.clear()
    _loaded_from = str(path)
    if not path.exists():
        return _memory
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                _memory[record["key"]] = record
            except (ValueError, KeyError, TypeError):
                # A damaged cache line costs one extra call, never a wrong
                # verdict, so it is skipped loudly rather than raising.
                logger.warning("[OR-group judge] skipping damaged cache line %s:%d", path, line_no)
    return _memory


def _cache_get(key: str) -> dict | None:
    if not cache_enabled():
        return None
    return _load_cache().get(key)


def _cache_put(key: str, record: dict) -> None:
    """Persist one verdict. ERROR rows are never cached -- an outage must not stick."""
    if not cache_enabled():
        return
    _load_cache()[key] = record
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"key": key, **record}, ensure_ascii=False) + "\n")


def reset_for_tests() -> None:
    """Drop the in-process LLM handle and cache. Test helper, not production API."""
    global _llm, _llm_model, _loaded_from
    _llm = None
    _llm_model = None
    _loaded_from = None
    _memory.clear()


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #


def _build_llm(model: str):
    """:param model: the resolved model string. :returns: a chat model handle.

    Separate from :func:`_get_llm` so tests can substitute a stub without a
    network, and so the json_mode/temperature choices live in one place. Mirrors
    ``pubmed_fetcher._get_criteria_llm``.
    """
    from src.utils.llm import get_llm

    return get_llm(model_name=model, temperature=0.0, json_mode=True)


def _get_llm(model: str):
    """Cached per resolved model, so changing LLM_MODEL rebuilds the handle."""
    global _llm, _llm_model
    if _llm is None or _llm_model != model:
        _llm = _build_llm(model)
        _llm_model = model
        logger.info("[OR-group judge] initialised LLM arm with model=%s", model)
    return _llm


def _parse_response(content: str, alternatives: Sequence[str]) -> tuple[str, tuple[str, ...], str, tuple[str, ...]]:
    """Parse one model response into (verdict, matched, reason, warnings).

    :raises ValueError: when the response holds no JSON object, or names a
        verdict outside :data:`MODEL_VERDICTS`. The caller turns that into an
        :data:`ERROR` row; it is never softened into a verdict.
    """
    from src.utils.llm import extract_answer

    cleaned, _strategy = extract_answer(str(content))
    cleaned = cleaned.strip()
    if cleaned.startswith("```"):
        body = cleaned.split("```")[1]
        cleaned = body[4:].strip() if body.startswith("json") else body.strip()

    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object, got {type(payload).__name__}")

    verdict = str(payload.get("verdict", "")).strip().lower()
    if verdict not in MODEL_VERDICTS:
        raise ValueError(f"unknown verdict {payload.get('verdict')!r}")

    warnings: list[str] = []
    matched: list[str] = []
    for raw_index in payload.get("matched_alternatives") or []:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            warnings.append(f"non-numeric alternative index {raw_index!r}")
            continue
        if 1 <= index <= len(alternatives):
            matched.append(alternatives[index - 1])
        else:
            warnings.append(f"alternative index {index} out of range 1..{len(alternatives)}")

    reason = str(payload.get("reason", "")).strip()
    return verdict, tuple(matched), reason, tuple(warnings)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def judge_or_group_restatement(candidate: str, items: Sequence[str]) -> JudgeResult:
    """The rich answer to "does ``candidate`` restate an alternative in ``items``?".

    Dispatches on :func:`judge_arm`, so a harness gets a comparable
    :class:`JudgeResult` from every arm.

    :param candidate: the criterion being considered for addition or retention.
    :param items: the list it would join; the OR-GROUP reference is read from here.
    :returns: a :class:`JudgeResult`; ``verdict`` is :data:`ERROR` when the LLM
        arm could not answer.
    """
    from src.utils.llm import resolve_model

    arm = judge_arm()
    model = resolve_model()

    if arm == ARM_OFF:
        return JudgeResult(
            verdict=DISTINCT, is_restatement=False, arm=arm, model=model,
            source=SOURCE_OFF, reason="deduplication disabled by arm selection",
        )

    if arm == ARM_LEXICAL:
        flag = criteria_dedup.restates_or_group_alternative(candidate, items)
        return JudgeResult(
            verdict=RESTATEMENT if flag else DISTINCT, is_restatement=flag, arm=arm,
            model=model, source=SOURCE_LEXICAL,
            reason="lexical baseline (criteria_dedup.restates_or_group_alternative)",
        )

    # --- LLM arm. Structural contract first; the model never sees these. ---
    # (1) An OR-GROUP candidate is never a duplicate: a richer group would be
    #     discarded against a poorer one, destroying the structure this whole
    #     module exists to preserve.
    if not isinstance(candidate, str) or is_or_group(candidate):
        return JudgeResult(
            verdict=DISTINCT, is_restatement=False, arm=arm, model=model,
            source=SOURCE_STRUCTURAL, reason="candidate is itself an OR-GROUP",
        )
    # (2) No OR-GROUP in items means there is no group to restate.
    alternatives: list[str] = []
    for item in items:
        alternatives.extend(or_group_alternatives(item))
    if not alternatives:
        return JudgeResult(
            verdict=DISTINCT, is_restatement=False, arm=arm, model=model,
            source=SOURCE_STRUCTURAL, reason="no OR-GROUP among items",
        )

    key = cache_key(candidate, alternatives, model)
    hit = _cache_get(key)
    if hit is not None:
        return JudgeResult(
            verdict=hit["verdict"], is_restatement=_VERDICT_TO_BOOL[hit["verdict"]],
            arm=arm, model=hit["model"], source=SOURCE_CACHE,
            matched_alternatives=tuple(hit.get("matched_alternatives", ())),
            reason=hit.get("reason", ""), warnings=tuple(hit.get("warnings", ())),
        )

    try:
        from langchain_core.messages import HumanMessage

        response = _get_llm(model).invoke([HumanMessage(content=_render_prompt(candidate, alternatives))])
        verdict, matched, reason, warnings = _parse_response(getattr(response, "content", ""), alternatives)
    except Exception as exc:  # noqa: BLE001 - every failure becomes one ERROR row
        # Deliberately NOT falling back to the lexical rule or to False. Either
        # would silently blend the arms and make the comparison meaningless.
        logger.warning("[OR-group judge] no verdict (model=%s): %s", model, exc)
        return JudgeResult(
            verdict=ERROR, is_restatement=None, arm=arm, model=model,
            source=SOURCE_LLM, llm_called=True, error=f"{type(exc).__name__}: {exc}",
        )

    record = {
        "verdict": verdict, "model": model, "matched_alternatives": list(matched),
        "reason": reason, "warnings": list(warnings), "candidate": candidate,
        "alternatives": alternatives, "prompt_version": PROMPT_VERSION,
    }
    _cache_put(key, record)
    return JudgeResult(
        verdict=verdict, is_restatement=_VERDICT_TO_BOOL[verdict], arm=arm, model=model,
        source=SOURCE_LLM, llm_called=True, matched_alternatives=matched,
        reason=reason, warnings=warnings,
    )


def restates_or_group_alternative(
    candidate: str,
    items: Sequence[str],
    threshold: float | None = None,
) -> bool:
    """Drop-in for :func:`criteria_dedup.restates_or_group_alternative`.

    :param candidate: the criterion being considered for addition or retention.
    :param items: the list it would join.
    :param threshold: accepted so the signature stays drop-in; the LLM arm has no
        coverage threshold to tune, and it is forwarded only on the lexical arm.
    :returns: True when the candidate is an alternative the group already states.
    :raises JudgeError: when the LLM arm produced no verdict. Returning False
        there would be indistinguishable from a genuine "keep".
    """
    if threshold is not None and judge_arm() == ARM_LEXICAL:
        return criteria_dedup.restates_or_group_alternative(candidate, items, threshold)
    result = judge_or_group_restatement(candidate, items)
    if result.is_restatement is None:
        raise JudgeError(f"no verdict for candidate {candidate!r}: {result.error}")
    return result.is_restatement
