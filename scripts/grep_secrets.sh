#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Fake/test secret markers that must NOT appear outside raw test data or logs/raw stores
MARKERS='AKIAFAKEFAKEFAKE0000|hunter2-FAKE|FAKE\.TOKEN\.VALUE'

echo "Scanning repository (excluding .git, .venv, venv, collector-security/data, sample-data/raw)..."
if grep -rnE \
  --exclude-dir='.git' \
  --exclude-dir='.venv' \
  --exclude-dir='venv' \
  --exclude-dir='__pycache__' \
  --exclude-dir='.pytest_cache' \
  --exclude-dir='data' \
  --exclude-dir='raw' \
  --exclude='grep_secrets.sh' \
  "$MARKERS" . ; then
  echo "FAIL: Secret marker found outside allowed raw/ignored paths!" >&2
  exit 1
fi

echo "PASS: No secret markers found in tracked/non-raw directories."
