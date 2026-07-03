"""Social Copy Package service — platform-specific caption/comment copy.

A Social Copy Package is the *publishing* counterpart to the generation prompt
package: it holds the caption / first-comment / hashtags / CTA that get sent to
a social platform via Postiz, linked to a generated artifact by ``media_id``.

This layer is manual-first: the operator authors (or lightly edits) copy, and
the service validates it as **claim-safe** and **platform-aware**, then persists
it with an approval lifecycle (DRAFT → READY → APPROVED). A deterministic
``suggest_copy`` helper seeds sensible per-platform scaffolding without needing
an LLM; if a copy-generation backend is added later it can replace/augment
``suggest_copy`` behind the same API. Claim-safety reuses the existing
``claim_safe_rewrite_service`` gate so herbal/traditional products never carry
unsupported medical claims (cure/heal/ubat/penawar/...).
"""
from __future__ import annotations

import json
import uuid

from agent.db import crud
from agent.services.claim_safe_rewrite_service import (
    _contains_unsafe_language,
    _normalize,
)

# Platforms BOSMAX supports for social copy (mirrors the DB CHECK constraint and
# the Postiz provider names so channel→variant matching is a direct key lookup).
SUPPORTED_PLATFORMS = ("tiktok", "facebook", "instagram", "threads", "x")

_STATUS_APPROVABLE = ("DRAFT", "READY", "REJECTED")

# Per-platform copy profile. Tone + CTA + hashtag scaffolding are intentionally
# generic and CLAIM-SAFE (lifestyle/commercial language only) so they can seed
# any product without asserting a health claim. ``first_comment`` is a pinned
# comment on TikTok and a first comment on Facebook/Instagram; Threads/X don't
# have a first-class pinned-comment slot, so it's advisory there.
PLATFORM_PROFILES: dict[str, dict] = {
    "tiktok": {
        "tone": "punchy, hook-driven, native",
        "supports_first_comment": True,
        "first_comment_label": "Pinned comment",
        "cta_options": ["Tap keranjang kuning", "Tap tengok harga", "Tap link untuk lihat"],
        "hashtag_suggestions": ["#fyp", "#tiktokfinds", "#racuntiktok", "#viral"],
        "caption_hint": "Short hook + one benefit + CTA. Keep it native and fast.",
    },
    "instagram": {
        "tone": "polished lifestyle",
        "supports_first_comment": True,
        "first_comment_label": "First comment",
        "cta_options": ["Klik link di bio", "Simpan untuk rujukan", "DM untuk info"],
        "hashtag_suggestions": ["#lifestyle", "#dailyroutine", "#travelfriendly"],
        "caption_hint": "Polished lifestyle caption, medium length, soft CTA.",
    },
    "facebook": {
        "tone": "trust-building, explanatory",
        "supports_first_comment": True,
        "first_comment_label": "First comment",
        "cta_options": ["PM untuk tempah", "Klik untuk lihat pilihan", "Komen untuk info"],
        "hashtag_suggestions": ["#pilihanramai", "#rutinharian"],
        "caption_hint": "Longer trust-building copy, explain the everyday use.",
    },
    "threads": {
        "tone": "conversational, casual, human",
        "supports_first_comment": False,
        "first_comment_label": "First comment",
        "cta_options": ["Cuba tengok", "Nak tahu lebih?"],
        "hashtag_suggestions": [],
        "caption_hint": "Conversational, casual, short-to-medium, soft CTA.",
    },
    "x": {
        "tone": "concise, punchy, character-aware",
        "supports_first_comment": False,
        "first_comment_label": "Reply",
        "cta_options": ["Tengok di sini", "Details below"],
        "hashtag_suggestions": ["#lifestyle"],
        "caption_hint": "Concise and punchy. No long paragraph. Optional 1–2 tags.",
    },
}


class SocialCopyError(ValueError):
    """Domain error surfaced to the API as a 4xx (never leaks internals)."""


def platform_profiles() -> dict[str, dict]:
    """Public copy of the per-platform profiles (for UI scaffolding)."""
    return {k: dict(v) for k, v in PLATFORM_PROFILES.items()}


