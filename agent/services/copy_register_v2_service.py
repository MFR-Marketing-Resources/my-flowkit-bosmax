"""Persistent formula-native Copy Register V2 workflow.

The service deliberately has no dependency on the legacy copy ledgers.  It
reads only Product Truth and the V2 evidence/blueprint/binding tables, and it
uses the existing formula authority plus the frozen V2 domain service for
validation, approval, projection, and binding.
"""
from __future__ import annotations

import hashlib
import json
import re
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
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services.ai_provider_settings_service import summarize_provider_settings
from agent.services.product_intelligence_claim_safety_service import (
    evaluate_claim_safety,
)


ANGLE_PROMPT_VERSION = "copy-register-v2-angle-options-v1"
FORMULA_PROMPT_VERSION = "copy-register-v2-formula-blueprint-v1"
STAGE_REGEN_PROMPT_VERSION = "copy-register-v2-stage-regeneration-v1"

_ANGLE_SYSTEM_PROMPT = f"""You are the formula-native Copy Register V2 angle author.
Prompt contract: {ANGLE_PROMPT_VERSION}.
Return strict JSON only: {{"angles":[{{"definition":str,"evidence_fact_ids":[str]}}]}}.
Create 3-8 materially distinct selling angles in the requested language and objective.
Every angle must be supported only by the supplied approved Product Truth facts. Use only
the supplied fact_id values, cite at least one per angle, and never invent a fact, number,
ingredient, outcome, offer, certification, price, guarantee, medical claim, or internal ID
inside the visible definition. Do not choose or change the formula."""

_FORMULA_SYSTEM_PROMPT = f"""You are the formula-native Copy Register V2 blueprint author.
Prompt contract: {FORMULA_PROMPT_VERSION}.
Return strict JSON only: {{"stages":[{{"formula_stage_key":str,"text":str,
"evidence_fact_ids":[str]}}]}}. Return every supplied formula stage exactly once and in
the supplied order. Write one coherent hook-to-CTA message around the selected angle; do
not write independent fragments. Every claim-bearing stage must cite one or more supplied
fact_id values. Use no fact outside the supplied list and never invent a fact, number,
ingredient, outcome, offer, certification, price, guarantee, or medical claim. The CTA may
carry an empty evidence list but must not introduce a claim. Do not output hook/body/CTA
fields outside the ordered stages."""

_STAGE_REGEN_SYSTEM_PROMPT = f"""You regenerate one stage of a Copy Register V2 blueprint.
Prompt contract: {STAGE_REGEN_PROMPT_VERSION}.
Return strict JSON only: {{"stage":{{"formula_stage_key":str,"text":str,
"evidence_fact_ids":[str]}}}}. Rewrite only the requested stage while preserving the
formula role, selected angle, surrounding-stage continuity, and supplied Product Truth.
Use only supplied fact_id values. Never invent facts or claims. Do not rewrite or return
the other stages."""


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


def _provider_receipt(
    prompt_version: str,
    call_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Return secret-free text-assist provenance for one explicit authoring call."""

    if (
        not isinstance(call_receipt.get("call_id"), int)
        or call_receipt.get("response_status") != "SUCCEEDED"
        or call_receipt.get("json_parse_status") != "VALID"
        or not _clean(call_receipt.get("provider_id"))
        or not _clean(call_receipt.get("model_id"))
    ):
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_PROVENANCE_INVALID",
            "The text-assist result did not include a complete receipt for its exact provider call.",
            status_code=502,
        )
    return {
        "prompt_version": prompt_version,
        "lane": call_receipt.get("lane") or "text_assist",
        "provider_id": call_receipt.get("provider_id"),
        "model_id": call_receipt.get("model_id"),
        "transport": call_receipt.get("transport"),
        "call_id": call_receipt.get("call_id"),
        "response_status": call_receipt.get("response_status"),
        "json_parse_status": call_receipt.get("json_parse_status"),
        "completed_at": call_receipt.get("completed_at"),
    }


def _call_text_assist(
    *,
    system_prompt: str,
    payload: dict[str, Any],
    prompt_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute only from an explicit authoring endpoint and fail closed."""

    if not ai_provider.is_configured():
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_NOT_CONFIGURED",
            "Configure and enable the existing text_assist provider lane before generating V2 copy.",
            status_code=409,
        )
    try:
        result, call_receipt = ai_provider.complete_json_with_receipt(
            system_prompt,
            _json(payload),
        )
    except ai_provider.AICopyProviderNotConfigured as exc:
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_NOT_CONFIGURED",
            "The text_assist provider lane is not configured or enabled.",
            status_code=409,
        ) from exc
    except ai_provider.AICopyProviderError as exc:
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_FAILED",
            "The text_assist provider did not return a valid formula-native response.",
            status_code=502,
            details={"provider_error": exc.code, "diagnostic": exc.diagnostic_category},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - provider boundary normalization
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_FAILED",
            "The text_assist provider call failed closed.",
            status_code=502,
            details={"exception_type": type(exc).__name__},
        ) from exc
    if not isinstance(result, dict):
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_RESPONSE_INVALID",
            "The text_assist provider response must be one JSON object.",
            status_code=502,
        )
    return result, _provider_receipt(prompt_version, call_receipt)


