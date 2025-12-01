"""Complete Portfolio Due Diligence - Lifecycle risk assessment requiring PFW + PTAB MCPs"""

from . import mcp


@mcp.prompt(
    name="complete_portfolio_due_diligence_pfw_ptab",
    description="Complete patent lifecycle risk assessment. company_name* (required). portfolio_size_limit: max applications to analyze (default 50). risk_scoring: true/false for risk scores. Requires PFW + PTAB MCPs."
)
async def complete_portfolio_due_diligence_prompt(
    company_name: str,
    portfolio_size_limit: str = "50", 
    risk_scoring: str = "true"
) -> str:
    """
    Complete portfolio due diligence with patent lifecycle risk assessment.
    
    WARNING: DEPENDENCIES: Requires Patent File Wrapper (PFW) MCP and PTAB MCP
    
    Required input:
    - company_name: Company/applicant name for portfolio analysis (e.g., "TechCorp Inc")
    
    Analysis options:
    - portfolio_size_limit: Maximum applications to analyze (default: 50)
    - risk_scoring: Calculate comprehensive risk scores (true/false) [DEFAULT: true]
    
    Returns complete patent lifecycle analysis: Filing -> Prosecution -> Petitions -> Grant -> PTAB with integrated risk assessment.
    """
    return f"""Complete Portfolio Due Diligence - Three-MCP Lifecycle Analysis

Inputs Provided:
- Company Name: "{company_name}"
- Portfolio Size Limit: {portfolio_size_limit}
- Risk Scoring: {risk_scoring}

WARNING: DEPENDENCIES: This workflow requires Patent File Wrapper (PFW) MCP and PTAB MCP for complete patent lifecycle analysis.

 ATTORNEY WORKFLOW: Comprehensive due diligence combining prosecution history, petition red flags, and post-grant challenges for complete portfolio risk assessment.

## COMPLETE IMPLEMENTATION WITH ERROR HANDLING

```python
# PHASE 1: Portfolio Discovery (PFW MCP)
print(f"## COMPLETE PORTFOLIO DUE DILIGENCE")
print(f"**Company:** {company_name}")
print(f"**Portfolio Size Limit:** {portfolio_size_limit}")
print(f"**Risk Scoring:** {risk_scoring}\\n")

portfolio_data = {{
    'applications': [],
    'granted_patents': [],
    'pending_apps': [],
    'abandoned_apps': []
}}

try:
    print("**PHASE 1: Discovering Portfolio via PFW MCP...**\\n")

    # Get company applications with targeted fields
    pfw_results = pfw_search_applications_minimal(
        applicant_name="{company_name}",
        fields=['applicationNumberText', 'patentNumber', 'inventionTitle',
                'applicationStatusDescription', 'applicationMetaData.firstApplicantName',
                'applicationMetaData.groupArtUnitNumber', 'applicationMetaData.filingDate'],
        limit=int({portfolio_size_limit})
    )

    portfolio_data['applications'] = pfw_results.get('patents', [])
    total_apps = len(portfolio_data['applications'])

    print(f"✅ **Found {{total_apps}} applications/patents**\\n")

    # Categorize by status
    for app in portfolio_data['applications']:
        status = app.get('applicationStatusDescription', '').lower()
        patent_num = app.get('patentNumber')

        if patent_num:
            portfolio_data['granted_patents'].append(app)
        elif 'abandoned' in status:
            portfolio_data['abandoned_apps'].append(app)
        else:
            portfolio_data['pending_apps'].append(app)

    print(f"**Portfolio Breakdown:**")
    print(f"- Granted Patents: {{len(portfolio_data['granted_patents'])}}")
    print(f"- Pending Applications: {{len(portfolio_data['pending_apps'])}}")
    print(f"- Abandoned Applications: {{len(portfolio_data['abandoned_apps'])}}\\n")

except Exception as e:
    print(f"❌ **PFW MCP Error:** {{e}}")
    print("**Cannot proceed without PFW MCP - this workflow requires prosecution data**\\n")
    # Exit workflow
    raise

# PHASE 2: Petition Risk Assessment (FPD MCP)
print("**PHASE 2: Analyzing Petition History...**\\n")

petition_analysis = {{
    'total_petitions': 0,
    'apps_with_petitions': 0,
    'red_flag_apps': [],
    'petition_types': {{
        'revival': 0,
        'examiner_dispute': 0,
        'restriction': 0,
        'other': 0
    }},
    'decisions': {{
        'granted': 0,
        'denied': 0,
        'dismissed': 0
    }}
}}

# Analyze petitions for each application (limit to prevent context explosion)
for app in portfolio_data['applications'][:50]:
    app_num = app.get('applicationNumberText')

    try:
        petitions = fpd_search_petitions_by_application(
            application_number=app_num,
            include_documents=False
        )

        petition_count = len(petitions.get('results', []))
        if petition_count > 0:
            petition_analysis['apps_with_petitions'] += 1
            petition_analysis['total_petitions'] += petition_count

            # Analyze petition details
            for petition in petitions.get('results', []):
                petition_id = petition.get('petitionDecisionRecordIdentifier')
                decision = petition.get('decisionTypeCodeDescriptionText', '')

                # Track decisions
                if decision == 'GRANTED':
                    petition_analysis['decisions']['granted'] += 1
                elif decision == 'DENIED':
                    petition_analysis['decisions']['denied'] += 1
                elif decision == 'DISMISSED':
                    petition_analysis['decisions']['dismissed'] += 1

                # Get petition type from details
                try:
                    details = fpd_get_petition_details(petition_id=petition_id, include_documents=False)
                    rules = details.get('ruleBag', [])

                    # Categorize by type
                    if any('1.137' in rule for rule in rules):
                        petition_analysis['petition_types']['revival'] += 1
                    elif any('1.181' in rule for rule in rules):
                        petition_analysis['petition_types']['examiner_dispute'] += 1
                    elif any('1.182' in rule for rule in rules):
                        petition_analysis['petition_types']['restriction'] += 1
                    else:
                        petition_analysis['petition_types']['other'] += 1

                except:
                    pass  # Skip if can't get details

            # Identify red flag applications
            if petition_count > 1 or (petition_count == 1 and 'denied' in [p.get('decisionTypeCodeDescriptionText', '').lower() for p in petitions.get('results', [])]):
                petition_analysis['red_flag_apps'].append({{
                    'app_num': app_num,
                    'petition_count': petition_count,
                    'title': app.get('inventionTitle', 'N/A'),
                    'art_unit': app.get('applicationMetaData', {{}}).get('groupArtUnitNumber', 'N/A')
                }})

    except Exception as e:
        print(f"⚠️ Could not analyze petitions for {{app_num}}: {{e}}")
        continue

print(f"✅ **Petition Analysis Complete**")
print(f"- Applications with Petitions: {{petition_analysis['apps_with_petitions']}}")
print(f"- Total Petitions: {{petition_analysis['total_petitions']}}")
print(f"- Red Flag Applications: {{len(petition_analysis['red_flag_apps'])}}\\n")

# PHASE 3: PTAB Challenge Assessment
print("**PHASE 3: Analyzing PTAB Challenges...**\\n")

ptab_analysis = {{
    'total_challenges': 0,
    'challenged_patents': 0,
    'instituted': 0,
    'final_decisions': 0,
    'high_risk_patents': []
}}

# Check PTAB challenges for granted patents
for patent in portfolio_data['granted_patents'][:30]:  # Limit to 30 to prevent explosion
    patent_num = patent.get('patentNumber')

    try:
        ptab_proceedings = ptab_search_proceedings_minimal(
            patent_number=patent_num
        )

        challenge_count = len(ptab_proceedings.get('results', []))
        if challenge_count > 0:
            ptab_analysis['challenged_patents'] += 1
            ptab_analysis['total_challenges'] += challenge_count

            # Check for high-risk patterns
            for proceeding in ptab_proceedings.get('results', []):
                status = proceeding.get('proceedingStatus', '').lower()

                if 'instituted' in status:
                    ptab_analysis['instituted'] += 1
                if 'final' in status:
                    ptab_analysis['final_decisions'] += 1

            ptab_analysis['high_risk_patents'].append({{
                'patent_num': patent_num,
                'challenge_count': challenge_count,
                'title': patent.get('inventionTitle', 'N/A')
            }})

    except Exception as e:
        print(f"**Note:** PTAB MCP unavailable or error for {{patent_num}}: {{e}}")
        continue

print(f"✅ **PTAB Analysis Complete**")
print(f"- Challenged Patents: {{ptab_analysis['challenged_patents']}}")
print(f"- Total Challenges: {{ptab_analysis['total_challenges']}}")
print(f"- Instituted Proceedings: {{ptab_analysis['instituted']}}\\n")

# PHASE 4: Risk Scoring and Correlation
if "{risk_scoring}" == "true":
    print("**PHASE 4: Calculating Risk Scores...**\\n")

    # Calculate portfolio-level risk score
    petition_risk_score = (
        (petition_analysis['petition_types']['revival'] * 2) +
        (petition_analysis['petition_types']['examiner_dispute'] * 1) +
        (petition_analysis['decisions']['denied'] * 3)
    )

    ptab_risk_score = (
        (ptab_analysis['total_challenges'] * 5) +
        (ptab_analysis['instituted'] * 3)
    )

    total_risk_score = petition_risk_score + ptab_risk_score

    if total_risk_score <= 5:
        risk_level = "LOW RISK ✅"
        risk_rating = 90
    elif total_risk_score <= 12:
        risk_level = "MEDIUM RISK ⚠️"
        risk_rating = 60
    else:
        risk_level = "HIGH RISK 🚨"
        risk_rating = 30

    print(f"### PORTFOLIO RISK ASSESSMENT\\n")
    print(f"**Overall Risk Level:** {{risk_level}} (Score: {{total_risk_score}}/{{risk_rating}})\\n")
    print(f"- **Petition Risk Score:** {{petition_risk_score}}")
    print(f"- **PTAB Risk Score:** {{ptab_risk_score}}\\n")

# PHASE 5: PRESENTATION - Summary Report
print("\\n## PORTFOLIO DUE DILIGENCE SUMMARY\\n")

# Portfolio Overview Table
print("### PORTFOLIO OVERVIEW\\n")
print(f"- **Company:** {company_name}")
print(f"- **Total Applications/Patents:** {{total_apps}}")
print(f"- **Granted Patents:** {{len(portfolio_data['granted_patents'])}}")
print(f"- **Pending Applications:** {{len(portfolio_data['pending_apps'])}}")
print(f"- **Abandoned Applications:** {{len(portfolio_data['abandoned_apps'])}}\\n")

# Petition Analysis Table
print("### PETITION ANALYSIS\\n")
print("| Metric | Count | Percentage |")
print("|--------|-------|------------|")
print(f"| Applications with Petitions | {{petition_analysis['apps_with_petitions']}} | {{(petition_analysis['apps_with_petitions']/total_apps*100) if total_apps > 0 else 0:.1f}}% |")
print(f"| Revival Petitions (37 CFR 1.137) | {{petition_analysis['petition_types']['revival']}} | - |")
print(f"| Examiner Disputes (37 CFR 1.181) | {{petition_analysis['petition_types']['examiner_dispute']}} | - |")
print(f"| Denied Petitions | {{petition_analysis['decisions']['denied']}} | {{(petition_analysis['decisions']['denied']/petition_analysis['total_petitions']*100) if petition_analysis['total_petitions'] > 0 else 0:.1f}}% |")

# RED FLAG APPLICATIONS
if petition_analysis['red_flag_apps']:
    print("\\n### 🚨 RED FLAG APPLICATIONS\\n")
    print("| App Number | Petition Count | Title | Art Unit |")
    print("|------------|----------------|-------|----------|")
    for red_flag in petition_analysis['red_flag_apps'][:10]:
        print(f"| {{red_flag['app_num']}} | {{red_flag['petition_count']}} | {{red_flag['title'][:50]}}... | {{red_flag['art_unit']}} |")

# PTAB CHALLENGES
if ptab_analysis['high_risk_patents']:
    print("\\n### PTAB CHALLENGED PATENTS\\n")
    print("| Patent Number | Challenges | Title |")
    print("|---------------|------------|-------|")
    for patent in ptab_analysis['high_risk_patents'][:10]:
        print(f"| {{patent['patent_num']}} | {{patent['challenge_count']}} | {{patent['title'][:60]}}... |")

# RECOMMENDED ACTIONS
print("\\n### RECOMMENDED ACTIONS\\n")

if total_risk_score > 12:
    print("**IMMEDIATE PRIORITY:**")
    print("1. 🚨 Review all red-flag applications for prosecution quality issues")
    print("2. 🚨 Assess PTAB settlement strategies for challenged patents")
    print("3. 🚨 Investigate art unit/examiner patterns causing petition spikes")
    print("4. 🚨 Implement enhanced quality controls and deadline management\\n")
elif total_risk_score > 5:
    print("**MODERATE PRIORITY:**")
    print("1. ⚠️ Monitor petition trends for degradation")
    print("2. ⚠️ Review denied petitions for process improvements")
    print("3. ⚠️ Enhance prosecution training and quality standards\\n")
else:
    print("**MAINTENANCE MODE:**")
    print("1. ✅ Continue current prosecution practices")
    print("2. ✅ Monitor for emerging patterns")
    print("3. ✅ Document successful strategies for replication\\n")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Limit portfolio analysis to 50 applications maximum to prevent context explosion
- Use targeted fields parameter in PFW searches (6 fields vs 15 standard = 60% reduction)
- Petition analysis limited to first 50 applications
- PTAB analysis limited to first 30 granted patents
- Always use include_documents=False for initial petition discovery
- Risk scoring provides relative assessment, not absolute predictions
- Requires both PFW and PTAB MCPs - will fail gracefully if unavailable

## PHASE 1: Portfolio Discovery (PFW MCP)

Step 1: Get company patent portfolio using Patent File Wrapper MCP with targeted fields:
```python
# CRITICAL: Use fields parameter for efficient portfolio discovery
pfw_search_applications_minimal(
    query='firstApplicantName:"{company_name}"',
    fields=[
        'applicationNumberText',
        'patentNumber', 
        'inventionTitle',
        'applicationMetaData.firstApplicantName',
        'applicationMetaData.groupArtUnitNumber',
        'applicationMetaData.filingDate'
    ],  # Only 6 fields vs 15 standard (60% reduction)
    limit={portfolio_size_limit}  # Can analyze larger portfolios efficiently
)
```

**Portfolio Analysis Benefits:**
- Targeted fields: 50 patents × 3KB = 150KB (manageable for comprehensive analysis)
- Enables complete portfolio lifecycle analysis

Step 2: Categorize applications by status:
- Granted patents: Full lifecycle analysis (prosecution -> petitions -> PTAB)
- Pending applications: Prosecution + petition analysis
- Abandoned applications: Petition analysis for revival patterns
- Foreign filings: International strategy assessment

## PHASE 2: Petition Risk Assessment (FPD MCP)

Step 3: Cross-reference portfolio with petition history:
For each application found in Phase 1:
```
fpd_search_petitions_by_application(
    application_number=app_number,
    include_documents=False
)
```

Red Flag Identification Matrix:

** CRITICAL RED FLAGS (Immediate Review):**
- Multiple petitions per application (>1)
- Denied revival petitions (abandonment + failed recovery)
- Pattern of examiner disputes (37 CFR 1.181)

WARNING: MODERATE RED FLAGS (Monitor Closely):
- Single revival petition (process improvement needed)
- Restriction disputes (claim scope issues)
- Granted examiner disputes (examiner over-strictness)

** PATTERN INDICATORS:**
- Art unit petition frequency above average
- Examiner-specific petition correlation
- Technology area procedural challenges

## PHASE 3: Post-Grant Challenge Assessment (PTAB MCP)

Step 4: PTAB vulnerability analysis for granted patents:
For each granted patent:
```
ptab_search_proceedings_minimal(
    patent_number=patent_number
)
```

Step 5: Correlation analysis between petition red flags and PTAB challenges:
- Key hypothesis: Patents with petition red flags may be more vulnerable to PTAB
- Calculate correlation coefficients and survival rates
- Identify predictive patterns for risk assessment

## PHASE 4: Comprehensive Risk Scoring (if risk_scoring=true)

Multi-dimensional Risk Calculation:

** Prosecution Risk (PFW Data):**
- Grant rate vs art unit average: ±2 points
- Prosecution length vs average: ±1 point
- Examiner interview frequency: ±1 point
- Office action count: +1 point per excess action

** Petition Risk (FPD Data):**
- Each petition filed: +2 points
- Denied petition: +3 points
- Revival petition: +2 points
- Examiner dispute: +1 point

** PTAB Risk (PTAB Data):**
- Each PTAB challenge: +5 points
- Institution decision: +3 points
- Adverse final written decision: +7 points
- Settlement/withdrawal: +2 points

TOTAL RISK SCORE:
- 0-5:  LOW RISK (Strong portfolio)
- 6-12: WARNING: MEDIUM RISK (Monitor closely)
- 13+:  HIGH RISK (Immediate attention)

## PHASE 5: Strategic Recommendations & Action Items

Prioritized Action Recommendations:

** IMMEDIATE ACTIONS (High Risk Applications):**
- Review prosecution strategy for petition-heavy applications
- Assess PTAB settlement opportunities for challenged patents
- Investigate art unit and examiner patterns for systemic issues

**[PENDING] SHORT-TERM IMPROVEMENTS (Medium Risk):**
- Enhance prosecution quality controls
- Implement proactive deadline management
- Develop examiner relationship strategies

**[OK] LONG-TERM OPTIMIZATION (Portfolio Strategy):**
- Technology area focus refinement
- Art unit selection optimization
- Cross-filing strategy enhancement
- Quality vs quantity balance adjustment

## EXPECTED DELIVERABLES

Comprehensive Portfolio Report:
- Executive summary with key metrics and insights
- Application-by-application risk assessment
- Cross-MCP correlation analysis and patterns
- Prioritized action item list with timelines

Strategic Intelligence:
- Prosecution quality improvement recommendations
- Art unit and examiner pattern insights
- Technology area portfolio optimization
- Competitive landscape and PTAB survival analysis

Predictive Analytics:
- PTAB vulnerability prediction model
- Petition red flag early warning system
- Portfolio risk trend analysis
- Cost-benefit optimization recommendations

** TRIPLE-MCP INTEGRATION**: This workflow showcases the power of combining Patent File Wrapper (prosecution), Final Petition Decisions (procedural), and PTAB (post-grant) data for unprecedented portfolio intelligence.

** COMPETITIVE ADVANTAGE**: Complete patent lifecycle visibility enables proactive risk management and strategic portfolio optimization that competitors cannot achieve without integrated data analysis."""


