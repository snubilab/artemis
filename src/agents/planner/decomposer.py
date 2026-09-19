"""
Criteria Planner (Agent 1.5) - Clinical Criteria Decomposer.
Decomposes composite clinical criteria into granular, OMOP-searchable sub-criteria.
"""
import json
from typing import Optional, List
from langchain_core.messages import SystemMessage, HumanMessage

from src.utils.llm import get_llm
from src.models.ir import ARTEMISRequest, CohortDefinition, Criteria
from src.agents.planner.prompts import PLANNER_SYSTEM_PROMPT, DECOMPOSITION_PROMPT
from src.services.entity_exception import detect_entity_exception
from src.services.value_constraint import parse_value_constraint
from src.agents.agent1.threshold_classifier import deescape
from src.utils.naming_words import naming_words


def _comparison_form(text: str) -> str:
    """Comparison form for the substring check: de-escaped, whitespace-folded, lowered.

    Same convention as ``threshold_classifier._normalise``, which owns it for ADR-032
    threshold spans; this is the same decision applied to sub-term spans. Tolerating
    case and whitespace drift is safe -- a model that re-wraps a line still copied it
    -- while an analyte the line never mentions is absent under any of these forms.
    """
    return " ".join(deescape(text).split()).lower()


# Moved to `src.utils.naming_words` so `src/utils/circe_lint.py` can ask the same
# question of a whole stored criterion without importing this module's model stack. The
# alias is kept because gate 2 below and every existing caller read the private name.
#
# The moved version does NOT route through `_comparison_form`, and that is an identity
# rather than a tolerance: `deescape` only removes backslashes, and the split pattern
# treats a backslash as a separator like every other non-alphanumeric character, so the
# two agree on every possible input. Re-checked against the 1,910 criterion strings of
# the 2026-09-14 store: zero differ.
_naming_words = naming_words


def _grounded_span(claimed: object, source_text: str, sub_term_text: str) -> Optional[str]:
    """The fragment of the protocol line that names this sub-term, or None.

    The prompt ASKS the model to copy the naming fragment verbatim. This function is
    what makes the answer worth anything: the model's own account of where a term came
    from is exactly what cannot be taken on trust here, since ``stated: true`` on an
    invented analyte is indistinguishable from the truth. Two gates, and a span has to
    pass both:

    1. **Really present in the line**, under :func:`_comparison_form`. Not a fuzzy
       match: fuzz is how an invention scores as a reading.
    2. **Shares a naming word with the sub-term it claims to name.**

    Gate 2 is not belt-and-braces; gate 1 alone is insufficient, and CAROLINA is the
    case that shows it. Asked for a span off ``acute liver disease or impaired hepatic
    function``, the model returned ``impaired hepatic function`` for an *ALT* sub-term.
    That span is a perfectly real substring -- it passes gate 1 -- and it names the
    umbrella, not the analyte. Since every elaborated member can cite the umbrella it
    was elaborated FROM, gate 1 alone would let the whole failure through wearing a
    grounding mark, which is worse than no mark at all. Gate 2 refuses it: the span
    shares no word with "Alanine aminotransferase (ALT) elevation".

    Gate 2 also subsumes the operand case. ``> 2X ULN`` is a real substring of a line
    that states a threshold and names nothing; it shares no word with the analyte. (The
    obvious alternative, :func:`~src.agents.agent1.threshold_classifier.is_headless`,
    does NOT catch it -- measured: it returns False, because ``ULN`` is not a unit
    ``normalize_unit`` recognises.)

    Known and deliberate false negative: a line that names the sub-term by a synonym
    the sub-term does not repeat -- ``SGPT`` decomposed into ``Alanine
    aminotransferase`` -- shares no word and is marked elaboration though it is really
    a reading. The asymmetry is the right way round. An under-credited reading loses
    nothing, because the sub-term is kept either way; an over-credited elaboration is
    the defect being fixed.

    Never raises, and never drops a sub-term. Failing both gates marks the member as
    the model's own; refusing it outright would delete a criterion the pipeline exists
    to recover.
    """
    # `sub_term_text` is deliberately not optional. Defaulted to "", gate 2 would refuse
    # every span, so a caller that forgot the argument would silently mark every member
    # as elaboration -- and a marking that says "all elaboration" reads exactly like one
    # that is working.
    if not isinstance(claimed, str):
        return None
    span = claimed.strip()
    if not span or span.lower() in {"null", "none", "nil"}:
        return None
    if not source_text:
        return None
    if _comparison_form(span) not in _comparison_form(source_text):
        return None
    span_words = _naming_words(span)
    if not span_words or not (span_words & _naming_words(sub_term_text)):
        return None
    return span


