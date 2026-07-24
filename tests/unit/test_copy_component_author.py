"""Phase B2 — AI component authoring: validation, fail-closed paths, brief."""
import asyncio
import json

import pytest

from agent.services import copy_component_author_service as svc
from agent.services import copy_component_service as comp

PERSONA = {
    "audience": "Ibu bapa di Malaysia",
    "pains": [
        "Anak sering menangis malam akibat perut kembung",
        "Sengal-sengal badan selepas bekerja",
    ],
    "desires": ["Anak tidur lena tanpa menangis malam", "Badan rasa ringan"],
}
PRODUCT = {"id": "p1", "product_display_name": "Minyak Warisan Tok Cap Burung 25ml"}


class _Grounding:
    class _K:
        benefits = ["Melegakan perut kembung"]
        usps = ["Formula tradisional"]

    class _P:
        tone = "mesra"
        pronoun = "anda"

    class _G:
        banned_terms = ["cure"]
        blocked_claims = []

    product_knowledge = _K()
    buyer_persona = _P()
    claim_guardrails = _G()


def _angle():
    from agent.services import copy_angle_derivation as der

    return der.derive_angles(PERSONA)["angles"][0]


# ---- pure helpers -------------------------------------------------------

def test_slot_fields_place_text_in_its_real_copy_slot():
    """The claim scanner must see the text exactly where it will appear."""
    assert svc._slot_fields(comp.HOOK, "x") == {"hook": "x"}
    assert svc._slot_fields(comp.SUBHOOK, "x") == {"subhook": "x"}
    assert svc._slot_fields(comp.CTA, "x") == {"cta": "x"}
    assert svc._slot_fields(comp.USP_SET, ["a", "b"]) == {"usp_set": ["a", "b"]}


def test_brief_targets_one_angle_and_one_type():
    system, user = svc.build_brief(PRODUCT, _Grounding(), _angle(), comp.HOOK, 6)
    payload = json.loads(user)
    assert payload["component_type_rules"].startswith("HOOK")
    assert "perut kembung" in payload["angle"]["pain"]
    assert payload["task"].startswith("Write 6 DISTINCT HOOK")
    assert "medical" in " ".join(payload["hard_rules"]).lower()
    assert "Never write a complete ad" in system


def test_brief_carries_product_truth_and_guardrails():
    _, user = svc.build_brief(PRODUCT, _Grounding(), _angle(), comp.USP_SET, 3)
    payload = json.loads(user)
    assert payload["product_benefits"] == ["Melegakan perut kembung"]
    assert payload["banned_terms"] == ["cure"]
    assert '"usps"' in payload["output_schema"]


def test_extract_handles_both_shapes_and_drops_empties():
    assert svc._extract({"items": [{"text": "A"}, {"text": "  "}, {"text": "B"}]}, comp.HOOK) == ["A", "B"]
    assert svc._extract({"items": [{"usps": ["a", "b", ""]}]}, comp.USP_SET) == [["a", "b"]]
    assert svc._extract({}, comp.HOOK) == []
    assert svc._extract(None, comp.HOOK) == []
    assert svc._extract({"items": "nope"}, comp.HOOK) == []


# ---- fail-closed validation --------------------------------------------

def test_unknown_component_type_is_refused():
    with pytest.raises(ValueError, match="UNKNOWN_COMPONENT_TYPE"):
        asyncio.run(svc.author_components("p1", "ang_x", "BODY", 6))


def test_count_bounds_are_enforced():
    for bad in (0, 1, svc.MAX_PER_CALL + 1):
        with pytest.raises(ValueError, match="COUNT_OUT_OF_RANGE"):
            asyncio.run(svc.author_components("p1", "ang_x", comp.HOOK, bad))


def test_unknown_product_is_refused(monkeypatch):
    async def _none(_pid):
        return None

    monkeypatch.setattr(svc.crud, "get_product", _none)
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        asyncio.run(svc.author_components("nope", "ang_x", comp.HOOK, 6))


