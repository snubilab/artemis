"""Every substantive criteria block contributes, and near-identical tiers stay apart.

`_best_section_match` used to keep the single heaviest regex match and discard
the rest. CAROLINA's supplement repeats "Inclusion criteria:" as a running page
header, so pdftotext yields ONE criteria list split into three page-sized
captures (protocol pages 5, 6 and 7). Keeping only the heaviest -- page 6, the
CV-risk group -- dropped page 5 (the T2DM diagnosis and both HbA1c tiers) and
page 7 (BMI, age, informed consent, stable background medication) entirely.

The blocks are NOT three renderings of one list at different detail levels.
Measured on the production rendering (`pdftotext <pdf> -`, no -layout): across
the three captures the only cross-block item pairs scoring >= 0.7 are the page
footer boilerplate ("! 2016 Boehringer Ingelheim ...", "This document may not
..."), which repeat verbatim on every page. Real criteria overlap zero. So
union is the right operation; the dedup below exists for the boilerplate.

The hazard union creates is the opposite one, and it is what these tests pin:
two DIFFERENT criteria written as near-identical strings must not be fused.
"""
import importlib.util
import pathlib
import shutil
import subprocess
from difflib import SequenceMatcher

import pytest

from src.agents.agent1.criteria_dedup import numerically_distinct, or_group_alternatives


def _load():
    """Resolve the parse chain deterministically, whatever the collection order.

    ``tests/test_parser_paper_status.py`` installs a MagicMock at
    ``sys.modules["src.agents.agent1.pubmed_fetcher"]`` at MODULE level -- i.e.
    during collection -- whose ``extract_eligibility_from_text`` returns
    ``{"inclusion": [], "exclusion": []}``. Any module collected after it
    alphabetically that binds the symbol at import time binds the mock, and every
    assertion here silently becomes a zero. ``test_corpus_regression.py`` escapes
    only because "corpus" sorts before "parser".

    Loading from the file path bypasses ``sys.modules`` entirely, which is the
    idiom ``tests/test_llm_criteria_parse_contract.py`` already uses against the
    same landmine. The module name is deliberately distinct so this copy never
    replaces the real entry for anything else.
    """
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "src" / "agents" / "agent1" / "pubmed_fetcher.py")
    spec = importlib.util.spec_from_file_location("_pubmed_fetcher_block_union", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FETCHER = _load()

pytestmark = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="pdftotext (poppler-utils) not installed"
)

# CAROLINA inclusion criterion 1, tiers a) and b), verbatim from the supplement.
# Two different HbA1c bands tied to two different background-therapy sets: a
# patient qualifying under (b) does not qualify under (a). Fusing them silently
# narrows or widens the cohort, which no downstream check would catch.
TIER_A = (
    "HbA1c 6.5 - 8.5% (48 - 69 mmol/mol) while patient is treatment naïve (if "
    "intolerant or contra-indicated to first line anti-diabetic treatment) or "
    "treated with:"
)
TIER_B = (
    "HbA1c 6.5 - 7.5% (48 - 58 mmol/mol) while patient is treated with "
    "sulphonylurea (SU) monotherapy, or glinide monotherapy"
)
# The same two tiers as they read before pdftotext appends each one's therapy
# list -- i.e. the wording the parse would produce on any document that wraps
# the line earlier. This pair is what makes the hazard real rather than
# theoretical: whole-string similarity scores it 0.857, well over the 0.7
# duplicate threshold, so a rule that consults similarity alone fuses them.
TIER_A_HEAD = "HbA1c 6.5 - 8.5% (48 - 69 mmol/mol) while patient is treatment naive"
TIER_B_HEAD = "HbA1c 6.5 - 7.5% (48 - 58 mmol/mol) while patient is treated with"


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """CAROLINA's CV-risk block opens the LLM validation gate (3 items, 2236 chars).

    The gate is evaluated per block, so unioning the blocks does not close it --
    it still fires on that one span both before and after this change. Left
    unstubbed each test here bills a real call and its assertions become
    nondeterministic, which is the opposite of a contract.
    """
    fetcher = _FETCHER
    # The module OBJECT, not a dotted string: the real sys.modules entry may be a
    # MagicMock or absent depending on collection order (see _load).
    monkeypatch.setattr(fetcher, "_llm_parse_criteria", lambda *a, **kw: [])
    monkeypatch.setattr(
        fetcher, "_get_criteria_llm",
        lambda *a, **kw: pytest.fail("the LLM was reached despite the stub"),
    )


