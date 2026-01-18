# Security Scanning - USPTO Final Petition Decisions MCP

This document describes the comprehensive security scanning infrastructure for the USPTO Final Petition Decisions (FPD) MCP, designed to prevent accidental exposure of sensitive credentials and protect against sophisticated prompt injection attacks including Unicode steganography.

## Overview

The FPD MCP uses **[detect-secrets](https://github.com/Yelp/detect-secrets)** and **custom prompt injection detection** to scan for accidentally committed secrets and malicious prompt patterns. This provides **three layers of protection**:

1. **Pre-commit hooks** - Scans files locally before they're committed to git
2. **GitHub Actions CI/CD** - Scans all code pushed to GitHub on every push/PR  
3. **Unicode Steganography Detection** - Protects against emoji-based prompt injection attacks

## 🚨 NEW: Unicode Steganography Protection

Following the discovery of Unicode Variation Selector attacks (as detailed in the [Repello.ai article](https://repello.ai/blog/prompt-injection-using-emojis)), the FPD MCP now includes advanced detection for:

- **Emoji-based steganography** - Malicious instructions hidden in innocent text using invisible Unicode characters
- **Variation Selector encoding** - Binary patterns using VS0 (U+FE00) and VS1 (U+FE01) to hide messages  
- **High invisible character ratios** - Suspicious concentrations of invisible Unicode characters
- **Binary pattern detection** - Recognition of steganographic encoding schemes

**Example Attack**: Text like "Hello!" can contain hidden malicious instructions encoded in invisible Variation Selectors that are completely undetectable to normal security scanning.

## What Gets Scanned

### 1. **Secret Detection** (20+ types)
Uses detect-secrets to find accidentally committed credentials

### 2. **Prompt Injection Detection** (80+ patterns)
Scans for malicious prompt patterns targeting Final Petition Decisions system, including Unicode steganography attacks

### Secret Types Detected (20+ types)

The scanner detects the following types of secrets:

**API Keys & Authentication:**
- AWS/Azure/GCP cloud credentials
- GitHub/GitLab tokens
- Mistral API keys (used for OCR)
- OpenAI API keys
- JWT tokens
- Basic authentication credentials

**Infrastructure Secrets:**
- Private SSH keys
- SSL/TLS certificates
- Database passwords
- NPM tokens
- PyPI tokens

**High-Entropy Strings:**
- Base64-encoded secrets (limit: 4.5 entropy)
- Hexadecimal secrets (limit: 3.0 entropy)

**Communication Services:**
- Slack tokens
- Discord bot tokens
- Telegram bot tokens
- Twilio API keys
- SendGrid API keys
- Mailchimp API keys

### Prompt Injection Attack Patterns (70+ patterns)

**Attack Categories Detected:**
- Instruction override attempts ("ignore previous instructions")
- System prompt extraction ("show me your instructions")
- AI behavior manipulation ("you are now a different AI")
- Output format manipulation ("encode in hex")
- Social engineering ("we became friends")

**Final Petition Decisions Specific:**
- Petition data extraction ("extract all petition numbers")
- Decision reasoning disclosure ("reveal director decisions")
- USPTO API bypass attempts ("ignore API restrictions")
- CFR rule manipulation ("override 37 CFR requirements")
- Petitioner information exfiltration ("dump petitioner data")

**🚨 Unicode Steganography Attacks (NEW):**
- **Variation Selector steganography** - Malicious instructions hidden using VS0/VS1 binary encoding
- **Invisible character injection** - Zero-width spaces and other invisible Unicode characters
- **Emoji-based hiding** - Messages concealed in emoji variation selectors
- **Binary steganography patterns** - Systematic use of invisible characters for encoding
- **High steganography ratios** - Suspicious concentrations of invisible vs visible characters

## Prompt Injection Baseline System

The prompt injection scanner uses a **baseline system** to track known findings and only flag **NEW** patterns that are not in the baseline. This solves the problem of false positives from legitimate code and documentation while maintaining protection against malicious prompt injection attacks.

### Why a Baseline System?

The scanner was flagging legitimate patterns as "attacks":

**Variable Names:**
```python
prompt = """Some prompt text"""        # Flagged as attack
system = "some value"               # Flagged as attack
class PromptTemplate:               # Flagged as attack
def system_init(self):              # Flagged as attack
```

**Documentation:**
```markdown
Instructions for using the system  # Flagged as attack
System health check                   # Flagged as attack
```

**Legitimate Unicode Characters:**
- Emoji variation selectors in documentation
- Unicode characters in prompt templates
- Special characters in logging

The baseline system allows legitimate code without compromising security - only NEW findings not in baseline cause failures.

### How It Works

1. **Baseline File**: `.prompt_injections.baseline` stores known findings
2. **Fingerprinting**: Each finding gets a unique SHA256 hash fingerprint
3. **Comparison**: Scanner checks if each finding is in the baseline
4. **Exit Codes**:
   - `0` - No NEW findings (all findings in baseline)
   - `1` - NEW findings detected (not in baseline)
   - `2` - Error occurred

### Baseline File Format

```json
{
  "src/fpd_mcp/shared/health_check.py": {
    "abc123def456": {
      "line": 2,
      "match": "system"
    },
    "def789ghi012": {
      "line": 4,
      "match": "system"
    }
  },
  "src/fpd_mcp/prompts/art_unit_quality_assessment.py": {
    "ghi345jkl678": {
      "line": 6,
      "match": "prompt"
    }
  }
}
```

### Baseline Commands

| Option | Purpose |
|--------|---------|
| `--baseline` | Use existing baseline (only NEW findings fail) |
| `--update-baseline` | Add new findings to baseline |
| `--force-baseline` | Create new baseline (overwrite existing) |
| `--verbose, -v` | Show detailed output with full matches |
| `--quiet, -q` | Only show summary (suppress individual findings) |
| `--include-security-files` | Check security documentation files |

### Usage Examples

**First Run - Create Baseline:**
```bash
# Scan and create baseline (will NOT fail if findings exist)
uv run python .security/check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json *.py
```

**Normal Run - Check Against Baseline:**
```bash
# Check for NEW findings only
uv run python .security/check_prompt_injections.py --baseline src/ tests/ *.yml *.yaml *.json *.py
```

**Add New Legitimate Finding to Baseline:**
```bash
# Update baseline to include new legitimate finding
uv run python .security/check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json *.py
```

**Force New Baseline:**
```bash
# Overwrite existing baseline
uv run python .security/check_prompt_injections.py --force-baseline src/ tests/ *.md *.yml *.yaml *.json *.py
```

### When to Update Baseline

**DO Update Baseline When:**
1. **New legitimate code** is flagged
   - New variable/function names with "prompt" or "system"
   - Documentation with these words
   - Legitimate Unicode characters

2. **Approved refactoring** changes line numbers
   - Code moves (findings appear at new lines)
   - File restructuring

3. **Baseline is outdated**
   - Many findings no longer exist in current code

**DON'T Update Baseline When:**
1. **Malicious pattern detected** - Remove the malicious code instead
2. **You're unsure** - Ask for review first
3. **Security-related finding** - Even if it looks "innocent", review carefully

### GitHub Actions Integration

The workflow automatically handles baselines:

```yaml
- name: Run prompt injection detection
  run: |
    # Create baseline if it doesn't exist, then check against it
    if [ ! -f .prompt_injections.baseline ]; then
      echo "📋 Creating baseline for first time..."
      uv run python .security/check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json *.py
    else
      echo "📋 Using existing baseline..."
      uv run python .security/check_prompt_injections.py --baseline src/ tests/ *.yml *.yaml *.json *.py
    fi
```

**Workflow Behavior:**

| Scenario | GitHub Actions Result |
|----------|----------------------|
| First run (no baseline) | Creates baseline, passes |
| Subsequent runs (no NEW findings) | Passes (findings in baseline) |
| Subsequent runs (NEW findings) | Fails (requires review) |
| Review finds legitimate false positive | Update baseline locally, push |

### Managing the Baseline File

**Add Baseline to Repository:**
```bash
git add .prompt_injections.baseline
git commit -m "Add prompt injection baseline"
git push
```

**Reviewing Baseline Changes:**
```bash
# See what changed in baseline
git diff .prompt_injections.baseline
```

**Regenerating Baseline:**
```bash
# Regenerate from scratch (re-run full scan)
uv run python .security/check_prompt_injections.py --force-baseline src/ tests/ *.md *.yml *.yaml *.json *.py

# Review and commit
git add .prompt_injections.baseline
git commit -m "Regenerate prompt injection baseline"
```

### Files Excluded from Scanning

The following file patterns are excluded to reduce false positives:

- `configs/**/*.json` - Example configuration files with placeholder keys
- `*.md` - Markdown documentation files (except actual secrets)
- `package-lock.json` - NPM lock files
- `*.lock` - Other lock files (Cargo.lock, poetry.lock, etc.)

**Important:**
- **Prompts directory IS scanned** - The baseline system allows legitimate prompt code while catching malicious injections
- `CLAUDE.md` is in `.gitignore` and not scanned
- All other files (including test files) are scanned to prevent accidental exposure

## Installation

### Prerequisites

You need Python 3.11+ and either:
- **uv** (recommended, already used by FPD MCP)
- **pip** (standard Python package manager)

### Option 1: Using uv (Recommended)

```bash
# Install detect-secrets as a tool
uv tool install detect-secrets

# Verify installation
uv tool run detect-secrets --version
```

### Option 2: Using pip

```bash
# Install detect-secrets
pip install detect-secrets

# Verify installation
detect-secrets --version
```

### Install Pre-commit Hooks

```bash
# Install pre-commit package
pip install pre-commit

# Install git hooks (run from project root)
cd C:\Users\JohnWalkoe\uspto_fpd_mcp
pre-commit install

# Verify installation
pre-commit --version
```

## Usage

### Prompt Injection Detection (Including Unicode Steganography)

**🚨 CRITICAL:** The scanner now detects Unicode steganography attacks as described in the [Repello.ai article](https://repello.ai/blog/prompt-injection-using-emojis).

**📋 BASELINE SYSTEM:** The scanner uses a baseline file to track known legitimate findings. See the [Prompt Injection Baseline System](#prompt-injection-baseline-system) section for complete details.

**Manual Scanning:**
```bash
# Check against existing baseline (only NEW findings fail)
uv run python .security/check_prompt_injections.py --baseline src/ tests/ *.md *.py

# Update baseline with new legitimate findings
uv run python .security/check_prompt_injections.py --update-baseline src/ tests/ *.md *.yml *.yaml *.json *.py

# Scan specific directories for all attack patterns
uv run python .security/check_prompt_injections.py --baseline src/fpd_mcp/

# Include security files in scan (normally excluded)
uv run python .security/check_prompt_injections.py --include-security-files src/ tests/

# Run via pre-commit hook (automatic Unicode steganography detection)
uv run pre-commit run prompt-injection-check --all-files

# Verbose output (shows full attack patterns detected)
uv run python .security/check_prompt_injections.py --verbose src/ tests/

# Quiet mode (only shows summary and Unicode steganography alerts)
uv run python .security/check_prompt_injections.py --quiet src/ tests/
```

**🔍 Unicode Steganography Examples:**
```bash
# Test with known steganography patterns
echo 'Hello!' > test_file.txt
# If test_file.txt contains hidden Variation Selectors, scanner will detect them

# Check specific file for invisible characters
uv run python .security/check_prompt_injections.py --baseline suspicious_file.md

# Emergency scan when Unicode steganography is suspected
uv run python .security/check_prompt_injections.py --verbose --include-security-files .
```

### Pre-commit Hooks (Local Development)

Once installed, pre-commit hooks run automatically on `git commit`:

```bash
# Make changes to files
git add src/fpd_mcp/config/settings.py

# Commit (hooks run automatically)
git commit -m "Update settings"

# If secrets detected:
# - Commit is blocked
# - Files with secrets are listed
# - Fix the issues and try again
```

**Bypass hooks (NOT RECOMMENDED):**
```bash
# Only use in emergencies (requires justification in commit message)
git commit --no-verify -m "Emergency fix - bypassing hooks"
```

### Manual Scanning

Run secret scanning manually anytime:

```bash
# Scan all files against baseline (uv method)
uv tool run detect-secrets scan --baseline .secrets.baseline

# Scan all files against baseline (pip method)
detect-secrets scan --baseline .secrets.baseline

# Scan specific file
uv tool run detect-secrets scan --baseline .secrets.baseline src/fpd_mcp/main.py

# Scan git history (last 100 commits)
git log --all --pretty=format: -p -100 | uv tool run detect-secrets scan --stdin
```

### Updating the Baseline

When you add new test placeholders or example configurations, update the baseline:

```bash
# Update baseline with new findings (uv method)
uv tool run detect-secrets scan --baseline .secrets.baseline

# Update baseline with new findings (pip method)
detect-secrets scan --baseline .secrets.baseline

# Review changes
git diff .secrets.baseline

# Commit updated baseline
git add .secrets.baseline
git commit -m "Update secrets baseline for new test placeholders"
```

**When to update the baseline:**
- Adding new test files with placeholder keys like `"test_key_for_unit_tests"`
- Adding example configuration files with dummy credentials
- After verifying a detection is a false positive (e.g., UUID, documentation example)

**When NOT to update the baseline:**
- When a real secret is detected (remove the secret instead!)
- When you're unsure if it's a real secret (ask for review first)

## GitHub Actions Integration

The FPD MCP automatically scans code on every push and pull request to `main`, `master`, or `develop` branches.

### Workflow Configuration

**File:** `.github/workflows/secret-scan.yaml`

**Triggers:**
- Push to `main`, `master`, or `develop`
- Pull requests targeting those branches

**What it does:**
1. Checks out code with full git history
2. Installs detect-secrets
3. Scans current codebase against `.secrets.baseline`
4. Scans last 100 commits of git history
5. Fails build if new secrets detected (not in baseline)

### Viewing Scan Results

**On GitHub:**
1. Go to your repository
2. Click **Actions** tab
3. Select **Secret Scanning** workflow
4. View latest run results

**Build failures:**
- If scan finds new secrets, the build fails
- Check the workflow logs for detected secrets
- Remove secrets and update baseline if needed
- Push again to re-run checks

## Troubleshooting

### False Positives

**Problem:** Scanner detects a UUID or other non-secret as a secret

**Solution:**
```bash
# Add to baseline (after verifying it's not a real secret)
uv tool run detect-secrets scan --baseline .secrets.baseline

# Review the addition
git diff .secrets.baseline

# Commit the updated baseline
git add .secrets.baseline
git commit -m "Add false positive UUID to baseline"
```

### Pre-commit Hook Not Running

**Problem:** Hooks don't run on `git commit`

**Solution:**
```bash
# Verify hooks are installed
ls -la .git/hooks/pre-commit

# If missing, reinstall
pre-commit install

# Test manually
pre-commit run --all-files
```

### Baseline File Conflicts

**Problem:** Merge conflicts in `.secrets.baseline` after updating from main

**Solution:**
```bash
# Regenerate baseline from scratch
uv tool run detect-secrets scan --baseline .secrets.baseline

# Review changes carefully
git diff .secrets.baseline

# Commit regenerated baseline
git add .secrets.baseline
git commit -m "Regenerate secrets baseline after merge"
```

### Real Secret Committed by Mistake

**Problem:** You accidentally committed a real secret

**Solution:**

**1. Immediately rotate the compromised credential:**
- USPTO API key: Generate new key at https://developer.uspto.gov/
- Mistral API key: Generate new key at https://console.mistral.ai/api-keys/

**2. Remove from git history:**
```bash
# Use git filter-repo (recommended) or BFG Repo Cleaner
# See: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository

# Example with git filter-repo (install first: pip install git-filter-repo)
git filter-repo --invert-paths --path path/to/file/with/secret.py
```

**3. Force push (if already pushed to GitHub):**
```bash
git push --force origin main
```

**4. Update baseline and verify:**
```bash
uv tool run detect-secrets scan --baseline .secrets.baseline
git add .secrets.baseline
git commit -m "Remove compromised secret from baseline"
git push origin main
```

### Scanner Hangs or Times Out

**Problem:** Scanning very large files or repos takes too long

**Solution:**
```bash
# Increase timeout for large files (not typically needed for FPD MCP)
uv tool run detect-secrets scan --baseline .secrets.baseline --timeout 300

# Or exclude large files
uv tool run detect-secrets scan --baseline .secrets.baseline --exclude-files 'large_file.json'
```

## Best Practices

### For Developers

**✅ DO:**
- Run `pre-commit run --all-files` before pushing
- Use environment variables for all secrets (never hardcode)
- Store secrets in `CLAUDE.md` (already in `.gitignore`)
- Use placeholder keys in tests (e.g., `"test_key_for_unit_tests"`)
- Update baseline when adding legitimate test placeholders
- Review baseline changes carefully before committing

**❌ DON'T:**
- Commit files with real API keys, tokens, or passwords
- Use `--no-verify` to bypass hooks (except emergencies)
- Update baseline to hide real secrets (rotate the secret instead!)
- Share API keys in chat, email, or documentation
- Reuse the same API key across multiple projects

### For API Key Management

**USPTO API Key:**
- Store in Claude Desktop config: `%APPDATA%\Claude\claude_desktop_config.json`
- Or use environment variable: `$env:USPTO_API_KEY="your_key"`
- Rotate quarterly or after any security incident

**Mistral API Key (optional):**
- Store in same Claude Desktop config file
- Or use environment variable: `$env:MISTRAL_API_KEY="your_key"`
- Monitor usage costs ($0.001/page for OCR)

### For Code Reviews

**Check for:**
- Files with high-entropy strings (not in baseline)
- Hardcoded credentials or tokens
- Configuration files with real secrets (should use env vars)
- Test files with real API keys (should use placeholders)

**Verify:**
- Baseline updates are justified (false positives or test placeholders)
- No `--no-verify` commits without good reason
- Environment variables are documented in README

## Integration with FPD MCP Architecture

### Protected Files

The following FPD MCP files are particularly sensitive and actively scanned:

**Configuration:**
- `src/fpd_mcp/config/settings.py` - Environment variable handling
- `field_configs.yaml` - Field configuration (no secrets, but scanned)

**Test Files:**
- `tests/test_basic.py` - Unit tests with placeholder keys (baseline tracked)
- `tests/test_integration.py` - Integration tests (baseline tracked)
- `tests/test_extraction.py` - Document extraction tests (CONTAINS REAL KEYS - NOT COMMITTED)

**API Client:**
- `src/fpd_mcp/api/fpd_client.py` - API authentication logic

**Documentation:**
- `CLAUDE.md` - **IN .GITIGNORE** - Contains real keys, never committed
- `README.md` - Public documentation (scanned to ensure no real keys)

### Excluded Files

**Automatically excluded:**
- `CLAUDE.md` - In `.gitignore` (contains real keys for development)
- `configs/**/*.json` - Example configurations with placeholder keys
- `*.md` files - Markdown documentation (except real secrets)

### Cross-MCP Consistency

The FPD MCP secret scanning matches the PTAB MCP pattern:
- Same detect-secrets version (v1.5.0)
- Same exclusion patterns
- Same pre-commit hooks
- Same GitHub Actions workflow structure
- Consistent with Patent File Wrapper MCP security practices

## Additional Resources

- **detect-secrets documentation:** https://github.com/Yelp/detect-secrets
- **USPTO API key management:** https://developer.uspto.gov/
- **Mistral API key management:** https://console.mistral.ai/api-keys/
- **GitHub secret scanning:** https://docs.github.com/en/code-security/secret-scanning
- **FPD MCP Security Guidelines:** `SECURITY_GUIDELINES.md`

## Support

**Found a security issue?**
- Create a private security advisory on GitHub
- Or email: [contact information]

**Questions about secret scanning?**
- Review this documentation
- Check troubleshooting section
- Open an issue on GitHub (without revealing secrets!)

---

**Last Updated:** 2025-10-12
**Version:** 1.0
**detect-secrets Version:** 1.5.0
