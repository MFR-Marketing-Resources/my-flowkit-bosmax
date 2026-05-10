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


def test_baby_wipes_physics_mapping():
    result = resolve_product_physics(
        product_name="Baby Wipes Newborn Wet Tissue Tisue Basah Fragrance-free",
        category="Baby Care",
        subcategory="Diapering / Baby Wipes / Wet Wipes",
        type_name="Baby Wipes",
    )

    assert result["physics_class"] == "WIPES_SOFT_PACK"
    assert "flat palm support" in result["recommended_grip"]
    assert "opening edge" in result["camera_handling_notes"]


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


def test_household_cleaner_uses_household_packaged_goods_family():
    result = resolve_product_physics(
        product_name="5 liter sabun dobi malaya liquid detergen",
        category="Home Supplies",
        subcategory="Home Care Supplies",
        type_name="Household Cleaners",
    )

    assert result["physics_class"] == "HOUSEHOLD_PACKAGED_GOODS"
    assert "label" in result["recommended_grip"] or "support" in result["recommended_grip"]


def test_square_hijab_uses_modestwear_family():
    result = resolve_product_physics(
        product_name="Amyrahijab chiffon premium",
        category="Muslim Fashion",
        subcategory="Hijabs",
        type_name="Square Hijabs",
    )

    assert result["physics_class"] == "MODESTWEAR_TEXTILE"
    assert "fabric" in result["recommended_grip"]


def test_skincare_cleanser_uses_skincare_family():
    result = resolve_product_physics(
        product_name="Bestie bundle cleanser",
        category="Beauty & Personal Care",
        subcategory="Skincare",
        type_name="Facial Cleansers",
    )

    assert result["physics_class"] == "SKINCARE_JAR_OR_TUBE"
    assert "label" in result["camera_handling_notes"] or "seal" in result["camera_handling_notes"]


def test_phone_charger_uses_electronics_family():
    result = resolve_product_physics(
        product_name="UGREEN PD20W fast charger",
        category="Phones & Electronics",
        subcategory="Phone Accessories",
        type_name="Cables, Chargers & Adapters",
    )

    assert result["physics_class"] == "ELECTRONICS_SMALL_DEVICE"
    assert "ports" in result["camera_handling_notes"] or "controls" in result["camera_handling_notes"]


def test_religion_book_uses_stationery_family():
    result = resolve_product_physics(
        product_name="100 doa taubat",
        category="Books, Magazines & Audio",
        subcategory="Humanities & Social Sciences",
        type_name="Religion & Philosophy",
    )

    assert result["physics_class"] == "STATIONERY_PACK"
    assert "printed" in result["handling_notes"] or "readable" in result["camera_handling_notes"]


def test_supplement_uses_bottle_family():
    result = resolve_product_physics(
        product_name="Pentavite men multivitamin",
        category="Health",
        subcategory="Supplements",
        type_name="Male Health",
    )

    assert result["physics_class"] == "SUPPLEMENT_BOTTLE"
    assert "bottle" in result["handling_notes"]


def test_wall_sticker_uses_small_rigid_decor_family():
    result = resolve_product_physics(
        product_name="Stiker Dinding PVC Mewah",
        category="Tools & Hardware",
        subcategory="Hardware",
        type_name="Fasteners & Hooks",
    )

    assert result["physics_class"] == "SMALL_RIGID_DECOR"
    assert "decorative" in result["handling_notes"] or "silhouette" in result["handling_notes"]
