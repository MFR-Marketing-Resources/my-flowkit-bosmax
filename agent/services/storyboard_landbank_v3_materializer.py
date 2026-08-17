"""Deterministic, provider-free V3 -> V2 materializer (Macro Round 3, P1/P2).

Takes ONE approved V3 duration projection plus its valid V3 human approval
receipt and produces exactly ONE V2 ``CopyBlueprintV2`` revision that reaches
``PRODUCTION_VALID`` through the EXISTING V2 approval gate.  It never generates
or rewrites copy, never calls a provider, and never auto-approves: the human
semantic approval is the V3 receipt, carried forward with machine revalidation.

Determinism / idempotency: the V2 blueprint id derives from the exact approved
projection identity + the materializer version, so re-materializing the same
approved projection resolves to the same blueprint (no duplicate authority row).

Authority model (unchanged): V3 = supply + human approval provenance; V2 =
production authority.  This module is the deterministic bridge and adds no
parallel authority.  P2 layers the immutable ``materialization_link_v3`` record
and the idempotent link/transaction semantics on top of ``materialize_projection``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.authority.copy_blueprint_v2_authority import (
    formula_version as v2_formula_version,
    is_production_formula,
    required_formula_stage_keys,
)
from agent.models.copy_blueprint_v2 import (
    Angle,
    BridgeContract,
    CopyBlueprintV2,
    EvidenceReference,
    FormulaStage,
    Objective,
    ProductionReadinessProof,
    ProvenanceEntry,
    SemanticReviewProof,
)
from agent.models.storyboard_landbank_v3 import deterministic_id, normalized_text
from agent.models.storyboard_landbank_v3_round3 import (
    MATERIALIZER_VERSION,
    MaterializationLinkV3,
    materialization_digest,
    materialization_link_id,
)
from agent.services import copy_register_v2_service as v2svc
from agent.services import production_supply_repository as supply_repo
from agent.services.storyboard_landbank_v3_factory import V3CopyFactoryService
from agent.services.storyboard_landbank_v3_round2 import V3CopyRegisterRound2Service

APPROVAL_SOURCE = "V3_HUMAN_APPROVAL_CARRY_FORWARD"
_TERMINAL_V3 = "APPROVED"


class MaterializationError(Exception):
    """Fail-closed materialization error (HTTP 409 by default)."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.details = details or {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def deterministic_blueprint_id(
    *,
    product_id: str,
    projection_id: str,
    projection_revision: int,
    projection_exact_digest: str,
    materializer_version: str = MATERIALIZER_VERSION,
) -> str:
    """Idempotent V2 blueprint id for one approved projection materialization."""

    return deterministic_id(
        "bpv2",
        {
            "materializer_version": materializer_version,
            "product_id": product_id,
            "projection_id": projection_id,
            "projection_revision": int(projection_revision),
            "projection_exact_digest": projection_exact_digest,
        },
    )


def _all_projection_fingerprints(receipt: Any) -> set[str]:
    fingerprints = set(getattr(receipt, "projection_fingerprints", ()) or ())
    for item in getattr(receipt, "batch_target_items", ()) or ():
        for fingerprint in getattr(item, "projection_fingerprints", ()) or ():
            fingerprints.add(fingerprint)
    return fingerprints


