"""Provider-free V3 FAST54 contract closure fixtures.

These tests use the real Round 2 service after the provider boundary.  The
fixture provider is deterministic and never opens a network connection.
"""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from agent.authority.copy_blueprint_v2_authority import required_formula_stage_keys
from agent.db.schema import get_db
from agent.models.copy_blueprint_v2 import digest_evidence_text
from agent.services import ai_copy_provider_adapter
from agent.services.storyboard_landbank_v3_factory import V3CopyFactoryService
from agent.services.storyboard_landbank_v3_round2 import V3CopyRegisterRound2Service


MWCB_PRODUCT_ID = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
MWCB_SNAPSHOT_ID = "mwcb-fast54-golden-snapshot-v8"
MWCB_ROUTE_FACT_ID = f"fact:{MWCB_PRODUCT_ID}:benefits_json:0"

_MWCB_FACTS = (
    ("allowed_claims_json:0", "ALLOWED_CLAIM", "Melegakan perut kembung"),
    ("allowed_claims_json:1", "ALLOWED_CLAIM", "Mengurangkan rasa sengal badan"),
    ("allowed_claims_json:2", "ALLOWED_CLAIM", "Membantu mengurangkan kebas"),
    ("allowed_claims_json:3", "ALLOWED_CLAIM", "Melegakan kegatalan akibat gigitan serangga"),
    ("benefits_json:0", "BENEFIT", "Melegakan perut kembung dan angin pada kanak-kanak dan dewasa"),
    ("benefits_json:1", "BENEFIT", "Mengurangkan rasa sengal-sengal badan selepas bekerja atau bangun tidur"),
    ("benefits_json:2", "BENEFIT", "Membantu mengurangkan kebas tangan dan kaki"),
    ("benefits_json:3", "BENEFIT", "Melegakan kegatalan dan bengkak akibat gigitan serangga"),
    ("benefits_json:4", "BENEFIT", "Memberi rasa hangat dan selesa pada badan"),
    (
        "product_description:0",
        "PRODUCT_DESCRIPTION",
        "Minyak Warisan Cap Burung 25ml ialah minyak angin tradisional untuk ketidakselesaan ringan dan kegunaan keluarga.",
    ),
    (
        "target_customer_text:0",
        "TARGET_CUSTOMER",
        "Ibu bapa di Malaysia yang mencari minyak angin tradisional untuk kegunaan keluarga.",
    ),
    (
        "usage_text:0",
        "USAGE",
        "Sapukan sedikit pada bahagian yang tidak selesa dan urut perlahan-lahan.",
    ),
    ("usp_json:0", "USP", "Resipi tradisional warisan Cap Burung"),
    ("usp_json:1", "USP", "Sesuai untuk kegunaan seisi keluarga"),
    ("usp_json:2", "USP", "Bekalan 25ml yang praktikal dan mudah dibawa"),
)


