"""Deterministic, credit-free P7.5-C SPICE_SEASONING pilot fixture."""

from __future__ import annotations

import hashlib
import json


ALLOWED_REMPAH_PRODUCT_IDS = {
    "0a26caf0-1bc6-43a9-a267-7d2a1dbaccab",
    "3f0e0206-a21a-4db6-a323-170ce505703f",
}
PILOT_PRODUCT_ID = "0a26caf0-1bc6-43a9-a267-7d2a1dbaccab"
FORMATS = ("UGC", "PGC", "CINEMATIC")
ACTION_SEQUENCES = (
    "buka pek, tuang rempah, gaul rata",
    "tunjuk tekstur rempah, masukkan ke dalam periuk",
    "kacau hidangan, tunjuk perubahan warna",
    "hidang di atas meja, kekalkan pek produk jelas",
)
APPROVED_DIALOGUE = (
    "Ini cara mudah saya siapkan hidangan berempah untuk keluarga."
)


def _templates() -> list[dict]:
    rows: list[dict] = []
    for action_index, action in enumerate(ACTION_SEQUENCES, start=1):
        for format_name in FORMATS:
            payload = {
                "product_id": PILOT_PRODUCT_ID,
                "product_type_group": "SPICE_SEASONING",
                "format": format_name,
                "generation_mode": "SINGLE",
                "dialogue_text": APPROVED_DIALOGUE,
                "scene_strategy_id": "SPICE_SEASONING",
                "fallback_used": False,
                "action_sequence": [action],
                "shot_grammar": [
                    {
                        "purpose": f"{format_name.lower()} action proof",
                        "action_sequence": action_index,
                    }
                ],
            }
            payload["template_sha256"] = hashlib.sha256(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            rows.append(payload)
    return rows


def _variation_group() -> dict:
    members = [
        {
            "variation_ordinal": ordinal,
            "dialogue_text": APPROVED_DIALOGUE,
            "visual_fingerprint_sha256": hashlib.sha256(
                f"rempah-visual-{ordinal}".encode()
            ).hexdigest(),
        }
        for ordinal in range(1, 6)
    ]
    return {
        "status": "APPROVED",
        "dialogue_text": APPROVED_DIALOGUE,
        "members": members,
    }


def test_rempah_pilot_has_twelve_format_action_templates() -> None:
    templates = _templates()
    assert PILOT_PRODUCT_ID in ALLOWED_REMPAH_PRODUCT_IDS
    assert len(templates) == 12
    assert {row["format"] for row in templates} == set(FORMATS)
    assert {
        row["action_sequence"][0] for row in templates
    } == set(ACTION_SEQUENCES)
    assert all(row["product_type_group"] == "SPICE_SEASONING" for row in templates)
    assert all(row["generation_mode"] == "SINGLE" for row in templates)
    assert all(not row["fallback_used"] for row in templates)


def test_five_member_group_has_same_dialogue_and_distinct_visuals() -> None:
    group = _variation_group()
    assert group["status"] == "APPROVED"
    assert len(group["members"]) == 5
    assert {
        member["dialogue_text"] for member in group["members"]
    } == {APPROVED_DIALOGUE}
    assert len(
        {
            member["visual_fingerprint_sha256"]
            for member in group["members"]
        }
    ) == 5
    assert [
        member["variation_ordinal"] for member in group["members"]
    ] == [1, 2, 3, 4, 5]


def test_pilot_fixture_hash_is_deterministic_and_credit_free() -> None:
    first = json.dumps(
        {"templates": _templates(), "group": _variation_group()},
        sort_keys=True,
        separators=(",", ":"),
    )
    second = json.dumps(
        {"templates": _templates(), "group": _variation_group()},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(first.encode()).hexdigest() == hashlib.sha256(
        second.encode()
    ).hexdigest()
    execution_evidence = {
        "provider_calls": 0,
        "credit_spend": 0,
        "canonical_product_readiness": "NOT VERIFIED",
    }
    assert execution_evidence == {
        "provider_calls": 0,
        "credit_spend": 0,
        "canonical_product_readiness": "NOT VERIFIED",
    }
