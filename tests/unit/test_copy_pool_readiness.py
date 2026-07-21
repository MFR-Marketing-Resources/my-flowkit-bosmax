"""Approved copy-pool readiness — can a product supply N UNIQUE dialogues?

A ``copy_set`` stores copy INGREDIENTS (angle/hook/subhook/usp/cta); there is no
dialogue column. Dialogue only exists once the canonical compiler renders SECTION
6, so "N unique dialogues available" can NEVER be answered by counting approved
rows — two distinct approved copy sets can compile to identical dialogue. These
tests pin that distinction, plus the fail-closed statuses the Studio gates on.

Readiness is READ-ONLY and CREDIT-FREE: no provider call, no Flow call, no DB
write, no approval, no live job. Nothing here relaxes the preview's fail-closed
uniqueness contract.
"""
import asyncio

from agent.services import copy_rotation_service
from agent.services import workspace_execution_package_service as wxp
from agent.services import workspace_generation_package_service as svc


def _approved(cs_id, **over):
    """A rotation-ELIGIBLE approved copy set row, with truth/compliance attached."""
    row = {
        "copy_set_id": cs_id,
        "product_id": "P",
        "status": "COPY_APPROVED",
        "archived": 0,
        "usage_count": 0,
        "angle": f"angle {cs_id}",
        "hook": f"hook {cs_id}",
        "subhook": f"subhook {cs_id}",
        "cta": "beli sekarang",
        "usp_set_json": '["usp"]',
        "provenance_json": '{"resolver": "ai_copy_assist_service"}',
        "claim_review_json": '{"approved": true, "safety": {"safe": true}}',
        "created_at": f"2026-07-20T00:00:0{cs_id[-1]}Z",
        "last_used_at": None,
    }
    row.update(over)
    return row


def _fake_pool(rows):
    async def _list(product_id):
        return list(rows)
    return _list


def _fake_compile(dialogue_by_copy_set, *, counter=None):
    async def _compile(**kw):
        if counter is not None:
            counter.append(kw)
        cs = kw.get("copy_set_id")
        dialogue = dialogue_by_copy_set.get(cs, f"fallback dialogue {cs}")
        return {
            "final_compiled_prompt_text": f"SECTION 6\n{dialogue}\nSECTION 7",
            "prompt_blocks": [{"exact_dialogue_slice": dialogue, "audio_seam_contract": {}}],
        }
    return _compile


def _readiness(monkeypatch, pool_rows, dialogues, *, quantity, counter=None):
    monkeypatch.setattr(copy_rotation_service, "list_eligible_copy_sets", _fake_pool(pool_rows))
    monkeypatch.setattr(
        wxp, "compile_workspace_prompt_preview", _fake_compile(dialogues, counter=counter))
    return asyncio.run(svc.evaluate_copy_pool_readiness(
        product_id="P", logical_mode="T2V", source_mode="T2V", quantity=quantity))


# ── eligibility: only COPY_APPROVED copy is usable ───────────────────────────
def test_unapproved_candidates_are_not_eligible(monkeypatch):
    """AI candidates land in COPY_REVIEW_REQUIRED and must NEVER be counted or used."""
    rows = [
        _approved("cs1"),
        _approved("cs2", status="COPY_REVIEW_REQUIRED"),   # AI candidate, unreviewed
        _approved("cs3", status="DRAFT_COPY"),
        _approved("cs4", status="COPY_REJECTED"),
        _approved("cs5", archived=1),                      # approved but archived
        _approved("cs6", usage_count=copy_rotation_service.REUSE_CAP),  # retired by cap
    ]
    monkeypatch.setattr(copy_rotation_service.crud, "list_copy_sets_for_product", _fake_pool(rows))
    pool = asyncio.run(copy_rotation_service.list_eligible_copy_sets("P"))
    assert [r["copy_set_id"] for r in pool] == ["cs1"]


