from __future__ import annotations

import json

import pytest

from agent.api import products as products_api
from agent.authority.copy_register_product_identity_authority import (
    PRODUCT_IDENTITY_STALE,
    find_product_identity_violation,
    validate_product_identity_text,
)
from agent.db import crud
from agent.db.schema import get_db
from agent.services import copy_register_v2_service as copy_service
from agent.services.copy_blueprint_v2_service import approve_copy_blueprint_v2, validate_copy_blueprint_v2
from agent.services.copy_execution_resolver import CopyExecutionResolutionError, resolve_copy_execution_binding
from tests.unit.test_copy_blueprint_v2_contract import _blueprint, _flags, _lineage, _registry
from tests.unit.test_copy_register_v2_cutover import _seed_truth


def _identity_product() -> dict[str, str]:
    return {
        "id": "identity-product",
        "brand": "Cap Burung",
        "raw_product_title": "Minyak Warisan Cap Burung 25ml",
        "product_display_name": "Minyak Warisan Cap Burung 25ml",
        "product_short_name": "Minyak Warisan Cap Burung",
    }


def test_product_identity_authority_allows_current_name_and_rejects_inserted_alias():
    product = _identity_product()

    assert validate_product_identity_text(
        "Minyak Warisan Cap Burung 25ml membantu rutin keluarga.", product
    ) == "Minyak Warisan Cap Burung 25ml membantu rutin keluarga."
    assert validate_product_identity_text(
        "Resipi tradisional warisan Cap Burung untuk kegunaan keluarga.", product
    )

    violation = find_product_identity_violation(
        "Minyak Warisan Tok Cap Burung 25ml membantu rutin keluarga.", product
    )
    assert violation is not None
    assert violation["code"] == PRODUCT_IDENTITY_STALE
    with pytest.raises(ValueError, match=PRODUCT_IDENTITY_STALE):
        validate_product_identity_text(
            "Resipi tradisional warisan Tok Cap Burung untuk keluarga.", product
        )


