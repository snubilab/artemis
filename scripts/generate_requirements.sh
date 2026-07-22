#!/usr/bin/env bash
# Generates requirements.txt from pyproject.toml using poetry export.
# Run this whenever pyproject.toml changes.
#
# Prerequisites: pip install poetry
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Generate requirements.txt (without dev deps, without hashes for Docker compat)
poetry export --without-hashes --format=requirements.txt --output=requirements.txt --without=dev 2>/dev/null

# Prepend header
TMPFILE=$(mktemp)
{
  echo "# AUTO-GENERATED from pyproject.toml — do not edit by hand."
  echo "# Regenerate: bash scripts/generate_requirements.sh"
  echo ""
  cat requirements.txt
} > "$TMPFILE"
mv "$TMPFILE" requirements.txt

echo "Generated requirements.txt with $(grep -c '^[a-z]' requirements.txt) packages"
