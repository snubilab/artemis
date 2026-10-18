"""
Criteria Planner (Agent 1.5) - Clinical Criteria Decomposer.
Decomposes composite clinical criteria into granular, OMOP-searchable sub-criteria.
"""
import json
from collections.abc import Mapping
from typing import Optional, List
from langchain_core.messages import SystemMessage, HumanMessage

from src.utils.llm import get_llm
from src.models.ir import (
    ARTEMISRequest,
    CohortDefinition,
    Criteria,
    ExceptedEntity,
    TemporalWindow,
    ValueConstraint,
)
from src.agents.planner.prompts import PLANNER_SYSTEM_PROMPT, DECOMPOSITION_PROMPT
from src.services.criterion_annotation import (
    FIELD_CARDINALITY,
    FIELD_RELATION,
    FIELD_RELATION_SPAN,
    Relation,
    check_relation,
    declared_group_type,
    span_in_line,
)
from src.utils.span_match import comparison_form


def _grounded_span(claimed: object, source_text: str, sub_term_text: str) -> Optional[str]:
    """The fragment of the protocol line that names this sub-term, or None.

    The prompt ASKS the model to copy the naming fragment verbatim. This function is what
    makes the answer worth anything: the model's own account of where a term came from is
    exactly what cannot be taken on trust, since ``stated: true`` on an invented analyte is
    indistinguishable from the truth. One gate: the span is **really present in the line**,
    under :func:`src.utils.span_match.span_in_line`, the check every other span gets. Not a
    fuzzy match: fuzz is how an invention scores as a reading.

    The second gate this function used to apply -- the span must share a "naming word"
    with the sub-term, read through an English function-word list -- is removed (RFC-016
    §5, inventory A9): it decided meaning from words. Its known cost is accepted: a member
    elaborated FROM an umbrella can cite the umbrella (CAROLINA's ALT sub-term citing
    ``impaired hepatic function``) and is then counted as named by the line. Two
    consequences follow and are deliberate: such a member is not marked as elaboration,
    and a split of two or more such members needs a stated ``relation`` like any other
    (:meth:`CriteriaPlanner._decompose_criterion`).

    Never raises, and never drops a sub-term. A span that fails marks the member as the
    model's own; refusing the member outright would delete a criterion the pipeline exists
    to recover.

    ``sub_term_text`` is kept in the signature for the callers; it is no longer read.
    """
    if not isinstance(claimed, str):
        return None
    span = claimed.strip()
    if not span or span.lower() in {"null", "none", "nil"}:
        return None
    if not span_in_line(span, source_text):
        return None
    return span


def _stated_exceptions(result: object, source_text: str) -> List[ExceptedEntity]:
    """The ``excepted_entities`` the planner stated, keeping each whose span is in the line.

    RFC-016 §3: the meaning is the planner model's, quoted with the fragment of the
    protocol line that names each excepted entity. The only test made here is the one
    every annotation span gets -- that the fragment is a substring of the line. An entry
    whose span is not there is dropped: subtracting on the model's own word creates a new
    wrong exclusion, which is the failure the exception machinery exists to prevent.

    :param result: the planner's parsed JSON answer.
    :param source_text: the verbatim protocol line.
    :returns: the verified entries, in the planner's order; empty when none verified.
    """
    entries = result.get("excepted_entities") if isinstance(result, dict) else None
    if not isinstance(entries, list):
        return []
    kept: List[ExceptedEntity] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text, span = entry.get("text"), entry.get("span")
        if isinstance(text, str) and text.strip() and span_in_line(span, source_text):
            kept.append(ExceptedEntity(text=text.strip(), span=span))
    return kept


def stated_member_value_constraint(sc_data: object, source_text: str) -> Optional[ValueConstraint]:
    """A member's threshold as the planner stated it, kept only when its fragment is in the line.

    The planner returns the threshold twice: ``value_constraint_text``, the fragment of
    Source Text that states it, and ``value_constraint``, its structure (``op``, ``value``,
    ``unit_text``, ``reference_bound``). The structure is machine format, validated by the
    IR model; the fragment is checked as a substring of the line (:func:`span_in_line`,
    the annotation step's own check). Until RFC-016 step 3 the fragment was parsed with
    English comparator spellings (``parse_value_constraint``, A5a) instead.

    REQ-007 fail-open: a missing or rejected fragment, a missing structure, or one the IR
    model refuses gives None -- never the parent's value and never an exception.

    :param sc_data: one entry of the planner's ``sub_criteria``.
    :param source_text: the parent criterion's protocol line.
    :returns: the member's own constraint, or None.
    """
    if not isinstance(sc_data, Mapping):
        return None
    payload = sc_data.get("value_constraint")
    if not isinstance(payload, Mapping) or not span_in_line(
        sc_data.get("value_constraint_text"), source_text
    ):
        return None
    try:
        return ValueConstraint.model_validate(
            {key: value for key, value in payload.items() if value is not None}
        )
    except (ValueError, TypeError):
        return None


