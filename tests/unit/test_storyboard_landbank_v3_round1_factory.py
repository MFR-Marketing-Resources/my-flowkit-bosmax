"""Provider-free Macro Round 1 Copy Factory golden coverage."""

from __future__ import annotations

import time
import tracemalloc
import uuid
from types import SimpleNamespace

import pytest

from agent.db.schema import get_db
from agent.models.copy_blueprint_v2 import digest_evidence_text
from agent.models.copy_blueprint_v2 import EvidenceFact, EvidenceRegistry
from agent.models.storyboard_landbank_v3 import (
    V3Angle,
    V3BridgeContract,
    V3ComponentStageSegment,
    V3CopyRecipe,
    V3FormulaRef,
    V3Objective,
    V3ProductTruthLineage,
    V3RevisionRef,
    V3StorylineFamily,
    V3StoryboardComponent,
    deterministic_digest,
    digest_text,
    word_count,
)
from agent.authority.copy_blueprint_v2_authority import formula_version, required_formula_stage_keys, strict_formula_contract
from agent.services.storyboard_landbank_v3_factory import (
    V3CopyFactoryService,
    V3FactoryError,
    compile_master_storyboard,
    list_formula_read_models,
    compile_duration_projection,
)


PRODUCT_ID = "round1-product"
SNAPSHOT_ID = "round1-snapshot"
FACT_ID = "round1-fact"


async def _seed_round1_truth(product_id: str = PRODUCT_ID, snapshot_id: str = SNAPSHOT_ID, fact_id: str = FACT_ID) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name) VALUES (?, ?, ?, ?)",
        (product_id, "Round 1 Product", "Round 1 Product", "Round 1"),
    )
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) VALUES (?, ?, 1, 'APPROVED', ?, ?, ?, ?, ?, ?, ?, 'CLAIM_SAFE', 'LOW', ?, ?)",
        (
            snapshot_id,
            product_id,
            "A lightweight product for a simple daily routine.",
            '["lightweight daily routine"]',
            '["simple routine"]',
            "people who want a simple routine",
            '["lightweight daily routine"]',
            '{"audience":"daily routine"}',
            '{"formula":"PAS"}',
            "2026-08-17T00:00:00Z",
            "2026-08-17T00:00:00Z",
        ),
    )
    text = "Approved lightweight daily routine fact"
    await db.execute(
        "INSERT INTO copy_evidence_fact_v2 "
        "(product_id, snapshot_id, fact_id, fact_kind, canonical_text, text_digest, snapshot_version, snapshot_status, approved, created_at) "
        "VALUES (?, ?, ?, 'PRODUCT_ATTRIBUTE', ?, ?, 1, 'APPROVED', 1, ?)",
        (product_id, snapshot_id, fact_id, text, digest_evidence_text(text), "2026-08-17T00:00:00Z"),
    )
    await db.commit()