_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?")


def _assert_generated_text_grounded(
    text: str,
    *,
    facts: Iterable[EvidenceFact],
    product: dict[str, Any],
    internal_ids: Iterable[str] = (),
) -> str:
    """Apply deterministic pre-review safety checks to provider-authored text."""

    normalized = _clean(text)
    if not normalized or len(normalized) > 1200:
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_RESPONSE_INVALID",
            "Generated V2 text is empty or exceeds the bounded stage contract.",
            status_code=502,
        )
    lowered = normalized.casefold()
    if any(_clean(item).casefold() in lowered for item in internal_ids if _clean(item)):
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_METADATA_LEAK",
            "Generated V2 text exposed an internal lineage identifier.",
            status_code=502,
        )
    fact_rows = tuple(facts)
    grounded_text = " ".join(
        [
            *(fact.text for fact in fact_rows),
            _clean(product.get("product_display_name")),
            _clean(product.get("raw_product_title")),
            _clean(product.get("product_short_name")),
        ]
    )
    grounded_numbers = set(_NUMBER_TOKEN.findall(grounded_text))
    unsupported_numbers = [
        token
        for token in _NUMBER_TOKEN.findall(normalized)
        if token not in grounded_numbers
    ]
    if unsupported_numbers:
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_UNGROUNDED_NUMBER",
            "Generated V2 text introduced a number absent from its cited Product Truth facts.",
            status_code=502,
            details={"tokens": unsupported_numbers},
        )
    safety = evaluate_claim_safety({"generated_copy": normalized}, product=product)
    if safety.get("claim_gate") != "CLAIM_SAFE":
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_UNSAFE",
            "Generated V2 text failed the deterministic claim-safety gate.",
            status_code=502,
            details={
                "claim_gate": safety.get("claim_gate"),
                "claim_tokens": safety.get("claim_tokens_json") or [],
            },
        )
    return normalized


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


def _angle_signals(snapshot: dict[str, Any], facts: list[EvidenceFact]) -> list[str]:
    """Collect approved source signals for the text-assist angle request."""

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
    signals: list[str] = []
    for text in raw_values:
        normalized = _clean(text)
        if not normalized or normalized.casefold() in seen:
            continue
        seen.add(normalized.casefold())
        signals.append(normalized)
        if len(signals) >= 12:
            break
    return signals


def _validate_ai_angle_options(
    raw: dict[str, Any],
    *,
    product: dict[str, Any],
    snapshot: dict[str, Any],
    facts: list[EvidenceFact],
) -> list[dict[str, Any]]:
    items = raw.get("angles")
    if not isinstance(items, list) or not (1 <= len(items) <= 8):
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_RESPONSE_INVALID",
            "Angle generation must return between one and eight structured candidates.",
            status_code=502,
        )
    fact_index = {fact.fact_id: fact for fact in facts}
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_RESPONSE_INVALID",
                "Every generated angle must be an object.",
                status_code=502,
            )
        ids = item.get("evidence_fact_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 5
            or len(set(str(value) for value in ids)) != len(ids)
        ):
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
                "Every generated angle must cite one to five unique approved facts.",
                status_code=502,
            )
        try:
            cited = tuple(fact_index[str(fact_id)] for fact_id in ids)
        except KeyError as exc:
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
                "Generated angle cited evidence outside the current Product Truth snapshot.",
                status_code=502,
                details={"fact_id": str(exc.args[0])},
            ) from exc
        definition = _assert_generated_text_grounded(
            item.get("definition"),
            facts=cited,
            product=product,
            internal_ids=(
                str(product["id"]),
                str(snapshot["snapshot_id"]),
                *(fact.fact_id for fact in cited),
            ),
        )
        if definition.casefold() in seen:
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_RESPONSE_INVALID",
                "Generated angle options must be materially distinct.",
                status_code=502,
            )
        seen.add(definition.casefold())
        options.append(
            {
                "angle_id": f"angv2_{uuid.uuid4().hex[:20]}",
                "definition": definition,
                "evidence_fact_ids": [fact.fact_id for fact in cited],
                "source": "TEXT_ASSIST_PRODUCT_TRUTH_V2",
            }
        )
    return options


