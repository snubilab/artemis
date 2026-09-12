"""Two `pdftotext` extraction defects, measured on the production rendering.

Production converts with plain `pdftotext`, no `-layout`
(`src/agents/agent1/parser.py`), so every fixture here is built the same way. A
`-layout` rendering has indentation and marker hierarchy that production never
sees, and a repair verified against it can be a complete no-op on the real path.

Defect A -- `pdftotext` sorts by vertical position, so a superscript digit is
emitted as its own line ABOVE the text it belongs to, truncating the unit.
Defect B -- `_best_section_match` seeded the union with the HEAVIEST block, so
every earlier block's unique items landed after it, out of document order.
"""
import importlib
import re
import shutil
import subprocess
import sys
import types
from unittest.mock import MagicMock

import pytest

# `tests/test_parser_paper_status.py` mutates the REAL modules, not just stubs:
# `_install_module_stubs()` (lines 75-78, 70-72, 83-89) does
# `sys.modules["src.agents.agent1.pubmed_fetcher"].extract_eligibility_from_text
#  = MagicMock(return_value={"inclusion": [], "exclusion": []})`
# and the same for `pubmed_linker`, `enricher`, `pmc_fetcher`, `pmc_supplement`.
# When an earlier test file has already imported those modules, the assignment
# lands on the real module object, and `teardown_module` -- which only pops
# `sys.modules` entries -- cannot undo it. The mocks then persist for the rest
# of the session.
#
# That is a pre-existing defect in that file, not something this file
# introduced: on an unmodified checkout it already fails 12 tests across
# `test_07_pubmed_linker.py`, `test_08_pubmed_fetcher.py` and
# `test_parser_paper_status.py` itself. Reloading restores the real attributes so
# this file's result does not depend on which other file ran first; the order
# matters because `parser` must rebind AFTER its dependencies are real.
# Dependency order matters: `enricher` binds `TrialData` from `nct_fetcher` at
# import, so restoring `enricher` first re-binds the MOCK class and
# `enrich_trial_data` then returns a MagicMock whose `.exclusion_criteria` reads
# as empty -- the same silent empty-list failure, one level deeper. `parser` is
# last because it depends on all of them.
for _polluted in [
    "src.agents.agent1.nct_fetcher",
    "src.agents.agent1.pubmed_fetcher",
    "src.agents.agent1.pubmed_linker",
    "src.agents.agent1.enricher",
    "src.agents.agent1.pmc_fetcher",
    "src.agents.agent1.pmc_supplement",
    "src.agents.agent1.parser",
]:
    _mod = sys.modules.get(_polluted)
    if _mod is None:
        continue
    if not isinstance(_mod, types.ModuleType):
        # The whole module was replaced by a MagicMock; drop it so the next
        # import loads the real file.
        del sys.modules[_polluted]
    elif any(isinstance(v, MagicMock) for v in vars(_mod).values()):
        importlib.reload(_mod)

from src.agents.agent1 import pubmed_fetcher as _pf  # noqa: E402
from src.agents.agent1.eligibility_section import (  # noqa: E402
    extract_eligibility_section,
)
from src.agents.agent1.nct_fetcher import TrialData  # noqa: E402
from src.agents.agent1.parser import LogicDecomposer  # noqa: E402
from src.agents.agent1.pubmed_fetcher import (  # noqa: E402
    _prefer_wording,
    extract_eligibility_from_text,
    rejoin_stranded_superscripts,
)
from src.services.value_constraint import _resolve_unit  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="pdftotext (poppler-utils) not installed"
)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """The LLM fallback gate opens on some of these blocks; a paid, nondeterministic
    call is the opposite of a regression contract."""
    # Patched on the MODULE OBJECT, not by dotted string. A string target is
    # re-resolved through `sys.modules`, and `tests/test_parser_paper_status.py`
    # pops every `src.agents.agent1.*` entry in its `teardown_module`, so in a
    # whole-suite run the string form raises
    # `AttributeError: module 'src.agents.agent1' has no attribute 'pubmed_fetcher'`
    # and the stub silently targets a different module object than the one this
    # file imported.
    monkeypatch.setattr(_pf, "_llm_parse_criteria", lambda *a, **k: [])
    monkeypatch.setattr(
        _pf, "_get_criteria_llm",
        lambda *a, **k: pytest.fail("the LLM was reached despite the stub"),
    )


