from __future__ import annotations

from copy import deepcopy
from math import floor
from typing import Any


ALLOWED_BLOCK_DURATIONS_SECONDS = [6, 8, 10, 12, 15, 20, 25]
DEFAULT_BLOCK_DURATION_SECONDS = 8
GENERATION_MODES = ["SINGLE", "EXTEND"]
CAMERA_STYLES = ["UGC_IPHONE_RAW", "CINEMATIC_PRO"]
CHARACTER_PRESENCE_OPTIONS = ["VISIBLE_CREATOR", "FACELESS"]
DEFAULT_CHARACTER_PRESENCE = "VISIBLE_CREATOR"
DEFAULT_CAMERA_STYLE = "UGC_IPHONE_RAW"
DEFAULT_TARGET_LANGUAGE = "BM_MS"
DEFAULT_CREATOR_PERSONA = "DEFAULT_CREATOR"

SHOT_COUNT_POLICY = {
    6: {"recommended": 1, "max": 2},
    8: {"recommended": 2, "max": 2},
    10: {"recommended": 3, "max": 3},
    12: {"recommended": 3, "max": 3},
    15: {"recommended": 4, "max": 4},
    20: {"recommended": 5, "max": 5},
    25: {"recommended": 6, "max": 6},
}

# ADR-008: values come from the RETAINED WORKBOOK AUTHORITY
# (agent/authority/wps_blocking_authority.json), not ad-hoc estimates.
# body_wps == SafeWPS (default budget), hook_wps == SweetWPS (deliberate
# dialogue-targeting mode), ceiling == workbook CeilingWPS. The canonical
# compiler reads the authority file directly; this mirror exists ONLY so the
# operator UI displays the same law the compiler enforces.
LANGUAGE_WPS_POLICY = {
    "BM_MS": {
        "hook_wps": 2.7,   # Malay SweetWPS (workbook)
        "body_wps": 2.4,   # Malay SafeWPS (workbook)
        "cta_wps": 2.4,
        "safe_wps": 2.4,
        "sweet_wps": 2.7,
        "absolute_ceiling_wps": 3.0,
    },
    "EN_US": {
        "hook_wps": 2.45,  # English SweetWPS (workbook)
        "body_wps": 2.3,   # English SafeWPS (workbook)
        "cta_wps": 2.3,
        "safe_wps": 2.3,
        "sweet_wps": 2.45,
        "absolute_ceiling_wps": 3.0,
    },
}

CAMERA_STYLE_REGISTRY = [
    {
        "id": "UGC_IPHONE_RAW",
        "label": "UGC iPhone Raw",
        "notes": [
            "vertical 9:16",
            "handheld iPhone raw style",
            "natural indoor light",
            "micro-jitter",
            "24mm/26mm wide equivalent",
            "TikTok/Reels native UGC pacing",
        ],
    },
    {
        "id": "CINEMATIC_PRO",
        "label": "Cinematic Pro",
        "notes": [
            "vertical cinematic commercial",
            "controlled lighting",
            "cleaner camera move",
            "premium product handling",
            "shallow depth if appropriate",
        ],
    },
]

PERSONA_REGISTRY = [
    {
        "id": "DEFAULT_CREATOR",
        "label": "Default Creator",
        "presentation": "visible creator",
        "tone": "calm, credible, product-first",
        "continuity_notes": "same creator identity and wardrobe across all blocks",
    },
    {
        "id": "CONFIDENT_EXPLAINER",
        "label": "Confident Explainer",
        "presentation": "visible creator",
        "tone": "clear, upbeat, instructional without hype",
        "continuity_notes": "consistent creator look and clean commercial delivery",
    },
]

CONTINUATION_POLICY = {
    "requires_same_character_identity": True,
    "requires_same_wardrobe_or_logical_variation": True,
    "requires_scene_or_product_state_continuity": True,
    "requires_dialogue_and_narrative_continuity": True,
    "requires_camera_continuity": True,
    "requires_claim_safe_copy_continuity": True,
}

ENGINE_MODE_CAPABILITY_POLICY = {
    "F2V": {
        "supports_generation_modes": ["SINGLE", "EXTEND"],
        "supports_camera_styles": CAMERA_STYLES,
        "supports_visible_creator_default": True,
    },
    "T2V": {
        "supports_generation_modes": ["SINGLE", "EXTEND"],
        "supports_camera_styles": CAMERA_STYLES,
        "supports_visible_creator_default": True,
    },
    "I2V": {
        "supports_generation_modes": ["SINGLE", "EXTEND"],
        "supports_camera_styles": CAMERA_STYLES,
        "supports_visible_creator_default": True,
    },
    "IMG": {
        "supports_generation_modes": ["SINGLE"],
        "supports_camera_styles": CAMERA_STYLES,
        "supports_visible_creator_default": True,
    },
}


