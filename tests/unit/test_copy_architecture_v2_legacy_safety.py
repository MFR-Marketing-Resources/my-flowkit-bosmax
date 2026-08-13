"""Legacy flag-off golden protection for Phase 2.

The V2 contract is additive and does not import or rewrite the canonical
compiler.  This test records the exact legacy CopySet-to-compiler projection
and verifies the default-off flag remains isolated.
"""
from __future__ import annotations

import json

from agent.models.copy_blueprint_v2 import CopyBlueprintV2FeatureFlagState
from agent.models.copy_set import to_compiler_copy


LEGACY_COPY_SET = {
    "angle": "Rutin mudah untuk kulit kombinasi",
    "hook": "Kulit rasa kering walaupun dah pakai moisturizer?",
    "subhook": "Tekstur ringan senang masuk rutin harian.",
    "usp_set": ["Menyerap cepat", "Tanpa rasa melekit"],
    "cta": "Cuba masukkan dalam rutin kau hari ini.",
    "formula_family": "HSO",
}


EXPECTED_LEGACY_COMPILER_COPY_JSON = (
    '{"angle":"Rutin mudah untuk kulit kombinasi",'
    '"copywriting_angle":"Rutin mudah untuk kulit kombinasi",'
    '"hook":"Kulit rasa kering walaupun dah pakai moisturizer?",'
    '"subhook":"Tekstur ringan senang masuk rutin harian.",'
    '"usps":["Menyerap cepat","Tanpa rasa melekit"],'
    '"cta":"Cuba masukkan dalam rutin kau hari ini.","formula_family":"HSO"}'
)


def test_v2_flag_defaults_off_and_legacy_projection_is_byte_stable():
    flags = CopyBlueprintV2FeatureFlagState()
    assert flags.enabled is False
    assert flags.state == "OFF"

    legacy_projection = to_compiler_copy(LEGACY_COPY_SET)
    assert json.dumps(legacy_projection, ensure_ascii=False, separators=(",", ":")) == EXPECTED_LEGACY_COMPILER_COPY_JSON