#: Days per UCUM time unit, keyed by the unit's OMOP concept id (hour, week, month, year) --
#: the ids `value_constraint.normalize_unit` resolves to; no unit word is read here.
#: shortcut: day and minute are absent because normalize_unit resolves neither; such a bound
#: stays a value filter (and stays refused, visibly) until the unit table resolves them.
_DAYS_PER_TIME_UNIT = {8505: 1 / 24, 8511: 7, 9580: 30, 9448: 365}


def duration_held_by_window(vc: Optional[ValueConstraint], window: Optional[TemporalWindow]) -> bool:
    """Whether ``vc`` is a duration that ``window`` already states, so it is no value filter.

    A planner member inherits its parent's window, which Agent 1 set from the line's time
    phrase; the planner then often restates that phrase as the member's own
    ``value_constraint`` ("within the past two years" -> eq 2 years), which no occurrence
    table can read (unreadable-value-filter). It is dropped only when its unit is a time unit
    (by UCUM concept id) AND the window spans the same time, within 5% (a month is 30 days
    in the window, 30.4 in the calendar).

    :param vc: the member's stated constraint.
    :param window: the window the member inherits.
    """
    from src.services.value_constraint import normalize_unit

    if vc is None or window is None or vc.value is None:
        return False
    days = _DAYS_PER_TIME_UNIT.get(vc.unit_concept_id or normalize_unit(vc.unit_text))
    if days is None:
        return False
    span = float(vc.value) * days
    return abs(abs(window.start - window.end) - span) <= 0.05 * span + 1


def _member_is_stated_exception(excepted: List[ExceptedEntity], members: list) -> bool:
    """Whether a member the planner proposed IS one of the entities the line excepts.

    A protocol line that names a set and carves part of it out states ONE criterion.
    Decomposing it into the base and the carve-out makes two members that Circe then
    AND-combines: EMPA-REG's delivered rule 17 is "zero cancers AND zero basal cell
    carcinomas", which removes exactly the patient whose only malignancy is the excepted
    one. When a member equals an excepted entity (whitespace and case folded) the split is
    declined and the exception travels as the criterion's ``excepted_entities`` instead.

    LEADER's insulin line excepts three insulins and its members are "insulin other than
    X" -- none equals an excepted entity -- so that split is a reading and survives.
    """
    forms = {comparison_form(entity.text) for entity in excepted}
    return any(
        comparison_form(str(member.get("name") or "")) in forms
        or comparison_form(str(member.get("entity_text") or "")) in forms
        for member in members
        if isinstance(member, dict)
    )


