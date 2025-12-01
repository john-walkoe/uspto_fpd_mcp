# Field Customization Guide

This document provides comprehensive guidance on customizing field sets for the USPTO Final Petition Decisions MCP Server to optimize context usage and workflow efficiency.

## 🔧 Field Customization

### User-Configurable Field Sets

The MCP server supports user-customizable field sets through YAML configuration at the project root. You can modify field sets that the minimal and balanced searches bring back without changing any code!

**Configuration file:** `field_configs.yaml` (in project root)

### Easy Customization Process

1. **Open** `field_configs.yaml` in the project root directory
2. **Uncomment fields** you want by removing the `#` symbol
3. **Save the file** - changes take effect on next Claude Desktop restart
4. **Use the simplified tools** with your custom field selections

### Available Field Sets (Progressive Workflow)

- **`petitions_minimal`** - Ultra-minimal for petition searches: **8 essential fields** for high-volume discovery (50-100 results)
- **`petitions_balanced`** - Comprehensive petition analysis: **18 key fields** for detailed petition analysis and cross-MCP integration

### Professional Field Categories Available

- **Critical Dates**: `petitionMailDate`, `decisionDate`
- **Cross-Reference Keys**: `applicationNumberText`, `patentNumber`, `groupArtUnitNumber`
- **Decision Details**: `decisionTypeCodeDescriptionText`, `finalDecidingOfficeName`
- **Petition Metadata**: `decisionPetitionTypeCode`, `petitionIssueConsideredTextBag`, `ruleBag`, `statuteBag`
- **Prosecution Context**: `prosecutionStatusCodeDescriptionText`, `technologyCenter`
- **Entity Information**: `firstApplicantName`, `businessEntityStatusCategory`
- **Technical Details**: `inventionTitle`

### Example Customization

**File: `field_configs.yaml`**
```yaml
predefined_sets:
  petitions_minimal:
    description: "Ultra-minimal fields for petition searches (95-99% context reduction)"
    fields:
      # === CORE REQUIRED FIELDS ===
      - petitionDecisionRecordIdentifier           # Unique petition UUID (required)
      - applicationNumberText                      # Links to PFW MCP
      - patentNumber                               # Links to PTAB MCP (if granted)
      - firstApplicantName                         # Petitioner/applicant name
      - decisionTypeCodeDescriptionText            # GRANTED/DENIED/DISMISSED
      - petitionMailDate                           # Filed date
      - decisionDate                               # Decided date
      - finalDecidingOfficeName                    # Deciding office
      # ... 30+ more organized field options

  petitions_balanced:
    description: "Key fields for petition searches (80-88% context reduction)"
    fields:
      # === BALANCED FIELDS FOR ADDITIONAL INFO AND CROSS REFERENCE WITH OTHER USPTO MCPs ===
      - petitionDecisionRecordIdentifier           # Unique petition UUID (required)
      - applicationNumberText                      # Links to PFW MCP
      - patentNumber                               # Links to PTAB MCP (if granted)
      - firstApplicantName                         # Petitioner/applicant name
      - decisionTypeCodeDescriptionText            # GRANTED/DENIED/DISMISSED
      - petitionMailDate                           # Filed date
      - decisionDate                               # Decided date
      - finalDecidingOfficeName                    # Deciding office
      - decisionPetitionTypeCode                   # Petition type code
      - decisionPetitionTypeCodeDescriptionText    # Petition type description
      - groupArtUnitNumber                         # Art unit (→ PFW cross-ref)
      - technologyCenter                           # Technology center context
      - prosecutionStatusCodeDescriptionText       # Prosecution status
      - petitionIssueConsideredTextBag            # Issues raised (array)
      - ruleBag                                    # CFR rules cited (array)
      - statuteBag                                 # Statutes cited (array)
      - businessEntityStatusCategory              # Entity status
      - inventionTitle                             # Patent/application title
      # ... additional field categories organized below
```

### Complete Field Categories in field_configs.yaml

The `field_configs.yaml` file contains professional petition analysis fields organized into the following categories:

