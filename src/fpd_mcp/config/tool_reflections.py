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
        "coverage": _get_coverage_section(),
        "red_flags": _get_red_flags_section(),
        "documents": _get_documents_section(),
        "ultra_context": _get_ultra_context_section(),
        "extraction": _get_extraction_section(),
        "limits": _get_limits_section()
    }

    # Back-compat alias: earlier releases documented this section under a
    # different name; keep old callers working without listing the alias.
    if section == "cost":
        section = "extraction"

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
- 📝 **"Read the office actions behind a petition"** → `workflows_pfw`
- ⚖️ **"Analyze petition + PTAB patterns"** → `workflows_ptab`
- 📊 **"Citation quality + petition correlation"** → `workflows_citations`
- 🏢 **"Complete portfolio due diligence"** → `workflows_complete`
- 📚 **"Research CFR rules with Assistant"** → `workflows_assistant`
- 🎯 **"Ultra-minimal PFW + FPD workflows"** → `ultra_context`
- **"Choose an extraction approach"** → `extraction`
- 📏 **"Why was my response truncated / how do I page it?"** → `limits`
- **"Why did an old petition return zero results?"** → `coverage`

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
- **extraction**: Extraction-tier selection for speed and quality
- **limits**: Active response budgets, the `_bounds`/`_window` markers, paging
- **coverage**: Dataset coverage bounds (2001+ filings; decisions data from 2022, backfilled monthly)

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
- **FPD_Search_petitions_minimal**: Ultra-fast discovery (50-100 petitions, 8 fields, 95-99% reduction)
- **FPD_Search_petitions_balanced**: Detailed analysis (10-20 petitions, 18 fields, 80-88% reduction)
- **FPD_Search_petitions_by_art_unit**: Art unit quality assessment
- **FPD_Search_petitions_by_application**: Complete petition history for application

### Detail Tools
- **FPD_Get_petition_details**: Full petition details with optional documents
- **FPD_get_document_download**: Browser-accessible PDF downloads via proxy
- **FPD_get_document_content_with_ocr**: Text extraction from petition PDFs (hybrid pypdf + Mistral OCR)

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
   PFW_search_applications_minimal(applicant_name='Target Co', limit=100)
   ```
2. **FPD:** Check petition history for procedural issues
   ```python
   FPD_Search_petitions_by_application(application_number='17414168')
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
   FPD_Search_petitions_balanced(query='ruleBag:"37 CFR 1.137"', limit=50)
   ```
2. **PFW:** Get full prosecution history to understand abandonment reason
   ```python
   PFW_search_applications_minimal(query='applicationNumberText:17414168')
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
   FPD_Search_petitions_by_art_unit(art_unit='2128', date_range='2020-01-01:2024-12-31')
   ```
2. Categorize: Examiner disputes, restriction appeals, rule waivers
3. **PFW:** Cross-reference to get examiner names
   ```python
   PFW_search_applications_minimal(art_unit='2128', fields=['applicationNumberText', 'examinerNameText'], limit=100)
   ```
4. Analyze: Petition frequency and types by examiner

**Value:** Understand procedural patterns in prosecution

### Reading Office Actions from FPD Workflows (the primary path)

Whenever a petition finding needs prosecution substance - what the examiner
actually rejected, and why - use PFW's office-action tools directly. Do **not**
route through the document bag and OCR.

```python
# 1. Structured triage: which office actions carry which rejections
PFW_get_oa_rejections(application_number='17/414,168')

