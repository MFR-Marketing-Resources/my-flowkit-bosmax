from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.bosmax_authority import router
from agent.models.asset_registry import AssetOption, AssetOptionsResponse


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _asset_response(asset_type: str, options: list[AssetOption], source_status: str = "REPO_VERIFIED") -> AssetOptionsResponse:
    return AssetOptionsResponse(
        asset_type=asset_type,
        options=options,
        warnings=[],
        provenance={"scope": "test"},
        source_status=source_status,
        empty_reason=None,
    )


def test_prompt_tool_context_returns_normalized_groups_and_explicit_missing_sources(monkeypatch):
    async def fake_list_products(*args, **kwargs):
        return [{"id": "prod-001", "product_display_name": "Atlas Bottle"}]

    async def fake_enrich_product(product):
        return {
            "id": "prod-001",
            "product_display_name": "Atlas Bottle",
            "raw_product_title": "Atlas Bottle Original",
            "category": "Beauty",
            "subcategory": "Skincare",
            "type": "Serum",
            "product_type": "Beauty Serum",
            "product_type_id": "BEAUTY_SERUM",
            "source": "FASTMOSS",
            "claim_risk_level": "LOW",
            "trigger_id": "TRUST_01",
            "silo": "beauty_mass_01",
            "formula": "PAS",
            "copywriting_angle": "Trust-led glow",
            "scene_context": "Premium vanity table.",
            "camera_style": "Macro beauty close-up.",
            "camera_behavior": "Slow push-in.",
            "section_9_overlay_hint": "Minimal lower-third.",
            "section_5_product_physics_prompt": "Glass dropper tilt with liquid realism.",
            "handling_notes": "Keep label front-facing and grip the bottle lightly.",
            "recommended_grip": "Two-finger bottle hold",
            "camera_shot": "Macro hero shot",
            "section_4_hint": "Show serum texture.",
            "section_5_physics_hint": "Keep droplet viscosity grounded.",
            "section_6_copy_hint": "No medical claims.",
        }

    async def fake_registry_listing(asset_type: str):
        if asset_type == "CHARACTER":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="character:atlas-presenter",
                        asset_type="CHARACTER",
                        label="Atlas Presenter",
                        description="Repo-backed character row",
                        metadata={},
                        compatibility_tags=[],
                        source_status="REPO_VERIFIED",
                    )
                ],
            )
        if asset_type == "SCENE_CONTEXT":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="scene:vanity",
                        asset_type="SCENE_CONTEXT",
                        label="Premium vanity table.",
                        description="Derived scene",
                        metadata={},
                        compatibility_tags=[],
                        source_status="DERIVED_FROM_PRODUCT_DATA",
                    )
                ],
                source_status="DERIVED_FROM_PRODUCT_DATA",
            )
        if asset_type == "CAMERA_STYLE":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="camera-style:macro",
                        asset_type="CAMERA_STYLE",
                        label="Macro beauty close-up.",
                        description="Derived camera style",
                        metadata={},
                        compatibility_tags=[],
                        source_status="DERIVED_FROM_PRODUCT_DATA",
                    )
                ],
                source_status="DERIVED_FROM_PRODUCT_DATA",
            )
        if asset_type == "CAMERA_BEHAVIOR":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="camera-behavior:push-in",
                        asset_type="CAMERA_BEHAVIOR",
                        label="Slow push-in.",
                        description="Derived camera behavior",
                        metadata={},
                        compatibility_tags=[],
                        source_status="DERIVED_FROM_PRODUCT_DATA",
                    )
                ],
                source_status="DERIVED_FROM_PRODUCT_DATA",
            )
        if asset_type == "COPYWRITING_FORMULA":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="formula:PAS",
                        asset_type="COPYWRITING_FORMULA",
                        label="PAS",
                        description="Repo formula",
                        metadata={},
                        compatibility_tags=[],
                        source_status="REPO_VERIFIED",
                    )
                ],
            )
        if asset_type == "PRODUCT_HANDLING":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="handling:serum",
                        asset_type="PRODUCT_HANDLING",
                        label="Front-facing bottle support",
                        description="Rule-backed handling",
                        metadata={},
                        compatibility_tags=[],
                        source_status="REPO_VERIFIED",
                    )
                ],
            )
        if asset_type == "PRODUCT_PHYSICS":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="physics:serum",
                        asset_type="PRODUCT_PHYSICS",
                        label="Glass dropper realism",
                        description="Rule-backed physics",
                        metadata={},
                        compatibility_tags=[],
                        source_status="REPO_VERIFIED",
                    )
                ],
            )
        if asset_type == "PRODUCT_REFERENCE":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="product:prod-001",
                        asset_type="PRODUCT_REFERENCE",
                        label="Atlas Bottle",
                        description="Derived product reference",
                        metadata={},
                        compatibility_tags=[],
                        source_status="DERIVED_FROM_PRODUCT_DATA",
                    )
                ],
                source_status="DERIVED_FROM_PRODUCT_DATA",
            )
        if asset_type == "STYLE_REFERENCE":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="style:realistic",
                        asset_type="STYLE_REFERENCE",
                        label="realistic",
                        description="Built-in material",
                        metadata={},
                        compatibility_tags=[],
                        source_status="REPO_VERIFIED",
                    )
                ],
            )
        if asset_type == "OVERLAY_TEMPLATE":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="overlay:minimal-lower-third",
                        asset_type="OVERLAY_TEMPLATE",
                        label="Minimal lower-third.",
                        description="Product-derived overlay hint",
                        metadata={},
                        compatibility_tags=[],
                        source_status="DERIVED_FROM_PRODUCT_DATA",
                    )
                ],
                source_status="DERIVED_FROM_PRODUCT_DATA",
            )
        if asset_type == "LANGUAGE":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="language:Malay",
                        asset_type="LANGUAGE",
                        label="Malay",
                        description="Input slot",
                        metadata={},
                        compatibility_tags=[],
                        source_status="INPUT_SLOT_ONLY",
                    )
                ],
                source_status="INPUT_SLOT_ONLY",
            )
        if asset_type == "PLATFORM":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="platform:TikTok",
                        asset_type="PLATFORM",
                        label="TikTok",
                        description="Input slot",
                        metadata={},
                        compatibility_tags=[],
                        source_status="INPUT_SLOT_ONLY",
                    )
                ],
                source_status="INPUT_SLOT_ONLY",
            )
        if asset_type == "ENGINE_PROFILE":
            return _asset_response(
                asset_type,
                [
                    AssetOption(
                        asset_id="engine:VEO_3_1",
                        asset_type="ENGINE_PROFILE",
                        label="VEO_3_1",
                        description="Input slot",
                        metadata={},
                        compatibility_tags=[],
                        source_status="INPUT_SLOT_ONLY",
                    )
                ],
                source_status="INPUT_SLOT_ONLY",
            )
        return _asset_response(asset_type, [])

    class FakeOperatorPack:
        available = True
        files = [
            "MASTER_IGNITION_TEMPLATE.yaml",
            "SCRIPT_REGISTRY_UNIFIED.yaml",
            "FASTMOSS_COMBINED_10_FILES_WORKBOOK.xlsx",
        ]
        avatars = ["avatar_operator_01"]
        headwear_styles = ["hijab_soft_neutral"]
        camera_styles = ["Operator beauty close-up"]
        triggers = ["TRUST_01"]
        silos = ["beauty_mass_01"]
        formulas = ["PAS"]
        language_defaults = ["Malay"]
        engines = ["VEO_3_1"]
        durations_by_engine = {"VEO_3_1": ["8", "16"]}
        products = [
            type(
                "OperatorProductShape",
                (),
                {
                    "product_id": "prod-001",
                    "product_name": "Atlas Bottle",
                    "raw_product_title": "Atlas Bottle Original",
                    "product_display_name": "Atlas Bottle",
                    "product_short_name": "Atlas",
                    "hook": "Glow starts here",
                    "usp_1": "Hydration-first",
                    "usp_2": "Clean finish",
                    "usp_3": "Daily texture",
                    "cta": "Shop now",
                    "copywriting_angle": "Trust-led glow",
                },
            )()
        ]

    monkeypatch.setattr("agent.services.bosmax_authority_registry.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.services.bosmax_authority_registry.enrich_product", fake_enrich_product)
    monkeypatch.setattr("agent.services.bosmax_authority_registry._registry_listing", fake_registry_listing)
    monkeypatch.setattr(
        "agent.services.bosmax_authority_registry._operator_pack_summary",
        lambda: (FakeOperatorPack(), []),
    )
    monkeypatch.setattr(
        "agent.services.bosmax_authority_registry._authority_file_presence",
        lambda: {
            "SOVEREIGN_01_MASTER_SCHEMA.yaml": False,
            "SOVEREIGN_03_CORE_LOGIC.yaml": False,
            "SATELLITE_04D_SCENE_CAMERA_ORCHESTRATION_FINAL.yaml": False,
            "SATELLITE_04B_CAMERA_STYLE_COMPATIBILITY.yaml": False,
            "SATELLITE_04_MAPPING_MATRIX.yaml": False,
            "SATELLITE_03_VISUAL_DECK.yaml": False,
        },
    )

    client = TestClient(_build_app())

    response = client.get("/api/bosmax-authority/prompt-tool-context")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"product", "creative", "visual", "character", "execution", "provenance"}
    assert payload["product"]["contexts"][0]["product"]["product_id"] == "prod-001"
    assert payload["product"]["contexts"][0]["creative"]["hook"] == "Glow starts here"
    assert payload["product"]["contexts"][0]["visual"]["product_physics"] == "Glass dropper tilt with liquid realism."
    assert payload["character"]["wardrobe_fallback"]["source_status"] == "NOT_FOUND"
    assert payload["character"]["headwear_suggestions"][0]["source_status"] == "OPERATOR_PACK"
    assert any(item["label"] == "Malay" for item in payload["execution"]["language_options"])
    assert payload["provenance"]["sales_analyzer_wired_to_prompt_tools"] is False
    assert "SALES_ANALYZER_NOT_WIRED_TO_PROMPT_TOOLS" in payload["provenance"]["warnings"]
    missing_labels = {item["label"]: item["source_status"] for item in payload["provenance"]["missing_sources"]}
    assert missing_labels["visual_en"] == "NOT_FOUND"
    assert missing_labels["audio_en"] == "NOT_FOUND"
    assert missing_labels["canonical wardrobe registry"] == "NOT_FOUND"
    assert any(item["label"] == "Atlas Bottle" for item in payload["creative"]["products_with_copy_signals"])