#: Bounds that state ONE side of a range. `bt` is deliberately absent -- it is a whole
#: band and states both sides -- and so is None, which is no bound at all. A member can
#: rarely carry `bt` (it was never produced while the member's threshold was a parsed
#: phrase, and now the planner states it), so a member's bound is mostly one-sided or
#: absent. It is listed as excluded anyway, because the check below must keep meaning what
#: it says.
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

    1. **Every member names the parent's own entity**, under :func:`comparison_form`.
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
        including the None that :func:`stated_member_value_constraint` fail-open
        produces. Checked after construction rather than off the raw payload for that
        reason: what matters is what the member ends up carrying.
    :returns: the reason to record, or None to leave the split alone.
    """
    parent = comparison_form(entity_text or "")
    if not parent or not members:
        # Without the parent's own analyte there is nothing to compare a member to,
        # and declining on that would refuse every split. The safe direction here is
        # to let the split through: it is what happens today.
        return None
    units: set[str] = set()
    for member in members:
        if comparison_form(member.entity_text or "") != parent:
            return None
        vc = member.value_constraint
        if vc is None or vc.op not in _ONE_SIDED_OPS:
            return None
        units.add(comparison_form(vc.unit_text or ""))
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
        
        # A failure must leave the criterion exactly as Agent 1 extracted it, and the body
        # below writes to it as it goes (the stated exceptions before the members are
        # built), so the failure path returns this copy rather than the half-written one.
        extracted = criterion.model_copy(deep=True)
        try:
            response = self.llm.invoke(messages)
            result = self._extract_json(response.content)

            # RFC-016 §3: the entities the line removes from this criterion's set, as the
            # planner stated them, each span checked against the line. Recorded whatever
            # the decomposition decides; the annotation step fills the row only when
            # this is empty.
            excepted = _stated_exceptions(result, criterion.source_text or "")
            if excepted:
                criterion.excepted_entities = excepted

            if result.get("decompose", False) and result.get("sub_criteria"):
                # An exception is a subtraction from one set, never a second
                # exclusion alongside it. Consulted before the members are built,
                # so a declined split leaves `sub_criteria` empty and this
                # criterion exactly as Agent 1 extracted it.
                if excepted and _member_is_stated_exception(excepted, result["sub_criteria"]):
                    print(f"  ⊘ '{criterion.entity_text}' → split declined: a proposed member "
                          f"is a stated exception {[e.text for e in excepted]}, so it maps "
                          f"whole with that subtracted "
                          f"(would have been {len(result['sub_criteria'])} sub-criteria: "
                          f"{[sc.get('entity_text') for sc in result['sub_criteria'][:5]]})")
                    return criterion

                # Build sub-criteria list
                sub_criteria = []
                for sc_data in result["sub_criteria"]:
                    # REQ-004/REQ-005: a sub-criterion's value_constraint is
                    # its OWN, as the planner stated it with a fragment of the
                    # line, never copied from the parent. REQ-007 fail-open: a
                    # missing or unverified answer leaves it None.
                    value_constraint = stated_member_value_constraint(
                        sc_data, criterion.source_text or ""
                    )
                    if duration_held_by_window(value_constraint, criterion.window):
                        value_constraint = None  # the inherited window already states it

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
                        # the member's OWN (`stated_member_value_constraint` above),
                        # never inherited.
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

                # RFC-016 step 2 (RFC-014 §2-1). How the line combines the members is the
                # model's reading, kept only when its span is in the line. A line that names
                # two or more of the members and states no verified relation is declined, like
                # a torn range: the group type would otherwise be guessed from the logic alone,
                # which is how CAROLINA's "T2DM and concurrently ... and ..." became ANY. A
                # split whose members the line does not name is an umbrella's elaboration and
                # reads as `any`.
                relation, _ = check_relation(result, criterion.source_text or "")
                named = sum(1 for sc in sub_criteria if sc.source_span)
                if relation[FIELD_RELATION] is None and named >= 2:
                    print(f"  ⊘ '{criterion.entity_text}' → split declined: the line names "
                          f"{named} of {len(sub_criteria)} members and states no verified "
                          f"relation (relation={result.get(FIELD_RELATION)!r}, "
                          f"relation_span={result.get(FIELD_RELATION_SPAN)!r})")
                    return criterion

                criterion.sub_criteria = sub_criteria
                criterion.group_type = declared_group_type(
                    criterion.logic_type,
                    relation[FIELD_RELATION] or Relation.ANY.value,
                    relation[FIELD_CARDINALITY],
                )
                criterion.relation = relation[FIELD_RELATION]
                criterion.relation_span = relation[FIELD_RELATION_SPAN]
                criterion.cardinality = relation[FIELD_CARDINALITY]

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
            # This criterion's failure, not the trial's: it stays undecomposed with the
            # reason on it, and every other criterion is planned. Swallowed silently it
            # read as "atomic"; raised out of plan() it discarded every other criterion's
            # decomposition with it.
            reason = " ".join(f"{type(e).__name__}: {e}".split())
            reason = reason[:300] + " ..." if len(reason) > 300 else reason
            print(f"[Planner] Decomposition failed for {criterion.entity_text!r}: {reason}")
            return extracted.model_copy(update={"planning_failure": reason})
        
        return criterion
    
    def _extract_json(self, content: str) -> dict:
        """Extract and parse JSON from LLM response content."""
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        # A reply that does not parse is a failed call. Read as {"decompose": false} it
        # turned a decomposition cut off mid-item into "atomic", printed with a check mark.
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse planner response as JSON: {e}") from e


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
