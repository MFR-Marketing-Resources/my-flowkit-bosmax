from agent.services.product_physics import evaluate_prompt_readiness, resolve_product_physics


def test_diaper_physics_mapping():
    result = resolve_product_physics(
        product_name="Sumikko Baby Diaper pants ultra-thin breathable pack",
        category="Baby Care",
        subcategory="Diaper",
        type_name="Pants",
    )

    assert result["physics_class"] == "SOFT_PACKAGED_GOODS"
    assert "soft compressible pack" in result["hand_object_interaction"]


def test_jersey_physics_mapping():
    result = resolve_product_physics(
        product_name="QAYRAA jersi muslimah microfiber quick dry",
        category="Fashion",
        subcategory="Sportswear",
        type_name="Jersey-Athleisure",
    )

    assert result["physics_class"] == "FLEXIBLE_FABRIC"
    assert "waistband hold" in result["recommended_grip"]


def test_pants_mapping_uses_fabric_class():
    result = resolve_product_physics(
        product_name="Seluar tarik ke atas",
        category="Fashion",
        subcategory="Bottoms",
        type_name="Pants",
    )

    assert result["physics_class"] == "FLEXIBLE_FABRIC"


def test_body_spray_physics_mapping():
    result = resolve_product_physics(
        product_name="Elianto body spray fresh bloom",
        category="Beauty & Personal Care",
        subcategory="Fragrance",
        type_name="Body Mist",
    )

    assert result["physics_class"] == "A"
    assert "label visible" in result["recommended_grip"]


def test_sambal_physics_mapping():
    result = resolve_product_physics(
        product_name="Sambal Nyet extra pedas",
        category="Food & Beverage",
        subcategory="Ready-to-eat/Food",
        type_name="Sauce-Food",
    )

    assert result["physics_class"] == "B"
    assert "food-safe" in result["camera_handling_notes"]


def test_unknown_manual_product_readiness_missing_fields():
    physics = resolve_product_physics(product_name="Mystery artisanal item")
    readiness = evaluate_prompt_readiness(
        {
            "product_short_name": "Mystery artisanal item",
            "category": "",
            "subcategory": "",
            "type": "",
            "image_url": None,
            "local_image_path": None,
            "copywriting_angle": "",
            "claim_risk_level": "",
        },
        physics,
    )

    assert readiness["prompt_readiness_status"] == "MISSING_FIELDS"
    assert "physics_class" in readiness["prompt_missing_fields"]
    assert "category" in readiness["prompt_missing_fields"]


def test_money_packet_physics_mapping():
    result = resolve_product_physics(
        product_name="Sampul Duit Raya money packet festive envelope",
        category="Stationery",
        subcategory="Envelope",
        type_name="Money Packet",
    )

    assert result["physics_class"] == "PAPER_GOODS"
    assert "paper" in result["material_behavior"]


def test_food_container_physics_mapping():
    result = resolve_product_physics(
        product_name="Microwave-safe food container set bekas makanan",
        category="Home & Living",
        subcategory="Kitchen Storage",
        type_name="Food Container",
    )

    assert result["physics_class"] == "RIGID_CONTAINER"
    assert "lid" in result["camera_handling_notes"]