def _production_text(path):
    """Exactly what `_enrich_from_pdf` holds before it calls the section extractor."""
    out = subprocess.run(
        ["pdftotext", path, "-"], capture_output=True, text=True, check=True
    ).stdout
    out = re.sub(r"Downloaded from .*?\n", "", out)
    out = re.sub(r"Copyright © .*?\n", "", out)
    return re.sub(r"\f", "\n", out)


ARISTOTLE = "data/papers/NCT00412984/nejmoa1107039_protocol.pdf"
CARMELINA = "data/papers/NCT01897532/jama_2019_carmelina_supplement.pdf"
EMPAREG = "data/papers/NCT01131676/nejmoa1504720_appendix.pdf"
CAROLINA = "data/papers/NCT01243424/jama_2019_carolina_supplement.pdf"
DECLARE = "data/papers/NCT01730534/nejmoa1812389_appendix.pdf"


# --------------------------------------------------------------------------
# Defect A
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pdf, stranded, repaired",
    [
        # The digit sits two lines above, with a blank between.
        (ARISTOTLE, "21) Platelet count ≤ 100,000/ mm", "21) Platelet count ≤ 100,000/ mm3"),
        # The exponent belongs mid-line, not at the end -- appending would give
        # "...maintenance dialysis.2".
        (CARMELINA,
         "4) eGFR <15 ml/min/1.73 m (severe renal impairment or ESRD, MDRD formula), as",
         "4) eGFR <15 ml/min/1.73 m2 (severe renal impairment or ESRD, MDRD formula), as"),
        # The stranded digit carries footnote daggers, and the unit has no space.
        (EMPAREG,
         "Estimated glomerular filtration rate – mL/min/1.73m",
         "Estimated glomerular filtration rate – mL/min/1.73m2"),
    ],
    ids=["aristotle-mm3", "carmelina-m2-midline", "empareg-m2-with-daggers"],
)
def test_should_rejoin_the_exponent_when_pdftotext_strands_it_above_its_unit(
    pdf, stranded, repaired
):
    before = _production_text(pdf)
    assert stranded in before.split("\n"), (
        "fixture drifted: the stranded spelling is not a whole line of the PDF text"
    )

    after = rejoin_stranded_superscripts(before)

    # Line-level, not substring: the repaired form CONTAINS the stranded form as
    # a prefix, so `stranded not in after` would fail on a correct repair.
    assert repaired in after.split("\n")
    assert stranded not in after.split("\n")


def test_should_leave_the_inline_spelling_alone_when_one_document_renders_it_both_ways():
    """CARMELINA's supplement writes `mL/min/1.73 m2` inline AND strands the `2`
    elsewhere, so the repair has to be idempotent on the already-correct form."""
    before = _production_text(CARMELINA)
    inline = "mL/min/1.73 m2 at visit 1 (screening) with any UACR."
    assert before.count(inline) == 1

    once = rejoin_stranded_superscripts(before)
    twice = rejoin_stranded_superscripts(once)

    assert once.count(inline) == 1
    assert once == twice, "applying the repair twice is not a fixed point"


def test_should_decline_when_the_stray_digit_has_no_unit_to_attach_to():
    """A page number and a stranded list index look exactly like a superscript on
    their own line. The only thing separating them is what follows."""
    page_number = "Approved v 3.0\n\n3\n\nApixaban\nBMS-562247\n"
    list_index = "3\n) Severe renal insufficiency (serum creatinine > 2.5 mg/dL)\n"

    assert rejoin_stranded_superscripts(page_number) == page_number
    assert rejoin_stranded_superscripts(list_index) == list_index


def test_should_decline_when_a_page_number_precedes_a_line_that_does_carry_a_unit():
    """The dangerous shape: the stray digit is plausible AND the next line has a
    unit. `m2` is already complete, so it offers no site and the join is refused."""
    text = "2\nPatients with a body mass index above 30 kg/m2 were excluded\n"
    assert rejoin_stranded_superscripts(text) == text


def test_should_decline_when_more_than_one_unit_token_could_take_the_exponent():
    """Two candidate sites means the position is a guess, and a wrong guess
    rewrites the criterion rather than degrading it."""
    text = "2\nBody surface area in m and wound diameter in cm were recorded\n"
    assert rejoin_stranded_superscripts(text) == text


def test_should_decline_when_the_digit_is_too_far_above_the_text():
    text = "3\n\n\n\nApixaban BMS-562247 in mL/min/1.73 m dosing\n"
    assert rejoin_stranded_superscripts(text) == text


