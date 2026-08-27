#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${HOME}/.local/lib/python3.11/site-packages:${ROOT_DIR}/backend/src:${PYTHONPATH:-}"

echo "=========================================="
echo "    Running RedCell_OS Local CI Suite     "
echo "=========================================="

echo ""
echo ">>> [1/7] Schema & Type Drift Check..."
./scripts/generate-types.sh --check

echo ""
echo ">>> [2/7] Backend: Ruff Linting Check..."
python3 -m ruff check backend/src tests

echo ""
echo ">>> [3/7] Backend: Ruff Format Check..."
python3 -m ruff format --check backend/src tests

echo ""
echo ">>> [4/7] Backend: Mypy Type Checker..."
python3 -m mypy backend/src

echo ""
echo ">>> [5/7] Backend: Pytest Unit Tests..."
python3 -m pytest -v tests/

echo ""
echo ">>> [6/7] Process Supervisor: Node Lifecycle & Circuit Breaker Tests..."
node tests/test_supervisor.js

echo ""
echo ">>> [7/7] Frontend: Vitest Tests, ESLint & TypeScript Build..."
cd frontend
npm run test
npm run lint
npm run build
cd ..

echo ""
echo "=========================================="
echo "  ✅ All Local CI Checks Passed Cleanly!  "
echo "=========================================="
