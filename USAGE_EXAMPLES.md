# USPTO Final Petition Decisions MCP Usage Examples

This document provides comprehensive examples for using the Final Petition Decisions (FPD) MCP, including basic searches, red flag identification, cross-MCP integration workflows, and progressive disclosure patterns.

## Notes on Final Petition Decisions MCP Usage

For the most part, **the LLMs will perform these searches and workflows on their own with minimal guidance from the user**. These examples are illustrative to give insight into what the LLMs are doing in the background.

**💡 Best Practice Recommendation:** For complex workflows or when you're unsure about the best approach, start by asking the LLM to use the `FPD_get_guidance` tool first. This tool provides context-efficient workflow recommendations and helps the LLM choose the most appropriate tools and strategies for your specific use case.

Sample requests that the user can give to the LLM to trigger the examples are as follows:

### Sample User Requests by Example

**Example 1 - Company Portfolio Petition Analysis:**
- *"Find all petitions filed by TechCorp and tell me about any red flags"*
- *"Analyze this company's petition track record for due diligence"*
- *"Show me petition patterns for Innovate Inc over the last 5 years"*

**Example 2 - Revival Petition Discovery:**
- *"Show me revival petitions for art unit 2128 - I'm analyzing abandonment patterns"*
- *"Find all abandoned applications that petitioned for revival"*
- *"Which companies have the most revival petitions?"*

**Example 3 - Art Unit Quality Assessment:**
- *"Analyze art unit 2128's petition frequency and types"*
- *"Compare petition rates across art units in technology center 2100"*
- *"Identify problematic art units with high examiner disputes"*

**Example 4 - Application Petition History:**
- *"Get me the petition history for application 17896175"*
- *"Did this application have any procedural issues during prosecution?"*
- *"Check if this patent had petition red flags"*

**Example 5 - Examiner Dispute Analysis:**
- *"Find examiner disputes and tell me the Director's overturn rate"*
- *"Show me supervisory review petitions for this art unit"*
- *"Identify examiners with high petition rates"*

**Example 6-9 - Progressive Disclosure & Document Access:**
- *"Get the full details and documents for this petition"*
- *"Download the petition decision letter for analysis"*
- *"Extract text from this petition document so I can read it"*

**Example 10-12 - Cross-MCP Integration Workflows:**
- *"Research this company's petition track record and correlate with their PTAB challenges"*
- *"Analyze this art unit's prosecution patterns and petition history"*
- *"Do a complete due diligence check on this patent portfolio including petitions and PTAB"*
- *"Check if patents with revival petitions are more vulnerable to PTAB challenges"*
- *"Find prosecution quality issues by looking at petition and PTAB correlation"*

**Example 13 - Comprehensive Workflow Guidance:**
- *"Show me the best workflows for using these petition search tools"*
- *"How do I integrate petition data with prosecution and PTAB analysis?"*
- *"What are the red flags I should look for in petition decisions?"*

---

## Example 1: Company Portfolio Petition Analysis

```python
# Find all petitions filed by a company
result = Search_petitions_minimal(
    query='firstApplicantName:"TechCorp Inc"',
    limit=50
)

print(f"Found {result['recordTotalQuantity']} petitions")
for petition in result['results']:
    print(f"App {petition['applicationNumberText']}: {petition['decisionTypeCodeDescriptionText']}")
    print(f"  Filed: {petition['petitionMailDate']} | Decided: {petition['decisionDate']}")
```

## Example 2: Revival Petition Discovery (Abandonment Red Flags)

```python
# Find all revival petitions under 37 CFR 1.137
revival_petitions = Search_petitions_balanced(
    query='ruleBag:"37 CFR 1.137"',
    limit=20
)

print(f"Found {len(revival_petitions['results'])} revival petitions")
for petition in revival_petitions['results']:
    status = petition['decisionTypeCodeDescriptionText']
    print(f"App {petition['applicationNumberText']}: {status}")
    print(f"  Inventor: {petition['firstApplicantName']}")
    print(f"  Art Unit: {petition.get('groupArtUnitNumber', 'N/A')}")
    print(f"  Issues: {petition.get('petitionIssueConsideredTextBag', [])}")
```

