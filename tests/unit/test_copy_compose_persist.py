"""compose_and_persist — pool → COPY_REVIEW_REQUIRED copy_set rows.

The capstone: it must persist composed copy through the SAME lifecycle as
AI-assist copy (review-required, dedupe-checked, claim-scanned) and never
auto-approve.
"""
import asyncio
import json

from agent.services import copy_component_service as comp
from agent.services import copy_composer_service as svc


A1, A2 = "ang_colic0000001", "ang_aches0000002"
PRODUCT = {"id": "p1", "product_display_name": "Test Oil"}


class _Grounding:
    source = "APPROVED_SNAPSHOT"
    effective_route = "STEALTH"


def _c(cid, ctype, angle, content, status=comp.STATUS_APPROVED):
    return {
        "component_id": cid, "component_type": ctype, "angle_key": angle,
        "angle_label": "colic" if angle == A1 else "aches",
        "content": content, "status": status, "archived": 0, "usage_count": 0,
    }


def _pool(angle, tag):
    out = []
    for i in range(2):
        out += [_c(f"{tag}h{i}", comp.HOOK, angle, f"{tag} hook {i}"),
                _c(f"{tag}s{i}", comp.SUBHOOK, angle, f"{tag} subhook {i}"),
                _c(f"{tag}u{i}", comp.USP_SET, angle, f'["{tag} usp {i}"]'),
                _c(f"{tag}c{i}", comp.CTA, angle, f"{tag} cta {i}")]
    return out


FULL = _pool(A1, "colic") + _pool(A2, "aches")


class FakeCrud:
    """In-memory stand-in for the crud module the service imports."""

    def __init__(self, pool, product=PRODUCT):
        self.pool = pool
        self.product = product
        self.created: list[dict] = []
        self.by_dedupe: dict[str, dict] = {}

    async def get_product(self, pid):
        return self.product if pid == self.product["id"] else None

    async def list_copy_components_for_product(self, pid):
        return self.pool

    async def list_copy_sets_for_product(self, pid):
        return list(self.created)

    async def find_copy_set_by_dedupe_key(self, key):
        return self.by_dedupe.get(key)

    async def create_copy_set(self, product_id, **kw):
        row = {"copy_set_id": f"cs{len(self.created)}", "product_id": product_id, **kw}
        self.created.append(row)
        if kw.get("dedupe_key"):
            self.by_dedupe[kw["dedupe_key"]] = row
        return row


def _run(pool, count, monkeypatch, **kw):
    fake = FakeCrud(pool)
    import agent.db.crud as real_crud

    for name in ("get_product", "list_copy_components_for_product",
                 "list_copy_sets_for_product", "find_copy_set_by_dedupe_key",
                 "create_copy_set"):
        monkeypatch.setattr(real_crud, name, getattr(fake, name))

    import agent.services.copy_grounding_service as cgs

    async def _grounding(_p):
        return _Grounding()

    monkeypatch.setattr(cgs, "resolve_copy_grounding", _grounding)
    out = asyncio.run(svc.compose_and_persist("p1", count, **kw))
    return out, fake


def test_persists_review_required_copy_sets(monkeypatch):
    out, fake = _run(FULL, 8, monkeypatch)
    assert out["created"] == 8
    assert len(fake.created) == 8
    assert all(r["status"] == "COPY_REVIEW_REQUIRED" for r in fake.created)
    assert all(r["source"] == svc.SOURCE_COMPONENT_COMPOSER for r in fake.created)


def test_never_auto_approved(monkeypatch):
    _, fake = _run(FULL, 8, monkeypatch)
    assert not any(r["status"] == "COPY_APPROVED" for r in fake.created)


def test_dry_run_writes_nothing(monkeypatch):
    out, fake = _run(FULL, 8, monkeypatch, dry_run=True)
    assert out["dry_run"] is True
    assert out["created"] == 0
    assert fake.created == []
    assert len(out["items"]) == 8  # preview still returned


def test_usp_set_is_persisted_as_json_list(monkeypatch):
    _, fake = _run(FULL, 1, monkeypatch)
    usp = json.loads(fake.created[0]["usp_set_json"])
    assert isinstance(usp, list) and usp


def test_provenance_records_components_and_fingerprint(monkeypatch):
    _, fake = _run(FULL, 1, monkeypatch)
    prov = json.loads(fake.created[0]["provenance_json"])
    assert prov["composed"] is True
    assert len(prov["component_ids"]) == 4
    assert prov["combination_fingerprint"].startswith("cc_")
    assert prov["angle_key"] in (A1, A2)


def test_reruns_do_not_re_emit_prior_compositions(monkeypatch):
    fake = FakeCrud(FULL)
    import agent.db.crud as real_crud
    import agent.services.copy_grounding_service as cgs

    async def _grounding(_p):
        return _Grounding()

    for name in ("get_product", "list_copy_components_for_product",
                 "list_copy_sets_for_product", "find_copy_set_by_dedupe_key",
                 "create_copy_set"):
        monkeypatch.setattr(real_crud, name, getattr(fake, name))
    monkeypatch.setattr(cgs, "resolve_copy_grounding", _grounding)

    asyncio.run(svc.compose_and_persist("p1", 8))
    fp1 = {json.loads(r["provenance_json"])["combination_fingerprint"]
           for r in fake.created}
    asyncio.run(svc.compose_and_persist("p1", 8))
    # second batch fingerprints must be disjoint from the first
    fp2 = {json.loads(r["provenance_json"])["combination_fingerprint"]
           for r in fake.created[8:]}
    assert fp2 and not (fp1 & fp2)


def test_coverage_report_is_returned(monkeypatch):
    out, _ = _run(FULL, 8, monkeypatch)
    assert out["coverage"]["status"] == "COVERAGE_OK"
    assert out["coverage"]["angles_covered"] == 2


def test_empty_pool_is_safe(monkeypatch):
    out, fake = _run([], 5, monkeypatch)
    assert out["created"] == 0
    assert "NO_APPROVED_COMPONENTS_OR_ANGLES" in out["warnings"]
    assert fake.created == []


def test_unapproved_components_are_not_composed(monkeypatch):
    pool = _pool(A1, "colic") + [
        _c("bad", comp.HOOK, A1, "UNREVIEWED", status="COMPONENT_REVIEW_REQUIRED")
    ]
    _, fake = _run(pool, 16, monkeypatch)
    assert all("UNREVIEWED" not in r["hook"] for r in fake.created)


def test_product_not_found_raises(monkeypatch):
    import pytest
    fake = FakeCrud(FULL, product=PRODUCT)
    import agent.db.crud as real_crud

    async def _none(_pid):
        return None

    monkeypatch.setattr(real_crud, "get_product", _none)
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        asyncio.run(svc.compose_and_persist("nope", 5))
