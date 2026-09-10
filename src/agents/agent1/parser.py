"""
Agent 1 (Logic Decomposer) - NLU Parser.
Converts natural language clinical queries or NCT protocols to ARTEMIS IR using LLM.
"""
import os
import json
import logging
import re
from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import ValidationError

logger = logging.getLogger(__name__)

from src.utils.env_flags import env_flag_enabled
from src.utils.llm import get_llm, raise_if_truncated, resolve_model, token_usage
from src.models.ir import ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria, CohortOutcome, TemporalWindow, ValueConstraint
from src.agents.agent1.eligibility_section import (
    Missing,
    Truncated,
    extract_eligibility_section,
)
from src.agents.agent1.prompts import (
    SYSTEM_PROMPT, DECOMPOSITION_PROMPT,
    NCT_SYSTEM_PROMPT, NCT_DECOMPOSITION_PROMPT,
    THRESHOLD_REVIEW_PROMPT, THRESHOLD_MATCH_PROMPT
)
from src.agents.agent1.nct_fetcher import (
    fetch_trial_data, fetch_or_load_trial_data, 
    load_trial_data_from_file, TrialData
)
from src.agents.agent1.pubmed_linker import (
    extract_pmids_from_nct, get_design_paper_pmids,
    search_pubmed_for_nct
)
from src.agents.agent1.pubmed_fetcher import (
    fetch_pubmed_abstract, extract_eligibility_from_text
)
from src.agents.agent1.enricher import enrich_trial_data
from src.api.models.tte import PaperStatus, PaperDownloadInfo, DownloadUrl, DownloadResult
from src.agents.agent1.paper_url_mapper import (
    extract_doi_from_pubmed,
    download_papers_for_doi,
    build_paper_urls,
)

def _ir_cache_enabled() -> bool:
    """Whether the Agent 1 IR cache may be read or written.

    Same name shape and the same comparison as ``CRITERION_CACHE_ENABLED`` —
    both go through :func:`src.utils.env_flags.env_flag_enabled`.
    """
    return env_flag_enabled("AGENT1_IR_CACHE_ENABLED")


def _normalize_trial_data_for_stable_hash(trial_data: "TrialData") -> "TrialData":
    """
    Return a copy of trial_data with criteria normalized for stable hashing.

    Normalization steps:
    - Strip leading/trailing whitespace from each criterion string
    - Collapse multiple internal spaces into one
    - Remove Unicode non-breaking spaces (U+00A0)
    - Deduplicate criteria while preserving stable (sorted) order

    This is a pure function — the original trial_data is not mutated.
    """
    def _clean(text: str) -> str:
        # Remove non-breaking spaces
        text = text.replace("\u00a0", " ")
        # Collapse multiple spaces
        text = re.sub(r" {2,}", " ", text)
        return text.strip()

    def _normalize_list(criteria: list) -> list:
        seen: set = set()
        result = []
        for item in sorted(_clean(c) for c in criteria):
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    return trial_data.model_copy(update={
        "inclusion_criteria": _normalize_list(trial_data.inclusion_criteria),
        "exclusion_criteria": _normalize_list(trial_data.exclusion_criteria),
    })