# 2. The examiner's actual words, one call, no document bag / PDF / scanning step
PFW_get_oa_text(application_number='17/414,168', latest_only=True)
PFW_get_oa_text(application_number='17/414,168', action_type='CTFR')  # final rejection
```

**Coverage floors differ per tool - do not lump them together.**
- `PFW_get_oa_rejections`: Oct 1, 2017 to roughly 30 days ago. Rows are per
  rejection group, not per office action.
- `PFW_get_oa_text`: office actions mailed roughly 2008 onward (measured, not a
  USPTO guarantee) - about a decade deeper than the rejections floor. **An empty
  `PFW_get_oa_rejections` result says nothing about text availability.**
- `section='101'|'102'|'103'|'112'` narrows to one rejection, but USPTO populates
  those sub-documents sparsely and the tool silently falls back to the FULL body
  when the requested section is empty - check `section_returned` /
  `text_length_chars` before reporting a section quote.
- No coverage is not an error: `success=True`, `num_found=0`, empty text. Branch
  on `num_found`.

**Fallback only** - `PFW_get_application_documents(document_code='CTNF'|'CTFR')`
then `PFW_get_document_content_with_ocr` - for office actions older than roughly
2008, for non-office-action documents (892/1449, IDS, amendments, claims,
drawings, interview summaries), when an actual PDF or shareable link is wanted, or
when `PFW_get_oa_text` returned `num_found=0`. Note the document bag can itself
return HTTP 403 on some older applications, so an old case may be readable through
`PFW_get_oa_text` even when the bag is not.

### Learning PFW Workflows

**Context-Efficient Guidance Tool:** `PFW_get_guidance`

When working with cross-MCP workflows, use PFW's selective guidance tool:

**Relevant Sections for FPD Users:**
- `workflows_fpd`: FPD+PFW integration workflows, petition red flag analysis
- `workflows_complete`: Complete company due diligence across PFW, FPD, PTAB
- `tools`: PFW convenience parameter searches
- `fields`: Ultra-minimal field selection for 99% context reduction

**Quick Reference:**
```python
# Learn FPD+PFW workflows
PFW_get_guidance('workflows_fpd')

# Learn complete due diligence workflows
PFW_get_guidance('workflows_complete')
```

### PFW XML Data Retrieval - Token Optimization

**IMPORTANT:** If you need detailed patent/application XML data from PFW (beyond search metadata), use the `PFW_get_patent_or_application_xml` tool with `include_raw_xml=False` for massive token savings.

**Token Reduction:**
- With `include_raw_xml=True` (default): ~55KB per application (~50K chars raw XML)
- With `include_raw_xml=False`: ~5KB per application (91% reduction)
- With `include_raw_xml=False` + `include_fields`: ~500 chars (99% reduction)

**Best Practice:**
```python
# RECOMMENDED: Exclude raw XML (91% token reduction)
PFW_get_patent_or_application_xml(
    application_number='17/414,168',
    include_raw_xml=False  # ← CRITICAL for cross-MCP workflows
)

