"""Round 2 promotion contracts: settings become review-only background plates."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent.services import creative_avatar_recommendation_service as avatar_svc
from agent.services import scene_context_promotion_service as svc
from agent.services import scene_context_registry


def test_preview_candidates_are_empty_background_rows_for_known_cluster():
    preview = svc.preview_scene_context_promotion("Beauty")

    assert preview["dry_run"] is True
    assert preview["source"] == "SCENE_CONTEXT_PROMOTION_R2"
    assert preview["candidate_count"] >= 1
    candidate = preview["candidates"][0]
    row = candidate["row"]
    assert candidate["cluster"] == "Beauty"
    assert row["BackgroundPrompt"].startswith("Background: ")
    assert row["approved_flag"] == "FALSE"
    assert "cluster:beauty" in row["usage_tags"]
    assert "EMPTY_BACKGROUND_ONLY" in row["SafetyBlock"]
    assert "[AVATAR]" not in row["BackgroundPrompt"] + row["PromptV1"]
    assert "[PRODUCT]" not in row["BackgroundPrompt"] + row["PromptV1"]
    assert svc._unsafe_reason(row["BackgroundPrompt"], row["PromptV1"]) is None


def test_all_canonical_clusters_have_deterministic_candidate_or_quarantine_status():
    first = svc.preview_scene_context_promotion()
    second = svc.preview_scene_context_promotion()

    assert first == second
    expected = set(avatar_svc.canonical_clusters())
    assert set(first["cluster_summary"]) == expected
    assert all(
        counts["candidate_count"] + counts["quarantine_count"] >= 1
        for counts in first["cluster_summary"].values()
    )


def test_unsafe_template_is_quarantined_with_exact_reason(monkeypatch):
    monkeypatch.setattr(
        svc._scene_prompts,
        "library_templates",
        lambda: [{
            "template_id": "SCN-UNSAFE-01",
            "cluster": "Beauty",
            "source_category": "Beauty",
            "setting": "[AVATAR] holding a [PRODUCT] beside a price headline",
        }],
    )

    preview = svc.preview_scene_context_promotion()

    assert preview["candidate_count"] == 0
    assert preview["quarantine"] == [{
        "cluster": "Beauty",
        "source_template_id": "SCN-UNSAFE-01",
        "source_category": "Beauty",
        "setting": "[AVATAR] holding a [PRODUCT] beside a price headline",
        "reason": "PLACEHOLDER_AVATAR",
    }]


@pytest.mark.parametrize(
    ("setting", "reason"),
    (
        ("A presenter beside a clean vanity", "PERSON_OR_SUBJECT_INSTRUCTION"),
        ("Shelf display for a product", "PRODUCT_INSTRUCTION"),
        ("Holding area in a bright studio", "ACTION_INSTRUCTION"),
        ("Wall with a logo headline", "RENDERED_TEXT_OR_BRANDING_INSTRUCTION"),
    ),
)
def test_person_action_product_and_text_instructions_are_quarantined(
    monkeypatch, setting, reason
):
    monkeypatch.setattr(
        svc._scene_prompts,
        "library_templates",
        lambda: [{
            "template_id": "SCN-UNSAFE-02",
            "cluster": "Beauty",
            "source_category": "Beauty",
            "setting": setting,
        }],
    )

    preview = svc.preview_scene_context_promotion()

    assert preview["candidate_count"] == 0
    assert preview["quarantine"][0]["reason"] == reason


def test_duplicate_active_scene_is_quarantined_not_promoted(monkeypatch):
    monkeypatch.setattr(
        svc._scene_prompts,
        "library_templates",
        lambda: [{
            "template_id": "SCN-DUP-01",
            "cluster": "Beauty",
            "source_category": "Beauty",
            "setting": "Clean vanity area with soft daylight",
        }],
    )
    monkeypatch.setattr(
        svc._registry,
        "find_duplicate_scene",
        lambda *_: {"scene_code": "SCN_EXISTING"},
    )

    preview = svc.preview_scene_context_promotion()

    assert preview["candidate_count"] == 0
    assert preview["quarantine"][0]["reason"] == "DUPLICATE_ACTIVE_SCENE"
    assert preview["quarantine"][0]["duplicate_scene_code"] == "SCN_EXISTING"


def test_duplicate_candidate_background_is_quarantined(monkeypatch):
    monkeypatch.setattr(
        svc._scene_prompts,
        "library_templates",
        lambda: [
            {
                "template_id": "SCN-DUP-01",
                "cluster": "Beauty",
                "source_category": "Beauty",
                "setting": "Clean vanity area with soft daylight",
            },
            {
                "template_id": "SCN-DUP-02",
                "cluster": "Beauty",
                "source_category": "Beauty",
                "setting": "Clean vanity area with soft daylight",
            },
        ],
    )
    monkeypatch.setattr(svc._registry, "find_duplicate_scene", lambda *_: None)

    preview = svc.preview_scene_context_promotion()

    assert preview["candidate_count"] == 1
    assert preview["quarantine"][0]["reason"] == "DUPLICATE_PROMOTION_CANDIDATE"


def test_preview_never_writes_seed_or_registry_bridge():
    seed = Path(__file__).resolve().parents[2] / "agent" / "authority" / "SCENE_CONTEXT_POOL.csv"
    before_digest = hashlib.sha256(seed.read_bytes()).hexdigest()
    before_pool = scene_context_registry.list_pool()

    svc.preview_scene_context_promotion()

    assert hashlib.sha256(seed.read_bytes()).hexdigest() == before_digest
    assert scene_context_registry.list_pool() == before_pool


def test_generation_services_do_not_import_promotion_layer():
    repo_root = Path(__file__).resolve().parents[2]
    generation_files = (
        "agent/services/canonical_prompt_compiler.py",
        "agent/services/make_video.py",
        "agent/services/workspace_execution_package_service.py",
        "agent/api/flow.py",
    )
    for relative_path in generation_files:
        assert "scene_context_promotion_service" not in (
            repo_root / relative_path
        ).read_text(encoding="utf-8")
