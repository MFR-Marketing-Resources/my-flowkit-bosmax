"""Persistent formula-native Copy Register V2 workflow.

The service deliberately has no dependency on the legacy copy ledgers.  It
reads only Product Truth and the V2 evidence/blueprint/binding tables, and it
uses the existing formula authority plus the frozen V2 domain service for
validation, approval, projection, and binding.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from agent.authority.copy_blueprint_v2_authority import (
    formula_version,
    is_production_formula,
    required_formula_stage_keys,
    strict_formula_contract,
    strict_formula_id,
)
from agent.authority.copy_formula_registry import FORMULA_REGISTRY
from agent.authority.copy_lane_matrix import get_lane_descriptor, producer_consumer_matrix
from agent.db.schema import _db_lock, get_db
from agent.models.copy_blueprint_v2 import (
    Angle,
    ApprovalSnapshot,
    ApprovedExecutionText,
    BridgeContract,
    CopyBlueprintV2,
    CopyBlueprintV2FeatureFlagState,
    CopyExecutionBinding,
    EvidenceFact,
    EvidenceLineage,
    EvidenceReference,
    EvidenceRegistry,
    FormulaStage,
    Objective,
    ProductTruthLineage,
    ProvenanceEntry,
    ProductionReadinessProof,
    SemanticReviewProof,
    StageValidation,
    digest_evidence_text,
    digest_json,
)
from agent.services.copy_blueprint_v2_service import (
    CopyBlueprintV2Error,
    _blueprint_digest,
    approve_copy_blueprint_v2,
    bind_copy_blueprint_v2,
    create_blueprint_revision,
    validate_copy_blueprint_v2,
)


class CopyRegisterV2Error(ValueError):
    """Stable API/service error for the new Copy Register workflow."""

    def __init__(self, code: str, message: str, *, status_code: int = 409, details: Any = None):
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return value


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _truth_digest(snapshot: dict[str, Any]) -> str:
    """Digest only the Product Truth authority fields used by V2 copy."""

    payload = {
        key: snapshot.get(key)
        for key in (
            "snapshot_id",
            "version",
            "claim_gate",
            "claim_risk_level",
            "product_description",
            "benefits_json",
            "usp_json",
            "hook_angles_json",
            "pain_points_json",
            "usage_text",
            "target_customer_text",
            "allowed_claims_json",
            "blocked_claims_json",
            "buyer_persona_snapshot_json",
            "copy_strategy_summary_json",
            "warnings_text",
        )
    }
    return _sha256(payload)


def _present(value: Any) -> bool:
    return value is not None and _clean(value).lower() not in {"", "[]", "{}", "null"}


def _parse_list(value: Any) -> list[str]:
    parsed = _loads(value, value if isinstance(value, list) else [])
    if not isinstance(parsed, list):
        return []
    return [_clean(item) for item in parsed if _clean(item)]


def _parse_dict(value: Any) -> dict[str, Any]:
    parsed = _loads(value, value if isinstance(value, dict) else {})
    return parsed if isinstance(parsed, dict) else {}


def _formula_items() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for formula_id, formula in FORMULA_REGISTRY.items():
        if formula.get("definition_status") != "CANONICAL":
            continue
        rows.append(
            {
                "formula_id": formula_id,
                "formula_version": formula_version(formula_id),
                "display_name": formula.get("display_name", formula_id),
                "definition_status": formula.get("definition_status"),
                "compiler_family": formula.get("compiler_family", formula_id),
                "slots": formula.get("slots", []),
                "best_for": formula.get("best_for", []),
                "unsuitable_for": formula.get("unsuitable_for", []),
            }
        )
    return rows


def list_formulas() -> list[dict[str, Any]]:
    return _formula_items()


def _require_formula(formula_id: str) -> tuple[str, dict[str, Any]]:
    token = _clean(formula_id)
    if not token:
        raise CopyRegisterV2Error("COPY_V2_FORMULA_REQUIRED", "Select an explicit registered formula.", status_code=422)
    try:
        canonical = strict_formula_id(token)
        contract = strict_formula_contract(canonical)
    except Exception as exc:  # noqa: BLE001 - normalize authority failures
        code = getattr(exc, "code", "COPY_V2_UNKNOWN_FORMULA")
        raise CopyRegisterV2Error(code, "Formula is not registered; no default or HSO fallback is permitted.", status_code=422) from exc
    if not is_production_formula(canonical):
        raise CopyRegisterV2Error(
            "COPY_V2_FORMULA_NOT_PRODUCTION_SUPPORTED",
            "Only canonical repository formulas can produce a production blueprint.",
            status_code=422,
        )
    return canonical, contract


async def _product_truth_rows(product_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    db = await get_db()
    product_cursor = await db.execute("SELECT * FROM product WHERE id = ?", (product_id,))
    product_row = await product_cursor.fetchone()
    snapshot_cursor = await db.execute(
        """
        SELECT * FROM product_intelligence_snapshot
        WHERE product_id = ? AND status = 'APPROVED'
        ORDER BY version DESC, approved_at DESC, created_at DESC, snapshot_id DESC
        LIMIT 1
        """,
        (product_id,),
    )
    snapshot_row = await snapshot_cursor.fetchone()
    return (
        dict(product_row) if product_row else None,
        dict(snapshot_row) if snapshot_row else None,
    )


def _fact_candidates(product: dict[str, Any], snapshot: dict[str, Any]) -> list[EvidenceFact]:
    product_id = str(product["id"])
    snapshot_id = str(snapshot["snapshot_id"])
    version = int(snapshot["version"])
    specs: list[tuple[str, str, Any]] = [
        ("product_description", "PRODUCT_DESCRIPTION", snapshot.get("product_description")),
        ("benefits_json", "BENEFIT", _parse_list(snapshot.get("benefits_json"))),
        ("usp_json", "USP", _parse_list(snapshot.get("usp_json"))),
        ("allowed_claims_json", "ALLOWED_CLAIM", _parse_list(snapshot.get("allowed_claims_json"))),
        ("target_customer_text", "TARGET_CUSTOMER", snapshot.get("target_customer_text")),
        ("pain_points_json", "PAIN_POINT", _parse_list(snapshot.get("pain_points_json"))),
        ("usage_text", "USAGE", snapshot.get("usage_text")),
    ]
    facts: list[EvidenceFact] = []
    for field_name, fact_kind, raw in specs:
        values = raw if isinstance(raw, list) else [raw]
        for index, value in enumerate(values):
            text = _clean(value)
            if not text:
                continue
            fact_id = f"fact:{product_id}:{field_name}:{index}"
            facts.append(
                EvidenceFact(
                    snapshot_id=snapshot_id,
                    fact_id=fact_id,
                    product_id=product_id,
                    fact_kind=fact_kind,
                    text=text,
                    text_digest=digest_evidence_text(text),
                    snapshot_version=version,
                    snapshot_status="APPROVED",
                    approved=True,
                    source_ref=f"product-intelligence:{snapshot_id}:{field_name}[{index}]",
                )
            )
    return facts


def _lineage(product: dict[str, Any], snapshot: dict[str, Any]) -> ProductTruthLineage:
    return ProductTruthLineage(
        product_id=str(product["id"]),
        snapshot_id=str(snapshot["snapshot_id"]),
        snapshot_version=int(snapshot["version"]),
        snapshot_digest=_truth_digest(snapshot),
        snapshot_status="APPROVED",
        approved_by=_clean(snapshot.get("approved_by")) or None,
        approved_at=_clean(snapshot.get("approved_at")) or None,
    )


def _truth_gate(product: dict[str, Any] | None, snapshot: dict[str, Any] | None) -> list[str]:
    if not product:
        return ["PRODUCT_NOT_FOUND"]
    if not snapshot:
        return ["V2_PRODUCT_TRUTH_APPROVAL_REQUIRED"]
    required = (
        "product_description", "benefits_json", "usp_json", "target_customer_text",
        "allowed_claims_json", "buyer_persona_snapshot_json", "copy_strategy_summary_json",
        "claim_gate", "claim_risk_level",
    )
    missing = [field for field in required if not _present(snapshot.get(field))]
    if missing:
        return ["V2_PRODUCT_TRUTH_INCOMPLETE:" + ",".join(missing)]
    claim_gate = _clean(snapshot.get("claim_gate")).upper()
    if claim_gate == "CLAIM_REVIEW_REQUIRED":
        return ["V2_PRODUCT_TRUTH_CLAIM_REVIEW_REQUIRED"]
    if claim_gate != "CLAIM_SAFE":
        return ["V2_PRODUCT_TRUTH_CLAIM_GATE_BLOCKED"]
    if _clean(product.get("lifecycle_status") or "ACTIVE").upper() != "ACTIVE":
        return ["V2_PRODUCT_TRUTH_PRODUCT_INACTIVE"]
    return []


async def _ensure_evidence_facts(facts: Iterable[EvidenceFact]) -> None:
    rows = list(facts)
    if not rows:
        raise CopyRegisterV2Error(
            "COPY_V2_EVIDENCE_REQUIRED",
            "The current approved Product Truth has no evidence-backed facts.",
            status_code=409,
        )
    db = await get_db()
    async with _db_lock:
        for fact in rows:
            cursor = await db.execute(
                "SELECT * FROM copy_evidence_fact_v2 WHERE snapshot_id = ? AND fact_id = ?",
                (fact.snapshot_id, fact.fact_id),
            )
            existing = await cursor.fetchone()
            if existing:
                if existing["text_digest"] != fact.text_digest or existing["canonical_text"] != fact.text:
                    raise CopyRegisterV2Error(
                        "COPY_V2_EVIDENCE_IMMUTABLE",
                        "The stable evidence identity has conflicting wording; create a new Product Truth snapshot.",
                        status_code=409,
                    )
                continue
            await db.execute(
                """
                INSERT INTO copy_evidence_fact_v2
                (product_id, snapshot_id, fact_id, fact_kind, canonical_text, text_digest,
                 snapshot_version, snapshot_status, approved, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.product_id, fact.snapshot_id, fact.fact_id, fact.fact_kind,
                    fact.text, fact.text_digest, fact.snapshot_version, fact.snapshot_status,
                    int(fact.approved), fact.source_ref, _now(),
                ),
            )
        await db.commit()


