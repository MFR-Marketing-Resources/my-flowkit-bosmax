"""Deterministic spoken-CTA fitting authority for final-block WPS budgets.

Canonical approved CTA text remains immutable provenance. Spoken CTA may be
compacted only when the exact CTA cannot fit the final spoken-dialogue budget.

No provider calls. Claim-safe. Final-block-only (callers enforce placement).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from agent.services import canonical_prompt_compiler as canonical

FIT_EXACT = "EXACT"
FIT_DETERMINISTIC_COMPACT = "DETERMINISTIC_COMPACT"
FIT_BLOCKED = "BLOCKED"

METHOD_EXACT = "exact_canonical"
METHOD_CLAUSE_PACK = "clause_pack_from_canonical"
METHOD_ACTION_CLAUSE = "action_bearing_clause"
METHOD_NATURAL_TRIM = "natural_trim_from_canonical"
METHOD_TYPE_SAFE_COMPACT = "type_safe_action_compact"
METHOD_BLOCKED = "blocked_cannot_fit"


@dataclass(frozen=True)
class CtaFitResult:
    canonical_cta_text: str
    spoken_cta_text: str
    original_word_count: int
    spoken_word_count: int
    final_block_word_budget: int
    fit_status: str
    fit_method: str
    was_compacted: bool
    cta_type: str
    target_language: str
    wps_mode: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _word_count(text: str) -> int:
    cleaned = _clean(text)
    return len(cleaned.split()) if cleaned else 0


def _ensure_terminal_punct(text: str) -> str:
    cleaned = _clean(text)
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        return f"{cleaned}."
    return cleaned


def _action_tokens_for_type(cta_type: str) -> tuple[str, ...]:
    return {
        "direct_checkout": (
            "checkout", "grab", "beg kuning", "buy", "order", "try", "cuba",
            "sekarang", "beli", "order now", "buy now",
        ),
        "standby_now": (
            "jangan tunggu", "promo", "stok", "today", "sekarang", "before habis",
            "limited", "habis",
        ),
        "add_to_kit": (
            "cart", "troli", "kit", "routine", "stash", "masuk", "add",
        ),
        "save_for_later": (
            "save", "simpan", "bookmark", "later",
        ),
        "comment_signal": (
            "comment", "komen", "reply", "drop", "nak link",
        ),
        "private_action": (
            "dm", "pm", "inbox", "whatsapp", "ws", "message",
        ),
    }.get(str(cta_type or "").strip().lower(), ())


def _has_action_signal(text: str, cta_type: str, *, canonical_text: str) -> bool:
    """Require an action cue present in both candidate and canonical when possible."""
    candidate = _clean(text).lower()
    source = _clean(canonical_text).lower()
    if not candidate:
        return False
    tokens = _action_tokens_for_type(cta_type)
    if tokens:
        matched = [tok for tok in tokens if tok in candidate]
        if not matched:
            return False
        # Prefer tokens that also appear in the approved CTA (claim-safe reuse).
        return any(tok in source for tok in matched)
    # Untyped / unknown: require at least one shared content word (>=4 chars)
    # with the canonical CTA so we never invent a free-standing pitch.
    stop = {
        "yang", "dan", "atau", "untuk", "dengan", "kalau", "this", "that", "with",
        "your", "anda", "korang", "kamu", "the", "and", "for", "from",
    }
    cand_words = {
        w for w in candidate.replace(".", " ").split()
        if len(w) >= 4 and w not in stop
    }
    src_words = {
        w for w in source.replace(".", " ").split()
        if len(w) >= 4 and w not in stop
    }
    return bool(cand_words & src_words)


def _type_safe_compact_bank(cta_type: str, target_language: str) -> tuple[str, ...]:
    """Shortest-first action lines. Used only when action tokens exist in canonical."""
    is_ms = canonical.language_name(target_language) == "Malay"
    bm = {
        "direct_checkout": ("Cuba sekarang.", "Grab sekarang.", "Checkout sekarang."),
        "standby_now": ("Jangan tunggu.", "Ambil sekarang."),
        "add_to_kit": ("Masuk troli.", "Masukkan ke kit."),
        "save_for_later": ("Simpan dulu.", "Save dulu."),
        "comment_signal": ("Komen je.", "Drop comment."),
        "private_action": ("DM terus.", "Inbox je."),
    }
    en = {
        "direct_checkout": ("Try now.", "Grab it now.", "Check out now."),
        "standby_now": ("Do not wait.", "Get it now."),
        "add_to_kit": ("Add to cart.", "Add it to your kit."),
        "save_for_later": ("Save it first.", "Bookmark this."),
        "comment_signal": ("Just comment.", "Drop a comment."),
        "private_action": ("DM me.", "Message for the link."),
    }
    bank = bm if is_ms else en
    return bank.get(str(cta_type or "").strip().lower(), ())


def _pick_action_clauses(clauses: list[str], cta_type: str, canonical_text: str) -> list[str]:
    action = [c for c in clauses if _has_action_signal(c, cta_type, canonical_text=canonical_text)]
    if action:
        return action
    # Prefer the terminal clause (often the action) then earlier ones.
    if not clauses:
        return []
    return list(reversed(clauses))


def fit_spoken_cta(
    *,
    canonical_cta_text: str,
    final_block_word_budget: int,
    target_language: str,
    wps_mode: str = "SAFE",
    cta_type: str | None = None,
    resolved_block_plan: list[int] | tuple[int, ...] | None = None,  # noqa: ARG001 - reserved for callers
) -> CtaFitResult:
    """Fit approved CTA into the final spoken block budget.

    Returns structured evidence. BLOCKED means callers must fail closed.
    """
    canonical_text = _clean(canonical_cta_text)
    budget = max(0, int(final_block_word_budget or 0))
    resolved_type = _clean(cta_type) or canonical._infer_cta_type({"cta": canonical_text}, canonical_text)
    original_words = _word_count(canonical_text)
    lang = str(target_language or "BM_MS")
    mode = str(wps_mode or "SAFE").upper()

    def _result(
        spoken: str,
        status: str,
        method: str,
    ) -> CtaFitResult:
        spoken_clean = _ensure_terminal_punct(spoken) if spoken else ""
        spoken_words = _word_count(spoken_clean)
        compacted = bool(spoken_clean) and _clean(spoken_clean) != canonical_text and status == FIT_DETERMINISTIC_COMPACT
        if status == FIT_EXACT:
            spoken_clean = canonical_text
            spoken_words = original_words
            compacted = False
        return CtaFitResult(
            canonical_cta_text=canonical_text,
            spoken_cta_text=spoken_clean,
            original_word_count=original_words,
            spoken_word_count=spoken_words,
            final_block_word_budget=budget,
            fit_status=status,
            fit_method=method,
            was_compacted=compacted,
            cta_type=resolved_type,
            target_language=lang,
            wps_mode=mode,
        )

    if not canonical_text:
        return _result("", FIT_EXACT, METHOD_EXACT)

    if budget <= 0:
        return _result("", FIT_BLOCKED, METHOD_BLOCKED)

    if original_words <= budget:
        return _result(canonical_text, FIT_EXACT, METHOD_EXACT)

    clauses = canonical._split_clauses(canonical_text)
    if not clauses:
        clauses = [canonical_text if canonical_text[-1:] in ".!?" else f"{canonical_text}."]

    # Prefer packing action-bearing clauses first so multi-sentence CTAs keep the ask.
    action_first = _pick_action_clauses(clauses, resolved_type, canonical_text)
    pack_order: list[str] = []
    seen_pack: set[str] = set()
    for group in (action_first, clauses):
        for clause in group:
            key = clause.casefold()
            if key in seen_pack:
                continue
            seen_pack.add(key)
            pack_order.append(clause)

    # 1) Pack whole natural clauses from the canonical CTA (no invention).
    packed = canonical._pack_dialogue_clauses(pack_order, budget)
    if (
        packed
        and _word_count(packed) <= budget
        and _compact_is_acceptable(packed, resolved_type, canonical_text)
    ):
        return _result(packed, FIT_DETERMINISTIC_COMPACT, METHOD_CLAUSE_PACK)

    # 2) Prefer a single action-bearing clause (terminal-first), pack if needed.
    for clause in action_first:
        if _word_count(clause) <= budget and _compact_is_acceptable(
            clause, resolved_type, canonical_text
        ):
            return _result(clause, FIT_DETERMINISTIC_COMPACT, METHOD_ACTION_CLAUSE)
        trimmed = canonical._pack_dialogue_clauses([clause], budget)
        if (
            trimmed
            and _word_count(trimmed) <= budget
            and _compact_is_acceptable(trimmed, resolved_type, canonical_text)
        ):
            return _result(trimmed, FIT_DETERMINISTIC_COMPACT, METHOD_NATURAL_TRIM)

    # 3) Type-safe short action line only when the canonical CTA already carries
    # that action family (no new destination/claim invention).
    if resolved_type and canonical._cta_has_native_signal(canonical_text, resolved_type):
        for line in _type_safe_compact_bank(resolved_type, lang):
            if _word_count(line) <= budget and _has_action_signal(
                line, resolved_type, canonical_text=canonical_text
            ):
                return _result(line, FIT_DETERMINISTIC_COMPACT, METHOD_TYPE_SAFE_COMPACT)

    # 4) Last resort: grounded pack without typed signal only when cta_type is unknown.
    if (
        not resolved_type
        and packed
        and _word_count(packed) <= budget
        and _has_action_signal(packed, "", canonical_text=canonical_text)
    ):
        return _result(packed, FIT_DETERMINISTIC_COMPACT, METHOD_CLAUSE_PACK)

    return _result("", FIT_BLOCKED, METHOD_BLOCKED)


def _compact_is_acceptable(text: str, cta_type: str, canonical_text: str) -> bool:
    """Typed CTAs must keep an action cue grounded in the approved text."""
    if not _clean(text):
        return False
    if cta_type:
        return _has_action_signal(text, cta_type, canonical_text=canonical_text)
    return _has_action_signal(text, "", canonical_text=canonical_text)


def fit_spoken_cta_dict(**kwargs: Any) -> dict[str, Any]:
    return fit_spoken_cta(**kwargs).to_dict()


def extract_cta_fit_from_planner(planner_result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Pull CTA fit diagnostics from a planner result dict, if present."""
    if not planner_result:
        return None
    dialogue = planner_result.get("full_dialogue_plan") or {}
    meta = dialogue.get("compliance_metadata") or {}
    fit = meta.get("cta_fit")
    if isinstance(fit, dict) and fit:
        return dict(fit)
    return None
