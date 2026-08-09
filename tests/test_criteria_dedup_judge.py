"""The LLM arm must be an ARM, not a second copy of the baseline.

Every test here runs against a stubbed chat model -- no network, no bill. What
they pin is the arm's contract rather than its medical judgement, because the
medical judgement is what the labelled gold table measures and a unit test that
asserted it would just be the same hand-tuning this arm exists to remove:

* the four model verdicts map to the right boolean, and only "restatement" drops
  a criterion;
* an unreachable or unparseable model produces an ERROR verdict, never
  False-by-fallback and never a quiet hand-off to the lexical rule;
* the arm selector honours all three arms and refuses a typo;
* the two structural early returns fire before the model is ever consulted;
* every row carries the model that resolve_model() named at call time.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.agents.agent1 import criteria_dedup, criteria_dedup_judge as judge

ARISTOTLE_GROUP = (
    "[OR-GROUP] One or more of the following risk factor(s) for stroke "
    "with any of: Age 75 years or older | Prior stroke, TIA or systemic embolus | "
    "Diabetes mellitus | Hypertension requiring pharmacological treatment"
)

PLAIN_ITEMS = ["Age >= 18 years", "Documented atrial fibrillation"]


class StubLLM:
    """Records every invocation and replays a scripted list of responses."""

    def __init__(self, responses: list[str] | None = None, raises: Exception | None = None):
        self.responses = list(responses or [])
        self.raises = raises
        self.calls: list[str] = []

    def invoke(self, messages):
        self.calls.append(messages[0].content)
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(content=self.responses.pop(0) if self.responses else "")


def _reply(verdict: str, matched: list[int] | None = None, reason: str = "because") -> str:
    return json.dumps({"verdict": verdict, "matched_alternatives": matched or [], "reason": reason})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Keep every test off the real verdict cache and off any real model."""
    monkeypatch.setenv("ARTEMIS_ORGROUP_JUDGE_CACHE_PATH", str(tmp_path / "verdicts.jsonl"))
    monkeypatch.delenv("ARTEMIS_ORGROUP_JUDGE", raising=False)
    monkeypatch.delenv("ARTEMIS_DISABLE_ORGROUP_DEDUP", raising=False)
    judge.reset_for_tests()
    yield
    judge.reset_for_tests()


@pytest.fixture
def stub(monkeypatch):
    """Install a stub chat model and hand the test its call log."""
    holder: dict[str, StubLLM] = {}

    def install(responses=None, raises=None) -> StubLLM:
        llm = StubLLM(responses, raises)
        holder["llm"] = llm
        monkeypatch.setattr(judge, "_build_llm", lambda model: llm)
        judge.reset_for_tests()
        return llm

    return install


@pytest.fixture
def llm_arm(monkeypatch):
    monkeypatch.setenv("ARTEMIS_ORGROUP_JUDGE", judge.ARM_LLM)


class TestVerdictMapping:
    """Only a restatement deletes a criterion; the other three keep it."""

    @pytest.mark.parametrize("verdict,expected", [
        (judge.RESTATEMENT, True),
        # Stricter than the group it echoes -- deleting it widens the cohort.
        (judge.CONJUNCTION_OF_ALTERNATIVES, False),
        # Opposite polarity; deleting an exclusion widens the cohort silently.
        (judge.NEGATION_OF_ALTERNATIVE, False),
        (judge.DISTINCT, False),
    ])
    def test_should_map_verdict_to_boolean_when_model_answers(self, verdict, expected, stub, llm_arm):
        stub([_reply(verdict, matched=[3])])
        result = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert result.verdict == verdict
        assert result.is_restatement is expected
        assert judge.restates_or_group_alternative("Diabetes mellitus", [ARISTOTLE_GROUP]) is expected

    def test_should_resolve_matched_alternatives_when_model_returns_indices(self, stub, llm_arm):
        stub([_reply(judge.RESTATEMENT, matched=[1, 3])])
        result = judge.judge_or_group_restatement("Age 75 or older with diabetes", [ARISTOTLE_GROUP])
        assert result.matched_alternatives == ("Age 75 years or older", "Diabetes mellitus")
        assert result.warnings == ()

    def test_should_warn_but_not_error_when_index_is_out_of_range(self, stub, llm_arm):
        stub([_reply(judge.RESTATEMENT, matched=[9])])
        result = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert result.verdict == judge.RESTATEMENT
        assert result.matched_alternatives == ()
        assert any("out of range" in w for w in result.warnings)


