"""Provider-free contracts for the bounded Faceless profile certification route."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.api import faceless as api
from agent.services import execution_approval_service as eas
from agent.services import flow_client
from agent.services import make_video
from agent.services import provider_certification_service as certifications
from agent.services import video_execution_profile_service as profiles


PRODUCT_ID = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
COPY_ID = "bpv2_7eec03e5b5fd42878c33"
RUNTIME_SHA = "78d023b7521a8dcc5f26e5d7290f4f143a73c981"


class _Binding:
    blueprint_id = COPY_ID
    revision = 3

    def model_dump(self, mode="json"):
        return {
            "blueprint_id": self.blueprint_id,
            "revision": self.revision,
            "status": "PRODUCTION_VALID",
        }


class _FakeClient:
    connected = True

    async def get_credits(self):
        return {"credits": 1013}


def _body(**overrides):
    values = {
        "product_id": PRODUCT_ID,
        "copy_id": COPY_ID,
        "model": "veo_3_1_lite",
        "duration_seconds": 8,
        "aspect_ratio": "9:16",
        "confirm_live_credit_burn": True,
        "maximum_provider_operations": 1,
        "max_retry_operations": 0,
        "request_id": "pcert-test-correlation",
    }
    values.update(overrides)
    return api.FacelessProfileCertificationRequest(**values)


def _install_common(monkeypatch, *, start_result=None, profile_error=None, prepared=None):
    calls = {
        "reservation": None,
        "snapshot": None,
        "start": None,
        "submitted": [],
        "failed": [],
        "invalidated": [],
    }
    profile = profiles.resolve_duration_model_profile(
        model="veo_3_1_lite",
        duration_s=8,
        aspect_ratio="9:16",
        logical_mode="T2V",
        source_mode="T2V",
        generation_mode="SINGLE",
        reference_count=0,
        prompt_block_count=1,
    )

    owner = SimpleNamespace(
        staff_id="staff_test_owner",
        display_name="Test Owner",
        role_codes=("OWNER",),
        permission_codes=("production.execute",),
    )
    package = prepared or {
        "execution_allowed": True,
        "selected_execution_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
        "package": {
            "execution_allowed": True,
            "prompt_text": "Exact deterministic product composite prompt.",
            "product_visual_custody": {
                "provider_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                "provider_product_reference_forbidden": True,
            },
            "faceless_execution_identity": {
                "workspace_execution_package_id": "wep_test",
                "prompt_fingerprint": "prompt-fingerprint",
                "surface_lane": "FACELESS",
            },
            "copy_execution_binding": {"blueprint_id": COPY_ID, "revision": 3},
        },
    }
    if start_result is None:
        start_result = {"status": "PRE_PROVIDER", "job_id": "g_provider_stub"}

    monkeypatch.setattr(api, "_require_profile_certification_owner", lambda: owner)
    monkeypatch.setattr(
        api,
        "_current_runtime_proof",
        lambda: {"canonical_runtime": True, "runtime_sha": RUNTIME_SHA},
    )
    monkeypatch.setattr(flow_client, "get_flow_client", lambda: _FakeClient())
    monkeypatch.setattr(
        make_video,
        "ensure_editor_binding",
        _async_value(
            {
                "project_id": "flow-project-test",
                "flow_tab_id": 7,
                "flow_project_url": "https://labs.google/fx/tools/flow/project/flow-project-test",
            }
        ),
    )
    monkeypatch.setattr(api, "faceless_prepare", _async_value(package))
    monkeypatch.setattr(
        api,
        "resolve_persisted_copy_execution_binding",
        _async_value(
            SimpleNamespace(
                ready=True,
                status="PRODUCTION_VALID",
                binding=_Binding(),
            )
        ),
    )
    copy_register = __import__(
        "agent.services.copy_register_v2_service", fromlist=["unused"]
    )
    monkeypatch.setattr(
        copy_register,
        "get_product_truth_proof",
        _async_value(
            {
                "ready_for_copy": True,
                "product_truth": {"snapshot": {"digest": "product-truth-digest"}},
            }
        ),
    )
    monkeypatch.setattr(
        copy_register,
        "get_blueprint",
        _async_value(SimpleNamespace(approval_snapshot=SimpleNamespace(blueprint_digest="copy-digest"))),
    )

    def resolve_profile(**_kwargs):
        if profile_error is not None:
            raise profile_error
        return profile

    monkeypatch.setattr(profiles, "resolve_duration_model_profile", resolve_profile)
    monkeypatch.setattr(
        profiles,
        "build_approval_context",
        lambda _profile, **_kwargs: {
            "duration_model_profile": _profile,
            "lane": "FACELESS",
            "lane_adapter_digest": "faceless-adapter-digest",
            "product_digest": "product-truth-digest",
            "copy_digest": "copy-digest",
            "sweetwps_digest": "sweetwps-digest",
            "compositor_digest": "compositor-digest",
            "compiler_digest": "compiler-digest",
        },
    )
    monkeypatch.setattr(profiles, "sweetwps_digest", lambda: "sweetwps-digest")
    monkeypatch.setattr(profiles, "compositor_digest", lambda: "compositor-digest")
    monkeypatch.setattr(profiles, "compiler_digest", lambda: "compiler-digest")
    monkeypatch.setattr(profiles, "lane_adapter_digest", lambda _lane: "faceless-adapter-digest")

    async def reserve(**kwargs):
        calls["reservation"] = kwargs
        return {
            "certification_id": "pec_test",
            "status": "RESERVED",
        }, True

    async def mark_submitted(certification_id, *, job_id, snapshot_id):
        calls["submitted"].append((certification_id, job_id, snapshot_id))
        return {
            "certification_id": certification_id,
            "status": "SUBMITTED",
            "job_id": job_id,
            "snapshot_id": snapshot_id,
        }

    async def mark_failed(certification_id, *, code, detail="", snapshot_id=None):
        calls["failed"].append((certification_id, code, detail, snapshot_id))
        return {"certification_id": certification_id, "status": "FAILED"}

    monkeypatch.setattr(certifications, "reserve_capture", reserve)
    monkeypatch.setattr(certifications, "mark_submitted", mark_submitted)
    monkeypatch.setattr(certifications, "mark_failed", mark_failed)

    async def create_snapshot(**kwargs):
        calls["snapshot"] = kwargs
        return {"snapshot_id": "snap_test", "approval_state": "REVIEW_REQUIRED"}

    async def approve_snapshot(snapshot_id, *, approved_by):
        return {
            "snapshot_id": snapshot_id,
            "approval_state": "APPROVED",
            "approved_by": approved_by,
        }

    async def invalidate_snapshot(snapshot_id, *, reason):
        calls["invalidated"].append((snapshot_id, reason))
        return {"snapshot_id": snapshot_id, "approval_state": "INVALIDATED"}

    async def reconcile_snapshot(snapshot_id, *, reason):
        calls["invalidated"].append((snapshot_id, reason))
        return {"snapshot_id": snapshot_id, "approval_state": "INVALIDATED"}

    monkeypatch.setattr(eas, "create_review_snapshot", create_snapshot)
    monkeypatch.setattr(eas, "approve_snapshot", approve_snapshot)
    monkeypatch.setattr(eas, "invalidate_snapshot", invalidate_snapshot)
    monkeypatch.setattr(eas, "reconcile_pre_provider_failure", reconcile_snapshot)

    async def start_generate(mode, prompt, **kwargs):
        calls["start"] = {"mode": mode, "prompt": prompt, "kwargs": kwargs}
        return start_result

    monkeypatch.setattr(make_video, "start_generate", start_generate)
    return calls, profile


def _async_value(value):
    async def resolve(*_args, **_kwargs):
        return value

    return resolve


@pytest.mark.asyncio
async def test_success_builds_exact_provider_free_certification_payload(monkeypatch):
    calls, profile = _install_common(monkeypatch)

    result = await api.faceless_profile_certification(_body())

    assert result["status"] == "PRE_PROVIDER"
    assert calls["submitted"] == []
    assert calls["start"]["mode"] == "T2V"
    assert calls["start"]["kwargs"]["product_id"] == PRODUCT_ID
    assert calls["start"]["kwargs"]["model"] == "veo_3_1_lite"
    assert calls["start"]["kwargs"]["duration_s"] == 8
    assert calls["start"]["kwargs"]["aspect"] == "9:16"
    assert calls["start"]["kwargs"]["production_recipe"] == "FACELESS"
    assert calls["start"]["kwargs"]["surface_lane"] == "FACELESS"
    assert calls["start"]["kwargs"]["confirm_live_credit_burn"] is True
    assert calls["start"]["kwargs"]["maximum_provider_operations"] == 1
    assert calls["start"]["kwargs"]["max_retry_operations"] == 0
    assert calls["start"]["kwargs"]["execution_profile_context"]["duration_model_profile"] == profile
    assert calls["start"]["kwargs"]["execution_snapshot_id"] == "snap_test"
    assert calls["start"]["kwargs"]["profile_certification_id"] == "pec_test"
    assert calls["reservation"]["snapshot_id"] == "snap_test"
    assert calls["start"]["kwargs"]["provider_target_authorization"]["target"]["model"] == "veo_3_1_lite"
    assert calls["start"]["kwargs"]["provider_target_authorization"]["target_digest"]


@pytest.mark.asyncio
async def test_exact_composite_route_is_preserved_to_dispatch(monkeypatch):
    calls, _profile = _install_common(monkeypatch)

    await api.faceless_profile_certification(_body())

    custody = calls["start"]["kwargs"]["product_visual_custody"]
    assert custody["provider_route"] == "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE"
    assert custody["provider_product_reference_forbidden"] is True


@pytest.mark.asyncio
async def test_editor_binding_failure_is_structured_and_has_zero_side_effects(monkeypatch):
    calls, _profile = _install_common(monkeypatch)

    async def fail_binding(*_args, **_kwargs):
        raise make_video.FlowEditorBindingError(
            "NO_OPEN_EDITOR: the Flow tab is not on a project editor",
            details={"flow_path_state": "ROOT_OR_NON_EDITOR"},
        )

    monkeypatch.setattr(make_video, "ensure_editor_binding", fail_binding)
    with pytest.raises(HTTPException) as raised:
        await api.faceless_profile_certification(_body(request_id="corr-editor"))

    assert raised.value.status_code == 409
    assert raised.value.detail["error_code"] == "FLOW_EDITOR_BINDING_REQUIRED"
    assert raised.value.detail["provider_calls"] == 0
    assert raised.value.detail["credit_spend"] is False
    assert calls["reservation"] is None
    assert calls["snapshot"] is None
    assert calls["start"] is None


@pytest.mark.asyncio
async def test_invalid_envelope_blocks_before_any_certification_side_effect(monkeypatch):
    calls, _profile = _install_common(monkeypatch)

    with pytest.raises(HTTPException) as raised:
        await api.faceless_profile_certification(_body(model="unsupported_model"))

    assert raised.value.status_code == 422
    assert raised.value.detail["error_code"] == "PROFILE_CERTIFICATION_TUPLE_INVALID"
    assert calls["reservation"] is None
    assert calls["snapshot"] is None
    assert calls["start"] is None


@pytest.mark.asyncio
async def test_missing_profile_is_structured_and_provider_free(monkeypatch):
    calls, _profile = _install_common(
        monkeypatch,
        profile_error=profiles.ExecutionProfileError("PROFILE_NOT_FOUND"),
    )

    with pytest.raises(HTTPException) as raised:
        await api.faceless_profile_certification(_body(request_id="corr-missing-profile"))

    detail = raised.value.detail
    assert raised.value.status_code == 409
    assert detail["error_code"] == "PROFILE_CERTIFICATION_PROFILE_RESOLUTION_FAILED"
    assert detail["source_error_code"] == "PROFILE_NOT_FOUND"
    assert detail["request_id"] == "corr-missing-profile"
    assert calls["reservation"] is None
    assert calls["start"] is None


@pytest.mark.asyncio
async def test_provider_rejection_is_structured_and_marks_snapshot_invalid(monkeypatch):
    calls, _profile = _install_common(
        monkeypatch,
        start_result={"status": "REJECTED", "error": "PROVIDER_REJECTED", "message": "stub denial"},
    )

    with pytest.raises(HTTPException) as raised:
        await api.faceless_profile_certification(_body(request_id="corr-provider-reject"))

    detail = raised.value.detail
    assert raised.value.status_code == 409
    assert detail["error_code"] == "PROVIDER_REJECTED"
    assert detail["request_id"] == "corr-provider-reject"
    assert detail["provider_response"]["message"] == "stub denial"
    assert calls["failed"]
    assert calls["invalidated"] == [("snap_test", "PROFILE_CERTIFICATION_DISPATCH_REJECTED")]


@pytest.mark.asyncio
async def test_persistence_failure_is_structured_and_stops_before_dispatch(monkeypatch):
    calls, _profile = _install_common(monkeypatch)

    async def fail_reservation(**_kwargs):
        raise certifications.ProviderCertificationError(
            "CERTIFICATION_RESERVATION_FAILED", "database is locked"
        )

    monkeypatch.setattr(certifications, "reserve_capture", fail_reservation)

    with pytest.raises(HTTPException) as raised:
        await api.faceless_profile_certification(_body(request_id="corr-persistence"))

    detail = raised.value.detail
    assert raised.value.status_code == 409
    assert detail["error_code"] == "CERTIFICATION_RESERVATION_FAILED"
    assert detail["request_id"] == "corr-persistence"
    assert calls["snapshot"] is not None
    assert calls["invalidated"]
    assert calls["start"] is None


@pytest.mark.asyncio
async def test_package_gate_failure_has_zero_job_artifact_and_provider_side_effects(monkeypatch):
    blocked = {
        "execution_allowed": False,
        "selected_execution_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
        "package": {"execution_allowed": False, "blockers": ["PRODUCT_TRUTH_REQUIRED"]},
    }
    calls, _profile = _install_common(monkeypatch, prepared=blocked)

    with pytest.raises(HTTPException) as raised:
        await api.faceless_profile_certification(_body())

    assert raised.value.status_code == 422
    assert raised.value.detail["error_code"] == "PROFILE_CERTIFICATION_PACKAGE_NOT_READY"
    assert calls["reservation"] is None
    assert calls["snapshot"] is None
    assert calls["start"] is None


@pytest.mark.asyncio
async def test_unexpected_preprovider_exception_never_returns_unstructured_error(monkeypatch):
    calls, _profile = _install_common(monkeypatch)

    async def fail_prepare(*_args, **_kwargs):
        raise RuntimeError("provider-free fixture failure")

    monkeypatch.setattr(api, "faceless_prepare", fail_prepare)

    with pytest.raises(HTTPException) as raised:
        await api.faceless_profile_certification(_body(request_id="corr-prepare"))

    assert raised.value.status_code == 500
    assert raised.value.detail["error_code"] == "PROFILE_CERTIFICATION_PREPARATION_FAILED"
    assert raised.value.detail["request_id"] == "corr-prepare"
    assert calls["reservation"] is None
    assert calls["start"] is None


@pytest.mark.asyncio
async def test_reconcile_route_carries_snapshot_linkage_into_certification(monkeypatch):
    owner = SimpleNamespace(
        staff_id="staff_test_owner",
        display_name="Test Owner",
        role_codes=("OWNER",),
        permission_codes=("production.execute",),
    )
    observed = {}

    monkeypatch.setattr(api, "_require_profile_certification_owner", lambda: owner)
    certification_crud = __import__(
        "agent.db.provider_certification_crud", fromlist=["unused"]
    )
    monkeypatch.setattr(
        certification_crud,
        "get_by_id",
        _async_value(
            {
                "certification_id": "pec_old",
                "job_id": "g_old",
                "snapshot_id": None,
                "status": "FAILED",
            }
        ),
    )
    monkeypatch.setattr(
        make_video,
        "get_job",
        lambda _job_id: {
            "job_id": "g_old",
            "status": "FAILED",
            "error": "agent did not approve a video: PRE_APPROVAL_SETTINGS_ACK_REQUIRED",
        },
    )
    monkeypatch.setattr(
        make_video,
        "reconcile_pre_provider_failure",
        _async_capture(observed, "job", {"job_id": "g_old", "status": "FAILED"}),
    )
    monkeypatch.setattr(
        certifications,
        "reconcile_pre_provider_failure",
        _async_capture(
            observed,
            "certification",
            {
                "certification_id": "pec_old",
                "status": "FAILED",
                "snapshot_id": "eas_old",
            },
        ),
    )
    monkeypatch.setattr(
        eas,
        "reconcile_pre_provider_failure",
        _async_capture(
            observed,
            "snapshot",
            {"snapshot_id": "eas_old", "approval_state": "INVALIDATED"},
        ),
    )

    result = await api.reconcile_faceless_profile_certification(
        "g_old",
        api.FacelessProfileCertificationReconcileRequest(
            certification_id="pec_old",
            snapshot_id="eas_old",
            error_code="PRE_APPROVAL_SETTINGS_ACK_REQUIRED",
            error_detail="agent did not approve a video: PRE_APPROVAL_SETTINGS_ACK_REQUIRED",
            request_id="reconcile-test",
        ),
    )

    assert observed["job"]["args"] == ("g_old",)
    assert observed["certification"]["kwargs"]["snapshot_id"] == "eas_old"
    assert observed["snapshot"]["args"][0] == "eas_old"
    assert result["certification"]["snapshot_id"] == "eas_old"


def _async_capture(observed, key, result):
    async def capture(*args, **kwargs):
        observed[key] = {"args": args, "kwargs": kwargs}
        return result

    return capture
