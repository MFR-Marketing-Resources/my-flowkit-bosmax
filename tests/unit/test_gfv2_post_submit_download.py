"""Tests for the operator-gated GFV2_POST_SUBMIT_DOWNLOAD trigger.

Covers job assembly and the fail-closed gate decision (dry-run vs live, and every
reject path) without a live extension or dispatch.
"""
import json

from agent.services import gfv2_post_submit_download as gfv2


def _package() -> dict:
    return {
        "workspace_execution_package_id": "wep_1fc9b182d3b352e6",
        "product_id": "de3ee6bd-592b-4228-bf96-f2cdcf15e78c",
        "mode": "F2V",
        "aspect_ratio": "9:16",
        "model": "Veo 3.1 - Lite",
        "duration_seconds": 8,
        "prompt_text": "Vertical 9:16 handheld. MCU to CU framing. Product-only reveal.",
        "prompt_package_snapshot_id": "pkg_9391fa3e44ec43df",
        "prompt_fingerprint": "8f1cca4d78de4deb774df2af6eb4dbde4cdbd29a",
        "resolved_assets": json.dumps([
            {
                "asset_id": "product-image:de3ee6bd:start_frame",
                "asset_fingerprint": "asset_74f6d9433ec5af0c",
                "slot_key": "start_frame",
                "asset_source": "PRODUCT_IMAGE_URL",
                "preview_url": "https://s.500fd.com/tt_product/abc.jpg",
                "file_name": "de3ee6bd.jpg",
            }
        ]),
    }


def _product() -> dict:
    return {"id": "de3ee6bd-592b-4228-bf96-f2cdcf15e78c", "product_short_name": "Remote"}


# ── assembly ─────────────────────────────────────────────────

def test_assemble_job_has_lane_and_flags():
    job = gfv2.assemble_job(_package(), _product(), "gfv2psd-test1")
    assert job["lane"] == "GFV2_POST_SUBMIT_DOWNLOAD"
    assert job["postSubmitDownload"] is True
    assert job["gfv2"] is True
    # extension's isGfv2PostSubmitDownload(job) would be true
    assert job["lane"] == "GFV2_POST_SUBMIT_DOWNLOAD" or job["postSubmitDownload"] is True


def test_assemble_job_carries_package_prompt_assets_settings():
    job = gfv2.assemble_job(_package(), _product(), "gfv2psd-test2")
    assert job["mode"] == "F2V"
    assert job["aspectRatio"] == "9:16"
    assert job["count"] == "1x"
    assert job["modelLabel"] == "Veo 3.1 - Lite"
    assert job["prompt"].startswith("Vertical 9:16 handheld")
    assert job["startAsset"] == "https://s.500fd.com/tt_product/abc.jpg"  # upload source
    assert job["product_id"] == "de3ee6bd-592b-4228-bf96-f2cdcf15e78c"
    assert job["workspace_execution_package_id"] == "wep_1fc9b182d3b352e6"
    assert job["request_id"] == "gfv2psd-test2"


# ── gate decision ────────────────────────────────────────────

def _ok_kwargs(**over):
    base = dict(
        confirm_live=False,
        build_proof_pass=True,
        active_job_count=0,
        package=_package(),
        product=_product(),
        request_id="gfv2psd-x",
        request_id_exists=False,
    )
    base.update(over)
    return base


def test_dry_run_when_all_gates_pass_and_no_confirm():
    d = gfv2.evaluate_trigger(**_ok_kwargs(confirm_live=False))
    assert d["action"] == gfv2.ACTION_DRY_RUN


def test_live_requires_confirm_flag():
    # Without confirm -> never LIVE (no dispatch)
    assert gfv2.evaluate_trigger(**_ok_kwargs(confirm_live=False))["action"] == gfv2.ACTION_DRY_RUN
    # With confirm + gates pass -> LIVE
    assert gfv2.evaluate_trigger(**_ok_kwargs(confirm_live=True))["action"] == gfv2.ACTION_LIVE


def test_build_proof_block_rejects():
    d = gfv2.evaluate_trigger(**_ok_kwargs(confirm_live=True, build_proof_pass=False))
    assert d["action"] == gfv2.ACTION_REJECT
    assert d["reason"] == gfv2.REJECT_BUILD_PROOF_NOT_PASS


def test_active_job_rejects():
    d = gfv2.evaluate_trigger(**_ok_kwargs(active_job_count=1))
    assert d["action"] == gfv2.ACTION_REJECT
    assert d["reason"] == gfv2.REJECT_ACTIVE_JOB_EXISTS


def test_duplicate_request_id_rejects():
    d = gfv2.evaluate_trigger(**_ok_kwargs(request_id_exists=True))
    assert d["action"] == gfv2.ACTION_REJECT
    assert d["reason"] == gfv2.REJECT_DUPLICATE_REQUEST_ID


def test_missing_package_rejects():
    d = gfv2.evaluate_trigger(**_ok_kwargs(package=None))
    assert d["action"] == gfv2.ACTION_REJECT
    assert d["reason"] == gfv2.REJECT_MISSING_PACKAGE


def test_missing_product_rejects():
    d = gfv2.evaluate_trigger(**_ok_kwargs(product=None))
    assert d["action"] == gfv2.ACTION_REJECT
    assert d["reason"] == gfv2.REJECT_MISSING_PRODUCT


def test_product_mismatch_rejects():
    d = gfv2.evaluate_trigger(**_ok_kwargs(product={"id": "OTHER"}))
    assert d["action"] == gfv2.ACTION_REJECT
    assert d["reason"] == gfv2.REJECT_PRODUCT_MISMATCH


def test_dry_run_never_reaches_live_even_with_block():
    # A blocked build in dry-run is still a REJECT (no job leaks as "ready")
    d = gfv2.evaluate_trigger(**_ok_kwargs(confirm_live=False, build_proof_pass=False))
    assert d["action"] == gfv2.ACTION_REJECT


def test_visible_creator_prompt_without_system_avatar_rejects():
    # System-avatar contract: product-only package whose prompt demands a visible
    # creator must be blocked (Google Flow would invent an uncontrolled human).
    from agent.services.system_avatar_contract import ERR_CHARACTER_PROMPT_WITHOUT_SYSTEM_AVATAR
    pkg = _package()
    pkg["prompt_text"] = "Vertical 9:16. CHARACTER: One visible creator on screen."
    d = gfv2.evaluate_trigger(**_ok_kwargs(confirm_live=True, package=pkg))
    assert d["action"] == gfv2.ACTION_REJECT
    assert d["reason"] == ERR_CHARACTER_PROMPT_WITHOUT_SYSTEM_AVATAR


def test_visible_creator_prompt_with_avatar_asset_allowed():
    # Same prompt, but the package carries a system avatar reference -> allowed.
    pkg = _package()
    pkg["prompt_text"] = "Vertical 9:16. CHARACTER: One visible creator on screen."
    pkg["resolved_assets"] = json.dumps([
        {"slot_key": "start_frame", "asset_source": "PRODUCT_IMAGE_URL"},
        {"slot_key": "character_reference", "asset_source": "AVATAR_UPLOAD"},
    ])
    d = gfv2.evaluate_trigger(**_ok_kwargs(confirm_live=False, package=pkg))
    assert d["action"] == gfv2.ACTION_DRY_RUN