#### Core Required Fields
- `petitionDecisionRecordIdentifier` - Unique petition UUID (always required)
- `applicationNumberText` - Application number for PFW cross-reference
- `patentNumber` - Patent number for PTAB cross-reference (if granted)

#### Petition Decision Details
- `decisionTypeCodeDescriptionText` - GRANTED/DENIED/DISMISSED
- `finalDecidingOfficeName` - Deciding office/authority
- `petitionMailDate` - Petition filing date
- `decisionDate` - Decision date

#### Petition Type and Legal Framework
- `decisionPetitionTypeCode` - Petition type code
- `decisionPetitionTypeCodeDescriptionText` - Human-readable petition type
- `petitionIssueConsideredTextBag` - Issues raised in petition (array)
- `ruleBag` - CFR rules cited (array)
- `statuteBag` - Statutes cited (array)

#### Cross-Reference Fields for Multi-MCP Integration
- `applicationNumberText` - Primary key linking to PFW prosecution
- `patentNumber` - Secondary key linking to PTAB challenges
- `groupArtUnitNumber` - Art unit analysis across MCPs
- `firstApplicantName` - Entity matching across MCPs

#### Prosecution and Technical Context
- `prosecutionStatusCodeDescriptionText` - Current prosecution status
- `technologyCenter` - USPTO technology center
- `inventionTitle` - Patent/application title
- `businessEntityStatusCategory` - Entity status (large/small/micro)

#### Critical Dates for Analysis
- `petitionMailDate` - Petition filing date
- `decisionDate` - Decision date
- `petitionReviewCompletionDate` - Review completion date

### Context Reduction Strategies

#### Token Efficiency by Field Set

| Field Set | Field Count | Token Usage (50 results) | Reduction | Use Case |
|-----------|------------|--------------------------|-----------|----------|
| **Minimal (default)** | 8 | ~10KB | 95-99% | Discovery, red flag identification |
| **Balanced (default)** | 18 | ~25KB | 80-88% | Analysis, cross-MCP integration |
| **Full (never recommended)** | 30+ | ~200KB+ | 0% | **AVOID - causes token explosion** |

#### Progressive Workflow Design

**Stage 1: Discovery (Minimal)**
- Use 8-field minimal set for high-volume petition discovery
- Focus on essential fields: UUID, application number, decision type, dates
- Ideal for identifying patterns and red flags across large datasets

**Stage 2: Analysis (Balanced)**
- Use 18-field balanced set for detailed analysis
- Include petition type, legal citations, prosecution context
- Optimal for cross-MCP integration and comprehensive assessment

**Stage 3: Document Extraction (Targeted)**
- Use `fpd_get_petition_details` only for selected petitions
- Include document bag only when document analysis is required
- Strategic approach to minimize context usage and costs

### Field Selection by Use Case

#### Red Flag Identification Workflow
```yaml
# Focus on decision outcomes and petition types
fields: ['petitionDecisionRecordIdentifier', 'applicationNumberText', 'decisionTypeCodeDescriptionText', 'decisionPetitionTypeCode', 'petitionMailDate']
# Purpose: Identify denied petitions, revival petitions, examiner disputes
```

#### Cross-MCP Integration Workflow
```yaml
# Include all cross-reference fields for PFW and PTAB linking
fields: ['petitionDecisionRecordIdentifier', 'applicationNumberText', 'patentNumber', 'groupArtUnitNumber', 'firstApplicantName', 'decisionTypeCodeDescriptionText']
# Purpose: Enable seamless cross-MCP analysis
```

#### Art Unit Quality Assessment
```yaml
# Focus on art unit and examiner-related fields
fields: ['applicationNumberText', 'groupArtUnitNumber', 'decisionTypeCodeDescriptionText', 'petitionMailDate', 'decisionPetitionTypeCode']
# Purpose: Analyze art unit petition patterns and quality metrics
```

