"""SPEC-INFRA-003 REQ-006: the live driver's plumbing, exercised without the LLM.

`scripts/measure_emission_stability.py` copies the base store, runs the reingest entry
point once per run, reads each run's criteria back, and renders the report. The counting
and the verdicts are unit-tested in `test_infra_003_emission_stability.py`; what is left
here is the I/O around them, and it is the part that fails silently -- a store copied to
a path nothing reads, a subprocess whose non-zero exit is ignored, a run directory that
overwrites the previous one.

The real reingest needs the container, the vLLM backend, and several minutes per run, so
these substitute a stub that writes a store with a chosen criterion count per run. That
leaves exactly one thing unverified here: whether the real reingest, invoked this way,
produces a store of this shape. That is the orchestrator's live run.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_DRIVER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "measure_emission_stability.py"

_CARMELINA_STEM = "Pregnancy/Nursing/Uncontrolled Contraception"
_CAROLINA_STEM = "Pre-menopausal women/Nursing/Pregnant/Not using contraception"


def _load_driver():
    """Import the driver script by path, since `scripts/` is not a package.

    Returns:
        The imported module.
    """
    spec = importlib.util.spec_from_file_location("_stability_driver", _DRIVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _criterion(id: int, description: str, domain: str = "Demographics") -> dict:
    """Build a stored top-level criterion.

    Args:
        id: Criterion id.
        description: The paraphrased description.
        domain: OMOP-ish domain label.

    Returns:
        A criterion dict as the store holds it.
    """
    return {
        "id": id,
        "description": description,
        "domain": domain,
        "groupId": None,
        "valueConstraint": None,
        "logicType": "ABSENCE",
        "isGroupLabel": False,
        "sourceText": "",
    }


def _base_store(path: Path) -> None:
    """Write a base store holding the three watched studies, pre-fix shaped.

    Args:
        path: Where to write `studies.json`.
    """
    path.write_text(json.dumps({"studies": [
        {"id": 8, "eligibility": {"inclusionCriteria": [], "exclusionCriteria": [
            _criterion(27, "Pre-menopausal women criteria"),
        ]}},
        {"id": 9, "eligibility": {"inclusionCriteria": [], "exclusionCriteria": [
            _criterion(11, _CARMELINA_STEM),
        ]}},
        {"id": 10, "eligibility": {"inclusionCriteria": [], "exclusionCriteria": [
            _criterion(21, _CAROLINA_STEM),
        ]}},
    ]}), encoding="utf-8")


def _stub_reingest(path: Path, *, carmelina_counts: str, exit_code: int = 0) -> None:
    """Write a stand-in for the reingest entry point.

    It rewrites the store the driver pointed it at, emitting a chosen number of
    CARMELINA restatements for this run so the measurement has something to disagree
    about. The run index comes from the store's own `run-N` directory, which is the
    driver's naming -- so if the driver stopped giving each run its own directory, this
    would read the wrong count rather than silently pass.

    Args:
        path: Where to write the stub.
        carmelina_counts: Comma-separated emitted count per run.
        exit_code: What the stub exits with.
    """
    path.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"EXIT = {exit_code}\n"
        f"COUNTS = [int(x) for x in {carmelina_counts!r}.split(',')]\n"
        "store = Path(os.environ['TTE_STORE_PATH'])\n"
        "index = int(store.parent.name.split('-')[1])\n"
        "assert os.environ['REINGEST_STUDIES'] == '8,9,10', os.environ['REINGEST_STUDIES']\n"
        "payload = json.loads(store.read_text())\n"
        "for s in payload['studies']:\n"
        "    if s['id'] == 9:\n"
        "        s['eligibility']['exclusionCriteria'] = [\n"
        "            {'id': 100 + n, 'description': %r + ('' if n == 0 else ' (v%%d)' %% n),\n"
        "             'domain': 'Demographics', 'valueConstraint': None}\n"
        "            for n in range(COUNTS[index])\n"
        "        ]\n"
        "store.write_text(json.dumps(payload))\n"
        "sys.exit(EXIT)\n" % _CARMELINA_STEM,
        encoding="utf-8",
    )


@pytest.fixture
def driver(tmp_path, monkeypatch):
    """Load the driver with its reingest entry point replaced by a stub.

    Args:
        tmp_path: pytest temp directory.
        monkeypatch: pytest monkeypatch fixture.

    Returns:
        A `(module, base_store, out_dir, install_stub)` bundle.
    """
    module = _load_driver()
    base = tmp_path / "base" / "studies.json"
    base.parent.mkdir(parents=True)
    _base_store(base)
    out = tmp_path / "out"
    monkeypatch.setenv("TTE_STORE_PATH", str(base))

    def install_stub(**kwargs):
        stub = tmp_path / "stub_reingest.py"
        _stub_reingest(stub, **kwargs)
        monkeypatch.setattr(module, "_REINGEST", stub)

    return module, base, out, install_stub


class TestDriverEndToEnd:
    """Copy, run, read back, report -- with the LLM replaced but nothing else."""

    def test_should_record_a_disagreeing_distribution_across_five_runs(self, driver):
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="3,3,2,3,2")

        assert module.main(["--runs", "5", "--out", str(out), "--side", "pre"]) == 0

        measurement = json.loads((out / "measurement.json").read_text())
        carmelina = next(
            d for d in measurement["distributions"]
            if d["label"] == "CARMELINA exclusion #10"
        )
        assert carmelina["counts"] == [3, 3, 2, 3, 2]
        assert "UNSTABLE" in (out / "report.md").read_text()

    def test_should_give_each_run_its_own_store_copy(self, driver):
        # Runs sharing one store would have each run reading the previous run's output,
        # which is neither identical input nor an independent draw.
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="3,3,2,3,2")

        module.main(["--runs", "5", "--out", str(out), "--side", "pre"])

        assert sorted(p.name for p in out.glob("run-*")) == [
            "run-0", "run-1", "run-2", "run-3", "run-4"
        ]
        assert all((out / f"run-{i}" / "studies.json").is_file() for i in range(5))

    def test_should_leave_the_base_store_untouched(self, driver):
        module, base, out, install_stub = driver
        before = base.read_text()
        install_stub(carmelina_counts="3,3,3,3,3")

        module.main(["--runs", "5", "--out", str(out), "--side", "pre"])

        assert base.read_text() == before

    def test_should_render_against_a_saved_baseline(self, driver):
        # AC-008's side-by-side, across the gap M4's prompt change sits in.
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="3,3,2,3,2")
        module.main(["--runs", "5", "--out", str(out / "pre"), "--side", "pre"])

        install_stub(carmelina_counts="1,1,1,1,1")
        module.main([
            "--runs", "5", "--out", str(out / "post"),
            "--baseline", str(out / "pre" / "measurement.json"),
        ])

        row = next(
            line for line in (out / "post" / "report.md").read_text().splitlines()
            if line.startswith("| CARMELINA exclusion #10")
        )
        assert "UNSTABLE" in row and "CONVERGED" in row


class TestDriverRefusesToInventData:
    """Every way the measurement can be wrong quietly is a refusal instead."""

    def test_should_abort_when_a_run_exits_non_zero(self, driver):
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="3,3,3,3,3", exit_code=1)

        with pytest.raises(RuntimeError, match="exited 1"):
            module.main(["--runs", "5", "--out", str(out), "--side", "pre"])

        assert not (out / "measurement.json").exists()

    def test_should_keep_the_failing_run_log(self, driver):
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="3,3,3,3,3", exit_code=1)

        with pytest.raises(RuntimeError):
            module.main(["--runs", "5", "--out", str(out), "--side", "pre"])

        assert (out / "run-0" / "reingest.log").is_file()

    def test_should_abort_when_a_run_emptied_a_watched_study(self, driver):
        # A study whose eligibility came back empty would count 0 for every watch. Five
        # such runs render VANISHED -- a stable, deterministic-looking regression that
        # is really a pipeline that did not process the study.
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="0,0,0,0,0")

        with pytest.raises(ValueError, match="no criteria"):
            module.main(["--runs", "5", "--out", str(out), "--side", "pre"])

    def test_should_refuse_fewer_than_five_runs(self, driver):
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="3,3,3")

        with pytest.raises(ValueError, match="at least 5"):
            module.main(["--runs", "3", "--out", str(out), "--side", "pre"])

    def test_should_exit_non_zero_when_the_base_store_is_missing(self, driver, monkeypatch):
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="3,3,3,3,3")
        monkeypatch.setenv("TTE_STORE_PATH", str(out / "absent" / "studies.json"))

        assert module.main(["--runs", "5", "--out", str(out), "--side", "pre"]) == 2


class TestDriverPassesTheWatchedStudies:
    """The reingest entry point refuses study ids it has no target for; give it ours."""

    def test_should_reingest_exactly_the_watched_studies(self, driver):
        # The stub asserts REINGEST_STUDIES == "8,9,10" and fails the run otherwise, so
        # a driver that stopped deriving the list from the watches fails here rather
        # than quietly reingesting all six studies.
        module, _, out, install_stub = driver
        install_stub(carmelina_counts="3,3,3,3,3")

        assert module.main(["--runs", "5", "--out", str(out), "--side", "pre"]) == 0

    def test_should_derive_the_study_list_from_the_watches(self, driver):
        module, _, _, _ = driver

        assert module._watched_study_ids(module.SPEC_2_1_WATCHES) == [8, 9, 10]
