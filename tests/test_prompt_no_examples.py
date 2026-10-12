"""No example reaches an LLM: the inventoried ones are gone, and a new one cannot land.

The user's standing rule (``AGENTS.md`` § PROMPTS AND TEXT RULES, rule 1): a prompt
states field definitions and the decision to make, nothing else. No real or invented
protocol text, no filled-in sample JSON, no input->output or WRONG/RIGHT pairs, no lists
of trigger words to recognise, no prose recounting past measurements -- and that includes
text a library appends (LangChain's ``get_format_instructions()`` carries a foo/bar/baz
sample object and a counterexample).

``tests/test_prompt_corpus_contamination.py`` cannot enforce this. It compares prompts
with the six evaluated trials, so an INVENTED example passes it by construction -- 54 of
the 106 examples on the delivery path got in exactly that way (623e663).

THE THREE CHECKS
----------------
(i)   Regression from the real event. Every row of
      ``docs/inventory/2026-10-12_prompt_examples.json`` (205 rows) is gone: neither its
      ``needle`` nor its ``core_needle`` occurs in its source file. Rows marked
      ``rendered_only`` (the LangChain format-instruction block, which is library text)
      are checked in the rendered prompt instead. TX3 (``(corpus n=``) counts as present
      while any of its nine occurrences remains.
(ii)  New examples. Every prompt that reaches an LLM is RENDERED -- through its real call
      path with the LLM replaced by a recorder wherever the text is assembled at call time
      (LangChain chains, the classifier, the comparator, the TTE report), and through the
      call site's own ``str.format`` keywords where it is a module template -- and the
      rendered text is linted for four shapes:
        * a quoted span (straight, curly or single quotes, or backticks) whose content is
          not a token declared for that prompt: a field name, an enum value, a JSON key,
          an OMOP / CIRCE name, a required output phrase, or runtime stub data;
        * a JSON-like block (``{key: value}``) holding a filled value -- a number, a
          boolean, or a string that is not a ``<placeholder>``, ``...``, an alternation
          of declared tokens, or a declared description placeholder;
        * an example marker (e.g., for example, for instance, such as, illustrat*,
          example, one-/few-shot, WRONG, RIGHT);
        * measurement history (an ISO date, an ``n=`` count).
      The declarations live in ``PROMPTS`` below, one set per prompt, so widening what a
      prompt may quote is a reviewed edit to this file, never a silent one.
(iii) Coverage. Every LLM call construct under ``src/`` (``get_llm(``, ``HumanMessage(``,
      ``SystemMessage(``, ``ChatPromptTemplate.from_messages(``, ``ChatOpenAI(``,
      ``OpenAI(``, ``.chat.completions.create(``) is counted per file with ``ast``, and the
      count must equal the one registered in ``CALL_SITES``. A new call in any file, or a
      new file, fails until its prompt is registered here. Every module- or class-level
      string constant named ``*PROMPT*`` / ``*INSTRUCTION*`` must also appear in some
      rendered prompt, so a template added beside an existing call site is caught too.

The lint below is a word list and a regex. That is deliberate and is not a pipeline rule:
it judges this repository's own prompt source, never protocol text, and it lives in
``tests/``.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "inventory" / "2026-10-12_prompt_examples.json"
SRC = ROOT / "src"

#: Every runtime value fed to a renderer contains this marker, so a quoted span that
#: carries it is data, not prompt text.
STUB = "STUBDATA"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class _Recorder:
    """Stands in for the chat model: records each rendered message list, answers ``reply``."""

    def __init__(self, reply: str = "{}") -> None:
        self.calls: list[str] = []
        self.reply = reply

    def _record(self, prompt_input: Any, **_kwargs: Any) -> AIMessage:
        to_messages = getattr(prompt_input, "to_messages", None)
        messages = to_messages() if to_messages else prompt_input
        self.calls.append("\n\n".join(str(m.content) for m in messages))
        return AIMessage(content=self.reply)

    def runnable(self) -> RunnableLambda:
        return RunnableLambda(self._record)

    def factory(self, *_args: Any, **_kwargs: Any) -> RunnableLambda:
        return self.runnable()


def _joined(calls: list[str]) -> str:
    assert calls, "the renderer never reached the LLM -- the call path changed under this test"
    return "\n\n=====\n\n".join(calls)


def _render_agent1_parse() -> str:
    from src.agents.agent1 import parser as parser_mod

    recorder = _Recorder()
    with patch.object(parser_mod, "get_llm", recorder.factory):
        decomposer = parser_mod.LogicDecomposer(model_name="stub-model")
        try:
            decomposer.parse(f"{STUB} clinical question")
        except Exception:
            pass  # the stub answer is not a valid IR; only the rendered prompt matters
    return _joined(recorder.calls)


def _render_agent1_parse_nct() -> str:
    """parser.py builds this with ``NCT_DECOMPOSITION_PROMPT.format(...)`` and sends
    ``NCT_SYSTEM_PROMPT`` verbatim; replicated here because ``parse_nct`` also fetches,
    enriches and writes the IR cache, none of which a lint should do."""
    from src.agents.agent1 import prompts
    from src.agents.agent1.parser import LogicDecomposer

    criteria = LogicDecomposer._format_criteria([f"{STUB} criterion one", f"{STUB} criterion two"])
    user = prompts.NCT_DECOMPOSITION_PROMPT.format(
        title=STUB, conditions=STUB, interventions=STUB, outcomes=STUB,
        inclusion=criteria, exclusion=criteria,
    )
    return prompts.NCT_SYSTEM_PROMPT + "\n\n=====\n\n" + user


def _render_agent1_threshold_review() -> str:
    from src.agents.agent1 import parser as parser_mod

    recorder = _Recorder(reply='{"misses": []}')
    ir = SimpleNamespace(target=SimpleNamespace(inclusion_rules=[], exclusion_rules=[]))
    with patch.object(parser_mod, "get_llm", recorder.factory):
        decomposer = parser_mod.LogicDecomposer.__new__(parser_mod.LogicDecomposer)
        decomposer.model_name = "stub-model"
        decomposer._llm_review_value_constraints(STUB, [f"{STUB} line"], [], ir)
    return _joined(recorder.calls)


def _render_agent1_threshold_match() -> str:
    from src.agents.agent1 import prompts

    return prompts.THRESHOLD_MATCH_PROMPT.format(
        original_text=f"{STUB} criterion",
        constraints_block=f"0: {STUB}",
        rules_block=f"0: {STUB}",
    )


def _render_agent1_extraction() -> str:
    """No caller in src/ (inventory §1); linted anyway because it is a prompt constant."""
    from src.agents.agent1 import prompts

    return prompts.EXTRACTION_PROMPT.format(text=STUB)


def _render_eligibility_segmentation() -> str:
    """Through ``segment_eligibility`` with the model replaced; the cache is off so
    nothing is written."""
    from src.agents.agent1 import segmentation

    recorder = _Recorder(reply='{"inclusion": null, "exclusion": null}')
    with patch.object(segmentation, "_build_llm", lambda _model: recorder.runnable()), \
            patch.dict(os.environ, {"ARTEMIS_SEGMENTATION_CACHE": "0"}):
        segmentation.segment_eligibility(f"{STUB} eligibility text", model="stub-model")
    return _joined(recorder.calls)


def _render_planner() -> str:
    from src.agents.planner import decomposer as decomposer_mod
    from src.models.ir import Criteria

    recorder = _Recorder(reply='{"decompose": false, "sub_criteria": []}')
    with patch.object(decomposer_mod, "get_llm", recorder.factory):
        planner = decomposer_mod.CriteriaPlanner(model_name="stub-model")
        planner._decompose_criterion(Criteria(
            name=STUB, domain="Condition", entity_text=STUB, source_text=STUB,
            logic_type="PRESENCE",
        ))
    return _joined(recorder.calls)


def _candidate(concept_id: int = 1) -> Any:
    from src.agents.agent2.retriever import CandidateConcept

    return CandidateConcept(
        concept_id=concept_id, concept_name=STUB, domain_id=STUB,
        vocabulary_id=STUB, concept_class_id=STUB, distance=0.0,
    )


def _render_reranker_single_select() -> str:
    from src.agents.agent2 import reranker as reranker_mod

    recorder = _Recorder()
    with patch.dict(os.environ, {"AGENT2_RERANKER_DOMAIN_AWARE": "true"}), \
            patch.object(reranker_mod, "get_llm", recorder.factory):
        reranker_mod.ConceptReranker().rerank(STUB, [_candidate()])
    return _joined(recorder.calls)


def _render_reranker_topn() -> str:
    from src.agents.agent2 import reranker as reranker_mod

    recorder = _Recorder(reply='{"selected_ids": []}')
    with patch.object(reranker_mod, "get_llm", recorder.factory):
        reranker_mod.ConceptReranker().rerank_topn(STUB, [_candidate()])
    return _joined(recorder.calls)


def _render_critic() -> str:
    from src.agents.agent2 import critic as critic_mod
    from src.agents.agent2.kg_expander import KGConcept

    recorder = _Recorder(reply='{"selected_concepts": [], "overall_reasoning": ""}')
    concept = KGConcept(concept_id=1, concept_name=STUB, domain_id=STUB, vocabulary_id=STUB,
                        relationship=STUB)
    env = {"AGENT2_CRITIC_SELF_REFLECT": "true", "AGENT2_CRITIC_MODEL_TIER": "follow"}
    with patch.dict(os.environ, env), patch.object(critic_mod, "get_llm", recorder.factory):
        critic_mod.ConceptCritic().evaluate(STUB, seed_concept_ids=[1], kg_concepts=[concept])
    return _joined(recorder.calls)


def _render_nlu_router() -> str:
    from src.agents.conceptset import nlu_router

    recorder = _Recorder(reply='{"include": [], "exclude": []}')
    with patch.object(nlu_router, "get_llm", recorder.factory):
        nlu_router.IntentSeparator().separate(STUB)
    return _joined(recorder.calls)


def _render_clinical_reranker() -> str:
    from src.agents.conceptset.clinical_reranker import ClinicalReranker
    from src.agents.conceptset.rag_search import ConceptCandidate
    from src.utils import llm as llm_mod

    recorder = _Recorder(reply='{"selected_id": null}')
    with patch.object(llm_mod, "get_llm", recorder.factory):
        reranker = ClinicalReranker(use_cross_encoder=False)
        candidates = [ConceptCandidate(concept_id=1, concept_name=STUB)]
        reranker._rerank_with_llm(STUB, candidates, top_k=1)
    return _joined(recorder.calls)


def _render_comparator_literature() -> str:
    from src.agents.comparator import recommender

    recorder = _Recorder(reply='{"candidates": []}')
    snapshot = {"documents": [{"pmid": STUB, "title": STUB, "finding": STUB}]}
    with patch.object(recommender, "_load_evidence_snapshot", lambda _key: snapshot), \
            patch.object(recommender, "_vllm_reachable", lambda *a, **k: True), \
            patch.object(recommender, "_get_llm", recorder.runnable):
        recommender.recommend_from_literature(STUB, STUB, STUB, STUB, trial_name=STUB, save=False)
    return _joined(recorder.calls)


def _render_tte_analysis_finalizer() -> str:
    from src.services import tte_service

    recorder = _Recorder()
    with patch.object(tte_service, "get_llm", recorder.factory):
        tte_service.TTEService._finalize_analysis_strategy_candidates(
            SimpleNamespace(), diagnosis_title=STUB, diagnosis_summary=STUB, diagnosis_facts=[STUB],
            warnings=[STUB], candidates=[], selected_method=STUB, recommendation_stage="final",
            requested_ps_method=None,
        )
    return _joined(recorder.calls)


def _render_tte_report_narrative() -> str:
    """Rendered twice so both sides of every data-dependent branch reach the lint."""
    from src.services import tte_service

    recorder = _Recorder(reply="<p></p>")
    common = dict(
        title=STUB, description=STUB, treatment_name=STUB,
        comparator_name=STUB, outcome_name=STUB, analysis_method=STUB, n_treatment=10,
        n_comparator=10, hr=1.0, ci_lower=0.5, ci_upper=2.0, p_value=0.5, treatment_events=1,
        comparator_events=1, matched_pairs=None, treatment_strategy=STUB,
        comparator_strategy=STUB, time_zero_def=STUB, comparison_mode=STUB, washout_days="1",
        grace_days="1", n_covariates=1,
    )
    sparse = dict(nct_id=STUB, brief_title=STUB, followup_days="30", source_key="Unknown",
                  trial_metadata={"officialTitle": STUB, "eligibilityCriteria": STUB},
                  total_events=2, max_smd_after=0.5, imbalanced_covariates=[STUB])
    ample = dict(nct_id="", brief_title="", followup_days="900", source_key=STUB, trial_metadata={},
                 total_events=200, max_smd_after=0.05, imbalanced_covariates=[])
    middle = dict(nct_id="", brief_title="", followup_days="900", source_key=STUB,
                  trial_metadata={},
                  total_events=15, max_smd_after=0.2, imbalanced_covariates=[STUB])
    with patch.object(tte_service, "get_llm", recorder.factory):
        for variant in (sparse, ample, middle):
            tte_service.TTEService._generate_report_narrative(
                SimpleNamespace(), **common, **variant,
            )
    return _joined(recorder.calls)


def _render_dedup_judge() -> str:
    from src.agents.agent1 import criteria_dedup_judge

    return criteria_dedup_judge._render_prompt(f"{STUB} candidate", [f"{STUB} one", f"{STUB} two"])


def _render_criterion_annotation() -> str:
    """Through ``annotate_eligibility`` with the model replaced, over a group label (so the
    members block is rendered) and its member; the cache is off so nothing is written."""
    from src.services import criterion_annotation

    recorder = _Recorder(reply='{"record_requirement": "required", "conditional_span": null, '
                               '"excepted_entities": [], "base_span": null}')
    common = {"domain": "Drug", "protocolLine": f"{STUB} line", "logicType": "PRESENCE",
              "window": {"start": -56, "end": 0}, "valueConstraint": None, "groupId": "g"}
    rows = [
        {"id": 1, "description": STUB, "sourceText": STUB, "isGroupLabel": True, **common},
        {"id": 2, "description": f"{STUB} member", "sourceText": STUB, "isGroupLabel": False,
         **common},
    ]
    with patch.object(criterion_annotation, "_build_llm", lambda _model: recorder.runnable()), \
            patch.dict(os.environ, {"ARTEMIS_ANNOTATION_CACHE": "0"}):
        criterion_annotation.annotate_eligibility(
            {"inclusionCriteria": rows, "exclusionCriteria": []}, model="stub-model",
        )
    return _joined(recorder.calls)


# ---------------------------------------------------------------------------
# Declarations: what each prompt may quote
# ---------------------------------------------------------------------------

#: Domain and enum values of the Agent 1 IR, shared by every Agent 1 prompt.
_IR_ENUMS = frozenset({
    "Condition", "Drug", "Measurement", "Procedure", "Observation", "Demographics", "Device",
    "PRESENCE", "ABSENCE", "ANY", "ALL", "First", "x ULN", "x LLN",
    "gt", "gte", "lt", "lte", "eq",
})
#: Agent 1 IR field names (also the JSON keys of its output schema).
_IR_FIELDS = frozenset({
    "target", "comparator", "outcome", "primary_criteria", "inclusion_rules", "exclusion_rules",
    "name", "domain", "entity_text", "source_text", "logic_type", "window", "start", "end",
    "value_constraint", "op", "value", "unit_text", "group_type", "sub_criteria", "conditional",
    "limit", "time_at_risk", "[value_constraint]",
})
#: OMOP CDM / CIRCE names a prompt may cite as the destination of a field.
_OMOP_NAMES = frozenset({
    "measurement.value_as_number", "observation.value_as_number", "drug_exposure",
    "condition_occurrence", "procedure_occurrence", "observation", "measurement", "person",
    "year_of_birth", "value_as_number", "unit_concept_id",
})


@dataclass(frozen=True)
class PromptSpec:
    """One prompt that reaches an LLM, how to render it, and what it may quote.

    ``tokens``: schema tokens a quoted span may hold -- field names, enum values, JSON
    keys, OMOP names, required output phrases. ``placeholders``: description strings a
    JSON value may hold in place of ``<...>``. ``declared_blocks``: exact substrings
    removed before the JSON check because they are a value table the prompt states as
    its decision (the per-domain default windows), rendered from their one source.
    """

    render: Callable[[], str]
    tokens: frozenset[str] = frozenset()
    placeholders: frozenset[str] = frozenset()
    declared_blocks: Callable[[], tuple[str, ...]] = field(default=lambda: ())


def _default_window_blocks() -> tuple[str, ...]:
    """The domain-default window table these prompts state, from its one home."""
    from src.utils.circe_lint import render_default_window_prompt_line

    return (
        render_default_window_prompt_line(
            [["Condition"], ["Drug"], ["Measurement"], ["Procedure"]]
        ),
        render_default_window_prompt_line([["Condition", "Procedure"], ["Drug"], ["Measurement"]]),
    )


PROMPTS: dict[str, PromptSpec] = {
    "agent1.parse": PromptSpec(
        _render_agent1_parse, tokens=_IR_ENUMS | _IR_FIELDS | _OMOP_NAMES,
        declared_blocks=_default_window_blocks,
    ),
    "agent1.parse_nct": PromptSpec(
        _render_agent1_parse_nct,
        # The annotation line parser.py attaches to a criterion (value_constraint.py).
        tokens=_IR_ENUMS | _IR_FIELDS | _OMOP_NAMES | frozenset({"[value_constraint] {...}"}),
        declared_blocks=_default_window_blocks,
    ),
    "agent1.threshold_review": PromptSpec(
        _render_agent1_threshold_review,
        tokens=frozenset({"misses", "criterion_line", "criterion_text", "reason", "x ULN", "x LLN",
                          "value_constraint", "source_text", "name"}),
    ),
    "agent1.threshold_match": PromptSpec(
        _render_agent1_threshold_match,
        tokens=frozenset({"mapping", "rule_index", "constraint_index"}),
    ),
    "agent1.extraction_unused": PromptSpec(
        _render_agent1_extraction, tokens=frozenset({"term", "domain", "context", "temporal"}),
    ),
    "agent1.eligibility_segmentation": PromptSpec(
        _render_eligibility_segmentation,
        tokens=frozenset({"inclusion", "exclusion", "start", "end", "items", "interruptions"}),
    ),
    "planner": PromptSpec(
        _render_planner,
        tokens=_IR_ENUMS | frozenset({
            "decompose", "reasoning", "sub_criteria", "name", "entity_text", "domain",
            "source_span", "value_constraint_text", "group_type", "logic_type", "null",
            "true", "false",
        }),
    ),
    "agent2.reranker_single_select": PromptSpec(
        _render_reranker_single_select,
        tokens=frozenset({"selected_concept_id", "reasoning"}),
    ),
    "agent2.reranker_topn": PromptSpec(
        _render_reranker_topn, tokens=frozenset({"query_has_match", "selected_ids"}),
    ),
    "agent2.critic": PromptSpec(
        _render_critic,
        tokens=frozenset({
            # Values of the candidate rows' Relationship column (kg_expander output).
            "sibling", "ancestor", "seed",
            # CriticSelection field names and their enum values.
            "selected_concepts", "overall_reasoning", "concept_id", "relevant", "reasoning",
            "confidence", "potential_issue", "assessment", "recommended_action",
            "abbreviation_confusion", "domain_mismatch", "too_specific", "vocab_mismatch", "none",
            "correct", "partially_supported", "contradicted", "keep", "drop", "rerank",
        }),
    ),
    "conceptset.nlu_router": PromptSpec(
        _render_nlu_router,
        tokens=frozenset({"include", "exclude", "fallback_to", "fallback_reason", "Agent1"}),
    ),
    "conceptset.clinical_reranker": PromptSpec(
        _render_clinical_reranker, tokens=frozenset({"selected_id", "confidence"}),
    ),
    "comparator.literature": PromptSpec(
        _render_comparator_literature,
        tokens=frozenset({"candidates", "drug_class", "ingredients", "verdict", "same_setting",
                          "rationale", "neutral", "beneficial", "harmful"}),
    ),
    "tte.analysis_finalizer": PromptSpec(_render_tte_analysis_finalizer),
    "tte.report_narrative": PromptSpec(
        _render_tte_report_narrative,
        tokens=frozenset({
            # Data values the prompt branches on.
            "Unknown", "IPTW (PSM fallback)", "placebo", "caution-box",
            # Output phrases the report is required to state verbatim.
            "insufficient events for reliable estimation",
            "weighting FAILED to achieve adequate balance",
            "This emulation differs materially from the original trial in [X, Y, Z]",
            "Original trial information not available.",
            "Propensity score weighting did NOT achieve adequate covariate balance. "
            "The reported effect estimate is highly vulnerable to residual confounding.",
        }),
    ),
    "agent1.dedup_judge": PromptSpec(
        _render_dedup_judge,
        tokens=frozenset({"restatement", "conjunction_of_alternatives", "negation_of_alternative",
                          "distinct", "verdict", "matched_alternatives", "reason"}),
        placeholders=frozenset({"one short sentence"}),
    ),
    "criterion_annotation": PromptSpec(
        _render_criterion_annotation,
        tokens=frozenset({
            "record_requirement", "conditional_span", "excepted_entities", "base_span", "text",
            "span", "required", "forbidden", "conditional",
            # RFC-016 step 4: route (the OMOP route concepts RxNorm dose forms carry,
            # `route_subtraction.AdministrationRoute`), specimen and no_entity, with their values.
            "route", "route_span", "any", "oral", "injectable", "topical", "transdermal",
            "respiratory_tract", "nasal", "ophthalmic", "otic", "rectal", "vaginal", "buccal",
            "sublingual", "implant",
            "specimen", "specimen_span", "blood", "urine", "other",
            "no_entity", "no_entity_span", "none", "refers_elsewhere", "investigator_judgement",
        }),
    ),
}


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------

_EXAMPLE_MARKERS = (
    re.compile(r"\be\.\s?g\b", re.IGNORECASE),
    re.compile(r"\bfor (?:example|instance)\b", re.IGNORECASE),
    re.compile(r"\bsuch as\b", re.IGNORECASE),
    re.compile(r"\billustrat\w*", re.IGNORECASE),
    re.compile(r"\b(?:counter)?examples?\b", re.IGNORECASE),
    re.compile(r"\b(?:one|few|zero)-shot\b", re.IGNORECASE),
    re.compile(r"\bWRONG\b"),
    re.compile(r"\bRIGHT\b"),
)
_HISTORY_MARKERS = (
    re.compile(r"\b20\d\d-\d\d-\d\d\b"),
    re.compile(r"\bn\s?=\s?\d"),
)
_PLACEHOLDER = re.compile(r"^<[^<>]+>$")
_NUMBER = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class Finding:
    kind: str
    text: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.text!r}"


_JSON_LITERALS = frozenset({"true", "false", "null"})


def _allowed_scalar(content: str, allowed: frozenset[str]) -> bool:
    content = content.strip()
    if content in ("", "...", "…") or STUB in content or _PLACEHOLDER.match(content):
        return True
    if content in allowed:
        return True
    pair = re.fullmatch(r"([\w.\[\]]+)\s*[:=]\s*(.+)", content)
    if pair:  # `group_type: "ANY"` -- a field set to a value, both of which must be declared
        key, value = pair.group(1), pair.group(2).strip().strip("\"'")
        return key in allowed and (value in _JSON_LITERALS or _allowed_scalar(value, allowed))
    members = [m.strip() for m in re.split(r"\s*\|\s*", content)]
    return len(members) > 1 and all(m in allowed or _PLACEHOLDER.match(m) for m in members)


def _quoted_spans(text: str) -> Iterator[str]:
    for line in text.replace("```", "").splitlines():
        quotes = [i for i, ch in enumerate(line) if ch == '"']
        for start, end in zip(quotes[0::2], quotes[1::2]):
            yield line[start + 1:end]
        yield from re.findall(r"“([^”]*)”", line)
        yield from re.findall(r"(?<![\w’])‘([^’]+)’(?!\w)", line)
        yield from re.findall(r"(?<![\w'])'([^'\n]+?)'(?![\w])", line)
        yield from (span.strip("\"'") for span in re.findall(r"`([^`]+)`", line))


class _BlockParser:
    """Tolerant reader for ``{key: value}`` blocks in prose: keys may be bare, values may be
    ``<placeholders>``. Yields ``(key_or_None, raw_scalar)`` for every leaf it reads."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.keys: list[str] = []
        self.leaves: list[tuple[str | None, str]] = []

    def _ws(self) -> None:
        while self.i < len(self.text) and self.text[self.i].isspace():
            self.i += 1

    def _string(self) -> str:
        end = self.text.index('"', self.i + 1)
        raw = self.text[self.i:end + 1]
        self.i = end + 1
        return raw

    def _scalar(self) -> str:
        if self.text[self.i] == '"':
            return self._string()
        if self.text[self.i] == "<":
            end = self.text.index(">", self.i)
            raw = self.text[self.i:end + 1]
            self.i = end + 1
            return raw
        start = self.i
        while self.i < len(self.text) and self.text[self.i] not in ",]}\n":
            self.i += 1
        return self.text[start:self.i].strip()

    def value(self, key: str | None) -> None:
        self._ws()
        ch = self.text[self.i]
        if ch == "{":
            self.object()
        elif ch == "[":
            self.i += 1
            while True:
                self._ws()
                if self.text[self.i] == "]":
                    self.i += 1
                    return
                self.value(key)
                self._ws()
                if self.text[self.i] == ",":
                    self.i += 1
                elif self.text[self.i] == "]":
                    self.i += 1
                    return
                else:
                    before = self.i
                    self._scalar()  # trailing prose after an element; keep reading
                    if self.i == before:
                        raise ValueError("not an array")
        else:
            self.leaves.append((key, self._scalar()))

    def object(self) -> None:
        assert self.text[self.i] == "{"
        self.i += 1
        while True:
            self._ws()
            if self.text[self.i] == "}":
                self.i += 1
                return
            if self.text[self.i] == '"':
                key = self._string()[1:-1]
            else:
                match = re.match(r"[A-Za-z_][\w.]*", self.text[self.i:])
                if not match:
                    raise ValueError("not a key")
                key = match.group(0)
                self.i += len(key)
            self._ws()
            if self.text[self.i] != ":":
                raise ValueError("not a key: value pair")
            self.i += 1
            self.keys.append(key)
            self.value(key)
            self._ws()
            if self.text[self.i] == ",":
                self.i += 1
            elif self.text[self.i] == "}":
                self.i += 1
                return
            else:
                self._scalar()  # trailing prose after a value ("... or null"); keep reading
                self._ws()
                if self.i < len(self.text) and self.text[self.i] == ",":
                    self.i += 1


