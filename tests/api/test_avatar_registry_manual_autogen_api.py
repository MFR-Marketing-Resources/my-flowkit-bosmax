"""Avatar registry — manual add + AI auto-generate API contract.

The AI adapter is ALWAYS mocked — no real provider network call ever happens.
add_avatar is mocked in the happy paths so the committed data/ bridge is never
touched.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_add_manual_redundant_avatar_409():
    """An avatar whose descriptor already exists (Alya seed) fails closed 409."""
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Clone",
            "gender": "F",
            "skin_tone": "Light-medium",
            "hair_style": "Medium tidy",
            "wardrobe": "Smart office wear",
            "expression": "Calm neutral",
        },
    )
    assert response.status_code == 409
    assert "AVATAR_REDUNDANT" in response.text


def test_add_manual_happy_path(monkeypatch):
    """A distinct avatar (controlled-vocabulary values) is added through the
    (mocked) add_avatar door, and the code is name-only (BOS_F_ZARA_NN)."""
    captured: dict = {}

    def fake_add_avatar(row):
        captured["row"] = row
        return {"rows": 252, "approved_loaded": 252, "bridge_path": "x"}

    monkeypatch.setattr(
        "agent.services.avatar_registry.add_avatar", fake_add_avatar)
    monkeypatch.setattr(
        "agent.services.avatar_registry.find_duplicate_avatar", lambda *a: None)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Zara",
            "gender": "F",
            "skin_tone": "Tan SEA",
            "hair_style": "Short neat",
            "wardrobe": "Modern baju kurung",
            "hijab": True,
            "expression": "Friendly neutral",
            "usage_tags": "event",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["redundant"] is False
    assert body["character_name"] == "Zara"
    # Name-only code — wardrobe never enters the slug.
    assert body["avatar_code"].startswith("BOS_F_ZARA_")
    assert "BAJU" not in body["avatar_code"]
    row = captured["row"]
    assert row["approved_flag"] == "TRUE"
    assert "Identity: Zara" in row["PromptV1"]
    assert "hijab" in row["PromptV1"].lower()


def test_add_manual_rejects_bad_gender():
    """gender must be F or M (pydantic pattern) → 422."""
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "X",
            "gender": "Z",
            "skin_tone": "Fair",
            "hair_style": "Short",
            "wardrobe": "Suit",
            "expression": "Serious",
        },
    )
    assert response.status_code == 422


def test_auto_generate_fail_closed_when_unconfigured(monkeypatch):
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: False)
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "a friendly pharmacist"},
    )
    assert response.status_code == 503
    assert "TEXT_ASSIST_NOT_CONFIGURED" in response.text


def test_auto_generate_happy_path_mocked_adapter(monkeypatch):
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)

    def fake_complete_json(system, user):
        # The model returns controlled-vocabulary values (+ off-vocab casing to
        # exercise the case-insensitive snap).
        return {
            "character_name": "Farah",
            "gender": "F",
            "skin_tone": "tan sea",
            "hair_style": "Tied-back sporty",
            "wardrobe": "Modest sportswear",
            "hijab": True,
            "expression": "Confident neutral",
            "environment": "Jogging park",
            "lighting": "Soft outdoor",
            "camera": "Waist-up",
            "usage_tags": ["studio", "event"],
        }

    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json", fake_complete_json)
    monkeypatch.setattr(
        "agent.services.avatar_registry.find_duplicate_avatar", lambda *a: None)

    captured: dict = {}

    def fake_add_avatar(row):
        captured["row"] = row
        return {"rows": 252, "approved_loaded": 252, "bridge_path": "x"}

    monkeypatch.setattr(
        "agent.services.avatar_registry.add_avatar", fake_add_avatar)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "a friendly Malaysian pharmacist", "gender": "F"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generated"] is True
    assert body["character_name"] == "Farah"
    assert body["avatar_code"].startswith("BOS_F_FARAH_")
    # Snapped to canonical casing + filtered to in-vocab tags.
    assert captured["row"]["SkinTone"] == "Tan SEA"
    assert captured["row"]["usage_tags"] == "studio|event"
    assert "hijab" in captured["row"]["PromptV1"].lower()


def test_auto_generate_invalid_ai_json_502(monkeypatch):
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json",
        lambda system, user: {"character_name": "NoGender"})  # missing keys
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "x"},
    )
    assert response.status_code == 502
    assert "AI_AVATAR_INVALID" in response.text


def test_delete_avatar_removes_row_and_archives_linked_image(monkeypatch):
    """DELETE removes the pool row (mocked) AND archives the linked reference
    image located via the AVATAR_CODE marker in the asset description — this
    exercises the previously-dead archive branch."""
    monkeypatch.setattr(
        "agent.services.avatar_registry.delete_avatar",
        lambda code: {"removed": code, "remaining": 249, "bridge_path": "x"},
    )

    class _Asset:
        asset_id = "ca_linked"
        media_id = "m_zara"
        description = "AVATAR_CODE:BOS_F_ZARA_01 — generated from registry PromptV1"

    async def fake_list(**kwargs):
        return [_Asset()]

    archived: dict = {}

    async def fake_archive(asset_id):
        archived["id"] = asset_id
        return None

    purged: dict = {}

    async def fake_purge(media_id):
        purged["id"] = media_id
        return {"deleted": 1, "file_removed": True}

    monkeypatch.setattr(
        "agent.services.creative_asset_service.list_creative_assets", fake_list)
    monkeypatch.setattr(
        "agent.services.creative_asset_service.archive_creative_asset", fake_archive)
    monkeypatch.setattr(
        "agent.db.crud.delete_generated_artifact", fake_purge)

    client = TestClient(_build_app())
    response = client.delete("/api/workspace/avatar-registry/BOS_F_ZARA_01")
    assert response.status_code == 200
    body = response.json()
    assert body["removed"] == "BOS_F_ZARA_01"
    assert body["archived_asset_id"] == "ca_linked"
    assert archived["id"] == "ca_linked"  # linked image WAS archived (not dead code)
    # the linked 48h temp artifact is also purged so the image fully leaves the Library
    assert body["purged_media_id"] == "m_zara"
    assert purged["id"] == "m_zara"


def test_delete_avatar_unknown_code_404(monkeypatch):
    def fake_delete(code):
        raise ValueError(f"AVATAR_CODE_NOT_FOUND:{code}")

    monkeypatch.setattr(
        "agent.services.avatar_registry.delete_avatar", fake_delete)

    client = TestClient(_build_app())
    response = client.delete("/api/workspace/avatar-registry/BOS_F_NOPE_00")
    assert response.status_code == 404
    assert "AVATAR_CODE_NOT_FOUND" in response.text


# ── Standardization: controlled vocabulary + gender/hijab rule ──────────────

def test_avatar_registry_vocab_endpoint():
    client = TestClient(_build_app())
    r = client.get("/api/workspace/avatar-registry/vocab")
    assert r.status_code == 200
    body = r.json()
    assert "Tan SEA" in body["vocab"]["skin_tone"]
    assert "Waist-up" in body["vocab"]["camera"]
    assert isinstance(body["personas"], list)
    # Personas are clean single tokens — no descriptor-slug leaks.
    assert all("_" not in p for p in body["personas"])


def test_add_manual_rejects_off_vocab_422(monkeypatch):
    monkeypatch.setattr(
        "agent.services.avatar_registry.find_duplicate_avatar", lambda *a: None)
    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Nova",
            "gender": "F",
            "skin_tone": "Neon purple",  # off-vocab
            "hair_style": "Short neat",
            "wardrobe": "Smart office wear",
            "expression": "Calm neutral",
        },
    )
    assert r.status_code == 422
    assert "AVATAR_VALUE_NOT_IN_VOCAB:skin_tone" in r.text


def test_add_manual_rejects_hijab_on_male_422():
    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Amir",
            "gender": "M",
            "hijab": True,
            "skin_tone": "Tan SEA",
            "hair_style": "Short neat",
            "wardrobe": "Baju melayu modern",
            "expression": "Calm neutral",
        },
    )
    assert r.status_code == 422
    assert "AVATAR_HIJAB_MALE_INVALID" in r.text


def test_auto_generate_forces_hijab_off_for_male(monkeypatch):
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)
    monkeypatch.setattr(
        "agent.services.avatar_registry.find_duplicate_avatar", lambda *a: None)

    def fake_complete_json(system, user):
        return {  # model wrongly set hijab=true for a male
            "character_name": "Amir",
            "gender": "M",
            "hijab": True,
            "skin_tone": "Tan SEA",
            "hair_style": "Short neat",
            "wardrobe": "Baju melayu modern",
            "expression": "Calm neutral",
            "usage_tags": ["office"],
        }

    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json", fake_complete_json)
    captured: dict = {}
    monkeypatch.setattr(
        "agent.services.avatar_registry.add_avatar",
        lambda row: captured.__setitem__("row", row) or {"rows": 1})

    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "a male farmer", "gender": "M"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["avatar_code"].startswith("BOS_M_AMIR_")
    # Hijab forced off for male → PromptV1 never mentions hijab.
    assert "hijab" not in captured["row"]["PromptV1"].lower()


def test_auto_generate_off_vocab_descriptor_502(monkeypatch):
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json",
        lambda system, user: {
            "character_name": "Nova",
            "gender": "F",
            "skin_tone": "Neon purple",  # off-vocab → cannot snap
            "hair_style": "Short neat",
            "wardrobe": "Smart office wear",
            "expression": "Calm neutral",
        },
    )
    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/auto-generate", json={"brief": "x"})
    assert r.status_code == 502
    assert "AI_AVATAR_INVALID" in r.text


# ── Gender-aware vocabulary + gender-dependency validation ──────────────────

def test_vocab_endpoint_is_gender_aware():
    client = TestClient(_build_app())
    body = client.get("/api/workspace/avatar-registry/vocab").json()
    assert body["gender_specific_fields"] == ["wardrobe"]
    # Personas split by pool prefix; no token in both buckets.
    pbg = body["personas_by_gender"]
    assert "AMIR" in pbg["M"] and "ALYA" in pbg["F"]
    assert not (set(pbg["F"]) & set(pbg["M"]))
    # Per-gender wardrobe is partitioned (female-only vs male-only traditional wear).
    vbg = body["vocab_by_gender"]
    assert "Modern baju kurung" in vbg["F"]["wardrobe"]
    assert "Modern baju kurung" not in vbg["M"]["wardrobe"]
    assert "Baju melayu modern" in vbg["M"]["wardrobe"]
    assert "Baju melayu modern" not in vbg["F"]["wardrobe"]


def test_add_manual_rejects_female_wardrobe_on_male_422():
    """M + female-only wardrobe (baju kurung) fails closed 422."""
    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Newman",  # new persona → no persona-gender clash
            "gender": "M",
            "skin_tone": "Tan SEA",
            "hair_style": "Short neat",
            "wardrobe": "Modern baju kurung",  # female-only
            "expression": "Calm neutral",
        },
    )
    assert r.status_code == 422
    assert "AVATAR_VALUE_NOT_FOR_GENDER:wardrobe" in r.text


def test_add_manual_rejects_male_wardrobe_on_female_422():
    """F + male-only wardrobe (baju melayu) fails closed 422."""
    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Newfem",
            "gender": "F",
            "skin_tone": "Tan SEA",
            "hair_style": "Short neat",
            "wardrobe": "Baju melayu modern",  # male-only
            "expression": "Calm neutral",
        },
    )
    assert r.status_code == 422
    assert "AVATAR_VALUE_NOT_FOR_GENDER:wardrobe" in r.text


def test_add_manual_rejects_persona_gender_mismatch_422():
    """An existing male persona (Amir) claimed as female fails closed 422."""
    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Amir",  # male persona in the pool
            "gender": "F",
            "skin_tone": "Tan SEA",
            "hair_style": "Short neat",
            "wardrobe": "Smart office wear",
            "expression": "Calm neutral",
        },
    )
    assert r.status_code == 422
    assert "AVATAR_PERSONA_GENDER_MISMATCH" in r.text


def test_auto_generate_rejects_off_gender_wardrobe_502(monkeypatch):
    """AI returns a male avatar wearing a female-only wardrobe → rejected 502
    (the gender-aware snap cannot place it in the male-allowed set)."""
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json",
        lambda system, user: {
            "character_name": "Rizal",
            "gender": "M",
            "skin_tone": "Tan SEA",
            "hair_style": "Short neat",
            "wardrobe": "Modern baju kurung",  # female-only on a male
            "expression": "Calm neutral",
        },
    )
    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "a male teacher", "gender": "M"},
    )
    assert r.status_code == 502
    assert "AI_AVATAR_INVALID" in r.text


def test_auto_generate_rejects_cross_gender_persona_502(monkeypatch):
    """AI names a male avatar after an existing female persona (Alya) → rejected
    502, so the AI lane can never mint a cross-gender persona code."""
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json",
        lambda system, user: {
            "character_name": "Alya",  # existing FEMALE persona
            "gender": "M",
            "skin_tone": "Tan SEA",
            "hair_style": "Short neat",
            "wardrobe": "Smart office wear",
            "expression": "Calm neutral",
        },
    )
    client = TestClient(_build_app())
    r = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "a male manager", "gender": "M"},
    )
    assert r.status_code == 502
    assert "AI_AVATAR_INVALID" in r.text
