"""Real HTTP/DB workflow proof for Copy Register V2.

The app router, validation service, SQLite persistence, approval, and activation
are exercised together. Only the provider boundary is deterministic; no network
provider or legacy CopySet service is reachable.
"""
from __future__ import annotations

import json
import re

import httpx
import pytest
from fastapi import FastAPI

from agent.api.copy_register_v2 import router
from agent.db.schema import get_db
from agent.services import copy_register_v2_service as service
from tests.unit.test_copy_register_v2_cutover import _seed_truth


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _install_synthetic_provider(monkeypatch, *, configured: bool) -> dict:
    state = {"calls": 0, "last_receipt": None}

    def complete_json_with_receipt(system: str, user: str):
        state["calls"] += 1
        payload = json.loads(user)
        if service.ANGLE_PROMPT_VERSION in system:
            facts = payload["facts"]
            result = {
                "angles": [
                    {
                        "definition": f"Bukti terpilih: {fact['text']}",
                        "evidence_fact_ids": [fact["fact_id"]],
                    }
                    for fact in facts[:3]
                ]
            }
        elif service.FORMULA_PROMPT_VERSION in system:
            facts = payload["facts"]
            angle = payload["selected_angle"]["definition"]
            if payload.get("duration_authority"):
                assert payload["evidence_contract"]["claim_bearing_stage_keys"] == [
                    "problem",
                    "agitate",
                    "solution",
                ]
                assert payload["evidence_contract"]["fact_id_rule"]
                short_text = {
                    "problem": "Masalah harian terasa mengganggu.",
                    "agitate": "Rutin pun jadi berat.",
                    "solution": facts[0]["text"],
                    "cta": "Cuba sekarang.",
                }
                result = {
                    "stages": [
                        {
                            "formula_stage_key": stage_key,
                            "text": short_text[stage_key],
                            "evidence_fact_ids": (
                                [] if stage_key == "cta" else [facts[0]["fact_id"]]
                            ),
                        }
                        for stage_key in payload["formula"]["ordered_stage_keys"]
                    ]
                }
            else:
                result = {
                    "stages": [
                        {
                            "formula_stage_key": stage_key,
                            "text": (
                                "Semak maklumat produk dan pilih langkah seterusnya."
                                if stage_key in {"cta", "action", "response"}
                                else f"{angle}. {facts[index % len(facts)]['text']}."
                            ),
                            "evidence_fact_ids": (
                                []
                                if stage_key in {"cta", "action", "response"}
                                else [facts[index % len(facts)]["fact_id"]]
                            ),
                        }
                        for index, stage_key in enumerate(
                            payload["formula"]["ordered_stage_keys"]
                        )
                    ]
                }
        else:  # pragma: no cover - this integration only uses two authoring routes
            raise AssertionError("unexpected V2 prompt contract")
        receipt = {
            "call_id": state["calls"],
            "lane": "text_assist",
            "provider_id": "synthetic-http-provider",
            "model_id": "synthetic-http-model",
            "transport": "synthetic-http-transport",
            "response_status": "SUCCEEDED",
            "json_parse_status": "VALID",
            "completed_at": "2026-08-15T00:00:00Z",
            "usage": {},
        }
        state["last_receipt"] = receipt
        return result, receipt

    monkeypatch.setattr(service.ai_provider, "is_configured", lambda: configured)
    monkeypatch.setattr(
        service.ai_provider,
        "provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": configured,
            "provider_id": "synthetic-http-provider" if configured else None,
            "model_id": "synthetic-http-model" if configured else None,
            "execution_enabled": configured,
        },
    )
    monkeypatch.setattr(
        service.ai_provider,
        "complete_json_with_receipt",
        complete_json_with_receipt,
    )
    return state


async def _legacy_counts() -> dict[str, int]:
    db = await get_db()
    output = {}
    for table in ("copy_set", "copy_component", "poster_copy_set"):
        output[table] = int((await (await db.execute(f"SELECT COUNT(*) FROM {table}")).fetchone())[0])
    return output


