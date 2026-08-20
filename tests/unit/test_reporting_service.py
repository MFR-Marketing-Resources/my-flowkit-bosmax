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
    # request wipes taxonomy, snapshot and request_telemetry.
    #
    # The V2 copy-authority chain (authority -> binding -> blueprint) references
    # product, and the binding is immutable-by-trigger, so it neither cascade-deletes
    # nor deletes normally — a prior copywriting-coverage test would otherwise block
    # this reseed's DELETE FROM product and wedge the shared connection. Drop the
    # delete guard (this file never asserts binding immutability) and wipe the chain
    # child-first before deleting products.
    await db.execute("DROP TRIGGER IF EXISTS trg_copy_execution_binding_v2_immutable_delete")
    await db.execute("DROP TRIGGER IF EXISTS trg_copy_blueprint_v2_approved_immutable_delete")
    await db.execute("DELETE FROM copy_execution_authority_v2")
    await db.execute("DELETE FROM copy_execution_binding_v2")
    await db.execute("DELETE FROM copy_blueprint_v2")
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

    # Snapshots first: P1's copy blueprint references its product-truth snapshot
    # (FK copy_blueprint_v2.product_truth_snapshot_id -> product_intelligence_snapshot).
    await db.execute("INSERT INTO product_intelligence_snapshot (snapshot_id, product_id, version, status, created_at, updated_at) VALUES ('sn1','P1',1,'APPROVED','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
    await db.execute("INSERT INTO product_intelligence_snapshot (snapshot_id, product_id, version, status, created_at, updated_at) VALUES ('sn3','P3',1,'APPROVED','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")

    # Current copy coverage = active V2 copy execution authority (the retired copy_set
    # store is gone). Give P1 the full blueprint -> BOUND/REQUIRED/VIDEO binding ->
    # activated authority chain so P1 counts as "has copy"; P2/P3 stay missing. Every
    # FK / NOT NULL / CHECK / integrity trigger is satisfied with foreign keys ON.
    await db.execute(
        "INSERT INTO copy_blueprint_v2 (blueprint_id, product_id, revision, status, "
        "formula_id, formula_version, objective_json, angle_json, stages_json, "
        "component_refs_json, evidence_refs_json, product_truth_lineage_json, "
        "product_truth_snapshot_id, product_truth_snapshot_version, product_truth_snapshot_digest, "
        "approved_execution_text_json, provenance_json, estimated_word_count, blueprint_digest, created_at) "
        "VALUES ('bp1','P1',1,'PRODUCTION_VALID','PAS','v1','{}','{}','{}','{}','{}','{}',"
        "'sn1',1, ?, '{}','{}',10, ?, 't')",
        ("d" * 64, "b" * 64),
    )
    await db.execute(
        "INSERT INTO copy_execution_binding_v2 (binding_id, blueprint_id, revision, "
        "product_id, lane, media_kind, copy_policy, formula_id, formula_version, "
        "approval_snapshot_id, product_truth_lineage_json, evidence_lineage_json, "
        "evidence_digest, compiler_binding_version, feature_flag_state_json, binding_status, bound_at) "
        "VALUES ('b1','bp1',1,'P1','T2V','VIDEO','REQUIRED','PAS','v1','sn1','{}','{}', ?, 'v2', '{}', 'BOUND', 't')",
        ("a" * 64,),
    )
    await db.execute(
        "INSERT INTO copy_execution_authority_v2 (product_id, lane, binding_id, activated_at) "
        "VALUES ('P1','T2V','b1','t')"
    )

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
    # copy_set aggregates are retired; V2 authority coverage reports them as absent.
    assert active["total_copy_sets"] is None
    assert active["copy_set_by_status"] is None
    assert active["authority"] == "copy_execution_authority_v2"
    assert active["coverage_pct"] == 50.0

    allp = await svc.copywriting_coverage("ALL")
    assert allp["total_products"] == 3             # + archived P3
    assert allp["products_with_copy"] == 1
    assert allp["products_missing_copy"] == 2      # P2, P3


async def test_copywriting_coverage_tristate_current(monkeypatch):
    """CURRENT: the covered product resolves a current-valid activation, so it counts
    as production-ready and copy_classification_counts reconciles with the headline
    (VALID + STALE + MISSING == total)."""
    from agent.services import copy_register_v2_service as v2

    async def fake(pid):
        return {"active_blueprint_id": "bp1", "active_revision": 1}

    monkeypatch.setattr(v2, "get_activation_status", fake)
    await _seed()
    cov = await svc.copywriting_coverage("ACTIVE")
    counts = cov["copy_classification_counts"]
    assert counts == {"APPROVED_COPY_VALID": 1, "APPROVED_COPY_STALE": 0, "MISSING_COPY": 1}
    assert sum(counts.values()) == cov["total_products"] == 2
    assert cov["products_with_valid_approved_copy"] == 1
    assert cov["validity_evaluation_failed"] == 0
    assert cov["valid_approved_coverage_pct"] == 50.0


async def test_copywriting_coverage_tristate_reveals_stale(monkeypatch):
    """STALE (the GAP-1 fix): the covered product has a BOUND authority but no
    current-valid activation resolves, so it is reclassified STALE — the exact case
    the binary EXISTS predicate previously hid as 'covered'/production-ready."""
    from agent.services import copy_register_v2_service as v2

    async def fake(pid):
        return {"active_blueprint_id": None}

    monkeypatch.setattr(v2, "get_activation_status", fake)
    await _seed()
    cov = await svc.copywriting_coverage("ACTIVE")
    counts = cov["copy_classification_counts"]
    assert counts == {"APPROVED_COPY_VALID": 0, "APPROVED_COPY_STALE": 1, "MISSING_COPY": 1}
    # still 'covered' by the raw predicate, but NOT production-ready
    assert cov["products_with_copy"] == 1
    assert cov["products_with_valid_approved_copy"] == 0
    assert cov["valid_approved_coverage_pct"] == 0.0


async def test_classify_copy_authority_fails_closed(monkeypatch):
    """An activation-check error fails closed to `failed` — never silently CURRENT."""
    from agent.services import copy_register_v2_service as v2

    async def boom(pid):
        raise RuntimeError("lineage load failed")

    monkeypatch.setattr(v2, "get_activation_status", boom)
    assert await svc._classify_copy_authority(["x", "y"]) == {
        "current": 0,
        "stale": 0,
        "failed": 2,
    }


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


async def test_catalog_population_summary_separates_raw_active_and_canonical():
    await _seed()
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name, lifecycle_status, archived_reason) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("alias-1", "Alpha duplicate", "Alpha duplicate", "Alpha duplicate", "ARCHIVED", "DUPLICATE_MERGED_TO_CANONICAL:P1"),
    )
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name, lifecycle_status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("fixture_1", "Test Product", "Test Product", "Test Product", "ACTIVE"),
    )
    await db.commit()

    summary = await svc.catalog_population_summary()

    assert summary["raw_database_rows"] == 5
    assert summary["active_products"] == 3
    assert summary["archived_products"] == 2
    assert summary["merged_historical_aliases"] == 1
    assert summary["test_fixture_rows"] == 1
    assert summary["real_canonical_products"] == 3
    assert summary["real_active_canonical_products"] == 2
    assert summary["production_eligible_products"] == 2
    assert summary["arithmetic"]["raw_equals_real_plus_aliases_plus_fixtures"] is True


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


