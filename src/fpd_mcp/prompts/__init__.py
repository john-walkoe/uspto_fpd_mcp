"""
FPD MCP Prompt Templates

This module contains comprehensive prompt templates for Final Petition Decision analysis workflows.
Each prompt provides complete implementation guidance with working code, error handling, safety rails,
and cross-MCP integration patterns.

All prompts follow the comprehensive implementation pattern:
- Complete working code with loops and data processing
- Error handling with try/except for cross-MCP calls
- Safety rails with explicit context limits
- Presentation formatting with markdown tables
- Result aggregation and scoring systems
- Cross-MCP integration (PFW, PTAB, Citations)

Available Prompts:
- company_petition_risk_assessment_pfw: Company petition risk assessment for due diligence
- art_unit_quality_assessment: Art unit quality evaluation via petition patterns
- revival_petition_analysis: Revival petition pattern analysis and risk assessment
- petition_document_research_package: Complete document retrieval and analysis workflow
- complete_portfolio_due_diligence_pfw_ptab: Portfolio-wide petition and PTAB risk analysis
- litigation_research_setup_pfw: Litigation research preparation with petition context
- prosecution_quality_correlation_pfw: Correlation analysis between prosecution and petitions
- patent_vulnerability_assessment_ptab: Patent vulnerability via petition and PTAB correlation
- petition_quality_with_citation_intelligence: Three-MCP citation-petition quality analysis
- examiner_dispute_citation_analysis: Examiner dispute correlation with citation patterns
"""

import os

# Registration gate (FPD_ENABLE_USER_MANAGEMENT parity): the 10 prompt
# templates are registered only when FPD_ENABLE_PROMPTS=true. Default off —
# unset/false means NO prompts appear in prompts/list, on stdio and HTTP
# alike. Evaluated at import time, same as the admin-tool gate.
PROMPTS_ENABLED = (
    os.getenv("FPD_ENABLE_PROMPTS", "false").lower() == "true"
)


def register_prompts(mcp_server):
    """Register all prompts with the MCP server (gated by FPD_ENABLE_PROMPTS).

    This function is called from main.py after the mcp object is created.
    When the gate is off (default) it returns without registering anything;
    when on, it imports each prompt module and calls its own register(mcp)
    function, passing the server instance explicitly (no order-dependent
    global injection into the prompts package namespace).

    Args:
        mcp_server: The FastMCP server instance to register prompts with
    """
    if not PROMPTS_ENABLED:
        return

    from . import company_petition_risk_assessment_pfw
    from . import art_unit_quality_assessment
    from . import revival_petition_analysis
    from . import petition_document_research_package
    from . import complete_portfolio_due_diligence_pfw_ptab
    from . import litigation_research_setup_pfw
    from . import prosecution_quality_correlation_pfw
    from . import patent_vulnerability_assessment_ptab
    from . import petition_quality_with_citation_intelligence
    from . import examiner_dispute_citation_analysis

    company_petition_risk_assessment_pfw.register(mcp_server)
    art_unit_quality_assessment.register(mcp_server)
    revival_petition_analysis.register(mcp_server)
    petition_document_research_package.register(mcp_server)
    complete_portfolio_due_diligence_pfw_ptab.register(mcp_server)
    litigation_research_setup_pfw.register(mcp_server)
    prosecution_quality_correlation_pfw.register(mcp_server)
    patent_vulnerability_assessment_ptab.register(mcp_server)
    petition_quality_with_citation_intelligence.register(mcp_server)
    examiner_dispute_citation_analysis.register(mcp_server)

__all__ = [
    'register_prompts',
    'PROMPTS_ENABLED',
]
