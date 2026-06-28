"""Deterministic, fail-closed build-identity proof for the live Flow runtime.

Historical defect this module fixes
------------------------------------
"Current loaded build" was being inferred from the most recent persisted
``request_telemetry`` row. That row survives extension reloads, so after a reload
to a new build the latest row still carries the OLD build id and is read as if it
were current proof. Result: a runtime that is actually running build B reports as
build A forever, and no live UAT can be trusted.

Design
------
This module NEVER reads persisted telemetry. It evaluates ONLY a *live* runtime
self-test snapshot (the no-credit ``GET_RUNTIME_SELF_TEST`` handshake) and fails
**closed** with an exact reason whenever current-page proof is missing, stale, or
mismatched. A PASS verdict therefore proves the build that is loaded *right now*
on the *active Flow tab* — tied to extension id, tab id, page url, and timestamp.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ─── Verdicts ────────────────────────────────────────────────
PASS = "PASS"
BLOCK = "BLOCK"

# ─── Block reasons (exact, machine-checkable) ────────────────
REASON_NO_SELF_TEST = "NO_SELF_TEST"
REASON_EXTENSION_OFFLINE = "EXTENSION_OFFLINE"
REASON_BACKGROUND_BUILD_MISSING = "BACKGROUND_BUILD_MISSING"
REASON_BACKGROUND_BUILD_MISMATCH = "BACKGROUND_BUILD_MISMATCH"
REASON_NO_FLOW_TAB = "NO_FLOW_TAB"
REASON_MISSING_CONTENT_SCRIPT = "MISSING_CONTENT_SCRIPT"
REASON_CONTENT_BUILD_MISSING = "CONTENT_BUILD_MISSING"
REASON_BUILD_MISMATCH = "BUILD_MISMATCH"
REASON_BUILD_MATCH_NOT_PROVEN = "BUILD_MATCH_NOT_PROVEN"
REASON_STALE_HANDSHAKE = "STALE_HANDSHAKE"

DEFAULT_FRESHNESS_SECONDS = 120

# Build id literal shape, e.g. flowkit-gfv2-post-submit-proof-2026-06-28a
BUILD_ID_LITERAL_RE = re.compile(r"flowkit-[a-z0-9-]*\d{4}-\d{2}-\d{2}[a-z0-9-]*")
_CONTENT_BUILD_ID_RE = re.compile(
    r"""FLOW_KIT_DOM_BUILD_ID\s*=\s*['"]([^'"]+)['"]"""
)


@dataclass
class BuildProofVerdict:
    verdict: str
    reason: Optional[str] = None
    detail: Optional[str] = None
    expected_build_id: Optional[str] = None
    background_build_id: Optional[str] = None
    runner_build_id: Optional[str] = None
    content_build_id: Optional[str] = None
    build_match: bool = False
    extension_id: Optional[str] = None
    tab_id: Optional[Any] = None
    page_url: Optional[str] = None
    handshake_timestamp: Optional[str] = None
    evaluated_at: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.verdict == PASS

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "detail": self.detail,
            "expected_build_id": self.expected_build_id,
            "background_build_id": self.background_build_id,
            "runner_build_id": self.runner_build_id,
            "content_build_id": self.content_build_id,
            "build_match": self.build_match,
            "extension_id": self.extension_id,
            "tab_id": self.tab_id,
            "page_url": self.page_url,
            "handshake_timestamp": self.handshake_timestamp,
            "evaluated_at": self.evaluated_at,
        }


def read_canonical_build_id(base_dir: Path) -> Optional[str]:
    """Single source of truth: parse FLOW_KIT_DOM_BUILD_ID from the injected
    content script. All other build constants are asserted equal to this by the
    SSOT regression test."""
    content_script = Path(base_dir) / "extension" / "content-flow-dom.js"
    try:
        text = content_script.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _CONTENT_BUILD_ID_RE.search(text)
    return match.group(1) if match else None


def _first(snapshot: dict, *keys: str) -> Optional[str]:
    for key in keys:
        value = snapshot.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _nested(snapshot: dict, parent: str, *keys: str) -> Optional[str]:
    child = snapshot.get(parent)
    if isinstance(child, dict):
        return _first(child, *keys)
    return None


def _has_flow_tab(snapshot: dict) -> bool:
    if snapshot.get("flow_tab_found") is True:
        return True
    if snapshot.get("target_tab"):
        return True
    tabs = snapshot.get("flow_tabs")
    if isinstance(tabs, list) and len(tabs) > 0:
        return True
    return False


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate_build_proof(
    self_test: Optional[dict],
    expected_build_id: Optional[str],
    *,
    now: datetime,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
) -> BuildProofVerdict:
    """Fail-closed evaluation of a live runtime self-test snapshot.

    Returns PASS only when, on the CURRENT active Flow tab, both the background
    and the content-script builds equal ``expected_build_id``, the extension's
    own ``build_match`` flag is true, and the handshake is fresh. Anything else
    is BLOCK with an exact reason. Persisted telemetry is never consulted.
    """
    evaluated_at = now.astimezone(timezone.utc).isoformat()

    def block(reason: str, detail: str, **extra: Any) -> BuildProofVerdict:
        return BuildProofVerdict(
            verdict=BLOCK,
            reason=reason,
            detail=detail,
            expected_build_id=expected_build_id,
            evaluated_at=evaluated_at,
            **extra,
        )

    if not isinstance(self_test, dict) or not self_test:
        return block(REASON_NO_SELF_TEST, "No live self-test snapshot was returned.")

    connected = self_test.get("connected")
    agent_connected = self_test.get("agentConnected")
    if connected is False and agent_connected is False:
        return block(REASON_EXTENSION_OFFLINE, "Extension WebSocket is not connected.")

    background = _first(self_test, "background_build_id", "build_id", "buildId", "gitSha", "git_sha")
    runner = _first(self_test, "runner_build_id")
    extension_id = _first(self_test, "extension_id", "extensionId")
    if not background:
        return block(
            REASON_BACKGROUND_BUILD_MISSING,
            "Self-test did not report a background build id.",
            runner_build_id=runner,
            extension_id=extension_id,
        )
    if expected_build_id and background != expected_build_id:
        return block(
            REASON_BACKGROUND_BUILD_MISMATCH,
            f"background_build_id={background} expected={expected_build_id}",
            background_build_id=background,
            runner_build_id=runner,
            extension_id=extension_id,
        )

    # A background-only match is NOT proof. The content script on a live page must
    # confirm the same build, otherwise we cannot distinguish a reloaded background
    # paired with a stale injected content script.
    if not _has_flow_tab(self_test):
        return block(
            REASON_NO_FLOW_TAB,
            "No Google Flow tab is open; content-script build cannot be proven.",
            background_build_id=background,
            runner_build_id=runner,
            extension_id=extension_id,
        )

    target_tab = self_test.get("target_tab") if isinstance(self_test.get("target_tab"), dict) else {}
    page_url = _first(self_test, "flow_tab_url", "flow_url") or _first(target_tab, "url")
    tab_id = self_test.get("flow_tab_id")
    if tab_id is None:
        tab_id = target_tab.get("tab_id") if isinstance(target_tab, dict) else None

    content_alive = self_test.get("content_script_alive_on_active_tab")
    if content_alive is None:
        content_alive = _nested(self_test, "page_diagnostic", "content_script_alive")
    if content_alive is False:
        return block(
            REASON_MISSING_CONTENT_SCRIPT,
            "Content script is not alive on the active Flow tab.",
            background_build_id=background, runner_build_id=runner,
            extension_id=extension_id, tab_id=tab_id, page_url=page_url,
        )

    content = _first(self_test, "content_build_id") or _nested(
        self_test, "page_diagnostic", "content_build_id"
    )
    if not content:
        return block(
            REASON_CONTENT_BUILD_MISSING,
            "No content-script build id was reported from the active page.",
            background_build_id=background, runner_build_id=runner,
            extension_id=extension_id, tab_id=tab_id, page_url=page_url,
        )
    if expected_build_id and content != expected_build_id:
        return block(
            REASON_BUILD_MISMATCH,
            f"content_build_id={content} background_build_id={background} expected={expected_build_id}",
            background_build_id=background, runner_build_id=runner,
            content_build_id=content, extension_id=extension_id,
            tab_id=tab_id, page_url=page_url,
        )
    if content != background:
        return block(
            REASON_BUILD_MISMATCH,
            f"content_build_id={content} != background_build_id={background}",
            background_build_id=background, runner_build_id=runner,
            content_build_id=content, extension_id=extension_id,
            tab_id=tab_id, page_url=page_url,
        )

    if self_test.get("build_match") is not True:
        return block(
            REASON_BUILD_MATCH_NOT_PROVEN,
            "Extension did not assert build_match=true for the active page.",
            background_build_id=background, runner_build_id=runner,
            content_build_id=content, extension_id=extension_id,
            tab_id=tab_id, page_url=page_url,
        )

    handshake_ts = _first(self_test, "timestamp", "last_updated_at")
    parsed_ts = _parse_iso(handshake_ts)
    if parsed_ts is None:
        return block(
            REASON_STALE_HANDSHAKE,
            "Self-test snapshot has no parseable timestamp; cannot prove freshness.",
            background_build_id=background, runner_build_id=runner,
            content_build_id=content, extension_id=extension_id,
            tab_id=tab_id, page_url=page_url, handshake_timestamp=handshake_ts,
        )
    age = (now.astimezone(timezone.utc) - parsed_ts).total_seconds()
    if age > freshness_seconds or age < -freshness_seconds:
        return block(
            REASON_STALE_HANDSHAKE,
            f"Handshake age {age:.1f}s exceeds freshness window {freshness_seconds}s.",
            background_build_id=background, runner_build_id=runner,
            content_build_id=content, extension_id=extension_id,
            tab_id=tab_id, page_url=page_url, handshake_timestamp=handshake_ts,
        )

    return BuildProofVerdict(
        verdict=PASS,
        reason=None,
        detail="Live content-page handshake proves the loaded build.",
        expected_build_id=expected_build_id,
        background_build_id=background,
        runner_build_id=runner,
        content_build_id=content,
        build_match=True,
        extension_id=extension_id,
        tab_id=tab_id,
        page_url=page_url,
        handshake_timestamp=handshake_ts,
        evaluated_at=evaluated_at,
    )