async def test_exceptions_items_carry_creative_cluster_projection():
    """PR-4: every drill-down row projects its stored strategy cluster to the
    creative bucket (resolve-on-read) so reporting can show both."""
    from agent.services.product_cluster_grouping import resolve_creative_cluster

    await _seed()
    res = await svc.list_exceptions("missing_copy", lifecycle_status="ALL")  # P2 + P3
    by_id = {item["product_id"]: item for item in res["items"]}
    for item in res["items"]:
        assert item["creative_cluster"] == resolve_creative_cluster(item.get("cluster"))
    assert by_id["P3"]["creative_cluster"] == resolve_creative_cluster("home_textiles")
    assert by_id["P2"]["creative_cluster"] is None  # generic_unclassified is unmapped


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
    # `total` is the REAL-PRODUCT count: fixtures are quarantined out of the default list
    # so the headline and the pager share one denominator (B-578-01).
    assert res["total"] == 2
    assert app["real_product_missing"] == res["total"]
    # nothing is hidden — the fixture is still reachable through the explicit view
    everything = await svc.list_exceptions(
        "missing_copy", lifecycle_status="ALL", include_test_fixtures=True)
    assert everything["total"] == res["total"] + app["test_fixture_excluded"]


async def test_exceptions_server_side_pagination_has_no_gaps_or_duplicates():
    await _seed_fixture_and_bulk()
    seen: list[str] = []
    for offset in (0, 1, 2):
        page = await svc.list_exceptions(
            "missing_copy", lifecycle_status="ALL", limit=1, offset=offset,
            include_test_fixtures=True)
        assert page["total"] == 3          # total is the WHOLE cohort, not the page
        seen.extend(i["product_id"] for i in page["items"])
    assert sorted(seen) == ["F1", "P2", "P3"]
    assert len(set(seen)) == 3             # no duplicates across pages
    # past the last page -> empty, but total unchanged
    tail = await svc.list_exceptions(
        "missing_copy", lifecycle_status="ALL", limit=1, offset=3, include_test_fixtures=True)
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
    assert bad["total"] == 2  # real products; the injection-shaped value changed nothing