## Example 3: Art Unit Quality Assessment

```python
# Analyze petition patterns for a specific art unit
art_unit_petitions = Search_petitions_by_art_unit(
    art_unit="2128",
    date_range="2020-01-01:2024-12-31",
    limit=50
)

# Count petition types
petition_types = {}
for petition in art_unit_petitions['results']:
    petition_type = petition.get('decisionPetitionTypeCodeDescriptionText', 'Unknown')
    petition_types[petition_type] = petition_types.get(petition_type, 0) + 1

print(f"Art Unit 2128 Petition Analysis (2020-2024):")
for ptype, count in sorted(petition_types.items(), key=lambda x: x[1], reverse=True):
    print(f"  {ptype}: {count}")
```

## Example 4: Application Petition History

```python
# Get complete petition history for an application
petition_history = Search_petitions_by_application(
    application_number="17896175",
    include_documents=False
)

if petition_history['recordTotalQuantity'] == 0:
    print("✅ No petitions - normal prosecution")
elif petition_history['recordTotalQuantity'] == 1:
    print("⚠️ One petition - review details")
    petition = petition_history['results'][0]
    print(f"  Type: {petition['decisionPetitionTypeCodeDescriptionText']}")
    print(f"  Outcome: {petition['decisionTypeCodeDescriptionText']}")
else:
    print(f"🚨 Multiple petitions ({petition_history['recordTotalQuantity']}) - red flag!")
    for petition in petition_history['results']:
        print(f"  {petition['decisionPetitionTypeCodeDescriptionText']}: {petition['decisionTypeCodeDescriptionText']}")
```

## Example 5: Examiner Dispute Analysis

```python
# Find all supervisory review petitions (examiner disputes)
examiner_disputes = Search_petitions_balanced(
    query='ruleBag:"37 CFR 1.181"',
    limit=30
)

# Count granted vs denied
granted = sum(1 for p in examiner_disputes['results'] if p['decisionTypeCodeDescriptionText'] == 'GRANTED')
denied = sum(1 for p in examiner_disputes['results'] if p['decisionTypeCodeDescriptionText'] == 'DENIED')

print(f"Examiner Dispute Petitions (37 CFR 1.181):")
print(f"  Granted: {granted} ({granted/len(examiner_disputes['results'])*100:.1f}%)")
print(f"  Denied: {denied} ({denied/len(examiner_disputes['results'])*100:.1f}%)")
print(f"  Director overturn rate: {granted/(granted+denied)*100:.1f}%")
```

## Example 6: Get Full Petition Details with Documents

```python
# First, find a petition
search_result = Search_petitions_minimal(
    query='firstApplicantName:"Acme Corp"',
    limit=1
)

if search_result['results']:
    petition_id = search_result['results'][0]['petitionDecisionRecordIdentifier']

    # Get complete petition details
    details = Get_petition_details(
        petition_id=petition_id,
        include_documents=True
    )

    print(f"Petition Details:")
    print(f"  Application: {details['applicationNumberText']}")
    print(f"  Title: {details.get('inventionTitle', 'N/A')}")
    print(f"  Issues: {details.get('petitionIssueConsideredTextBag', [])}")
    print(f"  Rules Cited: {details.get('ruleBag', [])}")
    print(f"  Statutes Cited: {details.get('statuteBag', [])}")

    if 'documentBag' in details:
        print(f"\nDocuments ({len(details['documentBag'])}):")
        for doc in details['documentBag']:
            print(f"  - {doc['documentFileName']} ({doc['pageCount']} pages)")
```

## Example 7: Download Petition Documents

```python
# Get petition details with documents
details = Get_petition_details(
    petition_id="uuid-from-search",
    include_documents=True
)

# Generate download URLs for each document
if 'documentBag' in details:
    for doc in details['documentBag']:
        download_info = FPD_get_document_download(
            petition_id=details['petitionDecisionRecordIdentifier'],
            document_identifier=doc['documentIdentifier']
        )

        print(f"**📁 [Download {doc['documentFileName']} ({doc['pageCount']} pages)]({download_info['download_url']})**")
```

