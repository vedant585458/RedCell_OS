#!/usr/bin/env bash
set -e

echo "=== RedCell_OS Environment Setup ==="

# Check Python version
python3 --version || { echo "Python 3 is required."; exit 1; }

# Install backend dependencies
echo "Installing backend dependencies..."
pip install --user --break-system-packages -r requirements.txt

# Create necessary runtime directories
echo "Creating data and workspace directories..."
mkdir -p data/engagements data/workspaces

echo "Setup completed successfully!"
