"""Creative Factory service — Round 1 acceptance matrix (mission A–S + amendments).

Every test is PROVIDER-FREE: the Creative Atom build uses an injected fake
provider, and the real provider adapter's process-global HTTP counter is asserted
to never advance. No paid provider call occurs anywhere in this suite.
"""

import copy
import re

import pytest

from agent.db import creative_factory_crud as cfdb
from agent.db.schema import get_db
from agent.models import creative_factory as models
from agent.services import ai_copy_provider_adapter as adapter
from agent.services import creative_factory_service as svc
from tests.conftest import make_product_copy_eligible, seed_product_ready

# One of the approved-snapshot benefit strings seeded by make_product_copy_eligible.
SUPPORTED_BENEFIT = "melembapkan kulit sepanjang hari"
SUPPORTED_BENEFIT_2 = "menyerap cepat tanpa melekit"
UNSUPPORTED_BENEFIT = "zzz qwerty unrelated random tokens 12345"
UNSAFE_BENEFIT = "sembuh penyakit dengan cepat"


async def _setup(product_id="prod_cf"):
    db = await get_db()
    await seed_product_ready(db, product_id)
    snapshot_id = await make_product_copy_eligible(product_id)
    return product_id, snapshot_id


def _valid_envelope():
    return {
        "angles": [
            {
                "angle": f"Sudut jualan nombor {a} untuk rutin harian",
                "hooks": [f"Buka dengan soalan ringkas {a}-{i}" for i in range(6)],
                "bodies": [f"Terangkan kegunaan harian pilihan {a}-{i}" for i in range(3)],
                "ctas": [f"Ajak cuba rutin ini {a}-{i}" for i in range(3)],
            }
            for a in range(3)
        ]
    }


class FakeProvider:
    """Injected structured provider double. Never touches the network."""

    def __init__(self, envelope=None):
        self.calls = 0
        self.last_system = None
        self.last_user = None
        self.last_kwargs = None
        self.envelope = envelope if envelope is not None else _valid_envelope()

    def complete_json_with_receipt(self, system, user, **kwargs):
        self.calls += 1
        self.last_system = system
        self.last_user = user
        self.last_kwargs = kwargs
        # The factory MUST suppress fallback and use the structure lane.
        assert kwargs.get("allow_fallback") is False
        assert kwargs.get("lane") == "structure"
        return (
            copy.deepcopy(self.envelope),
            {"provider": "fake", "model": "fake-model", "call_id": "fake-call", "usage": {"total_tokens": 10}},
        )


def _real_calls():
    return adapter.provider_call_receipt()["request_count_since_process_start"]


async def _active_counts(benefit_id):
    atoms = await cfdb.get_benefit_atoms(benefit_id, status="ACTIVE")
    return {k: len(v) for k, v in atoms.items()}


# --------------------------------------------------------------------------
# Benefit Registry: multi-row, required/optional, PI verdicts
# --------------------------------------------------------------------------
async def test_add_multiple_rows_required_and_optional_usage():
    # (A) many rows, (B) benefit required, (C/D/E) usage optional & non-blocking
    product_id, _ = await _setup()
    before = _real_calls()

    b1 = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, "Sapu pada kulit")
    b2 = await svc.create_benefit(product_id, SUPPORTED_BENEFIT_2, None)
    b3 = await svc.create_benefit(product_id, "kulit nampak segar", "")

    rows = await svc.list_benefits(product_id)
    assert len(rows) == 3
    assert b1["usage_hint"] == "Sapu pada kulit"
    assert b2["usage_hint"] is None
    assert b3["usage_hint"] is None  # empty usage normalised to None, never blocks
    assert b2["status"] in {"VERIFIED", "REVIEW_REQUIRED"}  # empty usage did not block

    with pytest.raises(svc.CreativeFactoryError) as exc:
        await svc.create_benefit(product_id, "   ", None)
    assert exc.value.code == "BENEFIT_REQUIRED"

    assert _real_calls() == before  # zero provider calls for registry ops


