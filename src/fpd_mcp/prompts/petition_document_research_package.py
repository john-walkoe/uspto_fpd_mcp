"""Petition Document Research Package - Collect comprehensive petition documents"""

from . import mcp


@mcp.prompt(
    name="petition_document_research_package",
    description="Collect comprehensive petition documents. At least ONE required (petition_identifier or application_number). extract_text: true/false for text extraction. document_priority: high/medium/all for filtering."
)
async def petition_document_research_package_prompt(
    petition_identifier: str = "",
    application_number: str = "",
    document_priority: str = "high",
    extract_text: str = "false"
) -> str:
    """
    Petition document research package for detailed case analysis and litigation preparation.
    
    Identifier fields (at least ONE required):
    - petition_identifier: Specific petition UUID for direct lookup
    - application_number: Application number to find petition history (e.g., "17896175")
    
    Document options:
    - document_priority: Priority level (high, medium, all) [DEFAULT: high]
    - extract_text: Extract document text for analysis (true/false) [DEFAULT: false]
    
    Returns organized document package with download links and optional text extraction for detailed petition analysis.
    """
    return f"""Petition Document Research Package - Comprehensive Case Analysis

Inputs Provided:
- Petition Identifier: "{petition_identifier}"
- Application Number: "{application_number}"
- Document Priority: {document_priority}
- Extract Text: {extract_text}

 ATTORNEY WORKFLOW: Systematic document collection and analysis for petition research, litigation preparation, and Director's reasoning analysis.

## COMPLETE IMPLEMENTATION WITH ERROR HANDLING

```python
# PHASE 1: Petition Identification
print(f"**Document Research Package**")
print(f"**Petition ID:** {petition_identifier or 'Not provided'}")
print(f"**Application Number:** {application_number or 'Not provided'}")
print(f"**Document Priority:** {document_priority}")
print(f"**Text Extraction:** {extract_text}\\n")

petitions_to_process = []

if "{petition_identifier}":
    # Direct petition lookup
    try:
        petition_details = fpd_get_petition_details(
            petition_id="{petition_identifier}",
            include_documents=True
        )
        petitions_to_process.append(petition_details)
        print(f"✅ Retrieved petition {{petition_details.get('petitionDecisionRecordIdentifier')}}")
    except Exception as e:
        print(f"❌ Error retrieving petition: {{e}}")

elif "{application_number}":
    # Search for all petitions related to application
    try:
        app_petitions = fpd_search_petitions_by_application(
            application_number="{application_number}",
            include_documents=False
        )

        print(f"**Found {{len(app_petitions.get('results', []))}} petitions for application {application_number}**\\n")

        # Get details for each petition (limit to 10 to prevent context explosion)
        for petition in app_petitions.get('results', [])[:10]:
            petition_id = petition.get('petitionDecisionRecordIdentifier')
            try:
                details = fpd_get_petition_details(
                    petition_id=petition_id,
                    include_documents=True
                )
                petitions_to_process.append(details)
                print(f"✅ Retrieved petition {{petition_id}}")
            except Exception as e:
                print(f"⚠️ Could not retrieve petition {{petition_id}}: {{e}}")
                continue

    except Exception as e:
        print(f"❌ Error searching for application petitions: {{e}}")

# PHASE 2: Document Classification and Prioritization
document_categories = {{
    'high_priority': [],
    'medium_priority': [],
    'low_priority': []
}}

# Document type classification keywords
high_priority_keywords = ['petition', 'decision', 'brief', 'letter', 'director']
medium_priority_keywords = ['response', 'reply', 'examiner', 'correspondence']

for petition in petitions_to_process:
    documents = petition.get('documents', [])
    petition_id = petition.get('petitionDecisionRecordIdentifier')
    app_num = petition.get('applicationNumberText', 'N/A')
    decision = petition.get('decisionTypeCodeDescriptionText', 'UNKNOWN')

    print(f"\\n**Processing Petition:** {{petition_id}}")
    print(f"  - Application: {{app_num}}")
    print(f"  - Decision: {{decision}}")
    print(f"  - Total Documents: {{len(documents)}}\\n")

    for doc in documents:
        doc_desc = doc.get('documentDescription', '').lower()
        doc_uuid = doc.get('documentUuid')

        # Classify document by priority
        is_high_priority = any(keyword in doc_desc for keyword in high_priority_keywords)
        is_medium_priority = any(keyword in doc_desc for keyword in medium_priority_keywords)

        doc_info = {{
            'petition_id': petition_id,
            'app_num': app_num,
            'doc_uuid': doc_uuid,
            'description': doc.get('documentDescription'),
            'document_code': doc.get('documentCode'),
            'filing_date': doc.get('filingDate', 'N/A')
        }}

        if is_high_priority:
            document_categories['high_priority'].append(doc_info)
        elif is_medium_priority:
            document_categories['medium_priority'].append(doc_info)
        else:
            document_categories['low_priority'].append(doc_info)

# PHASE 3: Generate Document Download Links
print("\\n## DOCUMENT PACKAGE ORGANIZATION\\n")

# Determine which documents to include based on priority setting
if "{document_priority}" == "high":
    docs_to_include = document_categories['high_priority']
    print("**Priority Level:** HIGH PRIORITY ONLY\\n")
elif "{document_priority}" == "medium":
    docs_to_include = document_categories['high_priority'] + document_categories['medium_priority']
    print("**Priority Level:** HIGH + MEDIUM PRIORITY\\n")
else:  # "all"
    docs_to_include = document_categories['high_priority'] + document_categories['medium_priority'] + document_categories['low_priority']
    print("**Priority Level:** ALL DOCUMENTS\\n")

print(f"**Total Documents to Process:** {{len(docs_to_include)}}\\n")

# Generate download links
print("### DOCUMENT DOWNLOAD LINKS\\n")
print("| Priority | Document | App Number | Filing Date | Download Link |")
print("|----------|----------|------------|-------------|---------------|")

download_links = []

for doc in docs_to_include[:50]:  # Limit to 50 documents to prevent context explosion
    try:
        download_url = fpd_get_document_download(document_uuid=doc['doc_uuid'])

        # Determine priority label
        if doc in document_categories['high_priority']:
            priority = "**HIGH**"
        elif doc in document_categories['medium_priority']:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        print(f"| {{priority}} | {{doc['description']}} | {{doc['app_num']}} | {{doc['filing_date']}} | [Download]({{download_url}}) |")

        download_links.append({{
            'doc_info': doc,
            'download_url': download_url
        }})

    except Exception as e:
        print(f"| ERROR | {{doc['description']}} | {{doc['app_num']}} | - | Error: {{e}} |")

# PHASE 4: Text Extraction (if requested)
if "{extract_text}" == "true":
    print("\\n## TEXT EXTRACTION ANALYSIS\\n")

    extraction_results = {{
        'successful': 0,
        'failed': 0,
        'total_cost': 0.0,
        'extracted_documents': []
    }}

    # Extract text from high priority documents only (limit to 10)
    high_priority_docs = document_categories['high_priority'][:10]

    for doc in high_priority_docs:
        try:
            print(f"\\n**Extracting:** {{doc['description']}}...")

            content_result = fpd_get_document_content(
                document_uuid=doc['doc_uuid']
            )

            extracted_text = content_result.get('content', '')
            extraction_method = content_result.get('extraction_method', 'unknown')
            cost = content_result.get('cost', 0.0)

            if extracted_text:
                extraction_results['successful'] += 1
                extraction_results['total_cost'] += cost
                extraction_results['extracted_documents'].append({{
                    'description': doc['description'],
                    'method': extraction_method,
                    'cost': cost,
                    'text_length': len(extracted_text),
                    'preview': extracted_text[:500]  # First 500 chars
                }})

                print(f"  ✅ Success ({{extraction_method}}) - {{len(extracted_text)}} chars")
                if cost > 0:
                    print(f"  💰 Cost: ${{cost:.4f}}")

            else:
                extraction_results['failed'] += 1
                print(f"  ⚠️ No text extracted")

        except Exception as e:
            extraction_results['failed'] += 1
            print(f"  ❌ Error: {{e}}")

    # Summary
    print(f"\\n### TEXT EXTRACTION SUMMARY\\n")
    print(f"- **Successful Extractions:** {{extraction_results['successful']}}")
    print(f"- **Failed Extractions:** {{extraction_results['failed']}}")
    print(f"- **Total Cost:** ${{extraction_results['total_cost']:.4f}}\\n")

    # Show previews of extracted content
    if extraction_results['extracted_documents']:
        print("### DOCUMENT TEXT PREVIEWS\\n")
        for ext_doc in extraction_results['extracted_documents'][:5]:
            print(f"**{{ext_doc['description']}}** ({{ext_doc['method']}}, {{ext_doc['text_length']}} chars)")
            print(f"```")
            print(ext_doc['preview'])
            print(f"...\\n```\\n")

# PHASE 5: Summary and Next Steps
print("\\n## RESEARCH PACKAGE SUMMARY\\n")
print(f"**Total Petitions Processed:** {{len(petitions_to_process)}}")
print(f"**High Priority Documents:** {{len(document_categories['high_priority'])}}")
print(f"**Medium Priority Documents:** {{len(document_categories['medium_priority'])}}")
print(f"**Low Priority Documents:** {{len(document_categories['low_priority'])}}")
print(f"**Documents with Download Links:** {{len(download_links)}}\\n")

print("### RECOMMENDED NEXT STEPS\\n")
print("1. Download high-priority documents for detailed review")
print("2. Use text extraction for key petition/decision documents")
print("3. Cross-reference with PFW for prosecution context")
if "{application_number}":
    print(f"4. Analyze prosecution history for Application {application_number} using PFW MCP")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Limit petition processing to 10 petitions maximum when searching by application_number
- Document download link generation limited to 50 documents to prevent context explosion
- Text extraction limited to 10 high-priority documents maximum
- Text extraction has costs for OCR processing - use sparingly for scanned documents
- Use document_priority='high' for focused analysis to minimize context usage
- Always check extraction costs before processing large document sets

## DOCUMENT COLLECTION STRATEGY

### Step 1: Petition Identification

If petition_identifier provided:
- Use `fpd_get_petition_details(petition_id="{petition_identifier}", include_documents=True)`
- Direct access to specific petition and all associated documents

If application_number provided:
- Use `fpd_search_petitions_by_application(application_number="{application_number}", include_documents=False)`
- Find all petitions for the application
- Then use `fpd_get_petition_details` for each petition of interest

### Step 2: Document Prioritization

** HIGH PRIORITY (Always Include):**
- Petition filing documents
- Decision letters from Director
- Supporting legal briefs and arguments
- Office correspondence related to petition

**[PENDING] MEDIUM PRIORITY (Include if Comprehensive):**
- Examiner responses and justifications
- Applicant reply briefs
- Administrative documents
- Related prosecution correspondence

**[OK] LOW PRIORITY (Include if Complete Package):**
- Form documents and administrative notices
- Routine correspondence
- Duplicate or superseded documents

### Step 3: Document Access and Organization

For each selected document, use `fpd_get_document_download` to generate:
- Browser-accessible download URLs
- Enhanced filename format: `PET-[date]_APP-[app_number]_[doc_type]_[filename].pdf`
- Chronological organization by petition filing date

## TEXT EXTRACTION WORKFLOW (if extract_text=true)

For high-priority documents, use `fpd_get_document_content`:
- Intelligent hybrid extraction: PyPDF2 first (free), Mistral OCR fallback (paid)
- Cost optimization: Only pay for OCR when needed
- Quality detection: Automatic method selection
- Transparent reporting: Shows extraction method and costs

### Legal Content Analysis Framework:

** Case Summary Elements:**
- Petition type and legal grounds
- Key issues and arguments presented
- Director's decision and reasoning
- Precedential value and implications

** Legal Strategy Insights:**
- Successful argument patterns
- Common rejection reasons
- Procedural best practices
- Precedent and citation analysis

** Litigation Relevance:**
- Examination quality indicators
- Prosecution strategy effectiveness
- Potential appeal grounds
- PTAB vulnerability correlation

## CROSS-MCP INTEGRATION OPPORTUNITIES

** Patent File Wrapper Integration:**
- Application {application_number} prosecution history
- Examiner interaction patterns
- Office action and response correlation with petition

** PTAB Integration (if granted patent):**
- Patent challenge assessment
- Petition red flags -> PTAB vulnerability correlation
- Post-grant challenge strategy implications

## EXPECTED DELIVERABLES

Organized Document Package:
- Chronologically organized petition documents
- Enhanced filename structure for legal filing systems
- Priority-based document classification
- Browser-accessible download links

Legal Analysis Summary (if text extraction enabled):
- Petition argument analysis and effectiveness
- Director's reasoning and precedent citations
- Key factual findings and legal conclusions
- Strategic insights for similar cases

Integration Opportunities:
- Cross-MCP workflow recommendations
- Related prosecution analysis suggestions
- PTAB vulnerability assessment links
- Portfolio strategy implications

Cost and Efficiency Metrics:
- Document extraction costs (if OCR used)
- Processing time and resource requirements
- Recommended workflow optimizations

## DOCUMENT EXTRACTION COST ESTIMATE

Free Text-Based PDFs:
- PyPDF2 extraction: $0.00 per document
- Instant processing

Scanned Documents (OCR Required):
- Mistral OCR: ~$0.001 per page
- Quality assured text extraction
- Automatic fallback when PyPDF2 fails

** SMART COST MANAGEMENT**: The system automatically tries free extraction first and only uses paid OCR when necessary, optimizing costs while ensuring complete text access."""


# =============================================================================
# CROSS-MCP INTEGRATION PROMPT TEMPLATES
# =============================================================================

