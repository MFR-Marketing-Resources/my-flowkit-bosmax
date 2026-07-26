import pytest

from agent.db import crud


def _event(activation_id: str, fingerprint: str = "fp", product_id: str | None = None) -> dict:
    return {
        "activation_id": activation_id, "source_template_id": "SCN-BEAUTY-01",
        "candidate_fingerprint": fingerprint, "review_id": "review-1", "reviewed_via_product_id": product_id,
        "cluster": "Beauty", "scene_code": f"SCN_{activation_id}", "scene_name": activation_id,
        "activated_by": "owner", "activation_note": None, "bridge_digest_before": None,
        "bridge_digest_after": "after", "activated_at": "2026-07-26T12:00:00Z",
    }


@pytest.mark.asyncio
async def test_activation_ledger_is_append_only_and_exact_lookup_is_deterministic():
    await crud.append_scene_context_promotion_activation_events([_event("activation-first")])
    await crud.append_scene_context_promotion_activation_events([_event("activation-second")])
    latest = await crud.get_scene_context_promotion_activation_exact("SCN-BEAUTY-01", "fp")
    assert latest["activation_id"] == "activation-second"
    history = await crud.list_scene_context_promotion_activation_history(source_template_id="SCN-BEAUTY-01")
    assert [event["activation_id"] for event in history[:2]] == ["activation-second", "activation-first"]


@pytest.mark.asyncio
async def test_activation_history_filters_by_product_without_touching_review_ledger():
    first = await crud.create_product("Activation product one")
    second = await crud.create_product("Activation product two")
    await crud.append_scene_context_promotion_activation_events([_event("activation-p1", "fp-p1", first["id"])])
    await crud.append_scene_context_promotion_activation_events([_event("activation-p2", "fp-p2", second["id"])])
    history = await crud.list_scene_context_promotion_activation_history(product_id=first["id"])
    assert [event["activation_id"] for event in history] == ["activation-p1"]
