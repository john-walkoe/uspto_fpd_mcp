"""
Tool reflections and comprehensive guidance for USPTO Final Petition Decisions MCP.

This module contains the detailed guidance, workflows, and cross-MCP integration patterns
that are returned by the FPD_get_guidance tool (sectioned approach).
"""


def get_guidance_section(section: str = "overview") -> str:
    """
    Get selective USPTO FPD guidance sections for context-efficient workflows.

    Args:
        section: Section name (default: "overview")

    Returns:
        Markdown-formatted string for requested section
    """
    sections = {
        "overview": _get_overview_section(),
        "workflows_pfw": _get_workflows_pfw_section(),
        "workflows_ptab": _get_workflows_ptab_section(),
        "workflows_citations": _get_workflows_citations_section(),
        "workflows_complete": _get_workflows_complete_section(),
        "workflows_assistant": _get_workflows_assistant_section(),
        "tools": _get_tools_section(),
        "red_flags": _get_red_flags_section(),
        "documents": _get_documents_section(),
        "ultra_context": _get_ultra_context_section(),
        "cost": _get_cost_section()
    }

    if section not in sections:
        return f"Error: Section '{section}' not found. Available sections: {', '.join(sections.keys())}"

    return sections[section]


def _get_overview_section() -> str:
    """Overview section with quick reference chart and section guide"""
    return """# USPTO Final Petition Decisions MCP - Tool Guidance

**Version:** 3.0
**Last Updated:** 2025-11-02

## Available Sections and Quick Reference

### 🎯 Quick Reference Chart - What section for your question?

- 🔍 **"Find petitions by company/art unit"** → `tools`
- 🚩 **"Identify petition red flags"** → `red_flags`
- 📄 **"Download petition documents"** → `documents`
- 🤝 **"Correlate petitions with prosecution"** → `workflows_pfw`
- ⚖️ **"Analyze petition + PTAB patterns"** → `workflows_ptab`
- 📊 **"Citation quality + petition correlation"** → `workflows_citations`
- 🏢 **"Complete portfolio due diligence"** → `workflows_complete`
- 📚 **"Research CFR rules with Assistant"** → `workflows_assistant`
- 🎯 **"Ultra-minimal PFW + FPD workflows"** → `ultra_context`
- 💰 **"Reduce extraction costs"** → `cost`

### Available Sections:
- **overview**: Available sections and MCP overview (this section)
- **workflows_pfw**: FPD + PFW integration workflows
- **workflows_ptab**: FPD + PTAB integration workflows
- **workflows_citations**: FPD + Citations integration workflows
- **workflows_complete**: Four-MCP complete lifecycle analysis
- **workflows_assistant**: Pinecone Assistant + FPD research workflows
- **tools**: Tool catalog, progressive disclosure, parameters
- **red_flags**: Petition red flag indicators and CFR rules
- **documents**: Document extraction, downloads, proxy configuration
- **ultra_context**: PFW fields parameter + ultra-minimal workflows
- **cost**: Cost optimization for document extraction

### Context Efficiency Benefits:
- **80-95% token reduction** (2-8KB per section vs 62KB total)
- **Targeted guidance** for specific workflows
- **Same comprehensive content** organized for efficiency
- **Consistent pattern** with PFW MCP

## MCP Overview

**Name:** USPTO Final Petition Decisions MCP
**Purpose:** Track prosecution-related petitions (37 CFR 1.181, 1.182, 1.183)
**Position in Lifecycle:** Bridges normal prosecution (PFW) and post-grant challenges (PTAB)
**Data Source:** USPTO Open Data Portal - Final Petition Decisions API
**Authentication:** Same USPTO_API_KEY as Patent File Wrapper MCP

## Available Tools Summary

### Search Tools
- **fpd_search_petitions_minimal**: Ultra-fast discovery (50-100 petitions, 8 fields, 95-99% reduction)
- **fpd_search_petitions_balanced**: Detailed analysis (10-20 petitions, 18 fields, 80-88% reduction)
- **fpd_search_petitions_by_art_unit**: Art unit quality assessment
- **fpd_search_petitions_by_application**: Complete petition history for application

### Detail Tools
- **fpd_get_petition_details**: Full petition details with optional documents
- **fpd_get_document_download**: Browser-accessible PDF downloads via proxy
- **fpd_get_document_content**: Text extraction from petition PDFs (hybrid PyPDF2 + Mistral OCR)

### Guidance Tool
- **FPD_get_guidance**: Context-efficient sectioned guidance (this tool)
"""