def _exception_kept_whole(
    name: str, entity_text: str, source_text: str, members: list[dict]
) -> Optional[str]:
    """The seed text to keep when this split would turn an exception into a sibling.

    A protocol line that names a set and then carves part of it out -- "cancer
    (except for basal cell carcinoma)", "insulin other than human NPH insulin" --
    states ONE criterion. Decomposing it produces the base and the carve-out as
    two members, and Circe then AND-combines them: EMPA-REG's delivered rule 17 is
    "zero cancers AND zero basal cell carcinomas", which removes exactly the
    patient whose only malignancy is the excepted one. The exception is not an
    additional exclusion; it is a subtraction from the first one, and
    :func:`~src.services.entity_subtraction.resolve_entity_exception` is what
    performs it -- but only if the criterion reaches the mapper whole.

    Three gates, and the split is declined only when all three hold. Each one
    keeps a real corpus case on the unchanged path; measured over the 118
    decomposition groups of ``output/site_gap/2026-09-14/store/studies.json``,
    together they fire on exactly one, EMPA-REG's.

    1. **A text here parses.** :func:`detect_entity_exception` is the arbiter and
       is not re-implemented: it declines 19 of the corpus's 32 exception-shaped
       strings under named rules (a hyphenated ``non-X`` is part of a term, an
       anaphoric "allowed short-term insulin" points at text this cannot see, a
       `` + ``-joined group label names no entity), and every decline falls
       through to the split exactly as before.
    2. **The excepted entity is really in the protocol line.** The parse may come
       off a member name the model wrote, so the excepted phrase is checked
       against the line the protocol actually stated -- the same demand
       :func:`_grounded_span` makes of a span, for the same reason. Subtracting
       on an invention creates a new wrong exclusion, which is the failure this
       exists to prevent.
    3. **Another member IS that entity.** Without this, LEADER's insulin line
       collapses: its three members each state their own exception
       ("insulin other than human NPH insulin", ...) and none of them is a
       sibling naming a carved-out entity, so that split is a reading and must
       survive. The member that produced the parse is excluded from the test --
       it names its own excepted phrase as a substring, and a check that let that
       count would collapse every legitimate multi-clause decomposition while
       looking like it worked.

    The returned text is rebuilt rather than copied: the base is the criterion's
    OWN ``entity_text`` where it has one, so what the mapper resolves is Agent 1's
    extracted entity and not a phrase the planner's model invented. It is parsed
    back before being returned -- a long excepted list rebuilds into a string the
    parser's own word cap declines, and returning that would lose the exception in
    a new place instead of the old one.

    :param name: the criterion's name.
    :param entity_text: the criterion's entity text, which becomes the mapper seed.
    :param source_text: the verbatim protocol line.
    :param members: the ``sub_criteria`` payload the model returned.
    :returns: the replacement ``entity_text``, or None to leave the split alone.
    """
    candidates: list[tuple[Optional[int], str]] = [(None, name), (None, entity_text)]
    for index, member in enumerate(members):
        candidates.append((index, str(member.get("name") or "")))
        candidates.append((index, str(member.get("entity_text") or "")))

    line = _comparison_form(source_text)
    for owner, text in candidates:
        exception = detect_entity_exception(text)
        if exception is None:
            continue
        if not line or not all(_comparison_form(p) in line for p in exception.excepted):
            continue
        siblings = [m for i, m in enumerate(members) if i != owner]
        if not any(
            _comparison_form(str(m.get(field) or "")) == _comparison_form(phrase)
            for m in siblings
            for field in ("name", "entity_text")
            for phrase in exception.excepted
        ):
            continue
        kept = f"{entity_text.strip() or exception.base} other than {', '.join(exception.excepted)}"
        rebuilt = detect_entity_exception(kept)
        if rebuilt is None or (
            [p.lower() for p in rebuilt.excepted] != [p.lower() for p in exception.excepted]
        ):
            continue
        return kept
    return None


