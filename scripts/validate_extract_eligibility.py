"""
Validate extract_eligibility_from_text against real clinical trial supplement PDFs.

Trials:
  - LEADER (NCT01179048) -- supplement appendix
  - PLATO (NCT00391872) -- supplement + main paper
  - ARISTOTLE (NCT00412984) -- skipped, directory not found

We import only the parsing functions directly to bypass __init__.py imports.
"""
import subprocess
import sys
import os
import re
import importlib.util
import types

# Load pubmed_fetcher as a standalone module to bypass __init__.py
_mod_path = "/Users/kyh/Workspace/Broadsea/artemis/src/agents/agent1/pubmed_fetcher.py"
spec = importlib.util.spec_from_file_location("pubmed_fetcher", _mod_path)
_mod = importlib.util.module_from_spec(spec)

# Stub out src.utils.llm so the LLM path doesn't crash on import
_src = types.ModuleType("src")
_src_utils = types.ModuleType("src.utils")
_src_utils_llm = types.ModuleType("src.utils.llm")
_src_utils_llm.get_llm = lambda **kw: None  # type: ignore
sys.modules["src"] = _src
sys.modules["src.utils"] = _src_utils
sys.modules["src.utils.llm"] = _src_utils_llm

spec.loader.exec_module(_mod)

extract_eligibility_from_text = _mod.extract_eligibility_from_text
_regex_parse_criteria = _mod._regex_parse_criteria


def extract_pdf_text(path: str) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", path, "-"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: pdftotext failed for {path}: {result.stderr}")
        return ""
    return result.stdout


def print_items(label: str, items: list, max_show: int = 5) -> None:
    print(f"  {label}: {len(items)} items")
    for i, item in enumerate(items[:max_show]):
        print(f"    [{i+1}] {item[:140]}")
    if len(items) > max_show:
        print(f"    ... and {len(items) - max_show} more")


def check_leader_quality(result: dict) -> None:
    print("\n=== LEADER Quality Checks ===")

    # Check exclusion count
    exc_count = len(result["exclusion"])
    if exc_count > 50:
        print(f"  FAIL: Exclusion count = {exc_count} (expected ~14, got way too many)")
    elif exc_count < 5:
        print(f"  FAIL: Exclusion count = {exc_count} (expected ~14, got too few)")
    elif 10 <= exc_count <= 20:
        print(f"  PASS: Exclusion count = {exc_count} (in expected range ~14)")
    else:
        print(f"  WARN: Exclusion count = {exc_count} (outside expected ~10-20 range)")

    inc_count = len(result["inclusion"])
    print(f"  INFO: Inclusion count = {inc_count}")

    # Check for 'o ' artifacts in inclusion
    o_artifacts = [item for item in result["inclusion"] if item.startswith("o ")]
    if o_artifacts:
        print(f"  FAIL: {len(o_artifacts)} inclusion items start with 'o ':")
        for item in o_artifacts[:5]:
            print(f"    -> {item[:100]}")
    else:
        print("  PASS: No 'o ' artifacts in inclusion items")

    # Check for 'o ' artifacts in exclusion
    o_exc = [item for item in result["exclusion"] if item.startswith("o ")]
    if o_exc:
        print(f"  FAIL: {len(o_exc)} exclusion items start with 'o ':")
        for item in o_exc[:5]:
            print(f"    -> {item[:100]}")
    else:
        print("  PASS: No 'o ' artifacts in exclusion items")

    # Check for line-wrapped fragments (very short items)
    for section_name in ["inclusion", "exclusion"]:
        short_items = [
            item for item in result[section_name]
            if len(item.split()) <= 3 and len(item) < 30
        ]
        if short_items:
            print(f"  WARN: {len(short_items)} suspiciously short {section_name} items:")
            for item in short_items[:10]:
                print(f"    -> '{item}'")
        else:
            print(f"  PASS: No suspiciously short {section_name} items (line-wrap fragments)")

    # Check for dot-filled TOC lines
    dot_items = [item for item in result["inclusion"] + result["exclusion"] if "...." in item]
    if dot_items:
        print(f"  FAIL: {len(dot_items)} items contain TOC dot-fills:")
        for item in dot_items[:3]:
            print(f"    -> {item[:100]}")
    else:
        print("  PASS: No TOC dot-fill artifacts")