def _get_workflows_pfw_section() -> str:
    """FPD + PFW integration workflows"""
    return """## FPD + PFW Integration Workflows

### Workflow 1: Complete Patent Lifecycle Tracking

**Scenario:** Due diligence on target company portfolio

**Steps:**
1. **PFW:** Get company's patent portfolio
   ```python
   pfw_search_applications_minimal(applicant_name='Target Co', limit=100)
   ```
2. **FPD:** Check petition history for procedural issues
   ```python
   fpd_search_petitions_by_application(application_number='17896175')
   ```
3. Identify patterns: Abandonments, examiner disputes, procedural problems
4. **PTAB:** Cross-check PTAB challenge history for granted patents
5. Analyze: Prosecution quality with petition context

**Value:** Holistic view of patent prosecution and challenge history

### Workflow 2: Abandonment and Revival Analysis

**Scenario:** Assessing patents with revival history

**Steps:**
1. **FPD:** Find revival petitions (37 CFR 1.137)
   ```python
   fpd_search_petitions_balanced(petition_type_code='551', limit=50)
   ```
2. **PFW:** Get full prosecution history to understand abandonment reason
   ```python
   pfw_search_applications_minimal(application_number='17896175')
   ```
3. Categorize: Missed deadline vs. strategic abandonment
4. **PFW:** Check post-revival prosecution quality
5. Context: Understand procedural issues in portfolio

**Value:** Understand IP management quality and procedural compliance

### Workflow 3: Art Unit Procedural Analysis

**Scenario:** Identifying art units with petition patterns

**Steps:**
1. **FPD:** Get all petitions for art unit
   ```python
   fpd_search_petitions_by_art_unit(art_unit='2128', date_range='2020-01-01:2024-12-31')
   ```
2. Categorize: Examiner disputes, restriction appeals, rule waivers
3. **PFW:** Cross-reference to get examiner names
   ```python
   pfw_search_applications_minimal(art_unit='2128', fields=['applicationNumberText', 'examinerNameText'], limit=100)
   ```
4. Analyze: Petition frequency and types by examiner

**Value:** Understand procedural patterns in prosecution

### Learning PFW Workflows

**Context-Efficient Guidance Tool:** `pfw_get_guidance`

When working with cross-MCP workflows, use PFW's selective guidance tool:

**Relevant Sections for FPD Users:**
- `workflows_fpd`: FPD+PFW integration workflows, petition red flag analysis
- `workflows_complete`: Complete company due diligence across PFW, FPD, PTAB
- `tools`: PFW convenience parameter searches
- `fields`: Ultra-minimal field selection for 99% context reduction
- `cost`: API cost optimization strategies

**Quick Reference:**
```python
# Learn FPD+PFW workflows
pfw_get_guidance('workflows_fpd')

# Learn complete due diligence workflows
pfw_get_guidance('workflows_complete')
```

### PFW XML Data Retrieval - Token Optimization

**IMPORTANT:** If you need detailed patent/application XML data from PFW (beyond search metadata), use the `pfw_get_patent_or_application_xml` tool with `include_raw_xml=False` for massive token savings.

**Token Reduction:**
- With `include_raw_xml=True` (default): ~55KB per application (~50K chars raw XML)
- With `include_raw_xml=False`: ~5KB per application (91% reduction)
- With `include_raw_xml=False` + `include_fields`: ~500 chars (99% reduction)

**Best Practice:**
```python
# RECOMMENDED: Exclude raw XML (91% token reduction)
pfw_get_patent_or_application_xml(
    application_number='17896175',
    include_raw_xml=False  # ← CRITICAL for cross-MCP workflows
)

# EVEN BETTER: Selective fields (99% reduction)
pfw_get_patent_or_application_xml(
    application_number='17896175',
    include_raw_xml=False,
    include_fields=['title', 'abstract', 'claims', 'assignee']
)
```

**Why This Matters for FPD Workflows:**
- Cross-MCP workflows share context budget across multiple MCPs
- Raw XML contains ~50K chars of unparsed data most workflows don't need
- Using `include_raw_xml=False` allows 10x more applications in same context window
- Perfect for: Due diligence, portfolio analysis, petition correlation studies

**When to Use Each Approach:**
- **Search tools only** (`pfw_search_applications_minimal`): Entity lookup, portfolio discovery (current FPD workflows)
- **XML with `include_raw_xml=False`**: Detailed prosecution analysis, claim review
- **XML with `include_fields`**: Ultra-targeted data extraction, large-scale analysis
"""


