"""The validation pass must not be opened on a participant-flow diagram.

``_parse_criteria_items`` opens an LLM validation pass whenever the regex found
fewer than 5 items in more than 200 characters. That gate cannot tell two very
different spans apart: prose the regex could not split (the case the pass exists
to rescue) and a CONSORT counts table that holds no criteria at all. On CAROLINA's
main paper the second kind reached the pass, which faithfully structured the
participant-flow diagram into six plausible-looking "inclusion criteria".

Every span below is verbatim ``pdftotext`` output from ``data/papers``, captured
by ``extract_eligibility_from_text`` at the commit that introduced the refusal --
not synthetic text. Two must be refused, three must still be rescued.

The tests are order-independent: ``tests/test_parser_paper_status.py`` installs a
``MagicMock`` under ``src.agents.agent1.pubmed_fetcher`` at import time and never
removes it, so the import below repairs that stub rather than trusting collection
order.
"""
import importlib
import logging
import sys
import types

_NAME = "src.agents.agent1.pubmed_fetcher"
_mod = sys.modules.get(_NAME)
if not isinstance(_mod, types.ModuleType):
    sys.modules.pop(_NAME, None)
    _mod = importlib.import_module(_NAME)
pf = _mod


# The real 384-char CARMELINA inclusion fragment -- the ONE span in the ingested
# corpus where the gate actually opens today. Duplicated from
# tests/test_llm_criteria_parse_contract.py on purpose: importing it would couple
# these tests to that module's import-time state.
CARMELINA_FRAGMENT = (
    "1) Documented diagnosis of type 2 diabetes before visit 1 (screening).\n"
    "2) Male or female patients who are drug-naive or pre-treated with any antidiabetic\n"
    "background therapy, excluding treatment with GLP-1 receptor agonists, DPP-4 inhibitors\n"
    "or SGLT-2 inhibitors if >= 7 consecutive days.\n"
    "3) Stable antidiabetic background medication (unchanged daily dose) for at least 8 weeks\n"
    "prior to visit 1.\n"
)


# data/papers/NCT01243424/jama_2019_carolina.pdf, DEGRADED path, inclusion
# span. 1545 chars, 42 non-blank lines, 34 of them opening with a bare count
# (81%). The capture anchored on the flow-diagram row
# "4021 Did not meet inclusion criteria", so the span is the rest of the
# diagram. The regex yields 1 item from it, so the gate opens -- this is the
# site where the pass turned one unusable item into six plausible ones
# ("HbA1c out of window", "BMI >45 at visit 1", "Not type 2 diabetes",
# "Aged <40 or >85 y at visit 1A" and two more).
CAROLINA_CONSORT_SPAN = """\
3490 HbA1c out of window
169 Lack of documentation of high CV risk
91 BMI >45 at visit 1
35 Not on a stable glucose-lowering
medication regimen for at least 8 wk
prior to visit 1
28 Not type 2 diabetes
26 Aged <40 or >85 y at visit 1A
324 Declined to participate
171 Other reasons
33 Visit window 1A-1B exceeded
26 Lost to follow-up
22 Adverse events

6042 Participants randomized

3028 Participants randomized to receive linagliptin
3023 Received treatment as randomized
1127 Discontinued treatment prematurely
5 Did not receive treatment as randomized

3014 Participants randomized to receive glimepiride
3010 Received treatment as randomized
1178 Discontinued treatment prematurely
4 Did not receive treatment as randomized

2899 Participants completed the study or died
124 Participants did not complete the study
63 Withdrew consent
61 Lost to follow-up (including site closure)

2895 Participants completed the study or died
115 Participants did not complete the study
49 Withdrew consent
66 Lost to follow-up (including site closure)

3023 Participants included in the primary
outcome analysis
3000 Vital status at study end available
23 Vital status at study end not available

3010 Participants included in the primary
outcome analysis
2988 Vital status at study end available
22 Vital status at study end not available

uptitrated to a potential maximum dose of 4 mg/d every 4 weeks
during the first 16 weeks. After the first 16 weeks, participants
returned for follow-up study visits every 16 weeks until the end
of the study. A final"""