async def get_product_truth_proof(product_id: str) -> dict[str, Any]:
    product, snapshot = await _product_truth_rows(product_id)
    blockers = _truth_gate(product, snapshot)
    if not product:
        raise CopyRegisterV2Error("PRODUCT_NOT_FOUND", "Selected product was not found.", status_code=404)
    facts = _fact_candidates(product, snapshot) if snapshot else []
    lineage = _lineage(product, snapshot) if snapshot else None
    persona = _parse_dict(snapshot.get("buyer_persona_snapshot_json")) if snapshot else {}
    return {
        "product_id": product_id,
        "product": {
            "display_name": _clean(product.get("product_display_name") or product.get("raw_product_title")),
            "category": _clean(product.get("category")),
            "subcategory": _clean(product.get("subcategory")),
            "product_type": _clean(product.get("type") or product.get("product_type")),
            "product_family": _clean(product.get("bosmax_product_family")),
            "cluster": _clean(product.get("silo")),
        },
        "product_truth": {
            "approved": snapshot is not None,
            "snapshot": {
                "snapshot_id": snapshot.get("snapshot_id"),
                "version": snapshot.get("version"),
                "status": snapshot.get("status"),
                "digest": lineage.snapshot_digest if lineage else None,
                "approved_by": snapshot.get("approved_by"),
                "approved_at": snapshot.get("approved_at"),
            } if snapshot else None,
            "lineage": lineage.model_dump(mode="json") if lineage else None,
            "persona": persona,
            "allowed_claims": _parse_list(snapshot.get("allowed_claims_json")) if snapshot else [],
            "blocked_claims": _parse_list(snapshot.get("blocked_claims_json")) if snapshot else [],
            "warnings": _parse_list(snapshot.get("warnings_text")) if snapshot else [],
        },
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "blockers": blockers,
        "ready_for_copy": not blockers and bool(facts),
        "legacy_copy_rows_read": 0,
    }