## Example 8: Denied Petition Red Flag Analysis

```python
# Find all denied petitions for risk assessment
denied = Search_petitions_balanced(
    query='decisionTypeCodeDescriptionText:DENIED',
    limit=50
)

print(f"Denied Petition Analysis ({len(denied['results'])} petitions):")

# Group by petition type
denial_by_type = {}
for petition in denied['results']:
    ptype = petition.get('decisionPetitionTypeCodeDescriptionText', 'Unknown')
    denial_by_type[ptype] = denial_by_type.get(ptype, 0) + 1

for ptype, count in sorted(denial_by_type.items(), key=lambda x: x[1], reverse=True):
    print(f"  {ptype}: {count} denials")
```

## Example 9: Progressive Disclosure Workflow

```python
# Stage 1: Fast discovery with minimal fields
discovery = Search_petitions_minimal(
    query='firstApplicantName:"Innovate Inc"',
    limit=100
)

print(f"Stage 1: Found {discovery['recordTotalQuantity']} petitions")

# Stage 2: User selects 5 petitions of interest (based on dates, outcome, etc.)
selected_ids = [p['petitionDecisionRecordIdentifier'] for p in discovery['results'][:5]]

# Stage 3: Get detailed analysis for selected petitions
print("\nStage 2: Detailed analysis of selected petitions:")
for petition_id in selected_ids:
    details = Get_petition_details(
        petition_id=petition_id,
        include_documents=True
    )

    print(f"\nApp {details['applicationNumberText']}:")
    print(f"  Type: {details['decisionPetitionTypeCodeDescriptionText']}")
    print(f"  Outcome: {details['decisionTypeCodeDescriptionText']}")
    print(f"  Issues: {', '.join(details.get('petitionIssueConsideredTextBag', []))}")
    print(f"  Documents: {len(details.get('documentBag', []))} available")

# Stage 4: Download specific documents if needed
# (See Example 7)
```

## Example 10: Cross-MCP Integration with Patent File Wrapper

```python
# Find petitions for a company
petitions = Search_petitions_minimal(
    query='firstApplicantName:"Acme Corp"',
    limit=30
)

# For each petition, get prosecution history from PFW MCP
for petition in petitions['results']:
    app_number = petition['applicationNumberText']

    # Get prosecution history from Patent File Wrapper MCP
    prosecution = pfw_search_applications_balanced(
        query=f'applicationNumberText:{app_number}',
        limit=1
    )

    if prosecution['applications']:
        app = prosecution['applications'][0]

        print(f"\nApp {app_number}:")
        print(f"  Petition: {petition['decisionPetitionTypeCodeDescriptionText']} ({petition['decisionTypeCodeDescriptionText']})")
        print(f"  Examiner: {app.get('examinerNameText', 'N/A')}")
        print(f"  Status: {app.get('applicationStatusDescriptionText', 'N/A')}")
        print(f"  Art Unit: {app.get('groupArtUnitNumber', 'N/A')}")

        # Red flag correlation
        if petition['decisionTypeCodeDescriptionText'] == 'DENIED':
            print(f"  ⚠️ RED FLAG: Denied petition may indicate weak prosecution strategy")
```

## Example 11: Cross-MCP Integration with PTAB

```python
# Find revival petitions
revivals = Search_petitions_balanced(
    query='ruleBag:"37 CFR 1.137"',
    limit=20
)

# Check if revived patents faced PTAB challenges
for petition in revivals['results']:
    patent_number = petition.get('patentNumber')

    if patent_number:
        # Check PTAB MCP for post-grant challenges
        ptab_proceedings = ptab_search_proceedings_minimal(
            patent_number=patent_number
        )

        print(f"\nPatent {patent_number}:")
        print(f"  Revival petition: {petition['decisionTypeCodeDescriptionText']}")

        if ptab_proceedings['recordTotalQuantity'] > 0:
            print(f"  🚨 PTAB Challenge Found!")
            print(f"  Hypothesis: Revival petition → difficult prosecution → PTAB vulnerability")
        else:
            print(f"  ✅ No PTAB challenges (yet)")
```