def _get_workflows_ptab_section() -> str:
    """FPD + PTAB integration workflows"""
    return """## FPD + PTAB Integration Workflows

### Three-MCP Availability

All three USPTO MCPs support cross-referencing:

1. **PFW (Patent File Wrapper)** - Filing and prosecution history
2. **FPD (Final Petition Decisions)** - Petition context and procedural issues
3. **PTAB (Patent Trial and Appeal Board)** - Post-grant challenges

**Complete Lifecycle:** PFW (filing) → FPD (petitions) → Grant → PTAB (challenges)

**Integration Value:** Each MCP provides different aspects of patent lifecycle

### Workflow: Prosecution Quality → PTAB Vulnerability Correlation

**Scenario:** Assess if petition patterns predict PTAB challenge vulnerability

**Steps:**
1. **PFW:** Get granted patents for target company
   ```python
   pfw_search_applications_minimal(applicant_name='Target', status='Patented', limit=100)
   ```
2. **FPD:** Check petition history during prosecution
   ```python
   fpd_search_petitions_by_application(application_number='17896175')
   ```
3. **PTAB:** Check for post-grant challenges
   ```python
   ptab_search_proceedings_minimal(patent_number='11788453')
   ```
4. Correlation Analysis:
   - Patents with denied examiner dispute petitions → Higher PTAB vulnerability
   - Patents with revival petitions → Procedural risk indicators
   - Multiple petitions during prosecution → Quality concerns

**Red Flags:**
- Denied 37 CFR 1.181 petitions (examiner disputes) + PTAB challenge = Examination quality issues
- Revival petitions + PTAB IPR = Procedural and substantive weakness
- High petition frequency + PTAB institution = Pattern of prosecution problems

**Value:** Predict PTAB vulnerability based on prosecution petition patterns
"""


def _get_workflows_citations_section() -> str:
    """FPD + Citations integration workflows"""
    return """## FPD + Citations Integration Workflows

### Overview

Enhanced Citations MCP provides AI-extracted citation intelligence from USPTO Office Actions (Oct 1, 2017 - present).

**Data Coverage:** Office Actions MAILED from October 1, 2017 to 30 days prior
**Effective Filing Date Coverage:** Applications filed 2015-2016+ typically have citation data
**Context Reduction:** 90-95% through progressive disclosure

### Workflow 1: Art Unit Petition Quality with Citation Intelligence

**Scenario:** Art unit 2128 has high petition rate - assess if citation quality is a factor

**Steps:**
1. **PFW Discovery:** Get art unit applications
   ```python
   pfw_search_applications_minimal(art_unit='2128', filing_date_start='2015-01-01',
                                   fields=['applicationNumberText', 'examinerNameText'], limit=100)
   ```
2. **FPD Petition Patterns:** Get art unit petitions
   ```python
   fpd_search_petitions_by_art_unit(art_unit='2128')
   ```
3. Calculate baseline petition rate
4. **Citation Analysis:** For 20-30 applications
   ```python
   search_citations_minimal(application_number=app_num, rows=50)
   ```
5. Aggregate citation metrics:
   - Citation density (citations per application)
   - Examiner citation ratio (examinerCitedReferenceIndicator=true / total)
   - Citation category distribution
6. Correlation Analysis:
   - LOW citation quality + HIGH petition rate = Art unit quality issues
   - Normal citations + high petitions = Complex technology

**Red Flags:**
- Examiner citation ratio below 50% (inadequate search)
- Low citation density (<5 citations) in citation-heavy tech
- High petition rate (>15%) correlating with low citation quality

### Workflow 2: Examiner Dispute Petitions with Citation Correlation

**Scenario:** 37 CFR 1.181 petitions - check if citation patterns indicate examiner issues

**Critical:** MUST start with PFW (examiner name not in FPD or Citations APIs)

**Steps:**
1. **PFW Examiner Discovery:**
   ```python
   pfw_search_applications_minimal(examiner_name='Smith, John', filing_date_start='2015-01-01',
                                   fields=['applicationNumberText'], limit=100)
   ```
2. **FPD Dispute Identification:** Check each application for petitions
3. Categorize: DISPUTED (has 1.181 petition) vs NON-DISPUTED
4. **Citation Analysis:** Compare citation metrics between groups
5. Correlation patterns:
   - DISPUTED apps with LOWER examiner citation rate → Inadequate search
   - DISPUTED apps normal citations → Disputes unrelated to search quality

**Citation Quality Indicators:**
- Healthy: Examiner citation ratio above 60%, 10+ citations per app
- Concern: Examiner citation ratio below 50%
- Critical: Below 30% + high dispute rate + granted petitions

### When to Use Citations Integration

**Use citations when:**
- Analyzing art unit quality with comprehensive assessment
- Investigating examiner dispute petitions for root cause
- Applications filed 2015-2016+ (likely have Office Action data)

**Skip citations when:**
- Applications filed before 2015 (unlikely to have data)
- Only need petition red flags without citation context
- Time/token budget limited
"""


