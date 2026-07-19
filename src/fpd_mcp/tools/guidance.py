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
💰 "Reduce extraction costs" → cost

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
- cost: Cost optimization for document extraction

Context Efficiency Benefits:
- 80-95% token reduction (2-8KB per section vs 62KB total)
- Targeted guidance for specific workflows
- Same comprehensive content organized for efficiency
- Consistent pattern with PFW MCP"""
    try:
        return get_guidance_section(section)
    except Exception as e:
        logger.error(f"Unexpected error in get guidance: {str(e)}")
        return f"Error: Internal error - {str(e)}"


def register(mcp) -> None:
    """Register the guidance tool (name/schema unchanged)."""
    mcp.tool(name="FPD_get_guidance",
             annotations={"defer_loading": False, "readOnlyHint": True})(fpd_get_guidance)