#### Legal Research Workflow
```yaml
# Include legal framework fields for Director reasoning analysis
fields: ['petitionDecisionRecordIdentifier', 'ruleBag', 'statuteBag', 'petitionIssueConsideredTextBag', 'decisionTypeCodeDescriptionText']
# Purpose: Research legal precedents and Director's reasoning patterns
```

### Best Practices for Field Customization

#### Progressive Workflow Design

1. **Start Minimal**: Use 8-field preset for discovery (95-99% reduction)
2. **User Selection**: Present results for user/attorney to choose relevant petitions
3. **Targeted Analysis**: Use balanced preset for detailed analysis of selected petitions
4. **Document Extraction**: Use targeted document tools only when needed

#### Token Budget Management

**High-Volume Workflows (100+ results)**:
- Use minimal mode (8 fields)
- Extract only essential fields for initial filtering
- Progress to detailed analysis only for selected results

**Analysis Workflows (10-20 results)**:
- Use balanced preset for comprehensive metadata
- Include legal citations and cross-reference fields
- Add prosecution context for quality assessment

**Cross-MCP Integration**:
- Use balanced preset to include cross-reference fields
- Include `applicationNumberText`, `patentNumber`, `groupArtUnitNumber`
- Add `firstApplicantName` for entity matching across MCPs

#### Common Field Selection Patterns

**Petition Red Flag Analysis**:
```yaml
fields: ['petitionDecisionRecordIdentifier', 'applicationNumberText', 'decisionTypeCodeDescriptionText', 'decisionPetitionTypeCode', 'petitionMailDate', 'ruleBag']
# Purpose: Identify revival petitions (37 CFR 1.137), examiner disputes (37 CFR 1.181), denied petitions
```

**Due Diligence Portfolio Analysis**:
```yaml
fields: ['applicationNumberText', 'patentNumber', 'firstApplicantName', 'decisionTypeCodeDescriptionText', 'petitionMailDate', 'groupArtUnitNumber']
# Purpose: Assess company petition history for M&A or investment decisions
```

**Prosecution Quality Assessment**:
```yaml
fields: ['applicationNumberText', 'groupArtUnitNumber', 'decisionTypeCodeDescriptionText', 'decisionPetitionTypeCode', 'petitionMailDate', 'prosecutionStatusCodeDescriptionText']
# Purpose: Correlate petition patterns with prosecution quality metrics
```

**Legal Precedent Research**:
```yaml
fields: ['petitionDecisionRecordIdentifier', 'ruleBag', 'statuteBag', 'petitionIssueConsideredTextBag', 'decisionTypeCodeDescriptionText', 'inventionTitle']
# Purpose: Research Director's reasoning and legal precedents for similar technologies
```

### Field Configuration Validation

#### Testing Your Configuration

After modifying `field_configs.yaml`:

1. **Restart Claude Desktop** - Changes only take effect after restart
2. **Test minimal search** - Run a small test search to verify fields
3. **Check token usage** - Monitor context consumption in your workflows

#### Common Configuration Issues

**Missing Required Fields**:
- Always include `petitionDecisionRecordIdentifier` (required for all workflows)
- Include `applicationNumberText` for PFW cross-reference
- Include `patentNumber` for PTAB cross-reference when analyzing granted patents

**Token Explosion**:
- Never include `documentBag` in field configurations without explicit need
- Limit results with appropriate `limit` parameters
- Use progressive disclosure approach for large datasets

**Cross-MCP Integration Issues**:
- Include `applicationNumberText` for PFW workflows
- Include `patentNumber` for PTAB workflows
- Include `groupArtUnitNumber` for art unit analysis across MCPs

#### Field Performance Notes

**Fast Fields** (minimal processing overhead):
- `petitionDecisionRecordIdentifier`, `applicationNumberText`, `patentNumber`
- `decisionTypeCodeDescriptionText`, `petitionMailDate`, `decisionDate`
- `groupArtUnitNumber`, `firstApplicantName`

**Medium Fields** (moderate processing):
- `decisionPetitionTypeCode`, `decisionPetitionTypeCodeDescriptionText`
- `prosecutionStatusCodeDescriptionText`, `businessEntityStatusCategory`
- `finalDecidingOfficeName`, `inventionTitle`

