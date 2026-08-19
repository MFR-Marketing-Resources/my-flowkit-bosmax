"""Mascot Montage Creative Grammar V1.1 — pure, provider-free.

Resolves a FINAL video duration into a canonical discrete block plan (THROUGH
``canonical_prompt_compiler.resolve_block_plan`` — never a second block table) and
the compatible SINGLE model(s) (THROUGH ``video_capability_matrix``), then composes
a DISTINCT natural-language creative-grammar direction per Montage scene:

  per-block macro purpose + scene objective/visual_action + four progressive
  micro-beats (scaled to the atomic block) + a small governed mascot action
  vocabulary + a lip-sync contract (when the mascot speaks) + product/mascot
  identity continuity + a visual-dynamism requirement (>=3 perceptible changes).

The output is ONLY natural video-production language. It carries no WPS numbers,
enum names, DB columns, internal ids, or FRAMES/source-mode vocabulary — the
canonical compiler no-leakage scrub remains the final guard at compile time.

No new duration / model / WPS SSOT is introduced here: every numeric authority is
resolved by calling the existing canonical services.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from agent.services import canonical_prompt_compiler as _canonical
from agent.services import video_capability_matrix as _cap

DEFAULT_ENGINE = "GOOGLE_FLOW"
DEFAULT_LANGUAGE = "BM_MS"
ERR_UNSUPPORTED_FINAL_DURATION = "ERR_MASCOT_UNSUPPORTED_FINAL_DURATION"

# V1.1 SCOPE GATE ONLY. This tuple bounds the operator menu to 1-3 uniform blocks;
# it does NOT encode block structure. The block PLAN for each final is resolved
# THROUGH canonical_prompt_compiler.resolve_block_plan (the workbook authority),
# and a mismatch/non-uniform/out-of-range plan fails closed. A test asserts each
# entry round-trips through the authority to the expected plan.
V11_FINAL_DURATIONS: tuple[int, ...] = (8, 10, 16, 20, 24, 30)

SINGLE_FINALIZE = "SINGLE_FINALIZE"
DISCRETE_MONTAGE = "DISCRETE_MONTAGE"

# Four progressive micro-beats — normalized proportions (choreography guidance,
# NOT a duration authority). Scaled to the atomic block seconds at compile time.
_MICRO_BEATS: tuple[tuple[str, float, float, str], ...] = (
    ("HOOK", 0.00, 0.22, "Hook / Reaction"),
    ("PRODUCT_CUE", 0.22, 0.48, "Movement / Product Cue"),
    ("DEMONSTRATION", 0.48, 0.73, "Demonstration / Explanation"),
    ("OUTCOME", 0.73, 1.00, "Outcome / CTA / Hero"),
)

# Small governed mascot action vocabulary (a configuration, NOT a choreography
# database). Selection is deterministic per scene so two blocks differ.
_ACTION_VOCAB: dict[str, tuple[str, ...]] = {
    "HOOK": (
        "notices something and reacts straight to camera",
        "steps briskly into frame with an expressive double-take",
        "turns sharply toward the problem and points it out",
        "interrupts the shot, grabbing the viewer's attention",
    ),
    "PRODUCT_CUE": (
        "points clearly to the product label",
        "taps the product body and presents it toward camera",
        "repositions beside the product and gestures to it",
        "lifts the product into a confident presenting pose",
    ),
    "DEMONSTRATION": (
        "mimes the product's usage motion with energy",
        "acts out the benefit physically in the scene",
        "interacts with the surrounding environment to show the effect",
        "mirrors a supporting human's action beside the product",
    ),
    "OUTCOME": (
        "breaks into a delighted, confident reaction",
        "reveals the positive result and holds a proud hero stance",
        "gives a decisive point to the product and a thumbs-up to camera",
        "takes a controlled step toward camera for the closing CTA",
    ),
}


def block_purposes(block_count: int) -> list[tuple[str, str, str]]:
    """(key, short_label, macro_objective) per block — macro intent, not wording.

    1 block  -> one complete hook-to-outcome arc.
    2 blocks -> Hook/Problem ; Demonstration/Benefit/CTA.
    3 blocks -> Hook/Problem ; Demonstration/Benefit ; Outcome/CTA.
    """
    if block_count <= 1:
        return [(
            "FULL_ARC", "Hook to Outcome",
            "Carry the entire arc in one scene: hook attention, cue the product, "
            "demonstrate the benefit, and close on a confident product-hero CTA",
        )]
    if block_count == 2:
        return [
            ("HOOK_PROBLEM", "Hook / Problem",
             "Grab attention and dramatize the problem the product solves"),
            ("DEMO_BENEFIT_CTA", "Demonstration / Benefit / CTA",
             "Demonstrate the product, land the benefit, and close on a confident CTA"),
        ]
    return [
        ("HOOK_PROBLEM", "Hook / Problem",
         "Grab attention and dramatize the problem the product solves"),
        ("DEMO_BENEFIT", "Demonstration / Benefit",
         "Demonstrate the product in use and reveal the benefit"),
        ("OUTCOME_CTA", "Outcome / CTA",
         "Land the positive outcome and a confident product-hero CTA close"),
    ]


def micro_beats(atomic_seconds: int) -> list[dict[str, Any]]:
    """Four progressive micro-beats scaled to the atomic clip seconds."""
    out: list[dict[str, Any]] = []
    for key, lo, hi, label in _MICRO_BEATS:
        out.append({
            "key": key,
            "label": label,
            "start_s": round(atomic_seconds * lo, 1),
            "end_s": round(atomic_seconds * hi, 1),
        })
    return out


@dataclass(frozen=True)
class MascotDurationPlan:
    final_seconds: int
    atomic_seconds: int
    block_plan: tuple[int, ...]
    block_count: int
    engine: str
    language: str
    models: tuple[str, ...]       # ui_labels valid for the atomic SINGLE clip
    default_model: str            # ui_label
    per_block_word_budget: int    # SWEET WPS for the atomic block + language
    assembly: str                 # SINGLE_FINALIZE | DISCRETE_MONTAGE

    def label(self) -> str:
        scene_word = "scene" if self.block_count == 1 else "scenes"
        base = f"{self.final_seconds} seconds · {self.block_count} {scene_word} × {self.atomic_seconds}s"
        # Surface the model only when it is forced to one (e.g. Omni Flash @10s).
        if len(self.models) == 1:
            base = f"{base} · {self.models[0]}"
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_seconds": self.final_seconds,
            "atomic_seconds": self.atomic_seconds,
            "block_plan": list(self.block_plan),
            "block_count": self.block_count,
            "engine": self.engine,
            "language": self.language,
            "models": list(self.models),
            "default_model": self.default_model,
            "per_block_word_budget": self.per_block_word_budget,
            "assembly": self.assembly,
            "label": self.label(),
        }


def resolve_final_duration_plan(
    final_seconds: int,
    *,
    engine: str = DEFAULT_ENGINE,
    language: str = DEFAULT_LANGUAGE,
    wps_mode: str = "SWEET",
) -> MascotDurationPlan:
    """final duration -> canonical block plan -> atomic block -> compatible model(s)
    -> scene count. Fail-closed. Resolves entirely through existing authorities.
    """
    try:
        final = int(final_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ERR_UNSUPPORTED_FINAL_DURATION}:{final_seconds!r}") from exc
    if final not in V11_FINAL_DURATIONS:
        raise ValueError(f"{ERR_UNSUPPORTED_FINAL_DURATION}:{final}:OUT_OF_V11_SCOPE")

    # Block plan from the canonical workbook authority (never a local table).
    try:
        blocks = [int(b) for b in _canonical.resolve_block_plan(engine, final)]
    except ValueError as exc:
        raise ValueError(f"{ERR_UNSUPPORTED_FINAL_DURATION}:{final}:{exc}") from exc
    if not blocks:
        raise ValueError(f"{ERR_UNSUPPORTED_FINAL_DURATION}:{final}:EMPTY_BLOCK_PLAN")
    atomic = blocks[0]
    if any(b != atomic for b in blocks):
        raise ValueError(f"{ERR_UNSUPPORTED_FINAL_DURATION}:{final}:NON_UNIFORM_BLOCKS:{blocks}")
    count = len(blocks)
    if not (1 <= count <= 3):
        raise ValueError(f"{ERR_UNSUPPORTED_FINAL_DURATION}:{final}:BLOCK_COUNT_OUT_OF_V11_RANGE:{count}")

    # Compatible SINGLE model(s) for the atomic block via the capability matrix.
    matrix_models = _cap.models_for_single(engine, atomic)
    models = tuple(m["ui_label"] for m in matrix_models if m.get("ui_label"))
    if not models:
        raise ValueError(f"{ERR_UNSUPPORTED_FINAL_DURATION}:{final}:NO_MODEL_FOR_ATOMIC:{atomic}")
    default_key = _cap.default_model_for_single(engine, atomic)
    default_model = next(
        (m["ui_label"] for m in matrix_models if m.get("key") == default_key),
        models[0],
    )

    # Per-atomic-block dialogue word budget from the canonical WPS authority (SWEET).
    budget = int(_canonical.dialogue_word_budget(atomic, language, wps_mode=wps_mode))

    return MascotDurationPlan(
        final_seconds=final,
        atomic_seconds=atomic,
        block_plan=tuple(blocks),
        block_count=count,
        engine=engine,
        language=language,
        models=models,
        default_model=default_model,
        per_block_word_budget=budget,
        assembly=SINGLE_FINALIZE if count == 1 else DISCRETE_MONTAGE,
    )


def duration_options(
    *, engine: str = DEFAULT_ENGINE, language: str = DEFAULT_LANGUAGE
) -> list[dict[str, Any]]:
    """Operator-facing menu of the V1.1 final durations, each resolved through the
    authority. Any final the authority cannot resolve is silently omitted."""
    out: list[dict[str, Any]] = []
    for final in V11_FINAL_DURATIONS:
        try:
            out.append(resolve_final_duration_plan(final, engine=engine, language=language).to_dict())
        except ValueError:
            continue
    return out


def _select(vocab_key: str, block_index: int) -> str:
    options = _ACTION_VOCAB[vocab_key]
    return options[block_index % len(options)]


def scene_beats(block_count: int) -> list[dict[str, str]]:
    """Story beats (one per block) carrying each block's macro objective + a
    concrete visual action. Distinct per block so prompts differentiate."""
    beats: list[dict[str, str]] = []
    for i, (key, label, objective) in enumerate(block_purposes(block_count)):
        beats.append({
            "beat_id": f"mascot-block-{i + 1}",
            "role": key,
            "objective": objective,
            "visual_action": (
                f"Mascot {_select('HOOK', i)}; then {_select('PRODUCT_CUE', i)}, "
                f"{_select('DEMONSTRATION', i)}, and {_select('OUTCOME', i)}"
            ),
        })
    return beats


def compose_scene_context(
    *,
    block_index: int,
    block_count: int,
    atomic_seconds: int,
    objective: str = "",
    visual_action: str = "",
    has_dialogue: bool = True,
    existing_context: Optional[str] = None,
) -> str:
    """Compose a DISTINCT natural-language creative direction for one mascot scene.

    Composes (never overwrites) the already-resolved hook/background/creative
    context with: this block's macro purpose, its objective + visual action, the
    four progressive micro-beats, the mascot action grammar, a lip-sync contract
    (when the mascot speaks), product/mascot identity continuity, and an explicit
    visual-dynamism requirement. Emits only natural production language.
    """
    purposes = block_purposes(block_count)
    idx = max(0, min(block_index, len(purposes) - 1))
    _key, short_label, macro_objective = purposes[idx]
    beats = micro_beats(atomic_seconds)
    scene_no = idx + 1

    lines: list[str] = []
    if existing_context and existing_context.strip():
        lines.append(existing_context.strip())

    if block_count == 1:
        lines.append(
            f"PRODUCT MASCOT COMMERCIAL — one energetic {atomic_seconds}-second scene "
            f"carrying the whole story: {short_label}."
        )
    else:
        lines.append(
            f"PRODUCT MASCOT COMMERCIAL — scene {scene_no} of {block_count} "
            f"({atomic_seconds}s each). This scene's job: {short_label}."
        )
    lines.append(f"Scene objective: {objective or macro_objective}.")
    if visual_action:
        lines.append(f"Mascot action for this scene: {visual_action}.")

    lines.append(
        "The Product Mascot is the ACTIVE on-screen actor and hero — never a static "
        "prop delivering voiceover. Keep the pacing energetic and commercial, with "
        "supporting environment or human action around the mascot."
    )

    # Four progressive micro-beats, scaled to this clip.
    micro = "; ".join(
        f"{b['start_s']}–{b['end_s']}s {b['label']}" for b in beats
    )
    lines.append(
        f"Progress through four beats within the {atomic_seconds}s clip: {micro}."
    )

    # Visual dynamism hard requirement (>=3 perceptible changes).
    lines.append(
        "Show at least THREE distinct visual-state changes across the clip — for "
        "example a cut, a clear camera-distance change, and a camera-angle change or "
        "a meaningful mascot move. Do NOT hold one continuous static talking shot."
    )

    # Lip-sync contract when the mascot speaks.
    if has_dialogue:
        lines.append(
            "The mascot is the actual on-screen speaker: its mouth moves continuously "
            "while it speaks, forming visibly open, closed, rounded and wide mouth "
            "shapes synchronized to the spoken syllables, with matching eyebrow and "
            "facial expression. No frozen smile while dialogue is playing, and no "
            "off-screen narrator or background character speaking the mascot's lines. "
            "Speech begins immediately with no dead opening."
        )

    # Product / mascot identity continuity.
    lines.append(
        "Preserve exact continuity of the product silhouette, packaging proportions, "
        "label and branding, and the mascot's facial identity, limbs and shoes, at a "
        "believable real-product scale."
    )

    # Strong product-hero ending.
    lines.append(
        "End on a strong product-hero moment with the product clearly featured."
    )
    return "\n".join(lines)
