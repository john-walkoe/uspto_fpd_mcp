#!/usr/bin/env python3
"""
Merge USPTO FPD MCP configuration into ~/.claude.json

This script specifically handles the case where Claude Code CLI uses ~/.claude.json
instead of ~/.config/Claude/claude_desktop_config.json (Claude Desktop)
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def main():
    # Determine project directory
    project_dir = Path.cwd()
    if not (project_dir / "pyproject.toml").exists():
        print("ERROR: Must run from uspto_fpd_mcp directory")
        sys.exit(1)

    # Claude config file location (Claude Code CLI)
    claude_config = Path.home() / ".claude.json"

    if not claude_config.exists():
        print(f"ERROR: {claude_config} does not exist")
        print("Claude Code CLI may not be configured yet")
        print()
        print("If you are using Claude Desktop (not Claude Code CLI),")
        print("use the setup scripts instead:")
        print("  Windows: .\\deploy\\windows_setup.ps1")
        print("  Linux/macOS: ./deploy/linux_setup.sh")
        sys.exit(1)

    # Backup existing config
    backup_path = Path(str(claude_config) + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    print(f"Creating backup: {backup_path}")
    backup_path.write_text(claude_config.read_text())

    # Load existing config
    print(f"Reading: {claude_config}")
    with claude_config.open('r') as f:
        config = json.load(f)

    # Ensure mcpServers exists
    if 'mcpServers' not in config:
        config['mcpServers'] = {}

    # Check if uspto_fpd already exists
    if 'uspto_fpd' in config['mcpServers']:
        print("WARN: uspto_fpd already exists in config - will overwrite")

    # Add or update uspto_fpd configuration
    config['mcpServers']['uspto_fpd'] = {
        'command': 'uv',
        'args': [
            '--directory',
            str(project_dir),
            'run',
            'fpd-mcp'
        ],
        'env': {
            'FPD_PROXY_PORT': '8081',
            'ENABLE_PROXY_SERVER': 'true'
        }
    }

    # Write updated config
    print(f"Writing: {claude_config}")
    with claude_config.open('w') as f:
        json.dump(config, f, indent=2)

    # Set secure permissions
    claude_config.chmod(0o600)

    print()
    print("✓ SUCCESS: USPTO FPD MCP configuration added to ~/.claude.json")
    print()
    print("Configuration details:")
    print(f"  - Server name: uspto_fpd")
    print(f"  - Project directory: {project_dir}")
    print(f"  - Proxy port: 8081")
    print()
    print("Next steps:")
    print("  1. Restart Claude Code CLI")
    print("  2. Run: claude mcp list")
    print("  3. Verify uspto_fpd appears in the list")
    print()
    print("Note: API keys are managed via DPAPI (Windows) or secure storage (Linux/macOS)")
    print("      Use deploy/manage_api_keys.ps1 (Windows) to configure API keys")
    print()

if __name__ == '__main__':
    main()