async def test_supported_benefit_verified_with_provenance():
    # (G) supported benefit -> VERIFIED with evidence/provenance
    product_id, snapshot_id = await _setup()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    assert b["status"] == "VERIFIED"
    assert b["pi_snapshot_id"] == snapshot_id
    assert b["pi_check"]["similarity"]["score"] >= svc.SIMILARITY_VERIFY_THRESHOLD
    assert b["pi_check"]["has_authority"] is True


async def test_unsupported_benefit_not_verified():
    # (F) unsupported/ambiguous benefit is NOT silently VERIFIED
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, UNSUPPORTED_BENEFIT, None)
    assert b["status"] == "REVIEW_REQUIRED"
    assert b["status"] != "VERIFIED"


async def test_unsafe_benefit_blocked():
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, UNSAFE_BENEFIT, None)
    assert b["status"] == "BLOCKED"
    assert b["pi_check"]["hard_safety_blocked"] is True


async def test_usage_hint_persisted_as_guidance_not_scene():
    # (E) usage hint is persisted as optional guidance, never a mandatory scene
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, "Sapu sedikit pada kulit")
    row = await cfdb.get_benefit(b["benefit_id"])
    assert row["usage_hint"] == "Sapu sedikit pada kulit"
    # no scene/mandatory-action column exists on the benefit row
    assert "mandatory_scene_action" not in row


async def test_stable_id_across_edit():
    # (H) stable benefit id survives editing
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    updated = await svc.update_benefit(b["benefit_id"], benefit_text="kulit nampak segar")
    assert updated["benefit_id"] == b["benefit_id"]
    assert updated["benefit"] == "kulit nampak segar"


# --------------------------------------------------------------------------
# Build: only-verified, hierarchy, capacity, system-owned ids
# --------------------------------------------------------------------------
async def test_only_verified_benefits_build():
    # (J) only VERIFIED benefits can build atoms
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, UNSUPPORTED_BENEFIT, None)  # REVIEW_REQUIRED
    with pytest.raises(svc.CreativeFactoryError) as exc:
        await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=FakeProvider())
    assert exc.value.code == "BENEFIT_NOT_VERIFIED"


async def test_build_persists_hierarchy_capacity_and_system_ids():
    # (K) fake output persists 3/18/9/9; (M) capacity 162; (L) system-owned ids
    product_id, _ = await _setup()
    fake = FakeProvider()
    before = _real_calls()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    result = await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=fake)

    assert fake.calls == 1
    assert result["counts"] == {"angles": 3, "hooks": 18, "bodies": 9, "ctas": 9}
    assert result["capacity"]["combinations"] == 162
    assert result["capacity"]["complete"] is True

    counts = await _active_counts(b["benefit_id"])
    assert counts == {"angle": 3, "hook": 18, "body": 9, "cta": 9}

    atoms = await cfdb.get_benefit_atoms(b["benefit_id"], status="ACTIVE")
    assert all(a["angle_id"].startswith("ANG_") for a in atoms["angle"])
    assert all(h["hook_id"].startswith("HOOK_") for h in atoms["hook"])
    assert _real_calls() == before  # the injected fake made the only call


async def test_provider_cannot_assign_ids():
    # (L) a provider-supplied identity key fails the strict contract; no atoms
    product_id, _ = await _setup()
    bad = _valid_envelope()
    bad["angles"][0]["angle_id"] = "ANG_injected"
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    with pytest.raises(svc.CreativeFactoryError) as exc:
        await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=FakeProvider(bad))
    assert exc.value.code == "STRUCTURE_CONTRACT_VIOLATION"
    assert await cfdb.count_atoms_for_benefit(b["benefit_id"]) == 0