async def test_exceptions_default_quarantines_fixtures_from_total_and_items():
    """B-578-01: headline, pager total and rows must use ONE denominator.

    Previously fixtures were excluded from `real_product_missing` but still counted in
    `total` and returned as rows, so the card said 402 while the table said 410.
    """
    await _seed_fixture_and_bulk()
    res = await svc.list_exceptions("missing_copy", lifecycle_status="ALL")
    app = res["applicability"]
    assert res["include_test_fixtures"] is False
    # total is now real products only, and reconciles exactly with the split
    assert res["total"] == 2
    assert app["active_missing"] + app["archived_missing"] == res["total"]
    assert app["real_product_missing"] == res["total"]
    # the quarantined set is still disclosed, not vanished
    assert app["test_fixture_excluded"] == 1
    # and no fixture row reaches the operational list
    assert "F1" not in {i["product_id"] for i in res["items"]}


async def test_exceptions_fixture_view_returns_only_fixtures_on_demand():
    await _seed_fixture_and_bulk()
    everything = await svc.list_exceptions(
        "missing_copy", lifecycle_status="ALL", include_test_fixtures=True)
    assert everything["total"] == 3
    assert "F1" in {i["product_id"] for i in everything["items"]}


async def test_exceptions_search_cannot_leak_a_fixture_into_the_default_list():
    await _seed_fixture_and_bulk()
    res = await svc.list_exceptions("missing_copy", lifecycle_status="ALL", q="Smoke")
    assert res["total"] == 0
    assert res["items"] == []
    # ...but it is still disclosed as quarantined
    assert res["applicability"]["test_fixture_excluded"] == 1


async def test_exceptions_pages_union_equals_real_product_cohort():
    await _seed_fixture_and_bulk()
    first = await svc.list_exceptions("missing_copy", lifecycle_status="ALL", limit=1, offset=0)
    total = first["total"]
    seen: list[str] = []
    for offset in range(0, total):
        page = await svc.list_exceptions(
            "missing_copy", lifecycle_status="ALL", limit=1, offset=offset)
        assert page["total"] == total          # pager total stable across pages
        seen.extend(i["product_id"] for i in page["items"])
    assert sorted(seen) == ["P2", "P3"]        # exactly the real products, no fixture
    assert len(set(seen)) == len(seen)         # no duplicates


async def test_exceptions_active_and_all_each_reconcile_independently():
    await _seed_fixture_and_bulk()
    for lifecycle in ("ACTIVE", "ALL"):
        res = await svc.list_exceptions("missing_copy", lifecycle_status=lifecycle)
        app = res["applicability"]
        assert app["active_missing"] + app["archived_missing"] == res["total"], lifecycle
        assert "F1" not in {i["product_id"] for i in res["items"]}, lifecycle


async def _seed_fixture_and_alias():
    """P1/P2/P3 real + F1 harness fixture + M1 merged-alias duplicate.

    M1 carries a REAL-looking title (so only the archived_reason marker, not the
    fixture title heuristic, excludes it) — it exercises the merged-alias arm.
    """
    await _seed_fixture_and_bulk()  # adds F1
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name,"
        " lifecycle_status, archived_reason, mapping_status, prompt_readiness_status, asset_status,"
        " created_at, updated_at)"
        " VALUES ('M1','Minyak Warisan Dup','Minyak Warisan Dup','Minyak Warisan Dup',"
        "'ARCHIVED','DUPLICATE_MERGED_TO_CANONICAL:P1','READY','READY','DOWNLOADED',"
        "'2026-01-01T00:00:00Z','2026-01-01T00:00:10Z')")
    await db.commit()


async def test_coverage_denominator_excludes_fixtures_and_merged_aliases():
    """Fix B: a coverage denominator counts only real catalogue — test fixtures
    (F1) and merged-alias duplicates (M1) are quarantined, exactly as the
    pi-quality / exceptions authorities do. Otherwise total_products at
    lifecycle=ALL overstates the real catalogue and every % reads low."""
    await _seed_fixture_and_alias()

    cov = await svc.copywriting_coverage("ALL")
    assert cov["total_products"] == 3          # P1, P2, P3 — NOT F1, NOT M1

    pic = await svc.product_intelligence_coverage("ALL")
    assert pic["total_products"] == 3

    prh = await svc.prompt_readiness_histogram("ALL")
    # F1 is MISSING_FIELDS and M1 is READY — neither may leak into the histogram.
    assert prh["READY"] == 1                    # P1 only
    assert prh["MISSING_FIELDS"] == 1           # P2 only
    assert prh["not_evaluated"] == 1            # P3 (null) only


async def test_coverage_active_default_is_unchanged_by_the_quarantine():
    """The real-only quarantine must not perturb the ACTIVE-default headline that
    operators see (F1 and M1 are both ARCHIVED, already outside ACTIVE)."""
    await _seed_fixture_and_alias()
    active = await svc.copywriting_coverage("ACTIVE")
    assert active["total_products"] == 2        # P1, P2
    assert active["coverage_pct"] == 50.0