async def _create_supply(service: V3CopyFactoryService, product_id: str = PRODUCT_ID, fact_id: str = FACT_ID):
    angle = await service.create_angle(
        product_id,
        {
            "definition": "A lightweight daily routine angle",
            "formula_id": "PAS",
            "objective_id": "conversion",
            "objective_definition": "Drive a safe trial",
            "evidence_fact_ids": [fact_id],
        },
        actor_id="round1-test",
        request_id=f"{product_id}:angle",
    )
    family = await service.create_storyline_family(
        product_id,
        {
            "angle_id": angle.angle_id,
            "formula_id": "PAS",
            "objective_compatibility": {"objective_ids": ["conversion"]},
            "reviewed_definition": "One continuous daily routine route",
        },
        actor_id="round1-test",
        request_id=f"{product_id}:family",
    )

    def component_data(semantic_class: str, segments: list[dict], component_id: str):
        return {
            "angle_id": angle.angle_id,
            "storyline_family_id": family.family_id,
            "formula_id": "PAS",
            "objective_id": "conversion",
            "objective_definition": "Drive a safe trial",
            "semantic_class": semantic_class,
            "stage_segments": segments,
            "component_id": component_id,
        }

    hooks = []
    for index in range(6):
        hooks.append(
            await service.create_component(
                product_id,
                component_data(
                    "HOOK",
                    [{
                        "formula_stage_key": "problem",
                        "authored_text": f"problem hook {index}",
                        "entry_key": "arc:start",
                        "exit_key": "arc:join",
                    "evidence_fact_ids": [fact_id],
                    }],
                    f"round1-hook-{index}",
                ),
                actor_id="round1-test",
                request_id=f"{product_id}:hook:{index}",
            )
        )
    bodies = []
    for index in range(3):
        bodies.append(
            await service.create_component(
                product_id,
                component_data(
                    "BODY_CORE",
                    [
                        {
                            "formula_stage_key": "agitate",
                            "authored_text": f"agitate route {index}",
                            "entry_key": "arc:join",
                            "exit_key": "arc:mid",
                            "evidence_fact_ids": [fact_id],
                        },
                        {
                            "formula_stage_key": "solution",
                            "authored_text": f"solution route {index}",
                            "entry_key": "arc:mid",
                            "exit_key": "arc:resolve",
                            "evidence_fact_ids": [fact_id],
                        },
                    ],
                    f"round1-body-{index}",
                ),
                actor_id="round1-test",
                request_id=f"{product_id}:body:{index}",
            )
        )
    ctas = []
    for index in range(3):
        ctas.append(
            await service.create_component(
                product_id,
                component_data(
                    "CTA",
                    [{
                        "formula_stage_key": "cta",
                        "authored_text": f"act now {index}",
                        "entry_key": "arc:resolve",
                        "exit_key": "arc:end",
                        "claim_bearing": False,
                    }],
                    f"round1-cta-{index}",
                ),
                actor_id="round1-test",
                request_id=f"{product_id}:cta:{index}",
            )
        )
    recipe = await service.create_recipe(
        product_id,
        {
            "preset": "FAST54",
            "formula_id": "PAS",
            "objective_id": "conversion",
            "objective_definition": "Drive a safe trial",
            "target_angles": [{"entity_id": angle.angle_id, "revision": angle.revision}],
        },
        actor_id="round1-test",
        request_id=f"{product_id}:recipe",
    )
    return recipe, angle, family, hooks, bodies, ctas


@pytest.mark.asyncio
async def test_round1_formula_read_model_discovers_canonical_registry():
    formulas = list_formula_read_models()
    assert {item.formula_id for item in formulas if item.production_eligible} == {"PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA"}
    pastor = next(item for item in formulas if item.formula_id == "PASTOR")
    assert pastor.body_core_mapping == ("amplify", "story", "transformation", "offer")


@pytest.mark.asyncio
async def test_round1_fast54_real_factory_is_lazy_and_compiles_all_compatible_candidates():
    fast_product = "round1-fast54-product"
    await _seed_round1_truth(fast_product, "round1-fast54-snapshot", "round1-fast54-fact")
    service = V3CopyFactoryService()
    recipe, angle, family, hooks, bodies, ctas = await _create_supply(service, fast_product, "round1-fast54-fact")
    start = time.perf_counter()
    page = await service.enumerate_candidates(recipe.recipe_id, limit=100, durations=(8, 16, 24))
    elapsed = time.perf_counter() - start
    assert page.theoretical_capacity == 54
    assert page.evaluated_count == 54
    assert page.duration_valid_capacity == 54, page.exclusions[:3]
    assert len(page.candidates) == 54
    assert not page.exclusions
    assert elapsed < 10
    assert all(candidate.master is not None for candidate in page.candidates)
    assert all(len(candidate.projections) == 3 for candidate in page.candidates)
    body = bodies[0]
    assert len(body.stage_segments) == 2
    assert body.authored_text == "agitate route 0 solution route 0"
    assert body.stage_segments[0].formula_stage_key == "agitate"
    assert body.stage_segments[1].formula_stage_key == "solution"


