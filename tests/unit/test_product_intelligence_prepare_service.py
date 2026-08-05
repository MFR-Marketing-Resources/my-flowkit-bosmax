"""Prepare Product for Copywriting lane — drafts Knowledge+Avatar+Formula, never approves.

The provider is ALWAYS mocked (no network, no token spend)."""
import pytest

from agent.db import crud
from agent.services import ai_copy_provider_adapter as provider
from agent.services import product_intelligence_prepare_service as prep


_PREPARE_AI = {
    "product_knowledge": {
        "description": "Minyak Warisan Tok Cap Burung 25ml, minyak sapuan tradisional.",
        "benefits": ["mudah dibawa", "cepat serap", "bau tidak kuat"],
        "usps": ["botol kecil poket", "sapuan tradisional keluarga"],
        "usage": "Sapu pada perut atau badan bila perlu.",
        "ingredients": "Campuran herba tradisional.",
        "warnings": "Untuk kegunaan luaran sahaja.",
        "target_customer": "ibu ada anak kecil",
    },
    "customer_avatar": {
        "audience": "ibu muda ada anak kecil",
        "desires": ["anak selesa", "malam tidur lena"],
        "fears": ["anak tak selesa waktu malam"],
        "pains": ["anak kembung perut", "perut berangin", "anak susah lena"],
        "objections": ["takut minyak busuk", "takut melekit"],
        "triggers": ["anak merengek waktu malam"],
        "tone": "mesra keibuan",
        "pronoun": "mak / awak",
    },
    "market_problem_language": ["kembung perut", "perut berangin", "anak susah lena"],
    "situation": "malam anak tak selesa, ibu berjaga",
    "desire": "anak tenang, satu rumah boleh rehat",
    "objection": "takut minyak busuk/melekit",
    "trigger": "anak mula tak selesa waktu malam",
    "use_context": "guna keluarga, sapuan tradisional",
    "claim_boundary": {
        "allowed_claims": ["minyak sapuan tradisional", "membantu rasa selesa"],
        "overclaim_notes": ["jangan dakwa sembuh", "jangan dakwa diluluskan KKM"],
    },
    "recommended_formula": "PAS",
    "formula_breakdown": {
        "problem": "Anak kembung perut waktu malam.",
        "agitate": "Rutin tidur satu rumah terganggu.",
        "solution": "Minyak sapuan tradisional botol kecil.",
        "cta": "Klik beg kuning untuk dapatkan.",
    },
}


async def _make_product() -> str:
    p = await crud.create_product(raw_product_title="MWTCB 25ml", source="MANUAL")
    return p["id"]


def _mock_complete(monkeypatch, value):
    def fake(system, user):
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(provider, "complete_json", fake)


@pytest.mark.asyncio
async def test_prepare_persists_knowledge_avatar_formula_never_approved(monkeypatch):
    pid = await _make_product()
    _mock_complete(monkeypatch, _PREPARE_AI)
    result = await prep.prepare_product_for_copywriting(pid)

    assert result["recommended_formula"] == "PAS"
    assert result["review_status"] != "APPROVED"  # operator must approve
    draft = result["draft"]
    assert draft["product_description"].startswith("Minyak Warisan")
    assert "mudah dibawa" in draft["benefits_json"]
    assert "botol kecil poket" in draft["usp_json"]

    persona = draft["buyer_persona_snapshot_json"]
    assert persona["audience"].startswith("ibu")
    assert "anak kembung perut" in persona["pains"]  # market problem language preserved
    assert persona["tone"] == "mesra keibuan"

    strat = draft["copy_strategy_summary_json"]
    assert strat["recommended_formula"] == "PAS"
    assert "kembung perut" in strat["market_problem_language"]
    assert strat["formula_breakdown"]["agitate"]


@pytest.mark.asyncio
async def test_prepare_preserves_verified_claim_critical_fields(monkeypatch):
    """Part A accuracy: the AI must NOT overwrite verified product truth. The latest
    APPROVED snapshot's ingredients/usage/warnings/description are preserved verbatim;
    the AI's (possibly wrong) guesses are ignored while it still builds persona/copy."""
    from agent.services import product_intelligence_snapshot_service as snapshot_svc

    pid = await _make_product()
    await snapshot_svc.create_snapshot(
        product_id=pid,
        version=1,
        status="APPROVED",
        product_description="Sambal sebenar",
        ingredients_text="Cili padi, bawang merah, minyak masak, belacan",
        usage_text="Gaul dengan nasi panas",
        warnings_text="Sangat pedas",
        approved_at="2026-07-05T10:00:00Z",
        created_by="legacy",
    )
    # _PREPARE_AI proposes DIFFERENT ingredients/usage/warnings — verified truth wins.
    _mock_complete(monkeypatch, _PREPARE_AI)
    result = await prep.prepare_product_for_copywriting(pid)
    draft = result["draft"]
    assert draft["ingredients_text"] == "Cili padi, bawang merah, minyak masak, belacan"
    assert draft["usage_text"] == "Gaul dengan nasi panas"
    assert draft["warnings_text"] == "Sangat pedas"
    assert draft["product_description"] == "Sambal sebenar"
    # ...but the AI still builds the fresh copy foundation.
    assert draft["copy_strategy_summary_json"]["recommended_formula"] == "PAS"
    assert draft["buyer_persona_snapshot_json"]["tone"] == "mesra keibuan"