def _angle_options(product: dict[str, Any], snapshot: dict[str, Any], facts: list[EvidenceFact]) -> list[dict[str, Any]]:
    fact_by_text = {fact.text.casefold(): fact for fact in facts}
    raw_values: list[str] = []
    raw_values.extend(_parse_list(snapshot.get("hook_angles_json")))
    raw_values.extend(_parse_list(snapshot.get("pain_points_json")))
    raw_values.extend(_parse_list(snapshot.get("usp_json")))
    strategy = _parse_dict(snapshot.get("copy_strategy_summary_json"))
    for key in ("angle", "primary_angle", "summary", "positioning"):
        if _clean(strategy.get(key)):
            raw_values.append(_clean(strategy[key]))
    if not raw_values:
        raw_values.extend(fact.text for fact in facts[:3])
    seen: set[str] = set()
    options: list[dict[str, Any]] = []
    for index, text in enumerate(raw_values):
        normalized = _clean(text)
        if not normalized or normalized.casefold() in seen:
            continue
        seen.add(normalized.casefold())
        fact = fact_by_text.get(normalized.casefold())
        options.append(
            {
                "angle_id": f"angle:{snapshot['snapshot_id']}:{index}",
                "definition": normalized,
                "evidence_fact_ids": [fact.fact_id] if fact else [item.fact_id for item in facts[:1]],
                "source": "APPROVED_PRODUCT_TRUTH",
            }
        )
        if len(options) >= 8:
            break
    return options


async def generate_angle_options(product_id: str, formula_id: str, objective: str = "conversion") -> dict[str, Any]:
    canonical_formula, _ = _require_formula(formula_id)
    product, snapshot = await _product_truth_rows(product_id)
    blockers = _truth_gate(product, snapshot)
    if blockers:
        raise CopyRegisterV2Error(blockers[0], "Current approved Product Truth is required before angle generation.", status_code=409, details={"blockers": blockers})
    assert product is not None and snapshot is not None
    facts = _fact_candidates(product, snapshot)
    await _ensure_evidence_facts(facts)
    return {
        "product_id": product_id,
        "formula_id": canonical_formula,
        "formula_version": formula_version(canonical_formula),
        "objective": objective,
        "angles": _angle_options(product, snapshot, facts),
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "provider_calls": 0,
        "credit_spend": 0,
        "legacy_copy_rows_read": 0,
    }


