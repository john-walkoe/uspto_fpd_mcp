"""Company Petition Risk Assessment - Due diligence and risk assessment requiring PFW MCP"""

from . import mcp


@mcp.prompt(
    name="company_petition_risk_assessment_PFW",
    description="Analyze company petition track record for due diligence. At least ONE identifier required (company_name, application_number, or patent_number). include_details: true/false for detailed analysis. Requires PFW MCP."
)
async def company_petition_risk_assessment_prompt(
    company_name: str = "",
    application_number: str = "",
    patent_number: str = "",
    date_range_start: str = "",
    date_range_end: str = "",
    include_details: str = "true"
) -> str:
    """
    Company petition risk assessment for due diligence and portfolio evaluation.

    WARNING: DEPENDENCIES: Requires Patent File Wrapper (PFW) MCP for entity lookup and prosecution context.

    Identifier fields (at least ONE required):
    - company_name: Company/applicant name (e.g., "TechCorp Inc", "Apple Inc")
    - application_number: Application number (e.g., "17896175", "17/896,175") - PFW will identify the assignee/applicant entity
    - patent_number: Patent number (e.g., "11234567", "11,234,567") - PFW will identify the assignee and related applications

    Analysis options:
    - date_range_start: Analysis start date (YYYY-MM-DD format, e.g., "2020-01-01")
    - date_range_end: Analysis end date (YYYY-MM-DD format, e.g., "2024-12-31")
    - include_details: Include detailed petition analysis (true/false) [DEFAULT: true]

    Entity Lookup Behavior:
    - If application_number or patent_number provided: Use PFW MCP to identify the company entity, then analyze that entity's complete petition history
    - If company_name provided: Search FPD directly for that entity's petitions

    Returns comprehensive risk assessment with red flag identification and cross-MCP integration guidance.
    """
    return f"""# Company Petition Risk Assessment - Due Diligence Workflow

**Inputs Provided:**
- Company Name: "{company_name}"
- Application Number: "{application_number}"
- Patent Number: "{patent_number}"
- Date Range: "{date_range_start}" to "{date_range_end}"
- Include Details: {include_details}

**WARNING: DEPENDENCIES**: This workflow requires Patent File Wrapper (PFW) MCP for entity identification and prosecution context analysis.

## ATTORNEY WORKFLOW: Comprehensive due diligence analysis for petition red flags and prosecution quality assessment.

## PHASE 1: Entity Identification & Input Processing

**Entity Lookup Strategy:**
1. **If company_name provided**: Use directly for FPD petition searches
2. **If application_number provided**: Use PFW MCP to identify assignee/applicant entity, then search FPD for that entity's complete petition history
3. **If patent_number provided**: Use PFW MCP to identify assignee and related application numbers, then search FPD for that entity's complete petition history

**Implementation Steps:**
1. Validate inputs and determine primary identifier
2. Execute PFW entity lookup if needed (application_number or patent_number) using fields parameter
3. Use identified company entity for comprehensive FPD petition analysis

**CRITICAL: PFW Usage with Fields Parameter**
When using PFW tools for entity identification, ALWAYS use the fields parameter for targeted data retrieval:

```python
# For application_number lookup:
pfw_search_applications_minimal(
    query=f'applicationNumberText:{application_number}',
    fields=['applicationNumberText', 'applicationMetaData.firstApplicantName'],
    limit=1
)

# For patent_number lookup:
pfw_search_applications_minimal(
    query=f'patentNumber:{patent_number}',
    fields=['applicationNumberText', 'patentNumber', 'applicationMetaData.firstApplicantName'],
    limit=1
)
```

**Benefits:**
- Targeted field retrieval reduces context usage
- Enables broader company searches
- More efficient petition analysis capacity

## PHASE 2: Petition Discovery & Red Flag Analysis

**COMPLETE IMPLEMENTATION WITH ERROR HANDLING:**

```python
# Step 1: Entity identification (if using app_num or patent_num)
company_entity = "{company_name}"  # Default to provided name

if "{application_number}" or "{patent_number}":
    try:
        # Get entity name from PFW
        identifier = "{application_number}" or "{patent_number}"
        field_type = "applicationNumberText" if "{application_number}" else "patentNumber"

        pfw_result = pfw_search_applications_minimal(
            query=f'{{field_type}}:{{identifier}}',
            fields=['applicationNumberText', 'applicationMetaData.firstApplicantName'],
            limit=1
        )

        if pfw_result and len(pfw_result.get('patents', [])) > 0:
            company_entity = pfw_result['patents'][0].get('applicationMetaData', {{}}).get('firstApplicantName', company_entity)
            print(f"**Identified Entity:** {{company_entity}}")
    except Exception as e:
        print(f"**Warning:** PFW lookup failed: {{e}}. Using provided company name: {{company_entity}}")

# Step 2: Search for all company petitions
date_filter = ""
if "{date_range_start}" and "{date_range_end}":
    date_filter = f"petition_date_start='{{date_range_start}}', petition_date_end='{{date_range_end}}'"

petitions = fpd_search_petitions_minimal(
    applicant_name=company_entity,
    limit=100
)
# Note: Add date filters manually if date range provided:
# petition_date_start='{date_range_start}', petition_date_end='{date_range_end}'

total_petitions = len(petitions.get('results', []))
print(f"**Total Petitions Found:** {{total_petitions}}")

# Step 3: RED FLAG ANALYSIS (categorize petitions)
red_flags = {{
    'high_risk': [],
    'medium_risk': [],
    'patterns': {{
        'revival': 0,
        'examiner_disputes': 0,
        'restriction': 0,
        'denied': 0
    }}
}}

for petition in petitions.get('results', []):
    petition_id = petition.get('petitionDecisionRecordIdentifier')
    app_num = petition.get('applicationNumberText', 'N/A')
    decision = petition.get('decisionTypeCodeDescriptionText', '')

    # Get detailed petition info if requested
    if "{include_details}" == "true":
        try:
            details = fpd_get_petition_details(petition_id=petition_id, include_documents=False)
            rules = details.get('ruleBag', [])

            # Check for specific CFR rules
            is_revival = any('1.137' in rule for rule in rules)
            is_examiner_dispute = any('1.181' in rule for rule in rules)
            is_restriction = any('1.182' in rule for rule in rules)

            # HIGH RISK: Denied revival petitions
            if is_revival and decision == 'DENIED':
                red_flags['high_risk'].append({{
                    'type': 'Denied Revival Petition',
                    'app_num': app_num,
                    'petition_id': petition_id,
                    'severity': 'HIGH',
                    'issue': 'Application abandoned + failed recovery attempt'
                }})
                red_flags['patterns']['denied'] += 1

            # MEDIUM RISK: Examiner disputes
            if is_examiner_dispute:
                red_flags['medium_risk'].append({{
                    'type': 'Examiner Dispute (37 CFR 1.181)',
                    'app_num': app_num,
                    'petition_id': petition_id,
                    'severity': 'MEDIUM',
                    'issue': 'Supervisory review required - examiner conflict'
                }})
                red_flags['patterns']['examiner_disputes'] += 1

            # Track patterns
            if is_revival:
                red_flags['patterns']['revival'] += 1
            if is_restriction:
                red_flags['patterns']['restriction'] += 1

        except Exception as e:
            print(f"Warning: Could not get details for {{petition_id}}: {{e}}")
            continue

# Step 4: PRESENTATION - Format results as markdown table
print("\\n## PETITION RISK ASSESSMENT SUMMARY\\n")
print(f"**Company:** {{company_entity}}")
print(f"**Analysis Period:** {date_range_start or 'All time'} to {date_range_end or 'Present'}")
print(f"**Total Petitions:** {{total_petitions}}\\n")

# RED FLAGS TABLE
if red_flags['high_risk'] or red_flags['medium_risk']:
    print("### 🚨 RED FLAGS IDENTIFIED\\n")
    print("| Severity | Type | App Number | Issue |")
    print("|----------|------|------------|-------|")

    for flag in red_flags['high_risk']:
        print(f"| **{{flag['severity']}}** | {{flag['type']}} | {{flag['app_num']}} | {{flag['issue']}} |")

    for flag in red_flags['medium_risk']:
        print(f"| {{flag['severity']}} | {{flag['type']}} | {{flag['app_num']}} | {{flag['issue']}} |")
else:
    print("✅ **No critical red flags identified**\\n")

# PATTERN ANALYSIS
print("\\n### PETITION PATTERNS\\n")
print(f"- **Revival Petitions (37 CFR 1.137):** {{red_flags['patterns']['revival']}} - Abandonment frequency")
print(f"- **Examiner Disputes (37 CFR 1.181):** {{red_flags['patterns']['examiner_disputes']}} - Communication issues")
print(f"- **Restriction Petitions (37 CFR 1.182):** {{red_flags['patterns']['restriction']}} - Claim scope disputes")
print(f"- **Denied Petitions:** {{red_flags['patterns']['denied']}} - Failed petition attempts")

# RISK SCORE CALCULATION
risk_score = (len(red_flags['high_risk']) * 10) + (len(red_flags['medium_risk']) * 5)
risk_level = "LOW" if risk_score < 20 else "MEDIUM" if risk_score < 50 else "HIGH"

print(f"\\n### OVERALL RISK SCORE: {{risk_score}} ({{risk_level}})")
print("\\n**Next Steps:**")
if risk_score > 20:
    print("1. Review high-risk petitions in detail using fpd_get_petition_details")
    print("2. Use PFW to analyze prosecution history for patterns")
    print("3. Check PTAB for any post-grant challenges on granted patents")
else:
    print("1. No immediate concerns - routine petition activity")
    print("2. Continue monitoring for pattern changes")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Always use date filters or applicant_name filters - never retrieve ALL petitions
- If result count > 100, narrow the search with date_range or additional filters
- Use `include_details=false` for initial discovery to prevent context explosion
- Only get petition_details for flagged petitions requiring deep analysis

## CROSS-MCP INTEGRATION

**With PFW MCP:**
```python
# For each high-risk application, get prosecution context
for flag in red_flags['high_risk']:
    try:
        pfw_context = pfw_search_applications_minimal(
            query=f"applicationNumberText:{{flag['app_num']}}",
            fields=['applicationNumberText', 'applicationStatusDescription',
                    'applicationMetaData.examinerNameText', 'groupArtUnitNumber'],
            limit=1
        )
        # Analyze if petition correlates with examiner or art unit patterns
    except:
        pass  # Graceful degradation
```

**With PTAB MCP:**
```python
# Check if any granted patents have PTAB challenges
for petition in petitions.get('results', []):
    patent_num = petition.get('patentNumber')
    if patent_num:
        try:
            ptab_challenges = search_trials_minimal(patent_number=patent_num)
            if ptab_challenges:
                print(f"⚠️ PTAB ALERT: Patent {{patent_num}} has challenges")
        except:
            pass  # PTAB MCP may not be available
```

**EXPECTED OUTPUT FORMAT:** Markdown report with risk score, red flags table, pattern analysis, and actionable next steps."""