def test_is_non_product_row_matches_fixtures_and_aliases():
    """Python mirror stays in lockstep with the two SQL predicates."""
    assert svc.is_non_product_row({"raw_product_title": "PR223 Smoke Approve 20260706"})
    assert svc.is_non_product_row({"id": "test_abc123"})
    assert svc.is_non_product_row({"archived_reason": "DUPLICATE_MERGED_TO_CANONICAL:P1"})
    # marker is case-insensitive (SQL uses UPPER(...))
    assert svc.is_non_product_row({"archived_reason": "duplicate_merged_to_canonical:xyz"})
    # a genuine product with a real title / a non-duplicate archive reason is kept
    assert not svc.is_non_product_row({"raw_product_title": "Minyak Warisan Cap Burung"})
    assert not svc.is_non_product_row({"archived_reason": "DISCONTINUED"})
    assert not svc.is_non_product_row({})


# ── scene-strategy contract observability ────────────────────────────────────
from agent.services import scene_contract_service as scs  # noqa: E402


def test_scene_contract_single_variant_is_complete_not_a_gap():
    """A sensitive product may legitimately have exactly ONE safe concrete scene.

    There is no minimum-variant threshold anywhere; completeness is about the grammar
    being concrete and usable, not numerous.
    """
    res = scs.evaluate_scene_contract({
        "matched_scene_strategy_id": "PET_CAGE_ACCESSORY",
        "scene_coverage_status": "COVERED",
        "fallback_used": 0,
    })
    assert res["scene_contract_status"] == "COMPLETE"
    assert res["scene_gap_reasons"] == []
    assert res["scene_variants_count"] == 1          # one variant, still complete
    assert res["scene_strategy_id"] == "PET_CAGE_ACCESSORY"


def test_scene_contract_gap_reasons_are_evidence_based():
    cases = [
        ({}, "NO_STRATEGY_BINDING"),
        ({"matched_scene_strategy_id": "GENERIC_FALLBACK",
          "scene_coverage_status": "COVERED"}, "GENERIC_FALLBACK"),
        ({"matched_scene_strategy_id": "NOT_A_REAL_STRATEGY",
          "scene_coverage_status": "COVERED"}, "STRATEGY_ID_NOT_IN_LIBRARY"),
        ({"matched_scene_strategy_id": "PET_CAGE_ACCESSORY",
          "scene_coverage_status": "PARTIAL"}, "PARTIAL_COVERAGE"),
        ({"matched_scene_strategy_id": "PET_CAGE_ACCESSORY",
          "scene_coverage_status": "COVERED", "fallback_used": 1}, "GENERIC_FALLBACK"),
    ]
    for taxonomy, expected in cases:
        res = scs.evaluate_scene_contract(taxonomy)
        assert res["scene_contract_status"] == "GAP", taxonomy
        assert expected in res["scene_gap_reasons"], (taxonomy, res["scene_gap_reasons"])


def test_scene_contract_reports_stale_fingerprint_without_hiding_the_binding():
    res = scs.evaluate_scene_contract(
        {"matched_scene_strategy_id": "PET_CAGE_ACCESSORY",
         "scene_coverage_status": "COVERED", "fallback_used": 0},
        fingerprint_stale=True)
    assert res["scene_contract_status"] == "GAP"
    assert res["scene_gap_reasons"] == ["STALE_PRODUCT_FINGERPRINT"]
    assert res["scene_strategy_id"] == "PET_CAGE_ACCESSORY"   # binding still reported


def test_scene_variants_count_is_variants_not_strategy_count():
    """One matched strategy id -> the number of scenes INSIDE it, never 1-per-strategy."""
    for sid in list(scs.COMPLETE_SCENE_STRATEGY_IDS)[:20]:
        entry = scs.SCENE_STRATEGIES[sid]
        expected = len(entry["allowed_scene_strategy"])
        assert scs.scene_variants_count(sid) == expected
        assert expected >= 1
    assert scs.scene_variants_count("NOT_A_REAL_STRATEGY") == 0


def test_scene_gap_sql_predicate_agrees_with_the_python_evaluator():
    """The SQL mirror and the pure evaluator must never disagree on structural gaps."""
    import sqlite3
    from agent.services.reporting_service import _PRODUCT_BASE
    rows = [
        # (id, strategy, coverage, fallback) -> expected structural gap?
        ("S1", "PET_CAGE_ACCESSORY", "COVERED", 0, False),
        ("S2", "GENERIC_FALLBACK", "FALLBACK_ONLY", 1, True),
        ("S3", None, None, 0, True),
        ("S4", "NOT_A_REAL_STRATEGY", "COVERED", 0, True),
        ("S5", "PET_CAGE_ACCESSORY", "PARTIAL", 0, True),
    ]
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE p (id TEXT)")
    con.execute("CREATE TABLE t (product_id TEXT, matched_scene_strategy_id TEXT,"
                " scene_coverage_status TEXT, fallback_used INTEGER)")
    for pid, sid, cov, fb, _exp in rows:
        con.execute("INSERT INTO p VALUES (?)", (pid,))
        con.execute("INSERT INTO t VALUES (?,?,?,?)", (pid, sid, cov, fb))
    pred = scs.scene_gap_sql_predicate("t")
    sql_gaps = {r[0] for r in con.execute(
        f"SELECT p.id FROM p LEFT JOIN t ON t.product_id = p.id WHERE {pred}")}
    con.close()
    py_gaps = {
        pid for pid, sid, cov, fb, _exp in rows
        if scs.evaluate_scene_contract({
            "matched_scene_strategy_id": sid, "scene_coverage_status": cov,
            "fallback_used": fb})["scene_contract_status"] == "GAP"
    }
    expected = {pid for pid, _s, _c, _f, exp in rows if exp}
    assert sql_gaps == py_gaps == expected


