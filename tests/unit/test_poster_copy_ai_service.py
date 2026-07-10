"""AI Poster Copy Assistant — grounding, safety gates, fallbacks, field regen
(POSTER_BUILDER_V2). All provider calls are mocked; no tokens are spent."""
import pytest

from agent.db import crud
from agent.services import poster_copy_ai_service as svc


async def _seed_product(**kw) -> str:
    row = await crud.create_product(
        kw.pop("title", "Minyak Warisan Tok 25ml"),
        source="MANUAL",
        product_display_name=kw.pop("display", "Minyak Warisan Tok"),
        category="Traditional",
        **kw,
    )
    return row["id"]


@pytest.mark.asyncio
async def test_objective_ranking_is_deterministic_and_signal_aware(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)
    pid = await _seed_product(title="Minyak Warisan Herba Tradisional 5ml roll-on")
    out = await svc.recommend_objectives(pid, refresh_ai=False)
    recs = out["recommendations"]
    assert len(recs) == 6
    top3 = {r["archetype"] for r in recs[:3]}
    # Size + heritage tokens boost these two archetypes into the top ranks.
    assert "PORTABILITY" in top3
    assert "HERITAGE_TRUST" in top3
    assert all(r["source"] == "DETERMINISTIC" for r in recs)


@pytest.mark.asyncio
async def test_high_claim_risk_prioritizes_problem_aware_safe(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)
    pid = await _seed_product(claim_risk_level="HIGH")
    out = await svc.recommend_objectives(pid)
    assert out["recommendations"][0]["archetype"] == "PROBLEM_AWARE_SAFE"


@pytest.mark.asyncio
async def test_angles_come_from_recipe_without_ai(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)
    pid = await _seed_product()
    out = await svc.recommend_angles(pid, "PRODUCT_HERO", refresh_ai=True)
    assert [a["source"] for a in out["angles"]] == ["RECIPE"] * len(out["angles"])
    assert out["angles"], "recipe main_selling_angles must seed the list"
    assert any("not configured" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_directions_fallback_is_safe_and_poster_native(monkeypatch):
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)
    pid = await _seed_product()
    out = await svc.generate_directions(pid, "PRODUCT_HERO", "Premium hero")
    assert len(out["directions"]) == 3
    for d in out["directions"]:
        assert d["primary_message"] and d["cta"]
        assert len(d["primary_message"]) <= 48
        assert len(d["cta"]) <= 24
        assert d["field_provenance"]["cta"] == "FALLBACK_TEMPLATE"
    assert out["prompt_version"] == "poster-copy-ai-v1"


@pytest.mark.asyncio
async def test_ai_directions_are_parsed_gated_and_stamped(monkeypatch):
    pid = await _seed_product()
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        svc.ai_provider, "provider_status",
        lambda: {"provider_id": "deepseek", "model_id": "chat-x",
                 "configured": True, "lane": "text_assist", "execution_enabled": True},
    )

    def fake_complete_json(system, user):
        assert "STRICT JSON" in system
        # Video concepts must NOT be in the poster brief.
        for banned in ("WPS", "duration", "story beat", "shot sequence", "dialogue"):
            assert banned not in user
        return {
            "directions": [
                {  # valid
                    "primary_message": "Warisan dalam poket anda",
                    "support_message": "Sedia setiap masa.",
                    "proof_points": ["Saiz poket", "Mudah dibawa"],
                    "cta": "Beli sekarang",
                    "disclaimer": "",
                    "tone": "mesra",
                },
                {  # medical claim → must be dropped by the safety gate
                    "primary_message": "Legakan sakit serta-merta",
                    "support_message": "",
                    "proof_points": [],
                    "cta": "Beli",
                    "disclaimer": "",
                    "tone": "",
                },
                {  # over-limit primary_message → clipped to fit, still valid
                    "primary_message": "P" * 80,
                    "support_message": "",
                    "proof_points": ["Okey"],
                    "cta": "Cuba",
                    "disclaimer": "",
                    "tone": "",
                },
            ]
        }

    monkeypatch.setattr(svc.ai_provider, "complete_json", fake_complete_json)
    out = await svc.generate_directions(pid, "PRODUCT_HERO", "Premium hero", count=3)
    texts = [d["primary_message"] for d in out["directions"]]
    assert "Warisan dalam poket anda" in texts
    assert all("Legakan" not in t for t in texts)
    assert any("failed the safety gate" in w for w in out["warnings"])
    ai_dirs = [d for d in out["directions"] if d["field_provenance"]["cta"] == "AI_GENERATED"]
    assert ai_dirs and out["ai_model"] == "deepseek:chat-x"


@pytest.mark.asyncio
async def test_offer_directions_reject_price_claims(monkeypatch):
    pid = await _seed_product()
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        svc.ai_provider, "complete_json",
        lambda s, u: {
            "directions": [
                {"primary_message": "Jimat RM10 hari ini", "support_message": "",
                 "proof_points": [], "cta": "Beli", "disclaimer": "", "tone": ""},
            ]
        },
    )
    out = await svc.generate_directions(pid, "OFFER", "Value push", count=1)
    # The RM price direction is dropped (OFFER V1 = non-price) and replaced by
    # a safe fallback.
    assert all("RM" not in d["primary_message"] for d in out["directions"])


