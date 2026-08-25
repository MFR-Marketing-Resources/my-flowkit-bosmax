"""Mascot Montage V1.1 wiring — per-scene grammar reaches the compiler distinctly,
single-block finalizes without concat, multi-block uses discrete assembly."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.services import montage_mascot_creative_grammar as g
from agent.services.montage_scene_execution_routing import (
    MontageSceneExecutionPlan,
    SceneExecutionRoute,
)
from agent.services.montage_scene_orchestrator import execute_scene_plan
from agent.services.montage_scene_reference_policy import SceneReferencePolicy

MASCOT = {
    "assetId": "ca_m", "mediaId": None, "downloadUrl": "http://x/m.png",
    "previewUrl": "http://x/m.png", "localFilePath": "/tmp/m.png", "fileName": "m",
    "assetSource": "PRODUCT_MASCOT_KEY_VISUAL",
}


def _patch_copy_disabled(monkeypatch):
    async def _d(*_a, **_k):
        return SimpleNamespace(v2_enabled=False)
    monkeypatch.setattr(
        "agent.services.montage_scene_orchestrator.resolve_persisted_copy_execution_binding",
        _d,
    )


def _plan(block_index, objective, visual_action):
    return MontageSceneExecutionPlan(
        scene_id=f"s{block_index + 1}", beat_id=f"b{block_index + 1}",
        block_index=block_index, route=SceneExecutionRoute.IMAGE_FIRST,
        reference_policy=SceneReferencePolicy.START_FRAME, transport_mode="F2V",
        source_mode="FRAMES", image_generation_required=True,
        video_generation_required=True, objective=objective, visual_action=visual_action,
    )


async def test_orchestrator_composes_distinct_per_scene_grammar(monkeypatch):
    """Each mascot scene compiles a DIFFERENT scene_context_override carrying its
    objective/visual_action + grammar — proving they materially reach the compiler
    and prompts differentiate per block."""
    _patch_copy_disabled(monkeypatch)
    captured: list[str] = []

    async def pkg(**kw):
        captured.append(kw.get("scene_context_override"))
        return {"workspace_execution_package_id": "wep", "prompt_text": "p", "execution_allowed": True}

    beats = g.scene_beats(3)
    for i in range(3):
        state = await execute_scene_plan(
            _plan(i, beats[i]["objective"], beats[i]["visual_action"]),
            product_id="p1", package_factory=pkg, model="Veo 3.1 - Lite", duration_seconds=8,
            mascot_start_asset=MASCOT, mascot_block_count=3, mascot_atomic_seconds=8,
            mascot_has_dialogue=True,
            scene_context_override="HOOK: energetic. BACKGROUND: kitchen.",
        )
        assert state.status == "PACKAGE_READY"

    assert len(captured) == 3
    assert len(set(captured)) == 3  # three materially different prompts
    for i, ctx in enumerate(captured):
        low = ctx.lower()
        assert "mouth" in low and "no frozen smile" in low  # lip-sync
        assert "three" in low and "visual" in low  # >=3 visual changes
        assert beats[i]["objective"] in ctx  # objective reaches the compiler
        assert beats[i]["visual_action"] in ctx  # visual_action reaches the compiler
        assert "HOOK: energetic" in ctx  # composed onto, not replacing, hook/bg


async def test_non_mascot_scene_grammar_not_applied(monkeypatch):
    """Regression: a non-mascot scene never gets the mascot grammar override."""
    _patch_copy_disabled(monkeypatch)
    captured: list[str] = []

    async def pkg(**kw):
        captured.append(kw.get("scene_context_override"))
        return {"workspace_execution_package_id": "wep", "prompt_text": "p", "execution_allowed": True}

    plan = MontageSceneExecutionPlan(
        scene_id="s1", beat_id="hook", block_index=0, route=SceneExecutionRoute.IMAGE_FIRST,
        reference_policy=SceneReferencePolicy.PRODUCT_ANCHOR, transport_mode="F2V",
        source_mode="HYBRID", image_generation_required=True, video_generation_required=True,
        objective="o", visual_action="v",
    )
    await execute_scene_plan(
        plan, product_id="p1", package_factory=pkg, model="Veo 3.1 - Lite",
        duration_seconds=8, scene_context_override="PLAIN CONTEXT",
    )
    assert captured == ["PLAIN CONTEXT"]  # untouched


async def test_single_block_finalize_promotes_clip_without_concat(monkeypatch):
    from agent.services import montage_run_service as rs
    monkeypatch.setattr(
        rs, "assess_montage_assembly_readiness",
        lambda scenes: SimpleNamespace(ok=True, clip_media_ids=["clip-9"], blockers=[], code=None, detail=""),
    )
    result = await rs._finalize_single_block_montage_run(
        "run-1", [object()], {"model": "Omni Flash", "duration_seconds": 10},
        job_id=None, dry_run=True,
    )
    assert result["assembly_path"] == "SINGLE_FINALIZE"
    assert result["final_media_id"] == "clip-9"
    assert result["segment_count"] == 1
    assert result["concat"]["invoked"] is False
    assert result["credit_spend"] is False


async def test_single_block_finalize_live_registers_artifact(monkeypatch):
    from agent.services import montage_run_service as rs
    from agent.services import video_artifact_delivery_service as delivery
    monkeypatch.setattr(
        rs, "assess_montage_assembly_readiness",
        lambda scenes: SimpleNamespace(ok=True, clip_media_ids=["clip-9"], blockers=[], code=None, detail=""),
    )

    # The single finished clip is promoted through the SHARED final-delivery path,
    # which requires persisted local-file evidence for the clip (no final artifact
    # without local bytes) and then registers the artifact/result pair.
    async def fake_get_artifact(media_id):
        assert media_id == "clip-9"
        return {"local_path": "/tmp/clip-9.mp4", "size_mb": 1.5, "duration_used": 10}

    monkeypatch.setattr(rs.crud, "get_generated_artifact", fake_get_artifact)

    calls: list = []

    async def fake_register(result, **kw):
        calls.append((result, kw))
        return {
            "status": "COMPLETE",
            "final_media_id": result["final_media_id"],
            "local_path": result["local_path"],
            "size_mb": result.get("size_mb"),
            "size_bytes": 1_572_864,
            "sha256": "a" * 64,
        }

    monkeypatch.setattr(delivery, "register_final_video_artifact", fake_register)

    result = await rs._finalize_single_block_montage_run(
        "run-2",
        [object()],
        {
            "model": "Omni Flash",
            "duration_seconds": 10,
            "staff_id": "staff_pytest_operator",
            "staff_display_name": "Pytest Operator",
        },
        job_id="job-x", dry_run=False,
    )
    assert result["concat"]["status"] == "COMPLETE"
    assert result["final_media_id"] == "clip-9"
    assert result["file_sha256"] == "a" * 64
    assert calls and calls[0][0]["final_media_id"] == "clip-9"
    assert calls[0][0]["local_path"] == "/tmp/clip-9.mp4"
    assert calls[0][1]["mode"] == "MONTAGE"
    assert calls[0][1]["surface_lane"] == "MONTAGE"
    assert calls[0][1]["transport_mode"] == "MONTAGE"
    assert calls[0][1]["provider_generation_type"] == "montage_single_block_final"


async def test_assemble_single_block_run_skips_concat(monkeypatch):
    from agent.services import montage_run_service as rs

    async def fake_run(_run_id):
        return {"config": {"model": "Omni Flash", "duration_seconds": 10, "product_media_id": None},
                "scenes": [{"scene_id": "s1"}]}

    monkeypatch.setattr(rs, "get_montage_discrete_run", fake_run)
    monkeypatch.setattr(rs, "scene_jobs_to_readiness", lambda scenes, product_media_id=None: [object()])
    monkeypatch.setattr(
        rs, "assess_montage_assembly_readiness",
        lambda scenes: SimpleNamespace(ok=True, clip_media_ids=["clip-1"], blockers=[], code=None, detail=""),
    )
    monkeypatch.setattr(rs, "persist_montage_assembly_result", AsyncMock(return_value={}))

    async def concat_should_not_run(**_kw):
        raise AssertionError("concat must NOT be invoked for a single-block montage")

    result = await rs.assemble_from_montage_run("run-1", concat_fn=concat_should_not_run, dry_run=True)
    assert result["assembly_path"] == "SINGLE_FINALIZE"
    assert result["final_media_id"] == "clip-1"


async def test_assemble_multi_block_run_uses_discrete_assembly(monkeypatch):
    from agent.services import montage_run_service as rs

    async def fake_run(_run_id):
        return {"config": {"model": "Omni Flash", "duration_seconds": 10, "product_media_id": None},
                "scenes": [{"scene_id": "s1"}, {"scene_id": "s2"}]}

    monkeypatch.setattr(rs, "get_montage_discrete_run", fake_run)
    monkeypatch.setattr(rs, "scene_jobs_to_readiness", lambda scenes, product_media_id=None: [object(), object()])
    monkeypatch.setattr(
        rs, "assess_montage_assembly_readiness",
        lambda scenes: SimpleNamespace(ok=True, clip_media_ids=["c1", "c2"], blockers=[], code=None, detail=""),
    )
    monkeypatch.setattr(rs, "persist_montage_assembly_result", AsyncMock(return_value={}))
    discrete = AsyncMock(return_value={"assembly_path": "DISCRETE_MONTAGE", "concat": {"status": "SEGMENTS_READY"}})
    monkeypatch.setattr(rs, "assemble_montage_discrete", discrete)

    async def concat_fn(**_kw):
        return {"status": "SEGMENTS_READY"}

    result = await rs.assemble_from_montage_run("run-2", concat_fn=concat_fn, dry_run=True)
    assert result["assembly_path"] == "DISCRETE_MONTAGE"
    discrete.assert_awaited_once()
    # requested_seconds == segment_count × atomic (2 × 10 = 20)
    assert discrete.await_args.kwargs["requested_seconds"] == 20
    assert discrete.await_args.kwargs["segment_seconds"] == 10