async def _facts_for_refs(product: dict[str, Any], snapshot: dict[str, Any], fact_ids: list[str]) -> tuple[EvidenceFact, ...]:
    if not fact_ids:
        raise CopyRegisterV2Error("COPY_V2_EVIDENCE_REQUIRED", "Select at least one approved evidence fact.", status_code=422)
    if len(fact_ids) > 5:
        raise CopyRegisterV2Error("COPY_V2_EVIDENCE_LIMIT", "Select no more than five evidence-backed USP facts.", status_code=422)
    if len(set(fact_ids)) != len(fact_ids):
        raise CopyRegisterV2Error("COPY_V2_EVIDENCE_DUPLICATE", "Evidence facts must be unique.", status_code=422)
    expected = {fact.fact_id: fact for fact in _fact_candidates(product, snapshot)}
    selected: list[EvidenceFact] = []
    for fact_id in fact_ids:
        fact = expected.get(fact_id)
        if fact is None or fact.snapshot_id != snapshot["snapshot_id"] or not fact.approved:
            raise CopyRegisterV2Error("COPY_V2_EVIDENCE_INVALID", "Every selected USP must be an approved fact in the current snapshot.", status_code=409, details={"fact_id": fact_id})
        selected.append(fact)
    await _ensure_evidence_facts(expected.values())
    return tuple(selected)


def _render_stage_text(slot: str, *, product_name: str, angle: str, facts: tuple[EvidenceFact, ...], variant: int = 0) -> str:
    fact = facts[(variant + len(slot)) % len(facts)].text
    if slot in {"cta", "action", "response"}:
        return f"Semak maklumat {product_name} dan pilih langkah seterusnya untuk angle ini."
    if slot in {"problem", "pain", "hook", "attention"}:
        return f"{angle}: mula dengan perkara sebenar yang penting kepada rutin anda — {fact}."
    if slot in {"agitate", "amplify", "emotion", "story"}:
        return f"Bila {angle.lower()}, kejelasan membantu anda menilai pilihan tanpa menambah janji — {fact}."
    if slot in {"solution", "offer", "bridge"}:
        return f"{product_name} diposisikan berdasarkan fakta yang boleh disemak: {fact}."
    if slot in {"transformation", "desire", "interest", "after"}:
        return f"Bina keputusan yang munasabah daripada {fact}, selari dengan angle {angle.lower()}."
    if slot == "before":
        return f"Sebelum memilih, kenal pasti konteks {angle.lower()} dan semak fakta ini: {fact}."
    return f"Untuk {angle.lower()}, gunakan fakta Product Truth ini sebagai panduan: {fact}."


def _build_stages(formula_id: str, *, blueprint_id: str, product_name: str, angle: str,
                  facts: tuple[EvidenceFact, ...], variant: int = 0) -> tuple[FormulaStage, ...]:
    slots = required_formula_stage_keys(formula_id)
    stages: list[FormulaStage] = []
    previous_exit = f"{formula_id}:OPEN"
    for index, slot in enumerate(slots):
        stage_key = f"stage-{index}-{slot}"
        exit_token = f"{formula_id}:STAGE:{index}"
        claim_bearing = slot not in {"cta", "action", "response"}
        refs = tuple(fact.reference() for fact in facts) if claim_bearing else ()
        stages.append(
            FormulaStage(
                stage_key=stage_key,
                order=index,
                authored_text=_render_stage_text(
                    slot, product_name=product_name, angle=angle, facts=facts, variant=variant + index,
                ),
                semantic_role=slot,
                component_ref=f"v2-component:{blueprint_id}:{stage_key}",
                formula_stage_key=slot,
                bridge=BridgeContract(
                    entry=previous_exit,
                    exit=exit_token,
                    continuity_requirements=("preserve selected angle", "do not invent evidence"),
                ),
                claim_bearing=claim_bearing,
                fact_refs=refs,
                validation=StageValidation(valid=True),
            )
        )
        previous_exit = exit_token
    return tuple(stages)