@pytest.mark.asyncio
async def test_prepare_fills_empty_verified_field_from_ai(monkeypatch):
    """Fill-if-empty: when the approved snapshot leaves ingredients empty, the AI value
    fills the gap (nothing verified to preserve)."""
    from agent.services import product_intelligence_snapshot_service as snapshot_svc

    pid = await _make_product()
    await snapshot_svc.create_snapshot(
        product_id=pid,
        version=1,
        status="APPROVED",
        product_description="Ada desc, takde ingredients",
        approved_at="2026-07-05T10:00:00Z",
        created_by="legacy",
    )
    _mock_complete(monkeypatch, _PREPARE_AI)
    result = await prep.prepare_product_for_copywriting(pid)
    assert result["draft"]["ingredients_text"] == "Campuran herba tradisional."


@pytest.mark.asyncio
async def test_prepare_normalizes_formula_label(monkeypatch):
    pid = await _make_product()
    _mock_complete(monkeypatch, {**_PREPARE_AI, "recommended_formula": "SAVAGE_HPAS"})
    result = await prep.prepare_product_for_copywriting(pid)
    assert result["recommended_formula"] == "HPAS"


@pytest.mark.asyncio
async def test_prepare_product_not_found(monkeypatch):
    from agent.services.copy_set_service import CopySetError

    _mock_complete(monkeypatch, _PREPARE_AI)
    with pytest.raises(CopySetError) as exc:
        await prep.prepare_product_for_copywriting("missing-id")
    assert exc.value.code == "PRODUCT_NOT_FOUND"


@pytest.mark.asyncio
async def test_prepare_invalid_ai_fails_closed(monkeypatch):
    pid = await _make_product()
    _mock_complete(monkeypatch, [])  # not a dict
    with pytest.raises(provider.AICopyProviderError):
        await prep.prepare_product_for_copywriting(pid)


@pytest.mark.asyncio
async def test_prepare_never_persists_overclaim_as_allowed_claim(monkeypatch):
    """Hardening (#3): overclaim in AI allowed_claims is moved to blocked; safe
    market/traditional language stays allowed."""
    pid = await _make_product()
    dirty = {
        **_PREPARE_AI,
        "claim_boundary": {
            "allowed_claims": [
                "minyak sapuan tradisional",  # safe -> allowed
                "dijamin 100% sembuh",  # overclaim -> blocked
                "membantu rasa selesa",  # safe -> allowed
                "diluluskan NPRA",  # overclaim -> blocked
            ],
            "overclaim_notes": ["jangan dakwa klinikal"],
        },
    }
    _mock_complete(monkeypatch, dirty)
    result = await prep.prepare_product_for_copywriting(pid)
    draft = result["draft"]
    allowed = [a.casefold() for a in draft["allowed_claims_json"]]
    blocked = " ".join(draft["blocked_claims_json"]).casefold()

    # Overclaim is NEVER an allowed claim.
    assert not any(
        ("sembuh" in a) or ("npra" in a) or ("100%" in a) for a in allowed
    )
    # Safe market / traditional language survives as allowed.
    assert any("tradisional" in a for a in allowed)
    # Overclaim recorded in blocked.
    assert ("sembuh" in blocked or "dijamin" in blocked) and "npra" in blocked


@pytest.mark.asyncio
async def test_prepare_blocks_overclaim_in_narrative_fields(monkeypatch):
    """Hardening (#1): overclaim OUTSIDE allowed_claims (usage, formula_breakdown,
    etc.) is still caught and recorded as blocked; market/problem language stays."""
    pid = await _make_product()
    dirty = {
        **_PREPARE_AI,
        "product_knowledge": {
            **_PREPARE_AI["product_knowledge"],
            "usage": "sapu untuk rawat bayi sampai sembuh",  # overclaim in usage
        },
        "formula_breakdown": {
            **_PREPARE_AI["formula_breakdown"],
            "solution": "100% sembuh, diluluskan NPRA",  # overclaim in breakdown
        },
    }
    _mock_complete(monkeypatch, dirty)
    result = await prep.prepare_product_for_copywriting(pid)
    draft = result["draft"]
    blocked = " ".join(draft["blocked_claims_json"]).casefold()
    # Overclaim from narrative fields is recorded as blocked.
    assert "sembuh" in blocked
    assert "npra" in blocked or "100%" in " ".join(draft["blocked_claims_json"])
    assert "rawat" in blocked
    # Market/problem language preserved in the avatar.
    assert "anak kembung perut" in [
        p.casefold() for p in draft["buyer_persona_snapshot_json"]["pains"]
    ]