class V3ToV2Materializer:
    def __init__(self, *, v3: V3CopyRegisterRound2Service | None = None) -> None:
        self._v3 = v3 or V3CopyRegisterRound2Service(factory=V3CopyFactoryService())

    # ----------------------------------------------------------------- load
    async def _load_receipt(self, receipt_id: str):
        from agent.db.schema import get_db

        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM v3_human_approval_receipt WHERE receipt_id = ?",
            (receipt_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise MaterializationError(
                "MATERIALIZATION_RECEIPT_NOT_FOUND",
                f"V3 human approval receipt not found: {receipt_id}",
                status_code=404,
            )
        return self._v3._receipt_from_row(dict(row))

    async def _latest_approved_revision(
        self, table: str, id_column: str, entity_id: str
    ) -> int | None:
        from agent.db.schema import get_db

        db = await get_db()
        cursor = await db.execute(
            f"SELECT MAX(revision) FROM {table} WHERE {id_column} = ? AND status = 'APPROVED'",
            (entity_id,),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else None

    # ------------------------------------------------------------ materialize
    async def materialize_projection(
        self,
        *,
        projection_id: str,
        receipt_id: str,
        projection_revision: int | None = None,
        actor_id: str = "v3-to-v2-materializer",
        source: str = "v3-round3-materializer",
    ) -> dict[str, Any]:
        repo = self._v3.factory.repository

        # The receipt is the authority on what was approved.  Human approval
        # inserts NEW APPROVED master/projection revisions, so resolve the exact
        # APPROVED revision by id (never a pre-approval or newer draft revision).
        receipt = await self._load_receipt(receipt_id)

        master_id = receipt.master_ref.entity_id
        master_revision = await self._latest_approved_revision(
            "master_storyboard_v3", "master_id", master_id
        )
        if master_revision is None:
            raise MaterializationError(
                "MATERIALIZATION_TARGET_NOT_APPROVED",
                f"No APPROVED V3 master revision for {master_id}.",
            )
        master = await repo.get("MASTER_STORYBOARD", master_id, master_revision)

        if projection_revision is None:
            projection_revision = await self._latest_approved_revision(
                "duration_projection_v3", "projection_id", projection_id
            )
        if projection_revision is None:
            raise MaterializationError(
                "MATERIALIZATION_TARGET_NOT_APPROVED",
                f"No APPROVED V3 duration projection revision for {projection_id}.",
            )
        projection = await repo.get(
            "DURATION_PROJECTION", projection_id, projection_revision
        )
        if projection is None or master is None:
            raise MaterializationError(
                "MATERIALIZATION_TARGET_NOT_FOUND",
                "APPROVED V3 master or projection could not be loaded.",
                status_code=404,
            )
        if projection.master.entity_id != master.master_id:
            raise MaterializationError(
                "MATERIALIZATION_SCOPE_MISMATCH",
                "Projection does not belong to the receipt's approved master.",
                details={
                    "projection_master": projection.master.entity_id,
                    "receipt_master": master.master_id,
                },
            )
        if master.status != _TERMINAL_V3 or projection.status != _TERMINAL_V3:
            raise MaterializationError(
                "MATERIALIZATION_TARGET_NOT_APPROVED",
                "Only an APPROVED V3 master + projection can be materialized.",
                details={
                    "master_status": master.status,
                    "projection_status": projection.status,
                },
            )

        # The receipt's internal cryptographic seal must be intact.
        verdict = await self._v3.verify_receipt(receipt_id)
        if not verdict.get("valid"):
            raise MaterializationError(
                "MATERIALIZATION_RECEIPT_INVALID",
                "V3 human approval receipt failed verification.",
                details={"failures": verdict.get("failures", [])},
            )
        if bool(getattr(receipt, "automatic_approval", False)):
            raise MaterializationError(
                "MATERIALIZATION_RECEIPT_INVALID",
                "Receipt is not a genuine human approval (automatic_approval set).",
            )

        # (3) The receipt must cryptographically bind THIS master + projection.
        if receipt.exact_content_fingerprint != master.exact_content_digest:
            raise MaterializationError(
                "MATERIALIZATION_FINGERPRINT_MISMATCH",
                "Receipt master fingerprint does not match the current master.",
                details={
                    "receipt": receipt.exact_content_fingerprint,
                    "master": master.exact_content_digest,
                },
            )
        if projection.exact_projection_digest not in _all_projection_fingerprints(receipt):
            raise MaterializationError(
                "MATERIALIZATION_SCOPE_MISMATCH",
                "Projection is not covered by the approval receipt scope.",
                details={"projection_digest": projection.exact_projection_digest},
            )

        # (4) Formula identity + production eligibility.
        if (
            master.formula.formula_id != receipt.formula_id
            or master.formula.formula_version != receipt.formula_version
        ):
            raise MaterializationError(
                "MATERIALIZATION_FORMULA_MISMATCH",
                "Master formula differs from the approved receipt formula.",
            )
        formula_id = master.formula.formula_id
        if not is_production_formula(formula_id):
            raise MaterializationError(
                "MATERIALIZATION_FORMULA_INELIGIBLE",
                f"Formula {formula_id} is not a production-supported formula.",
                status_code=422,
            )
        if master.formula.formula_version != v2_formula_version(formula_id):
            raise MaterializationError(
                "MATERIALIZATION_FORMULA_MISMATCH",
                "Approved formula version differs from the current V2 authority version.",
                details={
                    "approved": master.formula.formula_version,
                    "current": v2_formula_version(formula_id),
                },
            )

        # (5) Evidence + WPS digests bound to the receipt must match the source.
        if master.evidence_digest != receipt.evidence_digest:
            raise MaterializationError(
                "MATERIALIZATION_EVIDENCE_MISMATCH",
                "Master evidence digest differs from the approved receipt.",
            )
        if projection.wps_authority_digest not in set(receipt.wps_authority_digests or ()):
            raise MaterializationError(
                "MATERIALIZATION_WPS_MISMATCH",
                "Projection WPS authority digest is not covered by the receipt.",
            )

        # (6) CURRENT Product Truth must equal what the human approved against.
        product, snapshot = await v2svc._product_truth_rows(master.product_id)
        blockers = v2svc._truth_gate(product, snapshot)
        if blockers:
            raise MaterializationError(
                "MATERIALIZATION_TRUTH_STALE",
                "Current Product Truth is stale, incomplete, or unavailable.",
                details={"blockers": blockers},
            )
        assert product is not None and snapshot is not None
        current_truth_digest = v2svc._truth_digest(snapshot)
        if (
            int(snapshot["version"]) != receipt.product_truth_snapshot_version
            or current_truth_digest != receipt.product_truth_snapshot_digest
        ):
            raise MaterializationError(
                "MATERIALIZATION_TRUTH_STALE",
                "Product Truth advanced since human approval; re-approve in V3.",
                details={
                    "current_version": int(snapshot["version"]),
                    "approved_version": receipt.product_truth_snapshot_version,
                },
            )

        # (7) Build V2 stages from the EXACT human-approved projected slices.
        stages, evidence_refs = self._build_stages(
            master=master,
            projection=projection,
            formula_id=formula_id,
            product=product,
            snapshot=snapshot,
        )

        blueprint_id = deterministic_blueprint_id(
            product_id=master.product_id,
            projection_id=projection.projection_id,
            projection_revision=projection.revision,
            projection_exact_digest=projection.exact_projection_digest,
        )

        # Idempotency: a prior successful materialization is returned as-is, but
        # the link is still ensured (repairs a blueprint-approved / link-missing
        # partial failure without re-approving).
        existing = await self._existing_blueprint(blueprint_id)
        if existing is not None and existing.status == "PRODUCTION_VALID":
            link = await self._ensure_link(
                blueprint=existing,
                master=master,
                projection=projection,
                receipt=receipt,
                snapshot=snapshot,
                actor_id=actor_id,
                source=source,
            )
            return self._result(
                blueprint=existing,
                master=master,
                projection=projection,
                receipt=receipt,
                snapshot=snapshot,
                link=link,
                idempotent_reuse=True,
            )

        objective = Objective(
            objective_id=master.objective.objective_id,
            definition=normalized_text(master.objective.definition)
            or f"Formula-native production objective {master.objective.objective_id}.",
        )
        angle = await self._build_angle(master)
        lineage = v2svc._lineage(product, snapshot)
        provenance = self._provenance(master=master, projection=projection, receipt=receipt)

        draft = CopyBlueprintV2(
            blueprint_id=blueprint_id,
            product_id=master.product_id,
            revision=1,
            status="DRAFT",
            formula_id=formula_id,
            formula_version=master.formula.formula_version,
            objective=objective,
            angle=angle,
            stages=stages,
            evidence_refs=evidence_refs,
            target_duration_seconds=float(projection.target_duration_seconds),
            estimated_word_count=sum(
                len(stage.authored_text.split()) for stage in stages
            ),
            provenance=provenance,
            product_truth_lineage=lineage,
            created_at=_now(),
        )

        if existing is None:
            await v2svc._insert_blueprint(draft)

        # Carry the genuine human semantic approval forward; machine revalidation
        # (above + the V2 gate) is the ONLY thing that has run in addition.
        semantic_review = SemanticReviewProof(
            decision="APPROVED",
            reviewer=receipt.approved_by,
            rationale=(
                f"Carried forward from V3 human approval receipt {receipt.receipt_id} "
                f"(digest {receipt.receipt_digest[:16]}). Human rationale: "
                f"{normalized_text(receipt.rationale)}"
            ),
            reviewed_at=receipt.created_at,
        )
        readiness_proof = ProductionReadinessProof(
            readiness_validated=True,
            provenance_validated=True,
            safety_validated=True,
            bridge_validated=True,
            duration_validated=True,
        )
        try:
            approved = await v2svc.approve_blueprint(
                blueprint_id,
                approved_by=receipt.approved_by,
                semantic_review=semantic_review,
                readiness_proof=readiness_proof,
            )
        except v2svc.CopyRegisterV2Error as exc:
            # The existing V2 gate rejected the materialization: fail closed and
            # preserve the exact V2 authority reason.
            raise MaterializationError(
                getattr(exc, "code", "COPY_V2_BLUEPRINT_INVALID"),
                str(exc),
                status_code=getattr(exc, "status_code", 409),
                details=getattr(exc, "details", {}) or {},
            ) from exc

        link = await self._ensure_link(
            blueprint=approved,
            master=master,
            projection=projection,
            receipt=receipt,
            snapshot=snapshot,
            actor_id=actor_id,
            source=source,
        )
        return self._result(
            blueprint=approved,
            master=master,
            projection=projection,
            receipt=receipt,
            snapshot=snapshot,
            link=link,
            idempotent_reuse=False,
        )

    # --------------------------------------------------------------- helpers
    async def _existing_blueprint(self, blueprint_id: str):
        try:
            return await v2svc.get_blueprint(blueprint_id)
        except v2svc.CopyRegisterV2Error:
            return None

    async def _build_angle(self, master) -> Angle:
        definition = None
        try:
            angle_entity = await self._v3.factory.repository.get(
                "ANGLE", master.angle.entity_id, master.angle.revision
            )
            definition = normalized_text(getattr(angle_entity, "definition", "") or "")
        except Exception:  # noqa: BLE001 - angle definition is descriptive only
            definition = ""
        return Angle(
            angle_id=master.angle.entity_id,
            definition=definition or f"Formula-native angle {master.angle.entity_id}.",
        )

    def _build_stages(
        self, *, master, projection, formula_id, product, snapshot
    ) -> tuple[tuple[FormulaStage, ...], tuple[EvidenceReference, ...]]:
        required = required_formula_stage_keys(formula_id)
        master_stage_by_formula_key = {
            stage.formula_stage_key: stage for stage in master.stages
        }
        candidates = {fact.fact_id: fact for fact in v2svc._fact_candidates(product, snapshot)}

        present = [
            slice_
            for slice_ in projection.stage_allocations
            if getattr(slice_, "omission_state", "PRESENT") != "OMITTED"
        ]
        present.sort(key=lambda s: s.order)

        needed_fact_ids: list[str] = []
        for slice_ in present:
            for fact_id in slice_.source_evidence_fact_ids:
                if fact_id not in needed_fact_ids:
                    needed_fact_ids.append(fact_id)
        missing = [fid for fid in needed_fact_ids if fid not in candidates]
        if missing:
            raise MaterializationError(
                "MATERIALIZATION_EVIDENCE_MISMATCH",
                "Approved evidence facts are absent from current Product Truth.",
                details={"missing_fact_ids": missing},
            )
        evidence_refs = tuple(candidates[fid].reference() for fid in needed_fact_ids)

        stages: list[FormulaStage] = []
        for index, slice_ in enumerate(present):
            formula_stage_key = slice_.master_formula_stage_key
            master_stage = master_stage_by_formula_key.get(formula_stage_key)
            stage_fact_refs = tuple(
                candidates[fid].reference() for fid in slice_.source_evidence_fact_ids
            )
            claim_bearing = bool(
                getattr(master_stage, "claim_bearing", False)
            ) or bool(slice_.source_evidence_fact_ids)
            entry = getattr(master_stage, "entry_key", "") or (
                "OPEN" if index == 0 else f"{formula_id}_{index - 1}"
            )
            exit_ = getattr(master_stage, "exit_key", "") or f"{formula_id}_{index}"
            stages.append(
                FormulaStage(
                    stage_key=slice_.master_stage_key,
                    order=index,
                    authored_text=slice_.projected_text,
                    semantic_role=slice_.master_semantic_class
                    or getattr(master_stage, "semantic_class", None)
                    or slice_.master_stage_key,
                    formula_stage_key=formula_stage_key,
                    bridge=BridgeContract(entry=entry, exit=exit_),
                    claim_bearing=claim_bearing,
                    fact_refs=stage_fact_refs,
                )
            )

        actual_keys = [stage.formula_stage_key for stage in stages]
        if actual_keys != list(required):
            raise MaterializationError(
                "MATERIALIZATION_STAGE_INCOMPLETE",
                "Approved projection does not preserve the full formula stage set.",
                details={"required": list(required), "actual": actual_keys},
            )
        return tuple(stages), evidence_refs

    def _provenance(self, *, master, projection, receipt) -> tuple[ProvenanceEntry, ...]:
        return (
            ProvenanceEntry(key="approval_source", value=APPROVAL_SOURCE),
            ProvenanceEntry(key="materializer_version", value=MATERIALIZER_VERSION),
            ProvenanceEntry(
                key="v3_master",
                value=f"{master.master_id}:{master.revision}",
            ),
            ProvenanceEntry(
                key="v3_master_digest", value=master.exact_content_digest
            ),
            ProvenanceEntry(
                key="v3_projection",
                value=f"{projection.projection_id}:{projection.revision}",
            ),
            ProvenanceEntry(
                key="v3_projection_digest", value=projection.exact_projection_digest
            ),
            ProvenanceEntry(key="v3_approval_receipt_id", value=receipt.receipt_id),
            ProvenanceEntry(
                key="v3_approval_receipt_digest", value=receipt.receipt_digest
            ),
            ProvenanceEntry(
                key="v3_derivation_source", value=projection.derivation_source
            ),
        )

    async def _ensure_link(
        self, *, blueprint, master, projection, receipt, snapshot, actor_id, source
    ) -> MaterializationLinkV3:
        """Idempotently persist the immutable V3<->V2 materialization link.

        The link id is deterministic in the approved projection identity, so a
        rerun (or a concurrent writer) resolves to the SAME row instead of a
        duplicate authority record.
        """

        link_id = materialization_link_id(
            product_id=master.product_id,
            projection_id=projection.projection_id,
            projection_revision=projection.revision,
            projection_exact_digest=projection.exact_projection_digest,
        )
        existing = await supply_repo.get_materialization_link(link_id)
        if existing is not None:
            return existing

        truth_digest = v2svc._truth_digest(snapshot)
        approval_snapshot_id = (
            blueprint.approval_snapshot.approval_snapshot_id
            if blueprint.approval_snapshot is not None
            else ""
        )
        digest_payload = {
            "materializer_version": MATERIALIZER_VERSION,
            "product_id": master.product_id,
            "master": [master.master_id, master.revision, master.exact_content_digest],
            "projection": [
                projection.projection_id,
                projection.revision,
                projection.exact_projection_digest,
                projection.derivation_source,
            ],
            "approval_receipt": [receipt.receipt_id, receipt.receipt_digest],
            "v2_blueprint": [
                blueprint.blueprint_id,
                blueprint.revision,
                approval_snapshot_id,
            ],
            "product_truth": [
                str(snapshot["snapshot_id"]),
                int(snapshot["version"]),
                truth_digest,
            ],
            "formula": [master.formula.formula_id, master.formula.formula_version],
            "evidence_digest": master.evidence_digest,
            "target_duration_seconds": int(projection.target_duration_seconds),
        }
        link = MaterializationLinkV3(
            link_id=link_id,
            revision=1,
            product_id=master.product_id,
            master_id=master.master_id,
            master_revision=master.revision,
            master_exact_content_digest=master.exact_content_digest,
            projection_id=projection.projection_id,
            projection_revision=projection.revision,
            projection_exact_digest=projection.exact_projection_digest,
            derivation_source=projection.derivation_source,
            approval_receipt_id=receipt.receipt_id,
            approval_receipt_digest=receipt.receipt_digest,
            v2_blueprint_id=blueprint.blueprint_id,
            v2_blueprint_revision=blueprint.revision,
            v2_approval_snapshot_id=approval_snapshot_id,
            product_truth_snapshot_id=str(snapshot["snapshot_id"]),
            product_truth_snapshot_version=int(snapshot["version"]),
            product_truth_snapshot_digest=truth_digest,
            formula_id=master.formula.formula_id,
            formula_version=master.formula.formula_version,
            evidence_digest=master.evidence_digest,
            target_duration_seconds=int(projection.target_duration_seconds),
            materializer_version=MATERIALIZER_VERSION,
            materialization_digest=materialization_digest(digest_payload),
            status="PRODUCTION_VALID",
            source=source,
            created_at=_now(),
            created_by=actor_id,
        )
        try:
            await supply_repo.insert_materialization_link(link)
        except Exception:
            # A concurrent materialization won the race for this deterministic
            # link id; the canonical persisted row is authoritative.
            existing = await supply_repo.get_materialization_link(link_id)
            if existing is not None:
                return existing
            raise
        return link

    def _result(
        self, *, blueprint, master, projection, receipt, snapshot, link, idempotent_reuse
    ) -> dict[str, Any]:
        approval_snapshot_id = (
            blueprint.approval_snapshot.approval_snapshot_id
            if blueprint.approval_snapshot is not None
            else ""
        )
        return {
            "blueprint": blueprint,
            "blueprint_id": blueprint.blueprint_id,
            "revision": blueprint.revision,
            "status": blueprint.status,
            "v2_approval_snapshot_id": approval_snapshot_id,
            "link": link,
            "link_id": link.link_id,
            "link_status": link.status,
            "materialization_digest": link.materialization_digest,
            "idempotent_reuse": idempotent_reuse,
            "materializer_version": MATERIALIZER_VERSION,
            "derivation_source": projection.derivation_source,
            "target_duration_seconds": int(projection.target_duration_seconds),
            "revalidation": {
                "receipt_id": receipt.receipt_id,
                "receipt_valid": True,
                "master_fingerprint": master.exact_content_digest,
                "projection_fingerprint": projection.exact_projection_digest,
                "product_truth_snapshot_id": str(snapshot["snapshot_id"]),
                "product_truth_snapshot_version": int(snapshot["version"]),
                "product_truth_snapshot_digest": v2svc._truth_digest(snapshot),
                "formula_id": master.formula.formula_id,
                "formula_version": master.formula.formula_version,
                "evidence_digest": master.evidence_digest,
            },
            # Inputs P2 uses to write the immutable materialization_link_v3 row.
            "link_inputs": {
                "product_id": master.product_id,
                "master_id": master.master_id,
                "master_revision": master.revision,
                "master_exact_content_digest": master.exact_content_digest,
                "projection_id": projection.projection_id,
                "projection_revision": projection.revision,
                "projection_exact_digest": projection.exact_projection_digest,
                "derivation_source": projection.derivation_source,
                "approval_receipt_id": receipt.receipt_id,
                "approval_receipt_digest": receipt.receipt_digest,
                "v2_blueprint_id": blueprint.blueprint_id,
                "v2_blueprint_revision": blueprint.revision,
                "v2_approval_snapshot_id": approval_snapshot_id,
                "product_truth_snapshot_id": str(snapshot["snapshot_id"]),
                "product_truth_snapshot_version": int(snapshot["version"]),
                "product_truth_snapshot_digest": v2svc._truth_digest(snapshot),
                "formula_id": master.formula.formula_id,
                "formula_version": master.formula.formula_version,
                "evidence_digest": master.evidence_digest,
                "target_duration_seconds": int(projection.target_duration_seconds),
            },
        }
