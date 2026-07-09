"""Dry-run proof of execution-lane reference ORDERING (no Flow upload).

Incident 2026-07-09 item 6: prove the final execution payload orders reference
images deterministically for F2V/HYBRID/I2V without a live generation. The order
is fixed by the pure helper agent.api.flow.ordered_ref_slots (startAsset first,
then subject, scene, style, image), which both the one-door /generate lane and
the manual lane consume. Asserting on it is the instrumented request-builder proof.
"""

from agent.api.flow import REF_SLOT_ORDER, ordered_ref_slots


def _a(name):
    # A minimal non-empty asset dict (truthy) with an identifiable id.
    return {"assetId": name, "downloadUrl": f"https://example/{name}"}


def test_ref_slot_order_is_the_canonical_contract():
    assert REF_SLOT_ORDER == (
        ("subjectAsset", "Subject"),
        ("sceneAsset", "Scene"),
        ("styleAsset", "Style"),
        ("imageAsset", "Image"),
    )


def test_i2v_full_ref_ordering_subject_scene_style():
    refs = {
        # Deliberately out of order in the dict to prove order is by the
        # canonical tuple, not by caller dict insertion order.
        "styleAsset": _a("style"),
        "subjectAsset": _a("subject"),
        "sceneAsset": _a("scene"),
    }
    slots = ordered_ref_slots(None, refs)
    assert [label for label, _ in slots] == ["Subject", "Scene", "Style"]
    assert [asset["assetId"] for _, asset in slots] == ["subject", "scene", "style"]


def test_f2v_start_frame_leads_then_product_ref():
    # F2V/HYBRID execution: startAsset (start frame / product anchor) is index 0,
    # any product reference rides as an imageAsset ref after it.
    slots = ordered_ref_slots(_a("start_frame"), {"imageAsset": _a("product_ref")})
    assert [label for label, _ in slots] == ["Start", "Image"]
    assert [asset["assetId"] for _, asset in slots] == ["start_frame", "product_ref"]


def test_hybrid_start_first_then_subject_scene_style():
    slots = ordered_ref_slots(
        _a("start"),
        {"subjectAsset": _a("subj"), "sceneAsset": _a("scn"), "styleAsset": _a("sty")},
    )
    assert [label for label, _ in slots] == ["Start", "Subject", "Scene", "Style"]


def test_empty_and_missing_slots_are_skipped_not_reordered():
    # Empty dicts / None are dropped; present slots keep canonical order.
    slots = ordered_ref_slots(
        None,
        {"subjectAsset": _a("subj"), "sceneAsset": {}, "styleAsset": _a("sty")},
    )
    assert [label for label, _ in slots] == ["Subject", "Style"]


def test_no_assets_yields_empty_ordering():
    assert ordered_ref_slots(None, None) == []
    assert ordered_ref_slots({}, {}) == []