async def _persist_angle_options(
    options: list[dict[str, Any]],
    *,
    product: dict[str, Any],
    snapshot: dict[str, Any],
    formula_id: str,
    objective: str,
    provider_receipt: dict[str, Any],
) -> None:
    lineage = _lineage(product, snapshot)
    db = await get_db()
    async with _db_lock:
        try:
            for item in options:
                await db.execute(
                    """
                    INSERT INTO copy_angle_candidate_v2
                    (angle_id, product_id, product_truth_snapshot_id,
                     product_truth_snapshot_version, product_truth_snapshot_digest,
                     formula_id, formula_version, objective, definition,
                     evidence_fact_ids_json, provider_receipt_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["angle_id"],
                        product["id"],
                        lineage.snapshot_id,
                        lineage.snapshot_version,
                        lineage.snapshot_digest,
                        formula_id,
                        formula_version(formula_id),
                        objective,
                        item["definition"],
                        _json(item["evidence_fact_ids"]),
                        _json(provider_receipt),
                        _now(),
                    ),
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def generate_angle_options(product_id: str, formula_id: str, objective: str = "conversion") -> dict[str, Any]:
    canonical_formula, formula_contract = _require_formula(formula_id)
    product, snapshot = await _product_truth_rows(product_id)
    blockers = _truth_gate(product, snapshot)
    if blockers:
        raise CopyRegisterV2Error(blockers[0], "Current approved Product Truth is required before angle generation.", status_code=409, details={"blockers": blockers})
    assert product is not None and snapshot is not None
    facts = _fact_candidates(product, snapshot)
    await _ensure_evidence_facts(facts)
    raw, provider_receipt = _call_text_assist(
        system_prompt=_ANGLE_SYSTEM_PROMPT,
        prompt_version=ANGLE_PROMPT_VERSION,
        payload={
            "product": {
                "display_name": _clean(
                    product.get("product_display_name") or product.get("raw_product_title")
                ),
                "category": _clean(product.get("category")),
                "subcategory": _clean(product.get("subcategory")),
                "product_type": _clean(product.get("type") or product.get("product_type")),
                "product_family": _clean(product.get("bosmax_product_family")),
            },
            "product_truth": {
                "persona": _parse_dict(snapshot.get("buyer_persona_snapshot_json")),
                "allowed_claims": _parse_list(snapshot.get("allowed_claims_json")),
                "blocked_claims": _parse_list(snapshot.get("blocked_claims_json")),
                "warnings": _parse_list(snapshot.get("warnings_text")),
                "approved_angle_signals": _angle_signals(snapshot, facts),
            },
            "formula": {
                "formula_id": canonical_formula,
                "formula_version": formula_version(canonical_formula),
                "required_stage_keys": list(required_formula_stage_keys(canonical_formula)),
                "contract": formula_contract,
            },
            "objective": objective,
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "fact_kind": fact.fact_kind,
                    "text": fact.text,
                }
                for fact in facts
            ],
        },
    )
    options = _validate_ai_angle_options(
        raw,
        product=product,
        snapshot=snapshot,
        facts=facts,
    )
    await _persist_angle_options(
        options,
        product=product,
        snapshot=snapshot,
        formula_id=canonical_formula,
        objective=objective,
        provider_receipt=provider_receipt,
    )
    return {
        "product_id": product_id,
        "formula_id": canonical_formula,
        "formula_version": formula_version(canonical_formula),
        "objective": objective,
        "angles": options,
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "provider_calls": 1,
        "provider_receipt": provider_receipt,
        "prompt_version": ANGLE_PROMPT_VERSION,
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


async def _require_angle_candidate(
    *,
    product: dict[str, Any],
    snapshot: dict[str, Any],
    formula_id: str,
    objective_id: str,
    angle_id: str,
    angle_definition: str,
    selected_fact_ids: Iterable[str],
) -> dict[str, Any]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM copy_angle_candidate_v2 WHERE angle_id=?",
        (_clean(angle_id),),
    )
    row = await cursor.fetchone()
    if row is None:
        raise CopyRegisterV2Error(
            "COPY_V2_ANGLE_NOT_GROUNDED",
            "Select an angle generated by the current V2 Product Truth workflow.",
            status_code=422,
        )
    candidate = dict(row)
    lineage = _lineage(product, snapshot)
    expected = {
        "product_id": str(product["id"]),
        "product_truth_snapshot_id": lineage.snapshot_id,
        "product_truth_snapshot_version": lineage.snapshot_version,
        "product_truth_snapshot_digest": lineage.snapshot_digest,
        "formula_id": formula_id,
        "formula_version": formula_version(formula_id),
    }
    mismatches = {
        key: {"expected": value, "actual": candidate.get(key)}
        for key, value in expected.items()
        if candidate.get(key) != value
    }
    if mismatches:
        raise CopyRegisterV2Error(
            "COPY_V2_ANGLE_STALE",
            "The selected angle does not match current Product Truth and formula authority.",
            status_code=409,
            details=mismatches,
        )
    if _clean(candidate.get("definition")) != _clean(angle_definition):
        raise CopyRegisterV2Error(
            "COPY_V2_ANGLE_TAMPERED",
            "The selected angle wording differs from its immutable generation receipt.",
            status_code=409,
        )
    if _clean(candidate.get("objective")).casefold() != _clean(objective_id).casefold():
        raise CopyRegisterV2Error(
            "COPY_V2_ANGLE_OBJECTIVE_MISMATCH",
            "The selected angle belongs to a different objective.",
            status_code=409,
        )
    angle_fact_ids = {
        str(value) for value in _loads(candidate.get("evidence_fact_ids_json"), [])
    }
    if not angle_fact_ids or not angle_fact_ids.issubset(set(selected_fact_ids)):
        raise CopyRegisterV2Error(
            "COPY_V2_ANGLE_EVIDENCE_REQUIRED",
            "Keep the angle's cited Product Truth facts in the blueprint evidence selection.",
            status_code=422,
            details={"required_fact_ids": sorted(angle_fact_ids)},
        )
    candidate["evidence_fact_ids"] = sorted(angle_fact_ids)
    candidate["provider_receipt"] = _loads(candidate.get("provider_receipt_json"), {})
    return candidate


def _validate_ai_formula_stages(
    raw: dict[str, Any],
    *,
    product: dict[str, Any],
    snapshot: dict[str, Any],
    formula_id: str,
    facts: tuple[EvidenceFact, ...],
) -> list[dict[str, Any]]:
    items = raw.get("stages")
    expected_slots = list(required_formula_stage_keys(formula_id))
    if not isinstance(items, list) or len(items) != len(expected_slots):
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_FORMULA_INCOMPLETE",
            "The text-assist response did not return every required formula stage.",
            status_code=502,
            details={"expected_stage_keys": expected_slots},
        )
    fact_index = {fact.fact_id: fact for fact in facts}
    validated: list[dict[str, Any]] = []
    for index, (item, expected_slot) in enumerate(zip(items, expected_slots, strict=True)):
        if not isinstance(item, dict) or _clean(item.get("formula_stage_key")) != expected_slot:
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_FORMULA_ORDER_INVALID",
                "The text-assist response changed the registered formula stage order.",
                status_code=502,
                details={"order": index, "expected_stage_key": expected_slot},
            )
        raw_ids = item.get("evidence_fact_ids")
        if not isinstance(raw_ids, list):
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
                "Every generated stage must carry an evidence list.",
                status_code=502,
            )
        ids = [str(value) for value in raw_ids]
        if len(ids) > 5 or len(ids) != len(set(ids)):
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
                "Generated stage evidence must contain at most five unique facts.",
                status_code=502,
            )
        claim_bearing = expected_slot not in {"cta", "action", "response"}
        if claim_bearing and not ids:
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
                "Every claim-bearing formula stage must cite approved evidence.",
                status_code=502,
            )
        try:
            cited = tuple(fact_index[fact_id] for fact_id in ids)
        except KeyError as exc:
            raise CopyRegisterV2Error(
                "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
                "Generated formula copy cited evidence outside the selected facts.",
                status_code=502,
                details={"fact_id": str(exc.args[0])},
            ) from exc
        text = _assert_generated_text_grounded(
            item.get("text"),
            facts=cited,
            product=product,
            internal_ids=(
                str(product["id"]),
                str(snapshot["snapshot_id"]),
                *fact_index,
            ),
        )
        validated.append(
            {
                "formula_stage_key": expected_slot,
                "text": text,
                "evidence_fact_ids": ids,
            }
        )
    return validated


def _generate_formula_stage_payloads(
    *,
    product: dict[str, Any],
    snapshot: dict[str, Any],
    formula_id: str,
    objective: Objective,
    angle: Angle,
    facts: tuple[EvidenceFact, ...],
    target_duration_seconds: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw, receipt = _call_text_assist(
        system_prompt=_FORMULA_SYSTEM_PROMPT,
        prompt_version=FORMULA_PROMPT_VERSION,
        payload={
            "product": {
                "display_name": _clean(
                    product.get("product_display_name") or product.get("raw_product_title")
                ),
                "category": _clean(product.get("category")),
                "subcategory": _clean(product.get("subcategory")),
                "product_type": _clean(product.get("type") or product.get("product_type")),
            },
            "product_truth": {
                "persona": _parse_dict(snapshot.get("buyer_persona_snapshot_json")),
                "allowed_claims": _parse_list(snapshot.get("allowed_claims_json")),
                "blocked_claims": _parse_list(snapshot.get("blocked_claims_json")),
                "warnings": _parse_list(snapshot.get("warnings_text")),
            },
            "formula": {
                "formula_id": formula_id,
                "formula_version": formula_version(formula_id),
                "ordered_stage_keys": list(required_formula_stage_keys(formula_id)),
                "contract": strict_formula_contract(formula_id),
            },
            "objective": objective.model_dump(mode="json"),
            "selected_angle": angle.model_dump(mode="json"),
            "target_duration_seconds": target_duration_seconds,
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "fact_kind": fact.fact_kind,
                    "text": fact.text,
                }
                for fact in facts
            ],
        },
    )
    return (
        _validate_ai_formula_stages(
            raw,
            product=product,
            snapshot=snapshot,
            formula_id=formula_id,
            facts=facts,
        ),
        receipt,
    )


def _build_stages(
    formula_id: str,
    *,
    blueprint_id: str,
    revision: int,
    facts: tuple[EvidenceFact, ...],
    generated_stages: list[dict[str, Any]],
) -> tuple[FormulaStage, ...]:
    slots = required_formula_stage_keys(formula_id)
    if len(generated_stages) != len(slots):
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_FORMULA_INCOMPLETE",
            "Generated formula stages do not match the registered formula.",
            status_code=502,
        )
    fact_index = {fact.fact_id: fact for fact in facts}
    stages: list[FormulaStage] = []
    previous_exit = f"{formula_id}:OPEN"
    for index, (slot, generated) in enumerate(zip(slots, generated_stages, strict=True)):
        stage_key = f"stage-{index}-{slot}"
        exit_token = f"{formula_id}:STAGE:{index}"
        claim_bearing = slot not in {"cta", "action", "response"}
        refs = tuple(
            fact_index[fact_id].reference()
            for fact_id in generated["evidence_fact_ids"]
        )
        stages.append(
            FormulaStage(
                stage_key=stage_key,
                order=index,
                authored_text=generated["text"],
                semantic_role=slot,
                component_ref=f"v2-component:{blueprint_id}:r{revision}:{stage_key}",
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


def _new_blueprint(
    *,
    product: dict[str, Any],
    snapshot: dict[str, Any],
    formula_id: str,
    objective: Objective,
    angle: Angle,
    facts: tuple[EvidenceFact, ...],
    generated_stages: list[dict[str, Any]],
    provider_receipt: dict[str, Any],
    angle_provider_receipt: dict[str, Any],
    target_duration_seconds: float | None = None,
) -> CopyBlueprintV2:
    blueprint_id = f"bpv2_{uuid.uuid4().hex[:20]}"
    stages = _build_stages(
        formula_id,
        blueprint_id=blueprint_id,
        revision=1,
        facts=facts,
        generated_stages=generated_stages,
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
        wps_profile="COPY_REGISTER_V2_TEXT_ASSIST",
        estimated_word_count=sum(len(stage.authored_text.split()) for stage in stages),
        semantic_review=None,
        provenance=(
            ProvenanceEntry(key="source", value="COPY_REGISTER_V2"),
            ProvenanceEntry(key="formula_authority", value="copy-formula-registry-v1"),
            ProvenanceEntry(key="generator", value="text-assist-formula-native-v2"),
            ProvenanceEntry(key="formula_prompt_version", value=FORMULA_PROMPT_VERSION),
            ProvenanceEntry(key="formula_provider_receipt", value=_json(provider_receipt)),
            ProvenanceEntry(key="angle_provider_receipt", value=_json(angle_provider_receipt)),
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
    selected = await _require_angle_candidate(
        product=product,
        snapshot=snapshot,
        formula_id=canonical_formula,
        objective_id=objective_id,
        angle_id=angle_id,
        angle_definition=angle_definition,
        selected_fact_ids=evidence_fact_ids,
    )
    objective = Objective(
        objective_id=_clean(objective_id),
        definition=_clean(objective_definition),
    )
    angle = Angle(angle_id=_clean(angle_id), definition=_clean(angle_definition))
    generated_stages, provider_receipt = _generate_formula_stage_payloads(
        product=product,
        snapshot=snapshot,
        formula_id=canonical_formula,
        objective=objective,
        angle=angle,
        facts=facts,
        target_duration_seconds=target_duration_seconds,
    )
    blueprint = _new_blueprint(
        product=product,
        snapshot=snapshot,
        formula_id=canonical_formula,
        objective=objective,
        angle=angle,
        facts=facts,
        generated_stages=generated_stages,
        provider_receipt=provider_receipt,
        angle_provider_receipt=selected["provider_receipt"],
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


def get_text_assist_provider_status() -> dict[str, Any]:
    """Return the existing text-assist lane state without provider secrets."""

    adapter_status = ai_provider.provider_status()
    registry_status: dict[str, Any] = {}
    try:
        registry_status = next(
            (
                item
                for item in summarize_provider_settings().get("lanes", [])
                if item.get("lane") == "text_assist"
            ),
            {},
        )
    except Exception:  # noqa: BLE001 - status reads must fail closed
        registry_status = {}

    configured = bool(adapter_status.get("configured"))
    return {
        "lane": "text_assist",
        "status": (
            "READY"
            if configured
            else str(registry_status.get("status") or "NOT_CONFIGURED")
        ),
        "configured": configured,
        "provider_id": (
            adapter_status.get("provider_id") or registry_status.get("provider_id")
        ),
        "model_id": adapter_status.get("model_id") or registry_status.get("model_id"),
        "execution_enabled": bool(adapter_status.get("execution_enabled")),
        "provider_calls": 0,
    }


async def get_activation_status(product_id: str) -> dict[str, Any]:
    """Hydrate the all-required-lane activation state after a page reload."""

    required_lanes = tuple(
        item["lane_id"]
        for item in producer_consumer_matrix()
        if item["copy_policy"] == "REQUIRED"
    )
    placeholders = ",".join("?" for _ in required_lanes)
    db = await get_db()
    cursor = await db.execute(
        f"""
        SELECT binding.blueprint_id, binding.revision,
               COUNT(DISTINCT authority.lane) AS active_lane_count,
               MAX(authority.activated_at) AS activated_at
        FROM copy_execution_authority_v2 authority
        JOIN copy_execution_binding_v2 binding
          ON binding.binding_id = authority.binding_id
         AND binding.product_id = authority.product_id
         AND binding.lane = authority.lane
        JOIN copy_blueprint_v2 blueprint
          ON blueprint.blueprint_id = binding.blueprint_id
         AND blueprint.revision = binding.revision
        WHERE authority.product_id = ?
          AND authority.lane IN ({placeholders})
          AND binding.binding_status = 'BOUND'
          AND blueprint.status = 'PRODUCTION_VALID'
        GROUP BY binding.blueprint_id, binding.revision
        HAVING COUNT(DISTINCT authority.lane) = ?
        ORDER BY activated_at DESC
        LIMIT 1
        """,
        (product_id, *required_lanes, len(required_lanes)),
    )
    row = await cursor.fetchone()
    return {
        "active_blueprint_id": row["blueprint_id"] if row else None,
        "active_revision": int(row["revision"]) if row else None,
        "active_lane_count": int(row["active_lane_count"]) if row else 0,
        "required_lane_count": len(required_lanes),
        "activated_at": row["activated_at"] if row else None,
    }


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
    target = matching[0]
    raw, provider_receipt = _call_text_assist(
        system_prompt=_STAGE_REGEN_SYSTEM_PROMPT,
        prompt_version=STAGE_REGEN_PROMPT_VERSION,
        payload={
            "product": {
                "display_name": _clean(
                    product.get("product_display_name") or product.get("raw_product_title")
                ),
                "category": _clean(product.get("category")),
                "subcategory": _clean(product.get("subcategory")),
                "product_type": _clean(product.get("type") or product.get("product_type")),
            },
            "product_truth": {
                "allowed_claims": _parse_list(snapshot.get("allowed_claims_json")),
                "blocked_claims": _parse_list(snapshot.get("blocked_claims_json")),
                "warnings": _parse_list(snapshot.get("warnings_text")),
            },
            "formula_id": previous.formula_id,
            "formula_version": previous.formula_version,
            "ordered_stage_keys": [stage.formula_stage_key for stage in previous.stages],
            "selected_angle": previous.angle.model_dump(mode="json"),
            "objective": previous.objective.model_dump(mode="json"),
            "target_stage": {
                "stage_key": target.stage_key,
                "formula_stage_key": target.formula_stage_key,
                "current_text": target.authored_text,
                "claim_bearing": target.claim_bearing,
            },
            "surrounding_stages": [
                {
                    "formula_stage_key": stage.formula_stage_key,
                    "text": stage.authored_text,
                }
                for stage in previous.stages
                if stage.stage_key != target.stage_key
            ],
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "fact_kind": fact.fact_kind,
                    "text": fact.text,
                }
                for fact in facts
            ],
        },
    )
    generated = raw.get("stage")
    if (
        not isinstance(generated, dict)
        or _clean(generated.get("formula_stage_key")) != target.formula_stage_key
        or not isinstance(generated.get("evidence_fact_ids"), list)
    ):
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_STAGE_REGEN_INVALID",
            "Stage regeneration changed the stage role or returned an invalid contract.",
            status_code=502,
        )
    fact_index = {fact.fact_id: fact for fact in facts}
    fact_ids = [str(value) for value in generated["evidence_fact_ids"]]
    if len(fact_ids) > 5 or len(fact_ids) != len(set(fact_ids)):
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
            "Regenerated stage evidence must contain at most five unique facts.",
            status_code=502,
        )
    if target.claim_bearing and not fact_ids:
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
            "A claim-bearing regenerated stage must cite approved evidence.",
            status_code=502,
        )
    try:
        cited = tuple(fact_index[fact_id] for fact_id in fact_ids)
    except KeyError as exc:
        raise CopyRegisterV2Error(
            "COPY_V2_TEXT_AI_EVIDENCE_INVALID",
            "Regenerated stage cited evidence outside the blueprint selection.",
            status_code=502,
            details={"fact_id": str(exc.args[0])},
        ) from exc
    new_text = _assert_generated_text_grounded(
        generated.get("text"),
        facts=cited,
        product=product,
        internal_ids=(str(product["id"]), str(snapshot["snapshot_id"]), *fact_index),
    )
    next_revision = previous.revision + 1
    stages = tuple(
        stage.model_copy(
            update={
                "authored_text": new_text,
                "component_ref": (
                    f"v2-component:{previous.blueprint_id}:r{next_revision}:{stage.stage_key}"
                ),
                "fact_refs": tuple(fact.reference() for fact in cited),
                "validation": StageValidation(valid=True),
            }
        )
        if stage.stage_key == stage_key
        else stage
        for stage in previous.stages
    )
    revision = create_blueprint_revision(
        previous,
        stages=stages,
        evidence_refs=previous.evidence_refs,
        product_truth_lineage=_lineage(product, snapshot),
        created_at=_now(),
    ).model_copy(
        update={
            "component_refs": tuple(
                stage.component_ref for stage in stages if stage.component_ref
            ),
            "estimated_word_count": sum(
                len(stage.authored_text.split()) for stage in stages
            ),
            "provenance": (
                *previous.provenance,
                ProvenanceEntry(
                    key=f"stage_regeneration_r{next_revision}",
                    value=_json(provider_receipt),
                ),
            ),
            "semantic_review": None,
        }
    )
    validation = validate_copy_blueprint_v2(
        revision,
        current_product_truth=_lineage(product, snapshot),
        evidence_registry=EvidenceRegistry(facts=facts),
    )
    if not validation.valid:
        raise CopyRegisterV2Error(
            "COPY_V2_BLUEPRINT_INVALID",
            "Regenerated formula revision failed the V2 validation gate.",
            details=validation.model_dump(mode="json"),
        )
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


async def _prepare_binding(
    *,
    blueprint_id: str,
    lane: str,
    feature_flags: CopyBlueprintV2FeatureFlagState,
) -> tuple[CopyBlueprintV2, CopyExecutionBinding]:
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
    return blueprint, binding


async def _insert_or_get_binding(db: Any, blueprint: CopyBlueprintV2,
                                 binding: CopyExecutionBinding) -> CopyExecutionBinding:
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
    return binding


async def _set_binding_authority(
    db: Any,
    blueprint: CopyBlueprintV2,
    binding: CopyExecutionBinding,
) -> None:
    """Select an immutable binding receipt without rewriting the receipt."""

    await db.execute(
        """
        INSERT INTO copy_execution_authority_v2
            (product_id, lane, binding_id, activated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(product_id, lane) DO UPDATE SET
            binding_id=excluded.binding_id,
            activated_at=excluded.activated_at
        """,
        (blueprint.product_id, binding.lane, binding.binding_id, _now()),
    )


async def bind_blueprint(*, blueprint_id: str, lane: str,
                         feature_flags: CopyBlueprintV2FeatureFlagState) -> CopyExecutionBinding:
    blueprint, binding = await _prepare_binding(
        blueprint_id=blueprint_id,
        lane=lane,
        feature_flags=feature_flags,
    )
    db = await get_db()
    async with _db_lock:
        try:
            persisted = await _insert_or_get_binding(db, blueprint, binding)
            await _set_binding_authority(db, blueprint, persisted)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return persisted


async def activate_blueprint_for_required_lanes(blueprint_id: str) -> tuple[CopyExecutionBinding, ...]:
    """Atomically make one approved blueprint authoritative for all copy lanes."""

    feature_flags = CopyBlueprintV2FeatureFlagState.from_environment()
    if not feature_flags.enabled or feature_flags.state != "ON":
        raise CopyRegisterV2Error(
            "COPY_V2_ONLY_REQUIRED",
            "All-lane activation requires the canonical V2-only runtime state.",
        )
    prepared: list[tuple[CopyBlueprintV2, CopyExecutionBinding]] = []
    for item in producer_consumer_matrix():
        if item["copy_policy"] != "REQUIRED":
            continue
        prepared.append(
            await _prepare_binding(
                blueprint_id=blueprint_id,
                lane=item["lane_id"],
                feature_flags=feature_flags,
            )
        )

    db = await get_db()
    persisted: list[CopyExecutionBinding] = []
    async with _db_lock:
        try:
            for blueprint, binding in prepared:
                receipt = await _insert_or_get_binding(db, blueprint, binding)
                await _set_binding_authority(db, blueprint, receipt)
                persisted.append(receipt)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return tuple(persisted)


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



async def get_binding_by_id(binding_id: str) -> CopyExecutionBinding:
    """Load a persisted V2 binding by immutable binding_id."""
    bid = str(binding_id or "").strip()
    if not bid:
        raise CopyRegisterV2Error(
            "COPY_V2_BINDING_ID_REQUIRED",
            "copy_execution_binding_id_v2 is required.",
            status_code=422,
        )
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT binding.*
        FROM copy_execution_binding_v2 binding
        JOIN copy_execution_authority_v2 authority
          ON authority.binding_id = binding.binding_id
         AND authority.product_id = binding.product_id
         AND authority.lane = binding.lane
        WHERE binding.binding_id=?
          AND binding.binding_status='BOUND'
        LIMIT 1
        """,
        (bid,),
    )
    row = await cursor.fetchone()
    if not row:
        raise CopyRegisterV2Error(
            "COPY_V2_BINDING_NOT_FOUND",
            "No active V2 binding exists for this binding_id.",
            status_code=404,
        )
    return _row_to_binding(row)


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
        SELECT binding.*
        FROM copy_execution_authority_v2 authority
        JOIN copy_execution_binding_v2 binding
          ON binding.binding_id = authority.binding_id
        WHERE authority.product_id=? AND authority.lane=?
          AND binding.product_id=authority.product_id
          AND binding.lane=authority.lane
          AND binding.binding_status='BOUND'
        LIMIT 1
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
    "activate_blueprint_for_required_lanes",
    "approve_blueprint",
    "bind_blueprint",
    "generate_angle_options",
    "generate_blueprint",
    "get_activation_status",
    "get_blueprint",
    "get_binding",
    "get_binding_by_id",
    "get_product_truth_proof",
    "get_text_assist_provider_status",
    "list_binding_matrix",
    "list_blueprints",
    "list_formulas",
    "regenerate_stage",
]
