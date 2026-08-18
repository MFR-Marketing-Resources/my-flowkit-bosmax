"""Task A — canonical Product Truth -> EvidenceFact parity (V2 <-> V3).

Proves the V3 read model derives the current EvidenceFact set from the APPROVED
Product Truth snapshot itself, in EXACT parity with the V2 authority derivation,
with zero DB writes and zero provider calls. Persisted copy_evidence_fact_v2 rows
are integrity-only: missing/partial never downgrade the derived set, old-snapshot
rows are ignored, and a current-snapshot digest conflict fails closed.
"""

from __future__ import annotations

import json

import pytest

from agent.db.schema import get_db
from agent.models.copy_blueprint_v2 import digest_evidence_text
from agent.services import copy_register_v2_service as v2svc
from agent.services.product_truth_evidence import derive_product_truth_evidence_facts
from agent.services.storyboard_landbank_v3_factory import (
    ProductTruthEvidenceAdapter,
    V3FactoryError,
)

_FIELDS = (
    "fact_id",
    "fact_kind",
    "text",
    "text_digest",
    "snapshot_id",
    "snapshot_version",
    "snapshot_status",
    "approved",
)


def _key(fact) -> tuple:
    return tuple(getattr(fact, name) for name in _FIELDS)


def _keys(facts) -> list[tuple]:
    return sorted(_key(f) for f in facts)


async def _seed_product(product_id: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, source, raw_product_title, product_display_name, "
        "product_short_name, lifecycle_status, created_at, updated_at) "
        "VALUES (?, 'MANUAL', 'Parity Product', 'Parity Product', 'Parity', 'ACTIVE', "
        "'2026-08-18T00:00:00Z', '2026-08-18T00:00:00Z')",
        (product_id,),
    )
    await db.commit()


async def _seed_snapshot(
    product_id: str,
    *,
    snapshot_id: str,
    version: int,
    status: str = "APPROVED",
    description: str = "A lightweight serum for a simple daily routine.",
    benefits: list[str] | None = None,
    usps: list[str] | None = None,
) -> str:
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, "
        "usp_json, target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, "
        "copy_strategy_summary_json, claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'Pembeli rutin harian', '[\"formula ringan\"]', "
        "'{\"audience\":\"pembeli\"}', '{\"angle\":\"rutin\"}', 'CLAIM_SAFE', 'LOW', "
        "'2026-08-18T00:00:00Z', '2026-08-18T00:00:00Z')",
        (
            snapshot_id,
            product_id,
            version,
            status,
            description,
            json.dumps(benefits if benefits is not None else ["menyerap cepat", "tekstur ringan"]),
            json.dumps(usps if usps is not None else ["formula ringan"]),
        ),
    )
    await db.commit()
    return snapshot_id


async def _load_dicts(product_id: str):
    db = await get_db()
    product = dict(await (await db.execute("SELECT * FROM product WHERE id=?", (product_id,))).fetchone())
    snapshot = dict(
        await (
            await db.execute(
                "SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' "
                "ORDER BY version DESC LIMIT 1",
                (product_id,),
            )
        ).fetchone()
    )
    return product, snapshot


async def _v2_facts(product_id: str) -> list:
    product, snapshot = await _load_dicts(product_id)
    return list(v2svc._fact_candidates(product, snapshot))


async def _v3_facts(product_id: str) -> list:
    bundle = await ProductTruthEvidenceAdapter().current(product_id)
    return list(bundle.registry.facts)


async def _persist_fact(fact, *, override_text: str | None = None, override_digest: str | None = None) -> None:
    db = await get_db()
    text = override_text if override_text is not None else fact.text
    digest = override_digest if override_digest is not None else fact.text_digest
    await db.execute(
        "INSERT INTO copy_evidence_fact_v2 "
        "(product_id, snapshot_id, fact_id, fact_kind, canonical_text, text_digest, "
        "snapshot_version, snapshot_status, approved, source_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'APPROVED', 1, ?, '2026-08-18T00:00:00Z')",
        (
            fact.product_id,
            fact.snapshot_id,
            fact.fact_id,
            fact.fact_kind,
            text,
            digest,
            fact.snapshot_version,
            fact.source_ref,
        ),
    )
    await db.commit()


async def _count_evidence(product_id: str) -> int:
    db = await get_db()
    row = await (await db.execute("SELECT COUNT(*) FROM copy_evidence_fact_v2 WHERE product_id=?", (product_id,))).fetchone()
    return int(row[0])