**Array Fields** (higher processing - use strategically):
- `petitionIssueConsideredTextBag` (issues raised - valuable for analysis)
- `ruleBag` (CFR rules cited - essential for legal research)
- `statuteBag` (statutes cited - important for precedent analysis)

### Advanced Customization

#### Creating Custom Field Sets

You can create entirely new field sets beyond the default minimal/balanced:

```yaml
predefined_sets:
  petitions_red_flag_analysis:
    description: "Red flag identification (97% reduction)"
    fields:
      - petitionDecisionRecordIdentifier
      - applicationNumberText
      - decisionTypeCodeDescriptionText
      - decisionPetitionTypeCode
      - petitionMailDate
      - ruleBag

  petitions_cross_mcp_integration:
    description: "Cross-MCP workflow optimization (90% reduction)"
    fields:
      - petitionDecisionRecordIdentifier
      - applicationNumberText
      - patentNumber
      - groupArtUnitNumber
      - firstApplicantName
      - decisionTypeCodeDescriptionText
      - petitionMailDate
      - decisionDate

  petitions_legal_research:
    description: "Legal precedent research (85% reduction)"
    fields:
      - petitionDecisionRecordIdentifier
      - ruleBag
      - statuteBag
      - petitionIssueConsideredTextBag
      - decisionTypeCodeDescriptionText
      - inventionTitle
      - technologyCenter
      - finalDecidingOfficeName
```

### Red Flag Analysis Framework

The field customization system supports systematic red flag identification:

#### Revival Petitions (37 CFR 1.137)
- **Indicator**: `decisionPetitionTypeCode` contains revival petition codes
- **Significance**: Application was abandoned - indicates missed deadlines or prosecution issues
- **Fields needed**: `decisionPetitionTypeCode`, `ruleBag`, `decisionTypeCodeDescriptionText`

#### Examiner Disputes (37 CFR 1.181)
- **Indicator**: `ruleBag` contains "37 CFR 1.181"
- **Significance**: Petition for supervisory review challenging examiner decisions
- **Fields needed**: `ruleBag`, `petitionIssueConsideredTextBag`, `decisionTypeCodeDescriptionText`

#### Denied Petitions
- **Indicator**: `decisionTypeCodeDescriptionText` = "DENIED"
- **Significance**: Director denied the petition - may indicate weak legal arguments
- **Fields needed**: `decisionTypeCodeDescriptionText`, `ruleBag`, `petitionIssueConsideredTextBag`

### Troubleshooting Field Configuration

#### Common Error Messages

**"Field not found in YAML config"**:
- Check spelling of field names in your YAML file
- Verify field exists in the FPD API documentation
- Ensure proper YAML syntax (spaces, not tabs for indentation)

**"Empty results with custom fields"**:
- Ensure `petitionDecisionRecordIdentifier` is always included
- Check that your search criteria are valid
- Test with default fields first, then add custom fields

**"High token usage despite minimal configuration"**:
- Avoid array fields like `petitionIssueConsideredTextBag` in high-volume searches
- Limit results with appropriate `limit` parameter
- Use progressive disclosure for large datasets

#### Performance Validation

To validate your configuration efficiency:

```bash
# Test your custom configuration
uv run python tests/test_basic.py

# Check for configuration issues
uv run python tests/test_integration.py
```

#### Field Availability Reference

**Always Available**:
- `petitionDecisionRecordIdentifier`, `applicationNumberText`
- `decisionTypeCodeDescriptionText`, `petitionMailDate`

**Patent-Dependent**:
- `patentNumber` (only for granted patents)
- Some prosecution status fields

**Petition-Type Dependent**:
- `ruleBag` (may be empty for some petition types)
- `statuteBag` (may be empty for some petition types)
- `petitionIssueConsideredTextBag` (depends on petition complexity)

This comprehensive field customization system allows you to optimize the MCP server for your specific petition analysis workflows while maintaining the flexibility to adjust as your needs evolve and new use cases emerge.