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

def register_prompts(mcp_server):
    """Register all prompts with the MCP server.

    This function is called from main.py after the mcp object is created.
    It imports and registers all prompt modules with the server.

    Args:
        mcp_server: The FastMCP server instance to register prompts with
    """
    # Store mcp server globally for prompt modules to use
    global mcp
    mcp = mcp_server

    # Import all prompt modules to register them with the MCP server
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

__all__ = [
    'register_prompts',
]
