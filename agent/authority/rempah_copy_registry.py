"""P3B authority registry for the verified rempah/seasoning batch.

This is a bounded, non-persisting preview authority. It contains only the two
product IDs approved through the P2.6B admin review campaign. Copy is tailored
to each dish while remaining claim-safe and grounded in normal cooking use.
"""
from __future__ import annotations

from typing import Final, Literal, TypedDict


class RempahScriptSlot(TypedDict):
    hook_line: str
    demo_line: str
    benefit_line: str
    cta_line: str
    overlay_text: str


class RempahCopyRegistryEntry(TypedDict):
    copy_strategy_id: str
    dish_context: str
    scene_action_indices: tuple[Literal[1], Literal[2], Literal[3]]
    scripts: dict[int, RempahScriptSlot]


REMPAH_COPY_REGISTRY: Final[dict[str, RempahCopyRegistryEntry]] = {
    "0a26caf0-1bc6-43a9-a267-7d2a1dbaccab": {
        "copy_strategy_id": "P3B_REMPAH_NASI_KHOWMOK_V1",
        "dish_context": "nasi khowmok",
        "scene_action_indices": (1, 2, 3),
        "scripts": {
            8: {
                "hook_line": "Nak nasi khowmok lagi wangi?",
                "demo_line": "Masukkan rempah dan gaul rata.",
                "benefit_line": "Aroma nasi lebih naik.",
                "cta_line": "Semak pek 140g.",
                "overlay_text": "REMPAH NASI KHOWMOK • PEK 140G",
            },
            10: {
                "hook_line": "Nak nasi khowmok yang lebih harum?",
                "demo_line": "Masukkan rempah, gaul rata dan masak bersama nasi.",
                "benefit_line": "Langkah masak ringkas, aroma nasi lebih naik.",
                "cta_line": "Semak pek 140g.",
                "overlay_text": "MASUKKAN • GAUL • MASAK",
            },
            16: {
                "hook_line": (
                    "Nak nasi khowmok beraroma tanpa langkah rempah yang rumit?"
                ),
                "demo_line": (
                    "Masukkan rempah ke dalam nasi, gaul rata dan teruskan proses "
                    "memasak."
                ),
                "benefit_line": (
                    "Rempah memudahkan langkah masak sambil menaikkan aroma nasi."
                ),
                "cta_line": "Semak pek 140g sebelum mula masak.",
                "overlay_text": "NASI KHOWMOK • AROMA REMPAH",
            },
        },
    },
    "3f0e0206-a21a-4db6-a323-170ce505703f": {
        "copy_strategy_id": "P3B_REMPAH_AYAM_MADU_V1",
        "dish_context": "ayam madu",
        "scene_action_indices": (1, 2, 3),
        "scripts": {
            8: {
                "hook_line": "Nak ayam madu lebih beraroma?",
                "demo_line": "Tabur rempah dan gaul rata.",
                "benefit_line": "Rasa rempah lebih naik.",
                "cta_line": "Semak pek 100g.",
                "overlay_text": "REMPAH AYAM MADU • 100G",
            },
            10: {
                "hook_line": "Nak ayam madu yang lebih beraroma?",
                "demo_line": "Tabur rempah pada ayam dan gaul sampai rata.",
                "benefit_line": "Langkah masak ringkas, aroma rempah lebih naik.",
                "cta_line": "Semak pek 100g.",
                "overlay_text": "TABUR • GAUL • MASAK",
            },
            16: {
                "hook_line": (
                    "Nak ayam madu beraroma tanpa bancuhan yang rumit?"
                ),
                "demo_line": (
                    "Tabur rempah pada ayam, gaul rata dan teruskan proses memasak."
                ),
                "benefit_line": (
                    "Rempah memudahkan langkah masak sambil menaikkan aroma ayam."
                ),
                "cta_line": "Semak pek 100gram sebelum mula masak.",
                "overlay_text": "AYAM MADU • HASIL MASAKAN",
            },
        },
    },
}

P3B_ALLOWED_PRODUCT_IDS: Final[frozenset[str]] = frozenset(
    REMPAH_COPY_REGISTRY
)