async def test_exception_rows_carry_the_scene_contract_fields():
    await _seed()
    res = await svc.list_exceptions("missing_copy", lifecycle_status="ALL")
    assert res["items"], "expected at least one row"
    for item in res["items"]:
        for field in ("scene_strategy_id", "scene_variants_count", "scene_coverage",
                      "scene_contract_status", "scene_gap_reasons"):
            assert field in item, field


async def test_scene_strategy_gaps_is_a_real_exception_kind():
    await _seed()
    assert "scene_strategy_gaps" in svc.EXCEPTION_KINDS
    res = await svc.list_exceptions("scene_strategy_gaps", lifecycle_status="ALL")
    app = res["applicability"]
    # the card total must reconcile with its own split, like every other bucket
    assert app["active_missing"] + app["archived_missing"] == res["total"]
    # and every returned row must actually be a gap
    for item in res["items"]:
        assert item["scene_contract_status"] == "GAP", item["product_id"]


# ── B-581-01 / B-581-02: fingerprint staleness must reach BOTH the KPI and the rows ──
async def _make_stale(product_id: str):
    """Corrupt the stored taxonomy fingerprint so the product is genuinely stale."""
    db = await get_db()
    await db.execute(
        "UPDATE product_strategy_taxonomy SET product_fingerprint='DEFINITELY_NOT_CURRENT'"
        " WHERE product_id=?", (product_id,))
    await db.commit()


async def _make_scene_complete(product_id: str):
    """Give a product a real, fully-covered scene binding.

    The insert trigger seeds a placeholder with no scene strategy, so a freshly seeded
    product is already a STRUCTURAL gap — it has to be made genuinely complete first for a
    staleness-only assertion to mean anything.
    """
    db = await get_db()
    from agent.services.product_strategy_taxonomy_service import product_strategy_fingerprint
    cur = await db.execute("SELECT * FROM product WHERE id=?", (product_id,))
    product = dict(await cur.fetchone())
    await cur.close()
    await db.execute(
        "UPDATE product_strategy_taxonomy SET matched_scene_strategy_id='PET_CAGE_ACCESSORY',"
        " scene_coverage_status='COVERED', fallback_used=0, product_fingerprint=?"
        " WHERE product_id=?",
        (product_strategy_fingerprint(product), product_id))
    await db.commit()


async def test_stale_fingerprint_is_counted_by_the_scene_gap_kpi():
    """B-581-01: a stale binding cannot be trusted, so it must reach the card total.

    The predicate previously covered structural gaps only, so a stale product was counted
    as COMPLETE.
    """
    await _seed()
    await _make_scene_complete("P1")   # P1 is now genuinely COMPLETE
    before = await svc.list_exceptions("scene_strategy_gaps", lifecycle_status="ALL")
    assert "P1" not in {i["product_id"] for i in before["items"]}
    await _make_stale("P1")
    after = await svc.list_exceptions("scene_strategy_gaps", lifecycle_status="ALL")
    assert after["total"] == before["total"] + 1
    assert "P1" in {i["product_id"] for i in after["items"]}


async def test_stale_fingerprint_reaches_the_actual_reporting_row():
    """B-581-02: production rows previously always used the evaluator default (False).

    Exercises the real list_exceptions path, not a direct evaluate_scene_contract call.
    """
    await _seed()
    await _make_scene_complete("P1")
    await _make_stale("P1")
    res = await svc.list_exceptions("scene_strategy_gaps", lifecycle_status="ALL")
    row = next(i for i in res["items"] if i["product_id"] == "P1")
    assert row["scene_contract_status"] == "GAP"
    assert "STALE_PRODUCT_FINGERPRINT" in row["scene_gap_reasons"]
    # the binding itself stays visible — staleness annotates, it does not blank the row
    assert row["scene_strategy_id"] is not None


async def test_no_stale_product_is_ever_reported_complete():
    await _seed()
    await _make_scene_complete("P1")
    await _make_stale("P1")
    for kind in ("missing_copy", "scene_strategy_gaps"):
        res = await svc.list_exceptions(kind, lifecycle_status="ALL")
        for item in res["items"]:
            if item["product_id"] == "P1":
                assert item["scene_contract_status"] == "GAP", kind


