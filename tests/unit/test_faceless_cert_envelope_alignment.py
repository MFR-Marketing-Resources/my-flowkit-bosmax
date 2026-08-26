"""Regression suite for the Faceless profile-certification envelope-alignment defect.

Ground truth of the defect (root-caused live, owner kept the gate ON):
    The Faceless 9:16 certification self-approves a REVIEW snapshot whose
    execution envelope OMITS ``provider_profile_digest``, but the real async
    dispatch (``make_video`` capture path) derives a server provider profile via
    ``_server_derived_video_profiles`` and therefore hashes an envelope that
    INCLUDES ``provider_profile_digest``. The two SHAs differ, so
    ``verify_and_bind_dispatch`` fails ``DISPATCH_NOT_APPROVED`` at the
    (pre-provider, zero-credit) dispatch boundary.

The diverging field proven by the throwaway diff was exactly one:
    ``provider_profile_digest`` (review=None, dispatch=<real digest>).
``execution_profile_context`` does NOT diverge — both review and dispatch funnel
through the idempotent ``normalize_approval_context``.

The fix makes the cert REVIEW derive the SAME provider profile the DISPATCH
derives (``make_video._server_derived_video_profiles``) and pass it into
``create_review_snapshot`` so both envelopes are byte-identical.

These tests assert:
1. Alignment: the fixed certification review envelope == the real dispatch
   envelope (equal ``execution_envelope_sha256``) and dispatch PASSES.
2. The review envelope now actually binds ``provider_profile_digest``.
3. Fails-closed (defect reproduction): a review that OMITS the provider profile
   (old behavior) still fails closed against the provider-bearing dispatch —
   proving the digest is load-bearing and the invariant is not trivially met.
4. Fails-closed (tamper): flipping a provider-affecting field (aspect) at
   dispatch diverges the SHA and fails closed — proving equality is not weakened.
"""

from __future__ import annotations

import json

import pytest

from agent.services import execution_approval_service as eas
from agent.services import video_execution_profile_service as vep
from agent.services.execution_approval_service import ApprovalState
from agent.services.make_video import _server_derived_video_profiles

# The bounded, fixed Faceless certification tuple (see faceless.py profile
# certification endpoint + provider_certification_service.validate_capture_contract).
_PROMPT = "Faceless deterministic composite certification prompt"
_PRODUCT_ID = "prod_cert_alignment"
_EXECUTION_IDENTITY = {"kind": "FACELESS_V1", "product_id": _PRODUCT_ID, "copy_id": "copy_cert_1"}


@pytest.fixture(autouse=True)
def _enforce_gate(monkeypatch):
    """The whole point of the invariant is with the gate ENFORCED."""
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")


def _profile_context() -> dict:
    """Exactly what the cert builds at faceless.py (resolve_duration_model_profile
    -> build_approval_context) for the T2V 8s 9:16 Faceless profile."""
    profile = vep.resolve_duration_model_profile(
        model="veo_3_1_lite",
        duration_s=8,
        aspect_ratio="9:16",
        logical_mode="T2V",
        source_mode="T2V",
        generation_mode="SINGLE",
        reference_count=0,
        prompt_block_count=1,
    )
    return vep.build_approval_context(
        profile,
        lane="FACELESS",
        product_digest="pd_cert_digest",
        copy_digest="cd_cert_digest",
    )


def _derived_provider_profile() -> dict:
    """The SAME server-derived provider profile the dispatch derives
    (make_video._server_derived_video_profiles) for the cert tuple."""
    _duration_profile, provider_profile = _server_derived_video_profiles(
        mode="T2V",
        source_mode="T2V",
        model="veo_3_1_lite",
        duration_s=8,
        aspect="9:16",
        ref_count=0,
        num_videos=1,
    )
    return provider_profile


