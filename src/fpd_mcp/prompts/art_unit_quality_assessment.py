"""Art Unit Quality Assessment - Evaluate prosecution quality via petition patterns"""

from . import mcp


@mcp.prompt(
    name="art_unit_quality_assessment",
    description="Evaluate art unit prosecution quality via petition patterns. art_unit* (required). comparison_analysis: true/false for technology center comparison."
)
async def art_unit_quality_assessment_prompt(
    art_unit: str,
    date_range_start: str = "",
    date_range_end: str = "",
    comparison_analysis: str = "true"
) -> str:
    """
    Art unit quality assessment through petition pattern analysis.

    Required input:
    - art_unit: Art unit number to analyze (e.g., "2128", "1650")

    Optional parameters:
    - date_range_start: Analysis start date (YYYY-MM-DD format, e.g., "2020-01-01")
    - date_range_end: Analysis end date (YYYY-MM-DD format, e.g., "2024-12-31")
    - comparison_analysis: Include technology center comparison (true/false) [DEFAULT: true]

    Returns comprehensive art unit quality metrics including examiner patterns and prosecution efficiency indicators.
    """
    return f"""Art Unit Quality Assessment - Prosecution Pattern Analysis

Inputs Provided:
- Art Unit: "{art_unit}"
- Date Range: "{date_range_start}" to "{date_range_end}"
- Comparison Analysis: {comparison_analysis}

 ATTORNEY WORKFLOW: Systematic art unit quality evaluation for prosecution strategy and examiner assessment.

## COMPLETE IMPLEMENTATION WITH ERROR HANDLING

```python
# PHASE 1: Data Collection
date_range_filter = ""
if "{date_range_start}" and "{date_range_end}":
    date_range_filter = f"{date_range_start}:{date_range_end}"
else:
    # Default to last 5 years
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=1825)).strftime('%Y-%m-%d')
    date_range_filter = f"{{start_date}}:{{end_date}}"

print(f"**Analyzing Art Unit:** {art_unit}")
print(f"**Date Range:** {{date_range_filter}}\\n")

# Search for all petitions in this art unit
petitions = fpd_search_petitions_by_art_unit(
    art_unit="{art_unit}",
    date_range=date_range_filter,
    limit=200  # Comprehensive analysis
)

total_petitions = len(petitions.get('results', []))

# PHASE 2: Categorize Petitions by Type
petition_categories = {{
    'revival_37cfr1137': {{'count': 0, 'granted': 0, 'denied': 0}},
    'examiner_dispute_37cfr1181': {{'count': 0, 'granted': 0, 'denied': 0}},
    'restriction_37cfr1182': {{'count': 0, 'granted': 0, 'denied': 0}},
    'other': {{'count': 0, 'granted': 0, 'denied': 0}}
}}

examiner_petition_map = {{}}  # Track which examiners have most petitions

for petition in petitions.get('results', []):
    petition_id = petition.get('petitionDecisionRecordIdentifier')
    decision = petition.get('decisionTypeCodeDescriptionText', '')
    app_num = petition.get('applicationNumberText')

    try:
        # Get detailed petition info for categorization
        details = fpd_get_petition_details(petition_id=petition_id, include_documents=False)
        rules = details.get('ruleBag', [])

        # Categorize by CFR rule
        is_revival = any('1.137' in rule for rule in rules)
        is_examiner_dispute = any('1.181' in rule for rule in rules)
        is_restriction = any('1.182' in rule for rule in rules)

        if is_revival:
            petition_categories['revival_37cfr1137']['count'] += 1
            if decision == 'GRANTED':
                petition_categories['revival_37cfr1137']['granted'] += 1
            elif decision == 'DENIED':
                petition_categories['revival_37cfr1137']['denied'] += 1
        elif is_examiner_dispute:
            petition_categories['examiner_dispute_37cfr1181']['count'] += 1
            if decision == 'GRANTED':
                petition_categories['examiner_dispute_37cfr1181']['granted'] += 1
            elif decision == 'DENIED':
                petition_categories['examiner_dispute_37cfr1181']['denied'] += 1
        elif is_restriction:
            petition_categories['restriction_37cfr1182']['count'] += 1
            if decision == 'GRANTED':
                petition_categories['restriction_37cfr1182']['granted'] += 1
            elif decision == 'DENIED':
                petition_categories['restriction_37cfr1182']['denied'] += 1
        else:
            petition_categories['other']['count'] += 1

    except Exception as e:
        # If can't get details, skip categorization
        petition_categories['other']['count'] += 1
        continue

# PHASE 3: Cross-MCP Integration - Get Total Applications for Art Unit
total_applications = 0
examiner_list = []

if "{comparison_analysis}" == "true":
    try:
        # Get sample of applications from this art unit via PFW
        pfw_apps = pfw_search_applications_minimal(
            art_unit="{art_unit}",
            fields=['applicationNumberText', 'applicationMetaData.examinerNameText'],
            limit=200
        )

        total_applications = len(pfw_apps.get('patents', []))

        # Extract unique examiners
        for app in pfw_apps.get('patents', []):
            examiner = app.get('applicationMetaData', {{}}).get('examinerNameText')
            if examiner and examiner not in examiner_list:
                examiner_list.append(examiner)

    except Exception as e:
        print(f"**Note:** PFW MCP unavailable for application count: {{e}}")
        total_applications = total_petitions * 20  # Rough estimate

# PHASE 4: Calculate Quality Metrics
petition_frequency_rate = (total_petitions / total_applications * 100) if total_applications > 0 else 0

examiner_dispute_rate = (petition_categories['examiner_dispute_37cfr1181']['count'] / total_petitions * 100) if total_petitions > 0 else 0

revival_success_rate = (petition_categories['revival_37cfr1137']['granted'] / petition_categories['revival_37cfr1137']['count'] * 100) if petition_categories['revival_37cfr1137']['count'] > 0 else 0

# PHASE 5: Quality Assessment
if petition_frequency_rate < 5 and examiner_dispute_rate < 20 and revival_success_rate > 70:
    quality_rating = "HIGH QUALITY ✅"
    quality_score = 90
elif petition_frequency_rate < 10 and examiner_dispute_rate < 40:
    quality_rating = "MODERATE QUALITY ⚠️"
    quality_score = 65
else:
    quality_rating = "QUALITY CONCERNS 🚨"
    quality_score = 40

# PHASE 6: PRESENTATION - Format results
print("\\n## ART UNIT QUALITY ASSESSMENT SUMMARY\\n")
print(f"**Art Unit:** {art_unit}")
print(f"**Quality Rating:** {{quality_rating}} (Score: {{quality_score}}/100)")
print(f"**Analysis Period:** {{date_range_filter}}\\n")

print("### KEY METRICS\\n")
print(f"- **Total Petitions:** {{total_petitions}}")
print(f"- **Total Applications (Estimated):** {{total_applications}}")
print(f"- **Petition Frequency Rate:** {{petition_frequency_rate:.1f}}%")
print(f"  - Target: <5% (excellent), 5-10% (good), >10% (concerns)")
print(f"- **Examiner Dispute Rate:** {{examiner_dispute_rate:.1f}}%")
print(f"  - Target: <20% (excellent), 20-40% (acceptable), >40% (high conflict)")
print(f"- **Revival Success Rate:** {{revival_success_rate:.1f}}%")
print(f"  - Target: >70% (good), 50-70% (moderate), <50% (systemic issues)\\n")

# PETITION TYPE BREAKDOWN TABLE
print("### PETITION TYPE BREAKDOWN\\n")
print("| Type | Count | Granted | Denied | Success Rate |")
print("|------|-------|---------|--------|--------------|")

for category, data in petition_categories.items():
    if data['count'] > 0:
        success_rate = (data['granted'] / data['count'] * 100) if data['count'] > 0 else 0
        category_name = category.replace('_', ' ').title()
        print(f"| {{category_name}} | {{data['count']}} | {{data['granted']}} | {{data['denied']}} | {{success_rate:.1f}}% |")

print("\\n### QUALITY INDICATORS\\n")

if petition_frequency_rate > 10:
    print("🚨 **HIGH PETITION RATE** - Indicates potential examination quality or process issues")
if examiner_dispute_rate > 40:
    print("🚨 **HIGH EXAMINER DISPUTE RATE** - Suggests communication or quality problems")
if revival_success_rate < 50:
    print("🚨 **LOW REVIVAL SUCCESS RATE** - Systemic abandonment/procedural issues")

if quality_score >= 90:
    print("✅ **EXCELLENT ART UNIT PERFORMANCE** - Minimal petition activity, high quality")
elif quality_score >= 65:
    print("⚠️ **MODERATE PERFORMANCE** - Some improvement opportunities exist")
else:
    print("🚨 **QUALITY CONCERNS** - Process improvement and training recommended")

print("\\n### RECOMMENDED ACTIONS\\n")

if quality_score < 65:
    print("1. **Immediate:** Review examiner training protocols")
    print("2. **Short-term:** Analyze petition patterns by individual examiner")
    print("3. **Long-term:** Implement quality improvement initiatives")
else:
    print("1. Monitor trends for any degradation")
    print("2. Document best practices for other art units")
    print("3. Continue current quality standards")
```

## CRITICAL SAFETY RAILS

**⚠️ IMPORTANT:**
- Limit petition searches to 200 results maximum to prevent context explosion
- Always use date_range filters for temporal analysis
- If total_petitions > 200, narrow date range or analyze in segments
- Use include_documents=False for petition_details to save context

## CROSS-MCP INTEGRATION

**With PFW MCP (Enhanced Examiner Analysis):**
```python
# Map petitions to specific examiners
for examiner in examiner_list:
    examiner_petitions = [p for p in petitions['results']
                          if p.get('examinerName') == examiner]
    if len(examiner_petitions) > 5:
        print(f"⚠️ Examiner {{examiner}}: {{len(examiner_petitions)}} petitions - High dispute rate")
```

**With PTAB MCP (Post-Grant Correlation):**
```python
# Check if high petition rate correlates with PTAB challenges
try:
    granted_patents = [p.get('patentNumber') for p in petitions['results']
                      if p.get('patentNumber')]
    ptab_challenges = 0
    for patent_num in granted_patents[:20]:  # Sample check
        challenges = search_trials_minimal(patent_number=patent_num)
        if challenges and len(challenges.get('results', [])) > 0:
            ptab_challenges += 1

    if ptab_challenges > 5:
        print(f"🚨 CORRELATION ALERT: {{ptab_challenges}} PTAB challenges detected")
        print("   High petition rate + high PTAB challenges = Examination quality issues")
except:
    pass  # PTAB MCP may not be available
```

**EXPECTED OUTPUT FORMAT:** Comprehensive quality report with metrics table, quality rating, petition breakdown, and actionable recommendations."""