class TestNoSilentFallback:
    """An unanswered question must never read as "keep"."""

    @pytest.mark.parametrize("content", [
        "not json at all",
        '{"verdict": "maybe"}',          # outside the model's answer space
        '["restatement"]',               # right word, wrong shape
        "",
    ])
    def test_should_return_error_verdict_when_response_is_unusable(self, content, stub, llm_arm):
        stub([content])
        result = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert result.verdict == judge.ERROR
        # None, not False: False is a verdict the model never gave.
        assert result.is_restatement is None
        assert result.error

    def test_should_return_error_verdict_when_model_call_raises(self, stub, llm_arm):
        stub(raises=RuntimeError("connection refused"))
        result = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert result.verdict == judge.ERROR
        assert result.is_restatement is None
        assert "connection refused" in result.error

    def test_should_raise_at_boolean_boundary_rather_than_return_false(self, stub, llm_arm):
        stub(raises=RuntimeError("connection refused"))
        with pytest.raises(judge.JudgeError):
            judge.restates_or_group_alternative("Diabetes mellitus", [ARISTOTLE_GROUP])

    def test_should_not_consult_the_lexical_rule_when_the_model_fails(self, stub, llm_arm, monkeypatch):
        # "Diabetes mellitus" is a verbatim alternative, so the lexical arm says
        # True. If the LLM arm ever borrowed it, this test would go green on the
        # wrong answer -- so the baseline is booby-trapped instead.
        assert criteria_dedup.restates_or_group_alternative("Diabetes mellitus", [ARISTOTLE_GROUP]) is True
        monkeypatch.setattr(
            criteria_dedup, "restates_or_group_alternative",
            lambda *a, **k: pytest.fail("LLM arm fell back to the lexical baseline"),
        )
        stub(raises=RuntimeError("connection refused"))
        with pytest.raises(judge.JudgeError):
            judge.restates_or_group_alternative("Diabetes mellitus", [ARISTOTLE_GROUP])

    def test_should_not_cache_an_error(self, stub, llm_arm):
        llm = stub(raises=RuntimeError("connection refused"))
        judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert len(llm.calls) == 2


class TestArmSelector:
    """Three arms, an explicit default, and no quiet coercion of a typo."""

    def test_should_default_to_lexical_when_env_is_unset(self):
        assert judge.judge_arm() == judge.ARM_LEXICAL

    @pytest.mark.parametrize("arm", [judge.ARM_LEXICAL, judge.ARM_LLM, judge.ARM_OFF])
    def test_should_honour_every_known_arm(self, arm, monkeypatch):
        monkeypatch.setenv("ARTEMIS_ORGROUP_JUDGE", arm)
        assert judge.judge_arm() == arm

    def test_should_raise_when_arm_is_unknown(self, monkeypatch):
        monkeypatch.setenv("ARTEMIS_ORGROUP_JUDGE", "lexcial")
        with pytest.raises(judge.JudgeConfigurationError):
            judge.judge_arm()

    def test_should_answer_from_the_baseline_and_never_call_the_model_on_lexical(self, stub, monkeypatch):
        monkeypatch.setenv("ARTEMIS_ORGROUP_JUDGE", judge.ARM_LEXICAL)
        llm = stub([_reply(judge.DISTINCT)])
        result = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert result.source == judge.SOURCE_LEXICAL
        assert result.is_restatement is criteria_dedup.restates_or_group_alternative(
            "Diabetes mellitus", [ARISTOTLE_GROUP])
        assert llm.calls == []

    def test_should_keep_everything_and_never_call_the_model_on_off(self, stub, monkeypatch):
        monkeypatch.setenv("ARTEMIS_ORGROUP_JUDGE", judge.ARM_OFF)
        llm = stub([_reply(judge.RESTATEMENT)])
        result = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert result.is_restatement is False
        assert result.source == judge.SOURCE_OFF
        assert llm.calls == []


class TestStructuralEarlyReturns:
    """Contract, not judgement -- so the model is never asked and never billed."""

    def test_should_never_call_the_model_when_candidate_is_itself_an_or_group(self, stub, llm_arm):
        llm = stub([_reply(judge.RESTATEMENT)])
        result = judge.judge_or_group_restatement(ARISTOTLE_GROUP, [ARISTOTLE_GROUP])
        assert result.is_restatement is False
        assert result.source == judge.SOURCE_STRUCTURAL
        assert result.llm_called is False
        assert llm.calls == []

    def test_should_never_call_the_model_when_no_item_is_an_or_group(self, stub, llm_arm):
        llm = stub([_reply(judge.RESTATEMENT)])
        result = judge.judge_or_group_restatement("Diabetes mellitus", PLAIN_ITEMS)
        assert result.is_restatement is False
        assert result.source == judge.SOURCE_STRUCTURAL
        assert llm.calls == []

    def test_should_never_call_the_model_when_candidate_is_not_a_string(self, stub, llm_arm):
        llm = stub([_reply(judge.RESTATEMENT)])
        assert judge.judge_or_group_restatement(None, [ARISTOTLE_GROUP]).is_restatement is False
        assert llm.calls == []