def _get_workflows_complete_section() -> str:
    """Complete four-MCP lifecycle workflows"""
    return """## Complete Four-MCP Lifecycle Analysis

### Complete M&A Due Diligence

**Scenario:** Comprehensive patent intelligence across all USPTO databases

**Four-MCP Integration Workflow:**

1. **Portfolio Discovery (PFW)**
   ```python
   pfw_search_applications_minimal(applicant_name='Target Company',
                                   filing_date_start='2015-01-01', limit=100)
   ```

2. **Citation Intelligence (Citations)** - For applications filed 2015-2016+
   ```python
   search_citations_minimal(application_number=app_num, rows=50)
   ```
   Analyze examiner citation patterns for prosecution quality

3. **FPD Risk Assessment (FPD)**
   ```python
   fpd_search_petitions_by_application(application_number=app_num)
   ```
   Check procedural irregularities and petition history

4. **PTAB Challenge Analysis (PTAB)** - For granted patents
   ```python
   ptab_search_proceedings_minimal(patent_number=patent_num)
   ```
   Assess post-grant challenge exposure

5. **Document Intelligence (PFW)**
   Extract key prosecution documents for detailed analysis

6. **Comprehensive Reporting**
   Integrate findings across all four data sources

**Enhanced Risk Scoring Matrix:**
- **Technical Strength**: Claim scope, prosecution quality, prior art landscape
- **Legal Enforceability**: Citation thoroughness, procedural cleanliness
- **Challenge Exposure**: PTAB proceedings history and outcomes
- **Procedural Issues**: FPD petition patterns and denial history

### Patent Lifecycle Stages and MCP Coverage

**Stage 1: Filing (PFW)**
- Application filing and initial prosecution
- Examiner assignments and office actions
- Amendments and responses

**Stage 2: Procedural Issues (FPD)**
- Revival petitions (missed deadlines)
- Examiner disputes (supervisory review)
- Restriction challenges

**Stage 3: Citation Intelligence (Citations)** - Oct 2017+
- Examiner search quality assessment
- Prior art thoroughness
- Citation category analysis

**Stage 4: Grant (PFW)**
- Patent issuance
- Final prosecution history

**Stage 5: Post-Grant Challenges (PTAB)**
- IPR, PGR, CBM proceedings
- Challenge outcomes and validity assessment

**Value:** Complete prosecution and challenge intelligence across patent lifecycle
"""