## Example 12: Three-MCP Complete Lifecycle Analysis

```python
# Complete patent lifecycle: Filing → Prosecution → Petitions → Grant → PTAB

# Step 1: Find company's patents from PFW
patents = pfw_search_applications_balanced(
    query='firstApplicantName:"Target Company"',
    limit=50
)

lifecycle_analysis = []

for patent in patents['applications']:
    app_number = patent['applicationNumberText']
    patent_number = patent.get('patentNumber')

    # Step 2: Check FPD for petition history
    petitions = Search_petitions_by_application(
        application_number=app_number,
        include_documents=False
    )

    # Step 3: If granted, check PTAB for challenges
    ptab_count = 0
    if patent_number:
        ptab_proceedings = ptab_search_proceedings_minimal(
            patent_number=patent_number
        )
        ptab_count = ptab_proceedings['recordTotalQuantity']

    # Compile lifecycle data
    lifecycle_analysis.append({
        'app_number': app_number,
        'patent_number': patent_number or 'Pending',
        'status': patent['applicationStatusDescriptionText'],
        'petition_count': petitions['recordTotalQuantity'],
        'ptab_challenge_count': ptab_count,
        'examiner': patent.get('examinerNameText', 'N/A'),
        'art_unit': patent.get('groupArtUnitNumber', 'N/A')
    })

# Analyze correlations
print("Complete Patent Lifecycle Analysis:\n")
for item in lifecycle_analysis:
    risk_score = item['petition_count'] * 2 + item['ptab_challenge_count'] * 3

    print(f"App {item['app_number']}:")
    print(f"  Status: {item['status']}")
    print(f"  Petitions: {item['petition_count']}")
    print(f"  PTAB Challenges: {item['ptab_challenge_count']}")
    print(f"  Risk Score: {risk_score}/10")

    if item['petition_count'] > 0 and item['ptab_challenge_count'] > 0:
        print(f"  🚨 HIGH RISK: Both petition and PTAB issues")
    elif item['petition_count'] > 1:
        print(f"  ⚠️ MEDIUM RISK: Multiple petitions during prosecution")
    else:
        print(f"  ✅ LOW RISK: Normal prosecution")
    print()
```

## Example 13: Get Comprehensive Workflow Guidance

```python
# Get complete MCP usage guidance including all workflows
guidance = FPD_get_guidance(section="overview")

# Available sections:
# - "overview": General tool overview and workflows
# - "tools": All 8 tools and their use cases
# - "red_flags": Red flag identification patterns
# - "documents": Document download workflows
# - "workflows_pfw": PFW MCP integration patterns
# - "workflows_ptab": PTAB MCP integration patterns
# - "workflows_complete": Complete portfolio due diligence
# - "ultra_context": Ultra-minimal context workflows

print(guidance)
```

## Tool Reference

### Available Search Tools (4 Tools):

1. **Search_petitions_minimal** - Ultra-fast petition discovery (50-100 petitions, 95-99% context reduction)
2. **Search_petitions_balanced** - Detailed petition analysis (10-20 petitions, 80-88% context reduction)
3. **Search_petitions_by_art_unit** - Art unit quality assessment with date range filtering
4. **Search_petitions_by_application** - Complete petition history for specific application

### Detail & Document Tools (3 Tools):

5. **Get_petition_details** - Full petition details by UUID with optional documentBag
6. **FPD_get_document_download** - Browser-accessible PDF download URLs
7. **FPD_get_document_content_with_mistral_ocr** - OCR text extraction from petition documents

### Guidance Tool (1 Tool):

8. **FPD_get_guidance** - Selective guidance sections for context-efficient workflows and cross-MCP integration patterns

## Query Syntax