# data/papers/NCT01897532/jama_2019_carmelina.pdf, DEGRADED path. 1716 chars,
# 50 non-blank lines, 32 digit-leading (64%). A second CONSORT diagram, from a
# different journal template and a different trial. The gate does NOT open here
# (the regex yields 6 items), so the refusal is inert in effect -- it is kept
# because it is the independent case the threshold was not tuned on.
CARMELINA_CONSORT_SPAN = """\
a
2467 No documentation of
high cardiovascular risk
2234 Hemoglobin A1c not in specified range
112 Active liver disease or impaired hepatic functionb
89 Estimated glomerular filtration rate
<15 mL/min/1.73 m2 and/or need for
maintenance dialysis
89 DPP-4 inhibitor, SGLT-2 inhibitor, or GLP-1
receptor agonist pretreatment for ≥7 d
18 Had type 1 diabetes
179 Declined to participate
422 Other reasons
23 Lost to follow-up
19 Adverse events
380 Other various reasons

6991 Randomized

3499 Randomized to receive linagliptin
3494 Received linagliptin as randomized
5 Did not receive linagliptin

3492 Randomized to receive placebo
3485 Received placebo as randomized
7 Did not receive placebo

DPP-4 indicates dipeptidyl
peptidase 4; SGLT-2, sodium-glucose
cotransporter 2; GLP-1, glucagon-like
peptide 1.

3458 Had primary outcome data or died
36 Did not have primary
outcome data
20 Lost to follow-up
16 Withdrew consent

3430 Had primary outcome data or died
55 Did not have primary
outcome data
25 Lost to follow-up
30 Withdrew consent

834 Discontinued treatment before end of study

955 Discontinued treatment before end of study

3494 Included in primary analysis
5 Excluded (did not receive intervention)

3485 Included in primary analysis
7 Excluded (did not receive intervention)

Outcome
The primary outcome was defined as the time to first occurrence of CV death, nonfatal myocardial infarction, or nonfatal stroke (3-point major adverse CV event [MACE]). The
original protocol included hospitalization for unstable
angina pectoris in the primary outcome (a 4-point MACE).
However, this was changed by the steering committee in a
protocol amendment in 2016 based on emerging evidence
that a primary outcome"""


# data/papers/NCT01131676/NEJMoa1504720.pdf, DEGRADED path. 528 chars, 9
# non-blank lines, 0 digit-leading. Real inclusion prose that pdftotext
# line-wrapped, which is exactly what the validation pass exists to rescue.
EMPAREG_WRAPPED_PROSE_SPAN = """\
with type 2 diabetes were adults
(≥18 years of age) with a body-mass index (the
weight in kilograms divided by the square of the



The New England Journal of Medicine is produced by NEJM Group, a division of the Massachusetts Medical Society.



height in meters) of 45 or less and an estimated
glomerular filtration rate (eGFR) of at least 30 ml
per minute per 1.73 m2 of body-surface area, according to the Modification of Diet in Renal
Disease criteria. All the patients had established
cardiovascular disease (as defined in"""


# data/papers/NCT01179048/NEJMoa1603827.pdf, DEGRADED path, inclusion span.
# 691 chars, 13 non-blank lines, 0 digit-leading. Real wrapped prose.
LEADER_WRAPPED_INCLUSION_SPAN = """\
were the following: an age of 50 years or
more with at least one cardiovascular coexisting
condition (coronary heart disease, cerebrovascular disease, peripheral vascular disease, chronic
kidney disease of stage 3 or greater, or chronic
heart failure of New York Heart Association
class II or III) or an age of 60 years or more with
at least one cardiovascular risk factor, as determined by the investigator (microalbuminuria or
proteinuria, hypertension and left ventricular
hypertrophy, left ventricular systolic or diastolic
dysfunction, or an ankle–brachial index [the ratio
of the systolic blood pressure at the ankle to the
systolic blood pressure in the arm] of less than
0.9).9 Major"""


# Same PDF, exclusion span. 456 chars, 6 non-blank lines, 0 digit-leading.
LEADER_WRAPPED_EXCLUSION_SPAN = """\
were type 1 diabetes; the use of GLP-1–receptor agonists, dipeptidyl peptidase 4 (DPP-4) inhibitors, pramlintide,
or rapid-acting insulin; a familial or personal
history of multiple endocrine neoplasia type 2 or
medullary thyroid cancer; and the occurrence of



The New England Journal of Medicine is produced by NEJM Group, a division of the Massachusetts Medical Society.



an acute coronary or cerebrovascular event within 14 days before screening and"""


def _recorder(monkeypatch):
    """Replace the pass with a recorder. It must not raise.

    ``_parse_criteria_items`` wraps the call in ``except Exception``, so a stub
    that raises would be swallowed and logged, and the test would pass whether or
    not the pass was invoked.
    """
    seen = []

    def record(text):
        seen.append(text)
        return []

    monkeypatch.setattr(pf, "_llm_parse_criteria", record)
    return seen


# ------------------------------------------------------------------ must refuse


def test_should_decline_the_validation_pass_when_the_span_is_a_consort_flow_diagram(
    monkeypatch,
):
    seen = _recorder(monkeypatch)

    items = pf._parse_criteria_items(CAROLINA_CONSORT_SPAN)

    assert seen == [], "the pass was invoked on a participant-flow diagram"
    # The gate would otherwise have opened: a long span the regex barely split.
    assert len(items) < 5, items
    assert len(CAROLINA_CONSORT_SPAN) > 200


def test_should_return_the_regex_items_unchanged_when_the_pass_is_declined(monkeypatch):
    """Refusing must not change the function's contract, only skip the pass."""
    monkeypatch.setattr(pf, "_llm_parse_criteria", lambda text: [])
    regex_only = pf._parse_criteria_items(CAROLINA_CONSORT_SPAN)

    items = pf._parse_criteria_items(CAROLINA_CONSORT_SPAN)

    assert items == regex_only
    assert items, "the regex result must still be returned"


