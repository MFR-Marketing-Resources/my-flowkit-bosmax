"""Shared provider-free helpers for the On-Demand Copy Renderer (Round 2) tests.

Bootstraps a VERIFIED, atom-ready benefit by reusing the Round-1 Creative Factory
with an injected fake (so copy-render tests run over real ACTIVE atoms), and
provides the copy-render stitch fake. No test in the copy-render suites touches
the network — the real provider adapter's process-global counter must never move.
"""

from __future__ import annotations

import re
from typing import Any

from agent.db.schema import get_db
from agent.services import ai_copy_provider_adapter as adapter
from agent.services import creative_factory_service as cfsvc
from tests.conftest import make_product_copy_eligible, seed_product_ready

SUPPORTED_BENEFIT = "melembapkan kulit sepanjang hari"
SUPPORTED_BENEFIT_2 = "menyerap cepat tanpa melekit"
PAS_STAGES = ("problem", "agitate", "solution", "cta")


def cf_atom_envelope() -> dict[str, Any]:
    """Round-1 atom-build envelope: 3 angles × 6 hooks × 3 bodies × 3 ctas = 162."""
    return {"angles": [
        {"angle": f"Sudut jualan nombor {a} untuk rutin harian",
         "hooks": [f"Buka dengan soalan ringkas {a}-{i}" for i in range(6)],
         "bodies": [f"Terangkan kegunaan harian pilihan {a}-{i}" for i in range(3)],
         "ctas": [f"Ajak cuba rutin ini {a}-{i}" for i in range(3)]}
        for a in range(3)]}


class CFAtomFake:
    """Injected structured double for the Round-1 atom build."""

    def __init__(self) -> None:
        self.calls = 0

    def complete_json_with_receipt(self, system: str, user: str, **kwargs: Any):
        self.calls += 1
        assert kwargs.get("allow_fallback") is False
        assert kwargs.get("lane") == "structure"
        return (cf_atom_envelope(),
                {"provider": "fake", "model": "fake-model", "call_id": "c", "usage": {"total_tokens": 5}})


class StitchFake:
    """Copy-render stitch double: parses the requested S-slots + their recipe atoms
    from the prompt and returns one PAS-shaped suggestion per slot, deriving unique
    per-recipe stage text (so distinct recipes yield distinct full-copy text)."""

    def __init__(self, stages: tuple[str, ...] = PAS_STAGES, *, force_duplicate: bool = False,
                 corrupt_stage: bool = False, word_override: int | None = None) -> None:
        self.stages = list(stages)
        self.calls = 0
        self.last_kwargs: dict[str, Any] | None = None
        self._force_duplicate = force_duplicate
        self._corrupt_stage = corrupt_stage
        # When set, emit this many total words instead of the prompt's REQUIRED
        # EXACT count — used to exercise occupancy underrun/overrun rejection.
        self._word_override = word_override

    _FILLER = ("dan", "juga", "untuk", "anda", "hari", "ini", "serta", "dengan",
               "boleh", "kini", "segera", "rutin", "mudah", "selesa", "lega")

    def _fit_exact(self, stages: list[dict[str, str]], target: int) -> list[dict[str, str]]:
        """Emit EXACTLY ``target`` total words as BALANCED per-stage sentences, each
        ending in a full stop, so the script divides cleanly into equal per-block
        parts (materializable under the temporal-occupancy contract). Per-recipe
        uniqueness is preserved by the atom fragments."""
        n = len(stages)
        base, extra = divmod(int(target), n)
        out = []
        for i, st in enumerate(stages):
            want = base + (1 if i >= n - extra else 0)
            words = st["text"].split()[:want]
            words += [self._FILLER[j % len(self._FILLER)] for j in range(want - len(words))]
            text = " ".join(words).strip()
            if text and text[-1] not in ".!?":
                text += "."  # sentence boundary — adds punctuation, not a word
            out.append({"stage_key": st["stage_key"], "text": text})
        return out

    def complete_json_with_receipt(self, system: str, user: str, **kwargs: Any):
        self.calls += 1
        self.last_kwargs = dict(kwargs)
        assert kwargs.get("allow_fallback") is False
        assert kwargs.get("lane") == "structure"
        m = re.search(r"REQUIRED EXACT total words per complete script:\s*(\d+)", user)
        required_total = int(m.group(1)) if m else 0
        target = self._word_override if self._word_override is not None else required_total
        slots = re.findall(
            r"- (S\d+): angle=\[(.*?)\] hook=\[(.*?)\] body=\[(.*?)\] cta=\[(.*?)\]", user)
        suggestions = []
        for slot, angle, hook, body, cta in slots:
            role = {"problem": hook, "agitate": body, "solution": angle, "cta": cta}
            if self._force_duplicate:
                # Same full script for EVERY slot (to exercise the cross-slot text
                # uniqueness gate) — yet distinct per stage so it still splits into
                # the exact per-block occupancy (identical sentences would collapse).
                role = {k: f"ayat nombor {i} untuk kulit lembap segar sepanjang hari"
                        for i, k in enumerate(self.stages)}
            stages = []
            for i, key in enumerate(self.stages):
                out_key = "WRONG_STAGE" if (self._corrupt_stage and i == 0) else key
                stages.append({"stage_key": out_key, "text": role.get(key, f"{slot} {key}")})
            # Fit to the EXACT required occupancy (skip when deliberately corrupting
            # the stage key — that failure is asserted before the word count).
            if target and not self._corrupt_stage:
                stages = self._fit_exact(stages, target)
            suggestions.append({"slot": slot, "stages": stages})
        return ({"suggestions": suggestions},
                {"provider": "fake", "model": "fake-model", "call_id": "c", "usage": {"total_tokens": 7}})


def real_calls() -> int:
    return adapter.provider_call_receipt()["request_count_since_process_start"]


async def bootstrap_ready_benefit(product_id: str = "prod_cr",
                                  benefit_text: str = SUPPORTED_BENEFIT) -> dict[str, Any]:
    """Seed product + approved PI snapshot + a VERIFIED benefit, then build its
    Creative Atoms with an injected fake. Returns identifiers + the atom-fake."""
    db = await get_db()
    await seed_product_ready(db, product_id)
    snapshot_id = await make_product_copy_eligible(product_id)
    benefit = await cfsvc.create_benefit(product_id, benefit_text, None)
    assert benefit["status"] == "VERIFIED", benefit["status"]
    atom_fake = CFAtomFake()
    await cfsvc.build_benefit_atoms(product_id, benefit["benefit_id"], provider=atom_fake)
    capacity = await cfsvc.product_capacity(product_id)
    binfo = {b["benefit_id"]: b for b in capacity["per_benefit"]}[benefit["benefit_id"]]
    assert binfo["ready"] and binfo["combinations"] > 0, binfo
    return {"product_id": product_id, "benefit_id": benefit["benefit_id"],
            "snapshot_id": snapshot_id, "combinations": int(binfo["combinations"]),
            "atom_fake": atom_fake}