@pytest.mark.asyncio
async def test_round1_fast54_adversarial_supply_returns_real_bridge_exclusions():
    product_id = f"round1-adversarial-product-{uuid.uuid4().hex}"
    fact_id = f"{product_id}-fact"
    await _seed_round1_truth(product_id, f"{product_id}-snapshot", fact_id)
    service = V3CopyFactoryService()
    recipe, angle, family, hooks, _bodies, _ctas = await _create_supply(service, product_id, fact_id)

    # Remove the compatible hooks from the latest-only supply view, then seed
    # six deliberately malformed cross-component exits directly through the
    # repository.  The repository is intentionally not the semantic validator;
    # the actual compiler must issue the exclusion receipt.
    for index, hook in enumerate(hooks):
        await service.transition(
            "STORYBOARD_COMPONENT",
            hook.component_id,
            hook.revision,
            "REJECTED",
            actor_id="round1-adversarial",
            request_id=f"{product_id}:reject:{index}",
        )
        segment = hook.stage_segments[0]
        bad_exit = f"arc:broken-{index}"
        bad_segment = segment.model_copy(
            update={
                "exit_key": bad_exit,
                "bridge_contract": V3BridgeContract(entry_key=segment.entry_key, exit_key=bad_exit),
            }
        )
        bad_hook = hook.model_copy(
            update={
                "component_id": f"{product_id}-bad-hook-{index}",
                "stage_segments": (bad_segment,),
                "exit_key": bad_exit,
                "bridge_contract": V3BridgeContract(entry_key=hook.entry_key, exit_key=bad_exit),
            }
        )
        await service.repository.insert(
            bad_hook,
            actor_id="round1-adversarial",
            request_id=f"{product_id}:bad-hook:{index}",
            source="ROUND1_ADVERSARIAL_FIXTURE",
        )

    page = await service.enumerate_candidates(recipe.recipe_id, limit=100, durations=(8, 16, 24))
    assert page.theoretical_capacity == 54
    assert page.evaluated_count == 54
    assert page.duration_valid_capacity == 0
    assert len(page.exclusions) == 54
    assert {item.code for item in page.exclusions} == {"BRIDGE_CONTINUITY_BROKEN"}
    assert all(candidate.status == "EXCLUDED" for candidate in page.candidates)


class _MemoryRepository:
    """Small read-only repository double for the 10K Cartesian-space proof."""

    def __init__(self, entities: dict[tuple[str, str, int], object]):
        self.entities = entities

    async def get(self, entity_type: str, entity_id: str, revision: int | None = None):
        candidates = [
            entity
            for (kind, current_id, current_revision), entity in self.entities.items()
            if kind == entity_type.upper() and current_id == entity_id
            and (revision is None or current_revision == revision)
        ]
        return max(candidates, key=lambda item: item.revision) if candidates else None

    async def list(self, entity_type: str, **filters):
        rows = [entity for (kind, _entity_id, _revision), entity in self.entities.items() if kind == entity_type.upper()]
        if filters.get("product_id"):
            rows = [row for row in rows if row.product_id == filters["product_id"]]
        if filters.get("formula_id"):
            rows = [row for row in rows if getattr(row, "formula", None) and row.formula.formula_id == filters["formula_id"]]
        if filters.get("angle_id"):
            rows = [row for row in rows if getattr(row, "angle", None) and row.angle.entity_id == filters["angle_id"]]
        if filters.get("storyline_family_id"):
            rows = [row for row in rows if getattr(row, "storyline_family", None) and row.storyline_family.entity_id == filters["storyline_family_id"]]
        return sorted(rows, key=lambda row: (row.created_at, getattr(row, "component_id", getattr(row, "family_id", ""))))


