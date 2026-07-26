import csv
from pathlib import Path

import pytest

from agent.services import scene_context_promotion_activation_service as svc
from agent.services import scene_context_registry as registry


def _resolved(template_id="SCN-BEAUTY-01", scene_name="Beauty — vanity alcove"):
    return {
        "product_id": "p1", "cluster": "Beauty", "fingerprint": "f" * 64,
        "review": {"review_id": "review-1"},
        "candidate": {"source_template_id": template_id, "row": {
            "SceneName": scene_name, "SceneCode": "UNTRUSTED_CLIENT_CODE",
            "BackgroundPrompt": "Background: soft daylight vanity alcove",
            "RouteFit": "IMAGE|VIDEO_SUPPORT", "SafetyBlock": "EMPTY_BACKGROUND_ONLY",
            "PromptV1": "Empty background plate only. No people and no product.",
            "usage_tags": "scene_context|cluster:beauty",
        }},
    }


@pytest.fixture(autouse=True)
def _reset_pool_cache():
    registry._load_pool.cache_clear()
    yield
    registry._load_pool.cache_clear()


def _bridge(monkeypatch, tmp_path):
    path = tmp_path / "bridge" / "SCENE_CONTEXT_POOL.csv"
    monkeypatch.setattr(registry, "_BRIDGE_FILE", path)
    return path


def _wire_success(monkeypatch, resolved):
    async def resolve(_product_id, _item):
        return resolved

    async def lookup(*_args):
        return None

    events = []

    async def append(items):
        events.extend(items)
        return items

    monkeypatch.setattr(svc, "_resolve_candidate", resolve)
    monkeypatch.setattr(svc.crud, "get_scene_context_promotion_activation_exact", lookup)
    monkeypatch.setattr(svc.crud, "append_scene_context_promotion_activation_events", append)
    return events


@pytest.mark.asyncio
async def test_confirmation_is_required_before_candidate_resolution(monkeypatch):
    called = False

    async def resolve(*_args):
        nonlocal called
        called = True
        return _resolved()

    monkeypatch.setattr(svc, "_resolve_candidate", resolve)
    with pytest.raises(svc.ActivationError, match="ACTIVATION_CONFIRMATION_REQUIRED"):
        await svc.activate("p1", [{"source_template_id": "x", "candidate_fingerprint": "y"}], "NO", "owner")
    assert called is False