async def _create_and_approve_review(*, provider_profile) -> dict:
    """Mirror the cert review path: create_review_snapshot -> approve_snapshot."""
    review = await eas.create_review_snapshot(
        surface="FACELESS",
        logical_mode="T2V",
        final_prompt_text=_PROMPT,
        product_id=_PRODUCT_ID,
        source_mode="T2V",
        model="veo_3_1_lite",
        aspect="9:16",
        duration_s=8,
        count=1,
        execution_identity=_EXECUTION_IDENTITY,
        execution_profile_context=_profile_context(),
        provider_profile=provider_profile,
        created_by="owner_cert",
    )
    approved = await eas.approve_snapshot(review["snapshot_id"], approved_by="owner_cert")
    return approved


async def _verify_dispatch(*, provider_profile, aspect="9:16"):
    """Mirror the real dispatch boundary: make_video derives the provider profile
    and normalizes the approval context, then calls verify_and_bind_dispatch."""
    dispatch_context = vep.normalize_approval_context(_profile_context())  # make_video ~3836
    return await eas.verify_and_bind_dispatch(
        mode="T2V",
        final_prompt_text=_PROMPT,
        product_id=_PRODUCT_ID,
        source_mode="T2V",
        model="veo_3_1_lite",
        aspect=aspect,
        duration_s=8,
        count=1,
        execution_identity=_EXECUTION_IDENTITY,
        execution_profile_context=dispatch_context,
        provider_profile=provider_profile,
    )


async def test_faceless_cert_review_envelope_matches_dispatch():
    """FIXED cert review envelope == real dispatch envelope; dispatch PASSES."""
    derived = _derived_provider_profile()

    approved = await _create_and_approve_review(provider_profile=derived)
    assert approved["approval_state"] == ApprovalState.APPROVED
    review_env_sha = approved["execution_envelope_sha256"]

    verdict = await _verify_dispatch(provider_profile=derived)
    assert verdict["pass"] is True
    assert verdict["reason"] == "APPROVED_ENVELOPE_MATCH"
    # THE invariant: approved snapshot envelope SHA == actual dispatch envelope SHA.
    assert verdict["dispatched_execution_envelope_sha256"] == review_env_sha
    assert verdict["snapshot_id"] == approved["snapshot_id"]


async def test_faceless_cert_review_binds_provider_profile_digest():
    """The fixed review envelope carries the SAME provider_profile_digest the
    dispatch derives (the field that used to be missing)."""
    derived = _derived_provider_profile()
    expected_digest = derived["provider_profile_digest"]
    assert expected_digest  # sanity: the server derivation really produced a digest

    approved = await _create_and_approve_review(provider_profile=derived)
    env = json.loads(approved["execution_envelope_json"])
    assert env.get("provider_profile_digest") == expected_digest


async def test_faceless_cert_review_without_provider_profile_fails_closed():
    """Defect reproduction: the OLD review path (no provider_profile) omits
    provider_profile_digest, so it fails closed against the provider-bearing
    dispatch. Proves the digest binding is load-bearing (equality NOT weakened)."""
    # Old cert behavior: review created WITHOUT a provider profile.
    await _create_and_approve_review(provider_profile=None)

    # Real dispatch still derives and binds the server provider profile.
    with pytest.raises(eas.ExecutionApprovalError) as exc_info:
        await _verify_dispatch(provider_profile=_derived_provider_profile())
    assert exc_info.value.code == "DISPATCH_NOT_APPROVED"


async def test_faceless_cert_aspect_tamper_fails_closed():
    """A provider-affecting change (aspect 9:16 -> 16:9) at dispatch diverges the
    envelope SHA and fails closed — equality is strict, not weakened."""
    derived = _derived_provider_profile()
    await _create_and_approve_review(provider_profile=derived)

    with pytest.raises(eas.ExecutionApprovalError) as exc_info:
        await _verify_dispatch(provider_profile=derived, aspect="16:9")
    assert exc_info.value.code == "DISPATCH_NOT_APPROVED"
