"""Image-model resolver contract.

Maps an image-model key OR ui_label to Google Flow's internal imageModelName,
defaulting to Nano Banana Pro (the pre-existing hardcoded behaviour) and failing
CLOSED on unknown or not-yet-configured models — never silently substituting a
different model. Guards the model-picker wiring.
"""

import pytest

from agent.services.flow_client import resolve_image_model_name


def test_default_preserves_nano_banana_pro():
    # No model / explicit Pro -> today's hardcoded value, so behaviour is unchanged.
    assert resolve_image_model_name(None) == "GEM_PIX_2"
    assert resolve_image_model_name("Nano Banana Pro") == "GEM_PIX_2"
    assert resolve_image_model_name("NANO_BANANA_PRO") == "GEM_PIX_2"


def test_nano_banana_2_resolves_by_label_and_key():
    assert resolve_image_model_name("Nano Banana 2") == "NARWHAL"
    assert resolve_image_model_name("NANO_BANANA_2") == "NARWHAL"


def test_lite_fails_closed_until_internal_id_is_configured():
    # 2 Lite is a REAL picker option, but its Google internal id is pending in
    # models.json — it must fail closed, not silently fall back to another model.
    with pytest.raises(ValueError, match="PENDING"):
        resolve_image_model_name("Nano Banana 2 Lite")
    with pytest.raises(ValueError, match="PENDING"):
        resolve_image_model_name("NANO_BANANA_2_LITE")


def test_unknown_model_fails_closed():
    with pytest.raises(ValueError, match="ERR_UNKNOWN_IMAGE_MODEL"):
        resolve_image_model_name("Totally Fake Model")