def _validate_platform(platform: str) -> str:
    p = (platform or "").strip().lower()
    if p not in SUPPORTED_PLATFORMS:
        raise SocialCopyError(f"UNSUPPORTED_PLATFORM:{platform}")
    return p


def _assess_compliance(
    *, caption: str, first_comment: str, call_to_action: str, hashtags: list[str]
) -> tuple[str, list[str], list[str]]:
    """Return (compliance_status, blockers, warnings) for a copy variant.

    Unsafe (medical/guarantee) language in any field is a hard BLOCKER — the
    package cannot be approved until fixed. This reuses the repo's single
    claim-safe gate so behavior matches the production prompt lane.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    checks = {
        "caption": caption,
        "first_comment": first_comment,
        "call_to_action": call_to_action,
    }
    for field, value in checks.items():
        if value and _contains_unsafe_language(value):
            blockers.append(f"UNSAFE_LANGUAGE:{field}")
    for tag in hashtags:
        if _contains_unsafe_language(tag):
            blockers.append(f"UNSAFE_LANGUAGE:hashtag:{tag}")
    if not caption.strip():
        warnings.append("EMPTY_CAPTION")
    compliance = "BLOCKED" if blockers else ("WARN" if warnings else "OK")
    return compliance, blockers, warnings


def _clean_hashtags(hashtags: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in hashtags or []:
        tag = _normalize(raw)
        if not tag:
            continue
        tag = tag if tag.startswith("#") else f"#{tag}"
        out.append(tag)
    return out


def suggest_copy(
    *, platform: str, source_mode: str | None = None, product_name: str | None = None
) -> dict:
    """Deterministic, claim-safe per-platform scaffolding to seed the editor.

    This is NOT an AI copywriter — it returns safe defaults (tone, CTA options,
    hashtag suggestions, a neutral caption stub) the operator edits. It is the
    documented future-ready hook where an LLM copy backend would plug in.
    """
    p = _validate_platform(platform)
    profile = PLATFORM_PROFILES[p]
    name = _normalize(product_name) or "produk ni"
    caption_stub = f"{name} — standby untuk rutin harian. {profile['cta_options'][0]}."
    return {
        "platform": p,
        "tone": profile["tone"],
        "supports_first_comment": profile["supports_first_comment"],
        "first_comment_label": profile["first_comment_label"],
        "caption": caption_stub,
        "first_comment": "",
        "hashtags": list(profile["hashtag_suggestions"]),
        "call_to_action": profile["cta_options"][0],
        "cta_options": list(profile["cta_options"]),
        "caption_hint": profile["caption_hint"],
        "source_mode": source_mode,
    }


async def generate_social_copy_package(
    *,
    artifact_media_id: str,
    platform: str,
    caption: str = "",
    first_comment: str = "",
    hashtags: list[str] | None = None,
    call_to_action: str = "",
    tone: str = "",
    language: str = "ms",
    source_mode: str | None = None,
) -> dict:
    """Create + persist a social copy variant for an artifact, claim-safe checked."""
    p = _validate_platform(platform)
    artifact = await crud.get_generated_artifact(artifact_media_id)
    if not artifact:
        raise SocialCopyError("ARTIFACT_NOT_FOUND")

    caption = _normalize(caption)
    first_comment = _normalize(first_comment)
    call_to_action = _normalize(call_to_action)
    tone = _normalize(tone) or PLATFORM_PROFILES[p]["tone"]
    clean_tags = _clean_hashtags(hashtags)

    compliance, blockers, warnings = _assess_compliance(
        caption=caption,
        first_comment=first_comment,
        call_to_action=call_to_action,
        hashtags=clean_tags,
    )
    # READY only when clean; anything flagged stays DRAFT until the operator fixes it.
    status = "READY" if compliance == "OK" else "DRAFT"

    package_id = f"scp_{uuid.uuid4().hex[:16]}"
    return await crud.create_social_copy_package(
        package_id,
        artifact_media_id=artifact_media_id,
        platform=p,
        source_mode=source_mode or artifact.get("mode"),
        caption=caption,
        first_comment=first_comment,
        hashtags_json=json.dumps(clean_tags),
        call_to_action=call_to_action,
        tone=tone,
        language=_normalize(language) or "ms",
        status=status,
        compliance_status=compliance,
        blockers_json=json.dumps(blockers),
        warnings_json=json.dumps(warnings),
    )


async def update_social_copy_package(
    package_id: str,
    *,
    caption: str | None = None,
    first_comment: str | None = None,
    hashtags: list[str] | None = None,
    call_to_action: str | None = None,
    tone: str | None = None,
    language: str | None = None,
) -> dict:
    """Edit a copy variant, re-run claim-safety, and reset approval.

    Editing an APPROVED package un-approves it (back to DRAFT/READY) so approval
    always reflects the current text — you can never publish stale-approved copy.
    """
    pkg = await crud.get_social_copy_package(package_id)
    if not pkg:
        raise SocialCopyError("PACKAGE_NOT_FOUND")

    new_caption = _normalize(caption) if caption is not None else pkg.get("caption", "")
    new_first = (
        _normalize(first_comment) if first_comment is not None else pkg.get("first_comment", "")
    )
    new_cta = (
        _normalize(call_to_action)
        if call_to_action is not None
        else pkg.get("call_to_action", "")
    )
    new_tone = _normalize(tone) if tone is not None else pkg.get("tone", "")
    new_lang = _normalize(language) if language is not None else pkg.get("language", "ms")
    if hashtags is not None:
        clean_tags = _clean_hashtags(hashtags)
    else:
        try:
            clean_tags = json.loads(pkg.get("hashtags_json") or "[]")
        except (TypeError, ValueError):
            clean_tags = []

    compliance, blockers, warnings = _assess_compliance(
        caption=new_caption,
        first_comment=new_first,
        call_to_action=new_cta,
        hashtags=clean_tags,
    )
    status = "READY" if compliance == "OK" else "DRAFT"

    return await crud.update_social_copy_package(
        package_id,
        caption=new_caption,
        first_comment=new_first,
        hashtags_json=json.dumps(clean_tags),
        call_to_action=new_cta,
        tone=new_tone or PLATFORM_PROFILES.get(pkg.get("platform", ""), {}).get("tone", ""),
        language=new_lang or "ms",
        status=status,
        compliance_status=compliance,
        blockers_json=json.dumps(blockers),
        warnings_json=json.dumps(warnings),
        approval_note=None,
        approved_at=None,
    )


async def approve_social_copy_package(
    package_id: str, approval_note: str | None = None
) -> dict:
    """Approve a copy variant. Refuses claim-unsafe or empty copy; idempotent."""
    pkg = await crud.get_social_copy_package(package_id)
    if not pkg:
        raise SocialCopyError("PACKAGE_NOT_FOUND")
    if pkg.get("compliance_status") == "BLOCKED":
        raise SocialCopyError("CLAIM_UNSAFE_CANNOT_APPROVE")
    if not _normalize(pkg.get("caption")):
        # An empty caption would prefill nothing into Postiz — nothing to approve.
        raise SocialCopyError("EMPTY_CAPTION_CANNOT_APPROVE")
    if pkg.get("status") == "APPROVED":
        # Idempotent: don't re-stamp approved_at or clobber the existing note.
        return pkg
    if pkg.get("status") not in _STATUS_APPROVABLE:
        raise SocialCopyError(f"NOT_APPROVABLE_STATUS:{pkg.get('status')}")
    from agent.db.crud import _now

    return await crud.update_social_copy_package(
        package_id,
        status="APPROVED",
        approval_note=_normalize(approval_note) or None,
        approved_at=_now(),
    )


async def reject_social_copy_package(
    package_id: str, approval_note: str | None = None
) -> dict:
    pkg = await crud.get_social_copy_package(package_id)
    if not pkg:
        raise SocialCopyError("PACKAGE_NOT_FOUND")
    return await crud.update_social_copy_package(
        package_id, status="REJECTED", approval_note=_normalize(approval_note) or None
    )