def test_approved_variants_are_used_and_keep_truth_and_compliance(monkeypatch):
    """COPY_APPROVED rows ARE used, and rotation never strips provenance/claim review."""
    rows = [_approved("cs1"), _approved("cs2")]
    monkeypatch.setattr(copy_rotation_service.crud, "list_copy_sets_for_product", _fake_pool(rows))
    pool = asyncio.run(copy_rotation_service.list_eligible_copy_sets("P"))
    assert [r["copy_set_id"] for r in pool] == ["cs1", "cs2"]
    for row in pool:
        assert row["status"] == "COPY_APPROVED"
        assert row["provenance_json"]        # product-truth provenance still attached
        assert row["claim_review_json"]      # claim/compliance result still attached


# ── readiness statuses ───────────────────────────────────────────────────────
def test_zero_approved_reports_no_approved_copy_available(monkeypatch):
    out = _readiness(monkeypatch, [], {}, quantity=3)
    assert out["readiness_status"] == "NO_APPROVED_COPY_AVAILABLE"
    assert out["approved_copy_count"] == 0
    assert out["unique_dialogue_count"] == 0
    assert out["shortage_count"] == 3
    assert out["next_action"] == "GENERATE_AND_APPROVE_COPY"
    assert out["scanned_copy_set_count"] == 0