def _get_workflows_assistant_section() -> str:
    """Pinecone Assistant + FPD research workflows"""
    return """## Pinecone Assistant Integration (Optional)

### Overview

Optional integration with Pinecone Assistant MCP for petition legal research.

**Availability:** If Pinecone Assistant MCP is available in current session
**Graceful Degradation:** All FPD workflows function fully without Assistant
**Value:** Research CFR interpretations and Director policy (Free) before extracting documents
**Knowledge Base:** MPEP sections, 37 CFR interpretations, Director policy memoranda

### High-Value Assistant Scenarios

#### Scenario 1: Revival Petition Strategy

**Problem:** Understanding 37 CFR 1.137 revival requirements

**Workflow:**
1. Find similar revival petitions
   ```python
   fpd_search_petitions_balanced(petition_type_code='551', limit=20)
   ```
2. Assistant research
   ```python
   assistant_context(query='37 CFR 1.137 revival requirements MPEP 711 unintentional delay',
                    top_k=3, snippet_size=1024, temperature=0.3)
   ```
3. Understand Director standards and common denial reasons
4. Select 2-3 successful petitions based on guidance
5. Extract petition text
   ```python
   fpd_get_document_content(petition_id, doc_id)
   ```

**Value:** Draft petition aligned with current Director standards

#### Scenario 2: Examiner Dispute Analysis

**Problem:** Supervisory review petition (37 CFR 1.181) - understanding standards

**Workflow:**
1. Find similar disputes
   ```python
   fpd_search_petitions_balanced(petition_type_code='181', art_unit='2128', limit=20)
   ```
2. Assistant research
   ```python
   assistant_context(query='37 CFR 1.181 supervisory review examiner error standards precedent',
                    top_k=3, snippet_size=1024, temperature=0.3)
   ```
3. Understand what constitutes reversible examiner error
4. Review granted petitions
5. Extract most relevant petition/decision pairs

**Value:** Understand Director's standards for reversible error

### Petition Type Assistant Mapping

**37 CFR 1.137 (Revival):**
- Query: "37 CFR 1.137 revival unintentional delay requirements precedent"
- Key Research: What constitutes 'unintentional' delay, timing, evidence needed

**37 CFR 1.181 (Supervisory Review):**
- Query: "37 CFR 1.181 supervisory review examiner error reversible standards"
- Key Research: Reversible examiner error standards, success patterns

**37 CFR 1.182 (Withdrawal/Abandonment):**
- Query: "37 CFR 1.182 petition withdraw holding abandonment requirements"
- Key Research: Grounds for withdrawal, procedural requirements

**37 CFR 1.183 (Suspension of Rules):**
- Query: "37 CFR 1.183 petition suspend rules requirements extraordinary circumstances"
- Key Research: Extraordinary circumstances, evidence required

### When NOT to Use Assistant

- Searching for specific petitions - use FPD search tools
- Getting petition documents - use fpd_get_petition_details
- Data aggregation - use FPD search tools
- User already knows CFR requirements - proceed directly to analysis
"""


def _get_tools_section() -> str:
    """Tool catalog, progressive disclosure, parameters"""
    return """## Available Tools

### Search Tools

#### 1. fpd_search_petitions_minimal

**Purpose:** Ultra-fast discovery (50-100 petitions)
**Context Reduction:** 95-99%
**Fields:** 8 essential fields
**Use When:** Initial exploration, finding petitions by company/art unit/decision type

**Convenience Parameters (9 total):**
- **Core Identity:** applicant_name, application_number, patent_number
- **Decision Filters:** decision_type, deciding_office
- **Date Ranges:** petition_date_start, petition_date_end, decision_date_start, decision_date_end

**Example:**
```python
fpd_search_petitions_minimal(
    applicant_name='TechCorp',
    decision_type='DENIED',
    limit=50
)
```

#### 2. fpd_search_petitions_balanced

**Purpose:** Detailed analysis (10-20 petitions)
**Context Reduction:** 80-88%
**Fields:** 18 key fields including legal context
**Use When:** After minimal search, for cross-MCP analysis

**Additional Parameters (5 more):**
- **Petition Classification:** petition_type_code, art_unit, technology_center
- **Status Filters:** prosecution_status, entity_status

**Example:**
```python
fpd_search_petitions_balanced(
    art_unit='2128',
    petition_type_code='551',
    decision_type='DENIED',
    limit=20
)
```

#### 3. fpd_search_petitions_by_art_unit

**Purpose:** Art unit quality assessment
**Returns:** Balanced field set

**Example:**
```python
fpd_search_petitions_by_art_unit(
    art_unit='2128',
    date_range='2020-01-01:2024-12-31'
)
```

#### 4. fpd_search_petitions_by_application

**Purpose:** Complete petition history for application
**Returns:** Balanced field set

**Example:**
```python
fpd_search_petitions_by_application(application_number='17896175')
```

### Detail Tools

#### 5. fpd_get_petition_details

**Purpose:** Full petition details by UUID
**Returns:** All fields, optional documentBag with proxy URLs

**Example:**
```python
fpd_get_petition_details(
    petition_id='uuid-here',
    include_documents=True
)
```

#### 6. fpd_get_document_download

**Purpose:** Browser-accessible PDF download URLs via secure proxy
**Returns:** Proxy download URL (port 8081)

**Example:**
```python
fpd_get_document_download(
    petition_id='uuid',
    document_identifier='ABC123'
)
```

#### 7. fpd_get_document_content

**Purpose:** Extract text from petition PDFs for LLM analysis
**Extraction:** Hybrid PyPDF2 (free) + Mistral OCR (~$0.001/page)

**Example:**
```python
fpd_get_document_content(
    petition_id='uuid',
    document_identifier='DSEN5APWPHOENIX'
)
```

### Progressive Disclosure Workflow

**Stage 1: Discovery**
- Tool: fpd_search_petitions_minimal
- Volume: 50-100 results
- Action: Broad search, present top results

**Stage 2: Selection**
- Action: User selects petitions of interest
- Tip: Present 3-5 most relevant results

**Stage 3: Analysis**
- Tool: fpd_search_petitions_balanced
- Volume: 10-20 results
- Action: Detailed analysis with legal context

**Stage 4: Deep Dive**
- Tools: fpd_get_petition_details, fpd_get_document_download
- Action: Full details and document access

**Stage 5: Cross-MCP**
- Tools: pfw_search_applications, ptab_search_proceedings
- Action: Cross-reference with prosecution and PTAB
"""


