"""A "drug naive" criterion asks for ABSENCE of the drug, and maps on the drug.

Nine criteria in the 2026-09-10 six-trial delivery were refused
``domain-contradiction``. Five of them are Drug criteria whose ``entity_text`` names a
treatment-history STATE rather than a drug, four of those being a line that NEGATES a
drug and was nonetheless extracted as ``PRESENCE``::

    [1] incl #6   'Anti-diabetic drug naive'                      domain=Drug logic=PRESENCE
    [1] incl #10  'Anti-diabetic drug naive'                      domain=Drug logic=PRESENCE
    [9] incl #10  'Drug Naïve or Pre-treated (Excluding GLP-1/…)' domain=Drug logic=PRESENCE
    [9] incl #11  'Drug Naïve or Pre-treated (Excluding GLP-1/…)' domain=Drug logic=PRESENCE
    [9] incl #12  'Stable Background Medication (8 weeks prior…)' domain=Drug logic=PRESENCE

"Drug naive" means the patient has NOT taken the drug, so ``PRESENCE`` is the inverse of
what the protocol says. ("Stable Background Medication" is the one row that is not a
negation; it shares only the second half of the defect, below.)

The second half of the defect is what the mapper was asked: every
one of these rows carries an EMPTY ``sourceText``, because the model emitted no
``entity_text`` at all, so :func:`~src.utils.criterion_seed.criterion_mapper_seed` fell
back to the criterion's human-facing ``name`` -- a protocol phrase, not a drug. The
recorded refusal for the LEADER rows says what came back::

    DrugExposure reads Drug but the concept set mapped for 'Anti-diabetic drug naive'
    holds only Condition, Measurement, Observation, Procedure concepts, so the rule
    would match nothing

The fix is in ``agent1/prompts.NCT_SYSTEM_PROMPT``, and it belongs there rather than in a
producer -- but the reason is narrower than "no producer touches these fields", because
one does:

* ``logic_type`` IS overridden downstream, on the EXCLUSION path only.
  ``_build_criteria(..., force_logic_type="ABSENCE")`` (``parser.py:1322``) forces every
  exclusion rule to ABSENCE and logs a polarity override; inclusion rules pass no
  ``force_logic_type`` (``parser.py:1319``), so the model's value stands. All five rows
  above are INCLUSION rules.
* ``entity_text`` is normalised, never fabricated. ``_normalize_entity_text``
  (``parser.py:1569``) returns early when it is ``None`` and otherwise only strips
  parentheticals from Drug entities, so nothing downstream can supply an entity the model
  omitted; the absent entity travels intact to the mapper seed.

That is the contrast with ``value_constraint``, whose prompt rule failed in `738be93`
precisely because a parser pre-computed it and a repair step re-attached it.

What this file gates is the MECHANISM, on the real rows: the seed a missing
``entity_text`` falls back to, and the store row an entity-less IR leaf produces. The
downstream refusal itself is already gated by
``tests/test_seeded_rule_domain_contradiction.py`` and is not repeated here.
"""

from __future__ import annotations

from src.agents.agent1 import prompts
from src.services.tte_service import TTEService
from src.utils.criterion_seed import criterion_mapper_seed


class _IRLeaf:
    """The attribute surface ``_criteria_from_ir`` reads off an IR ``Criteria``."""

    def __init__(self, *, name, entity_text, domain="Drug", logic_type="PRESENCE"):
        self.name = name
        self.entity_text = entity_text
        self.domain = domain
        self.logic_type = logic_type
        self.source_text = "Anti-diabetic drug naive"
        self.sub_criteria = []
        self.group_type = "ALL"
        self.conditional = False
        self.value_constraint = None
        self.window = None


# The five refused rows, verbatim from
# `output/site_gap/2026-09-10/store/studies.json`.
_WINDOW = {"start": -365, "end": 0}
REFUSED_ROWS = [
    {"sourceText": "", "description": "Anti-diabetic drug naive", "window": _WINDOW},
    {
        "sourceText": "",
        "description": "Drug Naïve or Pre-treated (Excluding GLP-1/DPP-4/SGLT-2)",
        "window": _WINDOW,
    },
    {
        "sourceText": "",
        "description": "Stable Background Medication (8 weeks prior to screening)",
        "window": _WINDOW,
    },
]


