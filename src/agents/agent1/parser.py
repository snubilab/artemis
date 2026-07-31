"""
Agent 1 (Logic Decomposer) - NLU Parser.
Converts natural language clinical queries or NCT protocols to ARTEMIS IR using LLM.
"""
import json
import logging
from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import ValidationError

logger = logging.getLogger(__name__)

from src.utils.llm import get_llm, resolve_model
from src.models.ir import ARTEMISRequest, CohortDefinition, PrimaryCriteria, Criteria, CohortOutcome, TemporalWindow, ValueConstraint
from src.agents.agent1.prompts import (
    SYSTEM_PROMPT, DECOMPOSITION_PROMPT,
    NCT_SYSTEM_PROMPT, NCT_DECOMPOSITION_PROMPT
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
    import re

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
        response = self.llm.invoke(messages)
        
        # Parse JSON from response
        data = self._extract_json(response.content)
        
        # Convert to ARTEMIS IR objects
        return self._build_artemis_request(data)
    
    def parse_nct(
        self,
        nct_id: str,
        json_path: Optional[str] = None,
        enrich_from_pubmed: bool = True,
        design_paper_pdf: Optional[str] = None,
        papers_dir: Optional[str] = None,
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
        import hashlib
        from datetime import datetime, timezone
        cache_dir = Path(__file__).resolve().parents[3] / "data" / "cache" / "agent1_ir"
        model_key = self.model_name.replace("/", "_").replace(":", "_")
        prompt_hash = hashlib.sha256(f"{model_key}:{prompt}".encode()).hexdigest()[:16]
        cache_file = cache_dir / f"{nct_id}_{model_key}_{prompt_hash}.json"
        meta_file = cache_dir / f"{nct_id}_{model_key}_{prompt_hash}.meta.json"

        logger.info(
            "[Agent 1] Enrichment source: %s | criteria: %d inclusion, %d exclusion | hash: %s",
            enrichment_source,
            len(trial_data.inclusion_criteria),
            len(trial_data.exclusion_criteria),
            prompt_hash,
        )

        if cache_file.exists():
            print(f"[Agent 1] 📦 Cache HIT: {cache_file.name}")
            with open(cache_file) as f:
                data = json.load(f)
        else:
            print(f"[Agent 1] 🔄 Cache MISS → calling LLM")
            response = self.llm.invoke(messages)
            data = self._extract_json(response.content)
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

        # Expose paper enrichment status for the caller
        self.last_paper_status = paper_status

        return ir
    
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
        import warnings
        import re
        
        print(f"[Agent 1] 📄 Enriching from PDF: {pdf_path}")
        
        try:
            result = subprocess.run(
                ['pdftotext', pdf_path, '-'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                warnings.warn(
                    f"[Agent 1] ⚠ PDF enrichment FAILED: pdftotext returned code {result.returncode}. "
                    f"stderr: {result.stderr[:200]}",
                    RuntimeWarning, stacklevel=2
                )
                return trial_data
            
            full_text = result.stdout
            if not full_text or len(full_text) < 100:
                warnings.warn(
                    f"[Agent 1] ⚠ PDF enrichment FAILED: Extracted text too short ({len(full_text or '')} chars).",
                    RuntimeWarning, stacklevel=2
                )
                return trial_data
            
            # Clean up PDF artifacts
            full_text = re.sub(r'Downloaded from .*?\n', '', full_text)
            full_text = re.sub(r'Copyright © .*?\n', '', full_text)
            full_text = re.sub(r'\f', '\n', full_text)
            
            # Extract ONLY the eligibility criteria section, not the entire PDF.
            # This prevents tables, figures, author lists etc. from being parsed as criteria.
            eligibility_section = self._extract_eligibility_section(full_text)
            
            if eligibility_section:
                print(f"[Agent 1] 📄 Extracted eligibility section: {len(eligibility_section)} chars "
                      f"(from {len(full_text)} total)")
                pdf_criteria = extract_eligibility_from_text(eligibility_section)
            else:
                # Fallback: use full text if no section found (e.g., short abstracts)
                print(f"[Agent 1] 📄 No eligibility section found, using full text ({len(full_text)} chars)")
                pdf_criteria = extract_eligibility_from_text(full_text)
            
            if not pdf_criteria["inclusion"] and not pdf_criteria["exclusion"]:
                warnings.warn(
                    f"[Agent 1] ⚠ PDF enrichment FAILED: No eligibility criteria found in PDF text. "
                    f"The PDF may not contain structured inclusion/exclusion sections. "
                    f"Proceeding with NCT-only criteria (likely incomplete).",
                    RuntimeWarning, stacklevel=2
                )
                return trial_data
            
            # Choose strategy based on PDF role
            strategy = "supplement_priority" if role == "supplement" else "merge"
            enriched = enrich_trial_data(trial_data, pdf_criteria, strategy=strategy)
            logger.info(
                "[Agent 1] PDF enriched (strategy=%s): %d -> %d inclusion, %d -> %d exclusion",
                strategy,
                len(trial_data.inclusion_criteria), len(enriched.inclusion_criteria),
                len(trial_data.exclusion_criteria), len(enriched.exclusion_criteria),
            )
            print(f"[Agent 1] PDF enriched ({strategy}): "
                  f"{len(trial_data.inclusion_criteria)} -> "
                  f"{len(enriched.inclusion_criteria)} inclusion, "
                  f"{len(trial_data.exclusion_criteria)} -> "
                  f"{len(enriched.exclusion_criteria)} exclusion")
            
            return enriched
            
        except FileNotFoundError:
            warnings.warn(
                f"[Agent 1] ⚠ PDF enrichment FAILED: pdftotext not found. "
                f"Install with: brew install poppler (macOS) or apt install poppler-utils (Linux).",
                RuntimeWarning, stacklevel=2
            )
            return trial_data
        except Exception as e:
            warnings.warn(
                f"[Agent 1] ⚠ PDF enrichment FAILED with exception: {e}. "
                f"Proceeding with NCT-only criteria (likely incomplete).",
                RuntimeWarning, stacklevel=2
            )
            return trial_data
    
    @staticmethod
    def _extract_eligibility_section(full_text: str) -> Optional[str]:
        """
        Extract ONLY the eligibility criteria section from PDF full text.
        
        Looks for section headings like:
        - "Inclusion and exclusion criteria"
        - "Inclusion criteria"
        - "Study Eligibility Criteria"  
        - "Section C - STUDY ELIGIBILITY CRITERIA"
        
        Terminates at the next section heading (e.g., "Figure", "Table", 
        "Section D", "Clinical event definitions", "References").
        
        Returns None if no eligibility section found.
        """
        import re
        
        if not full_text:
            return None
        
        # Patterns to find the START of the eligibility section
        start_patterns = [
            r'(?:^|\n)\s*(?:section\s+\w[\.\s\-]+\s*)?(?:study\s+)?(?:inclusion\s+and\s+exclusion\s+criteria|eligibility\s+criteria|inclusion\s+criteria)',
            r'(?:^|\n)\s*INCLUSION\s+(?:AND\s+EXCLUSION\s+)?CRITERIA',
            r'(?:^|\n)\s*(?:Section\s+\w[\.\s\-]+\s*)?STUDY\s+ELIGIBILITY\s+CRITERIA',
        ]
        
        start_pos = None
        for pattern in start_patterns:
            # Use finditer to skip TOC entries (have dotted leaders like "... 39")
            for match in re.finditer(pattern, full_text, re.IGNORECASE | re.MULTILINE):
                # Check if this is a TOC entry (dotted leaders within 300 chars)
                context = full_text[match.start():match.start() + 300]
                is_toc = bool(re.search(r'\.{3,}', context))
                if not is_toc:
                    start_pos = match.start()
                    break
            if start_pos is not None:
                break
        
        if start_pos is None:
            return None
        
        # Patterns to find the END (next section heading)
        end_patterns = [
            r'\n\s*(?:Section\s+\w[\.\s\-]+)',  # "Section D.", "Section E."
            r'\n\s*(?:Figure\s+S?\d|Table\s+S?\d)',  # "Figure S1", "Table S1"
            r'\n\s*Clinical\s+event\s+definitions?',
            r'\n\s*Definitions?\s+of\s+(?:major\s+)?clinical',
            r'\n\s*(?:Statistical\s+)?(?:Analysis|Methods|Results|References|Discussion|Sensitivity)',
            r'\n\s*Supplementary\s+(?:Table|Figure|Methods)',
        ]
        
        # Search for end after start_pos + 200 (skip the start heading itself)
        search_start = start_pos + 200
        end_pos = len(full_text)
        
        for pattern in end_patterns:
            match = re.search(pattern, full_text[search_start:], re.IGNORECASE)
            if match:
                candidate = search_start + match.start()
                if candidate < end_pos:
                    end_pos = candidate
        
        section = full_text[start_pos:end_pos].strip()
        
        # Sanity check: section should be reasonable length
        if len(section) < 50:
            return None
        if len(section) > 20000:
            # Cap at 20K chars to avoid LLM token explosion
            section = section[:20000]
        
        return section
    
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
            merged = Criteria(
                name=f"{cluster_label} (OR group)",
                domain=run[0].domain,
                entity_text=None,
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