def _new_blueprint(*, product: dict[str, Any], snapshot: dict[str, Any], formula_id: str,
                   objective: Objective, angle: Angle, facts: tuple[EvidenceFact, ...],
                   target_duration_seconds: float | None = None) -> CopyBlueprintV2:
    blueprint_id = f"bpv2_{uuid.uuid4().hex[:20]}"
    stages = _build_stages(
        formula_id,
        blueprint_id=blueprint_id,
        product_name=_clean(product.get("product_display_name") or product.get("raw_product_title")) or "produk ini",
        angle=angle.definition,
        facts=facts,
    )
    lineage = _lineage(product, snapshot)
    return CopyBlueprintV2(
        blueprint_id=blueprint_id,
        product_id=str(product["id"]),
        revision=1,
        status="DRAFT",
        formula_id=formula_id,
        formula_version=formula_version(formula_id),
        objective=objective,
        angle=angle,
        stages=stages,
        component_refs=tuple(stage.component_ref for stage in stages if stage.component_ref),
        evidence_refs=tuple(fact.reference() for fact in facts),
        target_duration_seconds=target_duration_seconds,
        wps_profile="COPY_REGISTER_V2_DETERMINISTIC",
        estimated_word_count=sum(len(stage.authored_text.split()) for stage in stages),
        semantic_review=None,
        provenance=(
            ProvenanceEntry(key="source", value="COPY_REGISTER_V2"),
            ProvenanceEntry(key="formula_authority", value="copy-formula-registry-v1"),
            ProvenanceEntry(key="generator", value="deterministic-v2-fake"),
            ProvenanceEntry(key="product_truth_snapshot", value=str(snapshot["snapshot_id"])),
        ),
        product_truth_lineage=lineage,
        created_at=_now(),
    )


def _blueprint_row_values(blueprint: CopyBlueprintV2) -> tuple[Any, ...]:
    lineage = blueprint.product_truth_lineage
    return (
        blueprint.blueprint_id,
        blueprint.product_id,
        blueprint.revision,
        blueprint.status,
        blueprint.formula_id,
        blueprint.formula_version,
        _json(blueprint.objective.model_dump(mode="json")),
        _json(blueprint.angle.model_dump(mode="json")),
        _json([stage.model_dump(mode="json") for stage in blueprint.stages]),
        _json(list(blueprint.component_refs)),
        _json([ref.model_dump(mode="json") for ref in blueprint.evidence_refs]),
        _json(lineage.model_dump(mode="json")),
        lineage.snapshot_id,
        lineage.snapshot_version,
        lineage.snapshot_digest,
        _json([item.model_dump(mode="json") for item in blueprint.approved_execution_text]),
        _json(blueprint.approval_snapshot.model_dump(mode="json")) if blueprint.approval_snapshot else None,
        _json(blueprint.semantic_review.model_dump(mode="json")) if blueprint.semantic_review else None,
        _json(blueprint.readiness_proof.model_dump(mode="json")) if blueprint.readiness_proof else None,
        _json(blueprint.supersedes.model_dump(mode="json")) if blueprint.supersedes else None,
        _json([item.model_dump(mode="json") for item in blueprint.provenance]),
        blueprint.target_duration_seconds,
        blueprint.wps_profile,
        blueprint.estimated_word_count,
        _blueprint_digest(blueprint),
        blueprint.created_at,
        blueprint.approved_at,
        blueprint.approved_by,
    )


async def _insert_blueprint(blueprint: CopyBlueprintV2) -> CopyBlueprintV2:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO copy_blueprint_v2
            (blueprint_id, product_id, revision, status, formula_id, formula_version,
             objective_json, angle_json, stages_json, component_refs_json, evidence_refs_json,
             product_truth_lineage_json, product_truth_snapshot_id, product_truth_snapshot_version,
             product_truth_snapshot_digest, approved_execution_text_json, approval_snapshot_json,
             semantic_review_json, readiness_proof_json, supersedes_json, provenance_json, target_duration_seconds,
             wps_profile, estimated_word_count, blueprint_digest, created_at, approved_at, approved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _blueprint_row_values(blueprint),
        )
        await db.commit()
    return blueprint


def _row_to_blueprint(row: Any) -> CopyBlueprintV2:
    data = dict(row)
    return CopyBlueprintV2(
        blueprint_id=data["blueprint_id"],
        product_id=data["product_id"],
        revision=int(data["revision"]),
        status=data["status"],
        formula_id=data["formula_id"],
        formula_version=data["formula_version"],
        objective=_loads(data["objective_json"], {}),
        angle=_loads(data["angle_json"], {}),
        stages=tuple(_loads(data["stages_json"], [])),
        component_refs=tuple(_loads(data["component_refs_json"], [])),
        evidence_refs=tuple(_loads(data["evidence_refs_json"], [])),
        product_truth_lineage=_loads(data["product_truth_lineage_json"], {}),
        target_duration_seconds=data["target_duration_seconds"],
        wps_profile=data["wps_profile"],
        estimated_word_count=int(data["estimated_word_count"] or 0),
        approval_snapshot=_loads(data["approval_snapshot_json"], None),
        approved_execution_text=tuple(_loads(data["approved_execution_text_json"], [])),
        semantic_review=_loads(data["semantic_review_json"], None),
        readiness_proof=_loads(data["readiness_proof_json"], None),
        provenance=tuple(_loads(data["provenance_json"], [])),
        supersedes=_loads(data["supersedes_json"], None),
        created_at=data["created_at"],
        approved_at=data["approved_at"],
        approved_by=data["approved_by"],
    )


