"""Petition Quality with Citation Intelligence - Enhanced with citation data from Enhanced Citations MCP"""

from ._flags import flag


async def petition_quality_with_citation_intelligence_prompt(
    art_unit: str = "",
    date_range_start: str = "2015-01-01",
    date_range_end: str = "",
    include_citation_analysis: str = "true",
    analysis_depth: str = "comprehensive"
) -> str:
    """
    Enhanced art unit quality assessment correlating petition patterns with citation intelligence.

    Required input:
    - art_unit: Art unit number to analyze (e.g., "2128", "1650")

    Optional parameters:
    - date_range_start: Analysis start date (YYYY-MM-DD format) [DEFAULT: "2015-01-01" - Accounts for 1-2 year prosecution delay before Office Actions. Do not use dates earlier than 2015-01-01 due to Citations API limitations.]
    - date_range_end: Analysis end date (YYYY-MM-DD format)
    - include_citation_analysis: Include Enhanced Citations analysis (true/false) [DEFAULT: true]
    - analysis_depth: Analysis thoroughness (basic, standard, comprehensive) [DEFAULT: comprehensive]

    **IMPORTANT**: Both citation lanes are documented as covering Office Actions mailed October 1, 2017 to ~30 days prior; both have in practice been observed serving older records. Run BOTH citation lanes (Citations_search_citations_* enriched AND Citations_search_oa_citations_* raw 892/1449) and union the results - neither is a superset of the other.

    Returns art unit quality assessment with petition-citation correlation analysis and examiner citation quality metrics.

    Note: both citation lanes are documented as covering Office Actions MAILED from Oct 1, 2017 to ~30 days prior.
    Applications filed from 2015-2016 onward sit comfortably inside that window; older ones are still worth querying.
    """
    # R-2: accept any encoding a caller sends (True, 'True', 'yes',
    # '1'); the emitted template compares the normalized literal.
    include_citation_analysis = flag(include_citation_analysis)

    return f"""Art Unit Quality Assessment with Citation Intelligence

Analysis Configuration:
- Art Unit: {art_unit}
- Date Range Start: {date_range_start}
- Include Citation Analysis: {include_citation_analysis}
- Analysis Depth: {analysis_depth}

WORKFLOW: Three-MCP integration (PFW -> FPD -> Citations) for comprehensive art unit prosecution quality assessment.

## COMPLETE IMPLEMENTATION WITH ERROR HANDLING

```python
# PHASE 1: Data Collection - Petition Patterns
print(f"## ART UNIT QUALITY ASSESSMENT WITH CITATION INTELLIGENCE")
print(f"**Art Unit:** {art_unit}")
print(f"**Date Range:** {date_range_start} to {date_range_end or 'Present'}")
print(f"**Citation Analysis:** {include_citation_analysis}")
print(f"**Analysis Depth:** {analysis_depth}\\n")

# Step 1: Get petitions for art unit (FPD)
print("**PHASE 1: Analyzing Petition Patterns (FPD)...**\\n")

petition_data = {{
    'total_petitions': 0,
    'examiner_disputes': 0,
    'revivals': 0,
    'denied_rate': 0
}}

try:
    petitions = FPD_Search_petitions_by_art_unit(
        art_unit="{art_unit}",
        date_range="{date_range_start}:{date_range_end or '2025-12-31'}",
        limit=100
    )

    petition_data['total_petitions'] = len(petitions.get('results', []))

    for petition in petitions.get('results', []):
        petition_id = petition.get('petitionDecisionRecordIdentifier')
        decision = petition.get('decisionTypeCodeDescriptionText', '')

        try:
            details = FPD_Get_petition_details(petition_id=petition_id, include_documents=False)
            rules = details.get('ruleBag', [])

            if any('1.181' in rule for rule in rules):
                petition_data['examiner_disputes'] += 1
            if any('1.137' in rule for rule in rules):
                petition_data['revivals'] += 1

            if decision == 'DENIED':
                petition_data['denied_rate'] += 1
        except:
            pass

    print(f"✅ **Petition Analysis:**")
    print(f"- Total Petitions: {{petition_data['total_petitions']}}")
    print(f"- Examiner Disputes: {{petition_data['examiner_disputes']}}")
    print(f"- Revival Petitions: {{petition_data['revivals']}}\\n")

except Exception as e:
    print(f"⚠️ FPD Error: {{e}}\\n")

# PHASE 2: Get applications for art unit (PFW)
print("**PHASE 2: Collecting Application Data (PFW)...**\\n")

applications = []

try:
    pfw_results = PFW_search_applications_minimal(
        art_unit="{art_unit}",
        filing_date_start="{date_range_start}",
        fields=['applicationNumberText', 'applicationMetaData.examinerNameText',
                'applicationMetaData.filingDate'],
        limit=50
    )

    applications = pfw_results.get('patents', [])
    print(f"✅ **Found {{len(applications)}} applications**\\n")

except Exception as e:
    print(f"❌ **PFW MCP Error:** {{e}}")
    print("**Cannot perform citation analysis without PFW data**\\n")

# PHASE 3: Citation Intelligence Analysis (Enhanced Citations MCP)
if "{include_citation_analysis}" == "true" and applications:
    print("**PHASE 3: Analyzing Citation Patterns (Enhanced Citations)...**\\n")

    citation_analysis = {{
        'apps_analyzed': 0,
        'total_citations': 0,
        'examiner_citations': 0,
        'applicant_citations': 0,
        'avg_citations_per_app': 0,
        'examiner_citation_rate': 0
    }}

    # Analyze citations for sample of applications
    for app in applications[:20]:  # Limit to 20 for context management
        app_num = app.get('applicationNumberText')

        try:
            citations = Citations_search_citations_minimal(
                application_number=app_num,
                rows=50
            )

            citation_count = len(citations.get('results', []))
            citation_analysis['apps_analyzed'] += 1
            citation_analysis['total_citations'] += citation_count

            for citation in citations.get('results', []):
                if citation.get('examinerCitedReferenceIndicator') == 'Y':
                    citation_analysis['examiner_citations'] += 1
                else:
                    citation_analysis['applicant_citations'] += 1

        except Exception as e:
            print(f"**Note:** Citations MCP unavailable for {{app_num}}: {{e}}")
            continue

    if citation_analysis['apps_analyzed'] > 0:
        citation_analysis['avg_citations_per_app'] = citation_analysis['total_citations'] / citation_analysis['apps_analyzed']
        citation_analysis['examiner_citation_rate'] = (citation_analysis['examiner_citations'] / citation_analysis['total_citations'] * 100) if citation_analysis['total_citations'] > 0 else 0

    print(f"✅ **Citation Analysis:**")
    print(f"- Applications Analyzed: {{citation_analysis['apps_analyzed']}}")
    print(f"- Total Citations: {{citation_analysis['total_citations']}}")
    print(f"- Avg Citations per App: {{citation_analysis['avg_citations_per_app']:.1f}}")
    print(f"- Examiner Citation Rate: {{citation_analysis['examiner_citation_rate']:.1f}}%\\n")

# PHASE 4: Correlation and Quality Assessment
print("**PHASE 4: Quality Correlation Analysis...**\\n")

# Calculate petition rate
petition_rate = (petition_data['total_petitions'] / len(applications) * 100) if applications else 0
examiner_dispute_rate = (petition_data['examiner_disputes'] / petition_data['total_petitions'] * 100) if petition_data['total_petitions'] > 0 else 0

# Quality scoring
quality_score = 100
quality_score -= petition_rate * 1.5  # Petition frequency penalty
quality_score -= (100 - citation_analysis.get('examiner_citation_rate', 70)) * 0.3  # Citation quality penalty

# Correlation detection
correlation_warning = False
if petition_rate > 10 and citation_analysis.get('examiner_citation_rate', 70) < 50:
    correlation_warning = True
    quality_score -= 15  # Correlation penalty

if quality_score >= 80:
    quality_rating = "HIGH QUALITY ✅"
elif quality_score >= 60:
    quality_rating = "MODERATE QUALITY ⚠️"
else:
    quality_rating = "QUALITY CONCERNS 🚨"

# PHASE 5: PRESENTATION - Quality Report
print("\\n## ART UNIT QUALITY REPORT\\n")

# Overview
print(f"### QUALITY RATING: {{quality_rating}} (Score: {{quality_score:.1f}}/100)\\n")

# Metrics Table
print("### KEY METRICS\\n")
print("| Metric | Value | Benchmark | Status |")
print("|--------|-------|-----------|--------|")
print(f"| Petition Rate | {{petition_rate:.1f}}% | <5% | {{'✅ Good' if petition_rate < 5 else '⚠️ High' if petition_rate < 10 else '🚨 Very High'}} |")
print(f"| Examiner Disputes | {{examiner_dispute_rate:.1f}}% | <20% | {{'✅ Good' if examiner_dispute_rate < 20 else '⚠️ Elevated' if examiner_dispute_rate < 40 else '🚨 High'}} |")
print(f"| Avg Citations/App | {{citation_analysis.get('avg_citations_per_app', 0):.1f}} | 15-25 | {{'✅ Good' if 15 <= citation_analysis.get('avg_citations_per_app', 0) <= 25 else '⚠️ Review'}} |")
print(f"| Examiner Citation Rate | {{citation_analysis.get('examiner_citation_rate', 0):.1f}}% | >60% | {{'✅ Good' if citation_analysis.get('examiner_citation_rate', 0) > 60 else '⚠️ Low' if citation_analysis.get('examiner_citation_rate', 0) > 40 else '🚨 Very Low'}} |")

# Correlation Warning
if correlation_warning:
    print("\\n### 🚨 QUALITY CORRELATION WARNING\\n")
    print("**High petition rate combined with low examiner citation rate suggests:**")
    print("- Inadequate prior art searches leading to prosecution issues")
    print("- Quality control gaps in examination process")
    print("- Training needs for examiner citation practices\\n")

# Recommendations
print("### RECOMMENDED ACTIONS\\n")

if quality_score < 60:
    print("**IMMEDIATE PRIORITY:**")
    print("1. 🚨 Review examiner training on prior art search protocols")
    print("2. 🚨 Investigate petition patterns for systemic issues")
    print("3. 🚨 Implement enhanced citation quality controls")
    print("4. 🚨 Conduct case-by-case review of examiner disputes\\n")
elif quality_score < 80:
    print("**MODERATE PRIORITY:**")
    print("1. ⚠️ Monitor trends for quality degradation")
    print("2. ⚠️ Enhance examiner search training")
    print("3. ⚠️ Review high-petition applications\\n")
else:
    print("**MAINTENANCE MODE:**")
    print("1. ✅ Continue current quality practices")
    print("2. ✅ Document best practices")
    print("3. ✅ Monitor for emerging patterns\\n")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Limit petition search to 100 results maximum
- Limit PFW application search to 50 results
- Citation analysis limited to 20 applications to prevent context explosion
- Date range must account for 1-2 year prosecution delay (use 2015-01-01 or later)
- Both citation lanes are documented as covering Office Actions from Oct 1, 2017 to ~30 days prior (older records observed in practice); query both and union
- Three-MCP integration requires PFW, FPD, and Enhanced Citations MCPs
- Graceful degradation if any MCP unavailable

## PHASE 1: Petition Pattern Discovery (FPD MCP)

Use FPD tools to identify petition patterns:

1. Search art unit petitions:
   - FPD_Search_petitions_minimal for initial discovery
   - Focus on petition types: 37 CFR 1.181 (examiner disputes), 37 CFR 1.137 (revivals)

2. Identify red flags:
   - High petition rate per application
   - Denied petition patterns
   - Examiner dispute frequency

## PHASE 2: Prosecution Context Enrichment (PFW MCP)

CRITICAL WORKFLOW: Enhanced Citations API does NOT have examiner name field - must use PFW first.

CITATION DATA AVAILABILITY: both lanes are documented as covering Office Actions MAILED from Oct 1, 2017 to ~30 days
prior; both have been observed serving older records. Run BOTH citation lanes (Citations_search_citations_* enriched AND Citations_search_oa_citations_* raw 892/1449) and union the results - neither is a superset of the other.

1. Get art unit applications from PFW:
   - PFW_search_applications_minimal(art_unit="{art_unit}", filing_date_start="{date_range_start}", limit=100)
   - Use fields parameter for targeted data retrieval:
     fields=['applicationNumberText', 'applicationMetaData.examinerNameText', 'applicationMetaData.filingDate']

2. Extract application numbers for citation lookup

## PHASE 3: Citation Intelligence Analysis (Enhanced Citations MCP)

Use Enhanced Citations MCP to assess citation quality:

1. Search citations for art unit applications:
   - Citations_search_citations_minimal(application_number="...", rows=50)
   - Aggregate across 20-50 applications for pattern analysis

2. Analyze citation metrics:
   - Citation density (citations per application)
   - examinerCitedReferenceIndicator ratio (examiner vs applicant citations)
   - citationCategoryCode distribution (X=US patent, Y=foreign, NPL=non-patent literature)
   - officeActionCategory patterns (CTNF, CTFR, etc.)

3. Citation quality indicators:
   - Low examiner citation rate -> potential inadequate search
   - High NPL citation rate -> complex technology
   - passageLocationText presence -> thorough citation analysis

## PHASE 4: Correlation Analysis

Correlate petition patterns with citation quality:

1. LOW CITATION QUALITY + HIGH PETITION RATE = WARNING: Art unit quality issues
   - Examiner citation rate below 50%
   - Multiple petitions per application
   - Pattern suggests inadequate prosecution

2. EXAMINER DISPUTE PETITIONS + CITATION PATTERNS
   - Check if disputed applications have abnormal citation patterns
   - Compare citation density vs art unit average

3. REVIVAL PETITIONS + CITATION ANALYSIS
   - Abandoned applications citation history
   - Correlation with citation thoroughness

## DELIVERABLES

Comprehensive Report:
- Art unit petition statistics and trends
- Citation quality metrics aggregated across applications
- Correlation analysis: petition rate vs citation quality
- Examiner-specific citation patterns (if multiple examiners)
- Red flag inventory with severity assessment

Strategic Recommendations:
- Art unit prosecution quality assessment
- Citation quality improvement opportunities
- Examiner training recommendations (if patterns identified)
- Risk assessment for pending applications in this art unit

CROSS-MCP INTEGRATION NOTES:
- PFW provides application discovery and examiner mapping
- FPD provides petition red flag analysis
- Enhanced Citations provides AI-extracted citation intelligence
- Correlation analysis requires all three MCPs for complete assessment

CITATION API LIMITATIONS:
- Documented window on BOTH lanes: Office Actions MAILED from Oct 1, 2017 to ~30 days prior (not filing date);
  older records observed in practice, so do not screen an application out on date alone
- Neither lane is a superset of the other - query both and union; officeActionDate/publicationNumber 400 on the
  OA lane, legalSectionCode/examinerNameText 400 on the enriched lane
- Examiner name NOT in Citations API - requires PFW workflow
- Decision codes NOT available - use prosecution outcome from PFW"""


def register(mcp):
    """Register this prompt with the given MCP server instance."""
    mcp.prompt(
        name="petition_quality_with_citation_intelligence_PFW_FPD_CITATIONS",
        description="Art unit petition quality assessment enhanced with citation intelligence. art_unit* (required). include_citation_analysis: true/false for citation analysis. analysis_depth: basic/standard/comprehensive for thoroughness. Requires PFW + FPD + Enhanced Citations MCPs."
    )(petition_quality_with_citation_intelligence_prompt)