async def _seed_mwcb_truth() -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name, lifecycle_status) VALUES (?, ?, ?, ?, 'ACTIVE')",
        (MWCB_PRODUCT_ID, "Minyak Warisan Cap Burung 25ml", "Minyak Warisan Cap Burung 25ml", "Cap Burung"),
    )
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, usage_text, "
        "target_customer_text, allowed_claims_json, blocked_claims_json, buyer_persona_snapshot_json, "
        "copy_strategy_summary_json, claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES (?, ?, 8, 'APPROVED', ?, ?, ?, ?, ?, ?, '[]', ?, ?, 'CLAIM_SAFE', 'MEDIUM', ?, ?)",
        (
            MWCB_SNAPSHOT_ID,
            MWCB_PRODUCT_ID,
            "Minyak Warisan Cap Burung 25ml ialah minyak angin tradisional untuk ketidakselesaan ringan dan kegunaan keluarga.",
            json.dumps([
                "Melegakan perut kembung dan angin pada kanak-kanak dan dewasa",
                "Mengurangkan rasa sengal-sengal badan selepas bekerja atau bangun tidur",
                "Membantu mengurangkan kebas tangan dan kaki",
                "Melegakan kegatalan dan bengkak akibat gigitan serangga",
                "Memberi rasa hangat dan selesa pada badan",
            ], ensure_ascii=False),
            json.dumps([
                "Resipi tradisional warisan Cap Burung",
                "Sesuai untuk kegunaan seisi keluarga",
                "Bekalan 25ml yang praktikal dan mudah dibawa",
            ], ensure_ascii=False),
            "Sapukan sedikit pada bahagian yang tidak selesa dan urut perlahan-lahan.",
            "Ibu bapa di Malaysia yang mencari minyak angin tradisional untuk kegunaan keluarga.",
            json.dumps([
                "Melegakan perut kembung",
                "Mengurangkan rasa sengal badan",
                "Membantu mengurangkan kebas",
                "Melegakan kegatalan akibat gigitan serangga",
            ], ensure_ascii=False),
            json.dumps({"audience": "ibu bapa di Malaysia"}, ensure_ascii=False),
            json.dumps({"formula": "PAS", "route": "perut kembung"}, ensure_ascii=False),
            "2026-08-24T00:00:00Z",
            "2026-08-24T00:00:00Z",
        ),
    )
    for path, fact_kind, text in _MWCB_FACTS:
        fact_id = f"fact:{MWCB_PRODUCT_ID}:{path}"
        await db.execute(
            "INSERT INTO copy_evidence_fact_v2 "
            "(product_id, snapshot_id, fact_id, fact_kind, canonical_text, text_digest, snapshot_version, "
            "snapshot_status, approved, created_at) VALUES (?, ?, ?, ?, ?, ?, 8, 'APPROVED', 1, ?)",
            (
                MWCB_PRODUCT_ID,
                MWCB_SNAPSHOT_ID,
                fact_id,
                fact_kind,
                text,
                digest_evidence_text(text),
                "2026-08-24T00:00:00Z",
            ),
        )
    await db.commit()


async def _seed_mwcb_route(factory) -> None:
    """Pre-lock ONE approved benefit route (Angle + Storyline Family) for MWCB so
    STRUCTURE authoring receives a locked route, per the owner ruling.  BOSMAX
    owns the route; the provider only authors words on it."""
    angle = await factory.create_angle(
        MWCB_PRODUCT_ID,
        {
            "angle_id": f"{MWCB_PRODUCT_ID}-angle",
            "definition": "Sudut rutin keluarga apabila perut kembung mengganggu hari.",
            "formula_id": "PAS",
            "objective_id": "conversion",
            "objective_definition": "Drive a safe trial",
            "evidence_fact_ids": [MWCB_ROUTE_FACT_ID],
        },
        actor_id="mwcb-route",
        request_id=f"{MWCB_PRODUCT_ID}:angle",
    )
    await factory.create_storyline_family(
        MWCB_PRODUCT_ID,
        {
            "family_id": f"{MWCB_PRODUCT_ID}-family",
            "angle_id": angle.angle_id,
            "formula_id": "PAS",
            "objective_compatibility": {"objective_ids": ["conversion"]},
            "reviewed_definition": "Satu laluan PAS berterusan daripada masalah perut kembung kepada langkah sapuan tradisional.",
            "route_anchor_fact_ids": [MWCB_ROUTE_FACT_ID],
            "require_route_identity": True,
        },
        actor_id="mwcb-route",
        request_id=f"{MWCB_PRODUCT_ID}:family",
    )


