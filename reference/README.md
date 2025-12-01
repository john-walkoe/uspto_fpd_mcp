# USPTO FPD MCP Reference Documentation

This directory contains official USPTO reference documentation used by the Final Petition Decisions MCP.

## Files

### `petition-decision-schema.json`
**Source:** [USPTO Petition Decision Schema](https://data.uspto.gov/documents/documents/petition-decision-schema.json)
**Updated:** 2024-11-24
**Size:** ~15 KB

JSON Schema specification for USPTO Final Petition Decisions API responses.

**Contents:**
- Complete field definitions and data types
- Petition decision response structure
- Field validation schemas
- API response format specifications

**Key Fields:**
- **applicationNumberText** - Links to PFW MCP for prosecution history
- **patentNumber** - Links to PTAB MCP for post-grant challenges (if granted)
- **decisionTypeCode/Text** - Petition outcome (Granted, Denied, etc.)
- **ruleBag** - CFR rule citations (37 CFR 1.137, 1.181, 1.182, 1.183)
- **groupArtUnitNumber** - Art unit for quality analysis
- **firstApplicantName** - Party matching across MCPs

**Usage:**
- Field validation in fpd_client.py
- Response parsing and filtering
- Cross-MCP integration field mapping

---

### `FinalPetitionDecisions_swagger.yaml`
**Source:** [USPTO Master Swagger](https://data.uspto.gov/swagger/swagger.yaml) (filtered for FPD endpoints only)
**Updated:** 2024-11-24
**Size:** ~25 KB (FPD endpoints only)

OpenAPI/Swagger specification for the USPTO Final Petition Decisions REST API, extracted from the master USPTO API specification with Patent Search, Bulk DataSets, and PTAB endpoints removed.

**Contents:**
- FPD-specific API endpoint definitions (Petition Decision Search only)
- Request/response schemas for petition searches
- Authentication requirements (same USPTO API key as PFW)
- Query parameter specifications

**Key Endpoint:**
- `/api/v1/petition/decisions/search` - Search petition decisions (GET/POST)

**Usage:**
- API schema reference for fpd_client.py
- Field path mapping for field_configs.yaml
- Parameter validation and tool documentation

---

### `Document_Descriptions_List.csv`
**Source:** [USPTO EFS Document Description List](https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description)
**Updated:** 04/27/2022
**Size:** ~189 KB (3,133 rows)

Comprehensive list of all USPTO document codes, including petition-related documents.

**Contents:**
- **3,100+ document codes** with official descriptions
- Petition-specific codes for 37 CFR 1.137, 1.181, 1.182, 1.183
- Categories: Amendments, Office Actions, Appeals, Citations, Filings, Petitions

**Petition-Related Codes:**
- **PET.137** - Petition for Revival under 37 CFR 1.137
- **PET.181** - Petition under 37 CFR 1.181 (supervisory review)
- **PET.182** - Petition under 37 CFR 1.182 (reconsideration)
- **PET.183** - Petition under 37 CFR 1.183 (suspension of rules)
- **DEC.PET** - Decision on Petition
- **DENY.PET** - Denied Petition

**Usage:**
- Referenced by `fpd_get_tool_reflections` for petition code guidance
- Cross-reference with ruleBag field in petition decisions
- Document type analysis for petition workflows

---

## Integration with MCP

### Cross-MCP Integration Fields
The FPD MCP serves as a bridge between prosecution (PFW) and post-grant (PTAB) analysis:

**To PFW MCP:**
- `applicationNumberText` - Complete prosecution history
- `groupArtUnitNumber` - Art unit quality patterns
- `firstApplicantName` - Party matching

**To PTAB MCP:**
- `patentNumber` - Post-grant challenge correlation (if granted)
- `ruleBag` + decision outcome - Vulnerability assessment
- Red flag analysis for PTAB prediction

### Petition Decision Analysis
The schema supports sophisticated petition quality assessment:
- **Revival Petitions (37 CFR 1.137)** - Abandoned applications
- **Supervisory Review (37 CFR 1.181)** - Examiner disputes
- **Reconsideration (37 CFR 1.182)** - Restriction disputes
- **Suspension of Rules (37 CFR 1.183)** - Special circumstances

### API Schema Integration
The Swagger specification enables:
- Type-safe API calls in fpd_client.py
- Accurate field path mapping in field_manager.py
- Complete parameter documentation in tool docstrings
- Progressive disclosure workflow (minimal → balanced → detailed)

---

## Updating Reference Files

These files should be updated when:
1. **USPTO releases new API versions** - Update `FinalPetitionDecisions_swagger.yaml`
2. **Petition decision schema changes** - Update `petition-decision-schema.json`
3. **New petition codes added** - Update `Document_Descriptions_List.csv`
4. **API field schemas change** - Regenerate field_configs.yaml mappings

To update:
```bash
# Download latest full Swagger spec from USPTO
curl -O https://data.uspto.gov/swagger/swagger.yaml

# Extract FPD sections to FinalPetitionDecisions_swagger.yaml (remove Patent Search, Bulk DataSets, PTAB)
# Update petition-decision-schema.json from https://data.uspto.gov/documents/documents/petition-decision-schema.json

# Update document codes from USPTO EFS page
# Download from: https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description
# Update reference/Document_Descriptions_List.csv

# Regenerate field configs if needed
uv run python -c "from fpd_mcp.config.field_manager import FieldManager; FieldManager().validate_config()"
```

---

## Related Documentation

- **Tool Documentation:** See tool docstrings in `src/fpd_mcp/main.py`
- **Field Configs:** See `field_configs.yaml` for progressive disclosure
- **API Client:** See `src/fpd_mcp/api/fpd_client.py` for implementation
- **Cross-MCP Integration:** Use `fpd_get_tool_reflections` for workflow guidance
- **Red Flag Analysis:** Petition decision patterns for quality assessment

---

## Red Flag Analysis Framework

### Petition Types and Risk Indicators

**High-Risk Indicators:**
- **Denied Revival Petitions (37 CFR 1.137)** - Poor deadline management
- **Denied Supervisory Review (37 CFR 1.181)** - Examiner disputes, weak arguments
- **Multiple Restriction Disputes (37 CFR 1.182)** - Claim scope issues
- **Suspension of Rules Requests (37 CFR 1.183)** - Procedural problems

**Cross-MCP Correlation:**
- FPD red flags → PFW prosecution quality assessment
- FPD patterns → PTAB vulnerability prediction
- Art unit petition rates → Portfolio risk analysis

### Document Code Integration
The document codes support petition workflow analysis:
- **PET.xxx codes** - Petition filing tracking
- **DEC.PET/DENY.PET** - Outcome correlation with decision data
- **Cross-reference with ruleBag** - CFR citation validation

This framework enables systematic patent portfolio quality assessment across the complete prosecution and post-grant lifecycle.
