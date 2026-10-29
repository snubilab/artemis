"""Two cached wordings judge only seeds the reranker chose and the critic rejected.

A drop requires the critic and both wordings to reject a seed. All three can be
wrong; this agreement is not proof of clinical correctness. The workflow restores
all reranker seeds if every one would otherwise be dropped.
"""
import hashlib
import json
import logging
from enum import Enum

from langchain_core.exceptions import OutputParserException
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ValidationError

from src.agents.agent2.critic_cache import CriticCache
from src.utils.llm import StrictJsonOutputParser, get_llm, raise_if_truncated, resolve_model

logger = logging.getLogger(__name__)

SEED_TIEBREAK_SYSTEM_PROMPT = (
    "You judge one OMOP concept against one clinical term from a trial eligibility criterion. "
    "Return one JSON object and nothing else."
)
SEED_TIEBREAK_PROMPT_VERSION = "gatefix-seed-tiebreak-v1"
SEED_TIEBREAK_AGREEMENT_PROMPT_VERSION = "gatefix-seed-tiebreak-placebo-v1"

SEED_TIEBREAK_PROMPT = """Clinical term: {term}
Concept: {concept}

`answer` states whether every patient whose record carries this concept has what the clinical term \
names. One of:
- `yes`: every such patient has it; the concept is the term itself, a synonym, or a more specific \
kind of it.
- `no`: some such patients do not have it; the concept is broader than the term, or a different \
entity.

Output JSON:
{{"answer": "<yes|no>"}}"""

SEED_TIEBREAK_AGREEMENT_PROMPT = """Clinical term: {term}
Concept: {concept}

`answer` says whether a patient recorded with this concept always has what the clinical term names. \
One of:
- `yes`: always; the concept names the term, a synonym of it, or a narrower kind of it.
- `no`: not always; the concept covers more than the term does, or names something else.

Output JSON:
{{"answer": "<yes|no>"}}"""  # noqa: E501 - verbatim design prompt


class _Answer(str, Enum):
    YES = "yes"
    NO = "no"


class _Reply(BaseModel):
    answer: _Answer


# Reuse agent2's thread-safe TTL/LRU cache; its integer lists encode yes=[1], no=[0].
# A separate instance and prompt/model/input digest keep these out of critic entries.
_cache = CriticCache()


def _ask(term: str, concept: str, version: str, body: str, model: str, key: str) -> dict:
    record = {"answer": "not_called", "prompt_version": version, "cache_key": key}
    cached = _cache.get(key)
    if cached is not None:
        record["answer"] = "yes" if cached == [1] else "no"
        return record
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", SEED_TIEBREAK_SYSTEM_PROMPT), ("human", body),
        ])
        llm = get_llm(model_name=model, temperature=0.0, json_mode=True, max_tokens=256)
        response = (prompt | llm).invoke({"term": term, "concept": concept})
        raise_if_truncated(response, what="seed tiebreak")
        payload = StrictJsonOutputParser().parse(response.content)
        record["answer"] = _Reply.model_validate(payload).answer.value
    except (OutputParserException, ValidationError) as exc:
        record["answer"] = "unreadable"
        record["error"] = str(exc)
    except Exception as exc:
        record["answer"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
    if "error" in record:
        logger.warning("[seed-tiebreak] keeping seed: %s", record)
    else:
        _cache.put(key, [1 if record["answer"] == "yes" else 0])
    return record


def judge_seed(term: str, concept: str) -> dict:
    """Return both auditable verdicts; only no/no proposes a drop, errors keep."""
    model = resolve_model()

    def key(version: str, body: str) -> str:
        raw = json.dumps([
            version, SEED_TIEBREAK_SYSTEM_PROMPT, body, term, concept, model, 0.0,
        ])
        return hashlib.sha256(raw.encode()).hexdigest()

    first_key = key(SEED_TIEBREAK_PROMPT_VERSION, SEED_TIEBREAK_PROMPT)
    second_key = key(SEED_TIEBREAK_AGREEMENT_PROMPT_VERSION, SEED_TIEBREAK_AGREEMENT_PROMPT)
    first = _ask(
        term, concept, SEED_TIEBREAK_PROMPT_VERSION, SEED_TIEBREAK_PROMPT, model, first_key,
    )
    second = {"answer": "not_called", "prompt_version": SEED_TIEBREAK_AGREEMENT_PROMPT_VERSION,
              "cache_key": second_key}
    if first["answer"] == "no":
        second = _ask(term, concept, SEED_TIEBREAK_AGREEMENT_PROMPT_VERSION,
                      SEED_TIEBREAK_AGREEMENT_PROMPT, model, second_key)
    return {"first": first, "second": second,
            "drop": first["answer"] == "no" and second["answer"] == "no"}
