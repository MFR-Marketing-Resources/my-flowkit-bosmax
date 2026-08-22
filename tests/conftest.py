"""Shared pytest fixtures for Flow Kit tests."""

import os

# The pre-cutover suites exercise historical CopySet APIs and flag-OFF golden
# behavior.  ADR-011 permits that only in explicit test/maintenance mode.  New
# V2-only tests remove this flag locally to prove the production default.
os.environ.setdefault("COPY_LEGACY_MAINTENANCE_MODE", "1")
os.environ.setdefault("COPY_BLUEPRINT_V2_ENABLED", "0")

import pytest
from agent.config import DB_PATH
from agent.db.schema import init_db, close_db, get_db

def _unlink_db_safe() -> None:
    """Remove the test DB file, tolerating WinError 32 (file still held by OS)."""
    if DB_PATH == ":memory:":
        return
    if not (getattr(DB_PATH, "exists", None) and DB_PATH.exists()):
        return
    try:
        DB_PATH.unlink()
    except PermissionError:
        pass


@pytest.fixture(autouse=True)
async def db_setup():
    _unlink_db_safe()
    await init_db()
    # Active production API tests use a real registered profile rather than a
    # generic actor fallback. This is test authority, not application seed data.
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO staff_profile "
        "(staff_id, display_name, active, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (
            "staff_pytest_operator",
            "Pytest Operator",
            1,
            "2026-08-01T00:00:00Z",
            "2026-08-01T00:00:00Z",
        ),
    )
    await db.commit()
    yield
    await close_db()
    _unlink_db_safe()


async def make_product_copy_eligible(product_id: str) -> str:
    """PI-FINAL-B04 test helper: give a seeded product an accepted, claim-safe,
    copy-critical-complete Product Intelligence snapshot so it passes the
    fail-closed COPY_ELIGIBLE gate. Returns the snapshot_id."""
    from agent.db import crud
    from agent.models.product_intelligence_review_draft import (
        ProductIntelligenceReviewDraftApproveRequest,
    )
    from agent.services import product_intelligence_review_draft_service as _svc

    draft = await crud.create_product_intelligence_review_draft(
        product_id=product_id,
        review_status="READY_FOR_REVIEW",
        # COPY-CORRECTIVE-B1: the fixture PI carries a real vocabulary so the
        # standard skincare test copy (kulit / formula / menyerap / kombinasi /
        # rutin / segar / ringan) actually GROUNDS at approval, exercising the
        # grounding gate rather than trivially failing it.
        product_description="Serum penjagaan kulit yang menyerap cepat, formula ringan untuk kulit kombinasi dan rutin harian; melembapkan kulit sepanjang hari.",
        benefits_json='["melembapkan kulit sepanjang hari", "menyerap cepat tanpa melekit", "formula ringan untuk kulit kombinasi", "kulit nampak segar"]',
        usp_json='["untuk kulit kombinasi", "formula ringan menyerap cepat", "rutin harian ringkas"]',
        usage_text="Sapu pada kulit bersih setiap hari mengikut rutin harian.",
        ingredients_text="As listed on the packaging.",
        warnings_text="Keep away from direct sunlight.",
        target_customer_text="wanita yang mahu kulit segar dan lembap sepanjang hari",
        allowed_claims_json='["Product type: Skincare / Serum"]',
        buyer_persona_snapshot_json='{"audience": "wanita penjagaan kulit", "needs": ["kulit segar", "formula ringan"]}',
        copy_strategy_summary_json='{"angles": ["kulit segar sepanjang hari", "formula ringan menyerap cepat"], "recommended_formula": "FAB"}',
        source_urls_json='{"primary_listing": "https://example.com/listing"}',
        image_evidence_json='{"main": "https://example.com/img.jpg"}',
        claim_gate="CLAIM_SAFE",
        claim_risk_level="LOW",
    )
    snapshot = await _svc.approve_review_draft(
        draft["draft_id"],
        ProductIntelligenceReviewDraftApproveRequest(approved_by="pytest-eligible", claim_review_acknowledged=True),
    )
    return snapshot.snapshot_id


@pytest.fixture
def sample_uuid():
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def sample_cams_id():
    """A CAMS... base64 mediaGenerationId — NOT a valid UUID."""
    return "CAMSJDkxMTYwNzM4LTRlMjYtNDVkZi05OTMz"


@pytest.fixture
def sample_image_success(sample_uuid):
    """Successful image generation response from Google Flow API."""
    return {
        "data": {
            "media": [{
                "name": sample_uuid,
                "image": {
                    "generatedImage": {
                        "mediaId": sample_uuid,
                        "fifeUrl": f"https://lh3.googleusercontent.com/image/{sample_uuid}?sqp=params",
                    }
                }
            }]
        }
    }


