"""Poster copy auto-fit — condense over-length poster copy to the poster limits.

Request/response contract for the "Fit to poster" action. This is a
suggestion-only transform: it returns candidate shortened copy for the operator
to review and apply. It NEVER persists, approves, or binds a Copy Set.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PosterCopyFitRequest(BaseModel):
    language: str = "ms"
    hook: str = ""
    subhook: str = ""
    usp_1: str = ""
    usp_2: str = ""
    usp_3: str = ""
    cta: str = ""


class PosterCopyFitFields(BaseModel):
    hook: str = ""
    subhook: str = ""
    usp_1: str = ""
    usp_2: str = ""
    usp_3: str = ""
    cta: str = ""


class PosterCopyFitResponse(BaseModel):
    # True only when at least one field was actually shortened to fit.
    applied: bool = False
    # Mirrors the text_assist provider lane state so the UI can explain a no-op.
    provider_configured: bool = False
    # The resulting copy: shortened where the AI produced a valid shorter line,
    # original text everywhere else (never silently blanked).
    fields: PosterCopyFitFields = Field(default_factory=PosterCopyFitFields)
    # Human labels of the fields that were shortened, e.g. ["Hook", "USP 1"].
    changed_fields: list[str] = Field(default_factory=list)
    # Fields still over the limit after the attempt, as "Label (len/limit)".
    still_over_limit: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