def test_no_approved_snapshot_is_refused_with_actionable_message(monkeypatch):
    """This is the live Bosmax Herbs 5ML / Bosmax Oil 10ML case: the product
    exists but has no approved intelligence snapshot, so it has no persona and
    therefore no product-specific angles. Authoring must refuse and say what to
    do, not fall back to a generic family label."""
    async def _product(_pid):
        return PRODUCT

    async def _no_snap(_pid):
        return None

    monkeypatch.setattr(svc.crud, "get_product", _product)
    monkeypatch.setattr(
        svc.crud, "get_latest_approved_product_intelligence_snapshot", _no_snap
    )
    with pytest.raises(ValueError, match="NO_APPROVED_SNAPSHOT"):
        asyncio.run(svc.author_components("p1", "ang_x", comp.HOOK, 6))


def test_unknown_angle_key_lists_the_available_ones(monkeypatch):
    async def _product(_pid):
        return PRODUCT

    async def _snap(_pid):
        return {"buyer_persona_snapshot_json": PERSONA}

    monkeypatch.setattr(svc.crud, "get_product", _product)
    monkeypatch.setattr(
        svc.crud, "get_latest_approved_product_intelligence_snapshot", _snap
    )
    with pytest.raises(ValueError, match="UNKNOWN_ANGLE_KEY") as ei:
        asyncio.run(svc.author_components("p1", "ang_wrong", comp.HOOK, 6))
    assert "available=ang_" in str(ei.value)


def test_persona_stored_as_json_string_is_parsed(monkeypatch):
    """Snapshots come back with JSON columns as strings from some paths."""
    async def _product(_pid):
        return PRODUCT

    async def _snap(_pid):
        return {"buyer_persona_snapshot_json": json.dumps(PERSONA)}

    monkeypatch.setattr(svc.crud, "get_product", _product)
    monkeypatch.setattr(
        svc.crud, "get_latest_approved_product_intelligence_snapshot", _snap
    )
    with pytest.raises(ValueError, match="UNKNOWN_ANGLE_KEY"):
        asyncio.run(svc.author_components("p1", "ang_wrong", comp.HOOK, 6))


def test_dry_run_never_calls_the_provider_and_never_persists(monkeypatch):
    async def _product(_pid):
        return PRODUCT

    async def _snap(_pid):
        return {"buyer_persona_snapshot_json": PERSONA}

    async def _grounding(_p):
        return _Grounding()

    def _boom(*_a, **_k):  # noqa: ANN002
        raise AssertionError("provider must NOT be called on a dry run")

    async def _no_create(*_a, **_k):  # noqa: ANN002
        raise AssertionError("dry run must NOT persist")

    monkeypatch.setattr(svc.crud, "get_product", _product)
    monkeypatch.setattr(
        svc.crud, "get_latest_approved_product_intelligence_snapshot", _snap
    )
    monkeypatch.setattr(svc.crud, "create_copy_component", _no_create)
    monkeypatch.setattr(svc.ai_provider, "complete_json", _boom)
    import agent.services.copy_grounding_service as cgs

    monkeypatch.setattr(cgs, "resolve_copy_grounding", _grounding)

    key = _angle()["angle_key"]
    out = asyncio.run(
        svc.author_components("p1", key, comp.HOOK, 6, dry_run=True)
    )
    assert out["dry_run"] is True
    assert out["created_count"] == 0
    assert "DRY_RUN_NO_PERSIST" in out["warnings"]
    assert out["brief_preview"]["system"]
    assert out["angle_label"].startswith("Anak sering menangis")


def test_candidates_are_never_auto_approved():
    assert svc.STATUS_REVIEW_REQUIRED == "COMPONENT_REVIEW_REQUIRED"
    assert svc.STATUS_REVIEW_REQUIRED != comp.STATUS_APPROVED
