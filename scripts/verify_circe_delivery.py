#!/usr/bin/env python
"""Delivery gate for an existing per-arm CIRCE export directory.

Run this against a directory produced by ``export_seeded_cohorts.py`` (or any
other directory of ``*.circe.json`` files) before anything in it is sent to a
site. It never writes or fixes anything — it only checks and reports.

Checks per file:

(a) zero no-op exclusion rules (see ``src.utils.circe_lint.noop_exclusion_rules``)
(b) the file's InclusionRules names equal the store study's rule names as a
    multiset, allowing at most one extra rule (the appended arm drug rule).
    The store side is first reconciled against the file's own ``_droppedCriteria``
    records: the emission-time repair removes a criterion whose value filter its CDM
    table cannot read, which either removes its rule outright or rewrites the rule's
    name from the members that survived, while the store keeps the pre-drop text. So
    a repaired export diverged from its own store on 8 of 12 files. A drop is
    forgiven only to the exact extent a record explains it — an unrecorded missing
    rule still fails, and so does a record naming a rule the store does not carry or
    a (criteria type, attribute) pair that is not actually unreadable.
(c) the file's PrimaryCriteria entry concept ids equal the store study's
    entry set, OR — for a comparator — the entry may legitimately be either
    a disease-anchored ``ConditionOccurrence`` set (the placebo-comparator
    design) or a ``DrugEra`` set naming the study's own second treatment arm
    (the active-comparator design, e.g. CAROLINA's comparator is legitimately
    "glimepiride", not linagliptin)
(d) if a ``manifest.json`` sits beside the files, its recorded md5s match the
    files on disk and its ``store_sha256`` matches the ``--store`` file
(h) a disease-anchored comparator entry is the trial's OWN registered condition.
    Check (c) accepts ANY ``ConditionOccurrence`` entry on a comparator, because the
    swap itself is legitimate -- so it passed LEADER's comparator entering on
    ``LV systolic or diastolic dysfunction`` (one of several alternative
    cardiovascular-risk qualifiers) instead of type 2 diabetes, which is a fraction of
    the trial population. The expected anchor comes from
    ``src.utils.disease_anchor.expected_anchor_concept_ids``, the same function the
    generator chooses with, against ``trialMetadata.conditions``. A study with no
    registered condition FAILS rather than passing unchecked -- backfill it with
    ``scripts/backfill_registered_conditions.py``.

(g) every criterion's concept set shares at least one OMOP domain with the CDM
    table that criterion reads. A ``ConditionOccurrence`` criterion over a Drug
    concept set joins ``condition_occurrence.condition_concept_id`` against drug
    products and matches nothing; as an ABSENCE rule that means everyone
    satisfies it and the exclusion is never applied. CAROLINA shipped that shape
    ("Glimepiride", codeset 56) and passed checks (a) to (f), because none of
    them reads a criterion's domain against its own concept set. Measured
    against WebAPI rather than reasoned — see
    ``src.utils.circe_lint.domain_mismatched_criteria`` and
    ``output/site_gap/2026-09-06/plan048_domain_repair/``.

(i) the file's own criterion accounting — ``_generationCensus``,
    ``_unmappedCriteria``, ``_skippedCriteria`` — balances and records no loss.
    The generator has always written these three keys into the delivered payload
    and nothing read them: ``rg -c _unmappedCriteria`` over this script and
    ``export_seeded_cohorts.py`` exited 1. So
    ``output/anchor_after/aristotle_comparator.circe.json`` shipped with two
    protocol exclusions recorded as unmapped ("Aspirin and thienopyridine
    combination", "Investigational drug use") and this gate printed PASS. Check
    (b) structurally cannot catch it: it compares the file's rule names against
    the store ``structuredExpression`` produced by the SAME generation, so both
    sides are missing the same criteria and the multiset matches.
    See ``criterion_accounting`` below for the failure condition and for why
    ``skipped > 0`` is not one. A recorded skip is a permit, not a verdict: each
    one under an allowed reason is re-derived here from the store criterion it
    names and from the delivered file — a ``group-label`` row must be a group label
    whose threshold strands no member and at least one of whose members emitted, a
    ``demographic-no-rule`` row must be demographic-domain and carry no bound, and a
    restated-* row must have a collapse record naming a survivor that emitted. An
    ``_unmappedCriteria`` row is permitted only when its ``refusalCode`` says the loss
    is IRREDUCIBLE — see ``PERMITTED_REFUSAL_CODES`` for the axis and for why the
    reason prose cannot carry it — and one carrying no reason, no code, or an unknown
    code fails on its own line.

(j) no ``Measurement`` criterion carries no value condition while its own concept-set
    name or rule name asserts one. Every check above reads a criterion that is PRESENT
    and asks whether it is wrong; a rule that LOST its threshold is byte-identical to
    one that legitimately never had a threshold, so none of them could see it. Measured
    in ``carolina_treatment.circe.json``: rule 30 keeps its "3x ULN" as a
    ``RangeHighRatio`` while rules 33 and 37 emit bare, and rule 37 then excludes any
    patient who has ever had an ALT, AST, bilirubin or INR drawn — routine panel labs.
    The file was reported as "78 mapped, 0 unmapped": the bare members were counted as
    mapped. 26 such criteria in this batch, and 4 more in the hand-built TROY v1.1 gold
    under ``data/gold/``, which carries the same defect on ARISTOTLE's
    "systolic BP > 180 mm Hg" exclusion. See
    ``src.utils.circe_lint.asserted_bound_missing_criteria``.

(k) the STORE study's repair ledger (``eligibility._repairAccounting``) reconciles
    against the store's own criteria. Every check above reconciles the delivered file
    against the store, and the store's criteria rows are written AFTER Agent 1's
    post-parse repairs run -- so a criterion a repair removed is on NEITHER side of any
    of them, and ``total``, ``mappable``, the residual identity and the store anchor all
    balance exactly while it is gone. Measured: CAROLINA's inclusion criteria fell 52 ->
    32 between the 2026-09-11 and 2026-09-12 stores, six of them the drug-therapy rows
    18-23, and the 2026-09-13 delivery still reported "84 of 84 store criteria accounted
    for" on both CAROLINA arms. A ``demotion`` record claims its criterion is still in
    the tree, so one naming a criterion the store does not carry is a departure nothing
    recorded, and it fails. A ``departure`` is counted and not judged on presence -- a
    band merge's survivor legitimately keeps a departed half's name, 5 such rows in that
    store. See ``repair_ledger_violations``.

(l) no ``Measurement`` criterion is an ABSENCE carrying no value condition at all.
    Check (j) reads a NAME that promised a bound and finds it gone; this one reads what
    the emitted rule SELECTS without one. ``Occurrence {Type: 0, Count: 0}`` over a lab
    with no result filter excludes every patient who has ever had the test — not those
    whose result crossed a threshold. PLATO's InclusionRule 18 'Thrombocytopenia'
    (codeset 33 → three platelet-count LOINC concepts, no value condition) shipped in
    every delivery from 2026-09-10 to 2026-09-14 with all seven lints green on it,
    because neither its rule name nor its concept-set name asserts a bound: the name is
    a diagnosis, and a diagnosis needs no threshold. For scale, and not measured by this
    gate: the site-gap fixture run that motivated the check reports it removing 63.1% /
    56.3% / 38.7% of each site's population. The hand-built TROY v1.1 gold carries the
    same defect on ARISTOTLE's SBP/DBP under "systolic BP > 180 mm Hg".
    See ``src.utils.circe_lint.unfiltered_measurement_absence_criteria``.

(m) no two concept sets in one file hold byte-identical members under different
    names. Pure set comparison -- no vocabulary, no database. Two names over one member
    set mean either that a name says more than its members do, or that one criterion was
    mapped twice; nothing in the file can make them mean anything else. Measured on
    ``leader_{treatment,comparator}.circe.json``: codeset 12 ``'human NPH insulin'``,
    codeset 54 ``'insulin other than human NPH insulin'`` and codeset 56
    ``'insulin other than premixed insulin'`` are the same 26 concept ids, so the
    exclusion set IS the inclusion set and the delivered cohort excludes patients for
    taking the insulins ``InclusionRules[2]`` requires them to be on. The ``other than``
    qualifier is not lost on the way in -- the store's ``_criterionMappingMetadata``
    records ``queryUsed`` verbatim -- it is simply never read. ARISTOTLE
    (``'Aspirin and thienopyridine use'`` holding aspirin alone) and EMPA-REG (one
    ``eGFR < 30`` criterion emitted as two rules under two names) also fire, and both
    are real. See ``src.utils.circe_lint.aliased_concept_sets`` for the measured cost on
    the hand-built gold, and for why no name test separates a synonym pair from a
    dropped negation.

(n) no mandatory presence and mandatory absence sit over the same -- or a
    member-identical -- concept set in overlapping windows. CIRCE conjoins every
    ``InclusionRules`` entry, so the list is one implicit ``ALL`` and the pair is empty
    by construction whether it spans one rule or two. Check (f) is the near miss: it
    tests an absence against the cohort's own ENTRY set, and LEADER's codesets
    10/11/12/13/54/56 are none of them, which is how four such pairs shipped with every
    other lint green. Measured on both LEADER arms: ``InclusionRules[2]`` demands zero
    exposures to codeset 10 and at least one to the identical codeset 11 (an OR emitted
    as ``Type: ALL``), ``InclusionRules[3]`` repeats it, and ``InclusionRules[24]``
    demands zero exposures to codesets 54 and 56 against ``InclusionRules[2]``'s demand
    for codeset 12 -- the dropped negation. Two different defects, one signature, which
    is why the check reads structure rather than names. See
    ``src.utils.circe_lint.contradictory_presence_absence_criteria``.

(o) no rule is emitted as a conjunction over alternatives its protocol line states
    as a disjunction. Reads the emitted ``Type`` and the store group's own
    ``protocolLine``; no database, no vocabulary. The connective alone is NOT the
    signal -- 33 of the 82 groups in the six-trial store declare ``ALL`` under a line
    stating a disjunction and 31 of those are correct all-ABSENCE exclusions, where
    ``ALL`` IS the De Morgan reading -- so the check fires only when the rule's
    criteria are not all absences. Measured on the twelve delivered files: LEADER
    ``InclusionRules[2]``, both arms, and nothing else. Check (n) catches that rule
    too, but only because codesets 10 and 11 happen to be byte-identical; a conjoined
    disjunction over sets that merely differ is invisible to every other check here.
    See ``src.utils.circe_lint.conjoined_disjunction_rules``.

(q) no criterion bounds a value numerically while naming no unit, on any CDM table
    that would read one — ``Measurement`` and ``Observation``, derived as the types
    reading both ``ValueAsNumber`` and ``Unit``. The
    pipeline already REFUSES a criterion whose unit string resolves to no UCUM concept
    (``unstated-unit-bound``), and that refusal's own recorded reason says why: the
    bound "would be emitted as a bare number and compared against whatever scale the
    CDM stores". A criterion that stated no unit at all produces the identical bare
    number and was not refused — so the safe case was punished and the dangerous one
    shipped. Measured over the 92 ``Measurement`` leaves in this batch: 40 carry
    ``ValueAsNumber`` + ``Unit``, 32 carry ``RangeHighRatio``, 10 carry no value
    condition, and 10 carry ``ValueAsNumber`` with no ``Unit``. Those 10 are five
    concept sets on both LEADER arms — codesets 9 ``'eGFR'``, 17
    ``'Glycated hemoglobin'``, 18 ``'Hemoglobin A1c'``, 33 ``'Calcitonin'``, and 6
    ``'Ankle-brachial index'``, which is allowlisted. HbA1c is the harm and it is
    INVERTED rather than empty: 7.0% is 53 mmol/mol, so a bare ``>= 7.0`` against a
    site storing IFCC units passes essentially every patient. The ambiguity is internal
    to the file — codesets 17 and 18 each hold both ``4197971 HbA1c measurement (DCCT
    aligned)`` (%) and ``44793001 Hb A1c ... IFCC`` (mmol/mol) — and this same batch
    attaches ``%`` to HbA1c on CARMELINA, CAROLINA and EMPA-REG and
    ``mL/min/1.73m2`` to eGFR on CAROLINA and EMPA-REG, so LEADER's are missing rather
    than dimensionless. ``Observation`` carries the same defect on four more leaves,
    on two other trials: CARMELINA codeset 32 ``'Life expectancy'`` ``lt 5.0`` and
    CAROLINA codeset 22 ``'Systolic blood pressure'`` ``gt 140.0``, both arms each.
    CAROLINA's own codeset 44 ``'life expectancy less than 5 years for'`` carries
    ``Unit`` year over the SAME member concept ``4050791 FH: Longevity``, so one file
    in this delivery states the unit and another omits it for the identical concept —
    and "life expectancy < 5" read as months rather than years is a twelve-fold error.
    ``RangeHighRatio`` leaves are not flagged: a ratio bound is a
    multiple of the lab's own ``range_high``, so its units cancel, and all 32 carry no
    ``ValueAsNumber``. Ankle-brachial index is exempt by concept id — it is a quotient
    of two mmHg pressures, so a unit filter on it would be wrong rather than missing.
    See ``src.utils.circe_lint.unitless_value_bound_criteria`` and the allowlist
    ``DIMENSIONLESS_VALUE_CONCEPTS`` beside it, whose comment records how it was
    derived from the corpus and which three ratio-looking candidates were rejected.

(r) no concept set holds a concept that is not the analyte its own name states. Check
    (q) and everything beside it ask whether a numeric bound is on the right SCALE; this
    one asks whether it is on the right QUANTITY, and a unit cannot repair it: 'LDL
    cholesterol >= 135 mg/dL' applied to an HDL result is wrong in mg/dL, and because a
    high HDL is protective while a high LDL is the risk being selected on, it selects the
    OPPOSITE patients rather than merely the wrong number. Check (m) is the nearest
    existing check and structurally cannot reach it: it fires when TWO sets hold
    identical members under two names, and here ONE set holds members its single name
    contradicts. Measured by resolving every concept set in the six
    ``deliveries/2026-09-12/`` files and the six
    ``output/site_gap/2026-09-18_verify/DELIVERY/`` files against ``omop_vocab.concept``
    and reading each against its own name -- three pairs, all three present in BOTH
    corpora: CAROLINA codeset 30 ``'LDL cholesterol'`` holds ``3007070 Cholesterol in HDL
    [Mass/volume]``; EMPA-REG codesets 3 and 4 ``'Glycosylated haemoglobin (HbA1c)'`` hold
    ``3005446 Hemoglobin A1/Hemoglobin.total``, which includes HbA1a and HbA1b and so
    reads higher than HbA1c, meaning the delivered ``<= 10.0%`` excludes patients who
    satisfy it; CAROLINA codeset 28 ``'Systolic blood pressure'`` holds ``40758413 Blood
    pressure systolic and diastolic``, a panel over two quantities. Nothing repairs any of
    them: every export-time repair in this pipeline changes how a criterion is COMPARED,
    while dropping HDL from an LDL set changes which patients the cohort SELECTS, so it is
    a mapping correction and this gate refuses instead. ``isExcluded`` members are skipped
    -- an exclusion removes the concept, so the bound never reaches it. This is the one
    check here that reads a concept-set NAME, and deliberately: the name is the claim
    under test, so it cannot be replaced by a concept id the way
    ``DIMENSIONLESS_VALUE_CONCEPTS`` is. What the free-text problem costs instead is the
    shape of the match -- every spelling the corpus supplies, plus an escape for a name
    claiming both analytes ('LDL/HDL ratio' legitimately holds HDL). See
    ``src.utils.circe_lint.confusable_concept_sets`` and the table
    ``CONFUSABLE_ANALYTES`` beside it.

(s) no inclusion rule requires at least one occurrence of criteria that are EVERY ONE of
    them forbidden outright by a mandatory zero-occurrence criterion elsewhere in the
    file. CIRCE conjoins every ``InclusionRules`` entry, so such a rule selects nobody on
    any CDM with any data, and no ETL or vocabulary can change that. Criteria are matched
    on what they SELECT -- concept-set members, domain, value bound, unit list, window --
    never on ``CodesetId``, which is what makes it see past four different codeset ids
    holding the identical members. Checks (m) and (n) are the near misses and both return
    nothing on the motivating file: (m) needs identical members under DIFFERENT names and
    all four sets are named ``'HbA1c'``; (n) drops an absence that carries a value bound
    and does not descend a top-level ``ANY``, and the shipped rules are both. Measured on
    ``deliveries/2026-09-12/``: ``carmelina_comparator`` and ``carmelina_treatment``,
    ``InclusionRules[11]`` ``'HbA1c at least 6.5% + HbA1c at most 10.0%'``, whose two
    disjuncts are forbidden verbatim by ``InclusionRules[12]``'s two absences -- and the
    hospital's own per-rule counts corroborate it, the two rules summing to the entry
    count exactly in all four measured arms. Zero on the other 22 delivered files, zero on
    the six ``output/site_gap/2026-09-18_verify4/DELIVERY/`` files and zero on the 18
    hand-built TROY v1.1 files under ``data/gold/``. See
    ``src.utils.circe_lint.unsatisfiable_presence_rules``, and
    ``bound_contradicted_presence_criteria`` beside it for the weaker not-provably-empty
    shape this one deliberately does not report.

And one check across files rather than per file:

(f) no rule requires zero occurrences of a concept set that intersects the
    cohort's own entry set. Such a rule empties the cohort by construction, and
    every other per-file check reads one property in isolation, so none of them
    can see it. CARMELINA shipped that shape and passed.

(e) every arm a mapped study declares in the store produced a file. Checks (a)
    to (d) all read a file that exists, so a delivery that is SHORT an arm
    passes all of them -- which is what happened on 2026-09-05, when a five-file
    export with a silently dropped EMPA-REG comparator exited 0. Only studies
    that produced at least one file are checked, so a deliberate single-study
    export still passes; the expected arm set comes from the store's own
    ``treatmentArms``, so a genuinely single-arm study needs no opt-out.

The 2026-08-31 delivery (``artemis/output/circe_be/2026-08-31/``) is the
counterexample this gate exists to catch — see ``AGENTS.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.agent1.repair_accounting import (  # noqa: E402
    DISPOSITION_DEMOTION,
    KNOWN_DISPOSITIONS,
    REPAIR_ACCOUNTING_KEY,
)
from src.services.restated_demographics import (  # noqa: E402
    COLLAPSE_REASON as RESTATED_DEMOGRAPHICS_REASON,
)
from src.services.restated_distinctness import (  # noqa: E402
    COLLAPSE_REASON as RESTATED_DISTINCTNESS_REASON,
)
from src.services.restated_distinctness import distinctness_key  # noqa: E402
from src.services.value_constraint import (  # noqa: E402
    STRANDED_GROUP_CONSTRAINT_REASON,
    resolve_group_member_constraint,
)
from src.utils.circe_lint import (  # noqa: E402
    CRITERION_CONCEPT_SET_REFS_KEY,
    DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE,
    DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN,
    DEFAULTED_WINDOW_CRITERIA_KEY,
    DROP_OUTCOME_RULE_KEPT,
    DROP_OUTCOME_RULE_REMOVED,
    DROP_OUTCOME_RULE_RENAMED,
    DROPPED_CRITERIA_KEY,
    aliased_concept_sets,
    asserted_bound_missing_criteria,
    confusable_concept_sets,
    conjoined_disjunction_rules,
    contradictory_absence_rules,
    contradictory_presence_absence_criteria,
    domain_mismatched_criteria,
    entry_concept_ids,
    entry_concept_set_name,
    entry_matches_expected,
    missing_arm_roles,
    noop_exclusion_rules,
    rule_names,
    unfiltered_measurement_absence_criteria,
    ungrounded_criteria,
    unitless_value_bound_criteria,
    unreadable_value_attributes,
    unsatisfiable_presence_rules,
)
from src.utils.criterion_refusal import (  # noqa: E402
    REFUSAL_CODES,
    REFUSAL_UNMAPPABLE_PLACEHOLDER,
)
from src.utils.criterion_seed import MISSING_ENTITY_CRITERIA_KEY  # noqa: E402
from src.utils.delivery_mode import (  # noqa: E402
    DeliveryModeConflictError,
    resolve_drug_anchored_entry,
)
from src.utils.disease_anchor import DiseaseAnchorError, expected_anchor_concept_ids
from src.utils.store_resolution import StoreMismatchError, resolve_store_path  # noqa: E402

DEFAULT_MAP = "carmelina=9,empa-reg=8,carolina=10,aristotle=3,plato=2,leader=1"

#: The three keys ``TTEService._build_seeded_target_circe`` writes together to
#: account for every criterion that did not become a rule. Emitted as a set —
#: present-and-empty rather than absent — so a partial set means something removed
#: one after generation, which is checked separately from an artifact that carries
#: none of them because it predates the accounting.
ACCOUNTING_KEYS = ("_generationCensus", "_unmappedCriteria", "_skippedCriteria")

#: Skip reasons that are NOT criterion loss, so a delivery carrying them still
#: ships. Derived from what this tree's own exported artifacts contain — the 108
#: ``*.circe.json`` under ``output/`` that carry the records, of 151 present — one
#: entry per reason actually observed there:
#:
#: * ``group-label`` (1046 rows) — a container row. Its members map and emit as one
#:   grouped inclusion rule; the label itself never carried a concept set. Every
#:   observed row has ``isGroupLabel: true``.
#: * ``demographic-no-rule`` (106 rows) — a Demographics row with no single usable
#:   ``valueConstraint`` ("Age and Sex", "Age >= 50 with prior CVD",
#:   "Age (region-conditional)"). The components emit on their own.
#: * the two collapse reasons (458 rows) — a restatement deliberately dropped onto
#:   its retained sibling, which does emit. Both are recorded a second time under
#:   ``_restatedDemographicsCollapse`` / ``_restatedDistinctnessCollapse``.
#:
#: The two collapse spellings are imported from the modules that own them rather
#: than retyped; the other two are bare literals in ``tte_service.py`` with no
#: owning constant, so they are spelled here. That is safe in one direction only,
#: and it is the right one: this is a PERMIT list, so any drift — a renamed reason,
#: a typo here, a new silent branch — leaves the reason unrecognised and FAILS the
#: delivery rather than quietly passing it.
#:
#: Each entry is a PERMIT that :func:`skipped_criteria_violations` re-judges against
#: the store criterion and the delivered file — it is not a verdict the record gets to
#: assert about itself. ``group-label`` is re-judged as: the store row is actually a
#: group label, its own threshold is not one ``resolve_group_member_constraint``
#: refuses to hand down, and at least one member of its group emitted.
#: ``demographic-no-rule`` as: the store row is demographic-domain and carries no
#: numeric bound. The two restated-* reasons as: the file carries a collapse record
#: naming the criterion as dropped, whose survivor exists in the store and was not
#: itself lost. A record the gate cannot re-judge — one naming a criterion absent
#: from the store, or a collapse list absent from the file — fails closed.
#:
#: ``STRANDED_GROUP_CONSTRAINT_REASON`` is deliberately absent. It records a group
#: label whose absolute threshold reached no member, so the members emit
#: unconstrained and the exclusion is not what the protocol wrote. It occurs in the
#: real 2026-09-08 batch (CAROLINA exclusion 44 and EMPA-REG exclusion 56,
#: "Glucose"), where the file then emits the three members as UNFILTERED absence
#: criteria — measured in ``carolina_treatment``: rule 36 excludes any glucose
#: measurement of any value in the last 180 days while inclusion rule 5 REQUIRES an
#: HbA1c in the same window, and the two codesets overlap on 4 of 6 presence
#: concepts. So the emitted shape over-excludes rather than under-excludes, and
#: check (f) cannot see it because it tests absence against the ENTRY set only.
#: Keeping the reason off this list is what makes the re-judgement above load-bearing:
#: a producer that stopped recording it and wrote plain ``group-label`` instead would
#: otherwise launder four real losses straight through the permit.
#: ``exclusion-demographic-eq-unsupported`` is absent for the same reason — it drops
#: an exclusion age bound CIRCE cannot invert, which is a lost bound.
ALLOWED_SKIP_REASONS = frozenset(
    {
        "group-label",
        "demographic-no-rule",
        RESTATED_DEMOGRAPHICS_REASON,
        RESTATED_DISTINCTNESS_REASON,
    }
)


#: The ``refusalCode`` values an ``_unmappedCriteria`` row may carry and still ship.
#:
#: The axis is NOT "was the refusal deliberate". Every code in
#: :data:`~src.utils.criterion_refusal.REFUSAL_CODES` is deliberate — that is what the
#: class exists to say — and permitting on deliberateness would permit every recorded
#: loss in the batch. The axis is **"is this loss irreducible given a correct
#: pipeline?"**, and on that axis the codes split cleanly except for one:
#:
#: * ``unmappable-placeholder`` — irreducible. The seed names no clinical entity, so no
#:   vocabulary can hold it and no better mapper can find it. Verbatim from the
#:   2026-09-08 batch: LEADER inclusion 27 "Risk factor 1" (a numbered placeholder whose
#:   content is elsewhere in the protocol), PLATO inclusion 21 "Table II criteria" (a
#:   pointer into the source document), PLATO inclusion 29 "Preexisting Conditions
#:   Count" (a count, not an entity), EMPA-REG exclusion 32 bare "Contraindication"
#:   (names no substance).
#: * ``no-concept-mapping`` — NOT permitted, and the reason the split above had to be
#:   made at the producer. It is the code every row in that table carries TODAY, and it
#:   is also what PLATO exclusion 16 "Contraindication to clopidogrel" and ARISTOTLE
#:   exclusion 26 "Aspirin and thienopyridine combination" will carry — and those name
#:   real substances a better mapper finds. One code, two opposite verdicts.
#: * ``intent-unparsed`` — NOT permitted. The seed still carries a temporal qualifier
#:   ("... within 3 years") that belongs in the criterion's ``window``; the refusal is
#:   correct and the defect is fixable upstream at extraction. Permitting it would hide
#:   the four real CARMELINA losses (inclusion 10/11/13, exclusion 13).
#: * ``empty-seed``, ``empty-concept-set``, ``stranded-group-threshold``,
#:   ``domain-contradiction``, ``unreadable-value-filter`` — NOT permitted. Each names a
#:   defect with a repair: a criterion that reached the mapper with no text, a search
#:   that answered with nothing, a threshold that did not survive its group label, a
#:   mapping from the wrong domain, a filter the CDM table cannot read.
#:
#: A row whose ``refusalCode`` is absent or ``None`` is NEVER permitted, and that is the
#: load-bearing default rather than a formality: ``None`` means nothing deliberately
#: refused, which is the ``str(e) == ""`` defect — a five-second Stage 1 search timeout
#: booked as a mapping verdict (ARISTOTLE 26/27, PLATO 16 in the 2026-09-08 batch).
#:
#: The alternative considered and REJECTED was a gate-side heuristic over the seed text
#: ("does this look like a placeholder?"). It would live in the gate, guess about
#: English, and silently permit a real loss the day its seed happened to read
#: placeholder-shaped — the exact failure shape ``docs/mistakes.md`` records. The
#: decision belongs where the evidence is, so it is made at the raise site and this list
#: applies no judgement of its own.
PERMITTED_REFUSAL_CODES = frozenset({REFUSAL_UNMAPPABLE_PLACEHOLDER})


#: The three outcomes a drop record may claim for the rule its criterion sat in.
#: Imported from the producer rather than retyped, for the same reason the two
#: collapse reasons above are.
DROP_OUTCOMES = frozenset(
    {DROP_OUTCOME_RULE_REMOVED, DROP_OUTCOME_RULE_RENAMED, DROP_OUTCOME_RULE_KEPT}
)


#: Where the second record of a collapse lives, per collapse reason. The reasons are
#: the producer's own constants; the two KEY spellings are not — no module owns them,
#: they are literals in ``TTEService._build_seeded_target_circe``. That asymmetry is
#: safe in one direction only and it is this one: a misspelling here finds no list and
#: the skip FAILS as unreconcilable rather than passing unchecked.
COLLAPSE_RECORD_KEYS = {
    RESTATED_DISTINCTNESS_REASON: "_restatedDistinctnessCollapse",
    RESTATED_DEMOGRAPHICS_REASON: "_restatedDemographicsCollapse",
}


# ``CRITERION_CONCEPT_SET_REFS_KEY`` is imported from ``src.utils.circe_lint`` above,
# which is also where ``_build_seeded_target_circe`` takes it from. What it holds, and
# why this gate anchors ``census.mapped`` to it:
#
# The producer records under it, per criterion, the concept set it minted for it:
# ``{"inclusion:5": 2, "5": 2, ...}``, one ROLE-KEYED entry per criterion whose mapping
# returned a result, written in the same loop that appends the concept set and
# increments the codeset id. It is the only record in the file that says a PARTICULAR
# criterion produced something, which is what makes it the one referent for
# ``census.mapped`` — see :func:`criterion_accounting` for why the rule list cannot
# serve and why the ``ConceptSets`` length cannot either.
#
# The bare-id keys written beside the role keys are ignored everywhere here.
# Inclusion and exclusion criteria are numbered in independent sequences, so a bare
# key structurally cannot tell ``inclusion:42`` from ``exclusion:42``; the producer's
# own consumer dropped its bare-id fallback for exactly that reason.
#
# Unlike :data:`COLLAPSE_RECORD_KEYS`, whose spellings are still literals in
# ``TTEService``, this one is owned by ``circe_lint`` and imported by both sides — so
# the asymmetry that used to sit here is closed at the source rather than merely
# pointed at. It mattered in the OPPOSITE direction to the collapse keys: a producer
# typo found no map, and the link check simply did not run. There is no literal left
# to mistype, and the fail-open branch below is now reachable only by an artifact that
# genuinely carries no map — one generated before the record existed, or stripped after
# generation. Its absence is still printed on every row rather than passed over,
# because that is the signal that tells the two cases apart: a batch that suddenly
# reads "no concept-set links recorded" where it read "N of N mapped concept-set
# linked" is visible in a way a silent skip would not be.


def _describe(record: dict[str, Any]) -> str:
    role = record.get("role") or "?"
    return f"{role} #{record.get('criterionId', '?')} {str(record.get('label', ''))!r}"


def recorded_criterion_keys(records: Any) -> set[tuple[Any, str]]:
    """``{(role, criterionId)}`` for every row of a drop-record list that is a record.

    The one spelling of the key both ``_unmappedCriteria`` and ``_skippedCriteria``
    are read by, matching :func:`criteria_index` on the store side: the id is
    stringified because store ids are ints and every record spells them as strings.
    ``role`` is NOT coerced, so a row carrying something other than ``"inclusion"`` or
    ``"exclusion"`` keeps whatever it carries and joins nothing in the store index --
    which is the correct outcome, and is reported by
    :func:`unmapped_criteria_violations` on its own line.

    A row that is not a dict contributes nothing. It is reported on its own line by
    :func:`unmapped_criteria_violations` or by the malformed-skip check in
    :func:`criterion_accounting`, and leaving it out here is what makes the criterion
    it stood for show up as unaccounted-for rather than silently covered.
    """
    if not isinstance(records, list):
        return set()
    return {
        (record.get("role"), str(record.get("criterionId") or ""))
        for record in records
        if isinstance(record, dict)
    }


def emitted_criterion_keys(expression: dict[str, Any]) -> set[tuple[str, str]] | None:
    """``{(role, criterionId)}`` for every criterion the file says minted a concept set.

    The role-keyed half of ``_criterionConceptSetRefs``, read the way
    :func:`criterion_accounting` reads it and defined once so the two callers cannot
    drift: the accounting anchor that compares this set's size against
    ``census.mapped``, and the restatement survivor chain in
    :func:`_restatement_survivor`, which needs to know whether a NAMED criterion
    emitted rather than how many did.

    Bare-id keys are dropped for the reason stated at
    :data:`CRITERION_CONCEPT_SET_REFS_KEY`: inclusion and exclusion criteria are
    numbered in independent sequences, so a bare key cannot tell ``inclusion:42``
    from ``exclusion:42``.

    :returns: the key set, or ``None`` when the file carries no refs map at all --
        which is a legitimate state for an artifact exported on the draft path, and
        is why the value is three-state rather than an empty set. A caller that
        cannot tell "nothing emitted" from "no record of what emitted" would grant a
        permit on the strength of a missing key.
    """
    refs = expression.get(CRITERION_CONCEPT_SET_REFS_KEY)
    if not isinstance(refs, dict):
        return None
    keys: set[tuple[str, str]] = set()
    for key in refs:
        role, separator, criterion_id = str(key).partition(":")
        if separator:
            keys.add((role, criterion_id))
    return keys


def dropped_criteria_violations(records: Any) -> list[str]:
    """Whether each ``_droppedCriteria`` record actually describes a legal drop.

    Read on its own, a drop record is a self-report by the artifact being checked, and
    check (b) forgives a rule-set mismatch to the extent these records explain it. So
    the record must be more than well-formed: the ``(criteria type, attribute)`` pair
    it names is re-judged here by :func:`unreadable_value_attributes`, the same
    predicate the generator refused with. A record claiming ``Measurement`` carried an
    unreadable ``Unit`` describes no defect — Measurement reads Unit — so it explains
    no removal, and a rule cannot be laundered out of a file by inventing one.

    :param records: the value under ``_droppedCriteria``, of any shape.
    :returns: one line per malformed or unjustified record; empty when every record
        describes a drop this tree would actually have performed.
    """
    if records is None:
        return []
    if not isinstance(records, list):
        return [f"{DROPPED_CRITERIA_KEY} is not a list: {type(records).__name__}"]

    violations: list[str] = []
    for index, record in enumerate(records):
        where = f"{DROPPED_CRITERIA_KEY}[{index}]"
        if not isinstance(record, dict):
            violations.append(f"{where} is not a record: {record!r}")
            continue

        rule = record.get("rule")
        if not isinstance(rule, str) or not rule:
            violations.append(f"{where} names no rule: {record.get('rule')!r}")

        outcome = record.get("outcome")
        rule_after = record.get("ruleAfter")
        if outcome not in DROP_OUTCOMES:
            violations.append(f"{where} carries an unknown outcome {outcome!r}")
        elif outcome == DROP_OUTCOME_RULE_REMOVED and rule_after is not None:
            violations.append(
                f"{where} says the rule was removed but names a surviving rule "
                f"{rule_after!r}"
            )
        elif outcome == DROP_OUTCOME_RULE_RENAMED and (
            not isinstance(rule_after, str) or not rule_after or rule_after == rule
        ):
            violations.append(
                f"{where} says the rule was renamed but its new name is {rule_after!r}"
            )
        elif outcome == DROP_OUTCOME_RULE_KEPT and rule_after != rule:
            violations.append(
                f"{where} says the rule name was kept but records {rule_after!r} "
                f"beside {rule!r}"
            )

        unreadable = record.get("unreadable")
        if not isinstance(unreadable, list) or not unreadable:
            violations.append(f"{where} records no unreadable value attribute")
            continue
        for detail in unreadable:
            if not isinstance(detail, dict):
                violations.append(f"{where} carries a malformed detail {detail!r}")
                continue
            criteria_type = detail.get("criteriaType")
            attributes = detail.get("attributes")
            if not isinstance(criteria_type, str) or not isinstance(attributes, list):
                violations.append(f"{where} carries a malformed detail {detail!r}")
                continue
            # The predicate, not the record, decides. A probe body keyed by the
            # recorded attribute names is enough: `unreadable_value_attributes` reads
            # keys only.
            judged = unreadable_value_attributes(
                criteria_type, {name: None for name in attributes}
            )
            if sorted(judged) != sorted(str(name) for name in attributes):
                violations.append(
                    f"{where} claims {criteria_type} cannot read "
                    f"{', '.join(str(a) for a in attributes)}, but the allowlist says "
                    f"it cannot read {', '.join(judged) or 'nothing there'} — the "
                    "record justifies no drop"
                )
    return violations


def reconcile_dropped_rules(
    expression: dict[str, Any], store_names: list[str]
) -> tuple[list[str], list[str]]:
    """Replay the file's recorded drops onto the store's rule names.

    The emission-time repair mutates the expression being delivered and leaves the
    store's ``structuredExpression`` alone, so the two rule multisets legitimately
    differ after a drop. Each record says which rule it changed and how, so the store
    side can be moved forward to what the drop should have produced — and only that
    far. A missing rule no record accounts for survives the reconciliation and still
    fails check (b).

    :param expression: the delivered CIRCE expression.
    :param store_names: the store study's ``InclusionRules`` names.
    :returns: ``(adjusted store names, violations)``. Violations name a record whose
        rule the store does not carry, which means the record describes some other
        file's drop and explains nothing about this one.
    """
    records = expression.get(DROPPED_CRITERIA_KEY)
    if not isinstance(records, list) or not records:
        return list(store_names), []

    counter = Counter(store_names)
    violations: list[str] = []

    # One transformation per rule the drop touched, not one per criterion: CARMELINA's
    # incretin rule loses two members and leaves the file once. `ruleIndex` keys it, so
    # two distinct rules that happen to share a name stay two transformations.
    transformations: list[tuple[Any, str, Any, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        key = (
            record.get("ruleIndex"),
            str(record.get("rule") or ""),
            record.get("ruleAfter"),
            record.get("outcome"),
        )
        if key not in transformations:
            transformations.append(key)

    for _rule_index, rule, rule_after, outcome in transformations:
        if outcome == DROP_OUTCOME_RULE_KEPT:
            continue
        if outcome not in (DROP_OUTCOME_RULE_REMOVED, DROP_OUTCOME_RULE_RENAMED):
            # Reported by `dropped_criteria_violations`; replaying an outcome this
            # function does not understand would forgive a mismatch on a record
            # nobody validated.
            continue
        if counter[rule] <= 0:
            violations.append(
                f"{DROPPED_CRITERIA_KEY} records a drop from rule {rule!r}, which the "
                "store study does not carry"
            )
            continue
        counter[rule] -= 1
        if outcome == DROP_OUTCOME_RULE_RENAMED:
            counter[str(rule_after)] += 1

    return list(counter.elements()), violations


def criteria_index(study: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """``(role, criterionId)`` -> the store criterion row, for both roles.

    Store ids are ints and every record spells them as strings, so the key is
    stringified on both sides here — the same thing ``TTEService._record_skip`` does
    when it writes ``str(criterion.get("id", ""))``. A comparison that skipped that
    would find nothing and turn every reconciliation into a false failure.
    """
    eligibility = study.get("eligibility") or {}
    return {
        (role, str(criterion.get("id", ""))): criterion
        for role, rows in (
            ("inclusion", eligibility.get("inclusionCriteria") or []),
            ("exclusion", eligibility.get("exclusionCriteria") or []),
        )
        for criterion in rows
        if isinstance(criterion, dict)
    }


def unmapped_refusal_block_reason(record: dict[str, Any]) -> str | None:
    """Why this ``_unmappedCriteria`` row is criterion loss, or ``None`` when it is not.

    The single place the permit policy is applied. It reads ``refusalCode`` and nothing
    else — never the reason prose, which is written for a human and is byte-for-byte
    identical for an irreducible placeholder and for a mappable criterion the search
    stopped short of.

    :param record: one ``_unmappedCriteria`` row.
    :returns: a phrase naming why the row blocks the delivery, or ``None`` when
        :data:`PERMITTED_REFUSAL_CODES` covers it.
    """
    code = record.get("refusalCode")
    if code is None:
        return (
            "carries no refusalCode, so nothing deliberately refused it — a mapping "
            "that ended in a failure rather than a verdict is never permitted"
        )
    if code not in REFUSAL_CODES:
        return (
            f"carries refusalCode {code!r}, which is not in the vocabulary "
            f"(known: {', '.join(sorted(REFUSAL_CODES))})"
        )
    if code not in PERMITTED_REFUSAL_CODES:
        return f"refused as {code!r}, which is criterion loss a correct pipeline would not incur"
    return None


def unmapped_criteria_violations(
    records: Any, index: dict[tuple[str, str], dict[str, Any]]
) -> list[str]:
    """Whether each ``_unmappedCriteria`` record is a record at all.

    Deliberately NOT the loss verdict, which :func:`unmapped_refusal_block_reason`
    makes from ``refusalCode`` alone. This function asks only whether a row can be
    re-judged: a reason that is empty or whitespace-only, a ``(role, criterionId)`` the
    store study does not carry, or a ``refusalCode`` outside the vocabulary.

    Six rows of the 2026-09-08 batch (ARISTOTLE 26/27, PLATO 16, over two arms each)
    carry ``reason: ""`` because the producer records ``str(e)`` and
    ``str(TimeoutError())`` is the empty string — the run log shows a 5-second Stage 1
    search timeout booked as a mapping refusal. Such a row is reported on its own line,
    separately from the permit verdict, so that no future permit can ever cover it: a
    row with no reason ALSO carries no ``refusalCode``, and the two lines fail it twice
    for two different defects.

    The vocabulary check is here rather than in the permit because an unknown code is a
    record-integrity failure, not a policy decision. A permit that answered "not in
    ``PERMITTED_REFUSAL_CODES``, therefore loss" would report a producer typo as though
    it were a clinical verdict, and the delivery would be blocked for a reason nobody
    could find.

    :param records: the value under ``_unmappedCriteria``, of any shape.
    :param index: the store study's criteria, from :func:`criteria_index`.
    :returns: one line per record that cannot be re-judged; empty when every record is
        well-formed and attributable.
    """
    if records is None:
        return []
    if not isinstance(records, list):
        return [f"_unmappedCriteria is not a list: {type(records).__name__}"]

    violations: list[str] = []
    for position, record in enumerate(records):
        where = f"_unmappedCriteria[{position}]"
        if not isinstance(record, dict):
            violations.append(f"{where} is not a record: {record!r}")
            continue
        role = record.get("role")
        criterion_id = str(record.get("criterionId") or "").strip()
        if role not in ("inclusion", "exclusion"):
            violations.append(
                f"{where} {_describe(record)} carries an unrecognised role {role!r}"
            )
        elif not criterion_id:
            violations.append(f"{where} {_describe(record)} names no criterion")
        elif (role, criterion_id) not in index:
            violations.append(
                f"{where} {_describe(record)} names a criterion the store study does "
                "not carry, so the refusal cannot be re-judged"
            )
        if not str(record.get("reason") or "").strip():
            violations.append(
                f"{where} {_describe(record)} carries no reason — the producer recorded "
                "str(e) of an exception with an empty message (a TimeoutError on the "
                "Stage 1 search in the 2026-09-08 batch); a refusal that does not say "
                "why it refused cannot be reconciled"
            )
        code = record.get("refusalCode")
        if code is not None and code not in REFUSAL_CODES:
            violations.append(
                f"{where} {_describe(record)} carries refusalCode {code!r}, which is not "
                f"in the vocabulary — add it to REFUSAL_CODES in "
                f"src/utils/criterion_refusal.py rather than at the call site "
                f"(known: {', '.join(sorted(REFUSAL_CODES))})"
            )
    return violations


def _restatement_survivor(
    key: tuple[str, str],
    expression: dict[str, Any],
    index: dict[tuple[str, str], dict[str, Any]],
    unmapped_keys: set[tuple[str, str]],
    skipped_by_key: dict[tuple[str, str], dict[str, Any]],
    emitted: set[tuple[str, str]] | None,
) -> tuple[tuple[str, str] | None, str | None]:
    """Follow a criterion's restatement-collapse chain to the row that carries it.

    A criterion dropped by a restatement collapse is NOT lost: the collapse removed a
    duplicate and a survivor carries the same clinical content. Nothing in this module
    followed that chain, so ``_group_label_violations`` read such a member as gone and
    reported a group as having left the cohort when the store shows it did not --
    ARISTOTLE exclusion #19, whose members #20/#21 were folded member-for-member onto
    the identical pair #17/#18 in the sibling group ``355ec24f``, both of which
    emitted.

    Four conditions, ALL required. Each closes a different way a bookkeeping record
    could stand in for content that is actually gone, and the corpus supplies a real
    counterexample to the two that matter most:

    1. The criterion's OWN skip record names a restatement-collapse reason, and it is
       not also recorded as refused. A refusal is loss whatever a collapse list says
       about it, and a criterion carrying no record at all has nothing to follow --
       EMPA-REG inclusion #21's members #22/#23 were refused ``missing-entity-text``
       and appear in no collapse record, which is a real loss and still fails.
    2. A collapse record in the list that reason belongs to names it among its
       ``droppedIds`` AND names a ``survivorId``. Re-derived from the record rather
       than taken from the skip reason, so a producer writing the reason without the
       record reconciles nothing.
    3. The survivor ACTUALLY EMITTED -- it carries a per-criterion entry in
       ``_criterionConceptSetRefs``. This is the condition that does the work, and the
       corpus proves it: LEADER exclusion #28 and CAROLINA #16/#44 are each folded onto
       a survivor that is their own GROUP LABEL (#27, #15, #43), which was itself
       skipped as a container and minted nothing. Bookkeeping says "collapsed"; the
       cohort has nothing. Without this condition all three would be forgiven.
    4. The survivor's :func:`~src.services.restated_distinctness.distinctness_key`
       equals the dropped member's. The producer's own notion of sameness, imported
       rather than re-expressed, so the gate and the collapse cannot disagree about
       which two rows are the same row. This is what makes the substitution clinically
       honest rather than merely booked: without it a diastolic member reconciles
       against a systolic survivor, since both sit in the same collapse list.

    A missing refs map (``emitted`` is ``None``) reconciles NOTHING. Condition 3 cannot
    be evaluated, and the standard this module holds every other permit to is that
    unre-judgeable fails closed.

    ``distinctness_key`` is applied to the demographics collapse as well as the
    distinctness one. That path justifies itself by a cardinality argument over
    constraint-free Demographics rows rather than by key equality, so a group member
    folded by it will generally fail condition 4 and the group-label permit will be
    refused. That is the intended direction -- no corpus case exercises it, and a
    permit this gate cannot re-derive is one a human should look at.

    :returns: ``(survivor key, None)`` when the chain holds, else ``(None, why not)``
        with a phrase naming what broke -- or ``(None, None)`` when the criterion was
        never claimed to be a restatement at all, which is not a defect and warrants
        no clause on the report.
    """
    record = skipped_by_key.get(key)
    reason = record.get("reason") if isinstance(record, dict) else None
    if reason not in COLLAPSE_RECORD_KEYS:
        return None, None
    if key in unmapped_keys:
        return None, (
            f"#{key[1]} is recorded as {reason} and ALSO as refused, so the collapse "
            "cannot be what became of it"
        )

    collapses = expression.get(COLLAPSE_RECORD_KEYS[reason])
    if not isinstance(collapses, list):
        return None, (
            f"#{key[1]} is recorded as {reason} but the file carries no "
            f"{COLLAPSE_RECORD_KEYS[reason]}"
        )
    collapse = next(
        (
            candidate
            for candidate in collapses
            if isinstance(candidate, dict)
            and candidate.get("role") == key[0]
            and key[1] in {str(x) for x in (candidate.get("droppedIds") or [])}
        ),
        None,
    )
    if collapse is None:
        return None, f"#{key[1]} is recorded as {reason} but no collapse record names it"

    survivor_id = collapse.get("survivorId")
    if survivor_id is None:
        return None, f"#{key[1]}'s collapse record names no survivorId"
    survivor_key = (key[0], str(survivor_id))
    survivor = index.get(survivor_key)
    if survivor is None:
        return None, (
            f"#{key[1]} was collapsed onto survivor #{survivor_id}, which the store "
            "study does not carry"
        )

    if emitted is None:
        return None, (
            f"#{key[1]} was collapsed onto survivor #{survivor_id}, and the file "
            f"carries no {CRITERION_CONCEPT_SET_REFS_KEY} to show whether that "
            "survivor emitted"
        )
    if survivor_key not in emitted:
        return None, (
            f"#{key[1]} was collapsed onto survivor #{survivor_id}, which minted no "
            f"concept set of its own -- it carries no {CRITERION_CONCEPT_SET_REFS_KEY} "
            "entry, so the collapse moved this member onto a row that is not in the "
            "cohort either"
        )

    member = index.get(key)
    if member is None or distinctness_key(member) != distinctness_key(survivor):
        return None, (
            f"#{key[1]} was collapsed onto survivor #{survivor_id}, which does not "
            "carry the same sourceText and valueConstraint: the collapse is booked but "
            "the surviving row states a different fact"
        )
    return survivor_key, None


def _group_label_violations(
    where: str,
    label: dict[str, Any],
    role: str,
    index: dict[tuple[str, str], dict[str, Any]],
    lost: set[tuple[str, str]],
    expression: dict[str, Any],
    unmapped_keys: set[tuple[str, str]],
    skipped_by_key: dict[tuple[str, str], dict[str, Any]],
    emitted: set[tuple[str, str]] | None,
) -> list[str]:
    """Re-derive a ``group-label`` permit from the store rows of its own group."""
    violations: list[str] = []
    if not label.get("isGroupLabel"):
        violations.append(
            f"{where} is recorded as group-label but the store row is not a group label"
        )

    group_id = label.get("groupId")
    if not group_id:
        # The permit reads "this row lost nothing BECAUSE the members it labels
        # emitted". With no groupId there are no members to find, so neither the
        # stranded-threshold re-derivation below nor the all-members-lost check can
        # run, and the permit would be granted on the record's own word -- the amnesty
        # this whole module exists to remove. Unre-judgeable fails closed, the standard
        # `skipped_criteria_violations` already holds every other skip to.
        violations.append(
            f"{where} is recorded as group-label but the store row carries no groupId, "
            "so the members it claims to label cannot be found and nothing shows the "
            "group survived in them"
        )
        return violations
    members = [
        (key, criterion)
        for key, criterion in index.items()
        if key[0] == role
        and not criterion.get("isGroupLabel")
        and str(criterion.get("groupId")) == str(group_id)
    ]

    # The laundering guard. `resolve_group_member_constraint` is the one place that
    # decides whether a label's threshold reaches its members; asking it here means a
    # producer that stopped recording STRANDED and wrote plain `group-label` instead
    # cannot slip the loss past this permit, because the decision is re-made rather
    # than read off the record.
    #
    # Asked PER MEMBER, with that member's own analyte text. `997da1b` gave the
    # resolver a `member_analyte` keyword and an absolute bound now reaches the members
    # measured in its unit, so the question "does this threshold strand anything" no
    # longer has one answer for a whole group. Passing None asked the pre-997da1b
    # question -- "would this bound reach a member we know nothing about" -- whose
    # answer is always "no" for an absolute bound. On CAROLINA 44 and EMPA-REG 56 that
    # happened to give the right verdict (HbA1c genuinely is stranded by "> 240
    # mg/dL"), so nothing failed; but a group whose members are ALL unit-compatible
    # would have been reported as a loss the build never incurred.
    #
    # The analyte is read the way `TTEService._stranded_group_constraint_labels` reads
    # it -- `sourceText` then `description` -- because the two must answer alike or the
    # gate and the producer disagree about the same group.
    label_constraint = label.get("valueConstraint")
    if label_constraint:
        stranded = [
            criterion
            for _key, criterion in members
            if criterion.get("valueConstraint") is None
            and resolve_group_member_constraint(
                label_constraint,
                None,
                member_analyte=criterion.get("sourceText") or criterion.get("description"),
            ).refusal_reason
            == STRANDED_GROUP_CONSTRAINT_REASON
        ]
        if stranded:
            names = ", ".join(
                repr(criterion.get("sourceText") or criterion.get("description"))
                for criterion in stranded
            )
            violations.append(
                f"{where} is recorded as group-label but the producer's own predicate "
                f"says its absolute threshold {label_constraint!r} does not reach "
                f"{len(stranded)} of its {len(members)} member(s) ({names}): that is "
                f"{STRANDED_GROUP_CONSTRAINT_REASON}, which is loss and is off the "
                "allowlist"
            )

    # A container row loses nothing BECAUSE its members emit. When every member was
    # itself lost the group left the cohort entirely and nothing carries it.
    #
    # "Lost" is not the same as "absent from the rules", and reading it that way
    # reported a loss the store shows did not happen. A member dropped by a
    # restatement collapse is carried by its survivor, so it is lost only when that
    # chain does not reach a row that actually emitted -- which is what
    # `_restatement_survivor` decides, on four conditions it re-derives rather than
    # reads off the record. Measured on the 2026-09-11 delivery: it forgives ARISTOTLE
    # exclusion #19 and EMPA-REG exclusion #14 / inclusion #11, whose survivors all
    # minted concept sets, and forgives nothing on LEADER #27 or CAROLINA #15 / #43,
    # whose "survivor" is the skipped group label itself.
    if not members or any(key not in lost for key, _criterion in members):
        return violations

    chains = [
        _restatement_survivor(key, expression, index, unmapped_keys, skipped_by_key, emitted)
        for key, _criterion in members
    ]
    if any(survivor_key is not None for survivor_key, _why in chains):
        return violations

    # `why_not` is None for a member that never claimed to be a restatement, and such a
    # member is plainly gone -- there is nothing to explain. A phrase is appended only
    # where a collapse WAS recorded and did not reach an emitted row, because that is
    # the case a reader would otherwise have to reconstruct by hand from two lists.
    broken = [why for _survivor, why in chains if why is not None]
    detail = f" ({'; '.join(broken)})" if broken else ""
    violations.append(
        f"{where} is a group label skipped while none of its {len(members)} "
        f"member(s) emitted, so the whole group left the cohort{detail}"
    )
    return violations


def _collapse_violations(
    where: str,
    reason: str,
    role: str,
    criterion_id: str,
    expression: dict[str, Any],
    index: dict[tuple[str, str], dict[str, Any]],
    unmapped_keys: set[tuple[str, str]],
    skipped_by_key: dict[tuple[str, str], dict[str, Any]],
) -> list[str]:
    """Re-derive a restated-* permit from the collapse record in the same file."""
    key = COLLAPSE_RECORD_KEYS[reason]
    collapses = expression.get(key)
    if not isinstance(collapses, list):
        return [
            f"{where} is recorded as {reason} but the file carries no {key}, so nothing "
            "says which criterion it was collapsed onto"
        ]
    record = next(
        (
            candidate
            for candidate in collapses
            if isinstance(candidate, dict)
            and candidate.get("role") == role
            and criterion_id in {str(x) for x in (candidate.get("droppedIds") or [])}
        ),
        None,
    )
    if record is None:
        return [f"{where} is recorded as {reason} but no collapse record names it as dropped"]

    survivor_id = record.get("survivorId")
    survivor = (role, str(survivor_id))
    if survivor not in index:
        return [
            f"{where} was collapsed onto survivor #{survivor_id}, which the store study "
            "does not carry"
        ]
    if survivor in unmapped_keys:
        return [
            f"{where} was collapsed onto survivor #{survivor_id}, which was itself "
            "recorded unmapped — the restatement and the row it was folded into are "
            "both absent"
        ]
    survivor_skip = skipped_by_key.get(survivor)
    if survivor_skip is not None and survivor_skip.get("reason") not in ALLOWED_SKIP_REASONS:
        return [
            f"{where} was collapsed onto survivor #{survivor_id}, which was itself "
            f"skipped for {survivor_skip.get('reason')!r}"
        ]
    return []


def skipped_criteria_violations(
    records: Any,
    index: dict[tuple[str, str], dict[str, Any]],
    expression: dict[str, Any],
) -> list[str]:
    """Whether each ALLOWED skip reason actually holds for the criterion it names.

    :data:`ALLOWED_SKIP_REASONS` read on its own is an amnesty: the reason string is
    written by the artifact being checked, so a producer that renamed one branch's
    reason to another's would have its loss forgiven by a gate whose own test pins the
    original reason off the list. This is the same standard ``b6a4f2f`` set for
    ``_droppedCriteria`` — a drop is excused exactly as far as its record can be
    re-judged, and no further — applied to the channel that was still taken on trust.

    Only records whose reason IS on the allowlist are examined; an off-list reason is
    already failed by the caller and needs no re-derivation. Anything unre-judgeable
    fails closed: a record naming a criterion the store does not carry, or a collapse
    list the file does not carry.

    :param records: the value under ``_skippedCriteria``.
    :param index: the store study's criteria, from :func:`criteria_index`.
    :param expression: the delivered file, read for its collapse records and for the
        unmapped list that says which siblings were themselves lost.
    :returns: one line per permit that does not hold; empty when every allowed skip
        re-derives.
    """
    if not isinstance(records, list):
        return [f"_skippedCriteria is not a list: {type(records).__name__}"]

    # Deferred, not module-scope: `src.api.models.tte` reaches `src.settings`, whose
    # import runs `load_dotenv()`, and every src.* import in this tree must stay behind
    # `resolve_store_path`. Imported from the model module rather than from
    # `tte_service`, which re-exports it from here.
    from src.api.models.tte import DEMOGRAPHIC_DOMAINS

    unmapped_records = expression.get("_unmappedCriteria") or []
    unmapped_keys = recorded_criterion_keys(unmapped_records)
    skipped_by_key = {
        (record.get("role"), str(record.get("criterionId") or "")): record
        for record in records
        if isinstance(record, dict)
    }
    lost = unmapped_keys | set(skipped_by_key)
    # Read once here rather than per group label: the answer is a property of the file,
    # and `_restatement_survivor` needs it to tell a survivor that emitted from one
    # that was itself skipped. `None` (no refs map recorded) reconciles nothing.
    emitted = emitted_criterion_keys(expression)

    violations: list[str] = []
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        reason = record.get("reason")
        if reason not in ALLOWED_SKIP_REASONS:
            continue
        where = f"_skippedCriteria[{position}] {_describe(record)}"
        role = record.get("role")
        criterion_id = str(record.get("criterionId") or "").strip()
        criterion = index.get((role, criterion_id))
        if criterion is None:
            violations.append(
                f"{where} names a criterion the store study does not carry, so its "
                f"{reason!r} permit cannot be re-judged"
            )
            continue

        if reason == "group-label":
            violations.extend(
                _group_label_violations(
                    where,
                    criterion,
                    role,
                    index,
                    lost,
                    expression,
                    unmapped_keys,
                    skipped_by_key,
                    emitted,
                )
            )
        elif reason == "demographic-no-rule":
            domain = (criterion.get("domain") or "").strip()
            if domain not in DEMOGRAPHIC_DOMAINS:
                violations.append(
                    f"{where} is recorded as demographic-no-rule but the store row's "
                    f"domain {domain!r} is not a demographic domain"
                )
            # Meaning-derived rather than a copy of `_build_demographic_rule`: the
            # permit says the row had NO usable bound, so a row that carried a number
            # the builder happened not to support is a lost age bound, not a container.
            constraint = criterion.get("valueConstraint")
            if isinstance(constraint, dict) and constraint.get("value") is not None:
                violations.append(
                    f"{where} is a demographic criterion carrying a bound {constraint!r} "
                    "recorded as demographic-no-rule: the producer had a number and "
                    "built no rule from it"
                )
        else:
            violations.extend(
                _collapse_violations(
                    where,
                    reason,
                    role,
                    criterion_id,
                    expression,
                    index,
                    unmapped_keys,
                    skipped_by_key,
                )
            )
    return violations


def repair_ledger_violations(study: dict[str, Any]) -> tuple[list[str], str]:
    """Check (k): re-judge the store study's repair ledger. ``(violations, summary)``.

    ``eligibility._repairAccounting`` is the only record of what Agent 1's post-parse
    repairs did to the rule list. It matters to a DELIVERY gate because every other
    check in this file reconciles the delivered file against the store, and the store's
    own criteria rows are written AFTER those repairs run -- so a criterion a repair
    removed is on neither side of every reconciliation here. `total`, `mappable`,
    `mapped`, the residual identity and the store anchor all balance exactly while the
    criterion is gone. That is not hypothetical: CAROLINA's inclusion criteria fell from
    52 to 32 between the 2026-09-11 and 2026-09-12 stores, six of them the drug-therapy
    rows 18 to 23, and the 2026-09-13 delivery still reported "84 of 84 store criteria
    accounted for" on both CAROLINA arms.

    What is judged, and what is deliberately not:

    ``demotion`` -- JUDGED, and this is the check that catches a real loss. A demotion
        says the criterion is still in the tree and merely moved under a synthesised
        group. So a demotion naming a criterion the store does NOT carry is a departure
        with no departure record: the ledger says "moved", the store says "gone", and
        between them nothing says where. ``RepairLedger.accounted_ids`` already refuses
        to let a demotion satisfy the parse-time gate for exactly this reason; this is
        the same refusal one stage later, where the delivery is.

    ``departure`` -- COUNTED, never judged on presence. Verified against the six real
        ledgers in the 2026-09-13 store before this was written: 5 departures across
        studies 8, 9 and 10 name a criterion that IS still in the store, because
        ``_repair_band_tiers`` merges two halves of a band into one survivor and the
        survivor legitimately keeps a departed half's own name (2 of CAROLINA's 7).
        Failing those would fail correct rows, and a gate that fires on a correct batch
        is one someone switches off.

    ``rewrite`` -- COUNTED. The criterion is where it was; only a boundary moved, and
        the record exists so that a moved boundary is not silent.

    An unrecognised ``disposition``, a record that is not a record, a ledger that is not
    a list, and a record naming no criterion all FAIL. This is a reconciliation, so a
    record it cannot read is an unreconciled criterion -- the same direction
    :data:`ALLOWED_SKIP_REASONS` and :data:`PERMITTED_REFUSAL_CODES` fail in, where drift
    blocks a delivery rather than passing unread.

    Three-state on presence, like ``_droppedCriteria``: ABSENT means the store predates
    ``9ec4b3a`` and no claim can be made, and the row says so rather than staying silent
    -- a check whose only output is silence cannot be told from a check that never ran,
    which is precisely how ``_unmappedCriteria`` went unread for a month.
    """
    eligibility = study.get("eligibility") or {}
    if not isinstance(eligibility, dict) or REPAIR_ACCOUNTING_KEY not in eligibility:
        return [], "repair accounting: NOT RECORDED (store predates the ledger)"

    ledger = eligibility.get(REPAIR_ACCOUNTING_KEY)
    if not isinstance(ledger, list):
        return (
            [
                f"{REPAIR_ACCOUNTING_KEY} is not a list: {type(ledger).__name__} -- the "
                "record of what the post-parse repairs removed cannot be read, so no "
                "criterion they removed can be accounted for"
            ],
            "repair accounting: UNREADABLE",
        )

    # The store's criteria by their own text. The ledger records a criterion's `name`,
    # which `TTEService._criteria_from_ir` writes onto the store row as `description`;
    # measured on the 2026-09-13 store, all 16 real demotions match on exactly that
    # pair. Ids are NOT usable here: a criterion the repairs removed never reached the
    # store, so it never received one.
    present = {
        (criterion.get("description") or "").strip()
        for rows in (
            eligibility.get("inclusionCriteria") or [],
            eligibility.get("exclusionCriteria") or [],
        )
        for criterion in rows
        if isinstance(criterion, dict)
    }
    present.discard("")

    violations: list[str] = []
    counts = Counter()
    lost: list[str] = []

    for position, record in enumerate(ledger):
        where = f"{REPAIR_ACCOUNTING_KEY}[{position}]"
        if not isinstance(record, dict):
            violations.append(
                f"{where} is not a record ({record!r}), so the repair it stands for "
                "names no criterion and cannot be reconciled"
            )
            continue

        disposition = record.get("disposition")
        if disposition not in KNOWN_DISPOSITIONS:
            violations.append(
                f"{where} carries disposition {disposition!r}, which this gate does not "
                f"recognise (known: {', '.join(sorted(KNOWN_DISPOSITIONS))}) -- an "
                "unreadable repair record is an unreconciled criterion, so it blocks"
            )
            continue

        counts[disposition] += 1
        criterion = record.get("criterion")
        if not isinstance(criterion, dict):
            violations.append(
                f"{where} ({disposition}) names no criterion, so nothing says which "
                "criterion the repair acted on"
            )
            continue

        name = (criterion.get("name") or "").strip()
        if not name:
            violations.append(
                f"{where} ({disposition}) names a criterion with no name, so it cannot "
                "be reconciled against the store"
            )
            continue

        if disposition == DISPOSITION_DEMOTION and name not in present:
            lost.append(
                f"{where} records {name!r} as demoted into "
                f"{str(record.get('groupName') or 'a synthesised group')!r}, which says "
                "it is STILL in the rule tree -- and the store study carries no "
                "criterion by that name. It left, and no repair recorded taking it"
                + (
                    f" (protocol line: {(criterion.get('sourceText') or '')[:120]!r})"
                    if criterion.get("sourceText")
                    else ""
                )
            )

    if lost:
        violations.append(
            f"criteria recorded as demoted that the store does not carry ({len(lost)}): "
            + "; ".join(lost)
        )

    if not ledger:
        summary = "repair accounting: 0 repairs recorded"
    else:
        summary = "repair accounting: " + ", ".join(
            f"{counts[disposition]} {disposition}"
            for disposition in sorted(KNOWN_DISPOSITIONS)
            if counts[disposition]
        )
        if lost:
            summary += f", {len(lost)} demoted criteria MISSING from the store"
    return violations, summary


def criterion_accounting(
    expression: dict[str, Any], study: dict[str, Any]
) -> tuple[list[str], str]:
    """Re-judge a delivered file's own drop records: ``(violations, summary)``.

    The failure condition is any ``_unmappedCriteria`` row whose ``refusalCode`` is not
    in :data:`PERMITTED_REFUSAL_CODES`, plus ``skipped > 0`` for any reason not in
    :data:`ALLOWED_SKIP_REASONS`, plus any allowed skip whose permit does not
    re-derive. Neither ``skipped`` nor ``unmapped`` is loss by count alone — see those
    two constants for what is permitted and why — so a batch with 32 skips and nothing
    unmapped (the measured CAROLINA case) still passes, but only once each of those 32
    has been reconciled against the store criterion it names and the collapse record in
    the file beside it.

    The unmapped permit is strictly narrower than the skip permit: a skip is re-derived
    from the store, an unmapped row is classified by a code the producer wrote, and the
    two loosest possible readings of that code (absent, or outside the vocabulary) both
    fail. Until the producer emits ``unmappable-placeholder``, the permit changes no
    verdict at all — every row carries ``refusalCode: None`` or ``no-concept-mapping``
    and every one of them still blocks.

    ``study`` is required and has no default. The reconciliation needs the store's
    criteria rows, and a missing store would silently turn every re-derivation into a
    no-op — which is the shape of amnesty this function exists to remove. A record the
    store cannot answer for fails closed instead.

    The balance identity ``total == mapped + unmapped + demographicRules + skipped``
    is asserted here against the DELIVERED file.
    ``tests/test_generation_census_accounts_for_every_criterion.py`` asserts it
    against the generator, which is a different claim: between the two the payload
    is pruned, deep-copied and written to disk, and nothing re-checked it at the
    boundary where it is handed to a site.

    That identity is self-consistency and nothing more: every term in it is written by
    the artifact being checked, so a producer that stops writing ``_unmappedCriteria``
    rows can restore all of it by striking the rows and taking the difference off
    ``total`` and ``mappable``. Three anchors outside the census answer that, each
    seeing a defeat of the one before it:

    * ``total == len(criteria_index(study))`` — the store study's own criteria rows,
      the one referent outside the file. An EQUALITY in both directions: a census
      inflated first and then decremented survives a lower bound.
    * ``mapped + demographicRules == len(store criteria not named by any record)`` —
      the same reconciliation over ids rather than counts, so a criterion recorded
      under two outcomes, or a record naming a criterion the store does not carry,
      is visible where a count is not.
    * ``mapped == len(role-keyed _criterionConceptSetRefs)`` — the only per-criterion
      record of an emission the file carries, and the only thing that sees a refusal
      struck from ``_unmappedCriteria`` and booked as ``mapped``, which keeps the
      balance, the mappable identity and both anchors above. Run only when the file
      carries that key, and its absence is named in ``summary`` rather than passed
      over.

    ``summary`` is returned even when there are no violations, and the caller prints
    it on a passing row — a check whose only output is silence cannot be told from a
    check that never ran. It carries the store anchor and the emission link for that
    reason.
    """
    # The emission-time drop record, checked and reported on every path below. It is
    # NOT in ACCOUNTING_KEYS: those three are written together by the generator, so a
    # partial set means one was removed after the fact, while this fourth key is
    # written a stage later and is legitimately absent from any artifact exported
    # before it existed. Folding it into that set would fail every such artifact as
    # "incomplete" rather than reporting it as unrecorded.
    dropped = expression.get(DROPPED_CRITERIA_KEY)
    drop_violations = dropped_criteria_violations(dropped)

    # Check (k), folded in here rather than called beside this function because it must
    # reach EVERY return path below -- including the two early ones. A store whose
    # ledger records a loss is carrying that loss whether or not the file beside it
    # predates `_generationCensus`, and returning early on the file's age would drop the
    # only record of it. Same reason `drop_violations` is threaded through all three.
    ledger_violations, ledger_summary = repair_ledger_violations(study)
    drop_violations = drop_violations + ledger_violations
    ledger_clause = f", {ledger_summary}"
    if dropped is None:
        drop_clause = ""
    elif isinstance(dropped, list) and dropped:
        detail = "; ".join(
            str(record.get("summary") or record.get("rule"))
            for record in dropped
            if isinstance(record, dict)
        )
        drop_clause = f", {len(dropped)} dropped at emission ({detail})"
    else:
        drop_clause = ", 0 dropped at emission"

    # The windows the emitter substituted for a criterion whose extraction carried
    # none. Reported, never judged: a defaulted window is a QUALIFIER on a claim the
    # protocol did make, not criterion loss, so it appends NO violation on any path
    # below and cannot move a verdict -- the same reading `c1cb2c0` used to default
    # rather than refuse. Verified inert before it was written: injecting the key into
    # all 12 files of `output/site_gap/2026-09-09/deliver_v3` left 12 FAIL, the same
    # reasons and an unmoved census.
    #
    # It is reported because 57 of the 557 criteria in the cold-6 store (10%, nine of
    # the ten studies) carry no extracted window, so on a real batch one criterion in
    # ten had its temporal window guessed and the report said nothing -- this
    # function's own docstring rule ("a check whose only output is silence cannot be
    # told from a check that never ran") applied to a record rather than a check.
    #
    # Absent vs present-and-empty are kept distinct for the reason the producer emits
    # the key present-and-empty at all: "0 windows defaulted" is the claim that
    # nothing was substituted, and every artifact exported before 2026-09-10 -- the
    # whole 2026-09-09 delivery -- cannot make it. Printing 0 for those would assert
    # something unknown and probably false. Same three-state shape as `drop_clause`.
    #
    # The split is by `source`, which `c1cb2c0` recorded so the two could be told
    # apart. `domain-default` used the value `agent1/prompts.py` states to the model;
    # `unlisted-domain-default` took the judged -9999 for a domain the prompt never
    # documented, and per `DEFAULT_WINDOW_START_DAYS_UNLISTED_DOMAIN` such a row "is
    # the signal that a domain needs a documented value, not a judged one". Pooling
    # them would bury that signal in the routine case. A row whose `source` is neither
    # is counted and named rather than folded into either, because an unrecognised
    # source means the record shape drifted -- which is worth seeing and still is not
    # a failure.
    defaulted_windows = expression.get(DEFAULTED_WINDOW_CRITERIA_KEY)
    if defaulted_windows is None:
        defaulted_clause = ""
    elif isinstance(defaulted_windows, list) and defaulted_windows:
        sources = [
            record.get("source") if isinstance(record, dict) else None
            for record in defaulted_windows
        ]
        documented = sum(1 for s in sources if s == DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE)
        judged = sum(1 for s in sources if s == DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN)
        unrecognised = len(sources) - documented - judged
        if unrecognised == 0 and judged == 0:
            detail = "all documented"
        elif unrecognised == 0 and documented == 0:
            detail = "none documented"
        else:
            detail = ", ".join(
                f"{count} {word}"
                for count, word in (
                    (documented, "documented"),
                    (judged, "judged"),
                    (unrecognised, "unrecognised source"),
                )
                if count
            )
        defaulted_clause = f", {len(defaulted_windows)} windows defaulted ({detail})"
    else:
        defaulted_clause = ", 0 windows defaulted"

    # The criteria whose MANDATORY `entity_text` extraction left empty, so the mapper
    # was seeded on the criterion's human-facing `description` instead. Reported and
    # never a violation, for the reason the producer records survivors at all: 62 of the
    # grounded store's 70 substituted seeds MAPPED, and failing a delivery over them
    # would block 12 files to surface 8 losses `_unmappedCriteria` already carries. What
    # this line buys is the other direction -- a file that PASSES can still be carrying
    # dozens of concept sets mapped from a label rather than an entity, and until this
    # clause existed the report said nothing about it either way.
    #
    # Three-state, same as `defaulted_clause`: absent means the artifact predates the
    # record and no claim can be made; present-and-empty is the positive claim that every
    # criterion carried its own entity.
    missing_entity = expression.get(MISSING_ENTITY_CRITERIA_KEY)
    if missing_entity is None:
        missing_entity_clause = ""
    elif isinstance(missing_entity, list) and missing_entity:
        lost = sum(
            1
            for record in missing_entity
            if not isinstance(record, dict) or record.get("outcome") != "mapped"
        )
        missing_entity_clause = (
            f", {len(missing_entity)} seeds substituted for a missing entity_text "
            f"({lost} lost, {len(missing_entity) - lost} mapped on the criterion's name)"
        )
    else:
        missing_entity_clause = ", 0 seeds substituted"

    present = [key for key in ACCOUNTING_KEYS if key in expression]
    if not present:
        # Every current export writes all three. An artifact carrying none of them
        # was built before the accounting existed, so the identity cannot be
        # evaluated at all; saying so on the row is the honest report. This is a
        # known hole -- a pre-accounting artifact is not verifiable here and still
        # passes -- and closing it means re-exporting rather than re-reading.
        return (
            drop_violations,
            "criterion accounting: NOT RECORDED "
            f"(artifact predates _generationCensus){drop_clause}{defaulted_clause}"
            f"{missing_entity_clause}{ledger_clause}",
        )

    missing = [key for key in ACCOUNTING_KEYS if key not in expression]
    if missing:
        return (
            drop_violations
            + [
                "criterion accounting incomplete: "
                f"{', '.join(missing)} absent while {', '.join(present)} present"
            ],
            f"criterion accounting: INCOMPLETE{drop_clause}{defaulted_clause}"
            f"{missing_entity_clause}{ledger_clause}",
        )

    # The store's criteria: the anchor below and the two re-derivations further down
    # all read it. Built here rather than at the top because the two early returns
    # above (a pre-accounting artifact, an incomplete record set) have nothing to
    # reconcile.
    index = criteria_index(study)

    census = expression["_generationCensus"] or {}
    unmapped = expression["_unmappedCriteria"] or []
    skipped = expression["_skippedCriteria"] or []

    violations: list[str] = list(drop_violations)

    total = census.get("total")
    parts = {
        "mapped": census.get("mapped"),
        "unmapped": census.get("unmapped"),
        "demographicRules": census.get("demographicRules"),
        "skipped": census.get("skipped"),
    }
    if total is None or any(value is None for value in parts.values()):
        violations.append(f"census is missing a counter: {census!r}")
    else:
        balance = sum(parts.values())
        if total != balance:
            violations.append(
                f"census does not balance: total={total} != "
                + " + ".join(f"{name} {value}" for name, value in parts.items())
                + f" = {balance}"
            )
        # The counters and the lists are two records of the same event, so they are
        # cross-checked rather than trusted individually: a stripped list with its
        # counter left behind balances perfectly and reads as clean.
        if parts["unmapped"] != len(unmapped):
            violations.append(
                f"census counter disagrees with its record list: unmapped={parts['unmapped']} "
                f"but _unmappedCriteria carries {len(unmapped)}"
            )
        if parts["skipped"] != len(skipped):
            violations.append(
                f"census counter disagrees with its record list: skipped={parts['skipped']} "
                f"but _skippedCriteria carries {len(skipped)}"
            )
        by_reason = census.get("skippedByReason") or {}
        if sum(by_reason.values()) != parts["skipped"]:
            violations.append(
                "census counter disagrees with its own breakdown: skippedByReason sums to "
                f"{sum(by_reason.values())}, skipped={parts['skipped']}"
            )
        mappable = census.get("mappable")
        if mappable is not None and mappable != parts["mapped"] + parts["unmapped"]:
            violations.append(
                f"census counter disagrees: mappable={mappable} != "
                f"mapped {parts['mapped']} + unmapped {parts['unmapped']}"
            )

    # Every check above compares the census with itself, and self-consistency is
    # exactly what a producer that stops writing a record list can restore: strike the
    # rows, zero the counter, take the difference off `total` AND off `mappable`, and
    # the balance, both counter-vs-list cross-checks and the mappable identity all hold
    # again. Measured: deleting every `_unmappedCriteria` row from the 2026-09-09 batch
    # and rebalancing `total` alone fails all 12 files on the mappable identity;
    # rebalancing `mappable` too passes 8 of them. `total` is the one counter with a
    # referent OUTSIDE the file -- the store study's own criteria rows -- so anchoring
    # it there is what makes an unrecorded loss visible at all. On that batch the two
    # sides agree exactly on every file (39/39, 39/39, 114/114, 73/73, 49/49, 46/46),
    # so the anchor adds no failure the batch did not already carry.
    #
    # Outside the balance branch above on purpose: a census missing `mapped` cannot be
    # balanced but can still be anchored, and the criterion it lost is worth naming.
    #
    # An EQUALITY, in both directions, since `0d80c94` shipped it as a lower bound.
    # `total` short of the store is loss -- criteria the study has and the file accounts
    # for nowhere. `total` OVER the store is an outcome booked for a criterion that does
    # not exist, and leaving that direction open leaves the loss direction open with it:
    # a census inflated first and then decremented stays above a lower bound, so the
    # bound only ever closed the hole against a producer that did not also inflate. The
    # 11 gate-test fixtures that made this a bound -- synthetic censuses claiming 31-41
    # criteria over fixture stores of 2-15, every one of them the over-count direction --
    # were corrected to match their own stores in the same change that tightened this.
    if total is not None and total != len(index):
        if total < len(index):
            violations.append(
                f"census accounts for {total} of the store study's {len(index)} criteria: "
                f"{len(index) - total} criterion(s) left the study with no outcome recorded "
                "anywhere -- not mapped, not refused, not skipped, not built into a "
                "demographic rule -- and no record in the file says where they went"
            )
        else:
            violations.append(
                f"census accounts for {total} outcomes over the store study's {len(index)} "
                f"criteria: {total - len(index)} more outcome(s) are booked than the study "
                "has criteria, so at least that many name a criterion the store does not "
                "carry and the balance identity is counting something twice"
            )

    # The anchor above is a COUNT, and a count is defeated by a swap: strike an
    # `_unmappedCriteria` row, book the criterion as `mapped` and leave `total` alone,
    # and the balance, the mappable identity and the anchor all still hold while a
    # refused criterion is now recorded as having emitted. That is not only the
    # adversarial case -- a miscounting branch books a refused criterion as mapped by
    # accident and nothing else in this function would say so.
    #
    # So the outcomes are reconciled as SETS as well. The two recorded buckets name
    # their criterion ids; `mapped` and `demographicRules` do not, but they are the only
    # two outcomes left, so what the buckets do not name must be exactly what those two
    # counters claim. Three things follow and each is checked below: the buckets are
    # disjoint (a criterion has one outcome, not two), each is a subset of the store
    # (already reported per-record one channel over, and left to those lines), and
    # `mapped + demographicRules` equals the residual.
    #
    # Measured on the 12-file 2026-09-09 batch: the residual identity holds exactly on
    # all 12 (32/32, 25/25, 79/79, 58/58, 39/39, 38/38), the buckets are disjoint on all
    # 12, and no bucket names a criterion outside the store. It also holds on all 12 of
    # the previous day's `deliver_20260909` batch and all 12 of `deliver_20260908`.
    store_keys = set(index)
    unmapped_keys = recorded_criterion_keys(unmapped)
    skipped_keys = recorded_criterion_keys(skipped)

    double_booked = unmapped_keys & skipped_keys
    if double_booked:
        violations.append(
            f"{len(double_booked)} criterion(s) are recorded BOTH as refused and as "
            "skipped, so the balance counts one criterion twice and another that "
            "reached no outcome at all is hidden behind the double entry: "
            + "; ".join(f"{role} #{criterion_id}" for role, criterion_id in sorted(double_booked))
        )

    # Intersected with the store on purpose: a record naming a criterion the study does
    # not carry accounts for nothing here, and the residual below is right to count the
    # store criterion that record was standing in for as still unaccounted for. The
    # stray record itself is named by `unmapped_criteria_violations` and by
    # `skipped_criteria_violations`.
    residual = store_keys - ((unmapped_keys | skipped_keys) & store_keys)
    if parts["mapped"] is not None and parts["demographicRules"] is not None:
        claimed = parts["mapped"] + parts["demographicRules"]
        if claimed != len(residual):
            violations.append(
                f"census books {parts['mapped']} mapped + {parts['demographicRules']} "
                f"demographic rule(s) = {claimed} criteria as having emitted, but "
                f"{len(residual)} of the store study's {len(store_keys)} criteria are "
                "named by no refusal record and no skip record: the two counters and the "
                "two record lists are describing different sets of criteria"
            )

    # And the swap the residual identity above still cannot see, because it is a set
    # identity over the SAME partition: strike an `_unmappedCriteria` row and book its
    # criterion as `mapped`, and the id leaves the refused bucket and enters the
    # residual, so `mapped` rises by exactly as much as the residual does and both
    # sides move together. `mapped` has to be anchored to something the file records
    # PER CRITERION, and `_criterionConceptSetRefs` is the only such record: the
    # producer writes one role-keyed entry there in the same loop that appends the
    # concept set and increments the codeset id, so an entry means a concept set was
    # actually minted for that criterion.
    #
    # Two nearer-looking anchors were measured and REJECTED, both because they fire on
    # correct artifacts:
    #
    #   * `len(InclusionRules)` -- rules are not criteria. A group emits one rule for
    #     many members, a collapse folds a restatement onto its survivor, and a
    #     demographic rule has no concept set at all. `mapped == len(InclusionRules)`
    #     is wrong on every file of the real batch.
    #   * `len(ConceptSets)` -- the delivery path prunes, merges and adds sets after
    #     generation. Across the 144 census-carrying artifacts under `output/`,
    #     `len(ConceptSets) - mapped` takes four different values (1 on 130, 2 on 6,
    #     0 on 6, -1 on 2), so any fixed offset fails 14 real files.
    #
    # The refs map does hold: on all 71 artifacts under `output/` that carry both keys,
    # `mapped == len(role-keyed refs)` exactly, with no exception. It is an equality by
    # construction and not by coincidence -- the loop writes one entry per non-None
    # mapping result, keyed by `f"{role}:{id}"`, and `mapped` counts the same results --
    # and the two ways it could legitimately drift (a criterion with an empty id, two
    # criteria sharing one role+id) collapse the store index the same way, so the
    # equality anchor above fires on them first.
    #
    # CONDITIONAL, and this is the honest limit of the check: 73 of those 144 artifacts
    # carry `_generationCensus` and no refs map, including all 12 files of the previous
    # day's delivery. The key is popped on the draft path, so its presence is a property
    # of the export route rather than of the artifact's age, and failing a file for not
    # carrying it would fail a correct batch. It is therefore run when present and
    # NAMED IN THE SUMMARY when absent -- the same answer this function already gives a
    # pre-accounting artifact, and the reason `link_clause` is printed on passing rows.
    ref_keys = emitted_criterion_keys(expression)
    if ref_keys is None:
        link_clause = "no concept-set links recorded"
    else:
        contradicted = sorted(ref_keys & (unmapped_keys | skipped_keys))
        if contradicted:
            violations.append(
                f"{len(contradicted)} criterion(s) carry a concept-set reference in "
                f"{CRITERION_CONCEPT_SET_REFS_KEY} while a record says they were refused "
                "or skipped, so the file both minted a set for them and recorded that it "
                "did not: "
                + "; ".join(f"{role} #{criterion_id}" for role, criterion_id in contradicted)
            )
        stray_refs = sorted(ref_keys - store_keys)
        if stray_refs:
            violations.append(
                f"{len(stray_refs)} concept-set reference(s) in "
                f"{CRITERION_CONCEPT_SET_REFS_KEY} name a criterion the store study does "
                "not carry, so nothing says which criterion the set was minted for: "
                + "; ".join(f"{role} #{criterion_id}" for role, criterion_id in stray_refs)
            )

        if parts["mapped"] is not None and parts["mapped"] != len(ref_keys):
            if parts["mapped"] > len(ref_keys):
                violations.append(
                    f"census books {parts['mapped']} criteria as mapped but only "
                    f"{len(ref_keys)} of them carry a concept-set reference in "
                    f"{CRITERION_CONCEPT_SET_REFS_KEY}: "
                    f"{parts['mapped'] - len(ref_keys)} criterion(s) are counted as having "
                    "emitted while nothing in the file shows a concept set was ever minted "
                    "for them -- the shape a refusal booked as a mapping takes"
                )
            else:
                violations.append(
                    f"{CRITERION_CONCEPT_SET_REFS_KEY} carries {len(ref_keys)} per-criterion "
                    f"references but the census books only {parts['mapped']} criteria as "
                    f"mapped: {len(ref_keys) - parts['mapped']} concept set(s) were minted "
                    "for a criterion the census does not say was mapped"
                )
        link_clause = (
            f"{len(ref_keys)} of {parts['mapped']} mapped concept-set linked"
            if parts["mapped"] is not None
            else f"{len(ref_keys)} concept-set linked"
        )

    # Record integrity first, and on its own line: an unmapped row carrying no reason
    # at all is a different defect from the loss it also is, and no future allowlist
    # over reason strings could ever cover it.
    violations.extend(unmapped_criteria_violations(unmapped, index))

    # An unmapped record is loss unless its `refusalCode` says the loss is irreducible.
    # The verdict is made from that code and from nothing else -- see
    # `PERMITTED_REFUSAL_CODES` for why the prose cannot carry it, and
    # `unmapped_refusal_block_reason` for the one place it is applied.
    blocking: list[tuple[dict[str, Any], str]] = []
    permitted_unmapped: list[dict[str, Any]] = []
    for record in unmapped:
        if not isinstance(record, dict):
            continue
        block = unmapped_refusal_block_reason(record)
        if block is None:
            permitted_unmapped.append(record)
        else:
            blocking.append((record, block))

    if blocking:
        # The producer records `"reason": str(e)`, which is empty for any exception
        # constructed without an argument -- 3 of the 13 distinct unmapped criteria
        # across every exported artifact carry `""` (ARISTOTLE 26/27, PLATO 16).
        # Saying "reason not recorded" rather than printing nothing keeps that gap
        # visible here until the producer records `repr(e)` and the class as well.
        details = []
        for record, block in blocking:
            reason = str(record.get("reason") or "").strip()
            details.append(
                f"{_describe(record)} {block} — {reason or 'reason not recorded'}"
            )
        violations.append(f"unmapped criteria ({len(blocking)}): " + "; ".join(details))

    # An entry that is not a record carries no reason to judge and names no criterion
    # to reconcile, so the allowlist filter below and the re-derivation after it both
    # pass over it -- while `census.skipped` still counts it, the balance still holds,
    # and with `total` anchored the row it stands for is still accounted for. Nothing
    # else would ever speak: the summary would read "N skipped (all permitted)" over a
    # permit no one could read. `unmapped_criteria_violations` already reports exactly
    # this malformation one channel over; the two answer alike here.
    malformed_skips = [
        (position, record)
        for position, record in enumerate(skipped)
        if not isinstance(record, dict)
    ]
    if malformed_skips:
        violations.append(
            f"_skippedCriteria carries {len(malformed_skips)} entry(ies) that are not "
            "records, so the criterion each one counts as skipped names no permit and "
            "cannot be reconciled: "
            + "; ".join(f"[{position}] {record!r}" for position, record in malformed_skips)
        )

    off_list = [
        r for r in skipped if isinstance(r, dict) and r.get("reason") not in ALLOWED_SKIP_REASONS
    ]
    if off_list:
        violations.append(
            f"criteria skipped for a reason not on the allowlist ({len(off_list)}): "
            + "; ".join(f"{r.get('reason')!r} {_describe(r)}" for r in off_list)
        )

    # And the permits that ARE on the allowlist, re-derived rather than trusted.
    unreconciled = skipped_criteria_violations(skipped, index, expression)
    if unreconciled:
        violations.append(
            f"skips recorded under an allowed reason that does not hold "
            f"({len(unreconciled)}): " + "; ".join(unreconciled)
        )

    # "all permitted" now means permitted AND reconciled.
    notes = []
    if off_list:
        notes.append(f"{len(off_list)} not permitted")
    if unreconciled:
        notes.append(f"{len(unreconciled)} not reconciled")
    permitted = ", ".join(notes) if notes else "all permitted"
    # The unmapped count carries its own permit note for the same reason the skipped
    # one does: a permit that never appears on a passing row is indistinguishable from
    # a permit that was never applied, which is how these keys went unread for a month.
    if not unmapped:
        unmapped_clause = "0 unmapped"
    elif permitted_unmapped and not blocking:
        unmapped_clause = f"{len(unmapped)} unmapped (all permitted)"
    elif permitted_unmapped:
        unmapped_clause = (
            f"{len(unmapped)} unmapped ({len(permitted_unmapped)} permitted, "
            f"{len(blocking)} not permitted)"
        )
    else:
        unmapped_clause = f"{len(unmapped)} unmapped (none permitted)"
    # The store anchor and the emission link both report on the row, passing or not.
    # `0d80c94` held them silent to prove the anchor added no failure to the real batch;
    # that is proved, and a check whose only output is silence cannot be told from a
    # check that never ran -- which is exactly how a popped `_criterionConceptSetRefs`
    # would disable the link check without anyone noticing.
    anchor_clause = (
        f"{total} of {len(index)} store criteria accounted for"
        if total is not None
        else f"no total recorded against the store study's {len(index)} criteria"
    )
    summary = (
        f"criterion accounting: {census.get('mapped')} mapped, {unmapped_clause}, "
        f"{len(skipped)} skipped ({permitted}), {anchor_clause}, "
        f"{link_clause}{drop_clause}{defaulted_clause}{missing_entity_clause}"
        f"{ledger_clause}"
    )
    return violations, summary


def _parse_map(raw: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        slug, _, study_id_str = part.partition("=")
        mapping[slug.strip()] = int(study_id_str.strip())
    return mapping


def _split_filename(path: Path) -> tuple[str, str] | None:
    """Return (slug, role) for '<slug>_treatment.circe.json' /
    '<slug>_comparator.circe.json', or None if the name doesn't match."""
    stem = path.name
    if stem.endswith(".circe.json"):
        stem = stem[: -len(".circe.json")]
    for role in ("treatment", "comparator"):
        suffix = f"_{role}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)], role
    return None


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rule_multiset_check(file_names: list[str], store_names: list[str]) -> tuple[bool, str]:
    file_counter = Counter(file_names)
    store_counter = Counter(store_names)
    missing = store_counter - file_counter
    extra = file_counter - store_counter
    missing_count = sum(missing.values())
    extra_count = sum(extra.values())
    if missing_count == 0 and extra_count <= 1:
        if extra_count == 0:
            detail = "matches store rule set"
        else:
            detail = f"matches + 1 extra ({next(iter(extra))!r})"
        return True, detail
    detail = f"missing={missing_count} extra={extra_count}"
    return False, detail


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path, help="Export directory to verify")
    parser.add_argument("--store", required=True, type=Path, help="Explicit studies.json path")
    parser.add_argument(
        "--map",
        default=DEFAULT_MAP,
        help='"slug=study_id,..." mapping from filename prefix to store study id',
    )
    parser.add_argument(
        "--allow-skeleton",
        action="store_true",
        help="Skip files with fewer than 2 InclusionRules instead of failing them",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # The same resolver the exporter runs, for the same reason and in the same
    # order. Check (c) below expects a treatment arm's entry to equal the store's
    # own DrugEra entry, which is only what a drug-anchored export produces; a gate
    # resolving a different mode from the exporter compares against the wrong
    # expected entry, which is worse than no gate at all.
    try:
        mode = resolve_drug_anchored_entry()
    except DeliveryModeConflictError as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2
    print(mode.summary(), file=sys.stderr)

    try:
        store_path = resolve_store_path(args.store)
    except (StoreMismatchError, FileNotFoundError) as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2

    slug_to_id = _parse_map(args.map)

    with store_path.open(encoding="utf-8") as fh:
        store_payload = json.load(fh)
    studies = store_payload.get("studies") if isinstance(store_payload, dict) else store_payload
    studies_by_id = {int(s["id"]): s for s in studies}

    circe_files = sorted(args.dir.glob("*.circe.json"))
    if not circe_files:
        print(f"No *.circe.json files found under {args.dir}", file=sys.stderr)
        return 1

    manifest_path = args.dir / "manifest.json"
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as fh:
            manifest = json.load(fh)

    rows: list[dict[str, Any]] = []
    any_fail = False
    produced_roles_by_study: dict[int, set[str]] = {}

    for path in circe_files:
        parsed = _split_filename(path)
        if parsed is None:
            rows.append(
                {
                    "file": path.name,
                    "status": "FAIL",
                    "reasons": ["filename does not match '<slug>_treatment|comparator.circe.json'"],
                }
            )
            any_fail = True
            continue
        slug, role = parsed

        with path.open(encoding="utf-8") as fh:
            expression = json.load(fh)

        skeleton_study_id = slug_to_id.get(slug)
        if skeleton_study_id in studies_by_id:
            produced_roles_by_study.setdefault(skeleton_study_id, set()).add(role)

        rules = rule_names(expression)
        if len(rules) < 2 and args.allow_skeleton:
            rows.append(
                {
                    "file": path.name,
                    "status": "SKIPPED",
                    "reasons": [f"skeleton ({len(rules)} rule(s)) — allowed via --allow-skeleton"],
                }
            )
            continue

        study_id = slug_to_id.get(slug)
        if study_id is None or study_id not in studies_by_id:
            rows.append(
                {
                    "file": path.name,
                    "status": "FAIL",
                    "reasons": [f"no --map entry (or no store study) for slug {slug!r}"],
                }
            )
            any_fail = True
            continue
        study = studies_by_id[study_id]
        produced_roles_by_study.setdefault(study_id, set()).add(role)
        comparison_mode = study.get("comparisonMode") or ""
        store_structured = (study.get("eligibility") or {}).get("structuredExpression") or {}
        store_rule_names = rule_names(store_structured)
        store_domain, store_concept_ids = entry_concept_ids(store_structured)
        study_arms = study.get("treatmentArms") or []
        comparator_arm_name = study_arms[1].get("name") if len(study_arms) > 1 else None

        reasons: list[str] = []

        # (a) no-op exclusion rules
        noops = noop_exclusion_rules(expression)
        if noops:
            reasons.append(f"no-op rules ({len(noops)}): {', '.join(noops)}")

        # (b) rule-name multiset vs store, allowing one extra. The store side is moved
        # forward by whatever the file's own drop records say the emission-time repair
        # did to it -- and by nothing else, so a rule missing without a record naming
        # it is still a mismatch.
        expected_rule_names, drop_reconcile_violations = reconcile_dropped_rules(
            expression, store_rule_names
        )
        reasons.extend(drop_reconcile_violations)
        rules_ok, rules_detail = _rule_multiset_check(rules, expected_rule_names)
        if not rules_ok:
            reasons.append(f"rule set mismatch: {rules_detail}")
        elif Counter(expected_rule_names) != Counter(store_rule_names):
            rules_detail += " (after recorded emission-time drops)"

        # (c) entry concept ids vs store, with the sanctioned comparator swaps
        file_domain, file_concept_ids = entry_concept_ids(expression)
        file_entry_name = entry_concept_set_name(expression)
        entry_ok = entry_matches_expected(
            file_domain,
            file_concept_ids,
            store_domain,
            store_concept_ids,
            is_comparator=(role == "comparator"),
            comparison_mode=comparison_mode,
            file_entry_name=file_entry_name,
            comparator_arm_name=comparator_arm_name,
        )
        if entry_ok:
            if (file_domain, file_concept_ids) == (store_domain, store_concept_ids):
                case = "exact match"
            elif file_domain == "ConditionOccurrence":
                case = "disease-anchored comparator swap (target_minus_treatment)"
            else:
                case = f"active-comparator drug entry ({file_entry_name!r} matches arm 2)"
        else:
            case = "FAIL"
            reasons.append(
                f"entry mismatch: file={file_domain} {sorted(file_concept_ids)} "
                f"store={store_domain} {sorted(store_concept_ids)}"
            )

        # (h) a disease-anchored comparator must enter on the trial's registered
        # condition, not on whichever Condition rule the file happens to carry.
        if entry_ok and file_domain == "ConditionOccurrence" and (
            (file_domain, file_concept_ids) != (store_domain, store_concept_ids)
        ):
            registered = (study.get("trialMetadata") or {}).get("conditions")
            try:
                expected_anchor = expected_anchor_concept_ids(store_structured, registered)
            except DiseaseAnchorError as exc:
                reasons.append(f"disease anchor unverifiable: {exc}")
            else:
                if file_concept_ids != expected_anchor:
                    reasons.append(
                        "disease anchor mismatch: file enters on "
                        f"{file_entry_name!r} {sorted(file_concept_ids)} but the trial's "
                        f"registered condition ({', '.join(repr(c) for c in registered or [])}) "
                        f"resolves to {sorted(expected_anchor)}"
                    )
                    case = "FAIL"

        # (f) a rule that excludes what the cohort enters on -- an empty cohort.
        contradictions = contradictory_absence_rules(expression)
        if contradictions:
            reasons.append(
                f"contradictory absence rules ({len(contradictions)}): "
                f"{', '.join(contradictions)}"
            )

        # (g) a criterion whose concept set shares no domain with the CDM table it
        # reads -- the join matches nothing, so an absence rule excludes nobody.
        domain_mismatches = domain_mismatched_criteria(expression)
        if domain_mismatches:
            reasons.append(
                f"criterion domain mismatch ({len(domain_mismatches)}): "
                f"{'; '.join(domain_mismatches)}"
            )

        # (j) a Measurement criterion whose own name asserts a bound it does not
        # carry. Every other check reads a criterion that is PRESENT and asks whether
        # it is wrong; this one asks whether something is missing from it, which is
        # why the 26 lost thresholds in this batch were counted as "mapped".
        missing_bounds = asserted_bound_missing_criteria(expression)
        if missing_bounds:
            reasons.append(
                f"asserted bound missing ({len(missing_bounds)}): "
                f"{'; '.join(missing_bounds)}"
            )

        # (l) an absence over a lab with no result filter. Check (j) reads a NAME
        # that promised a bound; this one reads what the rule SELECTS without one --
        # "excluded anyone ever tested" rather than "anyone whose result crossed a
        # bound". PLATO's 'Thrombocytopenia' promises nothing, which is how it shipped
        # from 2026-09-10 to 2026-09-14 with every other lint green on it.
        unfiltered_absences = unfiltered_measurement_absence_criteria(expression)
        if unfiltered_absences:
            reasons.append(
                f"unfiltered measurement absence ({len(unfiltered_absences)}): "
                f"{'; '.join(unfiltered_absences)}"
            )

        # (q) a numeric bound with no unit, on any table that would read one. The
        # mirror of the pipeline's own `unstated-unit-bound` refusal, which drops a
        # criterion whose unit could not be resolved for precisely this reason -- so a
        # criterion that named no unit at all was shipping the bare number the refusal
        # exists to prevent. Check (j) reads a NAME that promised a bound and finds the
        # bound gone; here the bound is present and it is the SCALE that is missing,
        # which no name in the corpus asserts. LEADER's HbA1c is the case: 7.0% is 53
        # mmol/mol, so `>= 7.0` against an IFCC site passes nearly everyone rather than
        # no one. Covers `Observation` as well as `Measurement` -- CARMELINA's
        # 'Life expectancy' < 5 carries no unit while CAROLINA's same-concept criterion
        # carries `year`, and months rather than years is a twelve-fold error.
        unitless_bounds = unitless_value_bound_criteria(expression)
        if unitless_bounds:
            reasons.append(
                f"unitless value bound ({len(unitless_bounds)}): "
                f"{'; '.join(unitless_bounds)}"
            )

        # (m) two concept sets holding identical members under different names. Every
        # check above reads ONE concept set and asks whether the criterion using it is
        # wrong; this one reads a PAIR, which is the only way a name that describes an
        # exclusion its members never had becomes visible without a vocabulary.
        aliases = aliased_concept_sets(expression)
        if aliases:
            reasons.append(
                f"aliased concept sets ({len(aliases)}): {'; '.join(aliases)}"
            )

        # (r) a concept set holding a concept that is not the analyte its own name
        # states. Every check above -- (q) included -- asks whether a bound is on the
        # right SCALE; this one asks whether it is on the right QUANTITY, and no unit
        # filter can make 'LDL >= 135 mg/dL' right over an HDL result. Check (m) is the
        # nearest and cannot reach it: it needs TWO sets with identical members, and
        # here ONE set holds members its single name contradicts.
        confusables = confusable_concept_sets(expression)
        if confusables:
            reasons.append(
                f"confusable concept sets ({len(confusables)}): {'; '.join(confusables)}"
            )

        # (n) a mandatory presence and a mandatory absence over one concept set. Check
        # (f) tests an absence against the cohort's ENTRY set only, so a rule that
        # contradicts another RULE passed every lint; four such pairs shipped on both
        # LEADER arms.
        presence_absence = contradictory_presence_absence_criteria(expression)
        if presence_absence:
            reasons.append(
                f"contradictory presence/absence ({len(presence_absence)}): "
                f"{'; '.join(presence_absence)}"
            )

        # (s) an inclusion rule whose EVERY required criterion is forbidden outright by a
        # mandatory zero-occurrence criterion elsewhere in the file. Checks (m) and (n)
        # are the nearest and both stay silent on the shipped shape: (m) excludes
        # identical names and all four HbA1c sets carry one, (n) drops a bounded absence
        # and does not descend a top-level `ANY`. Matching on what a criterion SELECTS
        # rather than on its `CodesetId` is what makes four ids over identical members
        # visible as one predicate.
        unsatisfiable_presences = unsatisfiable_presence_rules(expression)
        if unsatisfiable_presences:
            reasons.append(
                f"unsatisfiable presence rule ({len(unsatisfiable_presences)}): "
                f"{'; '.join(unsatisfiable_presences)}"
            )

        # (o) a rule emitted as a conjunction over a stated disjunction. Check (n)
        # reaches LEADER's rule 2 only because codesets 10 and 11 are byte-identical;
        # the same inversion over sets that merely differ contradicts nothing a
        # structural check can see, and this is the only one that reads the protocol
        # line the alternatives were written on.
        conjoined_disjunctions = conjoined_disjunction_rules(expression, study)
        if conjoined_disjunctions:
            reasons.append(
                f"conjoined disjunction ({len(conjoined_disjunctions)}): "
                f"{'; '.join(conjoined_disjunctions)}"
            )

        # (i) the file's own drop records: recorded criterion loss, and whether the
        # census that reports it still balances on the delivered artifact.
        accounting_violations, accounting_summary = criterion_accounting(expression, study)
        reasons.extend(accounting_violations)

        # (p) criteria whose own protocolLine does not support what they claim.
        # REPORTED, NEVER JUDGED -- it appends no violation on any path below and
        # cannot move a verdict, exactly like `defaulted_clause` in
        # `criterion_accounting`. The reason is measured: over this batch the check
        # fires 21 times and nine of them carry a defect finding in the delivery audit,
        # the other twelve being decompositions of an umbrella the line does name (ACS
        # into STEMI/NSTEMI/unstable angina), a line truncated by pdftotext, and a lay
        # paraphrase. At 9-in-21 a gate would delete more correct criteria than
        # invented ones.
        #
        # Every other check in this file reads the emitted expression against itself or
        # against the store's structure. This is the only one that reads the protocol
        # line a criterion came from against what the criterion went on to claim -- the
        # question `protocolLine` was added to make answerable and that nothing asked.
        # ARISTOTLE InclusionRules[13] is why: an all-time "Prior ischemic stroke"
        # exclusion built from the one-word line "Prior", contradicting the trial's own
        # inclusion 3(b) emitted as rule 19, and it passed every existing check.
        grounding_records, grounding_summary = ungrounded_criteria(expression, study)
        if grounding_records:
            detail = "; ".join(
                f"{record['role']} {record['id']} \"{record['description']}\" "
                f"[{record['shape']}] line={record['protocolLine'][:60]!r}"
                for record in grounding_records
            )
            grounding_clause = f"{grounding_summary}: {detail}"
        else:
            grounding_clause = grounding_summary

        # (d) manifest cross-check, if present
        if manifest is not None:
            manifest_entry = next(
                (f for f in manifest.get("files", []) if f.get("file") == path.name), None
            )
            if manifest_entry is None:
                reasons.append("manifest.json present but has no entry for this file")
            elif manifest_entry.get("md5") != _file_md5(path):
                reasons.append("manifest md5 does not match file on disk")
            manifest_store_sha = manifest.get("store_sha256")
            if manifest_store_sha is not None and manifest_store_sha != _file_sha256(store_path):
                reasons.append("manifest store_sha256 does not match --store file")

        status = "PASS" if not reasons else "FAIL"
        if status == "FAIL":
            any_fail = True
        rows.append(
            {
                "file": path.name,
                "status": status,
                # The accounting summary rides EVERY row, passing or failing. On a
                # passing row because a check that only ever speaks up on failure is
                # indistinguishable from a check that was never wired in -- which is
                # exactly how these keys went unread from the day they were written.
                # On a failing row because every file of the six-study batch fails on
                # recorded criterion loss, so a summary printed only on success would
                # never once have said what the emission-time repair removed.
                "reasons": (
                    reasons + [accounting_summary, grounding_clause]
                    if reasons
                    else [
                        f"entry: {case}; rules: {rules_detail}; {accounting_summary}",
                        grounding_clause,
                    ]
                ),
            }
        )

    # (e) arm completeness, across files rather than per file.
    id_to_slug = {study_id: slug for slug, study_id in slug_to_id.items()}
    for study_id in sorted(produced_roles_by_study):
        study = studies_by_id[study_id]
        missing = missing_arm_roles(study, produced_roles_by_study[study_id])
        for role in missing:
            slug = id_to_slug.get(study_id, str(study_id))
            rows.append(
                {
                    "file": f"{slug}_{role}.circe.json",
                    "status": "MISSING",
                    "reasons": [
                        f"study {study_id} declares arm {role!r} "
                        f"({[a.get('name') for a in study.get('treatmentArms') or []]}) "
                        "but no file was produced for it"
                    ],
                }
            )
            any_fail = True

    print(f"{'file':<40}  {'status':<8}  reasons")
    for row in rows:
        print(f"{row['file']:<40}  {row['status']:<8}  {'; '.join(row['reasons'])}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
