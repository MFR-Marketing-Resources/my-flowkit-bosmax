"""Zero-credit post-merge browser contract checks (no live credit, no DOM required)."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "extension" / "flow-ui-driver.js"
FIXTURE = ROOT / "tests" / "fixtures" / "google_flow_ui_contract" / "ui_contract.sanitized.json"


def test_flow_ui_driver_uses_structural_composer_container():
    text = DRIVER.read_text(encoding="utf-8")
    assert "findComposerReferenceContainer" in text
    assert "collectComposerContextRoots" not in text
    assert "composer_panel:editable_text_plus_add_control_ancestor" in text
    assert "FLOWUI_SUBMIT_COMPOSER_CREATE" in text
    assert "UI_INITIAL_SUBMIT_NOT_IN_PHASE2B" not in text
    # Phase-2D: first ancestor wins — no upward replacement loop
    block = text.split("function findComposerReferenceContainer")[1].split("function ")[0]
    assert "let best" not in block
    assert "return el" in block


def test_ui_contract_documents_composer_reference_container():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    block = data["project_view"]["composer_reference_container"]
    assert block["evidence_id"].startswith("composer_panel:")


@pytest.mark.skipif(
    not __import__("os").environ.get("FLOW_UI_LIVE_BROWSER_VALIDATE"),
    reason="Set FLOW_UI_LIVE_BROWSER_VALIDATE=1 with extension connected to Flow tab",
)
def test_live_flow_tab_zero_credit_state_probe():
    """Optional live tab probe: FLOWUI_STATE only (zero credit)."""
    from agent.services.flow_client import get_flow_client

    client = get_flow_client()
    if not client.connected:
        pytest.skip("extension not connected")
    import asyncio

    async def _run():
        return await client.flowui_state()

    res = asyncio.get_event_loop().run_until_complete(_run())
    assert res.get("result", res).get("ok") is True