def _json_blocks(text: str) -> Iterator[_BlockParser]:
    i = 0
    while True:
        start = text.find("{", i)
        if start < 0:
            return
        parser = _BlockParser(text)
        parser.i = start
        try:
            parser.object()
        except (ValueError, IndexError, AssertionError):
            i = start + 1
            continue
        if parser.keys:
            yield parser
            i = parser.i
        else:
            i = start + 1


def lint(text: str, spec: PromptSpec) -> list[Finding]:
    findings: list[Finding] = []
    json_text = text
    for block in spec.declared_blocks():
        json_text = json_text.replace(block, "")
    blocks = list(_json_blocks(json_text))
    json_keys = frozenset(k for b in blocks for k in b.keys)
    allowed = spec.tokens | spec.placeholders | json_keys

    for block in blocks:
        for key, raw in block.leaves:
            if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
                content = raw[1:-1]
                if not (_allowed_scalar(content, spec.tokens | spec.placeholders)):
                    findings.append(Finding("json-filled-string", f"{key}: {raw}"))
            elif _NUMBER.match(raw) or raw in ("true", "false"):
                findings.append(Finding("json-filled-literal", f"{key}: {raw}"))

    for span in _quoted_spans(text):
        if not _allowed_scalar(span, allowed):
            findings.append(Finding("quoted", span))

    for kind, patterns in (("example-marker", _EXAMPLE_MARKERS), ("history", _HISTORY_MARKERS)):
        for pattern in patterns:
            for match in pattern.finditer(text):
                context = text[max(0, match.start() - 40):match.end() + 40]
                findings.append(Finding(kind, context))
    return findings


