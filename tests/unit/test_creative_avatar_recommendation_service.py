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
    # unknown / empty -> deterministic fallback
    assert svc.resolve_cluster("Verification") == {"cluster": "Home & Living", "cluster_source": "FALLBACK"}
    assert svc.resolve_cluster(None)["cluster_source"] == "FALLBACK_EMPTY"
    # every resolved cluster is one of the 12 canonical clusters
    clusters = set(svc.canonical_clusters())
    for cat in ("Automotive & Motorcycle", "Pet Supplies", "Sports & Outdoor", "Kitchenware", "Random Nonsense"):
        assert svc.resolve_cluster(cat)["cluster"] in clusters


def test_crosswalk_codes_all_resolve_in_live_pool():
    live = {a["avatar_code"] for a in avatar_registry.list_pool()}
    cross = svc._crosswalk()["crosswalk"]
    assert set(cross.keys()) == set(svc.canonical_clusters())
    for cluster, rows in cross.items():
        assert 3 <= len(rows) <= 5  # 3-5 avatars per cluster
        for row in rows:
            code = row["avatar_code"]
            assert code.startswith("BOS_")  # never workbook AV01-AV08
            assert code in live  # validated against the live pool
            # resolvable by the existing registry (what avatar_fit_service uses)
            avatar_registry.resolve_presenter(avatar_id=code)


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
    assert report["mappings_valid"] == 60
    assert report["skipped_invalid"] == []
    assert await _count("avatar_product_fit") == before  # nothing persisted


@pytest.mark.asyncio
async def test_seed_writes_idempotently_with_provenance():
    products_before = await _count("product")
    copy_before = await _count("copy_set")
    snap_before = await _count("product_intelligence_snapshot")

    r1 = await svc.seed_avatar_product_fit(dry_run=False)
    assert r1["written"] == 60
    n1 = await _count("avatar_product_fit")
    assert n1 == 60

    # Re-seed is idempotent (upsert keyed on avatar_code+product_category).
    r2 = await svc.seed_avatar_product_fit(dry_run=False)
    assert r2["written"] == 60
    assert await _count("avatar_product_fit") == 60

    # Provenance is preserved in the notes.
    rows = await crud.list_avatar_product_fits(product_category="BEAUTY")
    assert rows
    assert all(svc.CROSSWALK_SOURCE in (row.get("suitability_notes") or "") for row in rows)

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
    assert result["avatar_count"] >= 3
    assert all(a["fit_source"] == "EXPLICIT_MAPPING" for a in result["avatars"])
    assert all(str(a["avatar_code"]).startswith("BOS_") for a in result["avatars"])


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
    assert r_imp["cluster"] == "Beauty" and r_imp["avatar_count"] >= 3
    assert r_man["cluster"] == "Automotive" and r_man["avatar_count"] >= 3
    assert r_imp["product_id"] == imported["id"]


@pytest.mark.asyncio
async def test_recommend_unknown_category_degrades_gracefully():
    await svc.seed_avatar_product_fit(dry_run=False)
    manual = await crud.create_product(
        source="MANUAL", raw_product_title="Mystery", product_display_name="Mystery",
        product_short_name="Mystery", category="Totally Unknown Thing",
    )
    result = await svc.recommend_avatars_for_product(manual["id"])
    assert result["cluster"] == "Home & Living"  # deterministic fallback
    assert result["cluster_source"] == "FALLBACK"
    assert result["avatar_count"] >= 1  # still returns avatars, never crashes


@pytest.mark.asyncio
async def test_recommend_missing_product_raises():
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.recommend_avatars_for_product("does-not-exist")


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
