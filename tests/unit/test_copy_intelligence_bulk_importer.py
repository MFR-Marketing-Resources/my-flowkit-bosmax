"""Bulk COPYWRITING HUB -> review-DRAFT importer.

Pins the two properties that make this safe to run over hundreds of products:
  * MULTI-ANGLE, not monoculture — Pain Point + each Dream Outcome line become
    distinct angles (the whole reason this exists over the legacy single-pain
    seed-promotion path).
  * NEVER auto-approves, IDEMPOTENT — a product with an approved snapshot or a
    live draft is skipped; only-rejected or untouched products get a new DRAFT.
"""
import asyncio
import types

from agent.services import copy_intelligence_bulk_importer as bulk


# ---------------------------------------------------------------- pure logic

CP7 = {
    "source_row": 147,
    "source_product_name": "CP7 Pink Bloom",
    "target_avatar": "Wanita 18-40 mahu wangian tahan lama",
    "pain_point": "Minyak wangi cepat hilang, tak tahan lama",
    "emotion_trigger": "feminin, yakin, cari hadiah",
    "dream_outcome": "Wangian floral amber tahan lama\nSet kotak hadiah cantik\nAuthentic tempatan",
    "key_ingredients_features": "Thyme, Mawar, Saffron, Amber",
    "hook_script": "Nak wangian tahan lama?",
    "cta_script": "Wangi feminin, add to cart!",
}


def test_derive_angles_are_multi_and_ordered():
    angles = bulk.derive_angle_themes(CP7)
    # pain point first, then each distinct dream line -> 4 angles, not 1
    assert angles[0] == "Minyak wangi cepat hilang, tak tahan lama"
    assert "Wangian floral amber tahan lama" in angles
    assert "Set kotak hadiah cantik" in angles
    assert "Authentic tempatan" in angles
    assert len(angles) == 4


def test_derive_angles_dedupes_repeated_theme():
    rec = {"pain_point": "Sendi sakit", "dream_outcome": "Sendi sakit\nBoleh jalan jauh"}
    angles = bulk.derive_angle_themes(rec)
    assert angles == ["Sendi sakit", "Boleh jalan jauh"]  # duplicate collapsed


def test_derive_angles_capped_at_max():
    dream = "\n".join(f"Dream theme number {i}" for i in range(12))
    rec = {"pain_point": "Pain theme one", "dream_outcome": dream}
    assert len(bulk.derive_angle_themes(rec)) == bulk.MAX_ANGLES


def test_derive_angles_drops_tiny_tokens_and_empty():
    rec = {"pain_point": "abc", "dream_outcome": "   \nReal theme here"}
    assert bulk.derive_angle_themes(rec) == ["Real theme here"]
    assert bulk.derive_angle_themes({}) == []


def test_build_persona_shape():
    p = bulk.build_persona(CP7)
    assert p["audience"].startswith("Wanita")
    assert len(p["pains"]) == 4                       # angles
    assert p["desires"] == [
        "Wangian floral amber tahan lama", "Set kotak hadiah cantik", "Authentic tempatan",
    ]
    assert p["triggers"] == ["feminin", "yakin", "cari hadiah"]  # split on commas


def test_build_persona_defaults_tone_and_pronoun():
    p = bulk.build_persona({"target_avatar": "x", "pain_point": "Some pain here"})
    assert p["tone"] and p["pronoun"]                 # never empty


def test_knowledge_leaves_claim_critical_fields_empty():
    k = bulk.build_knowledge_fields(CP7)
    assert k["product_description"].startswith("CP7 Pink Bloom")
    assert k["benefits_json"] and k["usp_json"]
    # the claim-critical fields are DELIBERATELY not populated by the importer
    for banned in ("ingredients_text", "usage_text", "warnings_text"):
        assert banned not in k


# ------------------------------------------------------- async import harness

def _draft(status="NEEDS_REVISION"):
    return types.SimpleNamespace(draft_id="d1", review_status=status)


class FakeState:
    """Controls catalog, existing snapshots/drafts, and records writes."""

    def __init__(self, products, snapshots=None, drafts=None):
        self.products = products
        self.snapshots = snapshots or {}      # pid -> snapshot dict
        self.drafts = drafts or {}            # pid -> list[review_status]
        self.created = []                     # (pid, request)
        self.approved = []                    # must stay empty

    async def list_products(self, *a, **k):
        return self.products

    async def get_latest_approved_product_intelligence_snapshot(self, pid):
        return self.snapshots.get(pid)

    async def list_product_intelligence_review_drafts(self, *, product_id, limit=20):
        return [{"review_status": s} for s in self.drafts.get(product_id, [])]

    async def create_review_draft(self, pid, request):
        self.created.append((pid, request))
        return _draft()


