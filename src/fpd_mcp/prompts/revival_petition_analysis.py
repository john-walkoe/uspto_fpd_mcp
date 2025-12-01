"""Revival Petition Analysis - Find abandonment patterns and revival success rates"""

from . import mcp


@mcp.prompt(
    name="revival_petition_analysis",
    description="Find abandonment patterns and revival success rates. At least ONE required (company_name or art_unit). include_reasoning: true/false for Director's reasoning. outcome_focus: all/granted/denied/dismissed."
)
async def revival_petition_analysis_prompt(
    company_name: str = "",
    art_unit: str = "",
    date_range_start: str = "",
    date_range_end: str = "",
    outcome_focus: str = "all",
    include_reasoning: str = "true"
) -> str:
    """
    Revival petition analysis for abandonment pattern identification and risk assessment.
    
    Search criteria (at least ONE required):
    - company_name: Company/applicant name (e.g., "TechCorp Inc") 
    - art_unit: Art unit number (e.g., "2128")
    
    Analysis options:
    - date_range_start: Analysis start date (YYYY-MM-DD, defaults to 5 years ago)
    - outcome_focus: Focus analysis (all, granted, denied, dismissed) [DEFAULT: all]
    - include_reasoning: Include Director's reasoning analysis (true/false) [DEFAULT: true]
    
    Returns comprehensive revival petition analysis with abandonment risk indicators and procedural insights.
    """
    return f"""Revival Petition Analysis - Abandonment Risk Assessment

Inputs Provided:
- Company Name: "{company_name}"
- Art Unit: "{art_unit}"
- Date Range Start: "{date_range_start}"
- Outcome Focus: {outcome_focus}
- Include Reasoning: {include_reasoning}

 ATTORNEY WORKFLOW: Systematic analysis of 37 CFR 1.137 revival petitions to identify abandonment patterns, success factors, and prosecution quality indicators.

## COMPLETE IMPLEMENTATION WITH ERROR HANDLING

```python
# PHASE 1: Data Collection - Search for Revival Petitions
from datetime import datetime, timedelta

# Set default date range if not provided
date_start = "{date_range_start}" or (datetime.now() - timedelta(days=1825)).strftime('%Y-%m-%d')  # 5 years
date_end = "{date_range_end}" or datetime.now().strftime('%Y-%m-%d')

print(f"**Analyzing Revival Petitions (37 CFR 1.137)**")
print(f"**Company:** {company_name or 'All Companies'}")
print(f"**Art Unit:** {art_unit or 'All Art Units'}")
print(f"**Date Range:** {{date_start}} to {{date_end}}\\n")

# Build search query
search_filters = {{}}
if "{company_name}":
    search_filters['applicant_name'] = "{company_name}"
if "{art_unit}":
    search_filters['art_unit'] = "{art_unit}"

# Search for revival petitions (37 CFR 1.137)
revival_petitions = fpd_search_petitions_minimal(
    petition_date_start=date_start,
    petition_date_end=date_end,
    **search_filters,
    limit=100
)

# PHASE 2: Filter and Categorize Revival Petitions
revival_results = {{
    'total': 0,
    'granted': 0,
    'denied': 0,
    'dismissed': 0,
    'pending': 0,
    'by_outcome': {{}},
    'detailed_petitions': []
}}

for petition in revival_petitions.get('results', []):
    petition_id = petition.get('petitionDecisionRecordIdentifier')
    decision = petition.get('decisionTypeCodeDescriptionText', 'UNKNOWN')
    app_num = petition.get('applicationNumberText', 'N/A')
    decision_date = petition.get('decisionDate', 'N/A')

    # Get detailed petition info to verify it's a revival petition
    try:
        details = fpd_get_petition_details(petition_id=petition_id, include_documents=False)
        rules = details.get('ruleBag', [])

        # Check if it's actually a 37 CFR 1.137 revival petition
        is_revival = any('1.137' in rule for rule in rules)

        if not is_revival:
            continue  # Skip non-revival petitions

        revival_results['total'] += 1

        # Categorize by outcome
        if decision == 'GRANTED':
            revival_results['granted'] += 1
        elif decision == 'DENIED':
            revival_results['denied'] += 1
        elif decision == 'DISMISSED':
            revival_results['dismissed'] += 1
        else:
            revival_results['pending'] += 1

        # Store detailed petition data
        revival_results['detailed_petitions'].append({{
            'petition_id': petition_id,
            'app_num': app_num,
            'decision': decision,
            'decision_date': decision_date,
            'rules': rules
        }})

        # Filter by outcome_focus if specified
        if "{outcome_focus}" != "all":
            if decision.lower() != "{outcome_focus}".lower():
                continue

    except Exception as e:
        print(f"Warning: Could not process petition {{petition_id}}: {{e}}")
        continue

# PHASE 3: Calculate Risk Metrics
revival_success_rate = (revival_results['granted'] / revival_results['total'] * 100) if revival_results['total'] > 0 else 0
revival_denial_rate = (revival_results['denied'] / revival_results['total'] * 100) if revival_results['total'] > 0 else 0

# PHASE 4: Cross-MCP Integration - Get Total Applications for Context
total_applications = 0
if "{company_name}":
    try:
        # Get company's total application count from PFW
        pfw_apps = pfw_search_applications_minimal(
            applicant_name="{company_name}",
            filing_date_start=date_start,
            fields=['applicationNumberText'],
            limit=200
        )
        total_applications = len(pfw_apps.get('patents', []))
    except Exception as e:
        print(f"**Note:** PFW MCP unavailable for application count: {{e}}")
        total_applications = revival_results['total'] * 20  # Estimate

abandonment_frequency = (revival_results['total'] / total_applications * 100) if total_applications > 0 else 0

# PHASE 5: Risk Assessment
if abandonment_frequency < 2 and revival_success_rate > 80:
    risk_level = "LOW RISK ✅"
    risk_score = 90
elif abandonment_frequency < 5 and revival_success_rate > 60:
    risk_level = "MODERATE RISK ⚠️"
    risk_score = 60
else:
    risk_level = "HIGH RISK 🚨"
    risk_score = 30

# PHASE 6: PRESENTATION - Format Results
print("\\n## REVIVAL PETITION ANALYSIS SUMMARY\\n")
print(f"**Risk Assessment:** {{risk_level}} (Score: {{risk_score}}/100)")
print(f"**Total Revival Petitions:** {{revival_results['total']}}")
print(f"**Total Applications (Estimated):** {{total_applications}}\\n")

# KEY METRICS TABLE
print("### KEY METRICS\\n")
print(f"- **Revival Success Rate:** {{revival_success_rate:.1f}}%")
print(f"  - Target: >70% (good), 50-70% (moderate), <50% (concerning)")
print(f"- **Revival Denial Rate:** {{revival_denial_rate:.1f}}%")
print(f"- **Abandonment Frequency:** {{abandonment_frequency:.1f}}%")
print(f"  - Target: <2% (excellent), 2-5% (acceptable), >5% (high risk)\\n")

# OUTCOME BREAKDOWN TABLE
print("### REVIVAL PETITION OUTCOMES\\n")
print("| Outcome | Count | Percentage |")
print("|---------|-------|------------|")
print(f"| **Granted** | {{revival_results['granted']}} | {{(revival_results['granted']/revival_results['total']*100) if revival_results['total'] > 0 else 0:.1f}}% |")
print(f"| **Denied** | {{revival_results['denied']}} | {{(revival_results['denied']/revival_results['total']*100) if revival_results['total'] > 0 else 0:.1f}}% |")
print(f"| **Dismissed** | {{revival_results['dismissed']}} | {{(revival_results['dismissed']/revival_results['total']*100) if revival_results['total'] > 0 else 0:.1f}}% |")
print(f"| **Pending** | {{revival_results['pending']}} | {{(revival_results['pending']/revival_results['total']*100) if revival_results['total'] > 0 else 0:.1f}}% |")

# RISK INDICATORS
print("\\n### ABANDONMENT RISK INDICATORS\\n")

if abandonment_frequency > 5:
    print("🚨 **HIGH ABANDONMENT FREQUENCY** - Systemic docketing or prosecution management issues")
if revival_success_rate < 60:
    print("🚨 **LOW REVIVAL SUCCESS RATE** - Poor petition quality or procedural compliance issues")
if revival_results['denied'] > 5:
    print("🚨 **MULTIPLE DENIED REVIVALS** - Pattern suggests inadequate justification or systemic problems")

if risk_score >= 80:
    print("✅ **EXCELLENT PROSECUTION MANAGEMENT** - Minimal abandonment risk")
elif risk_score >= 60:
    print("⚠️ **ACCEPTABLE PERFORMANCE** - Some improvement opportunities exist")
else:
    print("🚨 **SIGNIFICANT CONCERNS** - Immediate process review and improvement required")

# PHASE 7: SUCCESS FACTOR ANALYSIS (if include_reasoning=true)
if "{include_reasoning}" == "true" and revival_results['granted'] > 0:
    print("\\n### SUCCESS FACTOR ANALYSIS\\n")

    success_factors = {{
        'extraordinary_circumstances': 0,
        'uspto_error': 0,
        'unavoidable_delay': 0,
        'other': 0
    }}

    # Analyze first 10 granted petitions for reasoning patterns
    granted_petitions = [p for p in revival_results['detailed_petitions'] if p['decision'] == 'GRANTED'][:10]

    for granted_petition in granted_petitions:
        try:
            details = fpd_get_petition_details(
                petition_id=granted_petition['petition_id'],
                include_documents=True  # Get decision documents
            )
            # Analyze decision reasoning (would require document text extraction)
            print(f"- Application {{granted_petition['app_num']}}: Granted on {{granted_petition['decision_date']}}")
        except:
            pass

    print(f"\\n**Analyzed {{len(granted_petitions)}} granted petitions for success patterns**")

# RECOMMENDED ACTIONS
print("\\n### RECOMMENDED ACTIONS\\n")

if risk_score < 60:
    print("**IMMEDIATE ACTIONS:**")
    print("1. Review docketing system and deadline tracking procedures")
    print("2. Analyze denied petitions to identify root causes")
    print("3. Implement additional deadline alerts and safeguards")
    print("4. Provide training on revival petition requirements\\n")
else:
    print("**MAINTENANCE ACTIONS:**")
    print("1. Continue monitoring abandonment trends")
    print("2. Document successful revival petition strategies")
    print("3. Maintain current deadline management practices")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Limit revival petition searches to 100 results maximum to prevent context explosion
- Always use date_range filters for temporal analysis (default: 5 years)
- If total_petitions > 100, narrow date range or use additional filters (company_name, art_unit)
- Use include_documents=False for initial petition discovery
- Only retrieve full documents for detailed success factor analysis (limit to 10-20 petitions)
- Outcome filtering (outcome_focus parameter) helps reduce result set for focused analysis

## SEARCH STRATEGY

### Step 1: Build Targeted Search Query
Base query: `ruleBag:"37 CFR 1.137"` (revival petitions)

Search refinement based on inputs:
- If company_name provided: Add `AND firstApplicantName:"{company_name}"`
- If art_unit provided: Add `AND groupArtUnitNumber:{art_unit}`
- Date filtering: Add `AND decisionDate:[{date_range_start or "2019-01-01"} TO 2024-12-31]`

### Step 2: Execute Revival Petition Search
Use `fpd_search_petitions_balanced` with the refined query for detailed analysis (limit: 50)

## ABANDONMENT RISK ANALYSIS

### Critical Metrics to Calculate:

** Revival Success Rate**
= (Granted Revival Petitions / Total Revival Petitions) × 100
- Target: >70% (good), 50-70% (moderate), <50% (concerning)

** Abandonment Frequency** 
= (Revival Petitions / Total Applications) × 100
- Lower percentages indicate better prosecution management

** Recovery Timeline**
= Average time from abandonment to revival petition
- Shorter timelines suggest proactive management

### Abandonment Root Cause Analysis:
- Missed deadlines: Docketing or calendar issues
- Fee payment failures: Administrative oversights
- Response preparation delays: Resource or complexity issues
- Strategic abandonments: Intentional portfolio management

## SUCCESS FACTOR ANALYSIS (if include_reasoning=true)

For granted revival petitions, use `fpd_get_petition_details` to analyze:
- Director's reasoning patterns
- Successful argument types
- Common justifications

Typical Success Factors:
- Extraordinary circumstances: Unforeseeable events
- USPTO error: Office mistakes or system failures
- Unavoidable delays: Despite diligent efforts
- Reasonable reliance: Good faith USPTO interactions

## RISK ASSESSMENT FRAMEWORK

**[OK] LOW ABANDONMENT RISK:**
- <2% revival petition rate
- >80% revival success rate
- Consistent prosecution management
- Proactive deadline management

**[PENDING] MODERATE ABANDONMENT RISK:**
- 2-5% revival petition rate
- 60-80% revival success rate
- Occasional procedural issues
- Room for process improvement

** HIGH ABANDONMENT RISK:**
- >5% revival petition rate
- <60% revival success rate
- Systemic procedural failures
- Poor prosecution management

## CROSS-MCP INTEGRATION

** With Patent File Wrapper MCP:**
For complete abandonment analysis, cross-reference prosecution history:
```
pfw_search_applications_balanced(
    query="firstApplicantName:{company_name or '*'}",
    limit=100
)
```

This reveals:
- Prosecution complexity factors leading to abandonment
- Examiner interaction patterns
- Office action response challenges
- Grant rate correlation with revival petition frequency

** With PTAB MCP:**
Check if revived patents faced post-grant challenges:
- Difficult prosecution -> potential weak patents
- Revival circumstances -> prosecution strategy issues

## EXPECTED DELIVERABLES

Abandonment Risk Report:
- Revival petition success rate analysis
- Abandonment frequency trends and patterns
- Root cause identification and categorization
- Comparative benchmarking (if art unit analysis)

Process Improvement Recommendations:
- Deadline management system enhancements
- Prosecution workflow optimization
- Training and resource allocation suggestions
- Technology solution recommendations

Strategic Portfolio Insights:
- Applications at high abandonment risk
- Process failure pattern identification
- Cross-MCP integration opportunities"""