### Basic Search Operators

```python
# Exact phrase match
query='firstApplicantName:"TechCorp Inc"'

# Wildcard search
query='firstApplicantName:Tech*'

# Field-specific search
query='groupArtUnitNumber:2128'

# Date range (use with date fields)
query='decisionDate:[2020-01-01 TO 2024-12-31]'

# Boolean operators
query='firstApplicantName:"Acme" AND decisionTypeCodeDescriptionText:DENIED'
```

### Common Search Patterns

```python
# Find all revival petitions
query='ruleBag:"37 CFR 1.137"'

# Find examiner disputes
query='ruleBag:"37 CFR 1.181"'

# Find restriction petitions
query='ruleBag:"37 CFR 1.182"'

# Find denied petitions
query='decisionTypeCodeDescriptionText:DENIED'

# Find granted petitions
query='decisionTypeCodeDescriptionText:GRANTED'

# Find dismissed petitions
query='decisionTypeCodeDescriptionText:DISMISSED'

# Find petitions by art unit
query='groupArtUnitNumber:2100'

# Find petitions by technology center
query='technologyCenter:2100'

# Combine multiple criteria
query='firstApplicantName:"Acme" AND decisionTypeCodeDescriptionText:DENIED AND ruleBag:"37 CFR 1.137"'
```

## Red Flag Indicators

### High Priority Red Flags:

- **Multiple Petitions:** Same application has 2+ petitions → Difficult prosecution
- **Denied Revival Petition:** Application abandoned and revival denied → Failed recovery
- **Examiner Dispute Denied:** Supervisory review denied → Weak legal arguments
- **Multiple Art Unit Issues:** Art unit has high petition frequency → Systematic problems

### Medium Priority Red Flags:

- **Single Revival Petition:** One abandonment → Check if procedural or substantive issue
- **Granted Examiner Dispute:** Director overturned examiner → Examiner may have been too strict
- **Restriction Petition:** Claim scope issues → Review divisional strategy

### Low Priority (Informational):

- **No Petitions:** Normal prosecution → Positive indicator
- **Granted Rule Waiver:** Special circumstances accommodated → Case-by-case assessment

## Performance Tips

### Context Reduction Strategy:

1. **Discovery (Minimal):** Use `Search_petitions_minimal` for initial exploration (50-100 results)
2. **Selection:** User reviews results and selects 3-5 petitions of interest
3. **Analysis (Balanced):** Use `Search_petitions_balanced` or `Search_petitions_by_application` for detailed review (10-20 results)
4. **Details:** Use `Get_petition_details` for 1-5 selected petitions (full data)
5. **Documents:** Use `FPD_get_document_download` only when user needs PDFs

**Token Savings:** This progressive approach reduces context by ~93% compared to fetching full data upfront.

### Best Practices:

- Start with minimal search for discovery
- Filter and select before detailed analysis
- Use art unit search for systematic analysis
- Use application search for targeted research
- Enable documents only when needed
- Leverage cross-MCP integration for complete picture

## Integration Patterns

### With Patent File Wrapper MCP:

**Shared Fields:**
- `applicationNumberText` - Primary linking key
- `groupArtUnitNumber` - Art unit correlation
- `firstApplicantName` - Party matching

**Common Workflows:**
- Petition → Get prosecution history
- Examiner disputes → Check examiner patterns
- Revival petitions → Analyze abandonment reasons

### With PTAB MCP:

**Shared Fields:**
- `patentNumber` - Secondary linking key (if granted)
- `groupArtUnitNumber` - Art unit correlation
- `firstApplicantName` - Party matching

**Common Workflows:**
- Petition red flags → Check PTAB vulnerability
- Denied petitions → Correlate with PTAB challenges
- Art unit analysis → Prosecution quality vs PTAB survival

## Questions?

For more detailed examples and workflow guidance, use the `FPD_get_guidance` tool with specific sections like "workflows_pfw", "workflows_ptab", or "workflows_complete" for targeted LLM-friendly guidance for complex multi-step analyses.