@pytest.mark.asyncio
async def test_approved_candidate_activates_server_derived_row(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    events = _wire_success(monkeypatch, _resolved())
    result = await svc.activate("p1", [{"source_template_id": "SCN-BEAUTY-01", "candidate_fingerprint": "f" * 64}], svc.CONFIRMATION, "owner", "approved")

    assert result["activated_count"] == result["registry_mutations"] == 1
    item = result["items"][0]
    assert item["activation_status"] == "ACTIVE_IN_REGISTRY"
    assert item["generation_status"] == "NOT_GENERATED"
    assert item["scene_code"] != "UNTRUSTED_CLIENT_CODE"
    assert bridge.exists() and len(events) == 1
    with bridge.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    row = rows[-1]
    assert row["PrimaryCluster"] == row["CompatibleClusters"] == "Beauty"
    assert row["SourceTemplateId"] == "SCN-BEAUTY-01"
    assert row["CandidateFingerprint"] == "f" * 64
    assert row["approved_flag"] == "TRUE"


@pytest.mark.asyncio
async def test_exact_retry_is_idempotent_without_sync_or_new_ledger(monkeypatch, tmp_path):
    _bridge(monkeypatch, tmp_path)
    resolved = _resolved()
    existing = {"activation_id": "a1", "source_template_id": "SCN-BEAUTY-01", "candidate_fingerprint": "f" * 64, "reviewed_via_product_id": "p1", "cluster": "Beauty", "scene_code": "SCN_EXISTING", "scene_name": "Existing"}

    async def resolve(*_args): return resolved
    async def lookup(_template, _fingerprint, product_id=None): return existing if product_id == "p1" else existing

    monkeypatch.setattr(svc, "_resolve_candidate", resolve)
    monkeypatch.setattr(svc.crud, "get_scene_context_promotion_activation_exact", lookup)
    monkeypatch.setattr(registry, "sync_pool_csv", lambda _bytes: pytest.fail("must not sync idempotent retry"))
    result = await svc.activate("p1", [{"source_template_id": "SCN-BEAUTY-01", "candidate_fingerprint": "f" * 64}], svc.CONFIRMATION, "owner")
    assert result["idempotent_count"] == 1 and result["registry_mutations"] == 0
    assert result["items"][0]["scene_code"] == "SCN_EXISTING"


@pytest.mark.asyncio
async def test_bulk_is_selected_only_and_reserves_unique_codes(monkeypatch, tmp_path):
    _bridge(monkeypatch, tmp_path)
    one, two = _resolved("one", "Shared Name"), _resolved("two", "Shared Name")
    values = iter([one, two])

    async def resolve(*_args): return next(values)
    async def lookup(*_args): return None
    captured = []
    async def append(items): captured.extend(items); return items

    monkeypatch.setattr(svc, "_resolve_candidate", resolve)
    monkeypatch.setattr(svc.crud, "get_scene_context_promotion_activation_exact", lookup)
    monkeypatch.setattr(svc.crud, "append_scene_context_promotion_activation_events", append)
    monkeypatch.setattr(registry, "find_duplicate_scene", lambda *_args: None)
    result = await svc.activate("p1", [{"source_template_id": "one", "candidate_fingerprint": "1"}, {"source_template_id": "two", "candidate_fingerprint": "2"}], svc.CONFIRMATION, "owner")
    assert result["activated_count"] == 2
    assert len({event["scene_code"] for event in captured}) == 2


@pytest.mark.asyncio
async def test_invalid_bulk_item_writes_no_bridge_or_ledger(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    bridge.parent.mkdir(parents=True)
    before = b"existing bridge"
    bridge.write_bytes(before)
    called = False

    async def resolve(_product, item):
        nonlocal called
        called = True
        if item["source_template_id"] == "bad":
            raise svc.ActivationError("STALE_CANDIDATE_FINGERPRINT")
        return _resolved()

    monkeypatch.setattr(svc, "_resolve_candidate", resolve)
    with pytest.raises(svc.ActivationError, match="STALE_CANDIDATE_FINGERPRINT"):
        await svc.activate("p1", [{"source_template_id": "ok", "candidate_fingerprint": "x"}, {"source_template_id": "bad", "candidate_fingerprint": "y"}], svc.CONFIRMATION, "owner")
    assert called and bridge.read_bytes() == before


@pytest.mark.asyncio
async def test_ledger_failure_restores_prior_bridge_byte_for_byte(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    bridge.parent.mkdir(parents=True)
    before = registry._POOL_FILE.read_bytes()
    bridge.write_bytes(before)
    _wire_success(monkeypatch, _resolved())

    async def failed_append(_items):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(svc.crud, "append_scene_context_promotion_activation_events", failed_append)
    with pytest.raises(RuntimeError, match="db unavailable"):
        await svc.activate("p1", [{"source_template_id": "SCN-BEAUTY-01", "candidate_fingerprint": "f" * 64}], svc.CONFIRMATION, "owner")
    assert bridge.read_bytes() == before


@pytest.mark.asyncio
async def test_product_missing_has_precedence(monkeypatch):
    async def product(_id): return None
    monkeypatch.setattr(svc.crud, "get_product", product)
    with pytest.raises(svc.ActivationError, match="PRODUCT_NOT_FOUND"):
        await svc._resolve_candidate("missing", {"source_template_id": "unknown", "candidate_fingerprint": "x"})


def test_service_has_no_provider_generation_or_seed_mutation_calls():
    source = Path(svc.__file__).read_text(encoding="utf-8")
    assert all(token not in source for token in ("make_video", "start_generate", "creative_asset", "Google Flow"))