async def test_scene_gap_kpi_equals_the_union_of_its_paginated_ids():
    """Card total must equal the union of every id the drill-down can actually reach."""
    await _seed()
    await _make_scene_complete("P1")
    await _make_stale("P1")
    first = await svc.list_exceptions("scene_strategy_gaps", lifecycle_status="ALL", limit=1)
    total = first["total"]
    seen: set[str] = set()
    for offset in range(total):
        page = await svc.list_exceptions(
            "scene_strategy_gaps", lifecycle_status="ALL", limit=1, offset=offset)
        assert page["total"] == total
        seen |= {i["product_id"] for i in page["items"]}
    assert len(seen) == total          # no duplicates, no gaps
    app = first["applicability"]
    assert app["active_missing"] + app["archived_missing"] == total


async def test_structural_and_stale_gaps_deduplicate():
    """A product that is BOTH structurally broken and stale counts once, with both reasons."""
    await _seed()
    await _make_stale("P2")            # P2 already has the generic-fallback placeholder
    res = await svc.list_exceptions("scene_strategy_gaps", lifecycle_status="ALL")
    ids = [i["product_id"] for i in res["items"]]
    assert ids.count("P2") == 1
    row = next(i for i in res["items"] if i["product_id"] == "P2")
    assert "STALE_PRODUCT_FINGERPRINT" in row["scene_gap_reasons"]
    assert len(row["scene_gap_reasons"]) >= 2


# ── BOSMAX-07H: derived intelligence stage in the drill-down ─────────────────
# The `missing_intelligence` headline still means "no approved snapshot". These tests pin
# that the stage columns/breakdown/filters ride along WITHOUT moving that predicate, and
# that collapsing the (non-unique) draft/snapshot sidecars cannot inflate any count.

async def _add_draft(product_id: str, draft_id: str, *, updated_at: str,
                     review_status: str = "DRAFT", claim_gate: str = "PASS",
                     blocked: str = "[]", risk: str = "LOW"):
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_review_draft "
        "(draft_id, product_id, review_status, claim_gate, claim_risk_level, "
        " blocked_claims_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (draft_id, product_id, review_status, claim_gate, risk, blocked,
         "2026-01-01T00:00:00Z", updated_at),
    )
    await db.commit()


async def test_multiple_drafts_and_snapshots_never_inflate_any_kpi():
    """Regression guard: neither sidecar is 1:1 with product (live data holds up to 7
    drafts and 5 snapshots for one product). A naive LEFT JOIN fans out and silently
    inflates `total` for EVERY exception kind."""
    await _seed()
    db = await get_db()
    before = {k: (await svc.list_exceptions(k, lifecycle_status="ALL", limit=1))["total"]
              for k in ("missing_copy", "missing_intelligence", "mapping_blocked",
                        "missing_image", "prompt_not_ready")}
    # P2 has no snapshot (so it is IN the missing_intelligence cohort); give it 3 drafts.
    # B-586-04: a product may hold many drafts but only ONE of them may be open, so the
    # superseded history carries the older two. The fan-out this test guards against is
    # caused by the ROW COUNT on the join, which is unchanged at 3.
    for i, ts in enumerate(("2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z",
                            "2026-02-03T00:00:00Z")):
        await _add_draft("P2", f"d{i}", updated_at=ts,
                         review_status="DRAFT" if i == 2 else "SUPERSEDED")
    # P1 already has one snapshot; add two more superseded versions.
    for i in (2, 3):
        await db.execute(
            "INSERT INTO product_intelligence_snapshot (snapshot_id, product_id, version,"
            " status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (f"sn1v{i}", "P1", i, "APPROVED", "2026-01-01T00:00:00Z",
             f"2026-02-0{i}T00:00:00Z"))
    await db.commit()

    after = {k: (await svc.list_exceptions(k, lifecycle_status="ALL", limit=1))["total"]
             for k in before}
    assert after == before, f"sidecar fan-out inflated a KPI: {before} -> {after}"

    page = await svc.list_exceptions("missing_intelligence", lifecycle_status="ALL", limit=50)
    ids = [i["product_id"] for i in page["items"]]
    assert len(ids) == len(set(ids)), "a product appeared more than once in the drill-down"


async def test_latest_draft_wins_for_the_row_stage():
    await _seed()
    # The older draft is SUPERSEDED — B-586-04 allows only one open draft per product,
    # and being superseded is exactly what "the row it must not read" now looks like.
    await _add_draft("P2", "old", updated_at="2026-02-01T00:00:00Z",
                     review_status="SUPERSEDED")
    await _add_draft("P2", "new", updated_at="2026-02-09T00:00:00Z",
                     review_status="NEEDS_REVISION",
                     claim_gate="CLAIM_REVIEW_REQUIRED")
    page = await svc.list_exceptions("missing_intelligence", lifecycle_status="ALL", limit=50)
    row = next(i for i in page["items"] if i["product_id"] == "P2")
    assert row["draft_id"] == "new"
    # the newest draft's GATE decides the stage, not the superseded one
    assert row["intelligence_stage"] == "CLAIM_REVIEW_REQUIRED"