async def _get_blueprint(blueprint_id: str, revision: int | None = None) -> CopyBlueprintV2:
    db = await get_db()
    if revision is None:
        cursor = await db.execute(
            "SELECT * FROM copy_blueprint_v2 WHERE blueprint_id = ? ORDER BY revision DESC LIMIT 1",
            (blueprint_id,),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM copy_blueprint_v2 WHERE blueprint_id = ? AND revision = ?",
            (blueprint_id, revision),
        )
    row = await cursor.fetchone()
    if not row:
        raise CopyRegisterV2Error("COPY_V2_BLUEPRINT_NOT_FOUND", "V2 blueprint was not found.", status_code=404)
    try:
        return _row_to_blueprint(row)
    except Exception as exc:  # noqa: BLE001
        raise CopyRegisterV2Error("COPY_V2_BLUEPRINT_INVALID", "Persisted V2 blueprint failed closed validation.", details=str(exc)) from exc


async def generate_blueprint(*, product_id: str, formula_id: str, objective_id: str,
                             objective_definition: str, angle_id: str, angle_definition: str,
                             evidence_fact_ids: list[str], target_duration_seconds: float | None = None) -> CopyBlueprintV2:
    canonical_formula, _ = _require_formula(formula_id)
    product, snapshot = await _product_truth_rows(product_id)
    blockers = _truth_gate(product, snapshot)
    if blockers:
        raise CopyRegisterV2Error(blockers[0], "An approved, production-ready Product Truth snapshot is required.", details={"blockers": blockers})
    assert product is not None and snapshot is not None
    facts = await _facts_for_refs(product, snapshot, evidence_fact_ids)
    options = _angle_options(product, snapshot, _fact_candidates(product, snapshot))
    selected = next((item for item in options if item["angle_id"] == angle_id and item["definition"] == _clean(angle_definition)), None)
    if selected is None:
        raise CopyRegisterV2Error("COPY_V2_ANGLE_NOT_GROUNDED", "Select an angle generated from the approved Product Truth.", status_code=422)
    blueprint = _new_blueprint(
        product=product,
        snapshot=snapshot,
        formula_id=canonical_formula,
        objective=Objective(objective_id=_clean(objective_id), definition=_clean(objective_definition)),
        angle=Angle(angle_id=_clean(angle_id), definition=_clean(angle_definition)),
        facts=facts,
        target_duration_seconds=target_duration_seconds,
    )
    result = validate_copy_blueprint_v2(
        blueprint,
        current_product_truth=_lineage(product, snapshot),
        evidence_registry=EvidenceRegistry(facts=facts),
    )
    if not result.valid:
        raise CopyRegisterV2Error("COPY_V2_BLUEPRINT_INVALID", "Generated formula stages failed validation.", details=result.model_dump(mode="json"))
    return await _insert_blueprint(blueprint)