@pytest.mark.asyncio
async def test_regenerate_field_locks_other_fields(monkeypatch):
    pid = await _seed_product()
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        svc.ai_provider, "provider_status",
        lambda: {"provider_id": "p", "model_id": "m", "configured": True,
                 "lane": "text_assist", "execution_enabled": True},
    )
    captured = {}

    def fake_complete_json(system, user):
        captured["user"] = user
        return {"cta": "Dapatkan hari ini"}

    monkeypatch.setattr(svc.ai_provider, "complete_json", fake_complete_json)
    fields = {
        "primary_message": "Warisan keluarga",
        "support_message": "",
        "proof_points": ["Saiz poket"],
        "cta": "Beli sekarang",
        "disclaimer": "",
    }
    out = await svc.regenerate_field(pid, "PRODUCT_HERO", "Hero", fields, "cta")
    assert out["value"] == "Dapatkan hari ini"
    assert out["provenance"] == "AI_GENERATED"
    # Locked context included the untouched primary message.
    assert "Warisan keluarga" in captured["user"]


@pytest.mark.asyncio
async def test_regenerate_field_fails_closed_when_unconfigured(monkeypatch):
    pid = await _seed_product()
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)
    with pytest.raises(svc.PosterCopyAIError) as exc:
        await svc.regenerate_field(pid, "PRODUCT_HERO", "Hero", {}, "cta")
    assert exc.value.code == "POSTER_AI_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_regenerated_unsafe_value_is_rejected(monkeypatch):
    pid = await _seed_product()
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        svc.ai_provider, "complete_json", lambda s, u: {"cta": "Rawat sakit anda"}
    )
    fields = {"primary_message": "Warisan", "cta": "Beli"}
    with pytest.raises(svc.PosterCopyAIError) as exc:
        await svc.regenerate_field(pid, "PRODUCT_HERO", "Hero", fields, "cta")
    assert exc.value.code == "POSTER_FIELD_REGEN_UNSAFE"


# ─── Fallback truth rule (repair PR): no fabricated claims ────────────────────

# Claims a no-grounding fallback must NEVER fabricate: popularity, scarcity,
# logistics, family suitability, quality/authenticity verification, heritage,
# ingredients, results.
_BANNED_FALLBACK_FRAGMENTS = (
    "dipercayai", "ramai", "kualiti", "terjaga", "kemasan", "asli",
    "keluarga", "stok", "terhad", "penghantaran", "pantas", "percuma",
    "original", "authentic", "turun-temurun", "warisan turun", "berkesan",
    "terbukti", "no.1", "terlaris", "mudah dibawa", "saiz kompak",
)


@pytest.mark.asyncio
async def test_fallback_makes_no_unsupported_claims_without_intelligence(monkeypatch):
    """A product with NO approved intelligence gets neutral copy: zero
    fabricated factual/social-proof claims and ZERO proof chips."""
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)
    pid = await _seed_product(title="Produk Baru XYZ", display="Produk Baru XYZ")
    out = await svc.generate_directions(pid, "PRODUCT_HERO", "")
    assert out["directions"], "fallback must still produce directions"
    for d in out["directions"]:
        blob = " ".join(
            [d["primary_message"], d["support_message"], d["cta"], d["disclaimer"]]
            + list(d["proof_points"])
        ).lower()
        for banned in _BANNED_FALLBACK_FRAGMENTS:
            assert banned not in blob, (
                f"fallback fabricated an unsupported claim: {banned!r} in {blob!r}"
            )
        # No approved benefits/USPs exist → chips must stay EMPTY.
        assert d["proof_points"] == []
        assert all(v == "FALLBACK_TEMPLATE" for v in d["field_provenance"].values())


@pytest.mark.asyncio
async def test_fallback_chips_come_only_from_approved_grounding(monkeypatch):
    """When approved benefits exist, fallback chips may state ONLY those."""
    monkeypatch.setattr(svc.ai_provider, "is_configured", lambda: False)
    pid = await _seed_product(title="Produk Grounded ABC", display="Produk Grounded ABC")

    class _PK:
        description = ""
        benefits = ["Menyegarkan aroma ruang"]
        usps = ["Formula asli Kelantan"]

    class _G:
        source = "TEST"
        product_knowledge = _PK()

    async def fake_grounding(_product):
        return _G()

    monkeypatch.setattr(svc, "resolve_copy_grounding", fake_grounding)
    out = await svc.generate_directions(pid, "PRODUCT_HERO", "Aroma asli")
    assert out["directions"]
    allowed = {"Menyegarkan aroma ruang", "Formula asli Kelantan"}
    for d in out["directions"]:
        for chip in d["proof_points"]:
            assert chip in allowed, f"chip {chip!r} is not an approved fact"
