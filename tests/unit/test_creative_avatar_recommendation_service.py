"""Creative Intelligence Round 1 — avatar recommendation service tests."""
import pytest

from agent.db import crud
from agent.services import avatar_registry
from agent.services import creative_avatar_recommendation_service as svc


async def _count(table):
    db = await crud.get_db()
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    return (await cur.fetchone())[0]


def test_resolve_cluster_exact_prefix_keyword_fallback():
    assert svc.resolve_cluster("Beauty & Personal Care") == {"cluster": "Beauty", "cluster_source": "EXACT"}
    assert svc.resolve_cluster("Muslim Fashion")["cluster"] == "Fashion"
    assert svc.resolve_cluster("Baby Care") == {"cluster": "Baby & Kids", "cluster_source": "KEYWORD"}
    assert svc.resolve_cluster("Electronics")["cluster"] == "Electronics & Gadgets"
    # FAIL-CLOSED (Defect 1): an empty or genuinely unknown category is
    # review-required, never a silent Home & Living fallback.
    assert svc.resolve_cluster("Verification") == {
        "cluster": None, "cluster_source": "REVIEW_REQUIRED_UNKNOWN_CATEGORY"
    }
    assert svc.resolve_cluster("Random Nonsense")["cluster"] is None
    assert svc.resolve_cluster(None) == {
        "cluster": None, "cluster_source": "REVIEW_REQUIRED_NO_CATEGORY"
    }
    assert svc.resolve_cluster("")["cluster"] is None
    assert svc.resolve_cluster("   ")["cluster"] is None
    assert svc.is_review_required(svc.resolve_cluster(None)) is True
    assert svc.is_review_required(svc.resolve_cluster("Beauty & Personal Care")) is False
    # The legacy generation lane may still opt in to the deterministic fallback.
    assert svc.resolve_cluster(None, allow_fallback=True) == {
        "cluster": "Home & Living", "cluster_source": "FALLBACK_EMPTY"
    }
    assert svc.resolve_cluster("Verification", allow_fallback=True) == {
        "cluster": "Home & Living", "cluster_source": "FALLBACK"
    }


def test_crosswalk_is_live_pool_authority_and_deterministically_ranked():
    live = {a["avatar_code"] for a in avatar_registry.list_pool()}
    cross = svc._crosswalk()["crosswalk"]
    assert set(cross.keys()) == set(svc.canonical_clusters())
    candidates = {row["avatar_code"] for rows in cross.values() for row in rows}
    assert candidates <= live
    for cluster, rows in cross.items():
        codes = [row["avatar_code"] for row in rows]
        scores = [float(row["fit_score"]) for row in rows]
        assert len(codes) == len(set(codes)), cluster
        assert scores == sorted(scores, reverse=True), cluster
        assert all(0 <= score <= 1 for score in scores), cluster