def test_quantity_three_with_three_unique_dialogues_is_ready(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
    out = _readiness(monkeypatch, rows, {"cs1": "aaa", "cs2": "bbb", "cs3": "ccc"}, quantity=3)
    assert out["readiness_status"] == "READY"
    assert out["approved_copy_count"] == 3
    assert out["unique_dialogue_count"] == 3
    assert out["shortage_count"] == 0
    assert out["duplicate_fingerprint_groups"] == []
    assert out["next_action"] is None


def test_hybrid_readiness_compiles_as_f2v_with_hybrid_lineage(monkeypatch):
    """HYBRID is a logical lane; prompt compilation uses its F2V transport."""
    rows = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
    calls: list[dict] = []
    monkeypatch.setattr(copy_rotation_service, "list_eligible_copy_sets", _fake_pool(rows))
    monkeypatch.setattr(
        wxp,
        "compile_workspace_prompt_preview",
        _fake_compile({"cs1": "aaa", "cs2": "bbb", "cs3": "ccc"}, counter=calls),
    )

    out = asyncio.run(svc.evaluate_copy_pool_readiness(
        product_id="P", logical_mode="HYBRID", source_mode="HYBRID", quantity=3))

    assert out["readiness_status"] == "READY"
    assert all(call["mode"] == "F2V" for call in calls)
    assert all(call["source_mode"] == "HYBRID" for call in calls)


def test_quantity_three_with_two_unique_dialogues_reports_shortage_one(monkeypatch):
    """Three APPROVED rows, but two compile to the same dialogue → shortage 1."""
    rows = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
    out = _readiness(monkeypatch, rows, {"cs1": "aaa", "cs2": "aaa", "cs3": "bbb"}, quantity=3)
    assert out["readiness_status"] == "COPY_POOL_SHORTAGE"
    assert out["approved_copy_count"] == 3      # row count says "enough"...
    assert out["unique_dialogue_count"] == 2    # ...dialogue truth says otherwise
    assert out["shortage_count"] == 1
    assert out["next_action"] == "GENERATE_AND_APPROVE_COPY"


def test_duplicate_dialogue_does_not_increase_unique_count(monkeypatch):
    """Five approved rows all compiling to ONE dialogue = unique pool of 1."""
    rows = [_approved(f"cs{i}") for i in range(1, 6)]
    out = _readiness(monkeypatch, rows, {f"cs{i}": "identical" for i in range(1, 6)}, quantity=5)
    assert out["approved_copy_count"] == 5
    assert out["unique_dialogue_count"] == 1
    assert out["shortage_count"] == 4
    assert out["readiness_status"] == "COPY_POOL_SHORTAGE"
    groups = out["duplicate_fingerprint_groups"]
    assert len(groups) == 1
    assert sorted(groups[0]["copy_set_ids"]) == ["cs1", "cs2", "cs3", "cs4", "cs5"]


def test_empty_dialogue_is_not_counted_as_unique(monkeypatch):
    """A copy set that compiles to nothing must not inflate the usable pool."""
    rows = [_approved("cs1"), _approved("cs2")]
    out = _readiness(monkeypatch, rows, {"cs1": "aaa", "cs2": "   "}, quantity=2)
    assert out["unique_dialogue_count"] == 1
    assert out["shortage_count"] == 1
    assert any("EMPTY_DIALOGUE" in e for e in out["compile_errors"])


def test_compile_failure_blocks_only_that_copy_set(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2")]

    async def _compile(**kw):
        if kw.get("copy_set_id") == "cs1":
            raise ValueError("boom")
        return {"final_compiled_prompt_text": "SECTION 6\nbbb\nSECTION 7",
                "prompt_blocks": [{"exact_dialogue_slice": "bbb", "audio_seam_contract": {}}]}

    monkeypatch.setattr(copy_rotation_service, "list_eligible_copy_sets", _fake_pool(rows))
    monkeypatch.setattr(wxp, "compile_workspace_prompt_preview", _compile)
    out = asyncio.run(svc.evaluate_copy_pool_readiness(
        product_id="P", logical_mode="T2V", source_mode="T2V", quantity=2))
    assert out["unique_dialogue_count"] == 1
    assert any(e.startswith("cs1:ValueError") for e in out["compile_errors"])


# ── credit-free / no-live contract ───────────────────────────────────────────
def test_readiness_is_credit_free_and_touches_no_flow_or_provider(monkeypatch):
    rows = [_approved("cs1"), _approved("cs2"), _approved("cs3")]
    calls: list = []
    out = _readiness(
        monkeypatch, rows, {"cs1": "aaa", "cs2": "bbb", "cs3": "ccc"},
        quantity=3, counter=calls)
    assert out["credit"] == "NONE"
    assert out["provider_calls"] == 0
    assert out["flow_calls"] == 0
    # the ONLY work done is credit-free compilation, once per scanned copy set
    assert len(calls) == 3
    # nothing in the compiled request asks for generation/enqueue/live
    for kw in calls:
        assert "confirm_live_credit_burn" not in kw
        assert "aspect_ratio" not in kw
    # read-only: no run/job/package identity is minted
    for key in ("production_run_id", "workspace_generation_package_id", "video_job_id"):
        assert key not in out


def test_readiness_early_exits_once_quantity_is_satisfied(monkeypatch):
    """A large healthy pool must not compile more than it needs to prove READY."""
    rows = [_approved(f"cs{i}") for i in range(1, 11)]
    calls: list = []
    out = _readiness(
        monkeypatch, rows, {f"cs{i}": f"dialogue {i}" for i in range(1, 11)},
        quantity=3, counter=calls)
    assert out["readiness_status"] == "READY"
    assert len(calls) == 3          # stopped as soon as 3 distinct dialogues existed
    assert out["scanned_copy_set_count"] == 3
    assert out["approved_copy_count"] == 10


def test_quantity_out_of_range_fails_closed(monkeypatch):
    monkeypatch.setattr(copy_rotation_service, "list_eligible_copy_sets", _fake_pool([]))
    for bad in (0, -1, svc.QUANTITY_PREVIEW_MAX + 1):
        try:
            asyncio.run(svc.evaluate_copy_pool_readiness(
                product_id="P", logical_mode="T2V", quantity=bad))
        except ValueError as exc:
            assert "QUANTITY_OUT_OF_RANGE" in str(exc)
        else:
            raise AssertionError(f"quantity {bad} should have failed closed")