# --- Trial definitions ---
trials = [
    {
        "name": "LEADER (supplement)",
        "nct": "NCT01179048",
        "pdf": "/Users/kyh/Workspace/Broadsea/artemis/data/papers/NCT01179048/nejmoa1603827_appendix.pdf",
        "quality_check": True,
    },
    {
        "name": "PLATO (supplement)",
        "nct": "NCT00391872",
        "pdf": "/Users/kyh/Workspace/Broadsea/artemis/data/papers/NCT00391872/nejm_wallentin_1045sa1.pdf",
        "quality_check": False,
    },
    {
        "name": "PLATO (main paper)",
        "nct": "NCT00391872",
        "pdf": "/Users/kyh/Workspace/Broadsea/artemis/data/papers/NCT00391872/NEJMoa0904327.pdf",
        "quality_check": False,
    },
]

# ARISTOTLE
aristotle_dir = "/Users/kyh/Workspace/Broadsea/artemis/data/papers/NCT00412984/"
if os.path.isdir(aristotle_dir):
    pdfs = [f for f in os.listdir(aristotle_dir) if f.lower().endswith(".pdf")]
    if pdfs:
        for pdf in pdfs:
            trials.append({
                "name": f"ARISTOTLE ({pdf})",
                "nct": "NCT00412984",
                "pdf": os.path.join(aristotle_dir, pdf),
                "quality_check": False,
            })
    else:
        print("ARISTOTLE: No PDFs found in directory, skipping.\n")
else:
    print("ARISTOTLE (NCT00412984): Directory not found, skipping.\n")

# --- Run extraction ---
for trial in trials:
    print(f"\n{'='*60}")
    print(f"Trial: {trial['name']} ({trial['nct']})")
    print(f"PDF:   {trial['pdf']}")
    print(f"{'='*60}")

    if not os.path.isfile(trial["pdf"]):
        print("  SKIP: PDF file not found")
        continue

    text = extract_pdf_text(trial["pdf"])
    if not text:
        print("  SKIP: No text extracted")
        continue

    print(f"  Extracted text length: {len(text)} chars")

    result = extract_eligibility_from_text(text)

    print_items("Inclusion", result["inclusion"])
    print()
    print_items("Exclusion", result["exclusion"])

    if trial.get("quality_check"):
        check_leader_quality(result)


# --- Diagnostic: manually extract LEADER exclusion section to show what SHOULD be found ---
print(f"\n{'='*60}")
print("DIAGNOSTIC: LEADER exclusion section raw text (manual extraction)")
print(f"{'='*60}")
leader_text = extract_pdf_text(
    "/Users/kyh/Workspace/Broadsea/artemis/data/papers/NCT01179048/nejmoa1603827_appendix.pdf"
)
m = re.search(r"Exclusion criteria\s*\n", leader_text, re.IGNORECASE)
if m:
    # Find end boundary
    chunk = leader_text[m.end():m.end()+3000]
    end_m = re.search(
        r"\n\s*(?:Clinical event definitions|Section|Appendix|Figure|Table \d)",
        chunk, re.IGNORECASE,
    )
    if end_m:
        exc_raw = chunk[:end_m.start()]
    else:
        exc_raw = chunk[:2000]
    print(f"  Raw exclusion text ({len(exc_raw)} chars):")
    print(exc_raw)

    # Parse it directly
    print("\n  Direct _regex_parse_criteria on this text:")
    items = _regex_parse_criteria(exc_raw)
    print(f"  -> {len(items)} items:")
    for i, item in enumerate(items):
        print(f"    [{i+1}] {item[:140]}")

# --- Diagnostic: show WHY the regex matched TOC instead of real section ---
print(f"\n{'='*60}")
print("DIAGNOSTIC: Why exclusion regex matched TOC line")
print(f"{'='*60}")
_exc_section_end = (
    r"(?="
    r"conclusion|result|discussion|statistical|"
    r"definition|clinical\s+event|endpoint|study\s+procedure|study\s+design|"
    r"section\s+[A-Z]|appendix|reference|bibliography|"
    r"supplement|figure|table\s+\d|acknowledgement|"
    r"randomization|treatment\s+period|follow-up|visit\s+schedule|"
    r"inclusion\s+criteria"
    r"|$)"
)
exc_pattern = r"(?:key\s+)?exclusion\s+criteria\s*(?:include)?[:\s]*(.*?)" + _exc_section_end

# Find ALL matches, not just the first
for i, match in enumerate(re.finditer(exc_pattern, leader_text, re.IGNORECASE | re.DOTALL)):
    captured = match.group(1).strip()
    print(f"  Match {i+1} at pos {match.start()}: captured {len(captured)} chars")
    print(f"    First 120: {repr(captured[:120])}")

print("\n  ROOT CAUSE: re.search returns the FIRST match (TOC line at pos ~749)")
print("  The real exclusion section is the LAST match. The regex should skip")
print("  TOC-like lines (those containing '...' dot-fills) or use the last match.")


print("\n\nDone.")
