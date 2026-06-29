"""SSOT registry of Google Flow video models (patch I1).

Pricing: Google Flow credits help (verified 30 Jun 2026), taken as the REGULAR/CEILING price.
https://support.google.com/flow/answer/16526234?hl=en

IMPORTANT (Layer A — cap-gate): expected_cost_by_duration values are a CEILING / typical price,
NOT an exact value. Google Flow credits are PROMO-VARIABLE — live capture shows Omni Flash 10s
is currently 15 credits (promo) vs the 30 ceiling — and the agent proposes by credits (often
multi-video). So the negotiation gate uses these as a `cost <= ceiling` CAP, never `cost == exact`.
The selected duration (8s Veo / 10s Omni) is verified POST-approve from the fired tool args,
not inferred from cost. `public_list().default_cost` is therefore the ceiling/typical figure.
"""

VIDEO_MODELS = {
    "veo_3_1_lite": {
        "key": "veo_3_1_lite",
        "ui_label": "Veo 3.1 - Lite",
        "agent_label": "Veo 3.1 - Lite",
        "default_duration_s": 8,
        "allowed_durations_s": [4, 6, 8],
        "expected_cost_by_duration": {4: 10, 6: 10, 8: 10},
        "model_usage_aliases": ["lite"],  # matches veo_3_1_lite / veo_3_1_r2v_lite
    },
    "veo_3_1_fast": {
        "key": "veo_3_1_fast",
        "ui_label": "Veo 3.1 - Fast",
        "agent_label": "Veo 3.1 - Fast",
        "default_duration_s": 8,
        "allowed_durations_s": [4, 6, 8],
        "expected_cost_by_duration": {4: 20, 6: 20, 8: 20},
        "model_usage_aliases": ["fast"],
    },
    "veo_3_1_quality": {
        "key": "veo_3_1_quality",
        "ui_label": "Veo 3.1 - Quality",
        "agent_label": "Veo 3.1 - Quality",
        "default_duration_s": 8,
        "allowed_durations_s": [8],
        "expected_cost_by_duration": {8: 100},
        "model_usage_aliases": ["quality"],
    },
    "omni_flash": {
        "key": "omni_flash",
        "ui_label": "Omni Flash",
        "agent_label": "Gemini Omni Flash",
        "default_duration_s": 10,
        "allowed_durations_s": [4, 6, 8, 10],
        "expected_cost_by_duration": {4: 15, 6: 20, 8: 25, 10: 30},
        "model_usage_aliases": ["omni"],
    },
}

DEFAULT_MODEL = "veo_3_1_lite"  # backward-compatible (patch I4)


def resolve(model) -> dict:
    """Resolve a model by key OR ui_label OR agent_label. Raises on unknown."""
    if not model:
        return VIDEO_MODELS[DEFAULT_MODEL]
    m = str(model).strip().lower()
    for spec in VIDEO_MODELS.values():
        if m in (spec["key"].lower(), spec["ui_label"].lower(), spec["agent_label"].lower()):
            return spec
    raise ValueError(f"unknown video model '{model}'")


def expected_cost(model, duration_s=None) -> int:
    """The exact expected credit cost for (model, duration). duration defaults to the
    model's default_duration_s. Raises on an unsupported duration."""
    spec = resolve(model)
    d = duration_s if duration_s is not None else spec["default_duration_s"]
    table = spec["expected_cost_by_duration"]
    if d not in table:
        raise ValueError(f"{spec['ui_label']} does not support {d}s (allowed: {spec['allowed_durations_s']})")
    return table[d]


def model_matches(model_used, model) -> bool:
    """Post-approve check: does the fired model_used satisfy the target model's aliases?"""
    if not model_used:
        return False
    mu = str(model_used).lower()
    return any(a in mu for a in resolve(model)["model_usage_aliases"])


def public_list() -> list:
    """Registry shape for the dashboard dropdown (SSOT). `default_cost` is the CEILING/typical
    price (promo-variable), kept under this name for UI/test compatibility — NOT an exact value."""
    return [
        {
            "key": s["key"],
            "ui_label": s["ui_label"],
            "default_duration_s": s["default_duration_s"],
            "allowed_durations_s": s["allowed_durations_s"],
            # ceiling/typical price (promo may be lower); kept as `default_cost` for compatibility
            "default_cost": s["expected_cost_by_duration"][s["default_duration_s"]],
        }
        for s in VIDEO_MODELS.values()
    ]
