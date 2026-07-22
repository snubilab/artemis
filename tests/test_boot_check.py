import subprocess
import sys
from pathlib import Path

PROJECT_DIR = str(Path(__file__).resolve().parent.parent)


def test_boot_check_passes_when_all_deps_present():
    """boot_check.py should exit 0 when all required packages are installed."""
    result = subprocess.run(
        [sys.executable, "-m", "src.boot_check"],
        capture_output=True, text=True, cwd=PROJECT_DIR,
    )
    assert result.returncode == 0, f"boot_check failed:\n{result.stderr}"
    assert "Boot check OK" in result.stdout or "requirements.txt not found" in result.stdout


def test_boot_check_reports_missing_package():
    """boot_check should detect a deliberately impossible import."""
    result = subprocess.run(
        [sys.executable, "-c",
         "from src.boot_check import check_imports; check_imports(['nonexistent_pkg_xyz123'])"],
        capture_output=True, text=True, cwd=PROJECT_DIR,
    )
    assert result.returncode != 0
    assert "nonexistent_pkg_xyz123" in result.stderr


def test_boot_check_covers_requirements_txt():
    """Every non-optional package in requirements.txt should be checkable."""
    req_path = Path(PROJECT_DIR) / "requirements.txt"
    if not req_path.exists():
        return  # Skip if requirements.txt not yet generated
    result = subprocess.run(
        [sys.executable, "-m", "src.boot_check"],
        capture_output=True, text=True, cwd=PROJECT_DIR,
    )
    assert result.returncode == 0, (
        f"boot_check failed — requirements.txt has packages not importable:\n{result.stderr}"
    )