def _patch(monkeypatch, state, records):
    import agent.db.crud as crud
    import agent.services.product_intelligence_review_draft_service as draft_svc

    monkeypatch.setattr(bulk, "parse_copy_intelligence_hub", lambda _p: records)
    monkeypatch.setattr(crud, "list_products", state.list_products)
    monkeypatch.setattr(
        crud, "get_latest_approved_product_intelligence_snapshot",
        state.get_latest_approved_product_intelligence_snapshot,
    )
    monkeypatch.setattr(
        crud, "list_product_intelligence_review_drafts",
        state.list_product_intelligence_review_drafts,
    )
    monkeypatch.setattr(draft_svc, "create_review_draft", state.create_review_draft)


def _products(*names):
    return [{"id": f"pid_{i}", "product_display_name": n} for i, n in enumerate(names)]


def test_matches_by_name_and_creates_multiangle_draft(monkeypatch):
    state = FakeState(_products("CP7 Pink Bloom"))
    _patch(monkeypatch, state, [CP7])
    rep = asyncio.run(bulk.import_hub_to_drafts("x.xlsx", dry_run=False))
    assert rep["matched"] == 1 and rep["created"] == 1
    assert len(state.created) == 1
    pid, request = state.created[0]
    assert pid == "pid_0"
    # the draft carries the multi-angle persona
    assert len(request.buyer_persona_snapshot_json["pains"]) == 4
    assert state.approved == []                       # never approves


def test_unmatched_rows_are_counted_not_created(monkeypatch):
    state = FakeState(_products("CP7 Pink Bloom"))
    ghost = {**CP7, "source_product_name": "Ghost Product Not In Catalog"}
    _patch(monkeypatch, state, [ghost])
    rep = asyncio.run(bulk.import_hub_to_drafts("x.xlsx", dry_run=False))
    assert rep["unmatched"] == 1 and rep["matched"] == 0 and rep["created"] == 0
    assert state.created == []


def test_idempotent_skips_approved_snapshot(monkeypatch):
    state = FakeState(_products("CP7 Pink Bloom"), snapshots={"pid_0": {"version": 1}})
    _patch(monkeypatch, state, [CP7])
    rep = asyncio.run(bulk.import_hub_to_drafts("x.xlsx", dry_run=False))
    assert rep["matched"] == 1 and rep["skipped_existing"] == 1 and rep["created"] == 0
    assert state.created == []


def test_idempotent_skips_live_draft_but_not_rejected(monkeypatch):
    products = _products("Alpha Product", "Beta Product")
    # pid_0 has a live (NEEDS_REVISION) draft -> skip; pid_1 only REJECTED -> create
    state = FakeState(products, drafts={"pid_0": ["NEEDS_REVISION"], "pid_1": ["REJECTED"]})
    recs = [
        {**CP7, "source_product_name": "Alpha Product"},
        {**CP7, "source_product_name": "Beta Product"},
    ]
    _patch(monkeypatch, state, recs)
    rep = asyncio.run(bulk.import_hub_to_drafts("x.xlsx", dry_run=False))
    assert rep["skipped_existing"] == 1 and rep["created"] == 1
    assert [pid for pid, _ in state.created] == ["pid_1"]


def test_dry_run_writes_nothing(monkeypatch):
    state = FakeState(_products("CP7 Pink Bloom"))
    _patch(monkeypatch, state, [CP7])
    rep = asyncio.run(bulk.import_hub_to_drafts("x.xlsx", dry_run=True))
    assert rep["dry_run"] is True
    assert rep["created"] == 1        # would-create count
    assert state.created == []        # but nothing persisted
    assert rep["samples"] and rep["samples"][0]["angles"]


def test_rows_without_angles_are_counted_not_created(monkeypatch):
    state = FakeState(_products("Blank Product"))
    blank = {"source_product_name": "Blank Product"}   # no pain/dream -> no angles
    _patch(monkeypatch, state, [blank])
    rep = asyncio.run(bulk.import_hub_to_drafts("x.xlsx", dry_run=False))
    assert rep["rows_without_angles"] == 1 and rep["created"] == 0
    assert state.created == []


def test_limit_caps_created(monkeypatch):
    products = _products("P one", "P two", "P three")
    recs = [{**CP7, "source_product_name": n} for n in ("P one", "P two", "P three")]
    state = FakeState(products)
    _patch(monkeypatch, state, recs)
    rep = asyncio.run(bulk.import_hub_to_drafts("x.xlsx", dry_run=False, limit=2))
    assert rep["created"] == 2 and len(state.created) == 2


def test_one_bad_row_does_not_abort_the_batch(monkeypatch):
    products = _products("Good One", "Bad One", "Good Two")
    recs = [{**CP7, "source_product_name": n} for n in ("Good One", "Bad One", "Good Two")]
    state = FakeState(products)
    _patch(monkeypatch, state, recs)

    real_create = state.create_review_draft

    async def flaky(pid, request):
        if pid == "pid_1":
            raise RuntimeError("simulated draft failure")
        return await real_create(pid, request)

    import agent.services.product_intelligence_review_draft_service as draft_svc
    monkeypatch.setattr(draft_svc, "create_review_draft", flaky)

    rep = asyncio.run(bulk.import_hub_to_drafts("x.xlsx", dry_run=False))
    assert rep["created"] == 2 and rep["skipped_existing"] == 1   # bad row -> skipped