# --------------------------------------------------------------------------- #
# A. APPROVED snapshot, ZERO persisted evidence -> V2 facts == V3 facts exactly
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_parity_A_zero_persisted_evidence():
    pid = "parity-A"
    await _seed_product(pid)
    await _seed_snapshot(pid, snapshot_id="parity-A-snap", version=5)

    before = await _count_evidence(pid)
    v2 = await _v2_facts(pid)
    v3 = await _v3_facts(pid)

    assert len(v3) >= 4  # description + benefits + usp + target + allowed claim
    assert _keys(v2) == _keys(v3)  # exact parity across all 8 fields
    # Read path performed zero writes (no lazy backfill).
    assert await _count_evidence(pid) == before == 0


# --------------------------------------------------------------------------- #
# B. APPROVED snapshot, persisted current facts matching -> exact parity
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_parity_B_persisted_matching():
    pid = "parity-B"
    await _seed_product(pid)
    await _seed_snapshot(pid, snapshot_id="parity-B-snap", version=5)
    for fact in await _v2_facts(pid):
        await _persist_fact(fact)  # persist the full, matching set

    before = await _count_evidence(pid)
    v2 = await _v2_facts(pid)
    v3 = await _v3_facts(pid)

    assert _keys(v2) == _keys(v3)
    # Full matching projection persisted; the read neither added nor removed rows.
    assert await _count_evidence(pid) == before == len(v2)


# --------------------------------------------------------------------------- #
# C. PARTIAL persisted projection -> V3 still returns the full derived set
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_parity_C_partial_persisted_not_downgraded():
    pid = "parity-C"
    await _seed_product(pid)
    await _seed_snapshot(pid, snapshot_id="parity-C-snap", version=5)
    derived = await _v2_facts(pid)
    await _persist_fact(derived[0])  # persist only ONE of four

    v3 = await _v3_facts(pid)
    assert len(v3) == len(derived)  # partial persisted never downgrades
    assert len(derived) > 1  # there ARE more derived facts than the single persisted row
    assert _keys(v3) == _keys(derived)
    assert await _count_evidence(pid) == 1  # read did not top up the projection


# --------------------------------------------------------------------------- #
# D. Persisted rows from an OLD snapshot -> current facts derive from latest only
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_parity_D_old_snapshot_rows_ignored():
    pid = "parity-D"
    await _seed_product(pid)
    # Old approved snapshot (v1) with DIFFERENT text, then current approved (v2).
    await _seed_snapshot(pid, snapshot_id="parity-D-v1", version=1, description="Old description.", benefits=["old benefit"], usps=["old usp"])
    # Persist v1-tagged evidence (build facts from the v1 snapshot explicitly).
    db = await get_db()
    v1_snap = dict(await (await db.execute("SELECT * FROM product_intelligence_snapshot WHERE snapshot_id='parity-D-v1'")).fetchone())
    v1_product = dict(await (await db.execute("SELECT * FROM product WHERE id=?", (pid,))).fetchone())
    for fact in derive_product_truth_evidence_facts(v1_product, v1_snap):
        await _persist_fact(fact)
    await _seed_snapshot(pid, snapshot_id="parity-D-v2", version=2, description="New current description.", benefits=["new benefit one", "new benefit two"], usps=["new usp"])

    v3 = await _v3_facts(pid)
    # Current facts come ONLY from the latest approved snapshot (v2).
    assert {f.snapshot_id for f in v3} == {"parity-D-v2"}
    assert {f.snapshot_version for f in v3} == {2}
    assert any(f.text == "New current description." for f in v3)
    assert all(f.text != "Old description." for f in v3)
    assert _keys(v3) == _keys(await _v2_facts(pid))


# --------------------------------------------------------------------------- #
# E. Current-snapshot persisted fact conflicting text/digest -> FAIL CLOSED
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_parity_E_conflicting_current_evidence_fails_closed():
    pid = "parity-E"
    await _seed_product(pid)
    await _seed_snapshot(pid, snapshot_id="parity-E-snap", version=5)
    derived = await _v2_facts(pid)
    tampered_text = "TAMPERED evidence text that no longer matches the approved snapshot."
    await _persist_fact(
        derived[0],
        override_text=tampered_text,
        override_digest=digest_evidence_text(tampered_text),
    )
    before = await _count_evidence(pid)

    with pytest.raises(V3FactoryError) as excinfo:
        await _v3_facts(pid)
    assert excinfo.value.code == "PRODUCT_TRUTH_EVIDENCE_CORRUPTION"
    # No silent overwrite / no DB repair on the fail-closed path.
    assert await _count_evidence(pid) == before == 1


# --------------------------------------------------------------------------- #
# Shared-seam determinism: V2 wrapper and the shared seam are identical.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_v2_wrapper_delegates_to_shared_seam_exactly():
    pid = "parity-seam"
    await _seed_product(pid)
    await _seed_snapshot(pid, snapshot_id="parity-seam-snap", version=3)
    product, snapshot = await _load_dicts(pid)
    assert _keys(v2svc._fact_candidates(product, snapshot)) == _keys(
        derive_product_truth_evidence_facts(product, snapshot)
    )
