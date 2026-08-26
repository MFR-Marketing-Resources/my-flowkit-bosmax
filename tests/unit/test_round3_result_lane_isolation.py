"""Round 3 — result identity / cross-lane isolation regression.

The AQUABLANCE incident began as a *misattribution*: a HYBRID one-door product
clip surfaced in the FACELESS rail because results were fetched by time only.
The durable fix is that every results lookup is scoped by ``surface_lane`` so a
HYBRID request can only ever return HYBRID lineage — never FACELESS or MONTAGE.

This locks the DB-level isolation (`crud.list_generation_results(surface_lane=…)`)
so the contamination cannot silently return. PROVIDER-FREE.
"""
from agent.db import crud

# Unique ids so the shared (not-always-wiped) Windows test DB can't cross-talk.
_STAFF = "staff_r3iso"
_HYB = "r3iso-hybrid-final"
_FAC = "r3iso-faceless-final"
_MON = "r3iso-montage-final"


async def _seed_one_per_lane():
    await crud.insert_generation_result(
        _HYB, job_id="r3iso-hyb", staff_id=_STAFF, mode="F2V",
        artifact_kind="video", surface_lane="HYBRID", source_mode="HYBRID",
    )
    await crud.insert_generation_result(
        _FAC, job_id="r3iso-fac", staff_id=_STAFF, mode="F2V",
        artifact_kind="video", surface_lane="FACELESS", source_mode="FACELESS",
    )
    await crud.insert_generation_result(
        _MON, job_id="r3iso-mon", staff_id=_STAFF, mode="F2V",
        artifact_kind="video", surface_lane="MONTAGE", source_mode="MONTAGE",
    )


async def test_hybrid_request_returns_only_hybrid_lineage():
    await _seed_one_per_lane()
    rows = await crud.list_generation_results(surface_lane="HYBRID", limit=200)
    ids = {r["media_id"] for r in rows}
    assert _HYB in ids
    assert _FAC not in ids and _MON not in ids     # no cross-lane contamination
    assert all(r["surface_lane"] == "HYBRID" for r in rows)


async def test_faceless_request_returns_only_faceless_lineage():
    await _seed_one_per_lane()
    rows = await crud.list_generation_results(surface_lane="FACELESS", limit=200)
    ids = {r["media_id"] for r in rows}
    assert _FAC in ids
    assert _HYB not in ids and _MON not in ids
    assert all(r["surface_lane"] == "FACELESS" for r in rows)


async def test_montage_request_returns_only_montage_lineage():
    await _seed_one_per_lane()
    rows = await crud.list_generation_results(surface_lane="MONTAGE", limit=200)
    ids = {r["media_id"] for r in rows}
    assert _MON in ids
    assert _HYB not in ids and _FAC not in ids
    assert all(r["surface_lane"] == "MONTAGE" for r in rows)


async def test_surface_lane_filter_is_case_insensitive():
    await _seed_one_per_lane()
    rows = await crud.list_generation_results(surface_lane="hybrid", limit=200)
    ids = {r["media_id"] for r in rows}
    assert _HYB in ids                              # lowercase still isolates
    assert _FAC not in ids and _MON not in ids


async def test_unscoped_request_is_shared_which_is_why_the_ui_must_scope():
    """Without a surface_lane the list is intentionally cross-lane — this is the
    exact reason the UI rails must always pass their own surface_lane. If this
    ever became lane-scoped by default the isolation contract would be hollow."""
    await _seed_one_per_lane()
    rows = await crud.list_generation_results(kind="video", limit=200)
    ids = {r["media_id"] for r in rows}
    assert {_HYB, _FAC, _MON}.issubset(ids)
