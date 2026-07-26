"""Round 2 preview-only promotion from scene templates to background plates.

The workbook-derived scene prompt library contains presenter/product actions, so
this module deliberately consumes only each template's ``setting`` field.  It
never writes the scene registry or its bridge CSV: callers receive a dry-run
candidate set plus a deterministic quarantine ledger for review.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from agent.services import creative_scene_prompt_service as _scene_prompts
from agent.services import scene_context_registry as _registry


PROMOTION_SOURCE = "SCENE_CONTEXT_PROMOTION_R2"
_UNSAFE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PLACEHOLDER_AVATAR", re.compile(r"\[AVATAR\]", re.IGNORECASE)),
    ("PLACEHOLDER_PRODUCT", re.compile(r"\[PRODUCT\]", re.IGNORECASE)),
    (
        "PERSON_OR_SUBJECT_INSTRUCTION",
        re.compile(
            r"\b(?:people|person|presenter|avatar|model|man|woman|child|children|baby|family|customer|user|pet|animal)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "PRODUCT_INSTRUCTION",
        re.compile(r"\b(?:product|item|merchandise)\b", re.IGNORECASE),
    ),
    (
        "ACTION_INSTRUCTION",
        re.compile(
            r"\b(?:holding|using|wearing|demonstrating|showing|presenting|installing|fitting|placing|pouring|dispensing|arranging|writing|operating)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "RENDERED_TEXT_OR_BRANDING_INSTRUCTION",
        re.compile(
            r"\b(?:rendered\s+text|caption|headline|logo|price|watermark|sticker|ui\s+chrome)\b",
            re.IGNORECASE,
        ),
    ),
)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _unsafe_reason(*values: str) -> str | None:
    """Return the first deterministic safety failure across candidate fields."""
    text = "\n".join(_clean_text(value) for value in values)
    for reason, pattern in _UNSAFE_RULES:
        if pattern.search(text):
            return reason
    return None


def _background_plate_prompt(scene_name: str, background_prompt: str) -> str:
    """Build a clean plate prompt without product/presenter vocabulary.

    This mirrors ``scene_context_registry.build_scene_prompt_v1``'s deterministic
    structure, but cannot reuse its wording because that legacy helper describes
    later compositing subjects.  Round 2 candidates must stay free of that
    vocabulary before owner review.
    """
    background = _clean_text(background_prompt)
    if background.lower().startswith("background:"):
        background = background.split(":", 1)[1].strip()
    return (
        "Create a photorealistic empty environmental background plate. "
        f"Scene: {_clean_text(scene_name)}. {background.rstrip('. ')}. "
        "Empty environment only, with architecture, furnishings, landscape, "
        "lighting, and atmosphere as described. Exclude all subjects, sellable "
        "objects, lettering, branding, pricing marks, and interface overlays. "
        "Natural depth, perspective, and lighting. Background plate only."
    )


def _usage_tags(cluster: str, template_id: str) -> str:
    return f"scene_context|cluster:{cluster.casefold()}|source:{template_id}"


def _candidate_from_template(template: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Project one safe setting into a candidate row, or quarantine it."""
    cluster = _clean_text(template.get("cluster"))
    template_id = _clean_text(template.get("template_id"))
    setting = _clean_text(template.get("setting"))
    provenance = {
        "cluster": cluster,
        "source_template_id": template_id,
        "source_category": _clean_text(template.get("source_category")),
        "setting": setting,
    }
    if not cluster or not template_id or not setting:
        return None, {**provenance, "reason": "MISSING_REQUIRED_TEMPLATE_FIELD"}

    source_reason = _unsafe_reason(setting)
    if source_reason:
        return None, {**provenance, "reason": source_reason}

    scene_name = f"{cluster} — {setting}"
    background_prompt = f"Background: {setting.rstrip('. ')}"
    prompt_v1 = _background_plate_prompt(scene_name, background_prompt)
    candidate_reason = _unsafe_reason(background_prompt, prompt_v1)
    if candidate_reason:
        return None, {**provenance, "reason": candidate_reason}

    row = {
        "SceneName": scene_name,
        "SceneCode": _registry.next_scene_code(f"{cluster} {template_id}"),
        "BackgroundPrompt": background_prompt,
        "RouteFit": "IMAGE|VIDEO_SUPPORT",
        "SafetyBlock": "EMPTY_BACKGROUND_ONLY|NO_SUBJECTS|NO_COMMERCIAL_OBJECTS|NO_TEXT_OR_BRANDING",
        "PromptV1": prompt_v1,
        "approved_flag": "FALSE",
        "usage_tags": _usage_tags(cluster, template_id),
    }
    return {**provenance, "row": row}, None


def preview_scene_context_promotion(cluster: str | None = None) -> dict[str, Any]:
    """Derive deterministic, review-only candidates from library settings.

    ``approved_flag`` remains ``FALSE`` and this function performs no sync/add
    operation.  Duplicate candidates and rows already present in the active pool
    are quarantined rather than silently selected for promotion.
    """
    templates = _scene_prompts.library_templates()
    if cluster is not None:
        wanted = _clean_text(cluster).casefold()
        templates = [
            template for template in templates
            if _clean_text(template.get("cluster")).casefold() == wanted
        ]

    candidates: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_backgrounds: set[str] = set()
    for template in templates:
        candidate, rejected = _candidate_from_template(template)
        if rejected is not None:
            quarantined.append(rejected)
            continue
        assert candidate is not None
        row = candidate["row"]
        name_key = _clean_text(row["SceneName"]).casefold()
        background_key = _clean_text(row["BackgroundPrompt"]).casefold()
        duplicate = _registry.find_duplicate_scene(
            row["SceneName"], row["BackgroundPrompt"]
        )
        if duplicate is not None:
            quarantined.append(
                {
                    **{key: candidate[key] for key in ("cluster", "source_template_id", "source_category", "setting")},
                    "reason": "DUPLICATE_ACTIVE_SCENE",
                    "duplicate_scene_code": duplicate["scene_code"],
                }
            )
            continue
        if name_key in seen_names or background_key in seen_backgrounds:
            quarantined.append(
                {
                    **{key: candidate[key] for key in ("cluster", "source_template_id", "source_category", "setting")},
                    "reason": "DUPLICATE_PROMOTION_CANDIDATE",
                }
            )
            continue
        seen_names.add(name_key)
        seen_backgrounds.add(background_key)
        candidates.append(candidate)

    summary: dict[str, dict[str, int]] = defaultdict(
        lambda: {"candidate_count": 0, "quarantine_count": 0}
    )
    for candidate in candidates:
        summary[candidate["cluster"]]["candidate_count"] += 1
    for rejected in quarantined:
        summary[rejected["cluster"]]["quarantine_count"] += 1
    return {
        "dry_run": True,
        "source": PROMOTION_SOURCE,
        "template_count": len(templates),
        "candidate_count": len(candidates),
        "quarantine_count": len(quarantined),
        "cluster_summary": dict(sorted(summary.items())),
        "candidates": candidates,
        "quarantine": quarantined,
    }


def preview_quarantine(cluster: str | None = None) -> dict[str, Any]:
    """Return only the explicit fail-closed review ledger."""
    preview = preview_scene_context_promotion(cluster)
    return {
        key: preview[key]
        for key in ("dry_run", "source", "template_count", "quarantine_count", "cluster_summary", "quarantine")
    }