async def test_stage_breakdown_sums_to_total_and_covers_every_stage():
    await _seed()
    await _add_draft("P2", "d1", updated_at="2026-02-01T00:00:00Z")
    page = await svc.list_exceptions("missing_intelligence", lifecycle_status="ALL", limit=50)
    assert set(page["stage_breakdown"]) == set(svc.INTELLIGENCE_STAGES)
    assert sum(page["stage_breakdown"].values()) == page["total"]


async def test_stage_breakdown_is_absent_for_other_kinds():
    await _seed()
    assert (await svc.list_exceptions("missing_copy", lifecycle_status="ALL"))["stage_breakdown"] == {}


async def test_creating_a_draft_does_not_move_the_headline():
    """The whole reason the stage panel exists: preparation is invisible in the KPI."""
    await _seed()
    before = (await svc.list_exceptions("missing_intelligence", lifecycle_status="ALL"))["total"]
    await _add_draft("P2", "d1", updated_at="2026-02-01T00:00:00Z")
    after = await svc.list_exceptions("missing_intelligence", lifecycle_status="ALL")
    assert after["total"] == before
    assert after["stage_breakdown"]["NO_DRAFT"] == before - 1


async def test_stage_filter_keeps_headline_and_applicability_reconciled():
    await _seed()
    await _add_draft("P2", "d1", updated_at="2026-02-01T00:00:00Z",
                     blocked='["cures acne"]', claim_gate="BLOCKED")
    page = await svc.list_exceptions("missing_intelligence", lifecycle_status="ALL",
                                     limit=50, intelligence_stage="CLAIM_BLOCKED")
    ap = page["applicability"]
    assert page["total"] == ap["active_missing"] + ap["archived_missing"]
    assert [i["product_id"] for i in page["items"]] == ["P2"]
    assert page["items"][0]["claim_reasons"] == ["cures acne"]


async def test_unknown_intelligence_stage_is_rejected():
    await _seed()
    try:
        await svc.list_exceptions("missing_intelligence", intelligence_stage="DROP TABLE")
    except ValueError as exc:
        assert "UNKNOWN_INTELLIGENCE_STAGE" in str(exc)
    else:
        raise AssertionError("an unknown stage must not reach SQL")


async def test_copy_blocked_filter_tracks_the_snapshot_relation():
    await _seed()
    blocked = await svc.list_exceptions("missing_intelligence", lifecycle_status="ALL",
                                        limit=50, copy_blocked=True)
    assert blocked["total"] == blocked["applicability"]["real_product_missing"]
    assert all(i["copy_blocked"] for i in blocked["items"])
    # every missing-intelligence row is copy-blocked by definition, so the inverse is empty
    unblocked = await svc.list_exceptions("missing_intelligence", lifecycle_status="ALL",
                                          copy_blocked=False)
    assert unblocked["total"] == 0


import pytest  # noqa: E402
from agent.db import crud  # noqa: E402

# ── Mission-08D: PI quality classification ───────────────────────────────────
from agent.models.product_intelligence_review_draft import (  # noqa: E402
    ProductIntelligenceFieldDispositionRequest as _DispReq,
    ProductIntelligenceReviewDraftApproveRequest as _ApproveReq,
    ProductIntelligenceReviewDraftCreateRequest as _CreateReq,
)
from agent.services import product_intelligence_review_draft_service as _draft_svc  # noqa: E402


def _pi_request(**kw) -> _CreateReq:
    base = {
        "product_description": "Beg hadiah transparent 24cm.",
        "benefits_json": ["nampak kemas"],
        "usp_json": ["tingkap depan jernih"],
        "usage_text": "Isi hadiah dan ikat reben.",
        "ingredients_text": "PVC + fabrik",
        "warnings_text": "Jauhkan dari api.",
        "target_customer_text": "Ibu bapa dan guru.",
        "allowed_claims_json": ["reka bentuk transparent"],
        "source_urls_json": {"source_url": "https://example.com/p"},
        "image_evidence_json": {"image_url": "https://example.com/i.jpg"},
        "buyer_persona_snapshot_json": {"audience": "ibu bapa", "pains": ["masa suntuk"]},
        "copy_strategy_summary_json": {"angles": ["praktikal"]},
        "created_by": "op",
    }
    base.update(kw)
    return _CreateReq(**base)


async def _mk(name, category="Stationery & Gifts"):
    return await crud.create_product(
        raw_product_title=name, source="MANUAL", product_display_name=name,
        category=category)