def test_prompt_tool_context_keeps_sales_analyzer_out_of_prompt_hydration(monkeypatch):
    async def fake_list_products(*args, **kwargs):
        return []

    async def fake_registry_listing(asset_type: str):
        return _asset_response(asset_type, [])

    monkeypatch.setattr("agent.services.bosmax_authority_registry.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.services.bosmax_authority_registry._registry_listing", fake_registry_listing)
    monkeypatch.setattr(
        "agent.services.bosmax_authority_registry._operator_pack_summary",
        lambda: (None, ["OPERATOR_PACK_UNAVAILABLE"]),
    )

    client = TestClient(_build_app())

    response = client.get("/api/bosmax-authority/prompt-tool-context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provenance"]["sales_analyzer_wired_to_prompt_tools"] is False
    assert "SALES_ANALYZER_NOT_WIRED_TO_PROMPT_TOOLS" in payload["provenance"]["warnings"]


def test_source_matrix_and_product_context_expose_external_operator_pack_truth(monkeypatch):
    class MinimalPack:
        available = True
        files = ["MASTER_IGNITION_TEMPLATE.yaml", "SCRIPT_REGISTRY_UNIFIED.yaml"]
        avatars = []
        headwear_styles = []
        camera_styles = []
        triggers = []
        silos = []
        formulas = []
        language_defaults = []
        engines = []
        durations_by_engine = {}
        products = []

    async def fake_list_products(*args, **kwargs):
        return [{"id": "prod-001", "product_display_name": "Atlas Bottle"}]

    async def fake_enrich_product(product):
        return {
            "id": "prod-001",
            "product_display_name": "Atlas Bottle",
            "raw_product_title": "Atlas Bottle Original",
            "category": "Beauty",
            "subcategory": "Skincare",
            "type": "Serum",
            "product_type": "Beauty Serum",
            "source": "FASTMOSS",
        }

    async def fake_registry_listing(asset_type: str):
        return _asset_response(asset_type, [])

    monkeypatch.setattr("agent.services.bosmax_authority_registry.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.services.bosmax_authority_registry.enrich_product", fake_enrich_product)
    monkeypatch.setattr("agent.services.bosmax_authority_registry._registry_listing", fake_registry_listing)
    monkeypatch.setattr(
        "agent.services.bosmax_authority_registry._operator_pack_summary",
        lambda: (MinimalPack(), []),
    )
    monkeypatch.setattr(
        "agent.services.bosmax_authority_registry._authority_file_presence",
        lambda: {
            "SOVEREIGN_01_MASTER_SCHEMA.yaml": False,
            "SOVEREIGN_03_CORE_LOGIC.yaml": False,
            "SATELLITE_04D_SCENE_CAMERA_ORCHESTRATION_FINAL.yaml": False,
            "SATELLITE_04B_CAMERA_STYLE_COMPATIBILITY.yaml": False,
            "SATELLITE_04_MAPPING_MATRIX.yaml": False,
            "SATELLITE_03_VISUAL_DECK.yaml": False,
        },
    )

    client = TestClient(_build_app())

    matrix_response = client.get("/api/bosmax-authority/source-matrix")
    product_response = client.get("/api/bosmax-authority/product-context/prod-001")

    assert matrix_response.status_code == 200
    matrix_payload = matrix_response.json()
    entry_by_key = {entry["key"]: entry for entry in matrix_payload["source_matrix"]}
    assert entry_by_key["master_ignition"]["source_status"] == "OPERATOR_PACK"
    assert entry_by_key["master_ignition"]["source_origin"] == "EXTERNAL_OPERATOR_PACK"
    assert entry_by_key["script_registry"]["source_status"] == "OPERATOR_PACK"
    assert entry_by_key["sales_analyzer"]["warnings"] == ["SALES_ANALYZER_NOT_WIRED_TO_PROMPT_TOOLS"]

    assert product_response.status_code == 200
    product_payload = product_response.json()
    assert product_payload["product_context"]["product_id"] == "prod-001"
    assert product_payload["provenance"]["scope"] == "BOSMAX_AUTHORITY_REGISTRY_ADAPTER"