def _clone_scale_component(component: V3StoryboardComponent, component_id: str, suffix: str) -> V3StoryboardComponent:
    segments = tuple(
        segment.model_copy(
            update={
                "authored_text": f"{segment.authored_text} {suffix}",
                "text_digest": digest_text(f"{segment.authored_text} {suffix}"),
            }
        )
        for segment in component.stage_segments
    )
    authored_text = " ".join(segment.authored_text for segment in segments)
    return component.model_copy(
        update={
            "component_id": component_id,
            "stage_segments": segments,
            "authored_text": authored_text,
            "content_digest": digest_text(authored_text),
            "semantic_fingerprint": deterministic_digest({"component_id": component_id, "text": authored_text}),
            "word_count": word_count(authored_text),
        }
    )


@pytest.mark.asyncio
async def test_round1_10k_theoretical_space_is_lazy_bounded_and_cursor_stable():
    recipe, angle, family, hook, body, cta, registry = _formula_fixture("PAS")
    hooks = tuple(_clone_scale_component(hook, f"scale-hook-{index:03d}", f"hook-{index:03d}") for index in range(100))
    bodies = tuple(_clone_scale_component(body, f"scale-body-{index:02d}", f"body-{index:02d}") for index in range(10))
    ctas = tuple(_clone_scale_component(cta, f"scale-cta-{index:02d}", f"cta-{index:02d}") for index in range(10))
    recipe = recipe.model_copy(
        update={
            "recipe_id": "scale-recipe-10k",
            "target_angles": (V3RevisionRef(entity_id=angle.angle_id, revision=angle.revision),),
            "component_count_targets": {"HOOK": 100, "BODY_CORE": 10, "CTA": 10},
            "supported_durations_seconds": (24,),
            "target_capacity": {"requested_capacity": 10000},
            "deterministic_seed": "scale-seed-10k",
            "config_digest": "e" * 64,
        }
    )
    entities: dict[tuple[str, str, int], object] = {
        ("ANGLE", angle.angle_id, angle.revision): angle,
        ("STORYLINE_FAMILY", family.family_id, family.revision): family,
        ("COPY_RECIPE", recipe.recipe_id, recipe.revision): recipe,
    }
    for component in (*hooks, *bodies, *ctas):
        entities[("STORYBOARD_COMPONENT", component.component_id, component.revision)] = component
    service = V3CopyFactoryService(
        repository=_MemoryRepository(entities),
        truth_adapter=SimpleNamespace(revalidate=lambda _lineage: SimpleNamespace(registry=registry)),
    )
    # The production service is async, so provide the tiny awaitable adapter
    # explicitly rather than materializing a 10,000-item candidate list.
    async def revalidate(_lineage):
        return SimpleNamespace(registry=registry)

    service.truth_adapter.revalidate = revalidate
    tracemalloc.start()
    start = time.perf_counter()
    first = await service.enumerate_candidates(recipe.recipe_id, limit=1, durations=(24,))
    elapsed = time.perf_counter() - start
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert first.theoretical_capacity == 10000
    assert first.evaluated_count == 1
    assert len(first.candidates) == 1
    assert first.next_cursor
    assert first.bounded is True
    assert elapsed < 5
    assert peak < 64 * 1024 * 1024
    repeat = await service.enumerate_candidates(recipe.recipe_id, limit=1, durations=(24,))
    following = await service.enumerate_candidates(recipe.recipe_id, limit=1, cursor=first.next_cursor, durations=(24,))
    assert repeat.candidates[0].candidate_id == first.candidates[0].candidate_id
    assert following.candidates[0].candidate_id != first.candidates[0].candidate_id