#: Bounds that state ONE side of a range. `bt` is deliberately absent -- it is a whole
#: band and states both sides -- and so is None, which is no bound at all. A member can
#: never actually carry `bt`: `parse_value_constraint` returns None for a range phrase
#: (measured: `"6.5 - 10.0%"` and `"between 6.5 and 10.0%"` both parse to None), so a
#: member's bound is one-sided or absent. It is listed as excluded anyway, because the
#: check below must keep meaning what it says if that ever changes.
_ONE_SIDED_OPS = frozenset({"gt", "gte", "lt", "lte"})


def _torn_range_declined(entity_text: str, members: list[Criteria]) -> Optional[str]:
    """Why this split is one criterion's range torn in half, or None to let it through.

    CARMELINA states one line -- "HbA1c of >= 6.5% and <= 10.0% at Visit 1
    (screening)" -- and the 2026-09-18 delivery shipped two inclusion rules off it
    that no patient can satisfy together::

        #12 ANY( Measurement gte 6.5 , Measurement lte 10.0 )   -> has a %-unit HbA1c
        #13 ALL( Occurrence{Type:0,Count:0} gte 6.5
               , Occurrence{Type:0,Count:0} lte 10.0 )          -> has NO %-unit HbA1c

    CIRCE ANDs inclusion rules, so #12 and #13 are complements and the cohort is empty
    on every CDM. Both come from this method's caller: the model answered that "HbA1c"
    is an umbrella term and returned two members per parent, each member the SAME
    analyte with one side of the band copied verbatim off the line. The member NAMES
    then describe the opposite of their own operators -- "below lower limit" carrying
    `gte 6.5` -- because `logic_type` is inherited from the parent while
    `value_constraint_text` is copied in the allowed polarity. Those two names appear
    in none of the 234 IR caches; they are this module's.

    The prompt's own rule is that such a criterion is atomic. A member that is the
    parent analyte again, carrying one side of the parent's range, is not a codeable
    sub-term -- it maps to the parent's own concept set -- so there is nothing for the
    fan-out to gain and a boundary to lose.

    Three gates, and the split is declined only when ALL of them hold for EVERY
    member. Measured over the 101 decomposition groups of
    ``output/site_gap/2026-09-18_verify4/store/studies.json``, the first two fire
    together on six groups and the third holds five of them:

    1. **Every member names the parent's own entity**, under :func:`_comparison_form`.
       This is the gate that separates the defect from the thing this module is FOR:
       CAROLINA's liver panel decomposes ``ALT or AST or alkaline phosphatase`` into
       three members whose parent ALSO carries a one-sided bound (``gt 3.0 x ULN``),
       and the analyte identity is the only difference between the two cases.
    2. **Every member carries a one-sided bound.** A member with no parsed bound is
       not half of a range: EMPA-REG's ``Bariatric surgery or intervention`` fans out
       into three procedures carrying no number, and a rule about bounds must not
       reach it.
    3. **The members agree on one unit.** The sixth group is CAROLINA study 10's
       ``Uncontrolled hyperglycaemia``, whose two members are ``>240 mg/dl`` and
       ``>13.3 mmol/L`` -- ONE threshold restated in two units, where the second
       member adds real coverage because Circe's unit filter is a per-criterion AND,
       so a row recorded in mmol/L is matched by that member and by nothing else.
       Gates 1 and 2 alone would decline it and drop those rows; this gate is what
       keeps it split. It is the one gate the brief for this fix did not state, and it
       is here because the corpus had a case for it.

    Deliberately silent about the PARENT's own operator, which is never read. The
    parent is `PRESENCE gte 6.5` before Agent 1's inclusive-upper-bound repair and
    `PRESENCE bt 6.5..10.0` after it merges the pair, and the same two members are
    torn out of both -- so a condition written on the parent's bound would let the
    merged band be torn apart again and the delivered shape would come straight back.

    :param entity_text: the parent criterion's entity text.
    :param members: the sub-criteria as they would be installed, already built, so
        each member's ``value_constraint`` is the one it would really carry --
        including the None that :func:`parse_value_constraint` fail-open produces.
        Checked after construction rather than off the raw payload for that reason:
        the raw ``value_constraint_text`` is a phrase, and what matters is what it
        parses to.
    :returns: the reason to record, or None to leave the split alone.
    """
    parent = _comparison_form(entity_text or "")
    if not parent or not members:
        # Without the parent's own analyte there is nothing to compare a member to,
        # and declining on that would refuse every split. The safe direction here is
        # to let the split through: it is what happens today.
        return None
    units: set[str] = set()
    for member in members:
        if _comparison_form(member.entity_text or "") != parent:
            return None
        vc = member.value_constraint
        if vc is None or vc.op not in _ONE_SIDED_OPS:
            return None
        units.add(_comparison_form(vc.unit_text or ""))
    if len(units) > 1:
        return None
    bounds = ", ".join(
        f"{m.value_constraint.op} {m.value_constraint.value}" for m in members
    )
    return (
        f"every member is {entity_text.strip()!r} again, each carrying a one-sided "
        f"bound ({bounds}) in one unit -- the parent's own range redistributed across "
        f"{len(members)} rules, not a decomposition into codeable sub-terms "
        f"({', '.join(repr(m.name) for m in members)})"
    )


