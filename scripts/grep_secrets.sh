#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Fake/test secret markers that must NOT appear in runtime/output/contract paths
MARKERS='AKIAFAKEFAKEFAKE0000|hunter2-FAKE|FAKE\.TOKEN\.VALUE'

echo "Scanning runtime/contract/output paths for accidental secret markers..."
if grep -rnE \
  --exclude-dir='.git' \
  --exclude-dir='.venv' \
  --exclude-dir='venv' \
  --exclude-dir='__pycache__' \
  --exclude-dir='.pytest_cache' \
  --exclude-dir='data' \
  --exclude-dir='raw' \
  --exclude-dir='tests' \
  --exclude-dir='docs' \
  --exclude='generator.py' \
  --exclude='grep_secrets.sh' \
  "$MARKERS" . ; then
  echo "FAIL: Secret marker found outside allowed raw/ignored/test paths!" >&2
  exit 1
fi

echo "PASS: No secret markers found outside allowed raw/ignored/test paths."