async def test_no_duration_wps_route_scene_in_authoring():
    # (P/Q/R) the output contract & persisted atoms carry no duration/WPS/route/
    # storyline/scene/camera/avatar; and the prompt embeds no timing/WPS budget.
    assert set(models.CreativeAngleProposal.model_fields) == {"angle", "hooks", "bodies", "ctas"}
    assert set(models.CreativeBuildEnvelope.model_fields) == {"angles"}

    product_id, _ = await _setup()
    fake = FakeProvider()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=fake)

    db = await get_db()
    banned = ("duration", "wps", "route", "storyline", "scene", "camera", "avatar")
    for table in ("creative_angle", "creative_hook", "creative_body", "creative_cta"):
        cols = [r[1].lower() for r in await (await db.execute(f"PRAGMA table_info({table})")).fetchall()]
        assert not any(any(term in c for term in banned) for c in cols), table

    prompt = (fake.last_system + "\n" + fake.last_user).lower()
    assert re.search(r"\d+(\.\d+)?\s*wps", prompt) is None       # no WPS budget value
    assert re.search(r"\b\d+\s*(s|saat|detik)\b", prompt) is None  # no duration value


# --------------------------------------------------------------------------
# Capacity: zero provider calls, product totals, 13x = 2106
# --------------------------------------------------------------------------
async def _seed_verified_direct(product_id, text):
    return await cfdb.create_benefit(
        {
            "benefit_id": cfdb.new_id("BEN"),
            "product_id": product_id,
            "canonical_text": text,
            "text_digest": svc._text_digest(text),
            "usage_hint": None,
            "status": "VERIFIED",
            "pi_check_json": {},
            "provenance_json": {"resolution": "AUTO"},
        }
    )


async def test_capacity_reads_are_provider_free():
    # (O) capacity/atoms/build-plan reads cause zero provider calls
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=FakeProvider())

    before = _real_calls()
    await svc.product_capacity(product_id)
    await svc.benefit_capacity(b["benefit_id"])
    await svc.build_plan(product_id)
    await svc.benefit_atoms(b["benefit_id"])
    assert _real_calls() == before


async def test_thirteen_benefits_yield_2106():
    # (N) 13 equivalent complete benefits = 2,106 theoretical combinations
    product_id, _ = await _setup("prod_cf_13")
    for i in range(13):
        benefit = await _seed_verified_direct(product_id, f"manfaat rutin harian nombor {i}")
        await svc.build_benefit_atoms(product_id, benefit["benefit_id"], provider=FakeProvider())

    capacity = await svc.product_capacity(product_id)
    assert capacity["ready_benefits"] == 13
    assert capacity["totals"]["combinations"] == 2106
    assert capacity["creative_factory_ready"] is True


# --------------------------------------------------------------------------
# Revision / stale law (amendment: edit A never stales B)
# --------------------------------------------------------------------------
async def test_edit_a_does_not_stale_b():
    # (I) editing Benefit A stales only A's atoms
    product_id, _ = await _setup()
    a = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT_2, None)
    await svc.build_benefit_atoms(product_id, a["benefit_id"], provider=FakeProvider())
    await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=FakeProvider())

    await svc.update_benefit(a["benefit_id"], benefit_text="kulit nampak segar")

    assert await cfdb.count_atoms_for_benefit(a["benefit_id"], statuses=["ACTIVE"]) == 0
    assert await cfdb.count_atoms_for_benefit(a["benefit_id"], statuses=["STALE"]) == 39
    assert await cfdb.count_atoms_for_benefit(b["benefit_id"], statuses=["ACTIVE"]) == 39


# --------------------------------------------------------------------------
# Fail-closed atomic build (amendment 6)
# --------------------------------------------------------------------------
def _envelope_with_unsafe_atom():
    env = _valid_envelope()
    env["angles"][1]["hooks"][2] = "Dijamin berkesan sembuh penyakit dengan cepat"
    return env


async def test_claim_qa_failure_is_fail_closed_and_atomic():
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    with pytest.raises(svc.CreativeFactoryError) as exc:
        await svc.build_benefit_atoms(
            product_id, b["benefit_id"], provider=FakeProvider(_envelope_with_unsafe_atom())
        )
    assert exc.value.code == "CLAIM_QA_FAILED"
    # zero atoms committed, and a FAILED receipt with diagnostics persists
    assert await cfdb.count_atoms_for_benefit(b["benefit_id"]) == 0
    receipt = await cfdb.get_latest_build_receipt(b["benefit_id"])
    assert receipt["status"] == "FAILED"
    assert receipt["failure_code"] == "CLAIM_QA_FAILED"