def _criteria(study_nct, pdf):
    from src.agents.agent1.parser import LogicDecomposer

    text = subprocess.run(
        ["pdftotext", f"data/papers/{study_nct}/{pdf}", "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    section = LogicDecomposer._extract_eligibility_section(text)
    return _FETCHER.extract_eligibility_from_text(section or text)


def _inclusion(study_nct, pdf):
    return _criteria(study_nct, pdf)["inclusion"]


def test_should_score_above_the_duplicate_threshold_when_tiers_are_compared_by_similarity():
    """The gate is proven to fire, not assumed to.

    This is the rule the numeric guard replaces. If this assertion ever fails
    the hazard has changed shape and the guard below needs re-deriving -- it
    does NOT mean the guard became unnecessary.
    """
    ratio = SequenceMatcher(None, TIER_A_HEAD.lower(), TIER_B_HEAD.lower()).ratio()
    assert ratio >= 0.7, f"expected the tiers to look like duplicates, got {ratio:.4f}"


def test_should_keep_tiers_apart_when_their_numeric_literals_differ():
    """The discriminator: different thresholds mean different criteria."""
    assert numerically_distinct(TIER_A_HEAD, TIER_B_HEAD)
    assert numerically_distinct(TIER_A, TIER_B)


def test_should_not_separate_items_when_their_numeric_literals_match():
    """The guard must not veto every merge -- verbatim repeats still collapse."""
    boilerplate = (
        "This document may not - in full or in part - be passed on, reproduced, "
        "published or otherwise used without prior written permission"
    )
    assert not numerically_distinct(boilerplate, boilerplate)
    assert not numerically_distinct("Type 1 diabetes mellitus", "Type 1 diabetes mellitus.")


def test_should_recover_both_hba1c_tiers_as_separate_items_when_parsing_carolina():
    inclusion = _inclusion("NCT01243424", "jama_2019_carolina_supplement.pdf")
    matched_a = [i for i in inclusion if "6.5 - 8.5%" in i]
    matched_b = [i for i in inclusion if "6.5 - 7.5%" in i]
    assert len(matched_a) == 1, f"tier a) missing or duplicated: {matched_a}"
    assert len(matched_b) == 1, f"tier b) missing or duplicated: {matched_b}"
    assert matched_a[0] != matched_b[0]


def test_should_recover_the_t2dm_diagnosis_criterion_when_parsing_carolina():
    inclusion = _inclusion("NCT01243424", "jama_2019_carolina_supplement.pdf")
    assert any("Documented diagnosis of T2DM" in i for i in inclusion)


def test_should_keep_the_cv_risk_or_group_intact_when_parsing_carolina():
    """The heaviest block's contribution must survive the union unchanged."""
    inclusion = _inclusion("NCT01243424", "jama_2019_carolina_supplement.pdf")
    groups = [i for i in inclusion if or_group_alternatives(i)]
    assert len(groups) == 1
    assert len(or_group_alternatives(groups[0])) == 14


def test_should_ignore_a_heading_mentioned_mid_sentence_when_parsing_aristotle():
    """ARISTOTLE's protocol says "Each subject who meets the inclusion/exclusion
    criteria will be randomly assigned to one of two treatment groups".

    That is a mention inside a sentence, not a section heading. It captures 169
    characters of randomisation prose which parse into two plausible-looking
    criteria. Union must not admit them.
    """
    exclusion = _criteria("NCT00412984", "nejmoa1107039_protocol.pdf")["exclusion"]
    # Pin the real list first, so an empty result cannot satisfy the two
    # negative assertions below by vacuous truth.
    assert len(exclusion) == 21
    assert any("mitral stenosis" in i for i in exclusion)
    assert not any("randomly assigned" in i for i in exclusion)
    assert not any("IVRS" in i for i in exclusion)
