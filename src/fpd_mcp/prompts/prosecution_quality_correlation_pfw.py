"""Prosecution Quality Correlation - Correlate examiner patterns with petition frequency"""

from ._classification import DECISION_NOTE
from ._flags import flag


async def prosecution_quality_correlation_prompt(
    art_unit: str = "",
    examiner_name: str = "",
    date_range_start: str = "",
    date_range_end: str = "",
    statistical_analysis: str = "true"
) -> str:
    """
    Prosecution quality correlation analysis between examiner patterns and petition frequency.

    WARNING: DEPENDENCIES: Requires Patent File Wrapper (PFW) MCP

    Analysis criteria (at least ONE required):
    - art_unit: Art unit number for group analysis (e.g., "2128")
    - examiner_name: Specific examiner for individual analysis (e.g., "John Smith")

    Analysis options:
    - date_range_start: Analysis start date (YYYY-MM-DD format, e.g., "2020-01-01")
    - date_range_end: Analysis end date (YYYY-MM-DD format, e.g., "2024-12-31")
    - statistical_analysis: Include statistical correlation metrics (true/false) [DEFAULT: true]

    Returns comprehensive correlation analysis between prosecution patterns and petition frequency for quality assessment.
    """
    # R-2: accept any encoding a caller sends (True, 'True', 'yes',
    # '1'); the emitted template compares the normalized literal.
    statistical_analysis = flag(statistical_analysis)

    return f"""Prosecution Quality Correlation Analysis - Examiner Performance Assessment

{DECISION_NOTE}

Inputs Provided:
- Art Unit: "{art_unit}"
- Examiner Name: "{examiner_name}"
- Date Range: "{date_range_start}" to "{date_range_end}"
- Statistical Analysis: {statistical_analysis}

WARNING: DEPENDENCIES: This workflow requires Patent File Wrapper (PFW) MCP for comprehensive prosecution data analysis.

 ATTORNEY WORKFLOW: Advanced correlation analysis between prosecution patterns and petition frequency to identify quality indicators and systemic issues.

## COMPLETE IMPLEMENTATION WITH ERROR HANDLING

```python
# PHASE 1: Analysis Scope and Data Collection
print(f"## PROSECUTION QUALITY CORRELATION ANALYSIS")
print(f"**Art Unit:** {art_unit or 'Not specified'}")
print(f"**Examiner Name:** {examiner_name or 'Not specified'}")
print(f"**Date Range:** {date_range_start or 'Default'} to {date_range_end or 'Present'}")
print(f"**Statistical Analysis:** {statistical_analysis}\\n")

from datetime import datetime, timedelta

# Set date range
date_start = "{date_range_start}" or (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')  # 2 years default
date_end = "{date_range_end}" or datetime.now().strftime('%Y-%m-%d')

# PHASE 1: Get prosecution data from PFW
prosecution_data = []

try:
    print("**PHASE 1: Collecting Prosecution Data (PFW MCP)...**\\n")

    if "{examiner_name}":
        # Individual examiner analysis
        pfw_results = PFW_search_applications_minimal(
            examiner_name="{examiner_name}",
            filing_date_start=date_start,
            fields=['applicationNumberText', 'patentNumber',
                    'applicationMetaData.examinerNameText',
                    'applicationMetaData.groupArtUnitNumber',
                    'applicationMetaData.filingDate'],
            limit=100
        )
        analysis_scope = "individual_examiner"
        print(f"✅ **Analyzing Examiner:** {examiner_name}")

    elif "{art_unit}":
        # Art unit group analysis
        pfw_results = PFW_search_applications_minimal(
            art_unit="{art_unit}",
            filing_date_start=date_start,
            fields=['applicationNumberText', 'patentNumber',
                    'applicationMetaData.examinerNameText',
                    'applicationMetaData.groupArtUnitNumber',
                    'applicationMetaData.filingDate'],
            limit=100
        )
        analysis_scope = "art_unit_group"
        print(f"✅ **Analyzing Art Unit:** {art_unit}")

    prosecution_data = pfw_results.get('patents', [])
    total_apps = len(prosecution_data)
    print(f"**Total Applications Found:** {{total_apps}}\\n")

except Exception as e:
    print(f"❌ **PFW MCP Error:** {{e}}")
    print("**Cannot proceed without PFW MCP - this workflow requires prosecution data**\\n")
    raise

# PHASE 2: Petition Frequency Analysis (FPD MCP)
print("**PHASE 2: Analyzing Petition Frequency...**\\n")

petition_correlation = {{
    'apps_with_petitions': 0,
    'total_petitions': 0,
    'petition_types': {{
        'revival': 0,
        'examiner_dispute': 0,
        'restriction': 0,
        'other': 0
    }},
    'decisions': {{
        'granted': 0,
        'denied': 0
    }},
    'high_petition_apps': []
}}

# Analyze petition data for each application
for app in prosecution_data[:50]:  # Limit to 50 to prevent context explosion
    app_num = app.get('applicationNumberText')

    try:
        petitions = FPD_Search_petitions_by_application(
            application_number=app_num,
            include_documents=False
        )

        petition_count = len(petitions.get('results', []))
        if petition_count > 0:
            petition_correlation['apps_with_petitions'] += 1
            petition_correlation['total_petitions'] += petition_count

            # Categorize petitions
            for petition in petitions.get('results', []):
                petition_id = petition.get('petitionDecisionRecordIdentifier')
                decision = petition.get('decisionTypeCodeDescriptionText', '')

                # Track decisions
                if decision == 'GRANTED':
                    petition_correlation['decisions']['granted'] += 1
                elif decision == 'DENIED':
                    petition_correlation['decisions']['denied'] += 1

                # Get petition type
                try:
                    details = FPD_Get_petition_details(petition_id=petition_id, include_documents=False)
                    rules = details.get('ruleBag', [])

                    if any('1.137' in rule for rule in rules):
                        petition_correlation['petition_types']['revival'] += 1
                    elif any('1.181' in rule for rule in rules):
                        petition_correlation['petition_types']['examiner_dispute'] += 1
                    elif any('1.182' in rule for rule in rules):
                        petition_correlation['petition_types']['restriction'] += 1
                    else:
                        petition_correlation['petition_types']['other'] += 1
                except:
                    pass

            # Track high petition applications
            if petition_count >= 2:
                petition_correlation['high_petition_apps'].append({{
                    'app_num': app_num,
                    'petition_count': petition_count,
                    'examiner': app.get('applicationMetaData', {{}}).get('examinerNameText', 'N/A')
                }})

    except:
        continue

print(f"✅ **Petition Analysis Complete**")
print(f"- Applications Analyzed: {{len(prosecution_data[:50])}}")
print(f"- Applications with Petitions: {{petition_correlation['apps_with_petitions']}}")
print(f"- Total Petitions: {{petition_correlation['total_petitions']}}\\n")

# PHASE 3: Statistical Correlation Calculation
if "{statistical_analysis}" == "true":
    print("**PHASE 3: Calculating Statistical Correlations...**\\n")

    # Calculate key metrics
    petition_rate = (petition_correlation['apps_with_petitions'] / total_apps * 100) if total_apps > 0 else 0
    examiner_dispute_rate = (petition_correlation['petition_types']['examiner_dispute'] / petition_correlation['total_petitions'] * 100) if petition_correlation['total_petitions'] > 0 else 0
    denial_rate = (petition_correlation['decisions']['denied'] / petition_correlation['total_petitions'] * 100) if petition_correlation['total_petitions'] > 0 else 0

    # Quality score calculation
    quality_score = 100
    quality_score -= petition_rate * 2  # Petition frequency penalty
    quality_score -= examiner_dispute_rate * 1.5  # Dispute penalty
    quality_score -= denial_rate * 0.5  # Denial penalty

    if quality_score >= 80:
        quality_rating = "HIGH QUALITY ✅"
    elif quality_score >= 60:
        quality_rating = "MODERATE QUALITY ⚠️"
    else:
        quality_rating = "QUALITY CONCERNS 🚨"

    print(f"**Quality Score:** {{quality_score:.1f}}/100 ({{quality_rating}})")
    print(f"**Petition Rate:** {{petition_rate:.1f}}%")
    print(f"**Examiner Dispute Rate:** {{examiner_dispute_rate:.1f}}%")
    print(f"**Denial Rate:** {{denial_rate:.1f}}%\\n")

# PHASE 4: PRESENTATION - Correlation Report
print("\\n## PROSECUTION-PETITION CORRELATION REPORT\\n")

# Overview Table
print("### OVERVIEW\\n")
print(f"**Analysis Scope:** {{analysis_scope}}")
print(f"**Date Range:** {{date_start}} to {{date_end}}")
print(f"**Total Applications:** {{total_apps}}\\n")

# Correlation Metrics Table
print("### CORRELATION METRICS\\n")
print("| Metric | Value | Baseline | Assessment |")
print("|--------|-------|----------|------------|")
print(f"| Petition Rate | {{petition_rate:.1f}}% | compute it, see below | pending a baseline |")
print(f"| Examiner Disputes | {{petition_correlation['petition_types']['examiner_dispute']}} ({{examiner_dispute_rate:.1f}}% of petitions) | compute it, see below | pending a baseline |")
print(f"| Revival Petitions | {{petition_correlation['petition_types']['revival']}} | compute it, see below | pending a baseline |")
print(f"| Denied Petitions | {{petition_correlation['decisions']['denied']}} ({{denial_rate:.1f}}%) | none applies | not a quality metric |")

print("\\n**No fixed bands.** This table used to print benchmark percentages")
print("for each row that were never measured against this corpus, including")
print("one for the denial rate. Observed art unit petition rates run far")
print("below one percent, so those bands mark everything 'good' and teach a")
print("reader to expect numbers two orders of magnitude off. Run the same")
print("calculation over two or three comparable art units in the same")
print("technology center and date window, report against that, and say so; or")
print("report the raw counts and state that no baseline was established.")
print("The denial rate is not a quality metric: see the reading rule above.\\n")

# High Petition Applications
if petition_correlation['high_petition_apps']:
    print("\\n### 🚨 HIGH PETITION FREQUENCY APPLICATIONS\\n")
    print("| App Number | Petition Count | Examiner |")
    print("|------------|----------------|----------|")
    for app in petition_correlation['high_petition_apps'][:10]:
        print(f"| {{app['app_num']}} | {{app['petition_count']}} | {{app['examiner']}} |")

# RECOMMENDED ACTIONS
print("\\n### RECOMMENDED ACTIONS\\n")

if quality_score < 60:
    print("**IMMEDIATE PRIORITY:**")
    print("1. 🚨 Review examiner training and quality protocols")
    print("2. 🚨 Investigate high-petition applications for systemic issues")
    print("3. 🚨 Implement enhanced communication protocols with applicants")
    print("4. 🚨 Conduct detailed case-by-case review of examiner disputes\\n")
elif quality_score < 80:
    print("**MODERATE PRIORITY:**")
    print("1. ⚠️ Monitor petition trends for deterioration")
    print("2. ⚠️ Provide targeted training on complex cases")
    print("3. ⚠️ Review and update examination procedures\\n")
else:
    print("**MAINTENANCE MODE:**")
    print("1. ✅ Continue current practices")
    print("2. ✅ Document best practices for replication")
    print("3. ✅ Monitor for emerging patterns\\n")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Limit prosecution data collection to 100 applications maximum
- Petition analysis limited to first 50 applications to prevent context explosion
- Requires both PFW and FPD MCPs - statistical analysis requires dual data sources
- Use date_range filters to focus analysis on relevant time periods
- Small samples: report the application count behind every rate. No sample size
  here was chosen by a power calculation, so do not describe any result as
  statistically significant
- Results are correlative, not causative - requires attorney judgment for interpretation

## PHASE 1: Analysis Scope Definition

Step 1: Determine analysis strategy:
```python
if examiner_name:
    analysis_scope = "individual_examiner"
    pfw_query = 'examinerNameText:"{examiner_name}"'
    comparison_baseline = "art_unit_average"

elif art_unit:
    analysis_scope = "art_unit_group"
    pfw_query = 'groupArtUnitNumber:{art_unit}'
    comparison_baseline = "technology_center_average"
```

Date Range Settings:
- 1_year: 2023-01-01 to 2024-12-31
- 2_years: 2022-01-01 to 2024-12-31
- 3_years: 2021-01-01 to 2024-12-31
- 5_years: 2019-01-01 to 2024-12-31

Step 2: Validate analysis feasibility:
- Sample size: record how many applications each rate is computed over and
  report it alongside the rate; there is no minimum that makes a result a test
- Data availability in both PFW and FPD systems
- Time range coverage and data completeness

## PHASE 2: Prosecution Data Collection (PFW MCP)

Step 3: Comprehensive prosecution pattern analysis using targeted fields:
```python
# CRITICAL: Use minimal search with fields parameter for efficient data retrieval
PFW_search_applications_minimal(
    query=pfw_query + ' AND filingDate:[start_date TO end_date]',
    fields=[
        'applicationNumberText',
        'applicationMetaData.examinerNameText',
        'applicationMetaData.groupArtUnitNumber',
        'applicationMetaData.filingDate',
        'patentNumber'
    ],  # Only 5 fields vs 15 standard fields (70% reduction)
    limit=200  # Can search 200 vs ~40 with standard fields
)
```

**Benefits for Correlation Analysis:**
- Standard search: 200 results × 25KB = 5MB
- Targeted fields: 200 results × 2KB = 400KB (manageable)
- Enables more data points for statistical analysis

Prosecution Performance Metrics:

** Efficiency Indicators:**
- Grant rate: (Granted / Total Applications) × 100
- Average prosecution time: Filing to grant duration
- Office action efficiency: Average OAs per granted application
- Amendment frequency: Claim changes per application

** Quality Indicators:**
- Final rejection rate: Final OAs vs total OAs
- Continuation frequency: RCE and continuation filings
- Interview utilization: Examiner interview frequency
- Citation quality: Prior art relevance and comprehensiveness

** Consistency Indicators:**
- Decision pattern consistency
- Timeline predictability
- Application complexity handling
- Applicant response accommodation

## PHASE 3: Petition Frequency Analysis (FPD MCP)

Step 4: Cross-reference prosecution with petition data:
For each application from PFW data:
```
FPD_Search_petitions_by_application(
    application_number=app_number,
    include_documents=False
)
```

Petition Pattern Classification:
- No petitions: Normal prosecution (baseline)
- Single petition: Minor procedural issue
- Multiple petitions: Systematic prosecution problems
- Red flag petitions: Denied petitions or examiner disputes

Correlation-Relevant Red Flags:
- PETITION_ON_THE_RECORD: the rule cited (37 CFR 1.137 revival, 1.181 dispute)
  is the correlation-relevant fact. The decision value is not: DENIED is the
  ordinary outcome and does not distinguish one examiner from another
- REVIVAL_PETITION: 37 CFR 1.137 (abandonment)
- EXAMINER_DISPUTE: 37 CFR 1.181 (supervisory review)

## PHASE 4: Statistical Correlation Analysis (if statistical_analysis=true)

Step 5: Calculate correlation coefficients:
- Prosecution-Petition Correlation: Pearson correlation between prosecution complexity and petition frequency
- Grant Rate-Petition Correlation: Correlation between examiner grant rates and petition rates
- Timeline-Petition Correlation: Correlation between prosecution length and petition occurrence
- Office Action-Petition Correlation: Correlation between OA count and petition frequency

Reporting the comparison honestly (no test is performed here):
- Record the sample size behind every rate and print it next to the rate
- Report the observed difference in percentage points, not as a verdict
- State explicitly that no significance test was applied, because none is
  available from these counts
- Do not print a confidence interval, a p-value or a correlation strength that
  this workflow did not compute

Step 6: Benchmarking analysis:
- Individual examiner vs art unit average
- Art unit vs technology center average
- Performance differential calculation
- Percentile ranking assessment

## PHASE 5: Pattern Recognition & Insights

Correlation Pattern Analysis:

** NEGATIVE QUALITY CORRELATIONS:**
- High office action count -> High petition frequency
- Long prosecution timelines -> More revival petitions
- Frequent amendments -> More examiner disputes
- Low grant rates -> Higher procedural petition rates

**[OK] POSITIVE QUALITY CORRELATIONS:**
- Efficient prosecution -> Lower petition frequency
- High grant rates -> Minimal procedural issues
- Consistent decision patterns -> Fewer examiner disputes
- Proactive examiner communication -> Reduced conflicts

** NEUTRAL/COMPLEX CORRELATIONS:**
- Technology complexity may drive legitimate petition frequency
- Art unit policies may influence petition patterns
- Applicant experience may affect petition necessity

## PREDICTIVE INSIGHTS AND RECOMMENDATIONS

High Petition Risk Indicators:
- Grant rate <70% compared to art unit average
- Prosecution timeline >18 months above average
- Office action count >3 per application
- Amendment frequency >2 per application

Quality Improvement Recommendations:
- Enhanced examiner training on complex cases
- Improved applicant communication protocols
- Streamlined prosecution procedures
- Regular quality control reviews

Monitoring Suggestions:
- Monthly petition rate tracking
- Quarterly grant rate analysis
- Examiner performance reviews
- Applicant feedback collection

## EXPECTED DELIVERABLES

Statistical Correlation Report:
- Observed differences with the denominators they were computed over, and an
  explicit statement that no significance test was applied
- Benchmarking analysis against peer groups
- Pattern recognition insights and trend analysis
- Predictive model for petition risk assessment

Quality Assessment Dashboard:
- Prosecution efficiency metrics and rankings
- Petition frequency analysis and categorization
- Red flag indicator tracking and alerts
- Performance improvement recommendations

Strategic Intelligence:
- Examiner and art unit optimization strategies
- Training and development recommendations
- Process improvement opportunities
- Resource allocation guidance for quality enhancement

Cross-MCP Integration Benefits:
- Complete prosecution-petition correlation visibility
- Predictive analytics for petition risk management
- Quality control insights unavailable from single data source
- Comprehensive examiner and art unit performance assessment

** ADVANCED ANALYTICS**: Statistical correlation analysis between prosecution patterns and petition frequency provides unprecedented quality insights.

** DUAL-MCP POWER**: Combining PFW prosecution data with FPD petition data reveals quality correlations impossible to detect with single data sources."""


def register(mcp):
    """Register this prompt with the given MCP server instance."""
    mcp.prompt(
        name="prosecution_quality_correlation_pfw",
        description="Correlate examiner patterns with petition frequency. At least ONE required (art_unit or examiner_name). statistical_analysis: true/false for correlation metrics. Requires PFW MCP."
    )(prosecution_quality_correlation_prompt)
