from agent.services import avatar_registry


def test_build_avatar_prompt_v1_enforces_free_hand_reference_pose():
    prompt = avatar_registry.build_avatar_prompt_v1(
        {
            "CharacterName": "Zara",
            "AvatarCode": "BOS_F_ZARA_99",
            "SkinTone": "Tan SEA",
            "HairStyle": "Medium tidy",
            "Wardrobe": "Home casual wear",
            "Expression": "Friendly neutral",
            "Environment": "Living room interior",
            "Lighting": "Soft natural",
            "Camera": "Waist-up",
        }
    )

    lowered = prompt.lower()
    assert "avatar reference pose law:" in lowered
    assert "both hands must be empty" in lowered
    assert "empty hands and no object held" in lowered
    assert "no cup, bottle, phone, book, food, bag, product, prop" in lowered
    assert "future product-composite generation" in lowered


def test_get_generation_prompt_hardens_legacy_prompt_v1(monkeypatch):
    monkeypatch.setattr(
        avatar_registry,
        "_load_pool",
        lambda: (
            {
                "AvatarCode": "BOS_F_LEGACY_01",
                "CharacterName": "Legacy",
                "PromptV1": "Create a photorealistic avatar reference image. Pose: Relaxed, natural.",
            },
        ),
    )

    prompt = avatar_registry.get_generation_prompt("BOS_F_LEGACY_01")["prompt"]

    assert "Avatar reference pose law:" in prompt
    assert "both hands must be empty" in prompt
    assert "No cup, bottle, phone, book, food, bag, product, prop" in prompt


def test_get_generation_prompt_does_not_duplicate_existing_free_hand_law(monkeypatch):
    law = avatar_registry.avatar_reference_free_hand_law()
    monkeypatch.setattr(
        avatar_registry,
        "_load_pool",
        lambda: (
            {
                "AvatarCode": "BOS_M_READY_01",
                "CharacterName": "Ready",
                "PromptV1": f"Create a photorealistic avatar reference image. {law}",
            },
        ),
    )

    prompt = avatar_registry.get_generation_prompt("BOS_M_READY_01")["prompt"]

    assert prompt.count("Avatar reference pose law:") == 1


def test_avatar_camera_vocab_excludes_product_hold():
    avatar_registry._vocab_doc.cache_clear()
    avatar_registry.load_vocab.cache_clear()

    camera_options = avatar_registry.load_vocab()["camera"]

    assert "Close product hold" not in camera_options
    assert "Close portrait" in camera_options