class LogicDecomposer:
    """
    Agent 1: Decomposes natural language clinical queries into structured IR.
    Supports both free-text queries and NCT protocol input.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.llm = get_llm(
            model_name=model_name,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        # The IR cache key is built from this; "default" collapsed every model
        # into one file, so a second-arm run replayed arm one's cached IR.
        self.model_name = model_name or resolve_model()
        self.parser = JsonOutputParser()
        # Paper enrichment status from the last parse_nct() call.
        # Callers may read this after parse_nct() returns.
        self.last_paper_status: Optional[PaperStatus] = None
    
    def parse(self, query: str) -> ARTEMISRequest:
        """
        Parse a natural language clinical question into ARTEMIS IR.
        
        Args:
            query: Natural language clinical question
            
        Returns:
            ARTEMISRequest object with structured representation
        """
        print(f"[Agent 1] Parsing query: '{query[:100]}...'")
        
        # Build prompt
        prompt = DECOMPOSITION_PROMPT.format(query=query)
        
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        
        # Call LLM
        data = self._invoke_and_extract(messages, what="Agent 1 free-text extraction")

        # Convert to ARTEMIS IR objects
        return self._build_artemis_request(data)
    
    def parse_nct(
        self,
        nct_id: str,
        json_path: Optional[str] = None,
        enrich_from_pubmed: bool = True,
        design_paper_pdf: Optional[str] = None,
        papers_dir: Optional[str] = None,
        verify_thresholds: bool = True,
    ) -> ARTEMISRequest:
        """
        Parse a clinical trial protocol from ClinicalTrials.gov into ARTEMIS IR.
        
        Args:
            nct_id: ClinicalTrials.gov identifier (e.g., "NCT01730534")
            json_path: Optional path to local JSON file.
            enrich_from_pubmed: Attempt to enrich from PubMed abstracts.
            design_paper_pdf: Optional path to single design paper PDF.
            papers_dir: Optional directory containing PDFs (main paper + appendix).
                        Auto-discovers from data/papers/{nct_id}/ if not specified.
                        Priority: appendix/supplement > main paper > PubMed.
            verify_thresholds: Run Step 7's second LLM pass, which reviews the
                        output against the original criteria text for a dropped
                        numeric threshold Step 6's aggregate count can miss when
                        another criterion over-produces and offsets the total. Costs
                        one extra LLM call per parse_nct(); disable for cheap/smoke runs.

        Returns:
            ARTEMISRequest object with structured representation
        """
        import warnings
        from pathlib import Path
        
        print(f"[Agent 1] Parsing NCT protocol: {nct_id}")
        
        # Step 1: Fetch or load trial data
        nct_raw_data = None
        if json_path:
            trial_data = load_trial_data_from_file(json_path)
        else:
            trial_data = fetch_or_load_trial_data(nct_id)
        
        # Step 1.5: Enrich from papers — track enrichment source for PaperStatus
        enriched = False
        paper_status = PaperStatus()

        # Priority 1: papers_dir (explicit or auto-discovered)
        if not papers_dir:
            # Auto-discover from data/papers/{nct_id}/
            auto_dir = Path(__file__).resolve().parents[3] / "data" / "papers" / nct_id.upper()
            if auto_dir.exists():
                papers_dir = str(auto_dir)
                print(f"[Agent 1] 📂 Auto-discovered papers dir: {papers_dir}")

        if papers_dir:
            pdfs = self._discover_pdfs(papers_dir)
            if pdfs:
                has_supplement = any(p['role'] == 'supplement' for p in pdfs)
                papers_found = []
                for pdf_info in pdfs:
                    if pdf_info['role'] == 'main' and has_supplement:
                        print(f"[Agent 1] ⏭ Skipping [{pdf_info['role']}] {pdf_info['name']} "
                              f"— supplement available (complete criteria)")
                        continue
                    print(f"[Agent 1] 📄 Enriching from [{pdf_info['role']}] {pdf_info['name']}")
                    trial_data = self._enrich_from_pdf(
                        trial_data, pdf_info['path'], role=pdf_info['role']
                    )
                    papers_found.append(PaperDownloadInfo(
                        name=pdf_info['name'],
                        role=pdf_info['role'],
                        source="local",
                    ))
                paper_status = PaperStatus(
                    source="local",
                    papers_found=papers_found,
                    supplement_available=has_supplement,
                    manual_download_needed=False,
                )
                enriched = True
            else:
                warnings.warn(
                    f"[Agent 1] ⚠ papers_dir '{papers_dir}' exists but contains no PDFs.",
                    RuntimeWarning, stacklevel=2
                )

        # Priority 2: single design_paper_pdf (backward compat)
        if not enriched and design_paper_pdf:
            from pathlib import Path as _PdfPath
            trial_data = self._enrich_from_pdf(trial_data, design_paper_pdf)
            pdf_name = _PdfPath(design_paper_pdf).name
            paper_status = PaperStatus(
                source="local",
                papers_found=[PaperDownloadInfo(name=pdf_name, role="main", source="local")],
                supplement_available=False,
                manual_download_needed=False,
            )
            enriched = True

        # Priority 3: PubMed fallback (also updates paper_status internally)
        if not enriched and enrich_from_pubmed:
            trial_data, paper_status = self._enrich_from_pubmed(trial_data, nct_id)

        # Determine enrichment source tag for logging / meta file
        enrichment_source = paper_status.source if paper_status and paper_status.source else "nct_only"

        # Normalize trial_data before hashing to ensure stable hash across minor whitespace differences
        trial_data = _normalize_trial_data_for_stable_hash(trial_data)

        # Log enrichment source with criteria counts
        logger.info(
            "[Agent 1] Enrichment source: %s | criteria: %d inclusion, %d exclusion",
            enrichment_source,
            len(trial_data.inclusion_criteria),
            len(trial_data.exclusion_criteria),
        )

        # Step 2: Build NCT-specific prompt
        prompt = NCT_DECOMPOSITION_PROMPT.format(
            title=trial_data.title,
            conditions=", ".join(trial_data.conditions) or "Not specified",
            interventions=", ".join(trial_data.interventions) or "Not specified",
            outcomes=", ".join(trial_data.primary_outcomes) or "Not specified",
            inclusion=self._format_criteria(trial_data.inclusion_criteria),
            exclusion=self._format_criteria(trial_data.exclusion_criteria),
        )
        
        messages = [
            SystemMessage(content=NCT_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        
        # Step 3: Call LLM (with deterministic cache)
        from datetime import datetime, timezone
        cache_dir = Path(__file__).resolve().parents[3] / "data" / "cache" / "agent1_ir"
        model_key = self.model_name.replace("/", "_").replace(":", "_")
        prompt_hash = self._ir_cache_key(model_key, NCT_SYSTEM_PROMPT, prompt)
        cache_file = cache_dir / f"{nct_id}_{model_key}_{prompt_hash}.json"
        meta_file = cache_dir / f"{nct_id}_{model_key}_{prompt_hash}.meta.json"

        logger.info(
            "[Agent 1] Enrichment source: %s | criteria: %d inclusion, %d exclusion | hash: %s",
            enrichment_source,
            len(trial_data.inclusion_criteria),
            len(trial_data.exclusion_criteria),
            prompt_hash,
        )

        cache_enabled = _ir_cache_enabled()
        if cache_enabled and cache_file.exists():
            print(f"[Agent 1] 📦 Cache HIT: {cache_file.name}")
            with open(cache_file) as f:
                data = json.load(f)
        else:
            reason = "disabled" if not cache_enabled else "MISS"
            print(f"[Agent 1] 🔄 Cache {reason} → calling LLM")
            data = self._invoke_and_extract(
                messages, what=f"Agent 1 NCT extraction for {nct_id}"
            )
            if cache_enabled:
                # Save to cache for deterministic replay
                cache_dir.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"[Agent 1] 💾 Cached: {cache_file.name}")

        # Write optional metadata alongside the cache file (does not affect cache key)
        if not meta_file.exists():
            cache_dir.mkdir(parents=True, exist_ok=True)
            meta = {
                "enrichment_source": enrichment_source,
                "model": self.model_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "inclusion_count": len(trial_data.inclusion_criteria),
                "exclusion_count": len(trial_data.exclusion_criteria),
                "inclusion_criteria": trial_data.inclusion_criteria,
                "exclusion_criteria": trial_data.exclusion_criteria,
            }
            with open(meta_file, "w") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        
        # Step 4: Build IR
        ir = self._build_artemis_request(data)
        
        # Step 5: Coverage check — warn if LLM omitted criteria
        input_count = len(trial_data.inclusion_criteria) + len(trial_data.exclusion_criteria)
        output_count = len(ir.target.inclusion_rules) + len(ir.target.exclusion_rules)
        
        print(f"[Agent 1] ✅ IR generated from {nct_id}: "
              f"{len(ir.target.inclusion_rules)} inclusion, "
              f"{len(ir.target.exclusion_rules)} exclusion rules")
        
        if output_count < input_count * 0.5:
            import warnings
            warnings.warn(
                f"[Agent 1] ⚠ Coverage gap: {input_count} input criteria → {output_count} output rules. "
                f"LLM may have omitted criteria. Consider re-running or reviewing output.",
                RuntimeWarning, stacklevel=2
            )

        # Step 6: Value-constraint coverage check — warn if the LLM's output carries
        # fewer numeric thresholds than the deterministic parser found in the input
        # criteria text. ADR-031-B hands the model its own thresholds pre-parsed so it
        # only has to copy them; when source_text isn't copied verbatim (the WRONG/RIGHT
        # example in prompts.py), the downstream substring match fails and
        # value_constraint silently comes back None even though the annotation was
        # right there in the prompt. Pattern E can only ever GROW the count (one shared
        # threshold written onto several sub_criteria), never shrink it, so `<` here is
        # always a real loss, not a legitimate merge.
        input_vc_count = (
            self._count_value_constraints(trial_data.inclusion_criteria)
            + self._count_value_constraints(trial_data.exclusion_criteria)
        )
        output_vc_count = (
            self._count_output_value_constraints(ir.target.inclusion_rules)
            + self._count_output_value_constraints(ir.target.exclusion_rules)
        )
        if output_vc_count < input_vc_count:
            import warnings
            warnings.warn(
                f"[Agent 1] ⚠ Value-constraint coverage gap: the deterministic parser "
                f"found {input_vc_count} threshold(s) in {nct_id}'s criteria text, but "
                f"only {output_vc_count} appear in the output IR. A threshold likely "
                f"vanished because source_text wasn't copied verbatim onto every "
                f"sub_criterion sharing it — inspect this run's criteria before trusting "
                f"its value_constraint fields.",
                RuntimeWarning, stacklevel=2
            )

        # Step 7: LLM threshold review — Step 6's count is a study-wide sum, so one
        # criterion losing its threshold and another over-producing (e.g. Pattern E
        # attaching a value_constraint to a sub_criterion that never had one) can
        # cancel out in the total and leave the aggregate check silent. This asks a
        # second, small, focused pass to read each criterion line against its
        # generated rule directly, instead of comparing totals.
        if verify_thresholds:
            misses = self._llm_review_value_constraints(
                nct_id, trial_data.inclusion_criteria, trial_data.exclusion_criteria, ir,
            )
            still_broken = self._repair_threshold_misses(
                nct_id,
                trial_data.inclusion_criteria,
                trial_data.exclusion_criteria,
                ir,
                misses,
            )

            if misses:
                print(f"[Agent 1] Step 7/8: {len(misses)} flagged, "
                      f"{len(misses) - len(still_broken)} auto-repaired, "
                      f"{len(still_broken)} still need review")

            if still_broken:
                import warnings
                lines = "; ".join(
                    f"line {m.get('criterion_line')}: {m.get('criterion_text')!r} — {m.get('reason')}"
                    for m in still_broken
                )
                warnings.warn(
                    f"[Agent 1] ⚠ {len(still_broken)} threshold(s) in {nct_id} could not be "
                    f"auto-repaired (ambiguous match) — needs human review: {lines}",
                    RuntimeWarning, stacklevel=2
                )

        # Expose paper enrichment status for the caller
        self.last_paper_status = paper_status

        return ir
    
    @staticmethod
    def _ir_cache_key(model_key: str, system_prompt: str, prompt: str) -> str:
        """Deterministic cache key for one Agent 1 IR call.

        The system prompt is part of the key because it decides the answer. Pattern E
        lives there, and it is what makes an "A or B or C" criterion a single ANY
        group rather than several flat rules. Keying only on the human message meant
        a Pattern E edit produced ``Cache HIT``, replayed the previous IR, and
        reported the number it was meant to change -- indistinguishable in the output
        from the change simply not working.

        Fields are joined with a separator that cannot occur in any of them, so
        ("ab", "c") and ("a", "bc") cannot collide.

        :param model_key: filename-safe model identifier.
        :param system_prompt: the SystemMessage content for this call.
        :param prompt: the HumanMessage content for this call.
        :returns: 16 hex characters, safe to place straight into a filename.
        """
        import hashlib

        material = "\x00".join((model_key, system_prompt, prompt))
        return hashlib.sha256(material.encode()).hexdigest()[:16]

    @staticmethod
    def _format_criteria(criteria: list) -> str:
        """Number the criteria and attach each one's deterministically parsed constraints.

        The model classifies; the parser owns the numbers. Agent 1 dropped
        ARISTOTLE's "ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN" to a bare
        "Liver Enzyme Elevation" label in the same run that read LVEF, haemoglobin,
        platelets and creatinine correctly -- three analytes and two thresholds in one
        sentence, not a harder number. ``parse_value_constraints`` reads it as 2.0 gt
        uln and 1.5 gte uln, so annotating turns those into something to copy.

        Lines with no threshold get no annotation, so the model never learns that one
        is always expected.

        :param criteria: criterion strings in prompt order.
        :returns: the formatted block, or the placeholder when empty.
        """
        from src.services.value_constraint import annotate_value_constraints

        lines = []
        for index, criterion in enumerate(criteria):
            lines.append(f"  {index + 1}. {criterion}")
            annotation = annotate_value_constraints(str(criterion))
            if annotation:
                lines.append(annotation)
        return "\n".join(lines) or "  None specified"

    @staticmethod
    def _count_value_constraints(criteria: list) -> int:
        """Total thresholds the deterministic parser finds across these criterion lines.

        Ground truth for the Step 6 coverage check in parse_nct(): computed the same
        way _format_criteria's annotations are, so the two describe the same numbers.
        """
        from src.services.value_constraint import parse_value_constraints

        return sum(len(parse_value_constraints(str(c))) for c in criteria)

    @classmethod
    def _count_output_value_constraints(cls, rules: list) -> int:
        """Total non-None value_constraint fields across rules, recursing into
        sub_criteria (Pattern E groups carry their thresholds one level down)."""
        count = 0
        for rule in rules:
            if getattr(rule, "value_constraint", None) is not None:
                count += 1
            count += cls._count_output_value_constraints(getattr(rule, "sub_criteria", None) or [])
        return count

    @classmethod
    def _flatten_rules_for_review(cls, rules: list, out: list | None = None) -> list[str]:
        """One line per rule (and each sub_criterion), for the Step 7 review prompt.

        Flattening loses nothing the reviewer needs: it only has to see each rule's
        own name/source_text/value_constraint, not the tree shape.
        """
        if out is None:
            out = []
        for rule in rules:
            name = getattr(rule, "name", "") or ""
            source_text = getattr(rule, "source_text", None) or ""
            vc = getattr(rule, "value_constraint", None)
            vc_repr = "null" if vc is None else f"{vc.op} {vc.value} ({vc.reference_bound})"
            out.append(f"- name={name!r} source_text={source_text!r} value_constraint={vc_repr}")
            cls._flatten_rules_for_review(getattr(rule, "sub_criteria", None) or [], out)
        return out

    def _llm_review_value_constraints(
        self, nct_id: str, inclusion_criteria: list, exclusion_criteria: list, ir
    ) -> list[dict]:
        """Step 7: a second, small LLM pass that reads each criterion line against
        its generated rule directly, catching the per-criterion loss Step 6's
        study-wide total can mask when another criterion over-produces.

        Detection only — does not warn and does not fix. The caller (parse_nct)
        decides what to do with the misses: try Step 8's mechanical repair first,
        warn only for what repair could not resolve.

        Fails open: a broken review call (bad JSON, network error, anything) is
        logged and swallowed, never raised — returns []. This is an additional
        check on top of Step 6, not a replacement, and a review failure must not
        fail the parse that already succeeded.

        :returns: the reviewer's "misses" list (each a dict with criterion_line,
            criterion_text, reason), or [] when nothing was flagged or the call failed.
        """
        all_criteria = list(inclusion_criteria) + list(exclusion_criteria)
        if not all_criteria:
            return []

        criteria_block = "\n".join(
            f"{i + 1}. {c}" for i, c in enumerate(all_criteria)
        )
        rules_block = "\n".join(
            self._flatten_rules_for_review(ir.target.inclusion_rules)
            + self._flatten_rules_for_review(ir.target.exclusion_rules)
        ) or "(no rules generated)"

        prompt = THRESHOLD_REVIEW_PROMPT.format(
            criteria_block=criteria_block, rules_block=rules_block
        )

        try:
            reviewer = get_llm(
                model_name=self.model_name, temperature=0.0,
                response_format={"type": "json_object"},
            )
            response = reviewer.invoke([HumanMessage(content=prompt)])
            data = self._extract_json(response.content)
            return data.get("misses") or []
        except Exception as exc:
            logger.debug(
                "[Agent 1] Step 7 threshold review failed for %s, skipping (fail-open): %s",
                nct_id, exc,
            )
            return []

    @staticmethod
    def _role_indexed_criteria(inclusion_criteria: list, exclusion_criteria: list) -> list[tuple]:
        """The criterion list Step 7's reviewer is numbered against, each line
        carrying the block it came from.

        `_llm_review_value_constraints` builds `criteria_block` from
        ``inclusion + exclusion`` numbered 1..N across BOTH blocks, and
        THRESHOLD_REVIEW_PROMPT asks for a bare 1-based ``criterion_line`` back —
        no role marker. The index therefore resolves to a *role and a text*, not
        to a text alone, and the repair step needs both: a threshold stated in an
        exclusion line belongs to an exclusion rule.

        :returns: [("inclusion" | "exclusion", criterion_text), ...] in reviewer order.
        """
        return (
            [("inclusion", str(c)) for c in inclusion_criteria]
            + [("exclusion", str(c)) for c in exclusion_criteria]
        )

    def _repair_threshold_misses(
        self, nct_id: str, inclusion_criteria: list, exclusion_criteria: list, ir, misses: list
    ) -> list:
        """Step 8: reattach the thresholds Step 7 flagged, to the rules of the
        criterion's OWN role.

        The constraint numbers were already parsed deterministically from the same
        criterion text before the first LLM call ever ran (ADR-031-B); neither path
        here re-extracts or invents a number, only decides which existing rule it
        belongs to.

          8a. Free, instant zip: safe exactly when rule-count == constraint-count,
              which holds when every analyte has its own distinct threshold.
          8b. LLM match (one call): the case 8a can't decide safely — most often a
              shared threshold ("ALT or AST > 2X ULN") where analyte-count and
              constraint-count differ on purpose. Given the text, the already-correct
              constraint list, and the candidate rule names, this asks which rule gets
              which constraint index, allowing many-to-one sharing. It is a matching
              decision, not extraction, so it does not carry the "shape separated them,
              not difficulty" extraction failure Step 6/7 exist for.

        Both are scoped to one role. Trying inclusion and falling back to exclusion
        crossed the two blocks in every direction at once: an exclusion line's
        threshold landed on a same-analyte inclusion rule (the cohort starts
        *requiring* serum creatinine > 2.0 mg/dL), the truthy return then left the
        exclusion rule at ``value_constraint=None`` so it emitted an ABSENCE rule
        with no value filter (excluding everyone who ever had that lab drawn), and
        `_repair_dropped_threshold` stamped the exclusion line over the inclusion
        rule's ``source_text`` — the provenance field ADR-032's classifier reads.

        :returns: the misses no repair path could resolve; the caller warns on those.
        """
        indexed = self._role_indexed_criteria(inclusion_criteria, exclusion_criteria)
        still_broken: list = []
        for miss in misses:
            line = miss.get("criterion_line")
            valid_line = (
                isinstance(line, int)
                and not isinstance(line, bool)
                and 1 <= line <= len(indexed)
            )
            if not valid_line:
                still_broken.append(miss)
                continue
            role, original_text = indexed[line - 1]
            rules = (
                ir.target.inclusion_rules if role == "inclusion" else ir.target.exclusion_rules
            )
            repaired = self._repair_dropped_threshold(original_text, rules)
            if not repaired:
                repaired = self._llm_match_dropped_threshold(nct_id, original_text, rules)
            if not repaired:
                still_broken.append(miss)
        return still_broken

    @staticmethod
    def _collect_broken_candidates(original_text: str, rules: list) -> list:
        """Rules (recursing into sub_criteria) with no value_constraint whose
        `entity_text` or `name` anchors into `original_text`.

        The broken shape (source_text collapsed to a bare label) leaves the entity
        name itself intact — only source_text/value_constraint are lost — so the
        entity name is still a reliable anchor back to the line it came from.
        Shared by both repair paths: 8a's count-match zip and 8b's LLM match.
        """
        candidates: list = []

        def _collect(items: list) -> None:
            for rule in items:
                if getattr(rule, "value_constraint", None) is None:
                    anchor = (getattr(rule, "entity_text", None) or getattr(rule, "name", None) or "")
                    if anchor and anchor.lower() in original_text.lower():
                        candidates.append(rule)
                _collect(getattr(rule, "sub_criteria", None) or [])

        _collect(rules)
        return candidates

    @classmethod
    def _repair_dropped_threshold(cls, original_text: str, rules: list) -> int:
        """Step 8a: mechanically reattach a threshold Step 7 found missing.

        No LLM call. Safe only when the candidate-rule count exactly equals the
        parsed-constraint count for this line — i.e. every analyte has its own
        distinct threshold, in the same order the rules were generated in. A count
        mismatch (most often a shared threshold, "ALT or AST > 2X ULN") means the
        mapping is ambiguous; assigning constraint N to the wrong analyte would
        silently apply the wrong threshold, worse than leaving it missing, so this
        refuses to guess and returns 0 — the caller falls back to Step 8b.

        :returns: how many rules were repaired (0 means: not attempted here).
        """
        from src.services.value_constraint import parse_value_constraints

        constraints = parse_value_constraints(original_text)
        if not constraints:
            return 0

        candidates = cls._collect_broken_candidates(original_text, rules)
        if len(candidates) != len(constraints):
            return 0

        for rule, constraint in zip(candidates, constraints):
            rule.value_constraint = constraint
            rule.source_text = original_text
        return len(candidates)

    def _llm_match_dropped_threshold(self, nct_id: str, original_text: str, rules: list) -> int:
        """Step 8b: when 8a can't confirm a safe 1:1 count match — typically a
        shared threshold, where analyte-count and constraint-count differ on
        purpose — ask a small, constrained LLM call which existing rule gets which
        already-correct constraint, allowing many-to-one sharing.

        The LLM never invents, re-derives, or rounds a number: `constraints` is
        already the correct output of parse_value_constraints(original_text); this
        call only decides an assignment. That is a matching decision, not
        extraction, so it does not carry the "shape separated them, not
        difficulty" extraction failure Step 6/7 exist for.

        Fails open: any error (network, malformed JSON, an out-of-range index)
        leaves every candidate untouched and returns 0 — Step 7's warning stands.
        """
        from src.services.value_constraint import parse_value_constraints

        constraints = parse_value_constraints(original_text)
        candidates = self._collect_broken_candidates(original_text, rules)
        if not constraints or not candidates:
            return 0

        constraints_block = "\n".join(
            f"{i}: {c.op} {c.value} ({c.reference_bound}"
            f"{', ' + c.unit_text if c.unit_text else ''})"
            for i, c in enumerate(constraints)
        )
        rules_block = "\n".join(
            f"{i}: {(getattr(r, 'entity_text', None) or getattr(r, 'name', '') or '')!r}"
            for i, r in enumerate(candidates)
        )
        prompt = THRESHOLD_MATCH_PROMPT.format(
            original_text=original_text,
            constraints_block=constraints_block,
            rules_block=rules_block,
        )

        try:
            matcher = get_llm(
                model_name=self.model_name, temperature=0.0,
                response_format={"type": "json_object"},
            )
            response = matcher.invoke([HumanMessage(content=prompt)])
            data = self._extract_json(response.content)
            mapping = data.get("mapping") or []
        except Exception as exc:
            logger.debug(
                "[Agent 1] Step 8b LLM match failed for %s, skipping (fail-open): %s",
                nct_id, exc,
            )
            return 0

        repaired = 0
        for entry in mapping:
            rule_index = entry.get("rule_index")
            constraint_index = entry.get("constraint_index")
            if not isinstance(rule_index, int) or not isinstance(constraint_index, int):
                continue
            if not (0 <= rule_index < len(candidates)) or not (0 <= constraint_index < len(constraints)):
                continue
            rule = candidates[rule_index]
            if rule.value_constraint is not None:
                continue  # already resolved by an earlier entry — don't overwrite
            rule.value_constraint = constraints[constraint_index]
            rule.source_text = original_text
            repaired += 1
        return repaired

    @staticmethod
    def _discover_pdfs(papers_dir: str) -> list:
        """
        Discover and sort PDFs in a directory by role priority.
        
        Priority order: appendix/supplement > protocol > main paper.
        This ensures supplementary criteria (most complete) are merged last,
        overriding less complete sources.
        """
        from pathlib import Path
        
        pdf_dir = Path(papers_dir)
        if not pdf_dir.exists():
            return []
        
        pdfs = list(pdf_dir.glob("*.pdf"))
        if not pdfs:
            return []
        
        def classify(name: str) -> tuple:
            """Returns (priority, role). Lower priority = processed first."""
            name_lower = name.lower()
            if "appendix" in name_lower or "supplement" in name_lower or "supp" in name_lower:
                return (2, "supplement")
            elif "protocol" in name_lower:
                return (1, "protocol")
            else:
                return (0, "main")
        
        results = []
        for pdf in sorted(pdfs):
            priority, role = classify(pdf.name)
            results.append({
                "path": str(pdf),
                "name": pdf.name,
                "role": role,
                "priority": priority,
            })
        
        # Sort: main first, supplement last (supplement overrides with merge)
        results.sort(key=lambda x: x["priority"])
        return results
    
    # A protocol and a supplement are both the trial's own text; ClinicalTrials.gov
    # is a summary of it. Merging the two as equals duplicates every criterion they
    # share, and Circe ANDs InclusionRules, so a duplicate is an extra mandatory
    # rule rather than a redundant one. On ARISTOTLE that turned "one or more of
    # the following risk factors" back into an AND: the collapsed five-way ANY rule
    # stood, and merge added the registry's diabetes-or-hypertension,
    # TIA-or-embolism and LVEF criteria as three further rules the patient also had
    # to satisfy. "Age >= 18 years" arrived twice for the same reason.
    #
    # "main" stays on merge. It is whatever the classifier could not place — a
    # results paper, a design paper — and does not get to override the registry.
    _PDF_AUTHORITATIVE_ROLES = frozenset({"protocol", "supplement"})

    @classmethod
    def _strategy_for_role(cls, role: str) -> str:
        """Which enrichment strategy a PDF's role selects.

        :param role: "main", "protocol" or "supplement", from _discover_pdfs.
        :returns: "supplement_priority" when the PDF is the trial's own text,
            else "merge".
        """
        return "supplement_priority" if role in cls._PDF_AUTHORITATIVE_ROLES else "merge"

    # Appended to every per-PDF failure. `_enrich_from_pdf` runs once per
    # discovered PDF, so one PDF failing is not the study failing. On the
    # 2026-09-07 cold run ARISTOTLE's appendix failed three lines after its own
    # protocol had succeeded (5 -> 9 inclusion, 0 -> 21 exclusion), and the pair
    # was read as a single verdict: "PDF enrichment is broken for ARISTOTLE".
    _PDF_FAILURE_SCOPE_NOTE = (
        "This is one PDF, not the study — other PDFs for this study may still succeed."
    )

    @staticmethod
    def _report_pdf_outcome(pdf_name: str, message: str, *, degraded: bool = False) -> None:
        """Announce one per-PDF enrichment outcome, on one channel, in one line.

        Success used to go through ``logger.info`` and failure through
        ``warnings.warn``. Measured in-container on 2026-09-07: this module's
        logger has effective level WARNING and the root logger has no handlers,
        so the INFO record produced no output while the warning did — a reader
        of an unconfigured run saw only the failures and read the pipeline as
        more broken than it was. Both outcomes now go to stdout, alongside the
        progress lines this module already prints, so one cannot appear without
        the other.

        Configuring logging stays the entry point's job
        (``scripts/reingest_protocol_pdfs.py`` calls ``configure_logging``);
        nothing here touches logging configuration.

        :param pdf_name: Basename of the PDF this outcome belongs to. Every
            outcome names its PDF, because a study has several and the log
            interleaves them.
        :param message: What happened. Newlines are collapsed so one outcome is
            one grep-able line.
        :param degraded: True when the result is worse than intended — a
            failure, a fallback, a truncation. Marked ``⚠`` so a reader can
            separate the degraded outcomes from the healthy ones.
        """
        marker = "⚠" if degraded else "•"
        where = f"[{pdf_name}] " if pdf_name else ""
        print(f"[Agent 1] {marker} {where}{' '.join(message.split())}")

    @classmethod
    def _report_pdf_failure(cls, pdf_name: str, message: str) -> None:
        """Announce a per-PDF enrichment failure, scoped to that PDF.

        :param pdf_name: Basename of the PDF that failed.
        :param message: Why it failed.
        """
        cls._report_pdf_outcome(
            pdf_name,
            f"PDF enrichment FAILED: {message} {cls._PDF_FAILURE_SCOPE_NOTE}",
            degraded=True,
        )

    def _enrich_from_pdf(
        self, trial_data: TrialData, pdf_path: str, role: str = "main"
    ) -> TrialData:
        """
        Enrich TrialData with eligibility criteria extracted from a design paper PDF.

        Args:
            trial_data: Current TrialData to enrich.
            pdf_path: Path to PDF file.
            role: PDF role — "main", "protocol", or "supplement".
                  Supplements use supplement_priority strategy (PDF as base).

        Uses pdftotext to extract full text, then parses inclusion/exclusion sections.
        """
        import subprocess

        pdf_name = os.path.basename(pdf_path)
        print(f"[Agent 1] 📄 Enriching from PDF: {pdf_path}")

        try:
            result = subprocess.run(
                ['pdftotext', pdf_path, '-'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                self._report_pdf_failure(
                    pdf_name,
                    f"pdftotext returned code {result.returncode}. "
                    f"stderr: {result.stderr[:200]}",
                )
                return trial_data

            full_text = result.stdout
            if not full_text or len(full_text) < 100:
                self._report_pdf_failure(
                    pdf_name,
                    f"extracted text too short ({len(full_text or '')} chars).",
                )
                return trial_data

            # Clean up PDF artifacts
            full_text = re.sub(r'Downloaded from .*?\n', '', full_text)
            full_text = re.sub(r'Copyright © .*?\n', '', full_text)
            full_text = re.sub(r'\f', '\n', full_text)
            
            # Extract ONLY the eligibility criteria section, not the entire PDF.
            # This prevents tables, figures, author lists etc. from being parsed as criteria.
            # The whole-paper fallback stays: Missing is the extractor failing, and
            # the caller is the only place that may decide to read the rest.
            section_result = extract_eligibility_section(full_text)

            if isinstance(section_result, Missing):
                # Not a neutral note. The section extractor exists to keep tables,
                # figures and author lists out of the criteria; parsing the whole
                # paper is the failure mode it was written to prevent, and on the
                # 2026-09-07 cold run it ran over as much as 153431 chars.
                self._report_pdf_outcome(
                    pdf_name,
                    f"DEGRADED: no eligibility section found — parsing the whole paper "
                    f"({len(full_text)} chars) instead, so tables, figures and author "
                    f"lists can be read as criteria.",
                    degraded=True,
                )
                pdf_criteria = extract_eligibility_from_text(full_text)
            else:
                if isinstance(section_result, Truncated):
                    self._report_pdf_outcome(
                        pdf_name,
                        f"eligibility section TRUNCATED at the {section_result.cap}-char cap — "
                        f"{section_result.dropped} chars of the section were dropped and "
                        f"are not read as criteria.",
                        degraded=True,
                    )
                self._report_pdf_outcome(
                    pdf_name,
                    f"eligibility section extracted: {len(section_result.text)} chars "
                    f"(from {len(full_text)} total)",
                )
                pdf_criteria = extract_eligibility_from_text(section_result.text)

            if not pdf_criteria["inclusion"] and not pdf_criteria["exclusion"]:
                self._report_pdf_failure(
                    pdf_name,
                    "no eligibility criteria found in the PDF text. The PDF may not "
                    "contain structured inclusion/exclusion sections. Proceeding with "
                    "NCT-only criteria for this PDF (likely incomplete).",
                )
                return trial_data

            strategy = self._strategy_for_role(role)
            enriched = enrich_trial_data(trial_data, pdf_criteria, strategy=strategy)
            self._report_pdf_outcome(
                pdf_name,
                f"PDF enriched ({strategy}): "
                f"{len(trial_data.inclusion_criteria)} -> "
                f"{len(enriched.inclusion_criteria)} inclusion, "
                f"{len(trial_data.exclusion_criteria)} -> "
                f"{len(enriched.exclusion_criteria)} exclusion",
            )

            return enriched

        except FileNotFoundError:
            self._report_pdf_failure(
                pdf_name,
                "pdftotext not found. Install with: brew install poppler (macOS) "
                "or apt install poppler-utils (Linux).",
            )
            return trial_data
        except Exception as e:
            self._report_pdf_failure(
                pdf_name,
                f"unexpected exception: {e}. Proceeding with NCT-only criteria "
                f"for this PDF (likely incomplete).",
            )
            return trial_data

    @staticmethod
    def _extract_eligibility_section(full_text: str, pdf_name: str = "") -> Optional[str]:
        """Compatibility wrapper — heading rules live in eligibility_section.

        Tests still import this name and expect ``Optional[str]``
        (``tests/test_pdf_eligibility_section.py``,
        ``tests/test_corpus_regression.py``'s ``section or text``).
        ``Missing`` is ``None``; ``Found`` / ``Truncated`` return the text.
        Truncation is announced at ``_enrich_from_pdf``, not here.
        """
        del pdf_name
        result = extract_eligibility_section(full_text)
        if isinstance(result, Missing):
            return None
        return result.text

    def _enrich_from_pubmed(
        self, trial_data: TrialData, nct_id: str
    ) -> tuple[TrialData, PaperStatus]:
        """
        Enrich TrialData with PubMed design paper criteria.

        Returns a tuple of (enriched TrialData, PaperStatus) so callers can
        surface enrichment source to the frontend without changing the public
        parse_nct() return type.

        Raises warnings on failures instead of silently falling back.
        """
        import warnings

        try:
            # Try to get raw NCT data for references
            from src.agents.agent1.nct_fetcher import DEFAULT_CACHE_DIR
            import json

            cache_file = DEFAULT_CACHE_DIR / f"{nct_id}.json"
            nct_raw = None
            if cache_file.exists():
                with open(cache_file) as f:
                    nct_raw = json.load(f)

            # Strategy 1: Extract PMIDs from NCT references
            pmids = []
            if nct_raw:
                pmids = get_design_paper_pmids(nct_raw)

            # Strategy 2: Search PubMed if no references found
            if not pmids:
                pmids = search_pubmed_for_nct(nct_id)

            if not pmids:
                warnings.warn(
                    f"[Agent 1] ⚠ PubMed enrichment FAILED: No PubMed links found for {nct_id}. "
                    f"Proceeding with NCT-only criteria (likely incomplete).",
                    RuntimeWarning, stacklevel=2
                )
                return trial_data, PaperStatus(source="nct_only")

            print(f"[Agent 1] 📚 Found {len(pmids)} linked papers: {pmids}")

            from src.agents.agent1.pmc_fetcher import get_pmc_eligibility, pmid_to_pmcid
            from src.agents.agent1.pmc_supplement import download_pmc_supplements

            # Priority A: PMC supplement PDFs (most complete eligibility criteria)
            for pmid in pmids:
                try:
                    pmcid = pmid_to_pmcid(pmid)
                    if pmcid:
                        downloaded = download_pmc_supplements(pmcid, nct_id)
                        supplements = [f for f in downloaded if f["role"] in ("supplement", "appendix")]
                        if supplements:
                            for pdf_info in supplements:
                                trial_data = self._enrich_from_pdf(trial_data, pdf_info["path"])
                            print(f"[Agent 1] Enriched from {len(supplements)} PMC supplement PDF(s)")
                            papers_found = [
                                PaperDownloadInfo(
                                    name=pdf_info["path"].split("/")[-1],
                                    role=pdf_info["role"],
                                    source="pmc",
                                )
                                for pdf_info in supplements
                            ]
                            return trial_data, PaperStatus(
                                source="pmc_supplement",
                                papers_found=papers_found,
                                supplement_available=True,
                                manual_download_needed=False,
                            )
                except Exception as _pmc_supp_err:
                    warnings.warn(
                        f"[Agent 1] PMC supplement download failed for PMID {pmid}: {_pmc_supp_err}",
                        RuntimeWarning, stacklevel=2
                    )

            # Priority B: PMC full-text eligibility
            for pmid in pmids:
                try:
                    pmc_criteria = get_pmc_eligibility(pmid)
                    if pmc_criteria and (pmc_criteria["inclusion"] or pmc_criteria["exclusion"]):
                        enriched = enrich_trial_data(trial_data, pmc_criteria, strategy="merge")
                        print(f"[Agent 1] Enriched from PMC full-text (PMID {pmid})")
                        return enriched, PaperStatus(
                            source="pmc_fulltext",
                            papers_found=[
                                PaperDownloadInfo(
                                    name=f"PMID_{pmid}_fulltext",
                                    role="main",
                                    source="pmc",
                                )
                            ],
                            supplement_available=False,
                            manual_download_needed=False,
                        )
                except Exception as _pmc_ft_err:
                    warnings.warn(
                        f"[Agent 1] PMC full-text lookup failed for PMID {pmid}: {_pmc_ft_err}",
                        RuntimeWarning, stacklevel=2
                    )

            # Priority C: journal direct download when PMC failed
            # Attempt to resolve DOI and download from the publisher.
            first_pmid = pmids[0]
            doi = extract_doi_from_pubmed(first_pmid)
            if doi:
                logger.info("[Agent 1] Attempting journal download for DOI %s (PMID %s)", doi, first_pmid)
                from pathlib import Path as _Path
                papers_base = _Path(__file__).resolve().parents[3] / "data" / "papers"
                attempts = download_papers_for_doi(doi, nct_id, papers_dir=papers_base)

                downloaded_files = [a for a in attempts if a.status == "downloaded"]
                if downloaded_files:
                    # Enrich from any downloaded PDFs
                    for attempt in downloaded_files:
                        if attempt.saved_path:
                            trial_data = self._enrich_from_pdf(
                                trial_data, attempt.saved_path, role=attempt.role
                            )
                    print(f"[Agent 1] Enriched from {len(downloaded_files)} journal download(s)")
                    papers_found = [
                        PaperDownloadInfo(
                            name=a.saved_path.split("/")[-1] if a.saved_path else f"paper_{a.role}.pdf",
                            role=a.role,
                            source="journal_download",
                        )
                        for a in downloaded_files
                    ]
                    return trial_data, PaperStatus(
                        source="journal_download",
                        papers_found=papers_found,
                        supplement_available=any(a.role in ("supplement", "appendix") for a in downloaded_files),
                        manual_download_needed=False,
                        download_results=[
                            DownloadResult(
                                url=a.url, role=a.role, status=a.status, saved_path=a.saved_path
                            )
                            for a in attempts
                        ],
                    )

                # All downloads failed — record URLs for frontend display
                url_infos = build_paper_urls(doi)
                download_urls = [
                    DownloadUrl(
                        journal=u.get("journal"),
                        doi=doi,
                        article_url=u["url"],
                        supplement_hint=u.get("hint"),
                        role=u["role"],
                    )
                    for u in url_infos
                ]
                download_results = [
                    DownloadResult(url=a.url, role=a.role, status=a.status, saved_path=a.saved_path)
                    for a in attempts
                ]
                logger.info(
                    "[Agent 1] Journal download failed for DOI %s — recording URLs for manual download",
                    doi,
                )
                # Fall through to PubMed abstract with URLs captured
                pubmed_paper_status_kwargs = {
                    "manual_download_needed": True,
                    "download_urls": download_urls,
                    "download_results": download_results,
                }
            else:
                pubmed_paper_status_kwargs = {
                    "manual_download_needed": True,
                }

            # Priority D: PubMed abstract fallback
            paper = fetch_pubmed_abstract(first_pmid)
            if not paper or not paper.abstract:
                warnings.warn(
                    f"[Agent 1] ⚠ PubMed enrichment FAILED: Could not fetch abstract for PMID {first_pmid}. "
                    f"Proceeding with NCT-only criteria (likely incomplete).",
                    RuntimeWarning, stacklevel=2
                )
                return trial_data, PaperStatus(source="nct_only", **pubmed_paper_status_kwargs)

            # Extract eligibility criteria from abstract
            pubmed_criteria = extract_eligibility_from_text(paper.abstract)

            if not pubmed_criteria["inclusion"] and not pubmed_criteria["exclusion"]:
                warnings.warn(
                    f"[Agent 1] ⚠ PubMed enrichment FAILED: No eligibility criteria found in PMID {first_pmid} abstract "
                    f"({len(paper.abstract)} chars). PubMed abstracts typically do NOT contain detailed "
                    f"eligibility criteria. Consider using full-text PDF instead. "
                    f"Proceeding with NCT-only criteria (likely incomplete).",
                    RuntimeWarning, stacklevel=2
                )
                return trial_data, PaperStatus(source="nct_only", **pubmed_paper_status_kwargs)

            # Enrich TrialData
            enriched = enrich_trial_data(trial_data, pubmed_criteria, strategy="merge")
            print(f"[Agent 1] ✅ Enriched: {len(trial_data.inclusion_criteria)} → "
                  f"{len(enriched.inclusion_criteria)} inclusion, "
                  f"{len(trial_data.exclusion_criteria)} → "
                  f"{len(enriched.exclusion_criteria)} exclusion")

            return enriched, PaperStatus(
                source="pubmed_abstract",
                papers_found=[
                    PaperDownloadInfo(
                        name=f"PMID_{first_pmid}_abstract",
                        role="main",
                        source="pmc",
                    )
                ],
                supplement_available=False,
                **pubmed_paper_status_kwargs,
            )

        except Exception as e:
            warnings.warn(
                f"[Agent 1] ⚠ PubMed enrichment FAILED with exception: {e}. "
                f"Proceeding with NCT-only criteria (likely incomplete).",
                RuntimeWarning, stacklevel=2
            )
            return trial_data, PaperStatus(source="nct_only")
    
    def _invoke_and_extract(self, messages: list, what: str) -> dict:
        """One LLM call, checked for truncation before anything tries to parse it.

        Both extraction entry points go through here so the check cannot be added to
        one and forgotten on the other -- and it was the NCT path that failed. A
        response stopped at ``max_model_len`` is a prefix of the answer, so handing it
        to ``_extract_json`` produces a JSON syntax error describing the wrong problem:
        the cold six-study run of 2026-09-06 read PLATO's exhausted budget as
        ``Expecting value: line 754 column 16`` and CAROLINA's as ``Unterminated
        string starting at: line 523 column 24``.

        The observed token split is logged on every call, truncated or not, so the
        headroom is visible while it is still shrinking rather than only once it is
        gone.

        :param messages: the chat turns to send.
        :param what: short name of this call, used in the log and error message.
        :returns: the parsed JSON payload.
        :raises LLMTruncationError: the completion hit the token ceiling.
        :raises ValueError: the model finished but the body is not JSON.
        """
        response = self.llm.invoke(messages)
        usage = token_usage(response)
        if usage:
            logger.info(
                "[Agent 1] %s token usage: prompt=%s completion=%s total=%s",
                what,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
        raise_if_truncated(response, what=what)
        return self._extract_json(response.content)

    def _extract_json(self, content: str) -> dict:
        """Extract and parse JSON from LLM response content."""
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            print(f"[Agent 1] JSON parsing error: {e}")
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")
    
    def _build_artemis_request(self, data) -> ARTEMISRequest:
        """
        Build ARTEMISRequest from parsed JSON data.
        """
        # Fallback: LLM sometimes returns a flat list of criteria dicts
        # instead of the expected {target, comparator, outcome} structure.
        # This is a valid fallback — the list contains correct entity_text,
        # domain, and logic_type fields that downstream agents can consume.
        if isinstance(data, list):
            logger.info(
                f"[Agent 1] LLM returned flat list ({len(data)} items) "
                f"instead of {{target, comparator, outcome}} dict — "
                f"wrapping into ARTEMISRequest via list fallback"
            )
            inclusion = []
            exclusion = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                logic = item.get("logic_type", "PRESENCE").upper().strip()
                if logic == "ABSENCE":
                    exclusion.append(item)
                else:
                    inclusion.append(item)
            data = {
                "target": {
                    "primary_criteria": inclusion[0] if inclusion else (exclusion[0] if exclusion else {}),
                    "inclusion_rules": inclusion,
                    "exclusion_rules": exclusion,
                },
                "comparator": {},
                "outcome": {},
            }

        target = self._build_cohort_definition(data.get("target", {}))
        comparator = self._build_cohort_definition(data.get("comparator", {}))
        outcome = self._build_outcome(data.get("outcome", {}))
        
        return ARTEMISRequest(
            target=target,
            comparator=comparator,
            outcome=outcome
        )
    
    def _build_cohort_definition(self, data: dict) -> CohortDefinition:
        """Build CohortDefinition from dict."""
        pc_data = data.get("primary_criteria", {})
        primary_criteria = PrimaryCriteria(
            domain=pc_data.get("domain", "Condition"),
            entity_text=pc_data.get("entity_text"),
            limit=pc_data.get("limit", "First"),
            observation_window=pc_data.get("observation_window", {"prior": 365, "post": 0})
        )
        
        inclusion_rules = [
            self._build_criteria(c, rule_name=c.get("name")) for c in data.get("inclusion_rules", [])
        ]
        exclusion_rules = [
            self._build_criteria(c, force_logic_type="ABSENCE", rule_name=c.get("name"))
            for c in data.get("exclusion_rules", [])
        ]
        
        # Pattern E post-parse repair: merge flat CV/risk factor OR groups
        inclusion_rules = self._repair_pattern_e(inclusion_rules)

        # C2Q-inspired post-parse validation
        self._validate_measurement_rules(inclusion_rules, "inclusion")
        self._validate_measurement_rules(exclusion_rules, "exclusion")

        return CohortDefinition(
            primary_criteria=primary_criteria,
            inclusion_rules=inclusion_rules,
            exclusion_rules=exclusion_rules,
            exit_strategy=data.get("exit_strategy", "OBSERVATION_END")
        )
    
    def _validate_measurement_rules(self, rules: list, rule_type: str) -> None:
        """Post-parse validation: warn if Measurement criteria lack value_constraint.
        
        Inspired by C2Q 3.0's structured attribute handling (Park et al, 2024).
        Recurses into sub_criteria for composite rules.
        """
        for rule in rules:
            if rule.domain == "Measurement" and rule.value_constraint is None:
                logger.warning(
                    f"[Agent 1] ⚠ Measurement {rule_type} rule '{rule.name}' "
                    f"(entity: '{rule.entity_text}') has NO value_constraint. "
                    f"This may produce incorrect cohort results. "
                    f"Consider adding op/value/unit_text."
                )
                print(
                    f"[Agent 1] ⚠ WARNING: Measurement rule '{rule.name}' "
                    f"missing value_constraint — likely LLM omission."
                )
            # Recurse into sub_criteria
            if rule.sub_criteria:
                self._validate_measurement_rules(rule.sub_criteria, rule_type)
    
    # --- Pattern E keyword clusters ---
    # ORDER MATTERS: more-specific clusters must come before less-specific ones.
    # "acs" must precede "cv_prior" because "acute coronary syndrome" contains
    # "coronary" which would otherwise match cv_prior first.
    _PATTERN_E_CLUSTERS: dict = {
        "acs": [
            "stemi", "st-elevation", "nstemi", "non-st-elevation",
            "unstable angina", "acute coronary",
        ],
        "cv_prior": [
            "mi", "myocardial infarction", "stroke", "tia", "transient ischemic",
            "revascular", "angioplasty", "coronary", "bypass", "cabg", "stenosis",
            "peripheral artery", "peripheral vascular", "carotid", "heart failure",
            "renal failure", "chronic kidney", "ckd",
        ],
        "cv_risk": [
            "microalbuminuria", "proteinuria", "hypertension", "lvh",
            "left ventricular hypertrophy", "ankle-brachial", "abi",
            "retinopathy", "neuropathy",
            "egfr", "glomerular filtration",
        ],
        "metabolic": [
            "diabetes", "t2dm", "obesity", "metabolic", "dyslipidemia", "hyperlipidemia",
        ],
    }

    @staticmethod
    def _match_cluster(rule: "Criteria") -> Optional[str]:
        """Return cluster name if rule's entity_text or name matches a cluster keyword.

        Uses word-boundary matching for short keywords (<=4 chars) to prevent
        false positives from substring collisions (e.g. 'mi' inside 'mellitus').
        """
        import re

        text = " ".join(filter(None, [rule.entity_text, rule.name])).lower()
        for cluster, keywords in LogicDecomposer._PATTERN_E_CLUSTERS.items():
            for kw in keywords:
                if len(kw) <= 4:
                    # Use word-boundary regex for short abbreviations
                    if re.search(r"\b" + re.escape(kw) + r"\b", text):
                        return cluster
                else:
                    if kw in text:
                        return cluster
        return None

    @staticmethod
    def _is_flat_rule(rule: "Criteria") -> bool:
        """A flat rule has no sub_criteria and group_type ALL."""
        return not rule.sub_criteria and rule.group_type == "ALL"

    @staticmethod
    def _repair_pattern_e(rules: list) -> list:
        """
        Post-parse repair: merge flat inclusion rules that match the same
        CV/risk cluster into a single ANY group.

        Scans all rules (not just consecutive) and groups by cluster.
        Merges if 2+ flat rules belong to the same cluster.
        Already-grouped rules (with sub_criteria) are untouched.
        """
        if not rules:
            return rules

        # Pass 1: collect flat rules by cluster (non-consecutive OK)
        cluster_buckets: dict[str, list[int]] = {}
        for i, rule in enumerate(rules):
            if not LogicDecomposer._is_flat_rule(rule):
                continue
            cluster = LogicDecomposer._match_cluster(rule)
            if cluster is not None:
                cluster_buckets.setdefault(cluster, []).append(i)

        # Determine which indices to merge (cluster size >= 2)
        merge_indices: set[int] = set()
        merge_map: dict[int, str] = {}  # index → cluster name
        for cluster, indices in cluster_buckets.items():
            if len(indices) >= 2:
                for idx in indices:
                    merge_indices.add(idx)
                    merge_map[idx] = cluster

        if not merge_indices:
            return rules

        # Pass 2: build result, inserting merged groups at first occurrence
        result: list = []
        emitted_clusters: set[str] = set()
        for i, rule in enumerate(rules):
            if i not in merge_indices:
                result.append(rule)
                continue

            cluster = merge_map[i]
            if cluster in emitted_clusters:
                continue  # already merged into group

            # Collect all rules in this cluster (preserving original order)
            run = [rules[idx] for idx in cluster_buckets[cluster]]
            cluster_label = cluster.replace("_", " ").title()
            # This label is synthesised here, so it has no JSON of its own to read a
            # line from -- yet `_criteria_from_ir` emits it as a store row alongside
            # its members, and a row with no line is the record this whole field
            # exists to prevent. Where every member came from one line, that line is
            # the label's line as well. Where they came from different lines there is
            # no single line between them, and naming one of them would attribute the
            # others' criteria to it -- so the label claims none, and each member
            # keeps its own.
            member_lines = {(rule.source_text or "").strip() for rule in run}
            merged_source_text = (
                member_lines.pop() if len(member_lines) == 1 else None
            ) or None
            merged = Criteria(
                name=f"{cluster_label} (OR group)",
                domain=run[0].domain,
                entity_text=None,
                source_text=merged_source_text,
                logic_type=run[0].logic_type,
                window=run[0].window,
                value_constraint=None,
                sub_criteria=run,
                group_type="ANY",
            )
            logger.info(
                "[Agent 1] Pattern E repair: merged %d non-consecutive '%s' rules into ANY group",
                len(run),
                cluster,
            )
            result.append(merged)
            emitted_clusters.add(cluster)

        return result

    def _build_criteria(self, data: dict, force_logic_type: str = None, rule_name: str = None) -> Criteria:
        """Build Criteria from dict.

        Args:
            data: Dict from LLM JSON output.
            force_logic_type: If set, override logic_type to this value.
                Used for exclusion_rules where LLM often outputs "PRESENCE"
                instead of the correct "ABSENCE".
        """
        window = None
        if isinstance(data.get("window"), dict):
            window = TemporalWindow(**data["window"])
        
        value_constraint = None
        if "value_constraint" in data and data["value_constraint"]:
            vc_data = data["value_constraint"]
            # Normalize field names from LLM output variations
            normalized_vc = {
                "op": vc_data.get("op") or self._normalize_operator(vc_data.get("operator", "gt")),
                "value": vc_data.get("value", 0),
                "unit_text": vc_data.get("unit_text") or vc_data.get("unit"),
                "unit_concept_id": vc_data.get("unit_concept_id")
            }
            try:
                value_constraint = ValueConstraint(**normalized_vc)
            except ValidationError as exc:
                logger.warning(
                    "[Agent 1] Ignoring invalid value_constraint for rule '%s': %s (input=%s)",
                    data.get("name", "Unnamed Rule"),
                    exc,
                    normalized_vc,
                )
                value_constraint = None
        
        # Determine logic_type: force_logic_type overrides LLM output
        llm_logic_type = data.get("logic_type", "PRESENCE")
        if force_logic_type and llm_logic_type != force_logic_type:
            logger.warning(
                f"[Agent 1] ⚠ Polarity override: '{data.get('name', 'Unnamed')}' "
                f"had logic_type='{llm_logic_type}' → forced to '{force_logic_type}'"
            )
            logic_type = force_logic_type
        else:
            logic_type = force_logic_type or llm_logic_type
        
        entity_text = self._normalize_entity_text(
            data.get("entity_text"), data.get("domain", "Condition"), rule_name=rule_name
        )

        # Parse sub_criteria for composite rules (Pattern E: OR grouping)
        sub_criteria_data = data.get("sub_criteria", [])
        sub_criteria = []
        if sub_criteria_data and isinstance(sub_criteria_data, list):
            for sc_data in sub_criteria_data:
                if not isinstance(sc_data, dict):
                    continue
                sc = self._build_criteria(
                    sc_data,
                    force_logic_type=force_logic_type,
                    rule_name=sc_data.get("name"),
                )
                sub_criteria.append(sc)
        
        group_type = data.get("group_type", "ALL")
        if isinstance(group_type, str):
            group_type = group_type.strip().upper()
        if group_type not in ("ALL", "ANY"):
            logger.warning(
                f"[Agent 1] Invalid group_type '{data.get('group_type')}' for rule "
                f"'{data.get('name', 'Unnamed')}' — defaulting to 'ALL'"
            )
            group_type = "ALL"

        return Criteria(
            name=data.get("name", "Unnamed Rule"),
            domain=data.get("domain", "Condition"),
            entity_text=entity_text,
            # The protocol's own line, as the extraction prompt requires the model to
            # copy it ("`source_text` is MANDATORY on every rule and must be the
            # protocol's own line, verbatim" -- prompts.py). This constructor names
            # every field it wants, one at a time, so a field it does not name is a
            # field the IR object never has -- however faithfully the model emitted
            # it and however completely `data/cache/agent1_ir/` recorded it.
            #
            # `source_text` was that field. It has been mandatory in the prompt and
            # declared on `Criteria` throughout, and every rule of every cached run
            # carries it (36/36 on NCT01179048's cache), but nothing read it here, so
            # the IR reaching the store had `source_text=None` on every criterion of
            # every study and `protocolLine` was stamped empty 578 times out of 578.
            # Steps 8a/8b assign `rule.source_text` too, but only on a rule whose
            # threshold they repair, which is why the field was not uniformly absent
            # and no downstream reader noticed.
            source_text=data.get("source_text"),
            logic_type=logic_type,
            window=window,
            value_constraint=value_constraint,
            sub_criteria=sub_criteria,
            group_type=group_type,
            conditional=bool(data.get("conditional", False)),
        )

    @staticmethod
    def _normalize_entity_text(entity_text: Optional[str], domain: str, rule_name: str = None) -> Optional[str]:
        if not entity_text or not domain:
            return entity_text
        if domain.lower() != "drug":
            return entity_text
        return LogicDecomposer._normalize_drug_entity_text(entity_text, rule_name)

    @staticmethod
    def _normalize_drug_entity_text(entity_text: str, rule_name: Optional[str] = None) -> str:
        """
        Normalize Drug entity_text to prevent over-expansion in Agent2.

        General-purpose guardrail that strips parenthetical content and
        trailing generalizations from drug names. Agent2 handles hierarchy
        expansion, so parenthetical details are redundant.
        """
        import re

        text = entity_text.strip()
        if not text:
            return text

        # Pattern 1: Remove ALL parenthetical content
        # Agent2 handles hierarchy expansion — parenthetical lists are noise
        cleaned = re.sub(r'\s*\([^)]*\)', '', text).strip()

        # Pattern 2: Remove trailing "or other X" clauses
        cleaned = re.sub(r'\s+or\s+other\s+\w+.*$', '', cleaned, flags=re.IGNORECASE).strip()

        # Pattern 3: Clean up dangling commas/spaces
        cleaned = re.sub(r',\s*$', '', cleaned).strip()

        if cleaned and cleaned != text:
            logger.info(f"[Agent1] Drug entity normalized: '{text}' → '{cleaned}'")

        return cleaned or text
    
    def _normalize_operator(self, op_str: str) -> str:
        """Normalize operator string from LLM output to expected format."""
        op_map = {
            ">": "gt", ">=": "gte", "<": "lt", "<=": "lte", "=": "eq", "==": "eq",
            "greater": "gt", "less": "lt", "equal": "eq",
            "greater_than": "gt", "less_than": "lt", "greater_or_equal": "gte", "less_or_equal": "lte"
        }
        return op_map.get(op_str, op_str)
    
    def _build_outcome(self, data: dict) -> CohortOutcome:
        """Build CohortOutcome from dict."""
        tar_data = data.get("time_at_risk", {"start": 0, "end": 365})
        time_at_risk = TemporalWindow(**tar_data)
        
        return CohortOutcome(
            name=data.get("name", "Outcome"),
            domain=data.get("domain", "Condition"),
            entity_text=data.get("entity_text"),
            time_at_risk=time_at_risk
        )
    



# Lazy singleton - don't initialize at import time
_agent1_instance = None

def get_agent1(model_name: str | None = None) -> LogicDecomposer:
    """Get or create Agent 1 instance (lazy initialization).

    When model_name is provided, returns a fresh instance using that model.
    When model_name is None, returns (or creates) the cached singleton.
    """
    global _agent1_instance
    if model_name is not None:
        return LogicDecomposer(model_name=model_name)
    if _agent1_instance is None:
        _agent1_instance = LogicDecomposer()
    return _agent1_instance

# For backwards compatibility (but may fail without API keys)
agent1 = None  # Use get_agent1() instead
