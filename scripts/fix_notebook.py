import json

with open("notebooks/artemis_step_by_step.ipynb", "r") as f:
    nb = json.load(f)

for cell in nb["cells"]:
    if cell["cell_type"] == "code":
        src = "".join(cell["source"])
        if "EndStrategy" in src and "circe" in src:
            cell["source"] = [s.replace(
                "circe.get('EndStrategy', {}).get('DateOffset', 'N/A')",
                "(circe.get('EndStrategy') or {}).get('DateOffset', 'N/A')"
            ) for s in cell["source"]]
            cell["outputs"] = []
            cell["execution_count"] = None
            print("Fixed EndStrategy None check")
            break

with open("notebooks/artemis_step_by_step.ipynb", "w") as f:
    json.dump(nb, f, indent=4, ensure_ascii=False)
print("Done")
