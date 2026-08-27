#!/usr/bin/env bash
set -e

echo "=== Starting RedCell_OS Development Environment ==="

# Set environment defaults
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export REDCELL_ENV="development"
export REDCELL_LOG_LEVEL="DEBUG"

echo "Environment initialized. Ready for backend and frontend launch."