def _golden_envelope(plan, recipe) -> dict:
    required = tuple(required_formula_stage_keys(recipe.formula.formula_id))
    route_fact_id = MWCB_ROUTE_FACT_ID

    def segment(stage_key: str, text: str, entry: str, exit: str, claim_bearing: bool) -> dict:
        return {
            "formula_stage_key": stage_key,
            "authored_text": text,
            "entry_key": entry,
            "exit_key": exit,
            "continuity_requirements": [],
            "evidence_fact_ids": [route_fact_id] if claim_bearing else [],
            "claim_bearing": claim_bearing,
        }

    hooks = (
        "Perut kembung mengganggu rutin keluarga?",
        "Si kecil meragam kerana perut kembung?",
        "Rasa tidak selesa selepas makan?",
        "Rutin anak terganggu oleh angin?",
        "Cari sapuan tradisional untuk kembung?",
        "Sediakan bantuan ringkas untuk keluarga?",
    )
    bodies = (
        ("Sapukan sedikit pada bahagian perut.", "Urut perlahan hingga lebih selesa."),
        ("Gunakan sapuan ringan apabila perlu.", "Bantu rutin kembali lebih tenang."),
        ("Sapu sedikit mengikut keperluan.", "Simpan botol praktikal untuk keluarga."),
    )
    ctas = (
        "Simpan untuk kegunaan keluarga.",
        "Bawa bersama apabila diperlukan.",
        "Cuba rutin ringkas hari ini.",
    )
    proposals: list[dict] = []
    for index, text in enumerate(hooks):
        proposals.append({
            "semantic_class": "HOOK",
            "segments": [segment(required[0], text, "arc:start", "arc:body", True)],
            "rationale": "Variasi hook Malay untuk satu laluan perut kembung.",
            "risk_notes": ["REVIEW"],
        })
    for index, texts in enumerate(bodies):
        proposals.append({
            "semantic_class": "BODY_CORE",
            "segments": [
                segment(required[1], texts[0], "arc:body", "arc:mid", True),
                segment(required[2], texts[1], "arc:mid", "arc:cta", True),
            ],
            "rationale": "Variasi Body/Core Malay dengan jambatan berterusan.",
            "risk_notes": ["REVIEW"],
        })
    for index, text in enumerate(ctas):
        proposals.append({
            "semantic_class": "CTA",
            "segments": [segment(required[-1], text, "arc:cta", "arc:end", False)],
            "rationale": "Variasi CTA Malay untuk semakan manusia.",
            "risk_notes": ["REVIEW"],
        })
    # The provider authors WORDS ONLY; BOSMAX owns the locked route, so the
    # golden envelope carries no Angle/Storyline Family proposal.
    return {
        "schema_version": "v3-copy-assistant-1",
        "proposals": proposals,
    }


