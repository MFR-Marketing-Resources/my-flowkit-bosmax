"""Canonical reference binding UI contract — eligibility diagnostics.

Operator Workspace pickers must never silently empty: when backend eligibility
returns 0 bindable assets, the controls surface audit counts + exclusion reasons
(same contract as F2VModule / I2VModule audit cards).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_canonical_binding_loads_eligibility_audit_per_surface():
    src = _read(
        "dashboard/src/components/workspace/CanonicalReferenceBindingControls.tsx"
    )
    assert 'import { fetchCreativeAssetEligibilityAudit } from "../../api/creativeAssets"' in src
    assert '"F2V_START_FRAME_PICKER"' in src
    assert '"F2V_END_FRAME_PICKER"' in src
    assert '"I2V_CHARACTER_PICKER"' in src
    assert '"I2V_SCENE_PICKER"' in src
    assert '"I2V_STYLE_PICKER"' in src
    assert '"HYBRID_START_FRAME_PICKER"' in src
    assert "eligible_assets" in src


def test_canonical_binding_surfaces_exclusion_reasons_not_silent_empty():
    src = _read(
        "dashboard/src/components/workspace/CanonicalReferenceBindingControls.tsx"
    )
    assert "BINDING_AUDIT_REASON_LABELS" in src
    assert "renderSurfaceAuditCard" in src
    assert "NOT_APPROVED_FOR_REUSE" in src
    assert "ENGINE_SLOT_NOT_ALLOWED" in src
    assert "Assets found but none eligible for this surface" in src
    assert "binding-audit-${surface}" in src
    assert "binding-picker-${surface}" in src
    assert "exact eligibility exclusion reasons" in src


def test_operator_page_wires_canonical_binding_into_package_payload():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "CanonicalReferenceBindingControls" in src
    assert "start_frame_asset_id" in src
    assert "character_reference_asset_id" in src
    assert "scene_context_reference_asset_id" in src
    assert "referenceBindingBlocker" in src


def test_canonical_binding_resolvable_source_not_media_id_only():
    """IMG factory LOCAL_FILE saves often have preview_url but no 48h media_id.

    Picker bindability must match backend `_asset_has_resolvable_source` so
    clean COMPOSITE_FRAME assets remain selectable without loosening gates.
    """
    src = _read(
        "dashboard/src/components/workspace/CanonicalReferenceBindingControls.tsx"
    )
    assert "function assetHasResolvableSource" in src
    assert "asset.preview_url" in src
    assert "asset.local_file_path" in src
    assert "asset.download_url" in src
    assert "disabled={!resolvable}" in src
    # Must not hard-gate solely on media_id (legacy bug that blocked base64 saves).
    assert "disabled={!asset.media_id}" not in src
    assert 'asset.media_id ? "" : " (no media — not bindable)"' not in src
