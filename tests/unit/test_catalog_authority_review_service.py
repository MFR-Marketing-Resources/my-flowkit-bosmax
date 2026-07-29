from __future__ import annotations

import json

import pytest

from agent.services import catalog_authority_review_service as service


def _evidence(index: int) -> service.CatalogAuthorityReviewEvidence:
    return service.CatalogAuthorityReviewEvidence(
        signature_id=f"{index:016x}",
        source_category="Home Supplies",
        source_subcategory="Home Care Supplies",
        source_product_type=f"Unresolved Type {index}",
        product_names=[f"Product {index}"],
        approved_descriptions=[f"Approved description {index}"],
        approved_usage=[],
        current_product_type_group="unknown_product_type",
        current_scene_strategy_id="GENERIC_FALLBACK",
    )


def _provider_payload(items: list[service.CatalogAuthorityReviewEvidence]) -> dict:
    return {
        "mission_id": service.P58_MISSION_ID,
        "decisions": [
            {
                "signature_id": item.signature_id,
                "disposition": "INSUFFICIENT_PRODUCT_TRUTH",
                "proposed_cluster": None,
                "proposed_product_type_group": None,
                "proposed_scene_strategy_id": None,
                "confidence": "LOW",
                "evidence_basis": ["approved description"],
                "exact_reason": "Approved evidence does not prove one reusable type.",
                "safety_flags": [],
            }
            for item in items
        ],
    }


def test_review_batch_uses_configured_adapter_and_returns_safe_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [_evidence(index) for index in range(10)]
    receipts = iter(
        [
            {"request_count_since_process_start": 4, "last_call": None},
            {
                "request_count_since_process_start": 5,
                "last_call": {
                    "call_id": 5,
                    "provider_id": "deepseek",
                    "model": "deepseek-v4-pro",
                    "response_status": "SUCCEEDED",
                    "json_parse_status": "VALID",
                },
            },
        ]
    )
    captured: dict[str, str] = {}

    def fake_complete_json(system: str, user: str) -> dict:
        captured["system"] = system
        captured["user"] = user
        return _provider_payload(items)

    monkeypatch.setattr(
        service.ai_copy_provider_adapter,
        "provider_call_receipt",
        lambda: next(receipts),
    )
    monkeypatch.setattr(
        service.ai_copy_provider_adapter,
        "complete_json",
        fake_complete_json,
    )

    ledger = service.review_catalog_authority_batch(items)

    assert ledger.request_count_before == 4
    assert ledger.request_count_after == 5
    assert ledger.provider_id == "deepseek"
    assert ledger.model == "deepseek-v4-pro"
    assert len(ledger.decisions) == 10
    prompt = json.loads(captured["user"])
    assert len(prompt["unresolved_signatures"]) == 10
    assert "unknown_product_type" in captured["user"]
    assert "GENERIC_FALLBACK" in captured["system"]
    serialized_ledger = ledger.model_dump_json()
    assert "Approved description 0" not in serialized_ledger
    assert "Product 0" not in serialized_ledger


@pytest.mark.parametrize("batch_size", [0, 9, 21])
def test_review_batch_rejects_out_of_bounds_size(batch_size: int) -> None:
    with pytest.raises(
        ValueError,
        match="P58_REVIEW_BATCH_REQUIRES_10_TO_20_SIGNATURES",
    ):
        service.review_catalog_authority_batch(
            [_evidence(index) for index in range(batch_size)]
        )


def test_review_batch_rejects_provider_signature_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [_evidence(index) for index in range(10)]
    payload = _provider_payload(items)
    payload["decisions"][0]["signature_id"] = "ffffffffffffffff"
    monkeypatch.setattr(
        service.ai_copy_provider_adapter,
        "provider_call_receipt",
        lambda: {"request_count_since_process_start": 0, "last_call": None},
    )
    monkeypatch.setattr(
        service.ai_copy_provider_adapter,
        "complete_json",
        lambda _system, _user: payload,
    )

    with pytest.raises(ValueError, match="P58_PROVIDER_SIGNATURE_SET_MISMATCH"):
        service.review_catalog_authority_batch(items)


def test_review_decision_rejects_partial_mapping() -> None:
    with pytest.raises(
        ValueError,
        match="MAPPED_DECISION_REQUIRES_COMPLETE_PROPOSAL",
    ):
        service.CatalogAuthorityReviewDecision(
            signature_id="0123456789abcdef",
            disposition="PROPOSE_NEW_TYPE",
            proposed_cluster="home_textiles",
            proposed_product_type_group=None,
            proposed_scene_strategy_id="BATH_LINEN",
            confidence="HIGH",
            evidence_basis=["approved description"],
            exact_reason="The supplied evidence proves a textile product.",
        )


def test_mission_review_ledger_accepts_sanitized_timeout_receipts() -> None:
    ledger = service.CatalogAuthorityMissionReviewLedger(
        mission_id=service.P58_MISSION_ID,
        configured_provider_id="deepseek",
        configured_model="deepseek-v4-pro",
        request_count=2,
        valid_provider_decision_count=0,
        accepted_provider_decision_count=0,
        rejected_provider_decision_count=0,
        blocked_provider_decision_count=0,
        attempts=[
            service.CatalogAuthorityReviewAttempt(
                call_number=call_number,
                batch_signature_count=batch_size,
                provider_id="deepseek",
                model="deepseek-v4-pro",
                status="FAILED_NO_VALID_RESPONSE",
                response_status="TIMEOUT",
                duration_seconds=42.0,
                valid_decision_count=0,
                error_type="httpx.ReadTimeout",
            )
            for call_number, batch_size in ((1, 20), (2, 10))
        ],
    )

    serialized = ledger.model_dump(mode="json")
    assert serialized["request_count"] == 2
    assert serialized["raw_provider_output_retained"] is False
    assert serialized["canonical_mutation_from_provider_output"] is False


def test_mission_review_ledger_rejects_inconsistent_accounting() -> None:
    with pytest.raises(ValueError, match="P58_REVIEW_REQUEST_COUNT_MISMATCH"):
        service.CatalogAuthorityMissionReviewLedger(
            mission_id=service.P58_MISSION_ID,
            configured_provider_id="deepseek",
            configured_model="deepseek-v4-pro",
            request_count=1,
            valid_provider_decision_count=0,
            accepted_provider_decision_count=0,
            rejected_provider_decision_count=0,
            blocked_provider_decision_count=0,
            attempts=[],
        )
