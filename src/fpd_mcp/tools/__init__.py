"""Tool registration package (SD-1/SOLID-1 god-module split).

Each module defines its tools as plain (envelope-wrapped) async functions and
exposes register(mcp); register_all preserves the historical registration
order: admin -> petitions (search/details) -> documents -> guidance.
"""

from . import admin, documents, guidance, petitions


def register_all(mcp, auth_provider=None) -> None:
    admin.register(mcp, auth_provider)
    petitions.register(mcp)
    documents.register(mcp)
    guidance.register(mcp)