@pytest.mark.parametrize(
    "truncated, repaired, concept_id",
    [
        ("/ mm", "/ mm3", 8785),
        ("ml/min/1.73 m", "ml/min/1.73 m2", 720870),
        (" kg/m", " kg/m2", 9531),
    ],
)
def test_should_resolve_the_unit_only_once_the_exponent_is_rejoined(
    truncated, repaired, concept_id
):
    """The cost of Defect A is a refused criterion: `_resolve_unit` returns None
    on the truncated spelling, so the bound is dropped as unstated-unit-bound."""
    assert _resolve_unit(truncated)[1] is None
    assert _resolve_unit(repaired)[1] == concept_id


def test_should_repair_the_criterion_on_the_production_extraction_path():
    """Not the text in isolation -- the real `_enrich_from_pdf`, which is the only
    path a delivered criterion travels. Driving the method rather than a replica
    is what makes this test fail for a behavioural reason rather than because a
    helper is missing."""
    enriched = LogicDecomposer()._enrich_from_pdf(
        TrialData(nct_id="NCT00412984"), ARISTOTLE, role="protocol"
    )
    platelet = [c for c in enriched.exclusion_criteria if "Platelet count" in c]

    assert platelet, "the platelet criterion vanished from the exclusion list"
    assert "mm3" in platelet[0], f"unit still truncated: {platelet[0]!r}"


# --------------------------------------------------------------------------
# Defect B
# --------------------------------------------------------------------------

def _section(pdf, kind):
    """The production section chain, with every name bound at import time.

    Deliberately NOT re-imported inside the function:
    `tests/test_parser_paper_status.py` pops every `src.agents.agent1.*` entry
    out of `sys.modules` in its `teardown_module`, so a late import here picks up
    a second, differently-stubbed copy of the parse chain and the section comes
    back empty.
    """
    text = _production_text(pdf)
    section = extract_eligibility_section(text)
    return extract_eligibility_from_text(getattr(section, "text", text))[kind]


def _index_of(items, needle):
    for i, item in enumerate(items):
        if needle in " ".join(item.split()):
            return i
    raise AssertionError(f"{needle!r} not found in {len(items)} items")


def test_should_keep_a_list_header_above_its_members_when_it_sits_in_a_lighter_block():
    """DECLARE's appendix splits its exclusion list across two blocks and the
    SECOND is heavier. Seeding with the heaviest put the header -- and the three
    medication criteria it governs -- after the criteria from the later block."""
    items = _section(DECLARE, "exclusion")

    header = _index_of(items, "Use of the following excluded medications:")
    member = _index_of(items, "Current or recent (within 24 months) treatment with pioglitazone")
    later_block = _index_of(items, "either the systolic BP is elevated")

    assert header < member, "the list header no longer precedes its own member"
    assert header < later_block, "a later block's criterion was hoisted above an earlier one"


def test_should_keep_the_first_block_first_when_the_heaviest_is_in_the_middle():
    """CAROLINA's supplement repeats its inclusion header as a running page
    header, so one list arrives as three page-sized blocks and the middle one is
    heaviest."""
    items = _section(CAROLINA, "inclusion")

    first_block = _index_of(items, "Documented diagnosis of T2DM")
    heaviest_block = _index_of(items, "High risk of CV events")

    assert first_block < heaviest_block


def test_should_keep_the_heaviest_blocks_wording_when_a_lighter_block_seeds_the_slot():
    """Folding in document order means the EARLIEST wording wins, which is the
    wrong half of the trade -- the heaviest block states the criteria at length
    and its phrasing is what the rest of the pipeline was tuned on."""
    lighter = ["Type 2 diabetes mellitus diagnosed before enrolment"]
    heaviest = ["Type 2 diabetes mellitus diagnosed prior to enrolment"]

    assert _prefer_wording(lighter, heaviest) == heaviest


def test_should_decline_to_rephrase_when_the_two_items_state_different_numbers():
    merged = [
        "Age 40 to 85 years at the time of consent",
        "Age 18 to 85 years at the time of consent",
    ]
    assert _prefer_wording(merged, [merged[1]]) == merged


def test_should_not_overwrite_a_slot_already_held_by_the_preferred_blocks_own_item():
    """Two items WITHIN the heaviest block can be similar enough to each other to
    pass the duplicate threshold. Without the guard the second overwrites the
    first's slot, which deletes a criterion instead of rephrasing one."""
    own = ["Documented coronary artery disease", "Documented cerebral artery disease"]
    assert _prefer_wording(list(own), own) == own