async def list_blueprints(product_id: str) -> list[CopyBlueprintV2]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT b.*
        FROM copy_blueprint_v2 b
        JOIN (
            SELECT blueprint_id, MAX(revision) AS latest_revision
            FROM copy_blueprint_v2 WHERE product_id = ? GROUP BY blueprint_id
        ) latest ON latest.blueprint_id = b.blueprint_id AND latest.latest_revision = b.revision
        WHERE b.product_id = ? AND b.status NOT IN ('SUPERSEDED','BLOCKED')
        ORDER BY b.created_at DESC, b.blueprint_id DESC
        """,
        (product_id, product_id),
    )
    return [_row_to_blueprint(row) for row in await cursor.fetchall()]


async def get_blueprint(blueprint_id: str, revision: int | None = None) -> CopyBlueprintV2:
    return await _get_blueprint(blueprint_id, revision)


async def regenerate_stage(blueprint_id: str, stage_key: str) -> CopyBlueprintV2:
    previous = await _get_blueprint(blueprint_id)
    product, snapshot = await _product_truth_rows(previous.product_id)
    blockers = _truth_gate(product, snapshot)
    if blockers:
        raise CopyRegisterV2Error(blockers[0], "Current Product Truth is stale or unavailable; revision is blocked.", details={"blockers": blockers})
    assert product is not None and snapshot is not None
    facts = await _facts_for_refs(product, snapshot, [ref.fact_id for ref in previous.evidence_refs])
    matching = [stage for stage in previous.stages if stage.stage_key == stage_key]
    if not matching:
        raise CopyRegisterV2Error("COPY_V2_STAGE_NOT_FOUND", "Requested formula stage was not found.", status_code=404)
    new_text = _render_stage_text(
        matching[0].formula_stage_key,
        product_name=_clean(product.get("product_display_name") or product.get("raw_product_title")) or "produk ini",
        angle=previous.angle.definition,
        facts=facts,
        variant=previous.revision + 1,
    )
    stages = tuple(stage.model_copy(update={"authored_text": new_text, "validation": StageValidation(valid=True)}) if stage.stage_key == stage_key else stage for stage in previous.stages)
    revision = create_blueprint_revision(
        previous,
        stages=stages,
        evidence_refs=previous.evidence_refs,
        product_truth_lineage=_lineage(product, snapshot),
        created_at=_now(),
    ).model_copy(update={"semantic_review": None})
    return await _insert_blueprint(revision)


async def approve_blueprint(blueprint_id: str, *, approved_by: str, semantic_review: SemanticReviewProof,
                            readiness_proof: ProductionReadinessProof) -> CopyBlueprintV2:
    blueprint = await _get_blueprint(blueprint_id)
    if blueprint.status in {"APPROVED", "PRODUCTION_VALID", "SUPERSEDED"}:
        raise CopyRegisterV2Error("COPY_V2_APPROVED_IMMUTABLE", "Approved V2 copy can only change through a new revision.")
    if semantic_review.decision != "APPROVED":
        raise CopyRegisterV2Error("COPY_V2_SEMANTIC_REVIEW_REQUIRED", "Explicit approved semantic review is required.", status_code=422)
    if not all(readiness_proof.model_dump(mode="python").values()):
        raise CopyRegisterV2Error("COPY_V2_READINESS_REQUIRED", "All production readiness gates must be explicitly proven.", status_code=422)
    product, snapshot = await _product_truth_rows(blueprint.product_id)
    blockers = _truth_gate(product, snapshot)
    if blockers:
        raise CopyRegisterV2Error(blockers[0], "Current Product Truth is stale or unavailable; approval is blocked.", details={"blockers": blockers})
    assert product is not None and snapshot is not None
    facts = await _facts_for_refs(product, snapshot, [ref.fact_id for ref in blueprint.evidence_refs])
    current_lineage = _lineage(product, snapshot)
    if blueprint.product_truth_lineage != current_lineage:
        raise CopyRegisterV2Error("COPY_V2_PRODUCT_TRUTH_STALE", "Blueprint Product Truth lineage is stale; generate a new revision.")
    reviewed = blueprint.model_copy(update={"semantic_review": semantic_review, "readiness_proof": readiness_proof})
    validation = validate_copy_blueprint_v2(
        reviewed,
        current_product_truth=current_lineage,
        evidence_registry=EvidenceRegistry(facts=facts),
        require_semantic_review=True,
    )
    if not validation.valid:
        raise CopyRegisterV2Error("COPY_V2_BLUEPRINT_INVALID", "Blueprint cannot be approved while gates are blocked.", details=validation.model_dump(mode="json"))
    approved = approve_copy_blueprint_v2(
        reviewed,
        approved_by=approved_by,
        current_product_truth=current_lineage,
        evidence_registry=EvidenceRegistry(facts=facts),
        approved_at=_now(),
        semantic_review=semantic_review,
        readiness_proof=readiness_proof,
    ).model_copy(update={"status": "PRODUCTION_VALID"})
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            UPDATE copy_blueprint_v2 SET status=?, formula_id=?, formula_version=?,
              objective_json=?, angle_json=?, stages_json=?, component_refs_json=?, evidence_refs_json=?,
              product_truth_lineage_json=?, product_truth_snapshot_id=?, product_truth_snapshot_version=?,
              product_truth_snapshot_digest=?, approved_execution_text_json=?, approval_snapshot_json=?,
              semantic_review_json=?, readiness_proof_json=?, supersedes_json=?, provenance_json=?, target_duration_seconds=?,
              wps_profile=?, estimated_word_count=?, blueprint_digest=?, created_at=?, approved_at=?, approved_by=?
            WHERE blueprint_id=? AND revision=? AND status IN ('DRAFT','REVIEW_REQUIRED')
            """,
            _blueprint_row_values(approved)[3:] + (approved.blueprint_id, approved.revision),
        )
        await db.commit()
    return await _get_blueprint(approved.blueprint_id, approved.revision)


