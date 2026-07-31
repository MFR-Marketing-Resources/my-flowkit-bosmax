"""Unit tests for the Command Centre reporting service (read-only aggregation).

Seeds a tiny, controlled dataset into the fresh per-test DB and asserts the exact
aggregation math. The live-DB numbers (646/221/…) are checked separately via a
live-payload run, not here.

Seed shape:
  P1  ACTIVE   cluster=beauty_makeup   +1 approved copy   +snapshot   prompt READY
  P2  ACTIVE   cluster=generic_unclassified (trigger placeholder), mapping BLOCKED,
               prompt MISSING_FIELDS, asset UNRESOLVED, NO copy, NO snapshot
  P3  ARCHIVED cluster=home_textiles   NO copy   +snapshot
  r1  FAILED request_telemetry (product P2)
"""
from agent.db.schema import get_db
from agent.services import reporting_service as svc


async def _seed():
    db = await get_db()
    # The autouse DB reset is unreliable on Windows (file can be held → WinError 32
    # swallowed), so start from a known-clean slate. ON DELETE CASCADE from product /
    # request wipes taxonomy, copy_set, snapshot and request_telemetry.
    await db.execute("DELETE FROM product")
    await db.execute("DELETE FROM request")

    async def prod(pid, name, lifecycle, mapping, prompt, asset, upd):
        await db.execute(
            "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name, "
            "lifecycle_status, mapping_status, prompt_readiness_status, asset_status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, name, name, name, lifecycle, mapping, prompt, asset, "2026-01-01T00:00:00Z", upd),
        )

    # inserting a product fires trg_..._after_product_insert → placeholder taxonomy
    # (cluster='generic_unclassified', product_type_group='unknown_product_type').
    await prod("P1", "Alpha", "ACTIVE", "READY", "READY", "DOWNLOADED", "2026-01-01T00:00:01Z")
    await prod("P2", "Bravo", "ACTIVE", "BLOCKED", "MISSING_FIELDS", "UNRESOLVED", "2026-01-01T00:00:02Z")
    await prod("P3", "Charlie", "ARCHIVED", "READY", None, "DOWNLOADED", "2026-01-01T00:00:03Z")

    # give P1 / P3 a real cluster; P2 keeps the "missing" placeholder. Only cluster /
    # product_type_group are changed — consumer_status stays as the placeholder set
    # (the taxonomy CHECK couples review/consumer/authority/materialization, not cluster).
    await db.execute(
        "UPDATE product_strategy_taxonomy SET cluster='beauty_makeup', "
        "product_type_group='lipstick_lip_tint' WHERE product_id='P1'"
    )
    await db.execute(
        "UPDATE product_strategy_taxonomy SET cluster='home_textiles', "
        "product_type_group='bedsheet' WHERE product_id='P3'"
    )

    await db.execute("INSERT INTO copy_set (copy_set_id, product_id, status) VALUES ('cs1','P1','COPY_APPROVED')")
    await db.execute("INSERT INTO product_intelligence_snapshot (snapshot_id, product_id, version, status, created_at, updated_at) VALUES ('sn1','P1',1,'APPROVED','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
    await db.execute("INSERT INTO product_intelligence_snapshot (snapshot_id, product_id, version, status, created_at, updated_at) VALUES ('sn3','P3',1,'APPROVED','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")

    await db.execute(
        "INSERT INTO request (id, type, status, created_at, updated_at) "
        "VALUES ('r1','GENERATE_VIDEO','FAILED','2026-01-02T00:00:00Z','2026-01-02T00:00:00Z')"
    )
    await db.execute(
        "INSERT INTO request_telemetry (request_id, request_type, status, mode, product_id, created_at, failed_at) "
        "VALUES ('r1','GENERATE_VIDEO','FAILED','F2V','P2','2026-01-02T00:00:00Z','2026-01-02T00:01:00Z')"
    )
    await db.commit()


async def test_copywriting_coverage_active_vs_all():
    await _seed()
    active = await svc.copywriting_coverage("ACTIVE")
    assert active["total_products"] == 2          # P1, P2
    assert active["products_with_copy"] == 1       # P1
    assert active["products_missing_copy"] == 1    # P2
    assert active["products_with_approved_copy"] == 1
    assert active["total_copy_sets"] == 1
    assert active["copy_set_by_status"] == {"COPY_APPROVED": 1}
    assert active["coverage_pct"] == 50.0

    allp = await svc.copywriting_coverage("ALL")
    assert allp["total_products"] == 3             # + archived P3
    assert allp["products_with_copy"] == 1
    assert allp["products_missing_copy"] == 2      # P2, P3


async def test_copywriting_coverage_cluster_filter():
    await _seed()
    beauty = await svc.copywriting_coverage("ALL", cluster="beauty_makeup")
    assert beauty["total_products"] == 1           # only P1
    assert beauty["products_with_copy"] == 1


async def test_product_intelligence_coverage():
    await _seed()
    active = await svc.product_intelligence_coverage("ACTIVE")
    assert active["total_products"] == 2
    assert active["with_snapshot"] == 1            # P1
    assert active["missing_snapshot"] == 1         # P2
    allp = await svc.product_intelligence_coverage("ALL")
    assert allp["with_snapshot"] == 2              # P1, P3
    assert allp["missing_snapshot"] == 1           # P2


async def test_prompt_readiness_histogram():
    await _seed()
    active = await svc.prompt_readiness_histogram("ACTIVE")
    assert active["READY"] == 1                    # P1
    assert active["MISSING_FIELDS"] == 1           # P2
    assert active["not_evaluated"] == 0
    allp = await svc.prompt_readiness_histogram("ALL")
    assert allp["not_evaluated"] == 1              # P3 (null)


async def test_exceptions_product_kinds():
    await _seed()
    cases = {
        ("missing_copy", "ACTIVE"): {"P2"},
        ("missing_copy", "ALL"): {"P2", "P3"},
        ("mapping_blocked", "ALL"): {"P2"},
        ("missing_cluster", "ALL"): {"P2"},
        ("missing_product_type", "ALL"): {"P2"},
        ("missing_image", "ALL"): {"P2"},
        ("prompt_not_ready", "ALL"): {"P2"},
        ("missing_intelligence", "ALL"): {"P2"},
    }
    for (kind, lifecycle), expected_ids in cases.items():
        res = await svc.list_exceptions(kind, lifecycle_status=lifecycle)
        got = {item["product_id"] for item in res["items"]}
        assert res["total"] == len(expected_ids), (kind, lifecycle, res["total"])
        assert got == expected_ids, (kind, lifecycle, got)


async def test_exceptions_failed_generation():
    await _seed()
    res = await svc.list_exceptions("failed_generation")
    assert res["total"] == 1
    assert res["items"][0]["request_id"] == "r1"
    assert res["items"][0]["product_display_name"] == "Bravo"
    assert res["items"][0]["mode"] == "F2V"


async def test_exceptions_pagination():
    await _seed()
    page1 = await svc.list_exceptions("missing_copy", lifecycle_status="ALL", limit=1, offset=0)
    page2 = await svc.list_exceptions("missing_copy", lifecycle_status="ALL", limit=1, offset=1)
    assert page1["total"] == 2 and page2["total"] == 2
    assert len(page1["items"]) == 1 and len(page2["items"]) == 1
    assert page1["items"][0]["product_id"] != page2["items"][0]["product_id"]


async def test_exceptions_unknown_kind_raises():
    await _seed()
    import pytest
    with pytest.raises(ValueError):
        await svc.list_exceptions("bogus")


async def test_exceptions_applicability_splits_archived_from_required():
    """`All (incl. archived)` must not read as actionable coverage.

    A non-ACTIVE product is ARCHIVED_NOT_IN_SCOPE / PRODUCT_LIFECYCLE_ARCHIVED under the
    merged P5.8 catalog authority, so it is documented N/A, not a missing requirement.
    `total` must stay exactly as before — this is an additive split, never a filter.
    """
    await _seed()
    # P2 is ACTIVE without copy; P3 is ARCHIVED without copy.
    res = await svc.list_exceptions("missing_copy", lifecycle_status="ALL")
    assert res["total"] == 2
    assert res["applicability"]["required_missing"] == 1
    assert res["applicability"]["documented_na_archived"] == 1
    assert res["applicability"]["documented_na_reason"] == "PRODUCT_LIFECYCLE_ARCHIVED"
    # the split must always reconcile back to the unchanged total
    assert (res["applicability"]["required_missing"]
            + res["applicability"]["documented_na_archived"]) == res["total"]


async def test_exceptions_applicability_active_scope_has_no_archived_residue():
    await _seed()
    res = await svc.list_exceptions("missing_copy", lifecycle_status="ACTIVE")
    assert res["total"] == 1
    assert res["applicability"]["required_missing"] == 1
    assert res["applicability"]["documented_na_archived"] == 0


async def _seed_fixture_and_bulk():
    """P1 real ACTIVE, P2 real ACTIVE w/o copy, P3 real ARCHIVED w/o copy, F1 harness row."""
    await _seed()
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name,"
        " lifecycle_status, mapping_status, prompt_readiness_status, asset_status, created_at, updated_at)"
        " VALUES ('F1','PR223 Smoke Approve 20260706','PR223 Smoke Approve','PR223 Smoke Approve',"
        "'ARCHIVED','BLOCKED','MISSING_FIELDS','UNRESOLVED','2026-01-01T00:00:00Z','2026-01-01T00:00:09Z')")
    await db.commit()