_RENDERED: dict[str, str] = {}


def rendered(prompt_id: str) -> str:
    if prompt_id not in _RENDERED:
        _RENDERED[prompt_id] = PROMPTS[prompt_id].render()
    return _RENDERED[prompt_id]


# ---------------------------------------------------------------------------
# (i) The inventoried examples are gone
# ---------------------------------------------------------------------------

_INVENTORY: list[dict[str, Any]] = json.loads(INVENTORY_PATH.read_text())

#: Where a ``rendered_only`` row's text arrives: the call site's prompt.
_RENDERED_ONLY_PROMPT = {
    "src/agents/agent2/critic.py": "agent2.critic",
    "src/agents/conceptset/nlu_router.py": "conceptset.nlu_router",
    "src/agents/agent2/reranker.py": "agent2.reranker_single_select",
}


def test_should_read_all_205_inventory_rows() -> None:
    assert len(_INVENTORY) == 205
    assert len({row["id"] for row in _INVENTORY}) == 205


@pytest.mark.parametrize("row", _INVENTORY, ids=[row["id"] for row in _INVENTORY])
def test_should_leave_no_inventoried_example_in_its_prompt(row: dict[str, Any]) -> None:
    if row.get("rendered_only"):
        haystack = rendered(_RENDERED_ONLY_PROMPT[row["file"]])
        where = f"the rendered {_RENDERED_ONLY_PROMPT[row['file']]} prompt"
    else:
        source = ROOT / row["file"]
        # A source file deleted outright sends none of its text to a model; the other
        # two checks still cover any prompt that moved elsewhere.
        haystack = source.read_text(encoding="utf-8") if source.exists() else ""
        where = row["file"]
    for needle_key in ("needle", "core_needle"):
        needle = row.get(needle_key)
        if needle:
            count = haystack.count(needle)
            assert count == 0, (
                f"{row['id']} ({row['class']}, {row['prompt']}) still occurs {count}x in {where}: "
                f"{row['display']!r}"
            )


