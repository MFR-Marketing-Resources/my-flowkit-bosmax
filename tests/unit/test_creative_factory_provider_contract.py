"""Provider-output contract + bounded-size proof (amendments 5 & 7).

The provider authors ONLY words. The strict Pydantic contract enforces the exact
3 / 6 / 3 / 3 shape, rejects any identity/control key, and bounds every authored
string, so the worst-case envelope is genuinely bounded and provably fits inside
the structured-output transport ceiling.
"""

import json

import pytest
from pydantic import ValidationError

from agent.models import creative_factory as m
from agent.services import creative_factory_service as svc
from agent.services.ai_copy_provider_adapter import OPENAI_COMPATIBLE_JSON_MAX_TOKENS


def _valid_envelope():
    return {
        "angles": [
            {
                "angle": f"Sudut {a}",
                "hooks": [f"hook {a}-{i}" for i in range(m.HOOKS_PER_ANGLE)],
                "bodies": [f"body {a}-{i}" for i in range(m.BODIES_PER_ANGLE)],
                "ctas": [f"cta {a}-{i}" for i in range(m.CTAS_PER_ANGLE)],
            }
            for a in range(m.ANGLES_PER_BENEFIT)
        ]
    }


def _maxlen_envelope():
    return {
        "angles": [
            {
                "angle": "A" * m.ANGLE_MAX_CHARS,
                "hooks": ["H" * m.HOOK_MAX_CHARS for _ in range(m.HOOKS_PER_ANGLE)],
                "bodies": ["B" * m.BODY_MAX_CHARS for _ in range(m.BODIES_PER_ANGLE)],
                "ctas": ["C" * m.CTA_MAX_CHARS for _ in range(m.CTAS_PER_ANGLE)],
            }
            for _ in range(m.ANGLES_PER_BENEFIT)
        ]
    }


def test_atom_shape_constants():
    assert (m.ANGLES_PER_BENEFIT, m.HOOKS_PER_ANGLE, m.BODIES_PER_ANGLE, m.CTAS_PER_ANGLE) == (3, 6, 3, 3)
    assert m.HOOKS_PER_BENEFIT == 18
    assert m.BODIES_PER_BENEFIT == 9
    assert m.CTAS_PER_BENEFIT == 9
    assert m.DEFAULT_BENEFIT_CAPACITY == 162


def test_valid_envelope_accepted():
    env = m.CreativeBuildEnvelope.model_validate(_valid_envelope())
    assert len(env.angles) == 3
    assert all(len(a.hooks) == 6 and len(a.bodies) == 3 and len(a.ctas) == 3 for a in env.angles)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda e: e["angles"].pop(),  # 2 angles
        lambda e: e["angles"][0]["hooks"].append("extra"),  # 7 hooks
        lambda e: e["angles"][0].__setitem__("angle_id", "ANG_x"),  # provider-assigned id
        lambda e: e.__setitem__("route_key", "R1"),  # forbidden top-level key
        lambda e: e["angles"][0].__setitem__("angle", "Z" * (m.ANGLE_MAX_CHARS + 1)),  # overlong
    ],
)
def test_contract_rejects_violations(mutator):
    env = _valid_envelope()
    mutator(env)
    with pytest.raises(ValidationError):
        m.CreativeBuildEnvelope.model_validate(env)


def test_worst_case_envelope_is_bounded_and_fits_ceiling():
    env = _maxlen_envelope()
    # Max-length content still satisfies the contract.
    m.CreativeBuildEnvelope.model_validate(env)
    raw = json.dumps(env, ensure_ascii=False, separators=(",", ":"))

    budget = svc.output_token_budget()
    # 1) our char upper-bound really covers the maximal serialized envelope
    assert svc.worst_case_output_chars() >= len(raw)
    # 2) the chosen budget never exceeds the transport ceiling
    assert budget <= OPENAI_COMPATIBLE_JSON_MAX_TOKENS
    # 3) the budget comfortably covers the maximal envelope at ~3 chars/token
    assert budget >= len(raw) // 3
