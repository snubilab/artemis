"""Startup dependency validator.

Auto-discovers packages from requirements.txt and validates they can be imported.
Run before uvicorn to fail fast on missing packages.

Usage: python -m src.boot_check
"""
import importlib
import sys
from pathlib import Path

# Mapping from pip package names to their Python import names
# (only needed when they differ)
PIP_TO_IMPORT = {
    "scikit-learn": "sklearn",
    "python-dotenv": "dotenv",
    "psycopg2-binary": "psycopg2",
    "pydantic-settings": "pydantic_settings",
    "langchain-core": "langchain_core",
    "langchain-openai": "langchain_openai",
    "google-generativeai": "google.generativeai",
    "googleapis-common-protos": "google.api",
    "grpcio": "grpc",
    "protobuf": "google.protobuf",
    "pillow": "PIL",
    "pyjwt": "jwt",
    "python-dateutil": "dateutil",
    "pyyaml": "yaml",
    "websocket-client": "websocket",
    "markdown-it-py": "markdown_it",
    "chroma-hnswlib": "hnswlib",
}

# Packages that are optional (have graceful fallbacks if missing)
# Also includes packages that are not directly importable as standalone modules
# (e.g., CUDA sub-packages installed by torch, platform-conditional packages,
# infrastructure packages like opentelemetry, pulsar)
OPTIONAL = {
    "spacy",
    "sentence-transformers",
    "torch",
    "transformers",
    # Windows-only
    "colorama",
    # Non-CPython only
    "brotlicffi",
    # CUDA/nvidia sub-packages (installed as data packages, not importable directly)
    "nvidia-cublas",
    "nvidia-cublas-cu12",
    "nvidia-cuda-cupti",
    "nvidia-cuda-cupti-cu12",
    "nvidia-cuda-nvrtc",
    "nvidia-cuda-nvrtc-cu12",
    "nvidia-cuda-runtime",
    "nvidia-cuda-runtime-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cudnn-cu13",
    "nvidia-cufft",
    "nvidia-cufft-cu12",
    "nvidia-cufile",
    "nvidia-cufile-cu12",
    "nvidia-curand",
    "nvidia-curand-cu12",
    "nvidia-cusolver",
    "nvidia-cusolver-cu12",
    "nvidia-cusparse",
    "nvidia-cusparse-cu12",
    "nvidia-cusparselt-cu12",
    "nvidia-cusparselt-cu13",
    "nvidia-nccl-cu12",
    "nvidia-nccl-cu13",
    "nvidia-nvjitlink",
    "nvidia-nvjitlink-cu12",
    "nvidia-nvshmem-cu13",
    "nvidia-nvtx",
    "nvidia-nvtx-cu12",
    # CUDA toolkit packages (not importable as Python modules)
    "cuda-bindings",
    "cuda-pathfinder",
    "cuda-toolkit",
    # OpenTelemetry (instrumentation, not core app dependency)
    "opentelemetry-api",
    "opentelemetry-exporter-otlp-proto-common",
    "opentelemetry-exporter-otlp-proto-grpc",
    "opentelemetry-instrumentation",
    "opentelemetry-instrumentation-asgi",
    "opentelemetry-instrumentation-fastapi",
    "opentelemetry-proto",
    "opentelemetry-sdk",
    "opentelemetry-semantic-conventions",
    "opentelemetry-util-http",
    # Message queue (optional infrastructure)
    "pulsar-client",
    # Font/graphics sub-deps
    "fonttools",
}


def _parse_requirements(path: Path) -> list[str]:
    """Extract pip package names from requirements.txt."""
    packages = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip version specifiers: "package>=1.0,<2.0" -> "package"
        name = (
            line.split(">=")[0]
            .split("<=")[0]
            .split("==")[0]
            .split("!=")[0]
            .split("~=")[0]
            .split("<")[0]
            .split(">")[0]
            .split(";")[0]
            .strip()
        )
        if name:
            packages.append(name)
    return packages


def _pip_to_import(pip_name: str) -> str:
    """Convert pip package name to importable module name."""
    if pip_name in PIP_TO_IMPORT:
        return PIP_TO_IMPORT[pip_name]
    return pip_name.replace("-", "_")


def check_imports(import_names: list[str] | None = None) -> None:
    """Check that all required packages can be imported.

    Args:
        import_names: list of import module names to check.
            If None, auto-discovers from requirements.txt.

    Raises SystemExit(1) if any required package is missing.
    """
    if import_names is not None:
        # Direct mode: check exactly these import names
        missing = []
        for mod_name in import_names:
            try:
                importlib.import_module(mod_name)
            except ImportError:
                missing.append((mod_name, mod_name))
        if missing:
            print("BOOT CHECK FAILED — missing Python packages:", file=sys.stderr)
            for mod_name, pip_name in missing:
                print(f"  - {mod_name} (pip install {pip_name})", file=sys.stderr)
            sys.exit(1)
        print(f"Boot check OK: {len(import_names)} packages verified.")
        return

    # Auto-discover from requirements.txt
    req_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    if not req_path.exists():
        print("Boot check: requirements.txt not found, skipping.")
        return

    pip_packages = _parse_requirements(req_path)
    missing = []
    checked = 0
    for pip_name in pip_packages:
        if pip_name in OPTIONAL:
            continue
        mod_name = _pip_to_import(pip_name)
        checked += 1
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append((mod_name, pip_name))

    if missing:
        print("BOOT CHECK FAILED — missing Python packages:", file=sys.stderr)
        for mod_name, pip_name in missing:
            print(f"  - {mod_name} (pip install {pip_name})", file=sys.stderr)
        print(
            "\nFix: rebuild the Docker image or run: pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Boot check OK: {checked} packages verified.")


if __name__ == "__main__":
    check_imports()