# ---------------------------------------------------------------------------
# (ii) No prompt carries an example shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt_id", sorted(PROMPTS))
def test_should_render_no_example_shape(prompt_id: str) -> None:
    findings = lint(rendered(prompt_id), PROMPTS[prompt_id])
    counts = Counter(f.kind for f in findings)
    assert not findings, (
        f"{prompt_id}: {len(findings)} finding(s) {dict(counts)}\n"
        + "\n".join(f"  - {f}" for f in findings[:60])
    )


def test_should_flag_each_shape_the_lint_exists_for() -> None:
    """A lint that only ever passes is indistinguishable from one that checks nothing.
    Each shape below is one the 2026-10-12 inventory found in a real prompt."""
    spec = PromptSpec(lambda: "", tokens=frozenset({"op", "value", "unit_text", "gt"}))
    shapes = {
        "json-filled-literal": '{"op": "gt", "value": 4.0, "unit_text": "<unit>"}',
        "json-filled-string": '{"op": "gt", "value": <number>, "unit_text": "ng/mL"}',
        "quoted": 'Emit "Hypersensitivity to bupivacaine" as the entity.',
        "example-marker": "Lab tests (e.g., creatinine) are measurements.",
        "history": "Measured on the 2026-09-10 store.",
    }
    for kind, text in shapes.items():
        assert kind in {f.kind for f in lint(text, spec)}, kind
    assert lint('{"op": "<gt|gte>", "value": <number>, "unit_text": "<unit>"}', spec) == []


