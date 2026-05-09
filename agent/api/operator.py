from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException
from openpyxl import load_workbook
from pydantic import BaseModel

from agent.config import OPERATOR_PACK_DIR
from agent.services.product_mapping import resolve_product_mapping

router = APIRouter(prefix="/api/operator", tags=["operator"])


class OperatorProduct(BaseModel):
    product_id: str | None = None
    product_name: str
    raw_product_title: str | None = None
    product_display_name: str | None = None
    product_short_name: str | None = None
    category: str
    sub_category: str
    type_angle: str
    product_type: str | None = None
    silo_id: str | None = None
    trigger_id: str | None = None
    submode_formula: str | None = None
    mode_recommendations: list[str] = []
    copywriting_angle: str | None = None
    claim_risk_level: str | None = None
    mapping_source: str | None = None
    mapping_confidence: str | None = None
    missing_fields: list[str] = []
    raw_category: str | None = None
    avg_price_rm: float | None = None
    status: str | None = None
    copy_angle: str | None = None
    hook: str | None = None
    usp_1: str | None = None
    usp_2: str | None = None
    usp_3: str | None = None
    body: str | None = None
    cta: str | None = None
    shop_name: str | None = None


class WorkbookSummary(BaseModel):
    workbook: str
    sheets: list[str]


class ContentPackSummary(BaseModel):
    pack_dir: str
    available: bool
    files: list[str]
    engines: list[str]
    durations_by_engine: dict[str, list[str]]
    avatars: list[str]
    headwear_styles: list[str]
    camera_styles: list[str]
    product_types: list[str]
    triggers: list[str]
    silos: list[str]
    formulas: list[str]
    materials: list[str]
    language_defaults: list[str]
    products: list[OperatorProduct]
    workbooks: list[WorkbookSummary]
    notes: list[str]


class BlueprintInput(BaseModel):
    product_name: str
    category: str = ""
    sub_category: str = ""
    type_angle: str = ""
    product_type: str
    target_language: str
    duration_target: str
    engine_id: str
    avatar_id: str
    headwear_style: str
    camera_style: str
    scene_context: str
    trigger_id: str
    silo_id: str
    submode_formula: str
    hook: str = ""
    usp_1: str = ""
    usp_2: str = ""
    usp_3: str = ""
    body: str = ""
    cta: str = ""
    material: str = "realistic"
    orientation: str = "VERTICAL"


class BlueprintCharacter(BaseModel):
    name: str
    entity_type: str
    description: str


class BlueprintScene(BaseModel):
    display_order: int
    prompt: str
    image_prompt: str
    video_prompt: str
    character_names: list[str]
    chain_type: str = "ROOT"


class BlueprintResponse(BaseModel):
    project: dict[str, Any]
    video: dict[str, Any]
    scenes: list[BlueprintScene]
    notes: list[str]


def _pack_file(name: str) -> Path:
    return OPERATOR_PACK_DIR / name