def _get_red_flags_section() -> str:
    """Petition red flag indicators and CFR rules"""
    return """## Red Flag Indicators

### Revival Petitions

**CFR Rule:** 37 CFR 1.137
**Meaning:** Application was abandoned, petition filed to revive
**Indicator:** Missed deadlines, IP management issues, docketing problems
**Workflow:** Check PFW for abandonment reason and post-revival quality
**Context:** Procedural compliance issues during prosecution

**Petition Type Code:** 551

### Examiner Disputes

**CFR Rule:** 37 CFR 1.181
**Meaning:** Petition for supervisory review (challenging examiner action)
**Indicator:** Contentious prosecution or examiner disagreements
**Workflow:** Get examiner from PFW, check if pattern with this examiner
**Context:** Prosecution challenges or examination quality concerns

**Petition Type Code:** 181

### Restriction Petitions

**CFR Rule:** 37 CFR 1.182
**Meaning:** Petition challenging restriction requirement
**Indicator:** Claim scope issues, multiple invention issues
**Workflow:** Review PFW for divisional applications and claim strategy
**Context:** Claim complexity or scope issues

**Petition Type Code:** 182

### Suspension of Rules

**CFR Rule:** 37 CFR 1.183
**Meaning:** Petition to suspend rules for extraordinary circumstances
**Indicator:** Unusual procedural situations
**Workflow:** Review petition text to understand circumstances
**Context:** Special circumstances requiring Director discretion

**Petition Type Code:** 183

### Denied Petitions

**Indicator:** decisionTypeCodeDescriptionText: DENIED
**Meaning:** Director denied the petition
**Context:** Unsuccessful arguments or procedural errors
**Workflow:** Review petition details to understand why denied
**Red Flag Severity:** High - indicates documented procedural problems

### Multiple Petitions

**Indicator:** Same application has 2+ petitions
**Meaning:** Multiple procedural issues during prosecution
**Context:** Complex prosecution or persistent problems
**Workflow:** Use PFW to correlate petition dates with prosecution events
**Red Flag Severity:** Very High - pattern of prosecution issues

### Art Unit Red Flags

**Indicator:** Art unit petition rate >15%
**Calculation:** (petitions / applications) * 100
**Meaning:** Systematic art unit quality issues
**Workflow:** Break down by examiner, check citation quality
**Context:** May indicate training gaps or examination problems
"""