def test_should_describe_every_output_field_where_the_library_schema_was_dropped() -> None:
    """Replacing LangChain's format instructions must not drop a field the parser reads."""
    from src.agents.agent2.critic import CriticResult, CriticSelection
    from src.agents.agent2.reranker import RerankResult
    from src.agents.conceptset.nlu_router import IntentResult

    for prompt_id, models in (
        ("agent2.critic", (CriticResult, CriticSelection)),
        ("agent2.reranker_single_select", (RerankResult,)),
        ("conceptset.nlu_router", (IntentResult,)),
    ):
        text = rendered(prompt_id)
        for model in models:
            for name in model.model_fields:
                assert name in text, f"{prompt_id} no longer names output field {name!r}"


# ---------------------------------------------------------------------------
# (iii) Every LLM call in src/ is covered
# ---------------------------------------------------------------------------

#: file -> (number of LLM call constructs in it, the PROMPTS ids that render them).
#: A file whose calls carry no prompt of their own says why instead.
CALL_SITES: dict[str, tuple[int, tuple[str, ...] | str]] = {
    "src/agents/agent1/parser.py": (
        9, ("agent1.parse", "agent1.parse_nct", "agent1.threshold_review",
            "agent1.threshold_match"),
    ),
    "src/agents/agent1/segmentation.py": (3, ("agent1.eligibility_segmentation",)),
    "src/agents/agent1/criteria_dedup_judge.py": (2, ("agent1.dedup_judge",)),
    "src/agents/planner/decomposer.py": (3, ("planner",)),
    "src/agents/agent2/reranker.py": (3, ("agent2.reranker_single_select", "agent2.reranker_topn")),
    "src/agents/agent2/critic.py": (3, ("agent2.critic",)),
    "src/agents/conceptset/nlu_router.py": (2, ("conceptset.nlu_router",)),
    "src/agents/conceptset/clinical_reranker.py": (2, ("conceptset.clinical_reranker",)),
    "src/agents/comparator/recommender.py": (2, ("comparator.literature",)),
    "src/services/tte_service.py": (6, ("tte.analysis_finalizer", "tte.report_narrative")),
    "src/services/criterion_annotation.py": (3, ("criterion_annotation",)),
    "src/utils/llm.py": (6, "transport: builds the chat client get_llm returns and appends "
                            "/no_think to the caller's last message; carries no prompt of its own"),
}

