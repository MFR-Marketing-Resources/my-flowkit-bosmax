"""Poster copy auto-fit — AI condenses over-length poster copy to the poster limits.

Why this exists: Copy Sets are authored by the video Formula Copywriting Engine,
so their lines are structurally long. When bound to a poster they overflow the
poster length gate (hook 48 / subhook 72 / USP 36 / CTA 24) and the operator was
forced to shorten every field by hand. This service does that shortening for
them — semantically (AI rewrite), never by blind truncation.

Contract (matches the repo's AI-copy rules):
- EXPLICIT-only: runs solely when the operator clicks "Fit to poster". No caller
  fires it on auto-load, so it never spends provider tokens silently.
- Suggestion-only: returns candidate shortened fields. It NEVER persists,
  approves, or binds a Copy Set.
- Fail-closed: when the text_assist provider lane is unconfigured (default) or a
  call fails, it returns the ORIGINAL copy untouched with an explanatory warning.
- Same gates as the deterministic build: it reuses the poster length SSOT
  (POSTER_COPY_LIMITS) and the unsafe-claim term list (UNSAFE_CLAIM_TERMS) from
  poster_prompt_draft_service, so any suggestion it returns will pass the
  downstream poster prompt-draft gate. AI output containing an unsafe term is
  discarded whole (fail-closed), never partially applied.
"""

from __future__ import annotations

from typing import Any

from agent.models.poster_copy_fit import (
    PosterCopyFitFields,
    PosterCopyFitRequest,
    PosterCopyFitResponse,
)
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services.poster_prompt_draft_service import (
    POSTER_COPY_LIMITS,
    UNSAFE_CLAIM_TERMS,
)

