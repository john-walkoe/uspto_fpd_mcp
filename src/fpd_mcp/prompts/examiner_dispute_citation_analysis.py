"""Examiner Dispute Citation Analysis - Analyze citation patterns in dispute petitions"""

from . import mcp


@mcp.prompt(
    name="examiner_dispute_citation_analysis_PFW_FPD_CITATIONS",
    description="Analyze citation patterns in examiner dispute petitions. At least ONE required (examiner_name or art_unit). petition_type: 37 CFR 1.137 (revival)/37 CFR 1.181 (examiner disputes)/37 CFR 1.182 (restriction). include_comparison: true/false for comparing disputed vs non-disputed apps. Requires PFW + FPD + Enhanced Citations MCPs."
)
async def examiner_dispute_citation_analysis_prompt(
    examiner_name: str = "",
    art_unit: str = "",
    petition_type: str = "37 CFR 1.181",
    date_range_start: str = "2015-01-01",
    date_range_end: str = "",
    include_comparison: str = "true"
) -> str:
    """
    Examiner dispute petition analysis enhanced with citation intelligence for prosecution quality assessment.

    Search criteria (at least ONE required):
    - examiner_name: Examiner to analyze (e.g., "Smith, John")
    - art_unit: Art unit number (e.g., "2128")

    Optional parameters:
    - petition_type: Petition type to focus on [DEFAULT: "37 CFR 1.181" - examiner disputes]
    - date_range_start: Analysis start date [DEFAULT: "2015-01-01" - Accounts for 1-2 year prosecution delay before Office Actions. Do not use dates earlier than 2015-01-01 due to Citations API limitations.]
    - date_range_end: Analysis end date (YYYY-MM-DD format)
    - include_comparison: Compare disputed vs non-disputed applications (true/false) [DEFAULT: true]
    
    **IMPORTANT**: Citations API contains Office Action data from October 1, 2017 onwards. Applications filed from 2015-2016 typically have citation data available due to 1-2 year prosecution delays.

    Returns examiner dispute analysis with citation pattern correlation and quality assessment.

    Note: Enhanced Citations API covers Office Actions MAILED from Oct 1, 2017 to 30 days prior. Applications filed
    from 2015-2016 onward typically have citation data available due to 1-2 year prosecution delays.
    """
    return f"""Examiner Dispute Citation Analysis - Prosecution Quality Assessment

Analysis Configuration:
- Examiner Name: {examiner_name}
- Art Unit: {art_unit}
- Petition Type Focus: {petition_type}
- Date Range Start: {date_range_start}
- Include Comparison Analysis: {include_comparison}

WORKFLOW: Correlate examiner dispute petitions with citation patterns to identify prosecution quality issues.

## COMPLETE IMPLEMENTATION WITH ERROR HANDLING

```python
# PHASE 1: Examiner Application Discovery
print(f"## EXAMINER DISPUTE CITATION ANALYSIS")
print(f"**Examiner:** {examiner_name or 'Not specified'}")
print(f"**Art Unit:** {art_unit or 'Not specified'}")
print(f"**Petition Type:** {petition_type}")
print(f"**Date Range:** {date_range_start} to {date_range_end or 'Present'}")
print(f"**Include Comparison:** {include_comparison}\\n")

# Step 1: Get examiner/art unit applications (PFW)
print("**PHASE 1: Collecting Application Data (PFW)...**\\n")

applications = []

try:
    if "{examiner_name}":
        pfw_results = pfw_search_applications_minimal(
            examiner_name="{examiner_name}",
            filing_date_start="{date_range_start}",
            fields=['applicationNumberText', 'applicationMetaData.filingDate',
                    'applicationMetaData.examinerNameText'],
            limit=50
        )
        print(f"**Analyzing Examiner:** {examiner_name}")
    elif "{art_unit}":
        pfw_results = pfw_search_applications_minimal(
            art_unit="{art_unit}",
            filing_date_start="{date_range_start}",
            fields=['applicationNumberText', 'applicationMetaData.filingDate',
                    'applicationMetaData.examinerNameText'],
            limit=50
        )
        print(f"**Analyzing Art Unit:** {art_unit}")

    applications = pfw_results.get('patents', [])
    print(f"✅ **Found {{len(applications)}} applications**\\n")

except Exception as e:
    print(f"❌ **PFW MCP Error:** {{e}}")
    print("**Cannot proceed without PFW data**\\n")
    raise

# PHASE 2: Find Examiner Dispute Petitions (FPD)
print("**PHASE 2: Identifying Examiner Dispute Petitions (FPD)...**\\n")

dispute_analysis = {{
    'disputed_apps': [],
    'non_disputed_apps': [],
    'total_disputes': 0,
    'dispute_rate': 0
}}

for app in applications:
    app_num = app.get('applicationNumberText')

    try:
        petitions = fpd_search_petitions_by_application(
            application_number=app_num,
            include_documents=False
        )

        has_dispute = False
        for petition in petitions.get('results', []):
            petition_id = petition.get('petitionDecisionRecordIdentifier')

            try:
                details = fpd_get_petition_details(petition_id=petition_id, include_documents=False)
                rules = details.get('ruleBag', [])

                # Check if it's an examiner dispute petition (37 CFR 1.181)
                if any('1.181' in rule for rule in rules):
                    has_dispute = True
                    dispute_analysis['total_disputes'] += 1
                    break
            except:
                pass

        if has_dispute:
            dispute_analysis['disputed_apps'].append(app)
        else:
            dispute_analysis['non_disputed_apps'].append(app)

    except:
        # If can't get petitions, assume non-disputed
        dispute_analysis['non_disputed_apps'].append(app)

dispute_analysis['dispute_rate'] = (len(dispute_analysis['disputed_apps']) / len(applications) * 100) if applications else 0

print(f"✅ **Dispute Analysis:**")
print(f"- Applications with Disputes: {{len(dispute_analysis['disputed_apps'])}}")
print(f"- Non-Disputed Applications: {{len(dispute_analysis['non_disputed_apps'])}}")
print(f"- Dispute Rate: {{dispute_analysis['dispute_rate']:.1f}}%\\n")

# PHASE 3: Citation Pattern Analysis (Enhanced Citations MCP)
print("**PHASE 3: Analyzing Citation Patterns...**\\n")

citation_comparison = {{
    'disputed': {{
        'apps_analyzed': 0,
        'total_citations': 0,
        'examiner_citations': 0,
        'avg_citations': 0,
        'examiner_citation_rate': 0
    }},
    'non_disputed': {{
        'apps_analyzed': 0,
        'total_citations': 0,
        'examiner_citations': 0,
        'avg_citations': 0,
        'examiner_citation_rate': 0
    }}
}}

# Analyze citations for disputed applications
for app in dispute_analysis['disputed_apps'][:15]:  # Limit to 15
    app_num = app.get('applicationNumberText')

    try:
        citations = search_citations_minimal(
            application_number=app_num,
            rows=50
        )

        citation_count = len(citations.get('results', []))
        citation_comparison['disputed']['apps_analyzed'] += 1
        citation_comparison['disputed']['total_citations'] += citation_count

        for citation in citations.get('results', []):
            if citation.get('examinerCitedReferenceIndicator') == 'Y':
                citation_comparison['disputed']['examiner_citations'] += 1

    except Exception as e:
        print(f"**Note:** Citations unavailable for {{app_num}}: {{e}}")
        continue

# Analyze citations for non-disputed applications (sample)
if "{include_comparison}" == "true":
    for app in dispute_analysis['non_disputed_apps'][:15]:  # Sample of 15
        app_num = app.get('applicationNumberText')

        try:
            citations = search_citations_minimal(
                application_number=app_num,
                rows=50
            )

            citation_count = len(citations.get('results', []))
            citation_comparison['non_disputed']['apps_analyzed'] += 1
            citation_comparison['non_disputed']['total_citations'] += citation_count

            for citation in citations.get('results', []):
                if citation.get('examinerCitedReferenceIndicator') == 'Y':
                    citation_comparison['non_disputed']['examiner_citations'] += 1

        except:
            continue

# Calculate metrics
for group in ['disputed', 'non_disputed']:
    data = citation_comparison[group]
    if data['apps_analyzed'] > 0:
        data['avg_citations'] = data['total_citations'] / data['apps_analyzed']
        data['examiner_citation_rate'] = (data['examiner_citations'] / data['total_citations'] * 100) if data['total_citations'] > 0 else 0

print(f"✅ **Citation Analysis Complete**\\n")

# PHASE 4: Correlation and Pattern Detection
print("**PHASE 4: Detecting Citation-Dispute Correlations...**\\n")

# Determine if there's a significant correlation
citation_difference = citation_comparison['non_disputed']['examiner_citation_rate'] - citation_comparison['disputed']['examiner_citation_rate']

correlation_detected = False
if abs(citation_difference) > 15:  # >15% difference is significant
    correlation_detected = True

# PHASE 5: PRESENTATION - Analysis Report
print("\\n## EXAMINER DISPUTE CITATION ANALYSIS REPORT\\n")

# Overview
print("### DISPUTE OVERVIEW\\n")
print(f"- **Total Applications Analyzed:** {{len(applications)}}")
print(f"- **Applications with Examiner Disputes:** {{len(dispute_analysis['disputed_apps'])}}")
print(f"- **Dispute Rate:** {{dispute_analysis['dispute_rate']:.1f}}%\\n")

# Citation Comparison Table
if "{include_comparison}" == "true":
    print("### CITATION PATTERN COMPARISON\\n")
    print("| Metric | Disputed Apps | Non-Disputed Apps | Difference |")
    print("|--------|---------------|-------------------|------------|")
    print(f"| Applications Analyzed | {{citation_comparison['disputed']['apps_analyzed']}} | {{citation_comparison['non_disputed']['apps_analyzed']}} | - |")
    print(f"| Avg Citations/App | {{citation_comparison['disputed']['avg_citations']:.1f}} | {{citation_comparison['non_disputed']['avg_citations']:.1f}} | {{citation_comparison['non_disputed']['avg_citations'] - citation_comparison['disputed']['avg_citations']:.1f}} |")
    print(f"| Examiner Citation Rate | {{citation_comparison['disputed']['examiner_citation_rate']:.1f}}% | {{citation_comparison['non_disputed']['examiner_citation_rate']:.1f}}% | {{citation_difference:.1f}}% |")
    print(f"| Total Citations | {{citation_comparison['disputed']['total_citations']}} | {{citation_comparison['non_disputed']['total_citations']}} | - |")

# Correlation Assessment
if correlation_detected:
    print("\\n### 🚨 SIGNIFICANT CORRELATION DETECTED\\n")

    if citation_difference > 0:
        print("**Finding:** Disputed applications have LOWER examiner citation rates than non-disputed applications.\\n")
        print("**Interpretation:**")
        print("- Examiner may not be conducting thorough prior art searches")
        print("- Inadequate citation of relevant prior art may lead to applicant objections")
        print("- Quality of examination process may need improvement\\n")
    else:
        print("**Finding:** Disputed applications have HIGHER examiner citation rates than non-disputed applications.\\n")
        print("**Interpretation:**")
        print("- Complex applications may require more citations and generate disputes")
        print("- Examiner may be citing extensively due to difficult prior art landscape")
        print("- Technology complexity rather than quality issues may drive disputes\\n")
else:
    print("\\n### ✅ NO SIGNIFICANT CORRELATION\\n")
    print("Citation patterns are similar between disputed and non-disputed applications.\\n")

# RECOMMENDED ACTIONS
print("### RECOMMENDED ACTIONS\\n")

if dispute_analysis['dispute_rate'] > 10:
    print("**HIGH DISPUTE RATE CONCERNS:**")
    print("1. 🚨 Review examiner communication and interaction patterns")
    print("2. 🚨 Assess prior art search quality and thoroughness")
    print("3. 🚨 Provide targeted training on dispute-prone technologies")
    print("4. 🚨 Implement quality control reviews for complex cases\\n")
elif dispute_analysis['dispute_rate'] > 5:
    print("**MODERATE DISPUTE RATE:**")
    print("1. ⚠️ Monitor dispute trends for escalation")
    print("2. ⚠️ Review citation practices for improvement opportunities")
    print("3. ⚠️ Enhance applicant communication protocols\\n")
else:
    print("**LOW DISPUTE RATE:**")
    print("1. ✅ Dispute rate within normal range")
    print("2. ✅ Continue current examination practices")
    print("3. ✅ Document successful strategies\\n")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Limit PFW application search to 50 applications
- Limit petition analysis to prevent context explosion
- Citation analysis limited to 15 disputed and 15 non-disputed applications
- Date range must account for 1-2 year prosecution delay (use 2015-01-01 or later)
- Enhanced Citations API covers Office Actions from Oct 1, 2017 onwards
- Three-MCP integration required: PFW (applications), FPD (disputes), Citations (patterns)
- Graceful degradation if any MCP unavailable

## CROSS-MCP INTEGRATION

**With PFW MCP:**
```python
# Get examiner applications with targeted fields
pfw_search_applications_minimal(
    examiner_name="{examiner_name}",
    fields=['applicationNumberText', 'applicationMetaData.filingDate'],
    limit=50
)
```

**With FPD MCP:**
```python
# Find examiner dispute petitions
for app in applications:
    petitions = fpd_search_petitions_by_application(
        application_number=app_num,
        include_documents=False
    )
    # Check for 37 CFR 1.181 petitions
```

**With Enhanced Citations MCP:**
```python
# Analyze citation patterns
try:
    citations = search_citations_minimal(
        application_number=app_num,
        rows=50
    )
    # Compare disputed vs non-disputed citation rates
except:
    pass  # Graceful degradation
```

** TRIPLE-MCP CORRELATION**: Combining PFW prosecution data, FPD examiner disputes, and Enhanced Citations patterns reveals examination quality issues impossible to detect from single data sources.

## PHASE 1: Examiner Dispute Discovery (PFW -> FPD)

CRITICAL: Start with PFW MCP to find examiner applications (FPD does not have examiner search).

1. Discover examiner applications (PFW MCP) using targeted fields:
```python
# CRITICAL: Use fields parameter to search examiner applications efficiently
pfw_search_applications_minimal(
    examiner_name="{examiner_name}",
    fields=[
        'applicationNumberText', 
        'applicationMetaData.filingDate', 
        'applicationMetaData.examinerNameText',
        'applicationStatusCode'
    ],  # Only 4 fields vs 15 standard (73% reduction)
    limit=100  # Can analyze 100 vs ~20 with standard fields
)
```
**Benefits**: 100 applications × 1KB = 100KB vs 100 × 25KB = 2.5MB (96% reduction)
- Extract application numbers for petition lookup

2. Find dispute petitions for these applications (FPD MCP):
   - fpd_search_petitions_minimal for each application
   - Filter for petition type: {petition_type}
   - Identify applications with examiner disputes

## PHASE 2: Citation Pattern Analysis (Enhanced Citations MCP)

Analyze citation patterns for disputed vs non-disputed applications:

1. Get citations for DISPUTED applications:
   - search_citations_minimal(application_number="...", rows=50)
   - Focus on examiner citation indicators

2. Get citations for NON-DISPUTED applications (comparison baseline):
   - Sample 20-30 non-disputed applications from same examiner
   - Same citation search methodology

3. Extract citation metrics for both groups:
   - Citation density (total citations per application)
   - examinerCitedReferenceIndicator ratio
   - citationCategoryCode distribution
   - NPL (non-patent literature) usage
   - passageLocationText thoroughness

## PHASE 3: Correlation Analysis

Compare citation patterns between disputed and non-disputed applications:

1. HIGH-RISK PATTERNS:
   - [OK] DISPUTED apps have LOWER examiner citation rate
   - [OK] DISPUTED apps have HIGHER applicant citation rate
   - [OK] DISPUTED apps have citation density below art unit average
   - Pattern suggests: Inadequate examiner search leading to disputes

2. CITATION QUALITY INDICATORS:
   - examinerCitedReferenceIndicator: true ratio (should be above 60%)
   - NPL citation rate (higher = more thorough search)
   - Citation category diversity (X/Y/NPL balance)

3. PETITION OUTCOME CORRELATION:
   - Cross-reference petition decisions (GRANTED/DENIED) with citation patterns
   - GRANTED petitions + low citation quality = WARNING: examiner performance issue
   - DENIED petitions + normal citations = applicant strategy issue

## PHASE 4: Examiner Performance Assessment

Assess whether citation patterns indicate systemic quality issues:

1. Citation thoroughness scoring:
   - Below average citation density -> [OK] CONCERN
   - Low examiner citation indicator -> [OK] CONCERN
   - Insufficient NPL citations (tech-dependent) -> [PENDING] REVIEW

2. Dispute petition correlation:
   - High dispute rate + low citation quality = WARNING: Examiner training needed
   - High dispute rate + normal citations = INFO: Complex technology or applicant issues

## DELIVERABLES

Comprehensive Analysis Report:
- Examiner dispute petition statistics
- Citation pattern analysis (disputed vs non-disputed)
- Statistical comparison of citation quality metrics
- Correlation assessment: citation quality -> dispute rate
- Root cause analysis: Examiner performance vs technology complexity

Strategic Recommendations:
- Examiner citation quality assessment
- Training recommendations (if quality issues identified)
- Applicant strategy insights (if disputes unwarranted)
- Art unit quality improvement opportunities

Risk Assessment:
- Current pending applications vulnerability
- Petition likelihood for ongoing prosecutions
- Recommended prosecution strategies

CROSS-MCP INTEGRATION:
- PFW MCP: Examiner application discovery (examiner name search)
- FPD MCP: Petition pattern analysis (dispute identification)
- Enhanced Citations MCP: Citation intelligence (quality assessment)
- Three-way correlation for comprehensive prosecution quality analysis

IMPORTANT WORKFLOW NOTES:
1. MUST start with PFW (examiner name not available in FPD or Citations APIs)
2. Citations data covers Office Actions MAILED from Oct 1, 2017 to 30 days prior
3. Applications filed 2015-2016+ typically have citation data due to 1-2 year prosecution delays
4. Use ultra-context reduction (fields parameter) in PFW for 5x broader discovery
5. Minimum 20 applications needed for statistical significance

CITATION METRICS DEFINITIONS:
- examinerCitedReferenceIndicator: true = examiner cited, false = applicant cited
- citationCategoryCode: X=US patent, Y=foreign patent, NPL=non-patent literature
- passageLocationText: Detailed citation passages (presence indicates thoroughness)
- officeActionCategory: CTNF=non-final, CTFR=final rejection, etc."""