async def bind_blueprint(*, blueprint_id: str, lane: str,
                         feature_flags: CopyBlueprintV2FeatureFlagState) -> CopyExecutionBinding:
    try:
        descriptor = get_lane_descriptor(lane)
    except ValueError as exc:
        raise CopyRegisterV2Error("COPY_V2_UNKNOWN_LANE", str(exc), status_code=422) from exc
    if descriptor.copy_policy != "REQUIRED":
        raise CopyRegisterV2Error("COPY_V2_BINDING_NOT_REQUIRED", "This lane is explicitly COPY_NOT_REQUIRED.", status_code=422)
    blueprint = await _get_blueprint(blueprint_id)
    if blueprint.status != "PRODUCTION_VALID":
        raise CopyRegisterV2Error("V2 BINDING REQUIRED", "Only a V2 PRODUCTION_VALID blueprint can bind.")
    if blueprint.semantic_review is None or blueprint.semantic_review.decision != "APPROVED":
        raise CopyRegisterV2Error("COPY_V2_SEMANTIC_REVIEW_REQUIRED", "Semantic review proof is missing.")
    product, snapshot = await _product_truth_rows(blueprint.product_id)
    blockers = _truth_gate(product, snapshot)
    if blockers:
        raise CopyRegisterV2Error("COPY_V2_PRODUCT_TRUTH_STALE", "Current Product Truth is stale; binding is blocked.", details={"blockers": blockers})
    assert product is not None and snapshot is not None
    facts = await _facts_for_refs(product, snapshot, [ref.fact_id for ref in blueprint.evidence_refs])
    try:
        binding = bind_copy_blueprint_v2(
            blueprint,
            lane=descriptor.lane_id,
            current_product_truth=_lineage(product, snapshot),
            evidence_registry=EvidenceRegistry(facts=facts),
            feature_flags=feature_flags,
        )
    except CopyBlueprintV2Error as exc:
        raise CopyRegisterV2Error(exc.code, str(exc), details=exc.details) from exc
    db = await get_db()
    async with _db_lock:
        existing_cursor = await db.execute(
            "SELECT * FROM copy_execution_binding_v2 WHERE blueprint_id=? AND revision=? AND lane=?",
            (binding.blueprint_id, binding.revision, binding.lane),
        )
        existing = await existing_cursor.fetchone()
        if existing:
            persisted = _row_to_binding(existing)
            expected = binding.model_copy(
                update={
                    "binding_id": persisted.binding_id,
                    "bound_at": persisted.bound_at,
                }
            )
            if persisted != expected:
                raise CopyRegisterV2Error(
                    "COPY_V2_BINDING_CONFLICT",
                    "This blueprint revision and lane already have a different immutable binding.",
                    status_code=409,
                )
            return persisted
        await db.execute(
            """
            INSERT INTO copy_execution_binding_v2
            (binding_id, blueprint_id, revision, product_id, lane, media_kind, copy_policy,
             formula_id, formula_version, approval_snapshot_id, product_truth_lineage_json,
             evidence_lineage_json, evidence_digest, compiler_binding_version,
             feature_flag_state_json, binding_status, bound_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binding.binding_id, binding.blueprint_id, binding.revision, blueprint.product_id,
                binding.lane, binding.media_kind, binding.copy_policy, binding.formula_id,
                binding.formula_version, binding.approval_snapshot_id,
                _json(binding.product_truth_lineage.model_dump(mode="json")),
                _json(binding.evidence_lineage.model_dump(mode="json")),
                binding.evidence_lineage.evidence_digest,
                binding.compiler_binding_version,
                _json(binding.feature_flag_state.model_dump(mode="json")),
                binding.binding_status, binding.bound_at,
            ),
        )
        await db.commit()
    return binding


def _row_to_binding(row: Any) -> CopyExecutionBinding:
    data = dict(row)
    return CopyExecutionBinding(
        binding_id=data["binding_id"],
        lane=data["lane"],
        media_kind=data["media_kind"],
        copy_policy=data["copy_policy"],
        blueprint_id=data["blueprint_id"],
        revision=int(data["revision"]),
        formula_id=data["formula_id"],
        formula_version=data["formula_version"],
        approval_snapshot_id=data["approval_snapshot_id"],
        product_truth_lineage=_loads(data["product_truth_lineage_json"], {}),
        evidence_lineage=_loads(data["evidence_lineage_json"], {}),
        compiler_binding_version=data["compiler_binding_version"],
        feature_flag_state=_loads(data["feature_flag_state_json"], {}),
        binding_status=data["binding_status"],
        bound_at=data["bound_at"],
    )


async def get_binding(product_id: str, lane: str) -> CopyExecutionBinding:
    try:
        descriptor = get_lane_descriptor(lane)
    except ValueError as exc:
        raise CopyRegisterV2Error("COPY_V2_UNKNOWN_LANE", str(exc), status_code=422) from exc
    if descriptor.copy_policy != "REQUIRED":
        raise CopyRegisterV2Error(
            "COPY_V2_BINDING_NOT_REQUIRED",
            "This lane is explicitly COPY_NOT_REQUIRED.",
            status_code=422,
        )
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT * FROM copy_execution_binding_v2
        WHERE product_id=? AND lane=? AND binding_status='BOUND'
        ORDER BY revision DESC, bound_at DESC, binding_id DESC LIMIT 1
        """,
        (product_id, descriptor.lane_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise CopyRegisterV2Error("V2 BINDING REQUIRED", "No persisted V2 binding exists for this lane.")
    return _row_to_binding(row)


async def list_binding_matrix() -> list[dict[str, Any]]:
    return producer_consumer_matrix()


__all__ = [
    "CopyRegisterV2Error",
    "approve_blueprint",
    "bind_blueprint",
    "generate_angle_options",
    "generate_blueprint",
    "get_blueprint",
    "get_binding",
    "get_product_truth_proof",
    "list_binding_matrix",
    "list_blueprints",
    "list_formulas",
    "regenerate_stage",
]