async def test_failed_rebuild_preserves_prior_active_build():
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=FakeProvider())
    assert await cfdb.count_atoms_for_benefit(b["benefit_id"], statuses=["ACTIVE"]) == 39

    with pytest.raises(svc.CreativeFactoryError):
        await svc.build_benefit_atoms(
            product_id, b["benefit_id"], provider=FakeProvider(_envelope_with_unsafe_atom())
        )
    # prior good build untouched
    assert await cfdb.count_atoms_for_benefit(b["benefit_id"], statuses=["ACTIVE"]) == 39


async def test_successful_rebuild_supersedes_prior_atomically():
    product_id, _ = await _setup()
    b = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=FakeProvider())
    await svc.build_benefit_atoms(product_id, b["benefit_id"], provider=FakeProvider())

    assert await cfdb.count_atoms_for_benefit(b["benefit_id"], statuses=["ACTIVE"]) == 39
    assert await cfdb.count_atoms_for_benefit(b["benefit_id"], statuses=["SUPERSEDED"]) == 39
    cap = await svc.benefit_capacity(b["benefit_id"])
    assert cap["combinations"] == 162


# --------------------------------------------------------------------------
# Governed batch build (amendment 4)
# --------------------------------------------------------------------------
async def test_build_plan_reports_counts():
    product_id, _ = await _setup()
    await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    await svc.create_benefit(product_id, SUPPORTED_BENEFIT_2, None)
    plan = await svc.build_plan(product_id)
    assert plan["verified_benefit_count"] == 2
    assert plan["expected_provider_calls"] == 2


async def test_batch_requires_confirmation():
    product_id, _ = await _setup()
    await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    with pytest.raises(svc.CreativeFactoryError) as exc:
        await svc.build_verified(product_id, confirm=False)
    assert exc.value.code == "CONFIRMATION_REQUIRED"
    assert exc.value.details["expected_provider_calls"] == 1


async def test_batch_is_sequential_and_independent():
    # B's failure must not invalidate A
    product_id, _ = await _setup()
    good = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    bad = await svc.create_benefit(product_id, SUPPORTED_BENEFIT_2, None)

    class SelectiveProvider(FakeProvider):
        def complete_json_with_receipt(self, system, user, **kwargs):
            # Discriminate on the exact BENEFIT line (grounding lists every
            # snapshot benefit, so a substring match would hit both prompts).
            if f"BENEFIT: {bad['benefit']}" in user:
                self.calls += 1
                return (_envelope_with_unsafe_atom(), {"provider": "fake", "model": "m", "call_id": "c"})
            return super().complete_json_with_receipt(system, user, **kwargs)

    outcome = await svc.build_verified(product_id, confirm=True, provider=SelectiveProvider())
    by_id = {r["benefit_id"]: r for r in outcome["results"]}
    assert by_id[good["benefit_id"]]["status"] == "COMPLETED"
    assert by_id[bad["benefit_id"]]["status"] == "FAILED"
    # A committed a full build despite B failing
    assert await cfdb.count_atoms_for_benefit(good["benefit_id"], statuses=["ACTIVE"]) == 39
    assert await cfdb.count_atoms_for_benefit(bad["benefit_id"]) == 0


# --------------------------------------------------------------------------
# delete vs archive
# --------------------------------------------------------------------------
async def test_delete_safe_draft_but_archive_with_atoms():
    product_id, _ = await _setup()
    draft = await svc.create_benefit(product_id, UNSUPPORTED_BENEFIT, None)  # no atoms
    res = await svc.delete_benefit(draft["benefit_id"])
    assert res["action"] == "DELETED"
    assert await svc.get_benefit(draft["benefit_id"]) is None

    built = await svc.create_benefit(product_id, SUPPORTED_BENEFIT, None)
    await svc.build_benefit_atoms(product_id, built["benefit_id"], provider=FakeProvider())
    res2 = await svc.delete_benefit(built["benefit_id"])
    assert res2["action"] == "ARCHIVED"
    assert (await cfdb.get_benefit(built["benefit_id"]))["status"] == "ARCHIVED"
