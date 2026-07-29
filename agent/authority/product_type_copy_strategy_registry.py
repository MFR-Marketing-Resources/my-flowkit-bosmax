"""P4 product-type copy strategy authority.

The registry is keyed by verified taxonomy, never by product ID. Templates are
preview-only and receive deterministic, claim-scanned product facts at runtime.
"""
from __future__ import annotations

from typing import Final, Literal, TypedDict


ProductTypeCopyStrategyKey = tuple[str, str, str]


class ProductTypeCopyScriptTemplate(TypedDict):
    hook_line: str
    demo_line: str
    benefit_line: str
    cta_line: str
    overlay_text: str


class ProductTypeCopyStrategyEntry(TypedDict):
    copy_strategy_id: str
    source_strategy: Literal["PRODUCT_TYPE_COPY_STRATEGY_REGISTRY"]
    scene_action_indices: tuple[int, ...]
    scene_result_template: str
    scripts: dict[int, ProductTypeCopyScriptTemplate]


PRODUCT_TYPE_COPY_STRATEGY_REGISTRY: Final[
    dict[ProductTypeCopyStrategyKey, ProductTypeCopyStrategyEntry]
] = {
    ("beauty_makeup", "lipstick_lip_tint", "LIP_COLOR"): {
        "copy_strategy_id": "P4_LIP_COLOR_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 2),
        "scene_result_template": (
            "show shade, colour payoff, texture, and finished-lip result clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat {finish_descriptor}?",
                "demo_line": "Sapu {product_reference} pada bibir.",
                "benefit_line": "{benefit_evidence}.",
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
            10: {
                "hook_line": "Nak lihat {finish_descriptor} dengan lebih jelas?",
                "demo_line": "Sapu {product_reference}, kemudian tunjuk shade.",
                "benefit_line": "{benefit_evidence}.",
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
            16: {
                "hook_line": (
                    "Nak lihat shade dan {finish_descriptor} sebelum pilih?"
                ),
                "demo_line": (
                    "Sapu {product_reference} pada bibir, kemudian tunjuk tekstur "
                    "dan hasil akhir."
                ),
                "benefit_line": (
                    "{benefit_evidence} untuk mudah bandingkan pilihan."
                ),
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
        },
    },
    ("food_cooking", "rempah_seasoning", "SPICE_SEASONING"): {
        "copy_strategy_id": "P4_REMPAH_SEASONING_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (1, 2, 3),
        "scene_result_template": (
            "show the cooking process and finished {use_context} result clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak masak {use_context}?",
                "demo_line": "Tabur {product_reference} dan gaul rata.",
                "benefit_line": "{benefit_evidence}.",
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
            10: {
                "hook_line": (
                    "Nak masak {use_context} dengan langkah yang ringkas?"
                ),
                "demo_line": (
                    "Masukkan {product_reference}, kemudian gaul sampai rata."
                ),
                "benefit_line": "{benefit_evidence}.",
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
            16: {
                "hook_line": (
                    "Nak sediakan {use_context} dengan langkah rempah yang jelas?"
                ),
                "demo_line": (
                    "Masukkan {product_reference}, gaul rata dan teruskan proses "
                    "memasak."
                ),
                "benefit_line": (
                    "{benefit_evidence} sambil proses masak mudah diikuti."
                ),
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
        },
    },
}

PRODUCT_TYPE_COPY_STRATEGY_KEYS: Final[frozenset[ProductTypeCopyStrategyKey]] = (
    frozenset(PRODUCT_TYPE_COPY_STRATEGY_REGISTRY)
)