@pytest.mark.asyncio
async def test_real_http_workflow_persists_one_draft_then_approval_and_reload(
    monkeypatch,
):
    monkeypatch.delenv("COPY_LEGACY_MAINTENANCE_MODE", raising=False)
    state = _install_synthetic_provider(monkeypatch, configured=True)
    product, _snapshot = await _seed_truth()
    legacy_before = await _legacy_counts()
    db = await get_db()
    statements: list[str] = []
    await db.set_trace_callback(statements.append)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://copy-register.test",
    ) as client:
        truth = await client.get(
            f"/api/copy-register/v2/product/{product['id']}/truth"
        )
        assert truth.status_code == 200
        assert truth.json()["ready_for_copy"] is True
        assert truth.json()["legacy_copy_rows_read"] == 0

        provider = await client.get("/api/copy-register/v2/provider-status")
        assert provider.status_code == 200
        assert provider.json()["status"] == "READY"
        assert provider.json()["provider_calls"] == 0
        assert not {"api_key", "masked_key", "key_present"} & provider.json().keys()

        angle_response = await client.post(
            "/api/copy-register/v2/angle-options",
            json={
                "product_id": product["id"],
                "formula_id": "PAS",
                "objective": "conversion",
            },
        )
        assert angle_response.status_code == 200
        angle_payload = angle_response.json()
        assert angle_payload["provider_receipt"]["call_id"] == 1
        assert angle_payload["legacy_copy_rows_read"] == 0
        selected_angle = angle_payload["angles"][0]
        selected_facts = selected_angle["evidence_fact_ids"]

        blueprint_response = await client.post(
            "/api/copy-register/v2/blueprints/generate",
            json={
                "product_id": product["id"],
                "formula_id": "PAS",
                "objective_id": "conversion",
                "objective_definition": "A grounded conversion objective.",
                "angle_id": selected_angle["angle_id"],
                "angle_definition": selected_angle["definition"],
                "evidence_fact_ids": selected_facts,
                "target_duration_seconds": 8,
            },
        )
        assert blueprint_response.status_code == 200
        generated = blueprint_response.json()
        assert generated["status"] == "DRAFT"
        assert generated["production_valid"] is False
        assert generated["legacy_copy_rows_written"] == 0
        blueprint_id = generated["blueprint"]["blueprint_id"]

        draft_count = await db.execute(
            "SELECT COUNT(*) FROM copy_blueprint_v2 WHERE product_id=? AND status='DRAFT'",
            (product["id"],),
        )
        assert int((await draft_count.fetchone())[0]) == 1

        approval_response = await client.post(
            f"/api/copy-register/v2/blueprints/{blueprint_id}/approve",
            json={
                "approved_by": "synthetic-http-reviewer",
                "semantic_review": {
                    "decision": "APPROVED",
                    "reviewer": "synthetic-http-reviewer",
                    "rationale": "Every stage was reviewed against approved evidence.",
                    "reviewed_at": "2026-08-15T00:10:00Z",
                },
                "readiness_proof": {
                    "readiness_validated": True,
                    "provenance_validated": True,
                    "safety_validated": True,
                    "bridge_validated": True,
                    "duration_validated": True,
                },
            },
        )
        assert approval_response.status_code == 200
        assert approval_response.json()["automatic_approval"] is False
        assert approval_response.json()["status"] == "PRODUCTION_VALID"

        activation_response = await client.post(
            f"/api/copy-register/v2/blueprints/{blueprint_id}/activate"
        )
        assert activation_response.status_code == 200
        assert activation_response.json()["required_lane_count"] == 8
        assert activation_response.json()["provider_calls"] == 0
        assert activation_response.json()["credit_spend"] == 0

        reloaded = await client.get(
            f"/api/copy-register/v2/product/{product['id']}/blueprints"
        )
        assert reloaded.status_code == 200
        assert reloaded.json()["items"][0]["status"] == "PRODUCTION_VALID"
        assert reloaded.json()["activation"]["active_blueprint_id"] == blueprint_id
        assert reloaded.json()["activation"]["active_lane_count"] == 8
        assert reloaded.json()["legacy_copy_rows_read"] == 0

    await db.set_trace_callback(None)
    assert state["calls"] == 2
    assert await _legacy_counts() == legacy_before
    legacy_sql = [
        statement
        for statement in statements
        if re.search(r"\b(copy_set|copy_component|poster_copy_set)\b", statement, re.I)
    ]
    assert legacy_sql == []


@pytest.mark.asyncio
async def test_real_http_unconfigured_text_assist_is_stable_and_zero_call(
    monkeypatch,
):
    state = _install_synthetic_provider(monkeypatch, configured=False)
    product, _snapshot = await _seed_truth()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://copy-register.test",
    ) as client:
        response = await client.post(
            "/api/copy-register/v2/angle-options",
            json={
                "product_id": product["id"],
                "formula_id": "PAS",
                "objective": "conversion",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "COPY_V2_TEXT_AI_NOT_CONFIGURED"
    assert state["calls"] == 0
    assert await _legacy_counts() == {
        "copy_set": 0,
        "copy_component": 0,
        "poster_copy_set": 0,
    }