class CriteriaPlanner:
    """
    Agent 1.5: Analyzes each criterion from Agent 1's IR output and
    decomposes composite/umbrella terms into specific sub-criteria.
    
    Pipeline: Agent 1 → [Planner] → Agent 2
    """
    
    def __init__(self, model_name: Optional[str] = None):
        self.llm = get_llm(model_name=model_name, temperature=0.0, json_mode=True)
    
    def plan(self, ir: ARTEMISRequest) -> ARTEMISRequest:
        """
        Process the IR and decompose composite criteria in both target 
        and comparator cohorts.
        
        Args:
            ir: ARTEMISRequest from Agent 1
            
        Returns:
            ARTEMISRequest with decomposed criteria
        """
        print("[Planner] Analyzing criteria for decomposition...")
        
        # Process target cohort
        ir.target = self._process_cohort(ir.target, "target")
        
        # Process comparator cohort
        ir.comparator = self._process_cohort(ir.comparator, "comparator")
        
        return ir
    
    def _process_cohort(self, cohort: CohortDefinition, label: str) -> CohortDefinition:
        """Process a single cohort's inclusion and exclusion rules."""
        # Process inclusion rules
        new_inclusion = []
        for rule in cohort.inclusion_rules:
            processed = self._decompose_criterion(rule)
            new_inclusion.append(processed)
        cohort.inclusion_rules = new_inclusion
        
        # Process exclusion rules
        new_exclusion = []
        for rule in cohort.exclusion_rules:
            processed = self._decompose_criterion(rule)
            new_exclusion.append(processed)
        cohort.exclusion_rules = new_exclusion
        
        total_sub = sum(len(r.sub_criteria) for r in cohort.inclusion_rules + cohort.exclusion_rules)
        print(f"[Planner] {label}: {len(cohort.inclusion_rules)} inclusion, "
              f"{len(cohort.exclusion_rules)} exclusion rules "
              f"({total_sub} sub-criteria generated)")
        
        return cohort
    
    def _decompose_criterion(self, criterion: Criteria) -> Criteria:
        """
        Analyze a single criterion and decompose if composite.
        
        If the LLM determines the criterion is composite, populates
        sub_criteria and sets group_type to "ANY".
        """
        # Skip if entity_text is None or already has sub_criteria
        if not criterion.entity_text or criterion.sub_criteria:
            return criterion
        
        # Call LLM
        # Fail-open on missing source_text (plan-audit D14): a pre-this-field
        # study has source_text=None. Pass an empty string rather than falling
        # back to entity_text, which ir.py documents as normalized and capable
        # of having already lost the threshold entirely — grounding the LLM in
        # text that structurally cannot carry the constraint would silently
        # reintroduce the ungrounded-guess hazard this grounding fix exists to
        # close. An empty Source Text resolves to value_constraint_text: null
        # via the prompt's own instruction, which REQ-007 then turns into None.
        prompt = DECOMPOSITION_PROMPT.format(
            name=criterion.name,
            entity_text=criterion.entity_text,
            domain=criterion.domain,
            logic_type=criterion.logic_type,
            source_text=criterion.source_text or ""
        )
        
        messages = [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            result = self._extract_json(response.content)
            
            if result.get("decompose", False) and result.get("sub_criteria"):
                # An exception is a subtraction from one set, never a second
                # exclusion alongside it. Consulted before the members are built,
                # so a declined split leaves `sub_criteria` empty and this
                # criterion exactly as Agent 1 extracted it, apart from the seed.
                kept = _exception_kept_whole(
                    criterion.name or "",
                    criterion.entity_text or "",
                    criterion.source_text or "",
                    result["sub_criteria"],
                )
                if kept is not None:
                    print(f"  ⊘ '{criterion.entity_text}' → split declined: the line states "
                          f"an entity exception, so it maps whole as {kept!r} "
                          f"(would have been {len(result['sub_criteria'])} sub-criteria: "
                          f"{[sc.get('entity_text') for sc in result['sub_criteria'][:5]]})")
                    criterion.entity_text = kept
                    return criterion

                # Build sub-criteria list
                sub_criteria = []
                for sc_data in result["sub_criteria"]:
                    # REQ-004/REQ-005: a sub-criterion's value_constraint is
                    # determined from its OWN text (the grounding requirement
                    # above), never unconditionally copied from the parent
                    # (decomposer.py:107, pre-fix). REQ-007 fail-open: any
                    # missing field, unparseable phrase, or unexpected error
                    # here leaves value_constraint as None — never the
                    # parent's (possibly wrong) value, never a raised
                    # exception that aborts the whole decomposition.
                    value_constraint = None
                    try:
                        raw_text = sc_data.get("value_constraint_text")
                        if raw_text:
                            value_constraint = parse_value_constraint(raw_text)
                    except Exception as vc_exc:
                        print(f"  ⚠ value_constraint parse failed for "
                              f"{sc_data.get('entity_text', '')!r}: {vc_exc}")
                        value_constraint = None

                    sc = Criteria(
                        name=sc_data.get("name", "Unnamed"),
                        domain=sc_data.get("domain", criterion.domain),
                        entity_text=sc_data.get("entity_text", ""),
                        logic_type=criterion.logic_type,  # Inherit parent's logic
                        window=criterion.window,  # Inherit parent's window
                        # Inherit the parent's protocol line. A sub-criterion is a
                        # reading OF the parent's line, so the line is its provenance
                        # too -- and these members are precisely where a
                        # line-to-criterion cardinality is worth reading, since this
                        # is the hop that turns one line into several criteria.
                        # Leaving it None meant every decomposed member reached the
                        # store carrying no line at all: CAROLINA's stored
                        # "Elevated Bilirubin" and "Coagulopathy (e.g., elevated INR)"
                        # members are this shape, and appear in no recorded Agent 1
                        # cache because the planner, not Agent 1, invented them.
                        #
                        # This carries provenance across the hop and decides nothing:
                        # not what is decomposed, not the prompt, and not the member's
                        # own `value_constraint`, which REQ-004/REQ-005 require be
                        # grounded in the member's OWN text and which is still parsed
                        # from `value_constraint_text` above, never inherited.
                        source_text=criterion.source_text,
                        # Which part of that line this member actually reads -- None
                        # when the line names it nowhere and the member is the model's
                        # own contribution. Verified here rather than believed: see
                        # `_grounded_span`.
                        source_span=_grounded_span(
                            sc_data.get("source_span"),
                            criterion.source_text or "",
                            # Both, because the naming word can live in either: the
                            # line says "Total Bilirubin" while the sub-term is named
                            # "Elevated Bilirubin" and its entity text is "Total
                            # bilirubin elevation".
                            f"{sc_data.get('entity_text', '')} {sc_data.get('name', '')}",
                        ),
                        value_constraint=value_constraint,
                    )
                    sub_criteria.append(sc)

                # One criterion's range torn in half is not a decomposition. Consulted
                # AFTER the members are built because it reads their parsed bounds, and
                # before they are installed, so a declined split leaves this criterion
                # exactly as Agent 1 extracted it -- no members, `group_type` untouched.
                torn = _torn_range_declined(criterion.entity_text or "", sub_criteria)
                if torn is not None:
                    print(f"  ⊘ '{criterion.entity_text}' → split declined: {torn}")
                    return criterion

                criterion.sub_criteria = sub_criteria
                # De Morgan: negating a disjunction distributes as a conjunction.
                # "cardiovascular disease" (PRESENCE) → any sub-term qualifies → ANY.
                # "no drug abuse" (ABSENCE) → alcohol AND opioid AND cannabis must all
                # be absent → ALL. Using ANY here would let one absent sub-term pass the
                # whole exclusion, silently admitting patients the protocol excludes.
                criterion.group_type = "ALL" if criterion.logic_type == "ABSENCE" else "ANY"

                # Say how many members the protocol line named and how many the model
                # supplied. The counts are printed rather than derived later because a
                # run whose every member is elaboration looks, in the store, exactly
                # like a run that read a line naming all of them -- which is the
                # confusion `source_span` exists to end. Naming it in the log too costs
                # one line and makes the elaboration visible while the run is watched,
                # not only afterwards.
                named = sum(1 for sc in sub_criteria if sc.source_span)
                print(f"  ✂ '{criterion.entity_text}' → "
                      f"{len(sub_criteria)} sub-criteria ({criterion.logic_type}"
                      f"/{criterion.group_type}; {named} named by the line, "
                      f"{len(sub_criteria) - named} supplied by the model): "
                      f"{[sc.entity_text for sc in sub_criteria[:5]]}...")
            else:
                print(f"  ✓ '{criterion.entity_text}' → atomic (no decomposition)")
                
        except Exception as e:
            print(f"  ⚠ Decomposition failed for '{criterion.entity_text}': {e}")
            # On failure, keep the original criterion unchanged
        
        return criterion
    
    def _extract_json(self, content: str) -> dict:
        """Extract and parse JSON from LLM response content."""
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            print(f"[Planner] JSON parsing error: {e}")
            return {"decompose": False, "sub_criteria": []}


# Lazy singleton
_planner_instance = None

def get_planner(model_name: str | None = None) -> CriteriaPlanner:
    """Get or create Planner instance (lazy initialization).

    When model_name is provided, returns a fresh instance using that model.
    When model_name is None, returns (or creates) the cached singleton.
    """
    global _planner_instance
    if model_name is not None:
        return CriteriaPlanner(model_name=model_name)
    if _planner_instance is None:
        _planner_instance = CriteriaPlanner()
    return _planner_instance
