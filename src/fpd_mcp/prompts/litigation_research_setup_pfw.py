"""Litigation Research Setup - Prosecution + petition history requiring PFW MCP"""

from . import mcp


@mcp.prompt(
    name="litigation_research_setup_pfw",
    description="Prepare litigation research with prosecution + petition history. At least ONE required (patent_number or application_number). include_prosecution: true/false for prosecution history. priority_documents: litigation/due_diligence/all. Requires PFW MCP."
)
async def litigation_research_setup_prompt(
    patent_number: str = "",
    application_number: str = "",
    include_prosecution: str = "true",
    priority_documents: str = "litigation"
) -> str:
    """
    Litigation research setup with prosecution history and petition analysis.
    
    WARNING: DEPENDENCIES: Requires Patent File Wrapper (PFW) MCP
    
    Identifier fields (at least ONE required):
    - patent_number: US patent number (e.g., "11788453", "11,788,453")
    - application_number: Application number (e.g., "17896175", "17/896,175")
    
    Research options:
    - include_prosecution: Include detailed prosecution history (true/false) [DEFAULT: true]
    - priority_documents: Document priority (litigation, due_diligence, all) [DEFAULT: litigation]
    
    Returns comprehensive litigation research package with prosecution context and petition red flag analysis.
    """
    return f"""Litigation Research Setup - Prosecution + Petition Analysis

Inputs Provided:
- Patent Number: "{patent_number}"
- Application Number: "{application_number}"
- Include Prosecution: {include_prosecution}
- Priority Documents: {priority_documents}

WARNING: DEPENDENCIES: This workflow requires Patent File Wrapper (PFW) MCP for complete prosecution history analysis.

 ATTORNEY WORKFLOW: Comprehensive litigation preparation combining prosecution history, petition red flags, and document collection for strategic case development.

## COMPLETE IMPLEMENTATION WITH ERROR HANDLING

```python
# PHASE 1: Identifier Resolution and Patent/Application Lookup
print(f"## LITIGATION RESEARCH SETUP")
print(f"**Patent Number:** {patent_number or 'Not provided'}")
print(f"**Application Number:** {application_number or 'Not provided'}")
print(f"**Include Prosecution:** {include_prosecution}")
print(f"**Priority Documents:** {priority_documents}\\n")

litigation_data = {{
    'patent_info': {{}},
    'application_number': "{application_number}" or None,
    'petition_history': [],
    'prosecution_metrics': {{}},
    'red_flags': [],
    'key_documents': []
}}

# Step 1: Resolve identifier and get basic patent/application info
try:
    print("**PHASE 1: Resolving Patent/Application Identifier...**\\n")

    if "{patent_number}":
        # Lookup by patent number using PFW MCP
        pfw_result = pfw_search_applications_minimal(
            patent_number="{patent_number}",
            fields=['applicationNumberText', 'patentNumber', 'inventionTitle',
                    'applicationStatusDescription', 'applicationMetaData.firstApplicantName',
                    'applicationMetaData.groupArtUnitNumber'],
            limit=1
        )

        if pfw_result and len(pfw_result.get('patents', [])) > 0:
            litigation_data['patent_info'] = pfw_result['patents'][0]
            litigation_data['application_number'] = pfw_result['patents'][0].get('applicationNumberText')
            print(f"✅ **Found Patent:** {patent_number}")
            print(f"   - Application: {{litigation_data['application_number']}}")
            print(f"   - Title: {{litigation_data['patent_info'].get('inventionTitle', 'N/A')}}")
            print(f"   - Assignee: {{litigation_data['patent_info'].get('applicationMetaData', {{}}).get('firstApplicantName', 'N/A')}}\\n")
        else:
            print(f"❌ Patent {patent_number} not found in PFW MCP\\n")

    elif "{application_number}":
        # Lookup by application number
        pfw_result = pfw_search_applications_minimal(
            application_number="{application_number}",
            fields=['applicationNumberText', 'patentNumber', 'inventionTitle',
                    'applicationStatusDescription', 'applicationMetaData.firstApplicantName',
                    'applicationMetaData.groupArtUnitNumber'],
            limit=1
        )

        if pfw_result and len(pfw_result.get('patents', [])) > 0:
            litigation_data['patent_info'] = pfw_result['patents'][0]
            litigation_data['application_number'] = "{application_number}"
            print(f"✅ **Found Application:** {application_number}")
            print(f"   - Title: {{litigation_data['patent_info'].get('inventionTitle', 'N/A')}}")
            print(f"   - Status: {{litigation_data['patent_info'].get('applicationStatusDescription', 'N/A')}}")
            print(f"   - Assignee: {{litigation_data['patent_info'].get('applicationMetaData', {{}}).get('firstApplicantName', 'N/A')}}\\n")
        else:
            print(f"❌ Application {application_number} not found in PFW MCP\\n")

except Exception as e:
    print(f"❌ **PFW MCP Error:** {{e}}")
    print("**Cannot proceed without PFW MCP - this workflow requires prosecution data**\\n")
    raise

# PHASE 2: Petition History Analysis (FPD MCP)
if litigation_data['application_number']:
    print("**PHASE 2: Analyzing Petition History...**\\n")

    try:
        petitions = fpd_search_petitions_by_application(
            application_number=litigation_data['application_number'],
            include_documents=False
        )

        petition_count = len(petitions.get('results', []))
        print(f"**Found {{petition_count}} petitions for this application**\\n")

        # Analyze each petition for red flags
        for petition in petitions.get('results', []):
            petition_id = petition.get('petitionDecisionRecordIdentifier')
            decision = petition.get('decisionTypeCodeDescriptionText', 'UNKNOWN')
            decision_date = petition.get('decisionDate', 'N/A')

            # Get petition details
            try:
                details = fpd_get_petition_details(petition_id=petition_id, include_documents=False)
                rules = details.get('ruleBag', [])

                petition_info = {{
                    'petition_id': petition_id,
                    'decision': decision,
                    'decision_date': decision_date,
                    'rules': rules,
                    'type': 'UNKNOWN'
                }}

                # Categorize petition type
                if any('1.137' in rule for rule in rules):
                    petition_info['type'] = 'Revival (37 CFR 1.137)'
                    # RED FLAG: Abandonment and revival
                    litigation_data['red_flags'].append({{
                        'type': 'ABANDONMENT_REVIVAL',
                        'severity': 'HIGH' if decision == 'DENIED' else 'MEDIUM',
                        'description': f"Application abandoned - Revival petition {{'denied' if decision == 'DENIED' else 'granted'}}",
                        'litigation_impact': 'Abandonment history may indicate prosecution quality issues or deadline management problems'
                    }})
                elif any('1.181' in rule for rule in rules):
                    petition_info['type'] = 'Examiner Dispute (37 CFR 1.181)'
                    # RED FLAG: Examiner conflicts
                    litigation_data['red_flags'].append({{
                        'type': 'EXAMINER_DISPUTE',
                        'severity': 'MEDIUM',
                        'description': f"Supervisory review requested - {{decision}}",
                        'litigation_impact': 'Examiner disputes may expose prosecution strategy weaknesses or claim issues'
                    }})
                elif any('1.182' in rule for rule in rules):
                    petition_info['type'] = 'Restriction (37 CFR 1.182)'

                litigation_data['petition_history'].append(petition_info)

            except Exception as e:
                print(f"⚠️ Could not get details for petition {{petition_id}}: {{e}}")
                continue

        # Add general red flag if multiple petitions
        if petition_count > 1:
            litigation_data['red_flags'].append({{
                'type': 'MULTIPLE_PETITIONS',
                'severity': 'HIGH',
                'description': f"{{petition_count}} petitions filed - indicates procedural complications",
                'litigation_impact': 'Multiple petitions suggest prosecution difficulties that may affect patent strength'
            }})

    except Exception as e:
        print(f"⚠️ **FPD MCP Error:** {{e}}\\n")

# PHASE 3: Document Collection (Priority Documents)
print("**PHASE 3: Collecting Priority Documents...**\\n")

if litigation_data['petition_history']:
    document_priorities = {{
        'high': [],
        'medium': []
    }}

    # Collect documents from petitions based on priority setting
    for petition in litigation_data['petition_history']:
        try:
            details = fpd_get_petition_details(
                petition_id=petition['petition_id'],
                include_documents=True
            )

            documents = details.get('documents', [])

            for doc in documents:
                doc_desc = doc.get('documentDescription', '').lower()

                # Prioritize litigation-relevant documents
                if "{priority_documents}" == "litigation":
                    if 'decision' in doc_desc or 'petition' in doc_desc or 'brief' in doc_desc:
                        document_priorities['high'].append({{
                            'petition_id': petition['petition_id'],
                            'doc_uuid': doc.get('documentUuid'),
                            'description': doc.get('documentDescription'),
                            'filing_date': doc.get('filingDate', 'N/A')
                        }})
                else:
                    # Collect all documents
                    document_priorities['high'].append({{
                        'petition_id': petition['petition_id'],
                        'doc_uuid': doc.get('documentUuid'),
                        'description': doc.get('documentDescription'),
                        'filing_date': doc.get('filingDate', 'N/A')
                    }})

        except:
            continue

    litigation_data['key_documents'] = document_priorities['high']
    print(f"✅ **Identified {{len(litigation_data['key_documents'])}} priority documents**\\n")

# PHASE 4: PRESENTATION - Litigation Package Summary
print("\\n## LITIGATION RESEARCH PACKAGE SUMMARY\\n")

# Case Information
print("### CASE INFORMATION\\n")
print(f"**Patent/Application:** {{litigation_data['application_number']}}")
if litigation_data['patent_info'].get('patentNumber'):
    print(f"**Patent Number:** {{litigation_data['patent_info'].get('patentNumber')}}")
print(f"**Title:** {{litigation_data['patent_info'].get('inventionTitle', 'N/A')}}")
print(f"**Assignee:** {{litigation_data['patent_info'].get('applicationMetaData', {{}}).get('firstApplicantName', 'N/A')}}")
print(f"**Status:** {{litigation_data['patent_info'].get('applicationStatusDescription', 'N/A')}}\\n")

# Petition History Summary
if litigation_data['petition_history']:
    print("### PETITION HISTORY\\n")
    print("| Petition Type | Decision | Decision Date |")
    print("|---------------|----------|---------------|")
    for petition in litigation_data['petition_history']:
        print(f"| {{petition['type']}} | {{petition['decision']}} | {{petition['decision_date']}} |")
    print()

# RED FLAG ANALYSIS
if litigation_data['red_flags']:
    print("### 🚨 LITIGATION RED FLAGS\\n")
    print("| Severity | Type | Description | Litigation Impact |")
    print("|----------|------|-------------|-------------------|")
    for flag in litigation_data['red_flags']:
        print(f"| **{{flag['severity']}}** | {{flag['type']}} | {{flag['description']}} | {{flag['litigation_impact'][:80]}}... |")
    print()
else:
    print("### ✅ NO PETITION RED FLAGS IDENTIFIED\\n")
    print("Clean prosecution history with no procedural complications.\\n")

# Key Documents for Litigation
if litigation_data['key_documents']:
    print("### PRIORITY DOCUMENTS FOR LITIGATION REVIEW\\n")
    print("| Document Description | Filing Date |")
    print("|----------------------|-------------|")
    for doc in litigation_data['key_documents'][:20]:
        print(f"| {{doc['description']}} | {{doc['filing_date']}} |")
    print()

# Litigation Strategy Recommendations
print("### LITIGATION STRATEGY RECOMMENDATIONS\\n")

if len(litigation_data['red_flags']) == 0:
    print("**PROSECUTION STRENGTH:**")
    print("- Clean prosecution history supports patent validity")
    print("- No procedural complications to address")
    print("- Strong foundation for litigation\\n")
elif len(litigation_data['red_flags']) <= 2:
    print("**MODERATE CONCERNS:**")
    print("- Review and prepare explanations for petition history")
    print("- Assess impact on patent strength and validity claims")
    print("- Develop defensive strategy for identified red flags\\n")
else:
    print("**SIGNIFICANT CONCERNS:**")
    print("- Multiple procedural issues may impact patent defensibility")
    print("- Detailed prosecution history review essential")
    print("- Consider settlement opportunities or claim amendments\\n")

print("**NEXT STEPS:**")
print("1. Download and review all priority documents")
print("2. Conduct detailed prosecution history analysis using PFW MCP")
print("3. Prepare explanations for any petition red flags")
print("4. Assess PTAB vulnerability if granted patent")
if "{include_prosecution}" == "true":
    print("5. Obtain full prosecution file wrapper for deep analysis")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Requires PFW MCP for patent/application lookup - workflow will fail if unavailable
- Limit petition document collection to 20-30 documents to prevent context explosion
- Use priority_documents='litigation' to focus on most relevant documents
- Text extraction from petition documents has costs - use sparingly
- For comprehensive prosecution analysis, use PFW MCP's full file history tools separately
- Red flag analysis is qualitative - requires attorney judgment for litigation strategy

## PHASE 1: Identifier Resolution & Strategy

Step 1: Process flexible identifier inputs using targeted fields:
```python
if patent_number:
    # Use PFW MCP with fields parameter for targeted retrieval
    patent_info = pfw_search_applications_minimal(
        query='patentNumber:"{{patent_number}}"',
        fields=['applicationNumberText', 'patentNumber', 'inventionTitle', 'applicationMetaData.firstApplicantName'],
        limit=1
    )
    # Extract application_number for petition search

elif application_number:
    # Direct application lookup with PFW MCP using targeted fields
    application_info = pfw_search_applications_minimal(
        query='applicationNumberText:"{application_number}"',
        fields=['applicationNumberText', 'inventionTitle', 'applicationMetaData.firstApplicantName'],
        limit=1
    )
```

**CRITICAL**: Always use the fields parameter with PFW tools for efficient data retrieval:
- Standard PFW search: ~25KB per result
- Targeted fields: ~500 chars per result
- Enables broader litigation research

Step 2: Validate target and set research scope:
- Granted patent: Full prosecution + petition + enforcement analysis
- Pending application: Current prosecution + petition analysis
- Abandoned application: Abandonment reason + petition analysis

## PHASE 2: Prosecution History Analysis (PFW MCP)

Step 3: Get comprehensive prosecution package (if include_prosecution=true):
```
pfw_get_application_details(
    application_number="{application_number}",
    include_documents=true
)
```

Document Prioritization for Litigation:

** LITIGATION PRIORITY:**
- Notice of Allowance
- Final Office Actions
- Non-Final Office Actions
- Applicant Responses
- Examiner Citations
- Interview Summaries

**[PENDING] DUE DILIGENCE PRIORITY:**
- Notice of Allowance
- Patent Grant Document
- Final Office Actions
- Key Applicant Responses

## PHASE 3: Petition Red Flag Analysis (FPD MCP)

Step 4: Comprehensive petition history review:
```
fpd_search_petitions_by_application(
    application_number="{application_number}",
    include_documents=True
)
```

Petition Litigation Impact Analysis:

** HIGH LITIGATION RISK:**
- Denied revival petitions -> Questions about diligent prosecution
- Multiple examiner disputes -> Potential examination quality issues
- Denied restriction petitions -> Claim scope and breadth concerns

WARNING: MODERATE LITIGATION CONSIDERATIONS:
- Granted revival petitions -> Timeline and diligence questions
- Procedural disputes -> Process complexity indicators
- Multiple petition types -> Difficult prosecution history

** LOW LITIGATION IMPACT:**
- No petitions -> Normal prosecution process
- Granted administrative petitions -> Routine procedural accommodations

## PHASE 4: Strategic Document Collection

Step 5: Prioritized document acquisition strategy:

High-priority prosecution documents (PFW MCP):
- Notice of Allowance with examiner reasoning
- Final Office Actions with rejections
- Applicant responses with claim amendments
- Examiner citations and prior art analysis

High-priority petition documents (FPD MCP):
- Petition filing documents with legal arguments
- Director decision letters with reasoning
- Supporting briefs and evidence
- Related prosecution correspondence

Step 6: Document extraction and text analysis:
For critical documents:
```
fpd_get_document_content(
    petition_id=petition_id,
    document_identifier=document_id
)
```

## PHASE 5: Integrated Analysis & Strategy Development

Cross-MCP Correlation Analysis:

** Prosecution Quality Indicators:**
- Examiner interaction patterns
- Claim amendment frequency
- Prior art handling effectiveness
- Prosecution timeline efficiency

** Petition Correlation:**
- Prosecution difficulty correlation with petition frequency
- Examiner dispute patterns and outcomes
- Timeline impact of petition proceedings

** Litigation Strength Assessment:**
- Prosecution robustness evaluation
- Potential vulnerability identification
- Strategic advantage assessment

## LITIGATION READINESS ASSESSMENT

** Prosecution Strength Indicators:**
- Clean prosecution history (minimal office actions)
- Strong examiner citation handling
- Clear claim scope development
- Robust prior art distinguishing

** Potential Vulnerability Areas:**
- Petition red flags requiring explanation
- Prosecution timeline irregularities
- Examiner dispute patterns
- Claim amendment frequency and rationale

** Strategic Litigation Advantages:**
- Strong prosecution record
- Examiner confidence indicators
- Clear invention disclosure
- Minimal procedural complications

## EXPECTED DELIVERABLES

Comprehensive Litigation Package:
- Integrated prosecution and petition timeline
- Red flag analysis with litigation impact assessment
- Priority document collection with download links
- Cross-MCP correlation insights and strategic analysis

Attorney Work Product:
- Prosecution strength/weakness analysis
- Petition history explanation and strategy
- Document prioritization for litigation team
- Discovery and evidence collection roadmap

Strategic Litigation Intelligence:
- Examiner behavior and decision patterns
- Prosecution quality indicators and benchmarking
- Potential challenges and defensive strategies
- Cross-reference opportunities with related patents

Cost-Optimized Research Plan:
- Document extraction priorities with cost estimates
- Text analysis recommendations for key documents
- Workflow optimization for litigation timeline
- Resource allocation guidance for legal team

** PFW-FPD INTEGRATION**: Combining prosecution history with petition analysis reveals complete patent development story crucial for litigation strategy.

** LITIGATION READY**: Organized document package and integrated analysis provide immediate litigation team support with strategic insights."""