class _GoldenBoundaryProvider:
    def __init__(self, payload: dict):
        self.payload = deepcopy(payload)
        self.calls = 0

    def complete_json_with_receipt(self, _system: str, _user: str):
        self.calls += 1
        return deepcopy(self.payload), {
            "lane": "text_assist",
            "provider_id": "fixture-mwcb-golden",
            "model_id": "fixture-realistic-malay",
            "response_status": "SUCCEEDED",
            "http_status": 200,
            "finish_reason": "stop",
            "json_parse_status": "VALID",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


class _UsageBoundaryProvider(_GoldenBoundaryProvider):
    def __init__(self, payload: dict, usage: dict, *, finish_reason: str = "stop"):
        super().__init__(payload)
        self.usage = dict(usage)
        self.finish_reason = finish_reason

    def complete_json_with_receipt(self, _system: str, _user: str):
        self.calls += 1
        return deepcopy(self.payload), {
            "lane": "text_assist",
            "provider_id": "fixture-token-boundary",
            "model_id": "fixture-token-boundary-model",
            "response_status": "SUCCEEDED",
            "http_status": 200,
            "finish_reason": self.finish_reason,
            "json_parse_status": "VALID",
            "usage": dict(self.usage),
        }


async def _production_counts(product_id: str) -> dict[str, int]:
    db = await get_db()
    tables = (
        "angle_v3",
        "storyline_family_v3",
        "storyboard_component_v3",
        "master_storyboard_v3",
        "duration_projection_v3",
        "v3_human_approval_receipt",
        "materialization_link_v3",
        "production_copy_supply_manifest_v3",
        "copy_blueprint_v2",
        "copy_execution_binding_v2",
        "copy_execution_authority_v2",
    )
    return {
        table: int((await (await db.execute(f"SELECT COUNT(*) FROM {table} WHERE product_id=?", (product_id,))).fetchone())[0])
        for table in tables
    }


async def _make_token_boundary_run(product_suffix: str, usage: dict, *, finish_reason: str = "stop", max_output_tokens: int = 4096):
    await _seed_mwcb_truth()
    factory = V3CopyFactoryService()
    await _seed_mwcb_route(factory)
    setup_service = V3CopyRegisterRound2Service(factory=factory)
    setup = await setup_service.create_campaign_recipe(
        MWCB_PRODUCT_ID,
        objective_id="conversion",
        objective_definition="Drive a safe trial",
        formula_id="PAS",
        preset="FAST54",
        supported_durations_seconds=[8, 16, 24],
        target_capacity=54,
        language_profile="Malay",
        wps_mode="SWEET",
        actor_id="token-boundary",
        request_id=f"mwcb-token:{product_suffix}:setup",
    )
    plan = await setup_service.plan_assistant(
        MWCB_PRODUCT_ID,
        setup["recipe_id"],
        mode="CREATE",
        evidence_fact_ids=[MWCB_ROUTE_FACT_ID],
        max_output_tokens=max_output_tokens,
        actor_id="token-boundary",
        request_id=f"mwcb-token:{product_suffix}:plan",
    )
    recipe = await factory.repository.get("COPY_RECIPE", setup["recipe_id"])
    provider = _UsageBoundaryProvider(
        _golden_envelope(plan, recipe),
        usage,
        finish_reason=finish_reason,
    )
    service = V3CopyRegisterRound2Service(factory=factory, provider=provider)
    return factory, service, plan, provider


@pytest.mark.asyncio
async def test_v3_output_budget_accepts_huge_prompt_when_completion_is_valid():
    _factory, service, plan, provider = await _make_token_boundary_run(
        "huge-prompt-pass",
        {"prompt_tokens": 10_189, "completion_tokens": 3_000, "total_tokens": 13_189},
    )
    result = await service.execute_assistant(
        plan.plan_id,
        actor_id="token-boundary",
        request_id="mwcb-token:huge-prompt-pass:execute",
    )
    assert result["status"] == "EXECUTED"
    assert provider.calls == 1
    assert result["provider"]["usage"] == {
        "prompt_tokens": 10_189,
        "completion_tokens": 3_000,
        "total_tokens": 13_189,
        "input_tokens": 10_189,
        "output_tokens": 3_000,
    }


@pytest.mark.asyncio
async def test_v3_output_budget_rejects_completion_over_cap_before_supply_mutation():
    _factory, service, plan, provider = await _make_token_boundary_run(
        "completion-over-cap",
        {"prompt_tokens": 10_189, "completion_tokens": 4_097, "total_tokens": 14_286},
    )
    with pytest.raises(Exception) as error:
        await service.execute_assistant(
            plan.plan_id,
            actor_id="token-boundary",
            request_id="mwcb-token:completion-over-cap:execute",
        )
    assert error.value.code == "AI_COPY_ASSIST_TOKEN_BUDGET_EXCEEDED"
    assert provider.calls == 1
    counts = await _production_counts(MWCB_PRODUCT_ID)
    # The pre-locked route (Angle + Storyline Family) is a prerequisite; the
    # budget failure must persist no NEW supply beyond it.
    assert all(
        count == 0
        for table, count in counts.items()
        if table not in {"angle_v3", "storyline_family_v3"}
    )


def test_v3_finish_reason_length_is_truncated_response():
    with pytest.raises(ai_copy_provider_adapter.AICopyProviderError) as error:
        ai_copy_provider_adapter._extract_json_object(
            '{"schema_version":"v3-copy-assistant-1"}',
            finish_reason="length",
        )
    assert error.value.code == ai_copy_provider_adapter.ERR_RESPONSE_INVALID
    assert error.value.diagnostic_category == ai_copy_provider_adapter.DIAGNOSTIC_TRUNCATED_RESPONSE
    assert error.value.finish_reason == "length"


@pytest.mark.asyncio
async def test_v3_valid_stop_completion_continues_to_semantic_contract():
    _factory, service, plan, provider = await _make_token_boundary_run(
        "valid-stop",
        {"prompt_tokens": 10_189, "completion_tokens": 3_000, "total_tokens": 13_189},
        finish_reason="stop",
    )
    result = await service.execute_assistant(
        plan.plan_id,
        actor_id="token-boundary",
        request_id="mwcb-token:valid-stop:execute",
    )
    assert result["status"] == "EXECUTED"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_v3_total_tokens_alone_never_trips_output_budget():
    _factory, service, plan, provider = await _make_token_boundary_run(
        "total-only",
        {"total_tokens": 999_999},
    )
    result = await service.execute_assistant(
        plan.plan_id,
        actor_id="token-boundary",
        request_id="mwcb-token:total-only:execute",
    )
    assert result["status"] == "EXECUTED"
    assert result["provider"]["usage"] == {"total_tokens": 999_999}
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_mwcb_fast54_golden_envelope_completes_provider_free_full_path():
    await _seed_mwcb_truth()
    factory = V3CopyFactoryService()
    await _seed_mwcb_route(factory)
    setup_service = V3CopyRegisterRound2Service(factory=factory)
    setup = await setup_service.create_campaign_recipe(
        MWCB_PRODUCT_ID,
        objective_id="conversion",
        objective_definition="Drive a safe trial",
        formula_id="PAS",
        preset="FAST54",
        supported_durations_seconds=[8, 16, 24],
        target_capacity=54,
        language_profile="Malay",
        wps_mode="SWEET",
        actor_id="closure-fixture",
        request_id="mwcb-fast54:setup",
    )
    plan = await setup_service.plan_assistant(
        MWCB_PRODUCT_ID,
        setup["recipe_id"],
        mode="CREATE",
        evidence_fact_ids=[MWCB_ROUTE_FACT_ID],
        actor_id="closure-fixture",
        request_id="mwcb-fast54:plan",
    )
    recipe = await factory.repository.get("COPY_RECIPE", setup["recipe_id"])
    golden = _golden_envelope(plan, recipe)
    provider = _GoldenBoundaryProvider(golden)
    service = V3CopyRegisterRound2Service(factory=factory, provider=provider)

    before = await _production_counts(MWCB_PRODUCT_ID)
    # The route (Angle + Storyline Family) is pre-locked by BOSMAX; everything
    # downstream of it is authored provider-free by this run.
    assert before["angle_v3"] == 1 and before["storyline_family_v3"] == 1
    assert all(
        count == 0
        for table, count in before.items()
        if table not in {"angle_v3", "storyline_family_v3"}
    )
    result = await service.execute_assistant(
        plan.plan_id,
        actor_id="closure-fixture",
        request_id="mwcb-fast54:execute",
        provider_mode="FAKE_TEST",
    )

    assert provider.calls == 1
    assert result["status"] == "EXECUTED"
    assert result["provider"]["mode"] == "FAKE_TEST"
    assert result["provider_calls"] == 0
    assert len(result["component_refs"]) == 12
    assert len(result["projections"]) == 3

    counts = await _production_counts(MWCB_PRODUCT_ID)
    assert counts["angle_v3"] == 1
    assert counts["storyline_family_v3"] == 1
    assert counts["storyboard_component_v3"] == 12
    assert counts["master_storyboard_v3"] == 1
    assert counts["duration_projection_v3"] == 3
    assert counts["v3_human_approval_receipt"] == 0
    assert counts["materialization_link_v3"] == 0
    assert counts["production_copy_supply_manifest_v3"] == 0
    assert all(count == 0 for table, count in counts.items() if table.startswith("copy_"))

    capacity = await factory.capacity(setup["recipe_id"])
    assert capacity.theoretical_raw_capacity == 54
    assert capacity.semantic_valid_capacity == 54
    assert capacity.duration_valid_capacity == 54
    assert capacity.weak_review_required_capacity == 0
    assert capacity.duration_counts == {"8": 54, "16": 54, "24": 54}
    assert capacity.fast54_ready is True


@pytest.mark.asyncio
async def test_mwcb_fast54_built_in_fake_provider_hits_exact_target_without_authority_mutation(monkeypatch):
    monkeypatch.setenv("V3_ROUND2_FAKE_PROVIDER", "1")
    await _seed_mwcb_truth()
    factory = V3CopyFactoryService()
    await _seed_mwcb_route(factory)
    service = V3CopyRegisterRound2Service(factory=factory)
    setup = await service.create_campaign_recipe(
        MWCB_PRODUCT_ID,
        objective_id="conversion",
        objective_definition="Drive a safe trial",
        formula_id="PAS",
        preset="FAST54",
        supported_durations_seconds=[8, 16, 24],
        target_capacity=54,
        language_profile="Malay",
        wps_mode="SWEET",
        actor_id="closure-fixture",
        request_id="mwcb-fast54:builtin-fake:setup",
    )
    plan = await service.plan_assistant(
        MWCB_PRODUCT_ID,
        setup["recipe_id"],
        mode="CREATE",
        evidence_fact_ids=[MWCB_ROUTE_FACT_ID],
        actor_id="closure-fixture",
        request_id="mwcb-fast54:builtin-fake:plan",
    )

    result = await service.execute_assistant(
        plan.plan_id,
        actor_id="closure-fixture",
        request_id="mwcb-fast54:builtin-fake:execute",
        provider_mode="FAKE_TEST",
    )

    assert result["status"] == "EXECUTED"
    assert result["provider"]["provider_id"] == "fake-v3-round2"
    assert result["provider_calls"] == 0
    assert len(result["component_refs"]) == 12
    assert len(result["projections"]) == 3

    counts = await _production_counts(MWCB_PRODUCT_ID)
    assert counts["angle_v3"] == 1
    assert counts["storyline_family_v3"] == 1
    assert counts["storyboard_component_v3"] == 12
    assert counts["master_storyboard_v3"] == 1
    assert counts["duration_projection_v3"] == 3
    assert counts["v3_human_approval_receipt"] == 0
    assert counts["materialization_link_v3"] == 0
    assert counts["production_copy_supply_manifest_v3"] == 0
    assert all(count == 0 for table, count in counts.items() if table.startswith("copy_"))

    capacity = await factory.capacity(setup["recipe_id"])
    assert capacity.theoretical_raw_capacity == 54
    assert capacity.semantic_valid_capacity == 54
    assert capacity.duration_valid_capacity == 54
    assert capacity.weak_review_required_capacity == 0
    assert capacity.duration_counts == {"8": 54, "16": 54, "24": 54}
    assert capacity.fast54_ready is True


@pytest.mark.asyncio
async def test_mwcb_fast54_locked_route_words_only_regression_proof(monkeypatch):
    # Owner requirement 6: one provider-free regression proof of the simplified,
    # route-locked, words-only STRUCTURE contract.
    monkeypatch.setenv("V3_ROUND2_FAKE_PROVIDER", "1")
    await _seed_mwcb_truth()
    factory = V3CopyFactoryService()
    await _seed_mwcb_route(factory)
    service = V3CopyRegisterRound2Service(factory=factory)
    setup = await service.create_campaign_recipe(
        MWCB_PRODUCT_ID,
        objective_id="conversion",
        objective_definition="Drive a safe trial",
        formula_id="PAS",
        preset="FAST54",
        supported_durations_seconds=[8, 16, 24],
        target_capacity=54,
        language_profile="Malay",
        wps_mode="SWEET",
        actor_id="req6",
        request_id="mwcb-req6:setup",
    )
    recipe = await factory.repository.get("COPY_RECIPE", setup["recipe_id"])
    plan = await service.plan_assistant(
        MWCB_PRODUCT_ID,
        setup["recipe_id"],
        mode="CREATE",
        evidence_fact_ids=[MWCB_ROUTE_FACT_ID],
        actor_id="req6",
        request_id="mwcb-req6:plan",
    )

    # (1) The prompt contains exactly ONE locked route; BOSMAX owns it.
    contract = service._provider_output_contract(plan, recipe)
    assert plan.locked_route_anchor_fact_ids
    assert contract["locked_route"]["route_anchor_fact_ids"] == list(plan.locked_route_anchor_fact_ids)

    # (2) The provider is not asked for route anchors / an Angle / a Family.
    assert "storyline_route_rules" not in contract
    assert "angle_proposal" not in contract["output_shape"]
    assert "storyline_family_proposal" not in contract["output_shape"]
    assert "storyline_family_proposal" in contract["forbidden_output_fields"]
    assert "route_anchor_fact_ids" in contract["forbidden_output_fields"]

    # (3) No duration / WPS authoring rules appear in the semantic prompt.
    system, user, _truth = await service._prompt_parts(plan, recipe)
    prompt = system + "\n" + user
    for banned in ("duration_feasibility", "wps_duration_rules", "shortest_duration"):
        assert banned not in prompt

    # (4) The provider sees only the locked route's allowed evidence.
    assert contract["allowed_evidence_fact_ids"] == list(plan.allowed_evidence_fact_ids)

    # (5) A fake 6/3/3 output commits and yields semantic_valid_capacity == 54.
    assert {gap.semantic_class: gap.gap_count for gap in plan.gaps} == {"HOOK": 6, "BODY_CORE": 3, "CTA": 3}
    result = await service.execute_assistant(
        plan.plan_id, actor_id="req6", request_id="mwcb-req6:execute", provider_mode="FAKE_TEST",
    )
    assert result["status"] == "EXECUTED"
    capacity = await factory.capacity(setup["recipe_id"])
    assert capacity.semantic_valid_capacity == 54
    assert capacity.fast54_semantic_ready is True

    # (6) Route/evidence violations still fail closed.
    bundle = await factory.truth_adapter.current(MWCB_PRODUCT_ID)
    golden = _golden_envelope(plan, recipe)
    out_of_island = deepcopy(golden)
    out_of_island["proposals"][0]["segments"][0]["evidence_fact_ids"] = [
        f"fact:{MWCB_PRODUCT_ID}:product_description:0"
    ]
    with pytest.raises(Exception) as error:
        service._validate_proposals(out_of_island, plan, recipe, bundle)
    assert error.value.code == "AI_COPY_ASSIST_EVIDENCE_INVALID"
    supply_owned = deepcopy(golden)
    supply_owned["storyline_family_proposal"] = {
        "reviewed_definition": "provider tried to own the route",
        "narrative_route": {"stage_keys": list(required_formula_stage_keys("PAS")), "order_locked": True},
        "route_anchor_fact_ids": list(plan.locked_route_anchor_fact_ids),
    }
    with pytest.raises(Exception) as error:
        service._validate_proposals(supply_owned, plan, recipe, bundle)
    assert error.value.code == "AI_COPY_ASSIST_ROUTE_OWNERSHIP_FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("remove_proposal", "AI_COPY_ASSIST_PROPOSAL_COUNT_MISMATCH"),
        ("add_proposal", "AI_COPY_ASSIST_PROPOSAL_COUNT_MISMATCH"),
        ("wrong_route_order", "AI_COPY_ASSIST_STAGE_CONTRACT_INVALID"),
        ("outside_evidence_island", "AI_COPY_ASSIST_EVIDENCE_INVALID"),
    ),
)
async def test_mwcb_provider_free_adversarial_closure_gates_do_not_persist_supply(mutation, expected_code):
    await _seed_mwcb_truth()
    factory = V3CopyFactoryService()
    await _seed_mwcb_route(factory)
    service = V3CopyRegisterRound2Service(factory=factory)
    setup = await service.create_campaign_recipe(
        MWCB_PRODUCT_ID,
        objective_id="conversion",
        objective_definition="Drive a safe trial",
        formula_id="PAS",
        preset="FAST54",
        supported_durations_seconds=[8, 16, 24],
        target_capacity=54,
        language_profile="Malay",
        wps_mode="SWEET",
        actor_id="closure-fixture",
        request_id=f"mwcb-fast54:adversarial-setup:{mutation}",
    )
    plan = await service.plan_assistant(
        MWCB_PRODUCT_ID,
        setup["recipe_id"],
        mode="CREATE",
        evidence_fact_ids=[MWCB_ROUTE_FACT_ID],
        actor_id="closure-fixture",
        request_id=f"mwcb-fast54:adversarial-plan:{mutation}",
    )
    recipe = await factory.repository.get("COPY_RECIPE", setup["recipe_id"])
    payload = _golden_envelope(plan, recipe)
    if mutation == "remove_proposal":
        payload["proposals"].pop()
    elif mutation == "add_proposal":
        payload["proposals"].append(deepcopy(payload["proposals"][-1]))
    elif mutation == "wrong_route_order":
        # Reverse the canonical Body/Core stage route within one proposal so the
        # per-proposal stage contract fails (BOSMAX owns the family route now).
        payload["proposals"][6]["segments"] = list(reversed(payload["proposals"][6]["segments"]))
    elif mutation == "outside_evidence_island":
        # A generic (PRODUCT_DESCRIPTION) fact is never a route anchor and is never
        # in the locked route's allowed evidence bundle.
        payload["proposals"][0]["segments"][0]["evidence_fact_ids"] = [
            f"fact:{MWCB_PRODUCT_ID}:product_description:0"
        ]

    bundle = await factory.truth_adapter.current(MWCB_PRODUCT_ID)
    with pytest.raises(Exception) as error:
        service._validate_proposals(payload, plan, recipe, bundle)
    assert error.value.code == expected_code

    counts = await _production_counts(MWCB_PRODUCT_ID)
    assert all(
        count == 0
        for table, count in counts.items()
        if table not in {"copy_blueprint_v2", "angle_v3", "storyline_family_v3"}
    )
    assert plan.provider.provider_calls == 0
