#!/bin/bash

# Quick script to merge FPD config into existing ~/.claude.json
# This is a wrapper around merge_fpd_to_claude_json.py
#
# Use this for Claude Code CLI users who have ~/.claude.json
# For Claude Desktop users, use linux_setup.sh instead

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Change to project directory so the script can find pyproject.toml
cd "$PROJECT_DIR"

echo "Merging USPTO FPD MCP configuration into ~/.claude.json"
echo "========================================================="
echo ""

# Run the Python merge script
python3 "$SCRIPT_DIR/merge_fpd_to_claude_json.py"