_CALL_NAMES = frozenset({"get_llm", "HumanMessage", "SystemMessage", "ChatOpenAI", "OpenAI"})


def _is_llm_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _CALL_NAMES
    if isinstance(func, ast.Attribute):
        if func.attr in _CALL_NAMES:
            return True
        if func.attr == "from_messages" and isinstance(func.value, ast.Name):
            return func.value.id == "ChatPromptTemplate"
        if func.attr == "create" and isinstance(func.value, ast.Attribute):
            return func.value.attr == "completions"
    return False


def _llm_call_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        n = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Call) and _is_llm_call(node))
        if n:
            counts[str(path.relative_to(ROOT))] = n
    return counts


def test_should_register_every_llm_call_site_in_src() -> None:
    counts = _llm_call_counts()
    unregistered = {f: n for f, n in counts.items() if f not in CALL_SITES}
    assert not unregistered, (
        f"LLM call sites with no renderer in this test: {unregistered}. Add a renderer to "
        "PROMPTS and the file to CALL_SITES."
    )
    changed = {f: (n, CALL_SITES[f][0]) for f, n in counts.items() if CALL_SITES[f][0] != n}
    assert not changed, (
        f"LLM call count changed (found, registered): {changed}. A new call is a new prompt: "
        "render it in PROMPTS, then update the count."
    )
    gone = sorted(set(CALL_SITES) - set(counts))
    assert not gone, f"registered call sites no longer present: {gone}"
    for entry, (_, covered) in CALL_SITES.items():
        if isinstance(covered, tuple):
            assert covered and all(p in PROMPTS for p in covered), entry


