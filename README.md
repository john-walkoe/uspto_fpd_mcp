# USPTO Final Petition Decisions MCP Server

A high-performance Model Context Protocol (MCP) server for the USPTO Final Petition Decisions API with token-saving **context reduction** capabilities, user-customizable fields, and **cross-MCP integration** for complete patent lifecycle analysis.

[![Platform Support](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![API](https://img.shields.io/badge/API-USPTO%20Final%20Petition%20Decisions-green.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[📥 Installation Guide](INSTALL.md)** | Complete cross-platform setup with automated scripts |
| **[🔑 API Key Guide](API_KEY_GUIDE.md)** | Step-by-step instructions for obtaining USPTO and Mistral API keys with screenshots |
| **[📖 Usage Examples](USAGE_EXAMPLES.md)** | Function examples, workflows, and integration patterns |
| **[🎯 Prompt Templates](PROMPTS.md)** | Detailed guide to sophisticated prompt templates for legal & research workflows |
| **[⚙️ Field Customization](CUSTOMIZATION.md)** | Comprehensive guidance on customizing field sets for the minimal and balanced tools |
| **[🔒 Security Guidelines](SECURITY_GUIDELINES.md)** | Comprehensive security best practices |
| **[🛡️ Security Scanning](SECURITY_SCANNING.md)** | Automated secret detection and prevention guide |
| **[🧪 Testing Guide](tests/README.md)** | Test suite documentation and API key setup |
| **[⚖️ License](LICENSE)** | MIT License terms and conditions |

## ⚡Quick Start

### Windows Install

**Run PowerShell as Administrator**, then:

```powershell
# Navigate to your user profile
cd $env:USERPROFILE

# If git is installed:
git clone https://github.com/john-walkoe/uspto_fpd_mcp.git
cd uspto_fpd_mcp

# If git is NOT installed:
# Download and extract the repository to C:\Users\YOUR_USERNAME\uspto_fpd_mcp
# Then navigate to the folder:
# cd C:\Users\YOUR_USERNAME\uspto_fpd_mcp

# The script detects if uv is installed and if it is not it will install uv - https://docs.astral.sh/uv

# Run setup script (sets execution policy for this session only):
Set-ExecutionPolicy -ExecutionPolicy Unrestricted -Scope Process
.\deploy\windows_setup.ps1

## View INSTALL.md for sample script output.
# Close Powershell Window.
# If choose option to "configure Claude Desktop integration" during the script then restart Claude Desktop
```

The PowerShell script will:

- ✅ Check for and auto-install uv (via winget or PowerShell script)
- ✅ Install dependencies and create executable
- ✅ Prompt for USPTO API key (required) and Mistral API key (optional) or Detect if you had installed the developer's other USPTO MCPs and ask if want to use existing keys from those installation.
- 🔒 **If entering in API keys, the script will automatically store API keys securely using Windows DPAPI encryption**
- ✅ Ask if you have [USPTO PFW MCP](https://github.com/john-walkoe/uspto_pfw_mcp) already installed, and if so will used the USPTO PFW MCP's default centralized proxy
- ✅ Ask if you want Claude Desktop integration configured
- 🔒 **Offer secure configuration method (recommended) or traditional method (API keys in plain text in the MCP JSON file)**
- ✅ Backups and then automatically merge with existing Claude Desktop config (preserves other MCP servers)
- ✅ Provide installation summary and next steps

### Claude Desktop Configuration - Manual installs

```json
{
  "mcpServers": {
    "uspto_fpd": {
      "command": "uv",
      "args": [
        "--directory",
        "C:/Users/YOUR_USERNAME/uspto_fpd_mcp",
        "run",
        "fpd-mcp"
      ],
      "env": {
        "USPTO_API_KEY": "your_actual_USPTO_api_key_here",
        "MISTRAL_API_KEY": "your_mistral_api_key_here_OPTIONAL",
        "CENTRALIZED_PROXY_PORT": "none",
        "FPD_PROXY_PORT": "8081"
      }
    }
  }
}
```

**Proxy Configuration Notes:**

- **CENTRALIZED_PROXY_PORT**:
  - Set to `"none"` for standalone use (not recommended)
  - Set to 8080 When USPTO PFW MCP is installed and PFW is using its default port for the local proxy.  (If PFW is not using its default port change this value to match)
- **FPD_PROXY_PORT**: Local proxy port (default: `8081`, avoids conflict with PFW on `8080`)
  - Only used in standalone mode (no PFW MCP detected)
  - When PFW MCP is installed, FPD automatically uses PFW's centralized proxy (port `8080`), but will fall back to FPD's local proxy port
  - **Centralized Proxy Benefits**: Single port for all USPTO MCPs, 7-day persistent links, unified rate limiting

## 🔑 Key Features

- **⚙️User-Customizable Fields** - Configure field sets through YAML without code changes
- **🎯Context Reduction** - Get focused responses instead of massive API dumps (80-99% reduction)
- **📊Progressive Disclosure Strategy** - Minimal discovery → Balanced analysis → Document extraction
- **🔍Petition-Type Focused Search** - Specialized tools for art unit and application-specific searches
- **✨Intelligent Document Extraction** - Auto-optimized hybrid extraction (free PyPDF2 → Mistral OCR fallback) with secure browser downloads
- **🆕Centralized Proxy Integration** - Auto-detects PFW MCP and uses unified proxy (port 8080) for persistent links and cross-MCP downloads
- **🌐Secure Browser Downloads** - Click proxy URLs to download PDFs directly while keeping API keys secure
- **👁️Advanced OCR Capabilities** - Extract text from scanned PDFs using Mistral OCR when needed
- **📁 Document Bag Integration** - Full petition document access alongside structured petition data
- **💰Mistral OCR Cost Transparency** - Real-time cost calculation when using Mistral OCR
- **🔐 Secure API Key Storage** - Optional Windows DPAPI encryption keeps API keys secure (no plain text in config files)
- **🚀High Performance** - Retry logic with exponential backoff, rate limiting compliance
- **🛡️ Production Ready** - Enhanced error handling, structured logging with request IDs, comprehensive security guidelines
- **💻Cross-Platform** - Works seamlessly on Linux and Windows
- **📋Complete API Coverage** - All USPTO Final Petition Decisions endpoints supported
- **🔗Cross-MCP Integration** - Seamless integration with Patent File Wrapper and PTAB MCPs for complete lifecycle analysis

### Workflow Design - All Performed by the LLM with Minimal User Guidance

**User Requests the following:**

- *"Find all petitions filed by TechCorp and tell me about any red flags"*
- *"Show me revival petitions for art unit 2128 - I'm analyzing abandonment patterns"*
- *"Get me the petition history for application 17414168"*
- *"Research this company's petition track record and correlate with their PTAB challenges"* - * Requires that the USPTO Patent Trial and Appeal Board (PTAB) be installed - [uspto_ptab_mcp](https://github.com/john-walkoe/uspto_ptab_mcp.git) and also recommended to ask LLM to perform a fpd_get_guidance tool call prior to this or any cross MCP prompt (see quick reference chart for section selection, additional details in [Usage Examples](USAGE_EXAMPLES.md))
- *"Analyze this art unit's prosecution quality by looking at petition frequency and types"*

**LLM Performs these steps:**

**Step 1: Discovery (Minimal)** → **Step 2: Selection and Analysis (Balanced - Optional)** → **Step 3: Detailed Petition Review** → **Step 4 (Optional): Select specific petition documents for examination** → **Step 5 (Optional): Retrieve document_id(s) from documentBag** → **Step 6 (Optional): Document Extraction for LLM use and/or Download Links of PDFs for user's use**

The field configuration supports an optimized research progression:

1. **Discovery (Minimal)** returns 50-100 petitions efficiently without document bloat
2. **Selection and Analysis (Balanced - Optional)** from the retrieved select likely petition(s). Optional balanced search(es) performed if needed in advanced workflows and/or cross-MCP workflows with Patent File Wrapper or PTAB
3. **Detailed Petition Review** via `fpd_get_petition_details` for selected petitions with complete structured data for LLM's use in analysis
4. **Select specific petition documents for examination** (Optional) e.g. Decision letters, petition filings, supporting evidence
5. **Retrieve document_id(s) from documentBag** (Optional) use `fpd_get_petition_details` with `include_documents=True` to get the document_id(s)
6. **Document Extraction for LLM use and/or Download Links** (Optional) Document extraction via intelligent hybrid tool that auto-optimizes for cost and quality, and Downloads of the documents as PDFs uses URLs from an HTTP proxy that obscures the USPTO's API key from chat history

##  🎯 Prompt Templates

This MCP server includes sophisticated AI-optimized prompt templates for complex petition workflows. For detailed documentation on all templates, features, and usage examples, see **[PROMPTS.md](PROMPTS.md)**.

### Quick Template Overview

| Category                   | Templates                                                    | Purpose                                                     |
| -------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------- |
| **Legal Analysis**         | `/company_petition_risk_assessment_PFW`, `/patent_vulnerability_assessment_ptab`, `/litigation_research_setup_pfw` | Due diligence, PTAB risk assessment, litigation preparation |
| **Research & Prosecution** | `/art_unit_quality_assessment`, `/prosecution_quality_correlation_pfw`, `/revival_petition_analysis` | Art unit analysis, examiner behavior, abandonment patterns  |
| **Document Management**    | `/petition_document_research_package`, `/complete_portfolio_due_diligence_pfw_ptab` | Organized retrieval, comprehensive lifecycle analysis       |

**Key Features Across All Templates:**

- **Enhanced Input Processing** - Flexible identifier support (petition IDs, application numbers, company names)
- **Smart Validation** - Automatic format detection and guidance
- **Cross-MCP Integration** - Seamless workflows with PFW, PTAB, and Citations MCPs
- **Context Optimization** - Token reduction through progressive disclosure

## 📊 Available Functions

### Search Functions (4 Focused Tools)

| Function (Display Name) | Context Reduction | Use Case |
|----------|------------------|----------|
| `fpd_search_petitions_minimal` (Search petitions minimal) | typical 95-99% | Ultra-fast petition discovery (user-customizable minimal fields) |
| `fpd_search_petitions_balanced` (Search petitions balanced) | typical 80-88% | Key fields for detailed analysis (no documentBag) |
| `fpd_search_petitions_by_art_unit` (Search petitions by art unit) | typical 80-88% | Art unit quality assessment with date range filtering |
| `fpd_search_petitions_by_application` (Search petitions by application) | typical 80-88% | Complete petition history for specific application |

##  Search Strategies

### Specialized Search Strategies

- **Art Unit Quality Assessment** - Use `fpd_search_petitions_by_art_unit` to analyze petition patterns across art units for examiner behavior and technology difficulty assessment
- **Application Petition History** - Use `fpd_search_petitions_by_application` to get complete petition timeline for specific applications during prosecution
- **Cross-MCP Integration** - Link petition data with PFW prosecution history using `applicationNumberText` and PTAB challenges using `patentNumber`
- **Red Flag Identification** - Focus on revival petitions (37 CFR 1.137), examiner disputes (37 CFR 1.181), and denied decisions for prosecution quality analysis

### Query Examples

```python
# Art unit quality assessment
fpd_search_petitions_by_art_unit(
    art_unit="2128",
    date_range="2020-01-01:2024-12-31",
    limit=100
)

# Complete application petition history
fpd_search_petitions_by_application(
    application_number="17896175",
    include_documents=False
)

# Cross-MCP workflow example
# 1. Find applications with PFW
# 2. Check petition history for red flags
fpd_search_petitions_by_application(
    application_number=app_from_pfw,
    include_documents=True
)
```

### Document Processing Functions

| Function (Display Name) | Purpose | Requirements |
|----------|----------|----------|
| `fpd_get_petition_details` (Get petition details) | Full petition details by UUID with optional documentBag | USPTO_API_KEY |
| `fpd_get_document_content` (FPD get document content) | Intelligent document extraction with cost transparency | USPTO_API_KEY (+ MISTRAL_API_KEY for OCR fallback) |
| `fpd_get_document_download` (FPD get document download) | Secure browser-accessible download URLs | USPTO_API_KEY |

### Document Processing Capabilities

- **Petition Details Tier (`fpd_get_petition_details`)**: Complete petition data retrieval
  - **UUID-based lookup** - Find petition by unique identifier
  - **Optional document bag** - Include/exclude documents based on need
  - **LLM-optimized parsing** - Extracts issues, rules cited, statutes, decision details
  - **Cross-reference fields** - applicationNumberText, patentNumber, groupArtUnitNumber for cross-MCP workflows
- **Intelligent Extraction Tier (`fpd_get_document_content`)**: Hybrid auto-optimized extraction
  - **Smart method selection** - Automatically tries PyPDF2 first (free), falls back to Mistral OCR (API key needed) when needed
  - **Cost optimization** - Only pay for OCR when PyPDF2 extraction fails quality check
  - **Quality detection** - Automatically determines if extraction is usable or requires OCR
  - **Transparent reporting** - Shows which method was used and associated costs
  - **Unified interface** - Single tool handles all document types (eliminates tool confusion)
  - **Advanced capabilities** - Extracts text from scanned documents using Mistral OCR
  - **Cost** - Free for text-based PDFs, ~$0.001/page for scanned OCR using Mistral
- **Browser Download Tier (`fpd_get_document_download`)**: Secure proxy downloads with enhanced filenames
  - **Click-to-download** URLs that work directly in any browser
  - **Centralized proxy integration** - If set up, auto-detects PFW MCP and uses unified proxy (port 8080) for all USPTO documents downloads, will fall back to local proxy if issues detected with centralized proxy.
    - **Persistent links** - 7-day encrypted links when using PFW centralized proxy (work across MCP restarts)
    - **Unified architecture** - Single HTTP proxy (port 8080) for all USPTO MCPs when PFW installed
    - **Standalone fallback** - Local proxy (port 8081) when PFW not detected
  - **Enhanced filenames** - Professional format with petition date, app/patent numbers, and description
    - Format: `PET-2013-09-10_APP-13632078_PAT-8803593_PATENT_PROSECUTION_HIGHWAY_DECISION.pdf`
    - Chronological sorting by petition filing date
    - Instant context for patent attorneys and file management
  - **API key security** - USPTO credentials never exposed in chat history or browser
  - **Rate limiting compliance** - Automatic enforcement of USPTO's 5 downloads per 10 seconds

### LLM Guidance Function

| Function (Display Name) | Purpose | Requirements |
|----------|----------|----------|
| `FPD_get_guidance` (FPD get guidance) | Context-efficient sectioned LLM guidance (80-95% token reduction) | None |

- #### Context-Efficient Guidance System

  **NEW: `fpd_get_guidance` Tool** - Solves MCP Resources visibility problem with selective guidance sections:

**🎯 Quick Refrence Chart** - What section for your question?

​	🔍 "Find petitions by company/art unit" → tools

​	🚩 "Identify petition red flags" → red_flags

​	📄 "Download petition documents" → documents

​	🤝 "Correlate petitions with prosecution" → workflows_pfw

​	⚖️ "Analyze petition + PTAB patterns" → workflows_ptab

​	📊 "Citation quality + petition correlation" → workflows_citations

​	🏢 "Complete portfolio due diligence" → workflows_complete

​	📚 "Research CFR rules with Assistant" → workflows_assistant

​	🎯 "Ultra-minimal PFW + FPD workflows" → ultra_context

​	💰 "Reduce extraction costs" → cost

The tool provides specific workflows, field recommendations, API call optimization strategies, anti-patterns to avoid, and cross-MCP integration patterns for maximum efficiency. See [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md) for detailed examples and integration workflows.

## 💻 Usage Examples & Integration Workflows

For comprehensive usage examples, including:

- **Basic petition searches** (company, type, outcome)
- **Art unit quality assessment** (petition frequency, types, examiner disputes)
- **Application petition history** (complete lifecycle tracking)
- **Cross-MCP integration workflows** (FPD + PFW + PTAB + Pinecone)
- **Red flag identification** (revival petitions, examiner disputes, denied petitions)
- **Document extraction and downloads** (hybrid PyPDF2/OCR approach)
- **Cost optimization strategies**

See the detailed [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md) documentation.

## 🔧 Field Customization

The MCP server supports user-customizable field sets through YAML configuration for optimal context reduction. You can modify field sets without changing any code!

**Configuration file:** `field_configs.yaml` (in project root)

For complete customization guidance, including progressive workflow strategies, token optimization, and advanced field selection patterns, see **[CUSTOMIZATION.md](CUSTOMIZATION.md)**.

## 🔗 Cross-MCP Integration

This MCP is designed to work seamlessly with other USPTO MCPs and knowledge bases for comprehensive patent lifecycle analysis:

### Related USPTO MCP Servers

| MCP Server | Purpose | GitHub Repository |
|------------|---------|-------------------|
| **USPTO Patent File Wrapper (PFW)** | Prosecution history & documents | [uspto_pfw_mcp](https://github.com/john-walkoe/uspto_pfw_mcp.git) |
| **USPTO Final Petition Decisions (FPD)** | Petition decisions during prosecution | [uspto_fpd_mcp](https://github.com/john-walkoe/uspto_fpd_mcp.git) |
| **USPTO Enhanced Citations** | AI-extracted citation intelligence from Office Actions mailed Oct 2017-present (apps filed 2015+) | [uspto_enriched_citation_mcp](https://github.com/john-walkoe/uspto_enriched_citation_mcp.git) |
| **USPTO Patent Trial and Appeal Board (PTAB)** | Post-grant challenges | [uspto_ptab_mcp](https://github.com/john-walkoe/uspto_ptab_mcp.git) |
| **Pinecone Assistant MCP** | Patent law knowledge base with AI-powered chat and citations (MPEP, examination guidance) - 1 API key, limited free tier | [pinecone_assistant_mcp](https://github.com/john-walkoe/pinecone_assistant_mcp.git) |
| **Pinecone RAG MCP** | Patent law knowledge base with custom embeddings (MPEP, examination guidance) - Requires Pinecone + embedding model, monthly resetting free tier | [pinecone_rag_mcp](https://github.com/john-walkoe/pinecone_rag_mcp.git) |

### Integration Overview

The **Final Petition Decisions (FPD) MCP** bridges prosecution and post-grant challenges, tracking procedural petitions that reveal prosecution quality issues. When combined with the other MCPs, it enables:

- **FPD + PFW**: Understand petition context by cross-referencing with prosecution history
- **FPD + PFW + Enhanced Citations**: Correlate petition patterns with examiner citation quality for comprehensive prosecution assessment (Oct 2017+ applications)
- **FPD + PTAB**: Correlate petition red flags with post-grant challenge outcomes
- **PFW + FPD + PTAB**: Complete patent lifecycle tracking from filing through post-grant challenges
- **PFW + FPD + Enhanced Citations**: Art unit quality assessment with citation intelligence and petition pattern analysis
- **FPD + Pinecone (Assistant or RAG)**: Research MPEP guidance and petition standards before extracting expensive documents

### Key Integration Patterns

**Cross-Referencing Fields:**

- `applicationNumberText` - Primary key linking petitions to PFW prosecution and Enhanced Citations
- `patentNumber` - Secondary key linking granted patents to PTAB challenges
- `groupArtUnitNumber` - Art unit analysis across all MCPs (FPD, PFW, Enhanced Citations, PTAB)
- `firstApplicantName` - Party matching across MCPs
- `examinerCitedReferenceIndicator` (Citations MCP) - Examiner vs applicant citation analysis for petition quality correlation

**Progressive Workflow:**
1. **Discovery** (FPD): Find petitions using minimal search
2. **Prosecution Context** (PFW): Cross-reference petition applications with prosecution history
3. **Citation Intelligence** (Enhanced Citations): Analyze examiner citation quality for applications with petitions (Oct 2017+ only)
4. **Challenge Assessment** (PTAB): Check if patents with petition red flags faced post-grant challenges
5. **Knowledge Research** (RAG): Research MPEP petition guidance if available
6. **Detailed Analysis** (FPD): Extract petition documents for Director's reasoning
7. **Risk Scoring**: Quantify prosecution quality based on petition patterns, citation quality, and outcomes

For detailed integration workflows, cross-referencing examples, and complete use cases, see [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md#cross-mcp-integration-workflows).

## 🆕Centralized Proxy Integration (PFW + FPD)

When both PFW and FPD MCPs are installed, FPD automatically integrates with PFW's centralized proxy for unified document management:

**Architecture Benefits:**

- **Single Port** - One HTTP server (port 8080) for all USPTO document downloads
- **Persistent Links** - 7-day encrypted links via PFW's SQLite database (work across MCP restarts)
- **Unified Rate Limiting** - Shared USPTO limits (5 requests/10 seconds) across all MCPs
- **Cross-MCP Caching** - PFW caches documents from all USPTO MCPs for faster access
- **Automatic Detection** - FPD detects PFW at startup and switches to centralized mode

**How It Works:**

1. FPD extracts PDF download URL from USPTO API response
2. FPD generates enhanced filename: `PET-{date}_APP-{app}_PAT-{patent}_{description}.pdf`
3. FPD registers document with PFW: `POST /register-fpd-document` (includes enhanced filename)
4. PFW stores metadata in database (petition_id, download_url, api_key, enhanced_filename)
5. FPD returns download link: `http://localhost:8080/download/{petition_id}/{doc_id}`
6. User clicks link → PFW fetches from USPTO → streams PDF with enhanced filename
7. Link persists for 7 days and works across MCP restarts

**Standalone Mode:**

- Without PFW: FPD uses local proxy (port 8081) for immediate session-based downloads
- Enhanced filenames still work (same generation logic used locally)
- Graceful fallback ensures FPD works independently with full filename functionality

## 📈 Performance Comparison

| Method | Response Size | Context Usage | Features |
|--------|---------------|---------------|----------|
| **Direct curl** | ~100KB+ | High | Raw API access |
| **MCP Balanced** | ~10KB | Medium | Key fields for analysis |
| **MCP Minimal** | ~2KB | Very Low | Essential data only |

## 🧪 Testing

### Core Tests (Essential)

**With uv (Recommended):**
```bash
# Test core functionality and field configuration
uv run python tests/test_basic.py

# Expected: ALL TESTS PASSED!
```

**With traditional Python:**
```bash
python tests/test_basic.py
```

### Expected Outputs

**test_basic.py:**
```
[OK] Settings imported successfully
[OK] FieldManager imported successfully
[OK] FPDClient initialized successfully
ALL TESTS PASSED!
```

See [tests/README.md](tests/README.md) for comprehensive testing guide.

##  📁 Project Structure

```
uspto_fpd_mcp/
├── field_configs.yaml             # Root-level field customization
├── .security/                      # Security scanning components
│   ├── fpd_prompt_injection_detector.py # Enhanced prompt injection detection
│   └── check_prompt_injections.py # Standalone scanning script
├── src/
│   └── fpd_mcp/
│       ├── main.py                 # MCP server with 8 tools
│       ├── __main__.py            # Entry point for -m execution
│       ├── secure_storage.py       # Windows DPAPI secure storage
│       ├── shared_secure_storage.py
│       ├── config/
│       │   ├── field_manager.py   # Configuration management
│       │   ├── settings.py        # Environment configuration
│       │   ├── tool_reflections.py # Sectioned LLM guidance (11 sections, 80-95% token reduction)
│       │   ├── api_constants.py   # API configuration constants
│       │   ├── api_key_validation.py
│       │   └── storage_paths.py    # Storage path management
│       ├── prompts/
│       │   ├── __init__.py        # Prompt registration
│       │   ├── company_petition_risk_assessment_pfw.py
│       │   ├── art_unit_quality_assessment.py
│       │   ├── revival_petition_analysis.py
│       │   ├── petition_document_research_package.py
│       │   ├── complete_portfolio_due_diligence_pfw_ptab.py
│       │   ├── litigation_research_setup_pfw.py
│       │   ├── prosecution_quality_correlation_pfw.py
│       │   ├── patent_vulnerability_assessment_ptab.py
│       │   ├── petition_quality_with_citation_intelligence.py
│       │   └── examiner_dispute_citation_analysis.py
│       ├── api/
│       │   ├── fpd_client.py      # FPD API client
│       │   └── field_constants.py # Field name constants
│       ├── proxy/
│       │   ├── server.py          # HTTP proxy for secure downloads
│       │   └── rate_limiter.py    # USPTO rate limiting compliance
│       ├── shared/
│       │   ├── error_utils.py     # Error handling utilities
│       │   ├── circuit_breaker.py # Circuit breaker pattern
│       │   ├── internal_auth.py   # Internal authentication
│       │   ├── structured_logging.py
│       │   └── security_logger.py # Security event logging
│       ├── services/
│       │   └── fpd_service.py     # Core business logic layer
│       ├── monitoring/
│       │   └── metrics.py         # Performance monitoring
│       └── util/
│           ├── logging.py         # Enhanced logging utilities
│           └── secure_logger.py   # Secure logging functionality
├── deploy/
│   ├── linux_setup.sh            # Linux deployment script
│   ├── windows_setup.ps1         # PowerShell deployment script
│   ├── manage_api_keys.ps1       # API key management utilities
│   ├── Validation-Helpers.psm1   # PowerShell validation module
│   └── Validation-Helpers.sh     # Bash validation helpers
├── tests/
│   ├── test_basic.py             # Core functionality test
│   ├── test_integration.py       # Integration tests
│   ├── test_tiered_convenience_params.py
│   ├── test_unified_key_management.py
│   ├── test_unified_storage.py
│   ├── validate_convenience_params_implementation.py
│   └── README.md                 # Testing documentation
├── reference/
│   ├── Document_Descriptions_List.csv
│   ├── FinalPetitionDecisions_swagger.yaml
│   ├── petition-decision-schema.json
│   └── README.md
├── documentation_photos/          # Visual documentation
│   ├── Prompts-Step1.jpg         # Prompt template usage guides
│   ├── Prompts-Step2.jpg
│   ├── Prompts-Step3.jpg
│   ├── Prompts-Step4.jpg
│   ├── Prompts-Step5.jpg
│   └── n8n_FPD.jpg               # N8N integration example
├── pyproject.toml                 # Package configuration
├── README.md                      # This file
├── INSTALL.md                     # Comprehensive installation guide
├── USAGE_EXAMPLES.md             # Function examples and workflows
├── CUSTOMIZATION.md              # Field configuration and optimization guide
├── PROMPTS.md                    # Prompt templates documentation
├── SECURITY_GUIDELINES.md        # Security best practices
├── SECURITY_SCANNING.md          # Automated secret detection guide
└── LICENSE                       # MIT License
```

## 🔍 Troubleshooting

### Common Issues

#### API Key Issues
- **For Claude Desktop:** API keys in config file are sufficient
- **For test scripts:** Environment variables must be set

**Setting USPTO API Key:**
- **Windows Command Prompt:** `set USPTO_API_KEY=your_key`
- **Windows PowerShell:** `$env:USPTO_API_KEY="your_key"`
- **Linux/macOS:** `export USPTO_API_KEY=your_key`

**Setting Mistral API Key (for OCR):**
- **Windows Command Prompt:** `set MISTRAL_API_KEY=your_key`
- **Windows PowerShell:** `$env:MISTRAL_API_KEY="your_key"`
- **Linux/macOS:** `export MISTRAL_API_KEY=your_key`

#### uv vs pip Issues
- **uv advantages:** Better dependency resolution, faster installs
- **Mixed installation:** Can use both `uv sync` and `pip install -e .`
- **Testing:** Use `uv run` prefix for uv-managed projects

#### Fields Not Returning Data
- **Cause:** Field name not in YAML config
- **Solution:** Edit `field_configs.yaml` to include desired fields

#### Authentication Errors
- **Cause:** Missing or invalid API key
- **Solution:** Verify `USPTO_API_KEY` environment variable or Claude Desktop config

#### MCP Server Won't Start
- **Cause:** Missing dependencies or incorrect paths
- **Solution:** Re-run setup script, restart all PowerShell windows, restart Claude Desktop (or other MCP Client) and verify configuration
- **If problems persist:** Reset the MCP installation (see "Resetting MCP Installation" below)

#### Virtual Environment Issues (Windows Setup)
- **Symptom:** "No pyvenv.cfg file" errors during `windows_setup.ps1`
- **Cause:** Claude Desktop locks `.venv` files when running, preventing proper virtual environment creation
- **Solution:**
  1. Close Claude Desktop completely before running setup script
  2. Remove `.venv` folder: `Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue`
  3. Run `.\deploy\windows_setup.ps1` again

#### Resetting MCP Installation

**If you need to completely reset the MCP installation to run the Windows Quick installer again:**

```powershell
# Navigate to the project directory
cd C:\Users\YOUR_USERNAME\uspto_fpd_mcp

# Remove Python cache directories
Get-ChildItem -Path ./src -Directory -Recurse -Force | Where-Object { $_.Name -eq '__pycache__' } | Remove-Item -Recurse -Force

# Remove virtual environment
if (Test-Path ".venv") {
    Remove-Item ./.venv -Force -Recurse -ErrorAction SilentlyContinue
}

# Remove database files (if any)
Remove-Item ./proxy_documents.db -Force -ErrorAction SilentlyContinue
Remove-Item ./petition_links.db -Force -ErrorAction SilentlyContinue

# Now you can run the setup script again
.\deploy\windows_setup.ps1
```

**Linux/macOS Reset:**
```bash
# Navigate to the project directory
cd ~/uspto_fpd_mcp

# Remove Python cache directories
find ./src -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Remove virtual environment and database files
rm -rf .venv
rm -f proxy_documents.db petition_links.db

# Run setup script again
./deploy/linux_setup.sh
```

### Getting Help
1. Check the test scripts for working examples
2. Review the field configuration in `field_configs.yaml`
3. Verify your Claude Desktop configuration matches the provided templates in INSTALL.md

## 🛡️ Security & Production Readiness

### Enhanced Error Handling
- **Retry logic with exponential backoff** - Automatic retries for transient failures (3 attempts with 1s, 2s, 4s delays)
- **Smart retry strategy** - Doesn't retry authentication errors or client errors (4xx)
- **Structured logging** - Request ID tracking for better debugging and monitoring
- **Production-grade resilience** - Handles timeouts, network issues, and API rate limits gracefully
- **Configurable timeouts** - USPTO_TIMEOUT and USPTO_DOWNLOAD_TIMEOUT environment variables for API request tuning

### Security Features
- **🔐 Windows DPAPI Secure Storage** - API keys encrypted with Windows Data Protection API (user-specific encryption)
- **🛡️ Safe Logging with Auto-Sanitization** - All logging automatically masks API keys, tokens, and sensitive data; file-based audit trail with rotation in `~/.uspto_fpd_mcp/logs/`
- **Environment variable API keys** - No hardcoded credentials anywhere in codebase
- **Zero plain text API keys** - Secure storage option eliminates API keys from Claude Desktop config files
- **Cross-platform security** - Automatic fallback to environment variables on non-Windows systems
- **Secure test patterns** - Test files use environment variables with fallbacks
- **Comprehensive .gitignore** - Prevents accidental credential commits
- **Security guidelines** - Complete documentation for secure development practices
- **Automated secret scanning** - CI/CD and pre-commit hooks prevent API key leaks (detect-secrets)
- **20+ secret types detected** - AWS keys, GitHub tokens, JWT, private keys, API keys, and more
- **Prompt injection detection** - 70+ pattern detection system protects against AI-specific attacks
- **Baseline management** - Tracks known placeholders while catching real secrets
- **Field name constants** - Eliminates magic strings, reduces typo-based security issues

### Request Tracking & Debugging
All API requests include unique request IDs (8-char UUIDs) for correlation:
```
[a1b2c3d4] Starting GET request to petition/decisions/search
[a1b2c3d4] Request successful on attempt 1
```

### Documentation
- `SECURITY_GUIDELINES.md` - Comprehensive security best practices
- `SECURITY_SCANNING.md` - Automated secret detection and prevention guide
- `tests/README.md` - Complete testing guide with API key setup
- Enhanced error messages with request IDs for better support

## 📝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

MIT License

## ⚠️ Disclaimer

**THIS SOFTWARE IS PROVIDED "AS IS" AND WITHOUT WARRANTY OF ANY KIND.**

**Independent Project Notice**: This is an independent personal project and is not affiliated with, endorsed by, or sponsored by the United States Patent and Trademark Office (USPTO).

The author makes no representations or warranties, express or implied, including but not limited to:

- **Accuracy & AI-Generated Content**: No guarantee of data accuracy, completeness, or fitness for any purpose. Users are specifically cautioned that outputs generated or assisted by Artificial Intelligence (AI) components, including but not limited to text, data, or analyses, may be inaccurate, incomplete, fictionalized, or represent "hallucinations" (confabulations) by the AI model.
- **Availability**: USPTO API and Mistral API dependencies may cause service interruptions.
- **Legal Compliance**: Users are solely responsible for ensuring their use of this software, and any submissions or actions taken based on its outputs, strictly comply with all applicable laws, regulations, and policies, including but not limited to:
  - The latest [Guidance on Use of Artificial Intelligence-Based Tools in Practice Before the United States Patent and Trademark Office](https://www.federalregister.gov/documents/2024/04/11/2024-07629/guidance-on-use-of-artificial-intelligence-based-tools-in-practice-before-the-united-states-patent) (USPTO Guidance).
  - The USPTO's Duty of Candor and Good Faith (e.g., 37 CFR 1.56, 11.303), which includes a duty to disclose material information and correct errors.
  - The USPTO's signature requirements (e.g., 37 CFR 1.4(d), 2.193(c), 11.18), certifying human review and reasonable inquiry.
  - All rules regarding inventorship (e.g., each claimed invention must have at least one human inventor).
- **Legal Advice**: This tool provides data access and processing only, not legal counsel. All results must be independently verified, critically analyzed, and professionally judged by qualified legal professionals.
- **Commercial Use**: Users must verify USPTO and Mistral terms for commercial applications.
- **Confidentiality & Data Security**: The author makes no representations regarding the confidentiality or security of any data, including client-sensitive or technical information, input by the user into the software's AI components or transmitted to third-party AI services (e.g., Mistral API). Users are responsible for understanding and accepting the privacy policies, data retention practices, and security measures of any integrated third-party AI services.
- **Foreign Filing Licenses & Export Controls**: Users are solely responsible for ensuring that the input or processing of any data, particularly technical information, through this software's AI components does not violate U.S. foreign filing license requirements (e.g., 35 U.S.C. 184, 37 CFR Part 5) or export control regulations (e.g., EAR, ITAR). This includes awareness of potential "deemed exports" if foreign persons access such data or if AI servers are located outside the United States.

**LIMITATION OF LIABILITY:** Under no circumstances shall the author be liable for any direct, indirect, incidental, special, or consequential damages arising from use of this software, even if advised of the possibility of such damages.

### USER RESPONSIBILITY: YOU ARE SOLELY RESPONSIBLE FOR THE INTEGRITY AND COMPLIANCE OF ALL FILINGS AND ACTIONS TAKEN BEFORE THE USPTO.

- **Independent Verification**: All outputs, analyses, and content generated or assisted by AI within this software MUST be thoroughly reviewed, independently verified, and corrected by a human prior to any reliance, action, or submission to the USPTO or any other entity. This includes factual assertions, legal contentions, citations, evidentiary support, and technical disclosures.
- **Duty of Candor & Good Faith**: You must adhere to your duty of candor and good faith with the USPTO, including the disclosure of any material information (e.g., regarding inventorship or errors) and promptly correcting any inaccuracies in the record.
- **Signature & Certification**: You must personally sign or insert your signature on any correspondence submitted to the USPTO, certifying your personal review and reasonable inquiry into its contents, as required by 37 CFR 11.18(b). AI tools cannot sign documents, nor can they perform the required human inquiry.
- **Confidential Information**: DO NOT input confidential, proprietary, or client-sensitive information into the AI components of this software without full client consent and a clear understanding of the data handling practices of the underlying AI providers. You are responsible for preventing inadvertent or unauthorized disclosure.
- **Export Controls**: Be aware of and comply with all foreign filing license and export control regulations when using this tool with sensitive technical data.
- **Service Compliance**: Ensure compliance with all USPTO (e.g., Terms of Use for USPTO websites, USPTO.gov account policies, restrictions on automated data mining) and Mistral terms of service. AI tools cannot obtain USPTO.gov accounts.
- **Security**: Maintain secure handling of API credentials and client information.
- **Testing**: Test thoroughly before production use.
- **Professional Judgment**: This tool is a supplement, not a substitute, for your own professional judgment and expertise.

**By using this software, you acknowledge that you have read this disclaimer and agree to use the software at your own risk, accepting full responsibility for all outcomes and compliance with relevant legal and ethical obligations.**

> **Note for Legal Professionals:** While this tool provides access to patent research tools commonly used in legal practice, it is a data retrieval and AI-assisted processing system only. All results require independent verification, critical professional analysis, and cannot substitute for qualified legal counsel or the exercise of your personal professional judgment and duties outlined in the USPTO Guidance on AI Use.

## 🔗 Related Links

- [USPTO Open Data Portal](https://data.uspto.gov/myodp)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [Claude](https://claude.ai)
- [uv Package Manager](https://github.com/astral-sh/uv)
- [Mistral AI](https://mistral.ai/solutions/document-ai)

## 💝 Support This Project

If you find this USPTO Final Petition Decisions MCP Server useful, please consider supporting the development! This project was developed during my personal time over many hours to provide a comprehensive, production-ready tool for the patent community.

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://paypal.me/walkoe)

Your support helps maintain and improve this open-source tool for everyone in the patent community. Thank you!

## Acknowledgments

- [USPTO](https://www.uspto.gov/) for providing the Final Petition Decisions API
- [Model Context Protocol](https://modelcontextprotocol.io/) for the MCP specification
- **[Claude Code](https://claude.ai/code)** for exceptional development assistance, architectural guidance, documentation creation, PowerShell automation, test organization, and comprehensive code development throughout this project
- **[Claude Desktop](https://claude.ai)** for additional development support and testing assistance

---

**Questions?** See [INSTALL.md](INSTALL.md) for complete cross-platform installation guide or review the test scripts for working examples.