async def test_exceptions_excludes_test_fixtures_from_real_product_totals():
    """Harness rows are not products: they never inflate real catalogue debt."""
    await _seed_fixture_and_bulk()
    res = await svc.list_exceptions("missing_copy", lifecycle_status="ALL")
    app = res["applicability"]
    # P2 (active) + P3 (archived) are real; F1 is a fixture.
    assert app["active_missing"] == 1
    assert app["archived_missing"] == 1
    assert app["real_product_missing"] == 2
    assert app["test_fixture_excluded"] == 1
    # `total` still counts every matching row, fixture included — nothing is hidden.
    assert res["total"] == 3
    assert app["real_product_missing"] + app["test_fixture_excluded"] == res["total"]


async def test_exceptions_server_side_pagination_has_no_gaps_or_duplicates():
    await _seed_fixture_and_bulk()
    seen: list[str] = []
    for offset in (0, 1, 2):
        page = await svc.list_exceptions(
            "missing_copy", lifecycle_status="ALL", limit=1, offset=offset)
        assert page["total"] == 3          # total is the WHOLE cohort, not the page
        assert len(page["items"]) == 1
        seen.append(page["items"][0]["product_id"])
    assert sorted(seen) == ["F1", "P2", "P3"]
    assert len(set(seen)) == 3             # no duplicates across pages
    # past the last page -> empty, but total unchanged
    tail = await svc.list_exceptions("missing_copy", lifecycle_status="ALL", limit=1, offset=3)
    assert tail["items"] == [] and tail["total"] == 3


async def test_exceptions_search_runs_over_whole_cohort_not_one_page():
    await _seed_fixture_and_bulk()
    res = await svc.list_exceptions("missing_copy", lifecycle_status="ALL", limit=1, q="Charlie")
    assert res["total"] == 1
    assert res["items"][0]["product_id"] == "P3"
    assert res["q"] == "Charlie"
    none = await svc.list_exceptions("missing_copy", lifecycle_status="ALL", q="zzz-no-match")
    assert none["total"] == 0 and none["items"] == []


async def test_exceptions_sort_allowlist_rejects_unknown_column():
    await _seed_fixture_and_bulk()
    ok = await svc.list_exceptions(
        "missing_copy", lifecycle_status="ALL", sort_by="product_display_name", sort_dir="asc")
    assert ok["sort_by"] == "product_display_name" and ok["sort_dir"] == "asc"
    names = [i["product_display_name"] for i in ok["items"]]
    assert names == sorted(names)
    # an unknown / injection-shaped value must never reach SQL as an identifier
    bad = await svc.list_exceptions(
        "missing_copy", lifecycle_status="ALL", sort_by="p.id; DROP TABLE product--")
    assert bad["sort_by"] is None
    assert bad["total"] == 3