class TestProvenance:
    """A row whose model string is a literal is a discarded row."""

    def test_should_record_the_model_resolve_model_names_at_call_time(self, stub, llm_arm, monkeypatch):
        from src.utils import llm as llm_module

        monkeypatch.setattr(llm_module.settings, "LLM_MODEL", "vllm/Qwen3-8B")
        stub([_reply(judge.RESTATEMENT)])
        result = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert result.model == llm_module.resolve_model() == "vllm/Qwen3-8B"
        assert result.llm_called is True

    def test_should_record_the_model_on_every_arm(self, stub, monkeypatch):
        from src.utils import llm as llm_module

        monkeypatch.setattr(llm_module.settings, "LLM_MODEL", "vllm/Qwen3-8B")
        stub([_reply(judge.DISTINCT)])
        for arm in (judge.ARM_LEXICAL, judge.ARM_OFF):
            monkeypatch.setenv("ARTEMIS_ORGROUP_JUDGE", arm)
            result = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
            assert result.model == "vllm/Qwen3-8B"
            assert result.llm_called is False


class TestCache:
    """Reproducible rows, and a re-run that does not re-bill."""

    def test_should_not_call_the_model_twice_for_the_same_question(self, stub, llm_arm):
        llm = stub([_reply(judge.RESTATEMENT, matched=[3], reason="same requirement")])
        first = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        second = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert len(llm.calls) == 1
        assert second.source == judge.SOURCE_CACHE
        assert (second.verdict, second.is_restatement, second.matched_alternatives, second.reason) == (
            first.verdict, first.is_restatement, first.matched_alternatives, first.reason)

    def test_should_survive_a_process_restart(self, stub, llm_arm):
        llm = stub([_reply(judge.RESTATEMENT)])
        judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        judge.reset_for_tests()          # stands in for a fresh process
        reloaded = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert reloaded.source == judge.SOURCE_CACHE
        assert len(llm.calls) == 1

    def test_should_not_reuse_a_verdict_across_models(self, stub, llm_arm, monkeypatch):
        from src.utils import llm as llm_module

        llm = stub([_reply(judge.RESTATEMENT), _reply(judge.DISTINCT)])
        monkeypatch.setattr(llm_module.settings, "LLM_MODEL", "vllm/Qwen3-8B")
        assert judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP]).is_restatement is True
        monkeypatch.setattr(llm_module.settings, "LLM_MODEL", "gpt-4o")
        second = judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        assert second.source == judge.SOURCE_LLM
        assert second.model == "gpt-4o"
        assert len(llm.calls) == 2

    def test_should_not_reuse_a_verdict_across_different_alternatives(self, stub, llm_arm):
        llm = stub([_reply(judge.RESTATEMENT), _reply(judge.DISTINCT)])
        other_group = "[OR-GROUP] header with any of: Prior myocardial infarction | Prior stroke"
        judge.judge_or_group_restatement("Diabetes mellitus", [ARISTOTLE_GROUP])
        judge.judge_or_group_restatement("Diabetes mellitus", [other_group])
        assert len(llm.calls) == 2


class TestNoGoldDependency:
    """The judge must be movable to hospital data, where no gold exists.

    Prose about gold is fine and the module has some; a gold *path* in executable
    code is not. So the gate reads string literals with the docstrings removed,
    which is the difference between explaining the boundary and crossing it.
    """

    @staticmethod
    def _code_string_literals(source: str) -> list[str]:
        import ast

        tree = ast.parse(source)
        docstring_ids = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                        and isinstance(first.value.value, str):
                    docstring_ids.add(id(first.value))
        return [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ]

    def test_should_not_reference_the_gold_corpus_in_code(self):
        from pathlib import Path

        literals = self._code_string_literals(Path(judge.__file__).read_text(encoding="utf-8"))
        assert [s for s in literals if "gold" in s.lower()] == []

    def test_should_not_import_anything_that_reads_gold(self):
        import ast
        from pathlib import Path

        tree = ast.parse(Path(judge.__file__).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert [name for name in imported if "gold" in name.lower()] == []