def test_crosswalk_code_gender_prefix_matches_seed():
    """Regression guard for the BOS_F_/BOS_M_ misprefix: every crosswalk avatar
    code's gender prefix must match the SEED pool's gender for that persona (the
    seed is the gender authority). Catches a male persona wrongly prefixed BOS_F_
    (or vice-versa) in the committed crosswalk."""
    import csv
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    code_re = re.compile(r"BOS_([FM])_([A-Z0-9]+)_[0-9]{2,}")
    seed_gender: dict[str, str] = {}
    with open(
        root / "agent/authority/AVATAR_POOL_NORMALIZED.csv",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        for row in csv.DictReader(f):
            m = code_re.match(str(row.get("AvatarCode") or ""))
            if m:
                seed_gender.setdefault(m.group(2), m.group(1))
    assert seed_gender.get("AMIR") == "M"  # sanity: seed knows AMIR is male

    bad = []
    for rows in svc._crosswalk()["crosswalk"].values():
        for row in rows:
            m = code_re.match(str(row["avatar_code"]))
            if not m:
                continue
            gender, token = m.group(1), m.group(2)
            expected = seed_gender.get(token)
            if expected and gender != expected:
                bad.append((row["avatar_code"], f"persona is {expected}"))
    assert not bad, f"crosswalk codes with wrong gender prefix vs seed: {bad}"


@pytest.mark.asyncio
async def test_seed_dry_run_writes_nothing():
    before = await _count("avatar_product_fit")
    report = await svc.seed_avatar_product_fit(dry_run=True)
    assert report["dry_run"] is True
    assert report["written"] == 0
    # dry-run reports the plan (valid + skipped == every crosswalk pair) but
    # persists nothing.
    total_pairs = sum(len(rows) for rows in svc._crosswalk()["crosswalk"].values())
    assert report["mappings_valid"] + len(report["skipped_invalid"]) == total_pairs
    assert await _count("avatar_product_fit") == before  # nothing persisted


@pytest.mark.asyncio
async def test_seed_writes_idempotently_with_provenance():
    products_before = await _count("product")
    copy_before = await _count("copy_set")
    snap_before = await _count("product_intelligence_snapshot")
    fits_before = await _count("avatar_product_fit")

    r1 = await svc.seed_avatar_product_fit(dry_run=False)
    assert r1["written"] == r1["mappings_valid"]  # every valid crosswalk pair upserted
    n1 = await _count("avatar_product_fit")
    assert n1 >= fits_before

    # Re-seed is idempotent (upsert keyed on avatar_code+product_category): the
    # row count does not grow.
    r2 = await svc.seed_avatar_product_fit(dry_run=False)
    assert r2["written"] == r2["mappings_valid"]
    assert await _count("avatar_product_fit") == n1

    # No Product Truth / Copy Set / snapshot mutation.
    assert await _count("product") == products_before
    assert await _count("copy_set") == copy_before
    assert await _count("product_intelligence_snapshot") == snap_before


@pytest.mark.asyncio
async def test_recommend_for_category_returns_explicit_avatars_after_seed():
    await svc.seed_avatar_product_fit(dry_run=False)
    result = await svc.recommend_avatars_for_category("Beauty & Personal Care")
    assert result["cluster"] == "Beauty"
    assert result["cluster_source"] == "EXACT"
    assert result["review_required"] is False
    assert result["avatar_count"] >= 1
    assert all(str(a["avatar_code"]).startswith("BOS_") for a in result["avatars"])
    # fit_source is EXPLICIT_MAPPING where the seed placed a ranked pair, else the
    # safe FALLBACK_UNRANKED — both are valid, non-review recommendations.
    assert all(
        a["fit_source"] in ("EXPLICIT_MAPPING", "FALLBACK_UNRANKED")
        for a in result["avatars"]
    )


@pytest.mark.asyncio
async def test_recommend_parity_manual_and_imported_product():
    await svc.seed_avatar_product_fit(dry_run=False)
    imported = await crud.create_product(
        source="FASTMOSS", raw_product_title="Imported Serum", product_display_name="Imported Serum",
        product_short_name="Serum", category="Beauty & Personal Care",
    )
    manual = await crud.create_product(
        source="MANUAL", raw_product_title="Manual Car Mat", product_display_name="Manual Car Mat",
        product_short_name="Car Mat", category="Automotive & Motorcycle",
    )
    r_imp = await svc.recommend_avatars_for_product(imported["id"])
    r_man = await svc.recommend_avatars_for_product(manual["id"])
    assert r_imp["cluster"] == "Beauty" and r_imp["avatar_count"] >= 1
    assert r_man["cluster"] == "Automotive" and r_man["avatar_count"] >= 1
    assert r_imp["product_id"] == imported["id"]


@pytest.mark.asyncio
async def test_recommend_unknown_category_is_review_required():
    """Defect 1: an unknown OR blank category yields NO avatar recommendation and
    ``review_required=True`` — never a silent Home & Living plan."""
    await svc.seed_avatar_product_fit(dry_run=False)
    unknown = await crud.create_product(
        source="MANUAL", raw_product_title="Mystery", product_display_name="Mystery",
        product_short_name="Mystery", category="Totally Unknown Thing",
    )
    blank = await crud.create_product(
        source="MANUAL", raw_product_title="Uncategorised", product_display_name="Uncategorised",
        product_short_name="Uncat", category="",
    )
    cases = (
        (unknown["id"], "REVIEW_REQUIRED_UNKNOWN_CATEGORY"),
        (blank["id"], "REVIEW_REQUIRED_NO_CATEGORY"),
    )
    for pid, expected_source in cases:
        result = await svc.recommend_avatars_for_product(pid)
        assert result["cluster"] is None
        assert result["cluster_source"] == expected_source
        assert result["review_required"] is True
        assert result["avatar_count"] == 0
        assert result["avatars"] == []


@pytest.mark.asyncio
async def test_recommend_missing_product_raises():
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.recommend_avatars_for_product("does-not-exist")


@pytest.mark.asyncio
async def test_audit_counts_blank_and_unknown_as_review_required():
    """Defect 1: the product-cluster audit never auto-clusters a blank or
    unresolved category — both are counted review-required, and cluster_counts
    is never None-keyed."""
    await crud.create_product(
        source="MANUAL", raw_product_title="Known Beauty", product_display_name="Known Beauty",
        product_short_name="Known", category="Beauty & Personal Care",
    )
    await crud.create_product(
        source="MANUAL", raw_product_title="Blank Cat", product_display_name="Blank Cat",
        product_short_name="Blank", category="",
    )
    await crud.create_product(
        source="MANUAL", raw_product_title="Weird Cat", product_display_name="Weird Cat",
        product_short_name="Weird", category="Totally Unknown Thing",
    )
    audit = await svc.audit_product_cluster_coverage()
    assert audit["unknown_review_required"] >= 2  # the blank + the unknown
    assert audit["cluster_counts"]["Beauty"] >= 1  # the known one IS clustered
    assert None not in audit["cluster_counts"]  # never a None-keyed cluster


@pytest.mark.asyncio
async def test_audit_excludes_smoke_fixtures_from_review_required():
    """Fix A: an archived smoke-test fixture (blank category) is NOT a real product
    and must never inflate unknown_review_required — that is what made the Executive
    'Uncategorised' KPI read non-zero while the real catalogue was fully clustered."""
    before = await svc.audit_product_cluster_coverage()

    # a harness fixture row (smoke title) with a blank category
    await crud.create_product(
        source="MANUAL", raw_product_title="PR223 Smoke Approve 20260706",
        product_display_name="PR223 Smoke Approve", product_short_name="PR223 Smoke Approve",
        category="",
    )
    after_fixture = await svc.audit_product_cluster_coverage()
    # the fixture is quarantined: neither the total nor the review counter moves
    assert after_fixture["unknown_review_required"] == before["unknown_review_required"]
    assert after_fixture["product_total"] == before["product_total"]

    # contrast: a GENUINE blank-category product still increments (counter alive)
    await crud.create_product(
        source="MANUAL", raw_product_title="Genuine Mystery Item",
        product_display_name="Genuine Mystery Item", product_short_name="Genuine",
        category="",
    )
    after_real = await svc.audit_product_cluster_coverage()
    assert after_real["unknown_review_required"] == before["unknown_review_required"] + 1
    assert after_real["product_total"] == before["product_total"] + 1


def test_invariant_generation_services_do_not_reference_creative_recommendation():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    generation_files = [
        "agent/services/canonical_prompt_compiler.py",
        "agent/services/ai_copy_assist_service.py",
        "agent/services/copy_grounding_service.py",
        "agent/services/copy_binding_service.py",
        "agent/services/workspace_execution_package_service.py",
    ]
    for rel in generation_files:
        text = (repo_root / rel).read_text(encoding="utf-8")
        assert "creative_avatar_recommendation_service" not in text
        assert "creative_avatar_cluster_crosswalk" not in text


@pytest.mark.asyncio
async def test_reconcile_avatar_product_fit_dry_run_and_apply(monkeypatch):
    """Reconciliation only touches avatar_product_fit; dry-run is write-free."""
    live_codes = {"BOS_F_TEST_01", "BOS_M_TEST_02"}

    monkeypatch.setattr(svc, "_live_avatar_codes", lambda: set(live_codes))
    monkeypatch.setattr(
        svc,
        "_crosswalk",
        lambda: {
            "crosswalk": {
                "Beauty": [
                    {
                        "avatar_code": "BOS_F_TEST_01",
                        "fit_score": 0.9,
                        "suitability_notes": f"Beauty [src:{svc.CROSSWALK_SOURCE}]",
                    },
                    {
                        "avatar_code": "BOS_ORPHAN_99",
                        "fit_score": 0.5,
                        "suitability_notes": "orphan",
                    },
                ],
                "Home & Living": [
                    {
                        "avatar_code": "BOS_M_TEST_02",
                        "fit_score": 0.85,
                        "suitability_notes": f"Home [src:{svc.CROSSWALK_SOURCE}]",
                    },
                ],
            }
        },
    )

    # Seed a stale managed row + a manual row that must be preserved.
    await crud.upsert_avatar_product_fit(
        avatar_code="BOS_STALE_01",
        product_category="Beauty",
        fit_score=0.1,
        suitability_notes=f"stale [src:{svc.CROSSWALK_SOURCE}]",
    )
    await crud.upsert_avatar_product_fit(
        avatar_code="BOS_MANUAL_01",
        product_category="Beauty",
        fit_score=0.99,
        suitability_notes="operator override — keep",
    )

    dry = await svc.reconcile_avatar_product_fit(dry_run=True)
    assert dry["dry_run"] is True
    assert dry["written"] == 0
    assert dry["removed"] == 0
    assert dry["expected_count"] == 2
    assert any(m["avatar_code"] == "BOS_F_TEST_01" for m in dry["missing"])
    assert any(s["avatar_code"] == "BOS_STALE_01" for s in dry["stale_managed"])
    assert dry["preserved_manual_count"] >= 1
    assert "BOS_ORPHAN_99" in dry["orphan_avatar_codes"]

    applied = await svc.reconcile_avatar_product_fit(dry_run=False)
    assert applied["dry_run"] is False
    assert applied["written"] == 2
    assert applied["removed"] >= 1
    assert applied["parity_ok"] is True

    rows = await crud.list_avatar_product_fits(limit=5000)
    keys = {(r["avatar_code"], r["product_category"]) for r in rows}
    assert ("BOS_F_TEST_01", "BEAUTY") in keys
    assert ("BOS_M_TEST_02", "HOME_LIVING") in keys
    assert ("BOS_STALE_01", "Beauty") not in keys
    assert ("BOS_MANUAL_01", "Beauty") in keys  # preserved


@pytest.mark.asyncio
async def test_reconcile_avatar_product_fits_rolls_back_all_writes_on_failure():
    """A later malformed mapping cannot leave an earlier mapping committed."""
    before = await crud.list_avatar_product_fits(limit=10_000)
    with pytest.raises(KeyError):
        await crud.reconcile_avatar_product_fits(
            [
                {
                    "avatar_code": "BOS_TXN_TEST_01",
                    "product_category": "BEAUTY",
                    "fit_score": 0.9,
                    "suitability_notes": "transaction proof",
                },
                {"avatar_code": "BOS_TXN_FAIL_02"},
            ],
            [],
        )
    after = await crud.list_avatar_product_fits(limit=10_000)
    assert after == before