def get_runtime_config() -> dict[str, Any]:
    return {
        "generation_modes": list(GENERATION_MODES),
        "allowed_block_durations_seconds": list(ALLOWED_BLOCK_DURATIONS_SECONDS),
        "default_block_duration_seconds": DEFAULT_BLOCK_DURATION_SECONDS,
        "camera_styles": deepcopy(CAMERA_STYLE_REGISTRY),
        "character_presence_options": [
            {
                "id": "VISIBLE_CREATOR",
                "label": "Visible Creator",
                "is_default": True,
                "warning": None,
            },
            {
                "id": "FACELESS",
                "label": "Faceless",
                "is_default": False,
                "warning": "Faceless output is explicit-only and must be operator-selected.",
            },
        ],
        "persona_registry": deepcopy(PERSONA_REGISTRY),
        "language_wps_policy": deepcopy(LANGUAGE_WPS_POLICY),
        "shot_count_policy": deepcopy(SHOT_COUNT_POLICY),
        "continuation_policy": deepcopy(CONTINUATION_POLICY),
        "engine_mode_capability_policy": deepcopy(ENGINE_MODE_CAPABILITY_POLICY),
        "defaults": {
            "generation_mode": "SINGLE",
            "block_duration_seconds": DEFAULT_BLOCK_DURATION_SECONDS,
            "camera_style": DEFAULT_CAMERA_STYLE,
            "character_presence": DEFAULT_CHARACTER_PRESENCE,
            "target_language": DEFAULT_TARGET_LANGUAGE,
            "creator_persona": DEFAULT_CREATOR_PERSONA,
            "overlay_enabled": False,  # NO_OVERLAY law (retained authority, ADR-008): default OFF
            "dialogue_enabled": True,
            "block_2_duration_seconds": DEFAULT_BLOCK_DURATION_SECONDS,
        },
    }


def normalize_generation_mode(value: str | None) -> str:
    candidate = str(value or "").strip().upper() or "SINGLE"
    if candidate not in GENERATION_MODES:
        raise ValueError(f"INVALID_GENERATION_MODE:{candidate}")
    return candidate


def normalize_camera_style(value: str | None) -> str:
    candidate = str(value or "").strip().upper() or DEFAULT_CAMERA_STYLE
    if candidate not in CAMERA_STYLES:
        raise ValueError(f"INVALID_CAMERA_STYLE:{candidate}")
    return candidate


def normalize_character_presence(value: str | None) -> str:
    candidate = str(value or "").strip().upper() or DEFAULT_CHARACTER_PRESENCE
    if candidate not in CHARACTER_PRESENCE_OPTIONS:
        raise ValueError(f"INVALID_CHARACTER_PRESENCE:{candidate}")
    return candidate


def normalize_target_language(value: str | None) -> str:
    candidate = str(value or "").strip().upper() or DEFAULT_TARGET_LANGUAGE
    if candidate not in LANGUAGE_WPS_POLICY:
        raise ValueError(f"INVALID_TARGET_LANGUAGE:{candidate}")
    return candidate


def normalize_creator_persona(value: str | None) -> str:
    candidate = str(value or "").strip().upper() or DEFAULT_CREATOR_PERSONA
    valid = {item["id"] for item in PERSONA_REGISTRY}
    if candidate not in valid:
        raise ValueError(f"INVALID_CREATOR_PERSONA:{candidate}")
    return candidate


def validate_duration_seconds(duration_seconds: int) -> int:
    if duration_seconds not in ALLOWED_BLOCK_DURATIONS_SECONDS:
        raise ValueError(f"INVALID_BLOCK_DURATION_SECONDS:{duration_seconds}")
    return duration_seconds


def get_language_policy(target_language: str) -> dict[str, float]:
    normalized = normalize_target_language(target_language)
    return deepcopy(LANGUAGE_WPS_POLICY[normalized])


def get_shot_policy(duration_seconds: int) -> dict[str, int]:
    duration = validate_duration_seconds(duration_seconds)
    return deepcopy(SHOT_COUNT_POLICY[duration])


def get_engine_mode_capability(mode: str) -> dict[str, Any]:
    return deepcopy(ENGINE_MODE_CAPABILITY_POLICY.get(str(mode or "").strip().upper(), {}))


def dialogue_word_budget(duration_seconds: int, target_language: str, *, dialogue_enabled: bool) -> int:
    if not dialogue_enabled:
        return 0
    policy = get_language_policy(target_language)
    budget = floor(duration_seconds * float(policy["body_wps"]))
    return max(1, budget)