def _require_pack() -> Path:
    if not OPERATOR_PACK_DIR.exists():
        raise HTTPException(404, f"Operator pack directory not found: {OPERATOR_PACK_DIR}")
    return OPERATOR_PACK_DIR


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _merged_registry_values(values: list[str], required: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in [*values, *required]:
        if not item or item in seen:
            continue
        ordered.append(item)
        seen.add(item)
    return ordered


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _seconds(duration: str) -> int:
    match = re.search(r"(\d+)", duration or "")
    return int(match.group(1)) if match else 8


def _scene_count(duration_target: str) -> int:
    sec = _seconds(duration_target)
    if sec <= 30:
        return 4
    return 8


def _timed_video_prompt(core_action: str, benefit: str, cta: str) -> str:
    return (
        f'0-3s: {core_action}. '
        f'3-6s: {benefit}. '
        f'6-8s: {cta}.'
    )


@lru_cache(maxsize=1)
def _content_pack_summary() -> ContentPackSummary:
    pack_dir = _require_pack()
    master = _load_yaml_file(_pack_file("MASTER_IGNITION_TEMPLATE.yaml"))
    script_registry = _load_yaml_file(_pack_file("SCRIPT_REGISTRY_UNIFIED.yaml"))

    files = sorted(p.name for p in pack_dir.iterdir() if p.is_file())

    durations_by_engine = {
        key: list(values or [])
        for key, values in (master.get("duration_target") or {}).items()
        if isinstance(values, list)
    }

    workbook_summaries = []
    for workbook_name in [
        "Category and product list.xlsx",
        "FASTMOSS_COMBINED_10_FILES_WORKBOOK.xlsx",
    ]:
        path = _pack_file(workbook_name)
        if path.exists():
            wb = load_workbook(path, read_only=True, data_only=True)
            workbook_summaries.append(
                WorkbookSummary(workbook=workbook_name, sheets=wb.sheetnames)
            )

    products = _load_products()

    return ContentPackSummary(
        pack_dir=str(pack_dir),
        available=True,
        files=files,
        engines=list(master.get("engine_id") or []),
        durations_by_engine=durations_by_engine,
        avatars=list(master.get("avatar_id") or []),
        headwear_styles=list(master.get("headwear_style") or []),
        camera_styles=list(master.get("camera_style") or []),
        product_types=_merged_registry_values(list(master.get("product_type") or ["STEALTH", "DIRECT"]), ["UNIVERSAL", "STEALTH"]),
        triggers=_merged_registry_values(list(master.get("trigger_id") or []), ["TRUST_01", "CONFIDENCE_01", "AUTHORITY_01", "COMFORT_01", "EGO_01"]),
        silos=_merged_registry_values(list(master.get("silo_id") or []), ["baby_care_universal_01", "fashion_mass_01", "perfume_mass_01", "fnb_mass_01", "household_or_beauty_mass_01", "electronics_mass_01", "household_mass_01", "health_supp_stealth_01"]),
        formulas=_merged_registry_values(list(master.get("submode_formula") or []), ["PAS", "AIDA", "TRUST_STACK", "FEATURE_BENEFIT"]),
        materials=["realistic", "3d_pixar", "anime"],
        language_defaults=["Malay", "English"],
        products=products,
        workbooks=workbook_summaries,
        notes=[
            "This operator pack supplies registries, copy hooks, and product intelligence.",
            "Current Flow Kit uses canonical Google Flow labels: Images, Ingredients, Frames, and Text to Video.",
            "Scene context remains the visual authority; hook/USP/CTA are used for wording and scene framing only.",
            f"Malay tone rules are sourced from SCRIPT_REGISTRY_UNIFIED.yaml ({len(script_registry.get('language_tone_rules', {}).get('rules', []))} rules detected).",
        ],
    )


def _load_products(limit: int = 120) -> list[OperatorProduct]:
    path = _pack_file("FASTMOSS_COMBINED_10_FILES_WORKBOOK.xlsx")
    if not path.exists():
        return []

    wb = load_workbook(path, read_only=True, data_only=True)
    if "Copywriting_Product_Map" not in wb.sheetnames:
        return []

    ws = wb["Copywriting_Product_Map"]
    headers: list[str] = []
    products: list[OperatorProduct] = []

    for row in ws.iter_rows(values_only=True):
        values = list(row)
        if not any(v is not None and str(v).strip() for v in values):
            continue
        if values and values[0] == "Rank":
            headers = [str(v).strip() if v is not None else "" for v in values]
            continue
        if not headers:
            continue
        data = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
        name = _clean_text(str(data.get("Product Name") or ""))
        if not name:
            continue
            
        # Basic normalization for Excel source
        short_name = re.sub(r'(\d+PCS|Premium|All size|S/M/L/XL/XXL/XXXL|Ultra-thin|breathable|disposable|tape|pull-ups|disposable diaper tape diaper pants pull-ups)', '', name, flags=re.IGNORECASE)
        short_name = " ".join(short_name.split()[:4]).strip()
        display_name = " ".join(name.split()[:9]).strip()

        mapping = resolve_product_mapping(
            product={
                "raw_product_title": name,
                "product_display_name": display_name,
                "product_short_name": short_name,
                "category": _clean_text(str(data.get("Category") or "")),
                "subcategory": _clean_text(str(data.get("Sub Category") or "")),
                "type": _clean_text(str(data.get("Type / Product Angle") or "")),
                "source": "FASTMOSS",
            },
            source_hint="FASTMOSS",
        )

        products.append(
            OperatorProduct(
                product_name=name,
                raw_product_title=name,
                product_short_name=mapping["product_short_name"],
                product_display_name=display_name,
                category=mapping["category"],
                sub_category=mapping["subcategory"],
                type_angle=mapping["type"],
                product_type=mapping["product_type"] or None,
                silo_id=mapping["silo"] or None,
                trigger_id=mapping["trigger_id"] or None,
                submode_formula=mapping["formula"] or None,
                mode_recommendations=list(mapping.get("mode_recommendations", [])),
                copywriting_angle=mapping.get("copywriting_angle") or None,
                claim_risk_level=mapping.get("claim_risk_level") or None,
                mapping_source=mapping.get("mapping_source") or None,
                mapping_confidence=mapping.get("mapping_confidence") or None,
                missing_fields=list(mapping.get("missing_fields", [])),
                raw_category=_clean_text(str(data.get("Raw Category") or "")) or None,
                avg_price_rm=float(data["Avg Price (RM)"]) if data.get("Avg Price (RM)") is not None else None,
                status=_clean_text(str(data.get("Product Status") or "")) or None,
                copy_angle=_clean_text(str(data.get("Copywriting Angle / Hook Direction") or "")) or None,
                hook=_clean_text(str(data.get("Hook") or "")) or None,
                usp_1=_clean_text(str(data.get("USP 1") or "")) or None,
                usp_2=_clean_text(str(data.get("USP 2") or "")) or None,
                usp_3=_clean_text(str(data.get("USP 3") or "")) or None,
                body=_clean_text(str(data.get("Body") or "")) or None,
                cta=_clean_text(str(data.get("CTA") or "")) or None,
                shop_name=_clean_text(str(data.get("Shop Name") or "")) or None,
            )
        )
        if len(products) >= limit:
            break
    return products


def _build_story(body: BlueprintInput) -> str:
    lines = [
        f"ENGINE: {body.engine_id}",
        f"DURATION: {body.duration_target}",
        f"PRODUCT: {body.product_name}",
        f"PRODUCT_TYPE: {body.product_type}",
        f"CATEGORY: {body.category}",
        f"SUB_CATEGORY: {body.sub_category}",
        f"TYPE_ANGLE: {body.type_angle}",
        f"TARGET_LANGUAGE: {body.target_language}",
        f"AVATAR: {body.avatar_id}",
        f"HEADWEAR: {body.headwear_style}",
        f"CAMERA_STYLE: {body.camera_style}",
        f"SCENE_CONTEXT: {body.scene_context}",
        f"TRIGGER: {body.trigger_id}",
        f"SILO: {body.silo_id}",
        f"FORMULA: {body.submode_formula}",
        f"HOOK: {body.hook}",
        f"USP_1: {body.usp_1}",
        f"USP_2: {body.usp_2}",
        f"USP_3: {body.usp_3}",
        f"BODY: {body.body}",
        f"CTA: {body.cta}",
    ]
    return "\n".join(line for line in lines if not line.endswith(": "))


def _build_characters(body: BlueprintInput) -> list[BlueprintCharacter]:
    avatar_name = body.avatar_id.replace("_", " ").title()
    product_label = _clean_text(body.product_name)
    context_label = _clean_text(body.scene_context)
    characters = [
        BlueprintCharacter(
            name=avatar_name,
            entity_type="character",
            description=(
                f"Primary presenter for {product_label}. "
                f"Headwear: {body.headwear_style}. Camera style: {body.camera_style}. "
                f"Use tone appropriate for {body.silo_id} in {body.target_language}."
            ),
        ),
        BlueprintCharacter(
            name=product_label,
            entity_type="visual_asset",
            description=(
                f"Hero product asset. Category: {body.category}. Sub-category: {body.sub_category}. "
                f"Type angle: {body.type_angle}. Keep product appearance stable across every scene."
            ),
        ),
    ]
    if context_label:
        characters.append(
            BlueprintCharacter(
                name=f"{product_label} Scene Context",
                entity_type="location",
                description=f"Visual environment authority: {context_label}.",
            )
        )
    return characters


def _build_scenes(body: BlueprintInput) -> list[BlueprintScene]:
    sec = _seconds(body.duration_target)
    scene_total = _scene_count(body.duration_target)
    avatar_name = body.avatar_id.replace("_", " ").title()
    product_label = body.product_name
    context = body.scene_context or f"{body.category} product environment"
    benefits = [part for part in [body.usp_1, body.usp_2, body.usp_3] if part]
    while len(benefits) < 3:
        benefits.append(body.body or "Show practical use and clear product value.")

    base_scenes = [
        (
            f"{avatar_name} opens in {context}. Hook the viewer with {body.hook or 'a sharp opening angle'} while keeping {product_label} visible.",
            f"Cinematic opening frame in {context}. {avatar_name} introduces {product_label}. Focus on visual hook, clean composition, and immediate product readability.",
            _timed_video_prompt(
                f"{avatar_name} enters frame and establishes the problem space around {product_label}",
                f"camera movement reinforces the hook while product remains readable",
                f"end on a compelling visual beat that invites the next scene",
            ),
        ),
        (
            f"Demonstrate {product_label} in use inside {context}. Highlight {benefits[0]}.",
            f"Close product interaction shot inside {context}. Show practical usage of {product_label} with emphasis on {benefits[0]}.",
            _timed_video_prompt(
                f"{avatar_name} demonstrates {product_label} in a believable use case",
                f"show the first clear benefit: {benefits[0]}",
                "finish on a stable proof-oriented frame",
            ),
        ),
        (
            f"Escalate proof for {product_label}. Highlight {benefits[1]} and {benefits[2]}.",
            f"Proof-driven scene in {context}. Product hero framing plus tactile detail shots. Reinforce {benefits[1]} and {benefits[2]}.",
            _timed_video_prompt(
                "show layered proof and tactile close-ups",
                f"translate product value into visual confidence: {benefits[1]}",
                f"close with one more proof beat on {benefits[2]}",
            ),
        ),
        (
            f"Resolve with CTA for {product_label}. Use urgency and decisiveness without changing the scene authority from {context}.",
            f"Final action frame in {context}. Product remains central. End on a direct CTA visual for {product_label}.",
            _timed_video_prompt(
                "build final decision energy around the product",
                f"use body copy rhythm: {body.body or 'clarify value and remove hesitation'}",
                f"deliver CTA visually and verbally: {body.cta or 'act now'}",
            ),
        ),
    ]

    scenes = [
        BlueprintScene(
            display_order=index,
            prompt=prompt,
            image_prompt=image_prompt,
            video_prompt=video_prompt,
            character_names=[avatar_name, product_label],
            chain_type="ROOT" if index == 0 else "CONTINUATION",
        )
        for index, (prompt, image_prompt, video_prompt) in enumerate(base_scenes)
    ]

    if scene_total > 4:
        for extra_index in range(4, scene_total):
            scenes.append(
                BlueprintScene(
                    display_order=extra_index,
                    prompt=(
                        f"Extend the campaign with a variation scene for {product_label} in {context}. "
                        f"Preserve identity and re-emphasize {benefits[(extra_index - 4) % len(benefits)]}."
                    ),
                    image_prompt=(
                        f"Variation scene for {product_label} inside {context}. "
                        f"Maintain product identity, avatar continuity, and clean benefit framing."
                    ),
                    video_prompt=_timed_video_prompt(
                        "carry continuity from the previous scene without changing environment authority",
                        f"restate the strongest visual benefit: {benefits[(extra_index - 4) % len(benefits)]}",
                        "close on a high-clarity transition frame",
                    ),
                    character_names=[avatar_name, product_label],
                    chain_type="CONTINUATION",
                )
            )

    if sec <= 10:
        return scenes[:4]
    return scenes


@router.get("/content-pack", response_model=ContentPackSummary)
async def get_content_pack():
    return _content_pack_summary()


@router.post("/blueprint", response_model=BlueprintResponse)
async def build_blueprint(body: BlueprintInput):
    summary = _content_pack_summary()
    if body.engine_id not in summary.engines:
        raise HTTPException(400, f"Unsupported engine_id: {body.engine_id}")

    allowed_durations = summary.durations_by_engine.get(body.engine_id, [])
    if allowed_durations and body.duration_target not in allowed_durations:
        raise HTTPException(
            400,
            f"Duration {body.duration_target} is not allowed for {body.engine_id}. Allowed: {', '.join(allowed_durations)}",
        )

    characters = _build_characters(body)
    scenes = _build_scenes(body)
    project_name = f"{body.product_name} | {body.engine_id} | {body.duration_target}"

    return BlueprintResponse(
        project={
            "name": project_name,
            "description": f"{body.category} / {body.sub_category} / {body.type_angle}".strip(" /"),
            "story": _build_story(body),
            "language": "ms" if body.target_language.lower() == "malay" else "en",
            "material": body.material,
            "allow_music": False,
            "allow_voice": True,
            "characters": [item.model_dump() for item in characters],
        },
        video={
            "title": body.product_name,
            "description": f"{body.engine_id} {body.product_type} operator blueprint",
            "display_order": 0,
            "orientation": body.orientation,
        },
        scenes=scenes,
        notes=[
            "Blueprint compiled from the external BOSMAX content pack.",
            "Use Generate Images before Generate Ingredients or Frames. Generate Text to Video remains visible only as a not-wired label.",
            "Direct single-step T2V is not exposed as a native queue type in this repo. Verified operator paths are prompt -> image -> video or ingredients/refs -> video.",
        ],
    )
