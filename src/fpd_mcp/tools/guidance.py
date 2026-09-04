"""Guidance tool (SD-1 god-module split)."""

from ..config.tool_reflections import get_guidance_section
from ..util.secure_logger import get_secure_logger

logger = get_secure_logger(__name__)


async def fpd_get_guidance(section: str = "overview") -> str:
    """Get selective USPTO FPD guidance sections for context-efficient workflows.

🎯 QUICK REFERENCE - What section for your question?

🔍 "Find petitions by company/art unit" → tools
🚩 "Identify petition red flags" → red_flags
📄 "Download petition documents" → documents
🤝 "Correlate petitions with prosecution" → workflows_pfw
⚖️ "Analyze petition + PTAB patterns" → workflows_ptab
📊 "Citation quality + petition correlation" → workflows_citations
🏢 "Complete portfolio due diligence" → workflows_complete
📚 "Research CFR rules with Assistant" → workflows_assistant
🎯 "Ultra-minimal PFW + FPD workflows" → ultra_context
"Choose an extraction approach" → extraction
📏 "Why was my response truncated / how do I page it?" → limits
"Why did an old petition return zero results?" → coverage

Available sections:
- overview: Available sections and MCP overview (default)
- workflows_pfw: FPD + PFW integration workflows
- workflows_ptab: FPD + PTAB integration workflows
- workflows_citations: FPD + Citations integration workflows
- workflows_complete: Four-MCP complete lifecycle analysis
- workflows_assistant: Pinecone Assistant + FPD research workflows
- tools: Tool catalog, progressive disclosure, parameters
- red_flags: Petition red flag indicators and CFR rules
- documents: Document extraction, downloads, proxy configuration
- ultra_context: PFW fields parameter + ultra-minimal workflows
- extraction: Extraction-tier selection for speed and quality
- limits: Active response-size budgets, the _bounds/_window markers, paging
- coverage: Dataset coverage bounds (2001+ filings; 2022 is a completeness floor for decisions, not a cutoff)

Context Efficiency Benefits:
- 80-95% token reduction (2-8KB per section vs 62KB total)
- Targeted guidance for specific workflows
- Same comprehensive content organized for efficiency
- Consistent pattern with PFW MCP"""
    try:
        return get_guidance_section(section)
    except Exception as e:
        # F-E2: this returned `f"Error: Internal error - {str(e)}"`, a plain
        # string that bypassed LogSanitizer AND the production genericization
        # entirely, so str(e) reached the model verbatim in every
        # environment. The tool's return type is `str`, so the envelope is
        # not available here; the message is a constant instead, and the
        # detail stays in the log with a traceback (F-X5).
        logger.error(
            "Unexpected error in get guidance: %s", type(e).__name__,
            exc_info=True,
        )
        return (
            "Error: that guidance section could not be rendered. "
            "Try FPD_get_guidance('overview') for the section list."
        )


def register(mcp) -> None:
    """Register the guidance tool (name/schema unchanged)."""
    mcp.tool(name="FPD_get_guidance",
             annotations={"defer_loading": False, "readOnlyHint": True})(fpd_get_guidance)