def test_should_name_the_refusal_reason_when_the_pass_is_declined(monkeypatch, caplog):
    _recorder(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=pf.logger.name):
        pf._parse_criteria_items(CAROLINA_CONSORT_SPAN)

    assert pf.LLM_REASON_FLOW_DIAGRAM in caplog.text, caplog.text
    assert pf.LLM_PASS_REFUSED_MARKER in caplog.text, caplog.text


def test_should_distinguish_a_refusal_from_an_empty_pass_when_the_pass_is_declined(
    monkeypatch, caplog
):
    """A declined pass and a pass that ran and found nothing are different outcomes.

    ``LLM_PASS_EMPTY_MARKER`` documents itself as "the validation pass RAN and
    produced nothing", and it is the phrase a reader greps for to establish that.
    Logging it for a refusal would put the two back into one silence -- the exact
    confusion that marker was added to end.
    """
    _recorder(monkeypatch)

    with caplog.at_level(logging.INFO, logger=pf.logger.name):
        pf._parse_criteria_items(CAROLINA_CONSORT_SPAN)

    assert pf.LLM_PASS_EMPTY_MARKER not in caplog.text, caplog.text
    assert "invoking LLM validation pass" not in caplog.text, caplog.text


def test_should_score_a_second_independent_diagram_when_the_predicate_is_applied():
    """The threshold is not tuned to one paper.

    CARMELINA's diagram comes from a different trial and a different journal
    template, and it was not used to choose the thresholds. The gate does not open
    on this span, so the discriminator is exercised directly.
    """
    assert pf._is_participant_flow_table(CARMELINA_CONSORT_SPAN)


# --------------------------------------------------------------- must not refuse


def test_should_still_open_the_validation_pass_when_the_span_is_wrapped_prose(
    monkeypatch,
):
    """The regression guard on what the pass is actually for.

    These three spans are real eligibility prose that ``pdftotext`` line-wrapped.
    Widening the discriminator until it swallows them removes the rescue.
    """
    for span in (
        EMPAREG_WRAPPED_PROSE_SPAN,
        LEADER_WRAPPED_INCLUSION_SPAN,
        LEADER_WRAPPED_EXCLUSION_SPAN,
    ):
        seen = []

        def record(text, _seen=seen):
            _seen.append(text)
            return []

        monkeypatch.setattr(pf, "_llm_parse_criteria", record)

        pf._parse_criteria_items(span)

        assert seen == [span], (
            f"the pass was refused on real wrapped prose: {span[:60]!r}"
        )


def test_should_not_decline_the_pass_when_the_span_is_a_numbered_criteria_list(
    monkeypatch,
):
    """The only gate opening on the ingested corpus must survive.

    A numbered list writes "1)" or "1."; a flow diagram writes "3490 HbA1c out of
    window". The predicate requires whitespace after the digits, which is what
    keeps the two apart.
    """
    seen = _recorder(monkeypatch)

    pf._parse_criteria_items(CARMELINA_FRAGMENT)

    assert seen == [CARMELINA_FRAGMENT]


# ------------------------------------------------------- the measured thresholds


def test_should_reproduce_the_measured_line_fractions_when_the_corpus_is_scored():
    """Pin the evidence the thresholds rest on.

    Measured over the six-study corpus: the two diagrams sit at 0.81 and 0.64, and
    every span carrying real criteria sits at 0.02 or below. The thresholds (5 rows
    and 0.30) sit in that empty band. If a future edit moves them, this fails and
    names the margin it spent.
    """
    def fraction(text):
        lines = [ln for ln in text.split("\n") if ln.strip()]
        rows = sum(1 for ln in lines if pf._FLOW_ROW_RE.match(ln))
        return rows, len(lines)

    assert fraction(CAROLINA_CONSORT_SPAN) == (34, 42)
    assert fraction(CARMELINA_CONSORT_SPAN) == (32, 50)
    assert fraction(EMPAREG_WRAPPED_PROSE_SPAN) == (0, 9)
    assert fraction(LEADER_WRAPPED_INCLUSION_SPAN) == (0, 13)
    assert fraction(LEADER_WRAPPED_EXCLUSION_SPAN) == (0, 6)
    assert fraction(CARMELINA_FRAGMENT) == (0, 6)

    assert pf._FLOW_MIN_ROWS == 5
    assert pf._FLOW_MIN_FRACTION == 0.30


def test_should_not_refuse_an_empty_or_short_span_when_the_predicate_is_applied():
    assert not pf._is_participant_flow_table("")
    assert not pf._is_participant_flow_table("\n\n\n")
    # Four count rows is under the row floor even at fraction 1.0.
    assert not pf._is_participant_flow_table("1 a\n2 b\n3 c\n4 d")
    assert pf._is_participant_flow_table("1 a\n2 b\n3 c\n4 d\n5 e")