@pytest.fixture
def sample_image_success_no_uuid():
    """Image response where media[0].name is NOT a UUID (CAMS format)."""
    return {
        "data": {
            "media": [{
                "name": "CAMSJDkxMTYwNzM4LTRlMjYtNDVkZi05OTMz",
                "image": {
                    "generatedImage": {
                        "mediaId": "CAMSJDkxMTYwNzM4",
                        "fifeUrl": "https://lh3.googleusercontent.com/image/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee?sqp=params",
                    }
                }
            }]
        }
    }


@pytest.fixture
def sample_video_success(sample_uuid):
    """Successful video generation response."""
    return {
        "data": {
            "operations": [{
                "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
                "operation": {
                    "name": "operations/video-123",
                    "metadata": {
                        "video": {
                            "mediaId": sample_uuid,
                            "fifeUrl": f"https://storage.googleapis.com/video/{sample_uuid}",
                        }
                    }
                }
            }]
        }
    }


@pytest.fixture
def sample_error_response():
    """Error response from Google Flow API."""
    return {"error": "Internal error encountered"}


@pytest.fixture
def sample_nested_error():
    """Error nested inside data.error."""
    return {
        "data": {
            "error": {
                "code": 403,
                "message": "caller does not have permission",
            }
        }
    }


@pytest.fixture
def sample_scene_row(sample_uuid):
    """A flat DB row for a scene with completed vertical image."""
    return {
        "id": "scene-001",
        "video_id": "video-001",
        "display_order": 0,
        "prompt": "Hero walks into the castle courtyard at dawn",
        "image_prompt": None,
        "video_prompt": "0-3s: Hero pushes open gate. 3-6s: Looks up. 6-8s: Zoom on sword.",
        "character_names": '["Hero", "Castle"]',
        "parent_scene_id": None,
        "chain_type": "ROOT",
        "vertical_image_media_id": sample_uuid,
        "vertical_image_url": f"https://example.com/image/{sample_uuid}",
        "vertical_image_status": "COMPLETED",
        "vertical_video_media_id": None,
        "vertical_video_url": None,
        "vertical_video_status": "PENDING",
        "vertical_upscale_media_id": None,
        "vertical_upscale_url": None,
        "vertical_upscale_status": "PENDING",
        "vertical_end_scene_media_id": None,
        "horizontal_image_media_id": None,
        "horizontal_image_url": None,
        "horizontal_image_status": "PENDING",
        "horizontal_video_media_id": None,
        "horizontal_video_url": None,
        "horizontal_video_status": "PENDING",
        "horizontal_upscale_media_id": None,
        "horizontal_upscale_url": None,
        "horizontal_upscale_status": "PENDING",
        "horizontal_end_scene_media_id": None,
        "trim_start": None,
        "trim_end": None,
        "duration": None,
        "created_at": "2026-04-01T00:00:00",
        "updated_at": "2026-04-01T00:00:00",
    }


@pytest.fixture
def sample_character_row(sample_uuid):
    """A flat DB row for a character entity."""
    return {
        "id": "char-001",
        "name": "Hero",
        "entity_type": "character",
        "description": "A brave warrior with golden armor",
        "image_prompt": "Full body portrait of a warrior in golden armor, front-facing, neutral background",
        "voice_description": "Deep calm heroic voice",
        "reference_image_url": f"https://example.com/ref/{sample_uuid}",
        "media_id": sample_uuid,
        "created_at": "2026-04-01T00:00:00",
        "updated_at": "2026-04-01T00:00:00",
    }


async def seed_product_ready(db, product_id: str):
    """Insert a minimal product row for testing that passes all safety gates."""
    await db.execute(
        "INSERT OR IGNORE INTO product "
        "(id, raw_product_title, product_display_name, product_short_name, image_url, asset_status, "
        "category, subcategory, type, product_type, silo, trigger_id, formula, copywriting_angle, claim_risk_level, "
        "physics_class, recommended_grip, handling_notes, camera_handling_notes, scene_context, camera_style, "
        "camera_behavior, camera_shot, section_4_hint, section_5_physics_hint, section_6_copy_hint, section_9_overlay_hint) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (product_id, "Test Diaper Pack", "Test Diaper Pack", "Diapers", "http://example.com/test.jpg", "DOWNLOADED",
         "Baby Care", "Diapering", "Pants", "STEALTH", "baby_care_universal_01", "TRUST_01", "PAS", "Trust-led framing", "LOW",
         "soft_pack", "two-hand hold", "stable handling", "clean reveal", "nursery shelf", "product close-up",
         "slow push-in", "hero shot", "reveal hint", "physics hint", "copy hint", "overlay hint")
    )
    await db.commit()