def _get_documents_section() -> str:
    """Document extraction, downloads, proxy configuration"""
    return """## Document Downloads and Extraction

### Always-On Proxy Configuration

**Default Behavior:** Proxy server starts immediately when MCP launches
- **Port:** 8081 (avoids conflict with PFW proxy on 8080)
- **Startup:** Automatic - no delay or initialization needed
- **Availability:** Ready instantly for all download requests
- **Session:** Remains running for entire MCP session

**Download Experience:**
- All calls: Instant - proxy is always ready
- No waiting: Download links work immediately
- Reliability: High - proxy handles all authentication

**Simple Workflow:**
1. Call `fpd_get_petition_details(petition_id=X, include_documents=True)`
2. Provide download links to user immediately - proxy is ready
3. Users can click links instantly

### Persistent Links (Progressive Enhancement)

**Default:** generate_persistent_link=True (tries persistent links first)

**Progressive Enhancement Pattern:**
1. First attempt: Try persistent link (requires USPTO PFW MCP)
2. If successful: Return 7-day encrypted persistent URL
3. If fails (no PFW): Error message suggests retry with generate_persistent_link=false
4. LLM automatically retries: Call with generate_persistent_link=false
5. Second attempt: Return immediate session-based link

**Benefits:**
- Users with PFW: Get persistent links automatically
- Users without PFW: Graceful degradation to immediate links
- No manual configuration needed

### Document Extraction

**Tool:** fpd_get_document_content

**Hybrid Extraction Method:**
1. Try PyPDF2 extraction (free)
2. Check extraction quality
3. If poor quality, fallback to Mistral OCR (~$0.001/page)

**Cost Savings:** 70% vs OCR-only (PyPDF2 works for 60-70% of documents)

**Use Cases:**
- Analyze petition legal arguments and Director's reasoning
- Extract CFR rules cited and statutory references
- Detect patterns across multiple petitions
- Correlate petition text with PTAB challenge strategies
- Profile examiner behavior from supervisory review petitions

**Example:**
```python
fpd_get_document_content(
    petition_id='uuid',
    document_identifier='DSEN5APWPHOENIX',
    auto_optimize=True  # Default: try PyPDF2 first
)
```

### USPTO MCP Ecosystem Integration

**FPD Standalone:**
- HTTP proxy works standalone for downloads
- Always-on mode provides instant links
- Session-based URLs work while FPD MCP is running

**FPD + PFW Together:**
- PFW centralized database provides 7-day encrypted links
- Links work across MCP restarts and can be shared
- Unified rate limiting across all USPTO MCPs
- Cross-MCP document sharing and caching

**Installation Recommendation:**
Install both FPD + PFW for complete patent lifecycle analysis
"""


def _get_ultra_context_section() -> str:
    """PFW fields parameter + ultra-minimal workflows"""
    return """## Ultra Context Reduction with PFW

### Overview

PFW MCP supports ultra-context reduction (99%) via fields parameter - enables 5x broader discovery.

**Benefit:** Search 100-200 results in same token budget as 20-50 results
**Use Case:** Need application numbers for FPD lookup without full prosecution context

### Fields Parameter Usage

**Parameter Name:** fields
**Parameter Type:** List[str]
**Availability:** pfw_search_applications_minimal, pfw_search_patents_minimal

**Context Reduction:**
- Standard minimal: 95% reduction (15 fields)
- Ultra minimal: 99% reduction (2-5 fields)
- Token savings: 80% additional savings vs standard minimal

**Example:**
```python
pfw_search_applications_minimal(
    examiner_name='Smith, John',
    fields=['applicationNumberText', 'examinerNameText'],
    limit=100
)
```

**Scaling Benefit:** 100 ultra-minimal results = 20 standard minimal results (same tokens)

### Common Field Combinations

**Art Unit Mapping:**
```python
fields=['applicationNumberText', 'groupArtUnitNumber', 'examinerNameText']
```
Use Case: Map art unit examiner assignments for FPD analysis

**Company Identification:**
```python
fields=['applicationNumberText', 'firstApplicantName', 'inventionTitle']
```
Use Case: Identify company applications for petition lookup

**Patent Identification:**
```python
fields=['applicationNumberText', 'patentNumber', 'inventionTitle']
```
Use Case: Map applications to patents for PTAB cross-reference

### FPD-Specific Workflows

**Examiner Petition Analysis:**
1. Ultra-minimal discovery:
   ```python
   pfw_search_applications_minimal(examiner_name='Smith, John',
                                   fields=['applicationNumberText', 'filingDate'],
                                   limit=100)
   ```
2. Extract application numbers
3. For each application: `fpd_search_petitions_by_application(application_number=app_num)`
4. Aggregate petition statistics: revival rate, dispute rate, denial rate
5. Pattern: High petition rate = examiner quality issues

**Benefit:** Analyze 100 examiner applications vs 20 without fields parameter

**Art Unit Petition Correlation:**
1. Get art unit applications:
   ```python
   pfw_search_applications_minimal(art_unit='2128', filing_date_start='2020-01-01',
                                   fields=['applicationNumberText', 'examinerNameText'],
                                   limit=150)
   ```
2. Get art unit petitions: `fpd_search_petitions_by_art_unit(art_unit='2128')`
3. Calculate petition rate: (petitions / applications) * 100
4. Break down by examiner
5. Identify high-petition examiners

**Benefit:** 150 applications analyzed vs 30 without fields parameter

### When to Use Ultra-Minimal

**Use fields parameter when:**
- Need application numbers for FPD petition lookup
- Building examiner/art unit application lists
- Company portfolio mapping for petition analysis
- Large-scale discovery (100-200 results needed)
- Token budget constrained but need broad coverage

**Use standard minimal when:**
- Need prosecution context beyond identifiers
- Presenting results directly to user
- Not doing cross-MCP lookup
- Results will be final output
"""