# EVEN BETTER: Selective fields (99% reduction)
PFW_get_patent_or_application_xml(
    application_number='17/414,168',
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
- **Search tools only** (`PFW_search_applications_minimal`): Entity lookup, portfolio discovery (current FPD workflows)
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
   PFW_search_applications_minimal(applicant_name='Target', status='Patented', limit=100)
   ```
2. **FPD:** Check petition history during prosecution
   ```python
   FPD_Search_petitions_by_application(application_number='17414168')
   ```
3. **PTAB:** Check for post-grant challenges
   ```python
   PTAB_search_trials_minimal(patent_number='12252554')
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

### PTAB Search Tool Parameters

**All PTAB search tools support:**
- `patent_number`: Patent number (e.g., '10701173')
- `petitioner_name`: Party filing the challenge
- `patent_owner_name`: Patent owner name
- `trial_type`: 'IPR', 'PGR', 'CBM'
- `trial_status`: Status category
- `tech_center`: Technology center (e.g., '2600')
- `filing_date_from/to`: Date range filters
- `fields`: Ultra-minimal field selection (99% context reduction)
- `limit`: Max results (default 50, max 100)

**Example - Ultra-minimal PTAB query:**
```python
# Only 2 fields - 99% context reduction
PTAB_search_trials_minimal(
    patent_number='10701173',
    fields=['trialNumber', 'trialMetaData.trialStatusCategory'],
    limit=20
)
```
"""


def _get_workflows_citations_section() -> str:
    """FPD + Citations integration workflows"""
    return """## FPD + Citations Integration Workflows

### Overview

The Citations MCP serves TWO independent lanes over USPTO office-action citations:

- **Enriched Citations (v3)** - `Citations_search_citations_minimal` / `_balanced`,
  `Citations_get_citation_details`, `Citations_get_citation_statistics`,
  `Citations_get_available_fields`. AI-extracted passage locations, claim mapping,
  quality score, NPL flag, `officeActionDate`.
- **OA Citations (v2)** - `Citations_search_oa_citations_minimal` / `_balanced`,
  `Citations_get_oa_citation_fields`. Raw citation lists transcribed from Form
  PTO-892 (examiner) and PTO-1449 (applicant IDS), plus statutory basis
  (`legalSectionCode`) and rejection posture (`actionTypeCategory`).

**Routing rule: TRY BOTH.** Neither lane is a superset of the other. OA is usually
broader in bulk, but on a given application the enriched lane can return more. For
any completeness-sensitive question (citation density, "was reference X cited",
examiner search thoroughness) query both and union the results, reporting which
lane contributed what. Take a single-lane shortcut only for a lane-exclusive
capability:

| Need | Lane |
|---|---|
| Passage locations, claim mapping, quality score, NPL flag | Enriched only |
| Date-windowed query (`officeActionDate`) | Enriched only |
| Cited-patent reverse lookup by `patent_number` parameter | Enriched only |
| Statutory-basis filter (`legalSectionCode` 102/103/112) | OA only |
| Everything else, especially "is this complete?" | Both |

**HTTP 400 traps - field vocabulary does not transfer between the lanes:**
`officeActionDate` and `publicationNumber` are INVALID on the OA lane (resolve a
patent to its application via PFW, then search by application; to find where a
patent was cited use `parsedReferenceIdentifier`). `legalSectionCode`,
`examinerNameText`, `citedDocumentTitle` and `citingPassageText` are INVALID on the
enriched lane. There is NO free-text or title search on either lane. Neither lane
carries examiner names - that join goes through PFW.

**Data Coverage:** USPTO documents the same window for both lanes - Office Actions
MAILED from October 1, 2017 to roughly 30 days prior. Cite that as the official
answer, but note that both lanes have in practice been observed serving records
older than that (enriched `officeActionDate` values reaching back to roughly 2008,
verified against PFW's authoritative prosecution record; the OA lane demonstrably
carries pre-2017 Form 892 material too). Never report an empty result on an older
application as proof that no art was cited without having queried both lanes.
**Context Reduction:** 90-95% through progressive disclosure

### Workflow 1: Art Unit Petition Quality with Citation Intelligence

**Scenario:** Art unit 2128 has high petition rate - assess if citation quality is a factor

**Steps:**
1. **PFW Discovery:** Get art unit applications
   ```python
   PFW_search_applications_minimal(art_unit='2128', filing_date_start='2015-01-01',
                                   fields=['applicationNumberText', 'examinerNameText'], limit=100)
   ```
2. **FPD Petition Patterns:** Get art unit petitions
   ```python
   FPD_Search_petitions_by_art_unit(art_unit='2128')
   ```
3. Calculate baseline petition rate
4. **Citation Analysis:** For 20-30 applications - run BOTH lanes and union
   ```python
   enriched = Citations_search_citations_minimal(
       criteria=f'patentApplicationNumber:{app_num}', rows=50)
   oa = Citations_search_oa_citations_minimal(
       application_number=app_num, rows=50)
   # No date clause on either call: the OA lane would 400 on officeActionDate,
   # and a 2017 floor on the enriched lane would drop material it actually holds.
   # Union on the normalized reference id (enriched: citedDocumentIdentifier /
   # publicationNumber; OA: parsedReferenceIdentifier) and report both totals.
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
   PFW_search_applications_minimal(examiner_name='Smith, John', filing_date_start='2015-01-01',
                                   fields=['applicationNumberText'], limit=100)
   ```
2. **FPD Dispute Identification:** Check each application for petitions
3. Categorize: DISPUTED (has 1.181 petition) vs NON-DISPUTED
4. **Citation Analysis:** Compare citation metrics between groups. Run both lanes
   per application (`Citations_search_citations_minimal` +
   `Citations_search_oa_citations_minimal`) and compare the union - a single-lane
   count understates density and can bias one group against the other.
   `examinerCitedReferenceIndicator` lives on both lanes.
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
- Any application worth checking - do not screen applications out by filing date.
  The documented floor is a documented floor, not an observed one; query both
  lanes and let the result decide.

**Skip citations when:**
- Only need petition red flags without citation context
- Time/token budget limited

**Never conclude from a single lane.** An empty enriched result is not evidence of
a thin search until the OA lane has been queried too, and vice versa.
"""


def _get_workflows_complete_section() -> str:
    """Complete four-MCP lifecycle workflows"""
    return """## Complete Four-MCP Lifecycle Analysis

### Complete M&A Due Diligence

**Scenario:** Comprehensive patent intelligence across all USPTO databases

**Four-MCP Integration Workflow:**

1. **Portfolio Discovery (PFW)**
   ```python
   PFW_search_applications_minimal(applicant_name='Target Company',
                                   filing_date_start='2015-01-01', limit=100)
   ```

2. **Citation Intelligence (Citations)** - run BOTH lanes, union the results
   ```python
   enriched = Citations_search_citations_minimal(
       criteria=f'patentApplicationNumber:{app_num}', rows=50)
   oa = Citations_search_oa_citations_minimal(
       application_number=app_num, rows=50)
   ```
   Neither lane is a superset of the other; analyze examiner citation patterns
   over the union and say which lane contributed what

3. **FPD Risk Assessment (FPD)**
   ```python
   FPD_Search_petitions_by_application(application_number=app_num)
   ```
   Check procedural irregularities and petition history

4. **PTAB Challenge Analysis (PTAB)** - For granted patents
   ```python
   PTAB_search_trials_minimal(patent_number=patent_num)
   ```
   Assess post-grant challenge exposure

5. **Prosecution Intelligence (PFW)**
   `PFW_get_oa_rejections(application_number=app_num)` to score the rejection mix
   across the portfolio, then `PFW_get_oa_text(application_number=app_num)` on the
   applications that matter - one call each, no document bag, no PDF, no scanning step in between.
   Drop to `PFW_get_application_documents` + `PFW_get_document_content_with_ocr`
   only for non-OA documents, for office actions older than roughly 2008, when an
   actual PDF is wanted, or when `PFW_get_oa_text` returns `num_found=0`.

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
- Examiner assignments and office actions - read them with `PFW_get_oa_rejections`
  (structured triage, Oct 1 2017 to ~30 days ago) and `PFW_get_oa_text` (the
  examiner's words, office actions mailed roughly 2008 onward), not the document
  bag; an empty rejections result does NOT mean the text is unavailable
- Amendments and responses

**Stage 2: Procedural Issues (FPD)**
- Revival petitions (missed deadlines)
- Examiner disputes (supervisory review)
- Restriction challenges

**Stage 3: Citation Intelligence (Citations)** - both lanes, unioned
- Examiner search quality assessment
- Prior art thoroughness
- Citation category analysis
- Documented window is Oct 1 2017 to ~30 days ago on both lanes, but both have
  been observed serving older records - query, do not assume

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
   FPD_Search_petitions_balanced(query='ruleBag:"37 CFR 1.137"', limit=20)
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
   FPD_get_document_content_with_ocr(petition_id, doc_id)
   ```

**Value:** Draft petition aligned with current Director standards

#### Scenario 2: Examiner Dispute Analysis

**Problem:** Supervisory review petition (37 CFR 1.181) - understanding standards

**Workflow:**
1. Find similar disputes
   ```python
   FPD_Search_petitions_balanced(query='ruleBag:"37 CFR 1.181"', art_unit='2128', limit=20)
   ```
   181 is the CFR rule number, not a petition type code — sending it as
   `petition_type_code` returns nothing. The supervisory-review type codes are
   504 (re patent examining) and 515 (re non-patent examining), but type codes
   are incomplete for a CFR class, so the dependable filter is a ruleBag
   clause through the raw `query` parameter.
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
- Getting petition documents - use FPD_Get_petition_details
- Data aggregation - use FPD search tools
- User already knows CFR requirements - proceed directly to analysis
"""


def _get_tools_section() -> str:
    """Tool catalog, progressive disclosure, parameters"""
    return """## Available Tools

### Search Tools

#### 1. FPD_Search_petitions_minimal

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
FPD_Search_petitions_minimal(
    applicant_name='TechCorp',
    decision_type='DENIED',
    limit=50
)
```

#### 2. FPD_Search_petitions_balanced

**Purpose:** Detailed analysis (10-20 petitions)
**Context Reduction:** 80-88%
**Fields:** 18 key fields including legal context
**Use When:** After minimal search, for cross-MCP analysis

**Additional Parameters (5 more):**
- **Petition Classification:** petition_type_code, art_unit, technology_center
- **Status Filters:** prosecution_status, entity_status

**Example:**
```python
FPD_Search_petitions_balanced(
    art_unit='2128',
    petition_type_code='502',  # revival; 551 is PTA correction
    decision_type='DENIED',
    limit=20
)
```

#### 3. FPD_Search_petitions_by_art_unit

**Purpose:** Art unit quality assessment
**Returns:** Balanced field set

**Example:**
```python
FPD_Search_petitions_by_art_unit(
    art_unit='2128',
    date_range='2020-01-01:2024-12-31'
)
```

#### 4. FPD_Search_petitions_by_application

**Purpose:** Complete petition history for application
**Returns:** Balanced field set

**Example:**
```python
FPD_Search_petitions_by_application(application_number='17414168')
```

### Detail Tools

#### 5. FPD_Get_petition_details

**Purpose:** Full petition details by UUID
**Returns:** All fields, optional documentBag with proxy URLs

**Example:**
```python
FPD_Get_petition_details(
    petition_id='uuid-here',
    include_documents=True
)
```

#### 6. FPD_get_document_download

**Purpose:** Browser-accessible PDF download URLs via secure proxy
**Returns:** Proxy download URL (port 8081)

**Example:**
```python
FPD_get_document_download(
    petition_id='uuid',
    document_identifier='ABC123'
)
```

#### 7. FPD_get_document_content_with_ocr

**Purpose:** Extract text from petition PDFs for LLM analysis
**Extraction:** Hybrid pypdf (fast, text-based PDFs) + OCR (scanned documents)

**Example:**
```python
FPD_get_document_content_with_ocr(
    petition_id='uuid',
    document_identifier='DSEN5APWPHOENIX'
)
```

### Progressive Disclosure Workflow

**Stage 1: Discovery**
- Tool: FPD_Search_petitions_minimal
- Volume: 50-100 results
- Action: Broad search, present top results

**Stage 2: Selection**
- Action: User selects petitions of interest
- Tip: Present 3-5 most relevant results

**Stage 3: Analysis**
- Tool: FPD_Search_petitions_balanced
- Volume: 10-20 results
- Action: Detailed analysis with legal context

**Stage 4: Deep Dive**
- Tools: FPD_Get_petition_details, FPD_get_document_download
- Action: Full details and document access

**Stage 5: Cross-MCP**
- Tools: PFW_search_applications, PTAB_search_trials
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

**Petition Type Codes:** 501 (unavoidable delay), 502 (unintentional delay, OPAP/TC).
NOT 551 — that is CORRECTION OF PATENT TERM ADJUSTMENT, an unrelated and much
larger class. Type codes are incomplete for this class; filter on
ruleBag:"37 CFR 1.137" to catch every revival.

### Examiner Disputes

**CFR Rule:** 37 CFR 1.181
**Meaning:** Petition for supervisory review (challenging examiner action)
**Indicator:** Contentious prosecution or examiner disagreements
**Workflow:** Get examiner from PFW, check if pattern with this examiner
**Context:** Prosecution challenges or examination quality concerns

**Petition Type Codes:** 504 (re patent examining), 515 (re non-patent examining).
181 is the CFR rule number, not a type code — querying it returns nothing.

### Restriction Petitions

**CFR Rule:** 37 CFR 1.182
**Meaning:** Petition challenging restriction requirement
**Indicator:** Claim scope issues, multiple invention issues
**Workflow:** Review PFW for divisional applications and claim strategy
**Context:** Claim complexity or scope issues

**Petition Type Codes:** restriction petitions under 37 CFR 1.144 arrive under 504;
519/520 carry the other 37 CFR 1.182 matters. 182 is the CFR rule number, not a
type code — querying it returns nothing.

### Suspension of Rules

**CFR Rule:** 37 CFR 1.183
**Meaning:** Petition to suspend rules for extraordinary circumstances
**Indicator:** Unusual procedural situations
**Workflow:** Review petition text to understand circumstances
**Context:** Special circumstances requiring Director discretion

**Petition Type Code:** 503. 183 is the CFR rule number, not a type code —
querying it returns nothing.

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
1. Call `FPD_Get_petition_details(petition_id=X, include_documents=True)`
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

**Tool:** FPD_get_document_content_with_ocr

**Hybrid Extraction Method:**
1. Try pypdf extraction (fast, direct text)
2. Check extraction quality
3. If poor quality, fall back to OCR (slower; handles scanned documents)

**Note:** pypdf succeeds for most text-based petition PDFs, so OCR runs only when actually needed.

**Use Cases:**
- Analyze petition legal arguments and Director's reasoning
- Extract CFR rules cited and statutory references
- Detect patterns across multiple petitions
- Correlate petition text with PTAB challenge strategies
- Profile examiner behavior from supervisory review petitions

**Example:**
```python
FPD_get_document_content_with_ocr(
    petition_id='uuid',
    document_identifier='DSEN5APWPHOENIX',
    auto_optimize=True  # Default: try pypdf first
)
```

**Reading a long document (cursor):**
```python
first = FPD_get_document_content_with_ocr(
    petition_id='uuid', document_identifier='DSEN5APWPHOENIX')
# first['_window'] -> {'unit': 'page', 'offset': 0, 'returned': 120000,
#                      'total': 310000, 'has_more': True,
#                      'next_offset': 120000, 'note': '...'}
rest = FPD_get_document_content_with_ocr(
    petition_id='uuid', document_identifier='DSEN5APWPHOENIX',
    char_offset=120000)
```
Nothing is discarded - long text is PAGED. See `FPD_get_guidance('limits')`
for the full `_bounds` / `_window` contract.

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

**Benefit:** Search up to 100 results in same token budget as 20-50 results
**Use Case:** Need application numbers for FPD lookup without full prosecution context

### Fields Parameter Usage

**Parameter Name:** fields
**Parameter Type:** List[str]
**Availability:** PFW_search_applications_minimal, PFW_search_patents_minimal

**Context Reduction:**
- Standard minimal: 95% reduction (15 fields)
- Ultra minimal: 99% reduction (2-5 fields)
- Token savings: 80% additional savings vs standard minimal

**Example:**
```python
PFW_search_applications_minimal(
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
   PFW_search_applications_minimal(examiner_name='Smith, John',
                                   fields=['applicationNumberText', 'filingDate'],
                                   limit=100)
   ```
2. Extract application numbers
3. For each application: `FPD_Search_petitions_by_application(application_number=app_num)`
4. Aggregate petition statistics: revival rate, dispute rate, denial rate
5. Pattern: High petition rate = examiner quality issues

**Benefit:** Analyze 100 examiner applications vs 20 without fields parameter

**Art Unit Petition Correlation:**
1. Get art unit applications:
   ```python
   PFW_search_applications_minimal(art_unit='2128', filing_date_start='2020-01-01',
                                   fields=['applicationNumberText', 'examinerNameText'],
                                   limit=150)
   ```
2. Get art unit petitions: `FPD_Search_petitions_by_art_unit(art_unit='2128')`
3. Calculate petition rate: (petitions / applications) * 100
4. Break down by examiner
5. Identify high-petition examiners

**Benefit:** 150 applications analyzed vs 30 without fields parameter

### When to Use Ultra-Minimal

**Use fields parameter when:**
- Need application numbers for FPD petition lookup
- Building examiner/art unit application lists
- Company portfolio mapping for petition analysis
- Large-scale discovery (up to 100 results per page; page with offset=)
- Token budget constrained but need broad coverage

**Use standard minimal when:**
- Need prosecution context beyond identifiers
- Presenting results directly to user
- Not doing cross-MCP lookup
- Results will be final output
"""


def _get_extraction_section() -> str:
    """Extraction-tier selection for speed and quality"""
    return """## Extraction Strategy

### Document Extraction Tiers

**Hybrid Extraction (Default):**
1. Try pypdf extraction (fast, direct text)
2. Check extraction quality
3. If poor quality, fall back to OCR (slower; handles scanned documents)

**Speed and Quality:**
- Text-based PDFs: instant pypdf extraction (succeeds for most petition documents)
- Scanned PDFs: OCR (slower per page, high-fidelity verbatim output)
- Keep auto_optimize=True so the fastest usable method is chosen automatically

### Efficient Extraction Strategy

1. **Research First**
   - Use Pinecone Assistant for CFR research
   - Review snippets in search results
   - Identify most relevant documents before extraction

2. **Extract Selectively**
   - Only extract documents needed for analysis
   - Start with 1-2 documents to verify relevance
   - Scale up only if needed (extraction output is large - it consumes context quickly)

3. **Leverage pypdf**
   - Keep auto_optimize=True (default)
   - Let the system try direct text extraction first
   - OCR runs only when the document is actually scanned

4. **Batch Analysis**
   - Group similar petitions
   - Extract representative samples
   - Extrapolate patterns without extracting all

### Mistral API Key (Optional)

**Required:** Only if document is scanned and pypdf fails
**Without Key:** Works for text-based PDFs via pypdf (Docling fallback if configured)
**With Key:** Full hybrid extraction for all document types
**Configuration:** Set MISTRAL_API_KEY environment variable

### Common Use Cases - Extraction Scope

**Due Diligence (10-20 petitions):**
- Review petition metadata first
- Extract 3-5 denied petitions for detailed reading

**Art Unit Analysis (50 petitions):**
- Review petition patterns from search metadata
- Extract 5 representative samples

**Examiner Profiling (100+ petitions):**
- Aggregate petition statistics from search results
- Extract 10 dispute petitions for argument analysis
"""


def _get_limits_section() -> str:
    """Active response budgets + the _bounds/_window marker contract.

    This is the server's configuration/status surface for response sizing:
    the numbers are read LIVE from the process environment via
    shared/response_bounds.py, so what the section prints is what the guard
    is actually enforcing right now.
    """
    from ..services.document_extraction import mistral_ocr_max_pages
    from ..shared.response_bounds import bounds_config

    config = bounds_config()
    return f"""## Response Size Limits and Markers

### Active configuration (live, this process)

| Setting | Value | Environment variable |
| --- | --- | --- |
| Guard enabled | {config["enabled"]} | `{config["env"]["enabled"]}` |
| Structured response budget | {config["max_response_chars"]:,} chars | `{config["env"]["max_response_chars"]}` |
| Document content budget | {config["max_content_chars"]:,} chars | `{config["env"]["max_content_chars"]}` |
| OCR page cap per document | {mistral_ocr_max_pages()} pages | `MISTRAL_OCR_MAX_PAGES` |

Budgets are CHARACTER counts of the serialized response, not token
estimates: an oversized tool result is replaced by a client-side truncation
error that this server never sees, so the model would get no data and no way
to recover. The guard trades records or fields for a usable response plus a
recovery note.

### `_bounds` - the response was reduced to fit

Present ONLY when the guard actually changed the response. Its absence means
nothing was dropped.

```json
"_bounds": {{
  "applied": true,
  "reason": "size",
  "size_chars": 39812,
  "size_limit": {config["max_response_chars"]},
  "stages": ["slimmed", "truncated"],
  "slimmed_fields": ["downloadOptionBag"],
  "items_returned": 20,
  "items_total": 137,
  "note": "<the exact tool + parameters that retrieve the rest>"
}}
```

- `stages`: `slimmed` = heavy per-record fields were dropped;
  `truncated` = whole records were dropped.
- `items_returned` / `items_total`: records (or, for a page-capped OCR,
  pages). `items_total` is `null` only when the true total is unknown.
- Always read `note` - it names the call that recovers what was dropped.
- Legacy aliases kept for this release: `documents_returned`,
  `documents_total`, `documents_note`, `truncated`, `truncation_note`.

### `_window` - long text was paged, not dropped

Present on `FPD_get_document_content_with_ocr` when the extracted
text is longer than one window.

```json
"_window": {{
  "unit": "page",
  "offset": 0,
  "returned": 120000,
  "total": 310000,
  "has_more": true,
  "next_offset": 120000,
  "note": "<how to fetch the next window>"
}}
```

All four counters are CHARACTER offsets in both units, so `next_offset`
feeds straight back into `char_offset`. `unit` reports only whether the
window edges snapped to `=== PAGE N ===` markers (`page`) or are raw
character slices (`char`).

**New parameters:** `char_offset` (default 0) and `max_chars` (default
{config["max_content_chars"]:,}).

### Paging searches

Every search tool returns a `paging` block reporting the limit that was
ACTUALLY applied (`limit_applied`) next to what was requested, plus
`returned` / `total` / `has_more` / `next_offset`. Tool ceilings: minimal,
by_art_unit and by_application accept 1-200; balanced accepts 1-50 (its
records carry ~18 fields each).
"""



def _get_coverage_section() -> str:
    """Dataset coverage bounds: filing-date floor and decisions-data start"""
    return """## Dataset Coverage

USPTO documents two separate bounds for the Final Petition Decisions dataset
(source: https://data.uspto.gov/apis/petition-decision/search, retrieved
2026-09-02). They are different axes; keep them apart.

### 1. Filing-date floor (the applications and patents)

The search covers "final agency petition decisions in publicly available
patent applications and patents that were filed in 2001 or later."
Petitions in applications filed before 2001 are out of scope entirely.

### 2. Decisions-data start (the decisions themselves)

"Petition decisions data are incrementally added to ODP on a monthly basis
starting with data from 2022 and later." The release notes at
https://data.uspto.gov/support/release list what is currently available.

### What a zero result means

- A zero result for a petition decided BEFORE 2022 is expected and says
  nothing about whether a petition existed or was decided. Do not report
  "no petitions" for pre-2022 activity; report that the decision predates
  the dataset. (Real case: a 2007 petition in application 11/752,072
  returns zero here even though it exists in the file wrapper.)
- A zero result only starts to mean "no decision" for petitions decided in
  2022 or later, and even then it is subject to the monthly incremental
  backfill; check the release notes URL above for the current extent.
- For older petition activity, fall back to the application file wrapper:
  the petition papers and decisions appear in the PFW MCP document list
  (PFW_get_application_documents) regardless of this dataset's bounds.
- Check what you passed. `application_number` is the APPLICATION serial, not
  a patent number, and since patent numbers passed 10,000,000 in mid-2018 an
  8-digit value is valid in both namespaces. This server does not resolve
  between them, so an 8-digit patent number returns an empty result that
  reads as "no petitions" and is wrong rather than empty. Crosswalk first
  with PFW_search_applications_minimal(query='patentNumber:<n>').
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
        _get_extraction_section(),
        _get_coverage_section()
    ]
    return "\n\n---\n\n".join(sections) + "\n\n**End of Tool Guidance**\n"
