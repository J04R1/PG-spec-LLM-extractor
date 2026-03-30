#!/usr/bin/env bash
set -e

echo "══════════════════════════════════════════════════════"
echo "  PG Spec Extractor — Test Suite (Iteration 09)"
echo "══════════════════════════════════════════════════════"
echo ""

.venv/bin/python -m pytest tests/ -v --tb=short -x "$@"

echo ""
echo "══════════════════════════════════════════════════════"
echo "  All tests passed ✓"
echo "══════════════════════════════════════════════════════"