class TestWhatTheMapperWasActuallyAsked:
    """The seed is the entity, and with no entity it is a phrase written for a human."""

    def test_should_seed_on_the_protocol_phrase_when_the_criterion_carries_no_entity(self):
        seeds = [criterion_mapper_seed(row) for row in REFUSED_ROWS]

        assert seeds[0] == "Anti-diabetic drug naive"
        assert seeds[1] == "Drug Naïve or Pre-treated (Excluding GLP-1/DPP-4/SGLT-2)"
        # The window-expressed duration is stripped by `738be93`; what is left is still
        # a policy phrase, not a drug.
        assert seeds[2] == "Stable Background Medication"

    def test_should_seed_on_the_drug_when_the_criterion_carries_one(self):
        """The control that makes the case above mean something."""
        row = dict(REFUSED_ROWS[0], sourceText="anti-diabetic agent")

        assert criterion_mapper_seed(row) == "anti-diabetic agent"


class TestTheStoreRowAnEntitylessLeafProduces:
    def test_should_leave_source_text_empty_when_the_ir_leaf_has_no_entity_text(self):
        service = TTEService.__new__(TTEService)

        rows = service._criteria_from_ir(
            [_IRLeaf(name="Anti-diabetic drug naive", entity_text=None)]
        )

        assert len(rows) == 1
        assert rows[0]["sourceText"] == ""
        assert rows[0]["description"] == "Anti-diabetic drug naive"
        # And therefore the mapper is asked about the name.
        assert criterion_mapper_seed(rows[0]) == "Anti-diabetic drug naive"

    def test_should_carry_the_drug_into_source_text_when_the_ir_leaf_names_one(self):
        service = TTEService.__new__(TTEService)

        rows = service._criteria_from_ir(
            [_IRLeaf(name="Anti-diabetic drug naive", entity_text="anti-diabetic agent",
                     logic_type="ABSENCE")]
        )

        assert rows[0]["sourceText"] == "anti-diabetic agent"
        assert rows[0]["logicType"] == "ABSENCE"
        assert criterion_mapper_seed(rows[0]) == "anti-diabetic agent"


class TestTheExtractionPromptCarriesTheRule:
    """Content assertions, because there is no other producer to assert against.

    ``logic_type`` and ``entity_text`` come from the model's reading of the line and from
    nothing else, so the prompt is the whole implementation. Each rule is asserted to
    appear exactly ONCE: a rule stated twice is two homes for one decision, and the
    second copy is the one that drifts.
    """

    def test_should_name_the_fused_negation_vocabulary_in_pattern_c(self):
        text = prompts.NCT_SYSTEM_PROMPT

        for word in ('"treatment-naive"', '"drug-naive"', '"insulin-naïve"',
                     '"no prior\n  use of"', '"washout of"'):
            assert text.count(word) == 1, word

    def test_should_put_the_negation_in_logic_type_and_not_in_the_entity(self):
        text = prompts.NCT_SYSTEM_PROMPT

        assert text.count(
            "the negation belongs to `logic_type` and NEVER to `entity_text`"
        ) == 1

    def test_should_make_entity_text_mandatory_on_a_leaf_criterion(self):
        text = prompts.NCT_SYSTEM_PROMPT

        assert text.count(
            "MANDATORY on\n  every criterion that has no `sub_criteria`"
        ) == 1

    def test_should_leave_the_natural_language_prompt_alone(self):
        """`SYSTEM_PROMPT` serves a different path and was not re-verified.

        It carries no Pattern C block of its own beyond two lines and none of Patterns
        E-H, so the two prompts already differ substantially; not sweeping it creates no
        drift this edit is responsible for. Pinned so a later sweep is a deliberate act.
        """
        assert "treatment-naive" not in prompts.SYSTEM_PROMPT
        assert "MANDATORY on" not in prompts.SYSTEM_PROMPT