@pytest.mark.asyncio
async def test_pi_quality_summary_partitions_exactly_and_classifies_all_four_ways():
    # FULLY_COMPLETE: everything present, straight approval
    full = await _mk("PIQ Full")
    d1 = await _draft_svc.create_review_draft(full["id"], _pi_request())
    await _draft_svc.approve_review_draft(d1.draft_id, _ApproveReq(approved_by="op"))

    # APPROVED_WITH_GOVERNED_ABSENCE: knowledge gaps resolved by dispositions
    governed = await _mk("PIQ Governed")
    d2 = await _draft_svc.create_review_draft(
        governed["id"],
        _pi_request(usage_text="", ingredients_text="", warnings_text=""))
    for field in ("usage_text", "ingredients_text", "warnings_text"):
        await _draft_svc.set_field_disposition(
            d2.draft_id,
            _DispReq(field_name=field, disposition="NOT_STATED_IN_SOURCE",
                     reviewed_by="owner", reviewer_note="Sumber tidak menyatakannya."))
    await _draft_svc.approve_review_draft(d2.draft_id, _ApproveReq(approved_by="owner"))

    # A newer OPEN draft is mutable review state and must never leak into the
    # immutable approved-snapshot drill-down.
    mutable = await _draft_svc.create_review_draft(
        governed["id"],
        _pi_request(usage_text="", ingredients_text="", warnings_text=""),
    )
    await _draft_svc.set_field_disposition(
        mutable.draft_id,
        _DispReq(
            field_name="ingredients_text",
            disposition="REQUIRES_EXTERNAL_EVIDENCE",
            reviewed_by="later-reviewer",
            reviewer_note="Open-draft evidence is still pending.",
        ),
    )


    # LEGACY_APPROVED_INCOMPLETE: the historical copy-flag shape — incomplete, NO
    # dispositions, frozen MISSING_REQUIRED_FIELDS
    legacy = await _mk("PIQ Legacy")
    d3 = await _draft_svc.create_review_draft(
        legacy["id"],
        _pi_request(usage_text="", ingredients_text="", warnings_text=""))
    await _draft_svc.approve_review_draft(
        d3.draft_id,
        _ApproveReq(approved_by="op", allow_incomplete_product_knowledge=True))

    # MISSING_APPROVED_INTELLIGENCE: a product with no snapshot at all
    await _mk("PIQ Missing")
    archived_missing = await _mk("PIQ Archived Missing")
    await crud.update_product(
        archived_missing["id"], lifecycle_status="ARCHIVED")

    summary = await svc.product_intelligence_quality_summary()
    classes = summary["classes"]
    assert sum(c["total"] for c in classes.values()) == summary["total_real_products"]
    assert classes["FULLY_COMPLETE"]["total"] >= 1
    assert classes["APPROVED_WITH_GOVERNED_ABSENCE"]["total"] >= 1
    assert classes["LEGACY_APPROVED_INCOMPLETE"]["total"] >= 1
    assert classes["MISSING_APPROVED_INTELLIGENCE"]["total"] >= 1
    assert classes["MISSING_APPROVED_INTELLIGENCE"]["archived"] >= 1
    assert (
        classes["MISSING_APPROVED_INTELLIGENCE"]["total"]
        == classes["MISSING_APPROVED_INTELLIGENCE"]["active"]
        + classes["MISSING_APPROVED_INTELLIGENCE"]["archived"]
    )

    # The drill-down agrees with the headline: governed kind returns the governed
    # product, with its dispositions and per-row class attached.
    listing = await svc.list_exceptions("pi_governed_absence", lifecycle_status="ALL")
    ids = {item["product_id"] for item in listing["items"]}
    assert governed["id"] in ids
    assert listing["total"] == classes["APPROVED_WITH_GOVERNED_ABSENCE"]["total"]
    row = next(item for item in listing["items"] if item["product_id"] == governed["id"])
    assert row["pi_quality"] == "APPROVED_WITH_GOVERNED_ABSENCE"
    fields = {d["field_name"] for d in row["governed_dispositions"]}
    assert fields >= {"usage_text", "ingredients_text", "warnings_text"}
    assert all(d["reviewer_note"] for d in row["governed_dispositions"])

    assert {d["disposition"] for d in row["governed_dispositions"]} == {
        "NOT_STATED_IN_SOURCE"}
    assert {d["reviewed_by"] for d in row["governed_dispositions"]} == {"owner"}


    # legacy is NEVER relabelled governed
    legacy_listing = await svc.list_exceptions("pi_legacy_incomplete", lifecycle_status="ALL")
    legacy_ids = {item["product_id"] for item in legacy_listing["items"]}
    assert legacy["id"] in legacy_ids
    assert governed["id"] not in legacy_ids
    legacy_row = next(item for item in legacy_listing["items"]
                      if item["product_id"] == legacy["id"])
    assert legacy_row["pi_quality"] == "LEGACY_APPROVED_INCOMPLETE"
    assert legacy_row["governed_dispositions"] == []
