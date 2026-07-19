"""
Pydantic models for the FPD proxy server.

Ported from the PTAB proxy's RecentDownloadRegistration (PTAB
proxy/models.py) — same shape of problem: an internal, X-Proxy-Token-gated
endpoint that previously accepted an arbitrary JSON object with no
field-level schema (L19) and whose fields are rendered into the downloads
page via client-side template literals (the latent innerHTML stored-XSS
pattern, L20). Whitelisting and length-capping the fields here closes both:
nothing outside this schema can ever reach the registry or the page.
"""

from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator


class RecentDownloadRegistration(BaseModel):
    """Payload accepted by the local /api/register-download endpoint."""

    download_url: str = Field(..., max_length=2048)
    petition_id: str = Field(..., max_length=64)
    document_identifier: str = Field(..., max_length=64)
    document_description: Optional[str] = Field(None, max_length=512)
    enhanced_filename: Optional[str] = Field(None, max_length=255)
    # int in the common case, but accept str defensively — PTAB's proxy
    # model hit the same Union[int, str] gotcha for a page-count-like field
    # that upstream metadata can report inconsistently.
    page_count: Optional[Union[int, str]] = None
    application_number: Optional[str] = Field(None, max_length=32)
    proxy_mode: Optional[str] = Field(None, max_length=32)
    viewer_key: Optional[str] = Field(None, max_length=128)
    download_id: Optional[str] = Field(None, max_length=64)

    model_config = {"extra": "ignore"}

    @field_validator("page_count")
    @classmethod
    def cap_page_count(cls, v):
        # Defense-in-depth: a string page_count is rendered in the panel, so
        # bound it even though this endpoint is proxy-token-gated.
        if isinstance(v, str) and len(v) > 32:
            return v[:32]
        return v
