"""Immutable render-artifact cache + full-lineage staleness (amendments 5 & cache).

Proves a cache hit costs ZERO provider calls, that a compatibility-map change stales
the session even with unchanged benefit text, that the render_key binds the copy
-authoring lineage, and that the bounded output budget stays within the transport
ceiling. PROVIDER-FREE.
"""

from agent.db import copy_render_crud as crud
from agent.db import creative_factory_crud as cfc
from agent.db.schema import get_db
from agent.models.copy_render_v1 import DEFAULT_WPS_MODE
from agent.services import copy_render_combination_service as comb
from agent.services import copy_render_service as svc
from agent.services.ai_copy_provider_adapter import OPENAI_COMPATIBLE_JSON_MAX_TOKENS
import pytest
from tests.copy_render_support import StitchFake, bootstrap_ready_benefit, real_calls


class ExplodingProvider:
    """Any provider call is a test failure — a full cache hit must not call out."""

    def complete_json_with_receipt(self, *a, **k):  # pragma: no cover - must never run
        raise AssertionError("provider called on a full cache hit")


async def test_full_cache_hit_costs_zero_provider_calls():
    before = real_calls()
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="HYBRID", target_count=5, duration_seconds=16)
    session_row = await crud.get_session(s["session_id"])

    # Pre-seed the immutable cache for EXACTLY the 5 recipes the first batch will
    # select (same deterministic seed the service uses on batch #1).
    recipes = await comb.enumerate_recipes(boot["benefit_id"])
    first5 = comb.select_diverse(recipes, set(), seed=f"{s['session_id']}:1", count=len(recipes))[:5]
    for i, rec in enumerate(first5):
        stages = [{"stage_key": k, "text": f"{k} kulit lembap segar unik {i}"}
                  for k in ("problem", "agitate", "solution", "cta")]
        full = " ".join(x["text"] for x in stages)
        await crud.get_or_create_artifact(svc._artifact_row(session_row, rec, stages, full, {}))

    r = await svc.generate_suggestions(s["session_id"], "req-cache-00001", provider=ExplodingProvider())
    shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    assert len(shown) == 5 and r["provider_calls"] == 0
    batch = r["batches"][-1]
    assert batch["cache_hit_count"] == 5 and batch["provider_calls"] == 0
    assert real_calls() == before


async def test_compat_map_change_stales_session():
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="HYBRID", target_count=3, duration_seconds=16)
    # Introduce ONE compatibility triple for an existing angle. Benefit text is
    # unchanged, but the active compatibility map now differs → session stales.
    atoms = await cfc.get_benefit_atoms(boot["benefit_id"], status="ACTIVE")
    angle_id = atoms["angle"][0]["angle_id"]
    hook = next(h for h in atoms["hook"] if h["angle_id"] == angle_id)
    body = next(b for b in atoms["body"] if b["angle_id"] == angle_id)
    cta = next(c for c in atoms["cta"] if c["angle_id"] == angle_id)
    db = await get_db()
    await db.execute(
        "INSERT INTO creative_atom_compatibility (hook_id, body_id, cta_id, angle_id) VALUES (?,?,?,?)",
        (hook["hook_id"], body["body_id"], cta["cta_id"], angle_id))
    await db.commit()

    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-stale-00001", provider=StitchFake())
    assert e.value.code == "COPY_RENDER_SESSION_STALE"
    assert "ATOM_BUILD_CHANGED" in e.value.details["reasons"]
    assert (await crud.get_session(s["session_id"]))["status"] == "STALE"


def _base_session():
    return {
        "product_id": "p", "pi_snapshot_id": "snap", "pi_snapshot_version": 1,
        "benefit_digest": "b" * 64, "formula_id": "PAS", "formula_version": "v1",
        "duration_seconds": 16, "target_language": "BM_MS", "wps_mode": DEFAULT_WPS_MODE,
        "wps_authority_version": "wv", "wps_authority_digest": "wd",
        "renderer_prompt_version": "rp", "safety_policy_version": "sp",
    }


def test_render_key_binds_full_copy_authoring_lineage():
    base = _base_session()
    fp = "f" * 64
    baseline = svc._render_key(base, fp)
    for field, newval in [("duration_seconds", 32), ("formula_id", "FAB"),
                          ("formula_version", "v2"), ("target_language", "EN"),
                          ("wps_authority_digest", "wd2"), ("wps_mode", "PUNCHY"),
                          ("benefit_digest", "c" * 64)]:
        variant = dict(base, **{field: newval})
        assert svc._render_key(variant, fp) != baseline, f"{field} must change render_key"
    # a different recipe fingerprint changes the key too
    assert svc._render_key(base, "g" * 64) != baseline


def test_output_token_budget_stays_within_transport_ceiling():
    # For the tested duration budgets the request stays well under the ceiling…
    for wb in (44, 80, 120):
        assert svc.output_token_budget(wb, 5) <= OPENAI_COMPATIBLE_JSON_MAX_TOKENS
    # …and even an absurd budget is CLAMPED, never exceeding the transport ceiling.
    assert svc.output_token_budget(100000, 5) == OPENAI_COMPATIBLE_JSON_MAX_TOKENS