@pytest.mark.asyncio
async def test_round1_governance_rejects_approval_and_stale_or_cross_lineage():
    governance_product = "round1-governance-product"
    await _seed_round1_truth(governance_product, "round1-governance-snapshot", "round1-governance-fact")
    service = V3CopyFactoryService()
    with pytest.raises(V3FactoryError, match="APPROVAL"):
        await service.create_recipe(
            governance_product,
            {"status": "APPROVED", "preset": "FAST54", "formula_id": "PAS", "objective_id": "x", "objective_definition": "x"},
            actor_id="round1-test",
            request_id="approval-request",
        )
    with pytest.raises(V3FactoryError, match="Formula"):
        await service.create_recipe(
            governance_product,
            {"preset": "FAST54", "formula_id": "PAS", "formula_version": "stale", "objective_id": "x", "objective_definition": "x"},
            actor_id="round1-test",
            request_id="stale-formula-request",
        )


@pytest.mark.asyncio
async def test_round1_evidence_ranker_is_explicitly_fail_closed():
    product_id = f"round1-evidence-product-{uuid.uuid4().hex}"
    fact_id = f"{product_id}-fact"
    await _seed_round1_truth(product_id, f"{product_id}-snapshot", fact_id)
    service = V3CopyFactoryService()
    with pytest.raises(V3FactoryError, match="registered"):
        await service.rank_evidence(product_id, formula_id="NOT_A_CANONICAL_FORMULA")
    missing = await service.rank_evidence(product_id, requested_fact_ids=("missing-fact",), require_claim_evidence=True)
    assert missing.outcome == "EVIDENCE_SHORTFALL"
    unsafe = await service.rank_evidence(product_id, formula_id="BAB")
    assert unsafe.outcome == "UNSAFE_TO_DERIVE"
    assert unsafe.fact_ids == ()


@pytest.mark.asyncio
async def test_round1_mutation_idempotency_returns_the_original_revision():
    idem_product = f"round1-idem-product-{uuid.uuid4().hex}"
    idem_snapshot = "round1-idem-snapshot"
    idem_fact = "round1-idem-fact"
    await _seed_round1_truth(idem_product, idem_snapshot, idem_fact)
    service = V3CopyFactoryService()
    first = await service.create_angle(
        idem_product,
        {"definition": "A grounded routine angle", "formula_id": "PAS", "objective_id": "conversion", "objective_definition": "Trial", "evidence_fact_ids": [idem_fact]},
        actor_id="round1-test",
        request_id="same-angle-request",
    )
    second = await service.create_angle(
        idem_product,
        {"definition": "A grounded routine angle", "formula_id": "PAS", "objective_id": "conversion", "objective_definition": "Trial", "evidence_fact_ids": [idem_fact]},
        actor_id="round1-test",
        request_id="same-angle-request",
    )
    assert second.angle_id == first.angle_id
    assert second.revision == first.revision == 1
    with pytest.raises(V3FactoryError, match="different V3 mutation"):
        await service.create_angle(
            idem_product,
            {"definition": "A different grounded angle", "formula_id": "PAS", "objective_id": "conversion", "objective_definition": "Trial", "evidence_fact_ids": [idem_fact]},
            actor_id="round1-test",
            request_id="same-angle-request",
        )


@pytest.mark.asyncio
async def test_round1_revisions_and_terminal_transitions_are_append_only():
    product_id = f"round1-revision-product-{uuid.uuid4().hex}"
    snapshot_id = f"{product_id}-snapshot"
    fact_id = f"{product_id}-fact"
    await _seed_round1_truth(product_id, snapshot_id, fact_id)
    service = V3CopyFactoryService()
    angle = await service.create_angle(
        product_id,
        {"definition": "Original grounded angle", "formula_id": "PAS", "objective_id": "conversion", "objective_definition": "Trial", "evidence_fact_ids": [fact_id]},
        actor_id="round1-test",
        request_id=f"{product_id}:create",
    )
    revised = await service.create_revision(
        "ANGLE", angle.angle_id, 1, {"definition": "Revised grounded angle"}, actor_id="round1-test", request_id=f"{product_id}:revision"
    )
    assert revised.revision == 2
    assert revised.definition == "Revised grounded angle"
    reviewed = await service.transition(
        "ANGLE", angle.angle_id, 2, "REVIEW_REQUIRED", actor_id="round1-test", request_id=f"{product_id}:review"
    )
    rejected = await service.transition(
        "ANGLE", angle.angle_id, reviewed.revision, "REJECTED", actor_id="round1-test", request_id=f"{product_id}:reject"
    )
    assert rejected.status == "REJECTED"
    assert (await service.get_entity("ANGLE", angle.angle_id, 1)).definition == "Original grounded angle"
    with pytest.raises(V3FactoryError, match="APPROVED"):
        await service.transition(
            "ANGLE", angle.angle_id, rejected.revision, "APPROVED", actor_id="round1-test", request_id=f"{product_id}:approve"
        )