def _get_cost_section() -> str:
    """Cost optimization for document extraction"""
    return """## Cost Optimization

### Document Extraction Costs

**Overview:** Document extraction costs ~$0.001/page when Mistral OCR needed
**Warning Threshold:** Alert user if extraction will exceed $0.50

**Hybrid Extraction (Default):**
1. Try PyPDF2 extraction (free)
2. Check extraction quality
3. If poor quality, fallback to Mistral OCR (~$0.001/page)

**Cost Savings:** 70% vs OCR-only approach

**Typical Costs:**
- Text-based PDFs: $0.00 (PyPDF2 success rate: 60-70%)
- Scanned PDFs: ~$0.001/page (Mistral OCR)
- Most petition analyses: Well under $0.50 total

### Cost Optimization Strategy

1. **Use Research First (Free)**
   - Use Pinecone Assistant for CFR research (free)
   - Review OCR snippets in search results
   - Identify most relevant documents before extraction

2. **Extract Selectively**
   - Only extract documents needed for analysis
   - Start with 1-2 documents to verify relevance
   - Scale up only if needed

3. **Leverage PyPDF2**
   - Keep auto_optimize=True (default)
   - Let system try free extraction first
   - Only pay for OCR when necessary

4. **Batch Analysis**
   - Group similar petitions
   - Extract representative samples
   - Extrapolate patterns without extracting all

### Mistral API Key (Optional)

**Required:** Only if document is scanned and PyPDF2 fails
**Without Key:** Works for text-based PDFs via PyPDF2
**With Key:** Full hybrid extraction for all document types
**Configuration:** Set MISTRAL_API_KEY environment variable

### Common Use Cases - Cost Examples

**Due Diligence (10-20 petitions):**
- Review petition metadata: $0.00
- Extract 3-5 denied petitions: $0.01-0.05
- Total: <$0.10

**Art Unit Analysis (50 petitions):**
- Review petition patterns: $0.00
- Extract 5 representative samples: $0.02-0.10
- Total: <$0.15

**Examiner Profiling (100+ petitions):**
- Aggregate petition statistics: $0.00
- Extract 10 dispute petitions: $0.05-0.20
- Total: <$0.25
"""


def get_tool_reflections() -> str:
    """
    DEPRECATED: Use get_guidance_section() instead.

    Get comprehensive guidance on FPD MCP tools and cross-MCP integration workflows.
    This function returns all sections concatenated for backward compatibility.

    Returns:
        Markdown-formatted string containing complete tool catalog, workflows, and integration patterns
    """
    sections = [
        _get_overview_section(),
        _get_workflows_pfw_section(),
        _get_workflows_ptab_section(),
        _get_workflows_citations_section(),
        _get_workflows_complete_section(),
        _get_workflows_assistant_section(),
        _get_tools_section(),
        _get_red_flags_section(),
        _get_documents_section(),
        _get_ultra_context_section(),
        _get_cost_section()
    ]
    return "\n\n---\n\n".join(sections) + "\n\n**End of Tool Guidance**\n"