def _prompt_constants() -> Iterator[tuple[str, str, str]]:
    """(module, name, value) for every str constant named like a prompt under src/."""
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scopes: list[tuple[str | None, list[ast.stmt]]] = [(None, tree.body)]
        scopes += [(n.name, n.body) for n in tree.body if isinstance(n, ast.ClassDef)]
        for owner, body in scopes:
            for node in body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if (isinstance(target, ast.Name) and re.search(r"PROMPT|INSTRUCTION", target.id)
                            and not re.search(r"VERSION|PATH", target.id)):  # cache keys, files
                        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
                        holder = importlib.import_module(module)
                        if owner:
                            holder = getattr(holder, owner)
                        value = getattr(holder, target.id)
                        if isinstance(value, str) and len(value) > 40:
                            yield module, (f"{owner}." if owner else "") + target.id, value


def test_should_render_every_prompt_constant_somewhere() -> None:
    corpus = "\n".join(rendered(p) for p in PROMPTS)
    missing = []
    for module, name, value in _prompt_constants():
        # The longest brace-free run reads the same whether the constant is sent verbatim
        # or through str.format, which only rewrites what sits between braces.
        probe = max(re.split(r"[{}]", value), key=len).strip()[:80]
        if probe not in corpus:
            missing.append(f"{module}.{name}")
    assert not missing, f"prompt constants no renderer reaches: {missing}"


def test_should_leave_no_stray_triple_quote_in_any_rendered_prompt() -> None:
    """NCT_DECOMPOSITION_PROMPT ended in a literal triple quote that reached the model."""
    stray = [p for p in PROMPTS if '"""' in rendered(p)]
    assert not stray, stray
