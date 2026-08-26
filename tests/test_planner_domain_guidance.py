"""SPEC-INFRA-007 item 1: Planner domain guidance parity.

AC-001 requires the SAME test to transition RED (pre-fix) -> GREEN (post-fix)
purely from `planner/prompts.py`'s added content -- no mocked/frozen LLM
response can demonstrate that transition honestly, because a canned response
cannot organically change when the prompt text changes; only a live call can
show the prompt-content edit is what actually moved the outcome (the
rejected-alternative guard, AC-003, exists precisely because a keyword rule
layered on top of an *unchanged* prompt would also make a mocked assertion
pass). This suite therefore makes LIVE calls against the configured LLM
backend (temperature=0.0, matching production), skipped when that backend is
unreachable -- the same unavailable-dependency-skip convention
`test_corpus_regression.py` uses for `pdftotext`.

Live reproduction (pre-fix, documented RED) and the fixed (post-fix, GREEN)
result are both captured verbatim in the SPEC-INFRA-007 completion report.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import pytest

from src.agents.planner.decomposer import CriteriaPlanner
from src.models.ir import Criteria


def _llm_backend_reachable() -> bool:
    base_url = os.environ.get("VLLM_BASE_URL")
    if not base_url:
        return False
    try:
        parsed = urlparse(base_url)
        if not parsed.hostname or not parsed.port:
            return False
        with socket.create_connection((parsed.hostname, parsed.port), timeout=3):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _llm_backend_reachable(),
    reason="LLM backend (VLLM_BASE_URL) unreachable -- this suite makes live calls",
)


def _decompose(entity_text: str, domain: str = "Condition"):
    planner = CriteriaPlanner()
    criterion = Criteria(
        name=entity_text, domain=domain, entity_text=entity_text, logic_type="ABSENCE"
    )
    return planner._decompose_criterion(criterion)


class TestLiverDiseaseSubCriteriaGetMeasurementDomain:
    """AC-001: the Planner's domain guidance produces the correct domain for
    CAROLINA's liver-disease sub-criteria (spec.md Section 2.4's confirmed
    live-current-store-equivalent records)."""

    def test_should_assign_measurement_domain_when_decomposing_elevated_liver_enzymes(self):
        result = _decompose("Elevated Liver Enzymes (ALT/AST)")
        assert result.sub_criteria, "expected the umbrella criterion to decompose"
        for sc in result.sub_criteria:
            assert sc.domain == "Measurement", (
                f"{sc.name!r} assigned domain={sc.domain!r}, expected Measurement"
            )

    def test_should_assign_measurement_domain_when_decomposing_impaired_synthetic_function(self):
        result = _decompose("Impaired Synthetic Function", domain="Observation")
        assert result.sub_criteria, "expected the umbrella criterion to decompose"
        for sc in result.sub_criteria:
            assert sc.domain == "Measurement", (
                f"{sc.name!r} assigned domain={sc.domain!r}, expected Measurement"
            )


class TestDomainAssignmentIsStableAtZeroTemperature:
    """spec.md Section 2.3 / plan.md M3: re-confirm the fixed prompt is still
    100% stable across repeated runs at temperature=0.0 (a smaller repeat
    count than the original 5-sample check; see the completion report for
    the additional runs performed outside the test suite)."""

    def test_should_return_identical_domains_across_repeated_runs(self):
        seen = set()
        for _ in range(3):
            result = _decompose("Elevated Liver Enzymes (ALT/AST)")
            seen.add(tuple(sc.domain for sc in result.sub_criteria))
        assert seen == {("Measurement", "Measurement")}, (
            f"domain assignment was not stable across repeated runs: {seen}"
        )


class TestRejectedAlternativeGuard:
    """AC-003 (2 of 2): the guidance is prompt content, not a lexical/keyword
    rule -- domain-ambiguous criteria of the DOMAIN_PRECHECK-harm shape
    (spec.md Section 2.1/2.5) must not be pushed to an incorrect domain by
    this SPEC's prompt-content addition. The mechanical diff-scan half of
    AC-003 (no new code branch keyed on entity_text/name/source_text) is
    covered separately by `scripts/check_no_domain_override_rule.py` /
    the completion report's git-diff evidence."""

    def test_should_keep_correct_domain_for_microalbuminuria_shaped_criterion(self):
        # Pre-fix this criterion is atomic (live-verified, unchanged domain
        # "Measurement"). Post-fix it may decompose -- a disclosed, benign
        # side effect (see the completion report's Residual Risk section) --
        # but every resulting sub-item's domain must stay correct.
        result = _decompose("Microalbuminuria or proteinuria", domain="Measurement")
        for sc in result.sub_criteria:
            assert sc.domain == "Measurement", (
                f"{sc.name!r} assigned domain={sc.domain!r}, expected Measurement "
                "(DOMAIN_PRECHECK once flipped this exact shape to Condition)"
            )

    def test_should_not_decompose_inr_monitoring_compliance_shaped_criterion(self):
        # Live-verified stable (pre-fix and post-fix): this criterion stays
        # atomic. Its OWN domain field is never mutated by the decomposer
        # regardless of decompose-triggering, so this also directly confirms
        # the top-level domain assignment is unchanged (still "Observation").
        result = _decompose("INR monitoring compliance", domain="Observation")
        assert result.sub_criteria == []
        assert result.domain == "Observation"