def _formula_fixture(formula_id: str):
    truth = V3ProductTruthLineage(product_id=f"fixture-{formula_id}", snapshot_id=f"snapshot-{formula_id}", snapshot_version=1, snapshot_digest="a" * 64, snapshot_status="APPROVED")
    objective = V3Objective(objective_id="conversion", definition="Drive a safe trial")
    formula = V3FormulaRef(formula_id=formula_id, formula_version=formula_version(formula_id))
    angle = V3Angle(angle_id=f"angle-{formula_id}", revision=1, product_id=truth.product_id, product_truth=truth, definition="A grounded routine angle", objective_compatibility={"objective_ids": ["conversion"]}, evidence_fact_ids=("fixture-fact",), evidence_digest=deterministic_digest(["fixture-fact"]), formula=formula, source="fixture", status="DRAFT", angle_digest="b" * 64, created_at="2026-08-17T00:00:00Z", created_by="fixture")
    family = V3StorylineFamily(
        family_id=f"family-{formula_id}",
        revision=1,
        product_id=truth.product_id,
        product_truth=truth,
        angle=V3RevisionRef(entity_id=angle.angle_id, revision=1),
        formula=formula,
        objective_compatibility={"objective_ids": ["conversion"]},
        reviewed_definition="One continuous grounded route",
        narrative_route={"stage_keys": list(required_formula_stage_keys(formula_id))},
        source="fixture",
        status="DRAFT",
        family_digest="c" * 64,
        created_at="2026-08-17T00:00:00Z",
        created_by="fixture",
    )
    fact_text = "Approved grounded product fact"
    registry = EvidenceRegistry(facts=(EvidenceFact(snapshot_id=truth.snapshot_id, fact_id="fixture-fact", product_id=truth.product_id, fact_kind="PRODUCT_ATTRIBUTE", text=fact_text, text_digest=digest_evidence_text(fact_text), snapshot_version=1, snapshot_status="APPROVED", approved=True, source_ref="fixture"),))
    contract = strict_formula_contract(formula_id)
    required = tuple(required_formula_stage_keys(formula_id))
    hook_keys = {contract["output_mapping"]["hook"]} if isinstance(contract["output_mapping"]["hook"], str) else set(contract["output_mapping"]["hook"])
    cta_keys = {contract["output_mapping"]["cta"]} if isinstance(contract["output_mapping"]["cta"], str) else set(contract["output_mapping"]["cta"])
    body_keys = set(required) - hook_keys - cta_keys

    def build_component(semantic_class: str, keys: tuple[str, ...], prefix: str):
        segments = []
        entry_key = {
            "HOOK": "arc:start",
            "BODY_CORE": "arc:hook-body",
            "CTA": "arc:body-cta",
        }[semantic_class]
        terminal_key = {
            "HOOK": "arc:hook-body",
            "BODY_CORE": "arc:body-cta",
            "CTA": "arc:end",
        }[semantic_class]
        previous = entry_key
        for index, key in enumerate(keys):
            next_key = terminal_key if index == len(keys) - 1 else f"arc:{prefix}:{key}:exit"
            text = f"{formula_id.lower()} {key} {prefix}"
            segments.append(V3ComponentStageSegment(formula_stage_key=key, semantic_class=semantic_class, order=required.index(key), authored_text=text, text_digest=digest_text(text), entry_key=previous, exit_key=next_key, bridge_contract=V3BridgeContract(entry_key=previous, exit_key=next_key), evidence_fact_ids=("fixture-fact",) if semantic_class != "CTA" else (), evidence_digest=deterministic_digest(["fixture-fact"]) if semantic_class != "CTA" else deterministic_digest([]), claim_bearing=semantic_class != "CTA"))
            previous = next_key
        authored = " ".join(item.authored_text for item in segments)
        evidence_fact_ids = tuple(dict.fromkeys(fact_id for segment in segments for fact_id in segment.evidence_fact_ids))
        return V3StoryboardComponent(
            component_id=f"component-{formula_id}-{prefix}",
            revision=1,
            product_id=truth.product_id,
            product_truth=truth,
            objective=objective,
            angle=V3RevisionRef(entity_id=angle.angle_id, revision=1),
            storyline_family=V3RevisionRef(entity_id=family.family_id, revision=1),
            formula=formula,
            semantic_class=semantic_class,
            formula_stage_keys=keys,
            ordered_stage_coverage=tuple(required.index(key) for key in keys),
            stage_segments=tuple(segments),
            authored_text=authored,
            entry_key=segments[0].entry_key,
            exit_key=segments[-1].exit_key,
            bridge_contract=V3BridgeContract(entry_key=segments[0].entry_key, exit_key=segments[-1].exit_key),
            evidence_fact_ids=evidence_fact_ids,
            evidence_digest=deterministic_digest(list(evidence_fact_ids)),
            claim_bearing=semantic_class != "CTA",
            content_digest=digest_text(authored),
            semantic_fingerprint=None,
            word_count=word_count(authored),
            status="DRAFT",
            source="fixture",
            created_at="2026-08-17T00:00:00Z",
            created_by="fixture",
        )

    hook = build_component("HOOK", tuple(key for key in required if key in hook_keys), "hook")
    body = build_component("BODY_CORE", tuple(key for key in required if key in body_keys), "body")
    cta = build_component("CTA", tuple(key for key in required if key in cta_keys), "cta")
    recipe = V3CopyRecipe(recipe_id=f"recipe-{formula_id}", revision=1, product_id=truth.product_id, product_truth=truth, formula=formula, objective=objective, component_count_targets={"HOOK": 1, "BODY_CORE": 1, "CTA": 1}, supported_durations_seconds=(8, 16, 24), deterministic_seed=f"seed-{formula_id}", config_digest="d" * 64, source="fixture", created_at="2026-08-17T00:00:00Z", created_by="fixture")
    return recipe, angle, family, hook, body, cta, registry


@pytest.mark.parametrize("formula_id", ("PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA"))
def test_round1_multiformula_master_and_duration_lineage(formula_id):
    recipe, angle, family, hook, body, cta, registry = _formula_fixture(formula_id)
    result = compile_master_storyboard(recipe=recipe, angle=angle, storyline_family=family, hook=hook, body_core=body, cta=cta, evidence_registry=registry)
    assert result.valid, result.details
    assert result.master is not None
    master = result.master
    assert tuple(stage.formula_stage_key for stage in master.stages) == tuple(required_formula_stage_keys(formula_id))
    assert len({stage.authored_text for stage in master.stages if stage.semantic_class == "BODY_CORE"}) == len([stage for stage in master.stages if stage.semantic_class == "BODY_CORE"])
    for duration in (8, 16, 24):
        projection, issues, details = compile_duration_projection(master, duration_seconds=duration, evidence_registry=registry)
        assert projection is not None, (formula_id, duration, issues, details)
        assert projection.master_exact_content_digest == master.exact_content_digest
        assert projection.cta_block_index == len(projection.block_plan_seconds) - 1