# Copy fields in draft order (SSOT limits live in poster_prompt_draft_service).
_COPY_KEYS: tuple[str, ...] = ("hook", "subhook", "usp_1", "usp_2", "usp_3", "cta")
_LABELS: dict[str, str] = {
    "hook": "Hook",
    "subhook": "Subhook",
    "usp_1": "USP 1",
    "usp_2": "USP 2",
    "usp_3": "USP 3",
    "cta": "CTA",
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _over_limit_keys(fields: dict[str, str]) -> list[str]:
    return [k for k in _COPY_KEYS if len(fields[k]) > POSTER_COPY_LIMITS[k]]


def _still_over_labels(fields: dict[str, str]) -> list[str]:
    out: list[str] = []
    for k in _COPY_KEYS:
        length = len(fields[k])
        if length > POSTER_COPY_LIMITS[k]:
            out.append(f"{_LABELS[k]} ({length}/{POSTER_COPY_LIMITS[k]})")
    return out


def _find_unsafe_terms(fields: dict[str, str]) -> list[str]:
    blob = " ".join(fields[k] for k in _COPY_KEYS if fields[k]).lower()
    return [term for term in UNSAFE_CLAIM_TERMS if term in blob]


def _build_condense_prompt(
    fields: dict[str, str], over_keys: list[str], language: str
) -> tuple[str, str]:
    system = (
        "You are a Malay/English poster copy EDITOR. Your ONLY job is to SHORTEN "
        "existing marketing copy so it fits strict poster character limits, "
        "WITHOUT changing its meaning, its language, or the product facts it "
        "already states. Poster lines are short and punchy — not long video-style "
        "sentences. You NEVER invent new facts or benefits, NEVER add a claim that "
        "is not already in the input, and NEVER write medical/cure/treat/heal/"
        "disease or guaranteed-result wording (in English or Malay). Keep the same "
        "language as each input line. Return STRICT JSON ONLY — no markdown, no "
        "commentary."
    )
    lines = [
        f'- "{k}": current = "{fields[k]}" -> rewrite to at most '
        f"{POSTER_COPY_LIMITS[k]} characters"
        for k in over_keys
    ]
    user = (
        f"Language: {language}. Shorten each field below so it fits its character "
        "limit while keeping the same meaning and language. Make each a tight "
        "poster line. Do not add facts or claims that are not already there.\n\n"
        + "\n".join(lines)
        + "\n\nReturn STRICT JSON with ONLY these keys: "
        + ", ".join(f'"{k}"' for k in over_keys)
        + ". Each value must be within its character limit."
    )
    return system, user


def fit_poster_copy(
    request: PosterCopyFitRequest | dict[str, Any],
) -> PosterCopyFitResponse:
    """Condense the operator's over-length poster copy to the poster limits.

    Only over-limit fields are sent to the AI; within-limit copy is left exactly
    as the operator wrote it. Fail-closed and suggestion-only throughout.
    """
    req = (
        request
        if isinstance(request, PosterCopyFitRequest)
        else PosterCopyFitRequest.model_validate(request)
    )
    fields = {k: _norm(getattr(req, k)) for k in _COPY_KEYS}
    over_keys = _over_limit_keys(fields)

    # Nothing to do — never call the provider (no token spend) when copy already fits.
    if not over_keys:
        return PosterCopyFitResponse(
            applied=False,
            provider_configured=ai_provider.is_configured(),
            fields=PosterCopyFitFields(**fields),
            warnings=[
                "Semua ayat copy sudah muat had poster — tiada apa untuk dipendekkan."
            ],
        )

    # Fail-closed when the AI lane is unconfigured (default). The operator keeps
    # their copy and a clear reason; no silent no-op.
    if not ai_provider.is_configured():
        return PosterCopyFitResponse(
            applied=False,
            provider_configured=False,
            fields=PosterCopyFitFields(**fields),
            still_over_limit=_still_over_labels(fields),
            warnings=[
                "AI provider (text_assist) belum dikonfigurasi — tidak dapat "
                "auto-pendekkan. Pendekkan manual, atau konfigur lane text_assist "
                "di Settings."
            ],
        )

    language = _norm(req.language) or "ms"
    system, user = _build_condense_prompt(fields, over_keys, language)
    try:
        raw = ai_provider.complete_json(system, user)
    except ai_provider.AICopyProviderNotConfigured:
        return PosterCopyFitResponse(
            applied=False,
            provider_configured=False,
            fields=PosterCopyFitFields(**fields),
            still_over_limit=_still_over_labels(fields),
            warnings=[
                "AI provider (text_assist) belum dikonfigurasi — tidak dapat "
                "auto-pendekkan."
            ],
        )
    except ai_provider.AICopyProviderError as exc:
        return PosterCopyFitResponse(
            applied=False,
            provider_configured=True,
            fields=PosterCopyFitFields(**fields),
            still_over_limit=_still_over_labels(fields),
            warnings=[
                f"AI auto-pendekkan gagal ({exc.code}). Sila cuba lagi atau "
                "pendekkan manual."
            ],
        )

    merged = dict(fields)
    changed: list[str] = []
    skipped: list[str] = []
    for k in over_keys:
        candidate = _norm(raw.get(k)) if isinstance(raw, dict) else ""
        # Only accept a candidate that is non-empty AND actually within the limit;
        # otherwise keep the operator's original line (never blank a field).
        if candidate and len(candidate) <= POSTER_COPY_LIMITS[k]:
            merged[k] = candidate
            changed.append(k)
        else:
            skipped.append(k)

    # Safety re-gate on the merged copy using the SAME static unsafe-term list the
    # poster prompt-draft build enforces. If the AI introduced an unsafe term,
    # discard its output entirely and keep the original copy (fail-closed).
    unsafe = _find_unsafe_terms(merged)
    if unsafe:
        return PosterCopyFitResponse(
            applied=False,
            provider_configured=True,
            fields=PosterCopyFitFields(**fields),
            still_over_limit=_still_over_labels(fields),
            warnings=[
                "Cadangan AI dibuang kerana mengandungi istilah tidak selamat: "
                + ", ".join(unsafe)
                + ". Sila pendekkan manual."
            ],
        )

    warnings: list[str] = []
    if skipped:
        warnings.append(
            "Sebahagian ayat masih terlalu panjang selepas cubaan AI — kemas "
            "sikit lagi secara manual: "
            + ", ".join(_LABELS[k] for k in skipped)
            + "."
        )

    return PosterCopyFitResponse(
        applied=bool(changed),
        provider_configured=True,
        fields=PosterCopyFitFields(**merged),
        changed_fields=[_LABELS[k] for k in changed],
        still_over_limit=_still_over_labels(merged),
        warnings=warnings,
    )
