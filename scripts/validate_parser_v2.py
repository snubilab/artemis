import subprocess, sys, os, importlib

# Direct import of the module to avoid __init__.py pulling in settings
sys.path.insert(0, "/Users/kyh/Workspace/Broadsea/artemis")
loader = importlib.util.spec_from_file_location(
    "pubmed_fetcher",
    "/Users/kyh/Workspace/Broadsea/artemis/src/agents/agent1/pubmed_fetcher.py",
)
mod = importlib.util.module_from_spec(loader)
loader.loader.exec_module(mod)
extract_eligibility_from_text = mod.extract_eligibility_from_text

def pdf_text(path):
    r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
    return r.stdout

papers_dir = "/Users/kyh/Workspace/Broadsea/artemis/data/papers"

trials = {
    "LEADER": "NCT01179048",
    "ARISTOTLE": "NCT00412984",
    "PLATO": "NCT00391872",
}

for name, nct in trials.items():
    trial_dir = os.path.join(papers_dir, nct)
    if not os.path.isdir(trial_dir):
        print(f"\n{'='*60}\n{name} ({nct}): directory not found, SKIP\n{'='*60}")
        continue

    pdfs = [f for f in os.listdir(trial_dir) if f.endswith(".pdf")]
    print(f"\n{'='*60}\n{name} ({nct}): {len(pdfs)} PDFs found: {pdfs}\n{'='*60}")

    for pdf_name in pdfs:
        pdf_path = os.path.join(trial_dir, pdf_name)
        text = pdf_text(pdf_path)
        if not text.strip():
            print(f"  {pdf_name}: empty text output")
            continue

        result = extract_eligibility_from_text(text)
        inc = result["inclusion"]
        exc = result["exclusion"]
        print(f"\n  {pdf_name}:")
        print(f"    Inclusion: {len(inc)} items")
        for i, item in enumerate(inc[:5]):
            print(f"      [{i+1}] {item[:100]}")
        if len(inc) > 5:
            print(f"      ... and {len(inc)-5} more")
        print(f"    Exclusion: {len(exc)} items")
        for i, item in enumerate(exc[:5]):
            print(f"      [{i+1}] {item[:100]}")
        if len(exc) > 5:
            print(f"      ... and {len(exc)-5} more")

        # LEADER-specific checks
        if name == "LEADER" and "appendix" in pdf_name.lower():
            print(f"\n    --- LEADER CHECKS ---")
            print(f"    Exclusion count OK? {5 <= len(exc) <= 25} (got {len(exc)}, expect 10-20)")
            o_prefix = [item for item in inc + exc if item.startswith("o ")]
            print(f"    'o ' prefix artifacts: {len(o_prefix)} (expect 0)")
            short_items = [item for item in inc + exc if len(item) < 15]
            print(f"    Very short items (<15 chars): {len(short_items)} -- {short_items[:5]}")
