"""Contracts for the Social Copy Package layer.

Platform-specific caption/comment copy linked to a generated artifact, with a
claim-safe approval workflow that Postiz Publish later prefills from. These
tests exercise the API route handlers + service directly (no HTTP server), the
same way tests/api/test_postiz_api.py does.
"""
import pytest
from fastapi import HTTPException

from agent.api import social_copy_packages as api
from agent.api.social_copy_packages import (
    ApprovalRequest,
    GenerateRequest,
    UpdateRequest,
)
from agent.db import crud

_MEDIA = "scp_test_media_0001"


async def _seed_artifact(media_id: str = _MEDIA):
    await crud.insert_generated_artifact(
        media_id, job_id="job_x", mode="IMG", artifact_kind="image",
        local_path="/tmp/x.jpg", size_mb=0.2,
    )


async def test_generate_clean_copy_is_ready_and_compliant():
    await _seed_artifact()
    pkg = await api.generate(
        GenerateRequest(
            artifact_media_id=_MEDIA,
            platform="tiktok",
            caption="Standby untuk rutin harian. Tap keranjang kuning.",
            hashtags=["fyp", "#lifestyle"],
            call_to_action="Tap keranjang kuning",
        )
    )
    assert pkg["package_id"].startswith("scp_")
    assert pkg["platform"] == "tiktok"
    assert pkg["status"] == "READY"
    assert pkg["compliance_status"] == "OK"
    assert pkg["hashtags_json"] == ["#fyp", "#lifestyle"]  # normalized to arrays
    assert pkg["blockers_json"] == []


async def test_generate_rejects_unknown_artifact():
    with pytest.raises(HTTPException) as exc:
        await api.generate(
            GenerateRequest(artifact_media_id="nope", platform="tiktok", caption="hi")
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "ARTIFACT_NOT_FOUND"


async def test_unsupported_platform_is_422():
    await _seed_artifact()
    with pytest.raises(HTTPException) as exc:
        await api.generate(
            GenerateRequest(artifact_media_id=_MEDIA, platform="linkedin", caption="hi")
        )
    assert exc.value.status_code == 422


async def test_claim_unsafe_copy_is_blocked_and_cannot_be_approved():
    await _seed_artifact()
    pkg = await api.generate(
        GenerateRequest(
            artifact_media_id=_MEDIA,
            platform="facebook",
            caption="Ubat ni boleh cure sakit dan heal semua penyakit, guaranteed results",
        )
    )
    assert pkg["compliance_status"] == "BLOCKED"
    assert pkg["status"] == "DRAFT"
    assert any(b.startswith("UNSAFE_LANGUAGE") for b in pkg["blockers_json"])

    # Approval must be refused while claim-unsafe.
    with pytest.raises(HTTPException) as exc:
        await api.approve_package(pkg["package_id"], ApprovalRequest())
    assert exc.value.status_code == 409
    assert exc.value.detail == "CLAIM_UNSAFE_CANNOT_APPROVE"


async def test_approve_clean_copy_and_list_by_status():
    await _seed_artifact()
    pkg = await api.generate(
        GenerateRequest(
            artifact_media_id=_MEDIA,
            platform="instagram",
            caption="Compact dan travel friendly untuk rutin harian.",
        )
    )
    approved = await api.approve_package(pkg["package_id"], ApprovalRequest())
    assert approved["status"] == "APPROVED"
    assert approved["approved_at"]

    listed = await api.list_packages(
        artifact_media_id=_MEDIA, platform=None, status="APPROVED", limit=50
    )
    assert listed["count"] >= 1
    assert all(p["status"] == "APPROVED" for p in listed["packages"])
    assert any(p["package_id"] == pkg["package_id"] for p in listed["packages"])


async def test_edit_reruns_claim_safety_and_unapproves():
    await _seed_artifact()
    pkg = await api.generate(
        GenerateRequest(
            artifact_media_id=_MEDIA, platform="threads",
            caption="Pilihan ramai untuk rutin harian.",
        )
    )
    approved = await api.approve_package(pkg["package_id"], ApprovalRequest())
    assert approved["status"] == "APPROVED"

    # Editing back to unsafe language must block + drop approval.
    edited = await api.update_package(
        pkg["package_id"], UpdateRequest(caption="penawar sakit, guaranteed cure")
    )
    assert edited["status"] == "DRAFT"
    assert edited["compliance_status"] == "BLOCKED"
    assert edited["approved_at"] is None


async def test_reapproving_is_idempotent_and_preserves_audit_fields():
    await _seed_artifact()
    pkg = await api.generate(
        GenerateRequest(
            artifact_media_id=_MEDIA, platform="x",
            caption="Compact dan senang bawa.",
        )
    )
    first = await api.approve_package(pkg["package_id"], ApprovalRequest(approval_note="ok by ops"))
    assert first["status"] == "APPROVED"
    assert first["approval_note"] == "ok by ops"
    # A second approve (note omitted) must NOT wipe the note or re-stamp the time.
    second = await api.approve_package(pkg["package_id"], ApprovalRequest())
    assert second["status"] == "APPROVED"
    assert second["approval_note"] == "ok by ops"
    assert second["approved_at"] == first["approved_at"]


async def test_empty_caption_cannot_be_approved():
    await _seed_artifact()
    pkg = await api.generate(
        GenerateRequest(artifact_media_id=_MEDIA, platform="instagram", caption="")
    )
    assert pkg["compliance_status"] == "WARN"  # empty caption is a warning
    with pytest.raises(HTTPException) as exc:
        await api.approve_package(pkg["package_id"], ApprovalRequest())
    assert exc.value.status_code == 422
    assert exc.value.detail == "EMPTY_CAPTION_CANNOT_APPROVE"


async def test_suggest_is_platform_aware_and_claim_safe():
    for platform in ("tiktok", "facebook", "instagram", "threads", "x"):
        s = await _suggest(platform)
        assert s["platform"] == platform
        assert s["cta_options"], "CTA options must be provided"
        # Suggested copy must itself pass the claim-safe gate.
        from agent.services.claim_safe_rewrite_service import _contains_unsafe_language
        assert not _contains_unsafe_language(s["caption"])
        assert not _contains_unsafe_language(s["call_to_action"])


async def _suggest(platform):
    # suggest is a sync route handler returning the dict directly
    return api.svc.suggest_copy(platform=platform, product_name="Minyak Herba")


async def test_profiles_cover_all_five_platforms():
    prof = await api.get_profiles()
    assert set(prof["platforms"]) == {"tiktok", "facebook", "instagram", "threads", "x"}
    for p in prof["platforms"]:
        assert "tone" in prof["profiles"][p]
