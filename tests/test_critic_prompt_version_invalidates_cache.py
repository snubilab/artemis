"""A prompt edit must invalidate both mapping caches.

Neither cache hashes the prompt — `critic_signature()` says so, and while the prompt
was frozen that was a defensible cost tradeoff. It stops being one the moment anyone
edits the prompt or the output schema, because entries computed under the old prompt
then replay under the new one and quietly corrupt the exact before/after the cache
exists to make cheap.

That is not hypothetical. On 2026-08-11 a grouped output schema was trialled against
this critic; the A/B only meant anything because the version string below forced both
caches cold. The schema itself was measured on ARISTOTLE (per-criterion recall
0.636 -> 0.602, precision 0.356 -> 0.348, zero-overlap pairs 2 -> 4) and reverted.
The guard it exposed did not go with it.
"""
from __future__ import annotations

from unittest.mock import patch

from src.agents.agent2 import critic as critic_mod
from src.agents.agent2.critic import _CRITIC_PROMPT_VERSION, critic_signature
from src.agents.agent2.critic_cache import CriticCache
from src.agents.agent2.criterion_cache import CriterionResultCache


class TestPromptVersionReachesTheCacheKeys:
    def test_should_carry_the_prompt_version_in_the_critic_signature(self):
        assert _CRITIC_PROMPT_VERSION in critic_signature()

    def test_should_change_the_critic_cache_key_when_the_prompt_version_changes(self):
        before = CriticCache.make_key("atrial fibrillation", "Condition")
        with patch.object(critic_mod, "_CRITIC_PROMPT_VERSION", "some-other-prompt"):
            after = CriticCache.make_key("atrial fibrillation", "Condition")
        assert before != after

    def test_should_change_the_criterion_cache_key_when_the_prompt_version_changes(self):
        """The on-disk cache — the one that survives a restart and replays a whole run."""
        before = CriterionResultCache._make_key("atrial fibrillation", "Condition", "minilm", "m")
        with patch.object(critic_mod, "_CRITIC_PROMPT_VERSION", "some-other-prompt"):
            after = CriterionResultCache._make_key("atrial fibrillation", "Condition", "minilm", "m")
        assert before != after

    def test_should_still_separate_keys_by_model_and_reflection(self):
        """The version must be additive — it must not swallow the pre-existing parts."""
        signature = critic_signature()
        assert "tier=" in signature and "reflect=" in signature