@pytest.mark.asyncio
async def test_current_product_truth_identity_mismatch_blocks_before_provider(monkeypatch):
    product, _snapshot = await _seed_truth()
    db = await get_db()
    await db.execute("UPDATE product SET brand=? WHERE id=?", ("Cap Burung", product["id"]))
    await db.execute(
        "UPDATE product_intelligence_snapshot SET product_description=?, usp_json=? WHERE snapshot_id=?",
        (
            "Minyak Warisan Tok Cap Burung 25ml ialah minyak tradisional.",
            json.dumps(["Resipi tradisional warisan Tok Cap Burung"]),
            _snapshot["snapshot_id"],
        ),
    )
    await db.commit()

    proof = await copy_service.get_product_truth_proof(product["id"])
    assert proof["ready_for_copy"] is False
    assert proof["blockers"] == [PRODUCT_IDENTITY_STALE]
    assert {item["field"] for item in proof["blocker_details"] if item["code"] == PRODUCT_IDENTITY_STALE} == {
        "product_description",
        "usp_json[0]",
    }

    called = False

    def forbidden_provider(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not run while identity truth is stale")

    monkeypatch.setattr(copy_service.ai_provider, "complete_json_with_receipt", forbidden_provider)
    with pytest.raises(copy_service.CopyRegisterV2Error) as blocked:
        await copy_service.generate_angle_options(product["id"], "PAS")
    assert blocked.value.code == PRODUCT_IDENTITY_STALE
    assert called is False


@pytest.mark.asyncio
async def test_stale_angle_output_is_rejected_before_candidate_persistence(monkeypatch):
    product, _snapshot = await _seed_truth()
    db = await get_db()
    before = int((await (await db.execute(
        "SELECT COUNT(*) FROM copy_angle_candidate_v2 WHERE product_id=?", (product["id"],)
    )).fetchone())[0])

    def stale_angle_provider(_system: str, _user: str):
        return {
            "angles": [{
                "definition": "Minyak Warisan Tok Cap Burung 25ml untuk rutin keluarga.",
                "evidence_fact_ids": [
                    f"fact:{product['id']}:product_description:0"
                ],
            }]
        }, {
            "call_id": 901,
            "lane": "text_assist",
            "provider_id": "synthetic-identity-provider",
            "model_id": "synthetic-identity-model",
            "transport": "synthetic",
            "response_status": "SUCCEEDED",
            "json_parse_status": "VALID",
            "completed_at": "2026-08-16T00:00:00Z",
        }

    monkeypatch.setattr(copy_service.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(copy_service.ai_provider, "complete_json_with_receipt", stale_angle_provider)
    with pytest.raises(copy_service.CopyRegisterV2Error) as rejected:
        await copy_service.generate_angle_options(product["id"], "PAS")
    assert rejected.value.code == PRODUCT_IDENTITY_STALE
    assert rejected.value.details["provider_receipt"]["call_id"] == 901
    after = int((await (await db.execute(
        "SELECT COUNT(*) FROM copy_angle_candidate_v2 WHERE product_id=?", (product["id"],)
    )).fetchone())[0])
    assert after == before


@pytest.mark.asyncio
async def test_stale_formula_stage_is_rejected_before_blueprint_persistence(monkeypatch):
    product, _snapshot = await _seed_truth()

    def valid_angle_provider(_system: str, user: str):
        payload = json.loads(user)
        fact = payload["facts"][0]
        return {"angles": [{
            "definition": f"Rutin keluarga: {fact['text']}",
            "evidence_fact_ids": [fact["fact_id"]],
        }]}, {
            "call_id": 900,
            "lane": "text_assist",
            "provider_id": "synthetic-identity-provider",
            "model_id": "synthetic-identity-model",
            "transport": "synthetic",
            "response_status": "SUCCEEDED",
            "json_parse_status": "VALID",
            "completed_at": "2026-08-16T00:00:00Z",
        }

    monkeypatch.setattr(copy_service.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(copy_service.ai_provider, "complete_json_with_receipt", valid_angle_provider)
    angles = await copy_service.generate_angle_options(product["id"], "PAS")
    selected = angles["angles"][0]
    db = await get_db()
    before = int((await (await db.execute(
        "SELECT COUNT(*) FROM copy_blueprint_v2 WHERE product_id=?", (product["id"],)
    )).fetchone())[0])

    def stale_formula_provider(_system: str, user: str):
        payload = json.loads(user)
        facts = payload["facts"]
        stages = []
        for index, stage_key in enumerate(payload["formula"]["ordered_stage_keys"]):
            stale_text = (
                "Minyak Warisan Tok Cap Burung 25ml melegakan rutin keluarga."
                if stage_key == "solution"
                else "Semak maklumat produk dan pilih langkah seterusnya."
                if stage_key == "cta"
                else facts[index % len(facts)]["text"]
            )
            stages.append({
                "formula_stage_key": stage_key,
                "text": stale_text,
                "evidence_fact_ids": [] if stage_key == "cta" else [facts[index % len(facts)]["fact_id"]],
            })
        return {"stages": stages}, {
            "call_id": 902,
            "lane": "text_assist",
            "provider_id": "synthetic-identity-provider",
            "model_id": "synthetic-identity-model",
            "transport": "synthetic",
            "response_status": "SUCCEEDED",
            "json_parse_status": "VALID",
            "completed_at": "2026-08-16T00:00:00Z",
        }

    monkeypatch.setattr(copy_service.ai_provider, "complete_json_with_receipt", stale_formula_provider)
    with pytest.raises(copy_service.CopyRegisterV2Error) as rejected:
        await copy_service.generate_blueprint(
            product_id=product["id"],
            formula_id="PAS",
            objective_id="conversion",
            objective_definition="A grounded conversion objective.",
            angle_id=selected["angle_id"],
            angle_definition=selected["definition"],
            evidence_fact_ids=selected["evidence_fact_ids"],
        )
    assert rejected.value.code == PRODUCT_IDENTITY_STALE
    assert rejected.value.details["provider_receipt"]["call_id"] == 902
    after = int((await (await db.execute(
        "SELECT COUNT(*) FROM copy_blueprint_v2 WHERE product_id=?", (product["id"],)
    )).fetchone())[0])
    assert after == before


@pytest.mark.asyncio
async def test_stale_persisted_angle_cannot_be_consumed_even_with_current_lineage():
    product, snapshot = await _seed_truth()
    db = await get_db()
    lineage = copy_service._lineage(product, snapshot)
    fact_id = f"fact:{product['id']}:product_description:0"
    await db.execute(
        """INSERT INTO copy_angle_candidate_v2
           (angle_id, product_id, product_truth_snapshot_id, product_truth_snapshot_version,
            product_truth_snapshot_digest, formula_id, formula_version, objective, definition,
            evidence_fact_ids_json, provider_receipt_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "identity-stale-angle",
            product["id"],
            lineage.snapshot_id,
            lineage.snapshot_version,
            lineage.snapshot_digest,
            "PAS",
            copy_service.formula_version("PAS"),
            "conversion",
            "Minyak Warisan Tok Cap Burung 25ml untuk rutin keluarga.",
            json.dumps([fact_id]),
            json.dumps({"call_id": 903}),
            "2026-08-16T00:00:00Z",
        ),
    )
    await db.commit()

    with pytest.raises(copy_service.CopyRegisterV2Error) as rejected:
        await copy_service._require_angle_candidate(
            product=product,
            snapshot=snapshot,
            formula_id="PAS",
            objective_id="conversion",
            angle_id="identity-stale-angle",
            angle_definition="Minyak Warisan Tok Cap Burung 25ml untuk rutin keluarga.",
            selected_fact_ids=[fact_id],
        )
    assert rejected.value.code == PRODUCT_IDENTITY_STALE


@pytest.mark.asyncio
async def test_product_truth_uses_canonical_copy_cluster_and_quarantines_legacy_silo():
    product, _snapshot = await _seed_truth()

    proof = await copy_service.get_product_truth_proof(product["id"])

    assert proof["ready_for_copy"] is True
    assert proof["product"]["cluster"] == "Traditional Wellness"
    assert proof["product"]["canonical_copy_cluster"] == "Traditional Wellness"
    assert proof["product"]["visual_internal_silo"] == "baby_care_universal_01"
    assert proof["product"]["visual_internal_silo_is_canonical_copy_cluster"] is False
    assert "NO_CANONICAL_VISUAL_SILO_AUTHORITY" in proof["authority"]["warnings"]
    assert proof["authority"]["authority_fingerprint"]
    assert len(proof["authority"]["authority_fingerprint"]) == 64
    repeat = await copy_service.get_product_truth_proof(product["id"])
    assert repeat["authority"]["authority_fingerprint"] == proof["authority"]["authority_fingerprint"]


@pytest.mark.asyncio
async def test_legacy_silo_change_does_not_invalidate_copy_authority():
    product, _snapshot = await _seed_truth()
    before = await copy_service.get_product_truth_proof(product["id"])

    db = await get_db()
    await db.execute(
        "UPDATE product SET silo=? WHERE id=?",
        ("visual_only_silo_changed", product["id"]),
    )
    await db.commit()

    after = await copy_service.get_product_truth_proof(product["id"])
    assert after["ready_for_copy"] is True
    assert after["authority"]["authority_fingerprint"] == before["authority"]["authority_fingerprint"]
    assert (
        after["authority"]["strategy_taxonomy"]["fingerprint_scope"]
        == "copy-register-strategy-product-subset-v1"
    )


@pytest.mark.asyncio
async def test_auto_derived_strategy_authority_is_not_copy_consumable():
    product, _snapshot = await _seed_truth()
    db = await get_db()
    await db.execute(
        """UPDATE product_strategy_taxonomy
           SET review_status=?, consumer_status=?, authority_source=?
           WHERE product_id=?""",
        ("REVIEW_REQUIRED", "BLOCKED_REVIEW_REQUIRED", "AUTO_DERIVED", product["id"]),
    )
    await db.commit()

    proof = await copy_service.get_product_truth_proof(product["id"])
    assert proof["ready_for_copy"] is False
    assert "V2_PRODUCT_TRUTH_STRATEGY_AUTHORITY_STALE" in proof["blockers"]
    assert any(
        detail["field"] == "authority_source"
        and detail["observed"] == "AUTO_DERIVED"
        and detail["expected"] == "MANUAL_OVERRIDE"
        for detail in proof["blocker_details"]
        if detail["code"] == "V2_PRODUCT_TRUTH_STRATEGY_AUTHORITY_STALE"
    )


@pytest.mark.asyncio
async def test_mismatched_canonical_taxonomy_blocks_before_provider_call(monkeypatch):
    product, _snapshot = await _seed_truth()
    db = await get_db()
    await db.execute(
        "UPDATE product SET category=? WHERE id=?",
        ("Beauty & Personal Care", product["id"]),
    )
    await db.commit()

    proof = await copy_service.get_product_truth_proof(product["id"])
    assert proof["ready_for_copy"] is False
    assert "V2_PRODUCT_TRUTH_TAXONOMY_DRIFT" in proof["blockers"]
    assert any(
        detail["field"] == "category"
        for detail in proof["blocker_details"]
        if detail["code"] == "V2_PRODUCT_TRUTH_TAXONOMY_DRIFT"
    )

    called = False

    def forbidden_provider(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not run while Product Truth is blocked")

    monkeypatch.setattr(copy_service.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(copy_service.ai_provider, "complete_json_with_receipt", forbidden_provider)
    with pytest.raises(copy_service.CopyRegisterV2Error) as blocked:
        await copy_service.generate_angle_options(product["id"], "PAS")
    assert blocked.value.code == "V2_PRODUCT_TRUTH_TAXONOMY_DRIFT"
    assert called is False


def test_taxonomy_authority_fingerprint_drift_is_distinct_from_snapshot_drift():
    source = _lineage()
    approved = _blueprint()
    approved_lineage = source.model_copy(
        update={
            "taxonomy_authority_version": "copy-register-product-truth-authority-v1",
            "taxonomy_authority_fingerprint": "a" * 64,
        }
    )
    artifact = approved.model_copy(update={"product_truth_lineage": approved_lineage})
    current = approved_lineage.model_copy(update={"taxonomy_authority_fingerprint": "b" * 64})

    result = validate_copy_blueprint_v2(
        artifact,
        current_product_truth=current,
        evidence_registry=_registry(),
    )

    assert result.valid is False
    assert "COPY_V2_TAXONOMY_AUTHORITY_STALE" in result.error_codes
    assert "COPY_V2_EVIDENCE_STALE" not in result.error_codes


def test_taxonomy_authority_drift_fails_closed_at_consumer_resolution():
    source = _lineage()
    authored_lineage = source.model_copy(
        update={
            "taxonomy_authority_version": "copy-register-product-truth-authority-v1",
            "taxonomy_authority_fingerprint": "a" * 64,
        }
    )
    approved = approve_copy_blueprint_v2(
        _blueprint().model_copy(update={"product_truth_lineage": authored_lineage}),
        approved_by="authority-remediation-test",
        current_product_truth=authored_lineage,
        evidence_registry=_registry(),
    )
    current = authored_lineage.model_copy(update={"taxonomy_authority_fingerprint": "b" * 64})
    context = {
        "current_product_truth": current.model_dump(mode="json"),
        "evidence_facts": [fact.model_dump(mode="json") for fact in _registry().facts],
        "feature_flags": _flags().model_dump(mode="json"),
        "blueprint": approved.model_dump(mode="json"),
        "readiness_validated": True,
        "provenance_validated": True,
        "safety_validated": True,
        "semantic_review_validated": True,
    }

    with pytest.raises(CopyExecutionResolutionError) as blocked:
        resolve_copy_execution_binding("product-1", "T2V", context)
    assert blocked.value.code == "COPY_V2_TAXONOMY_AUTHORITY_STALE"


@pytest.mark.asyncio
async def test_mapping_get_is_pure_read_and_does_not_advance_product_timestamp():
    product = await crud.create_product(
        "Read-only Mapping Product",
        source="MANUAL",
        category="Health & Personal Care",
        subcategory="Traditional Wellness",
        type="Traditional Herbal Oils",
    )
    db = await get_db()
    before = await crud.get_product(product["id"])
    statements: list[str] = []
    await db.set_trace_callback(statements.append)
    try:
        response = await products_api.get_product_mapping(product["id"])
    finally:
        await db.set_trace_callback(None)
    after = await crud.get_product(product["id"])

    assert response["product_id"] == product["id"]
    for field in ("category", "subcategory", "type", "silo", "mapping_status", "updated_at"):
        assert after[field] == before[field]
    assert after["updated_at"] == before["updated_at"]
    writes = [
        statement.strip().upper()
        for statement in statements
        if statement.strip().upper().startswith(("UPDATE ", "INSERT ", "DELETE ", "REPLACE "))
    ]
    assert writes == []
