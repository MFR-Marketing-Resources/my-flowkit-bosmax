"""F2V composite-frame picker UI contract (PR #2).

Asserts the ADDITIVE Creative-Library COMPOSITE_FRAME_REFERENCE picker was added
to F2VModule and that the existing upload / product-default start/end frame slots
remain intact (surgical, not a rewrite).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_f2v_composite_picker_added():
    src = _read("dashboard/src/components/workspace/F2VModule.tsx")
    assert 'import { fetchCreativeAssets } from "../../api/creativeAssets"' in src
    assert "COMPOSITE_FRAME_REFERENCE" in src
    assert "compositeToUploadedAsset" in src
    assert "Pick composite START frame" in src
    assert "Pick composite END frame" in src
    # Picker feeds the SAME start/end frame state used by the upload path.
    assert "setStartAsset(compositeToUploadedAsset(asset))" in src
    assert "setEndAsset(compositeToUploadedAsset(asset))" in src
    # Only ACTIVE, F2V-eligible composites are surfaced.
    assert 'allowed_mode: "F2V"' in src
    assert 'status: "ACTIVE"' in src


def test_f2v_composite_picker_is_approved_only_and_resolver_validated():
    src = _read("dashboard/src/components/workspace/F2VModule.tsx")
    # Only APPROVED composites are surfaced (never PENDING/REJECTED).
    assert 'c.review_status === "APPROVED"' in src
    # Every selection is validated by the backend F2V resolver before it is applied.
    assert 'import { resolveF2vFrameSources } from "../../api/imgFactory"' in src
    assert "handlePickComposite" in src
    assert "resolveF2vFrameSources(" in src
    # A rejected selection (blockers) is NOT applied to the frame.
    assert "response.blockers.some" in src


def test_f2v_existing_upload_slots_intact():
    src = _read("dashboard/src/components/workspace/F2VModule.tsx")
    # The additive picker must NOT have removed the proven upload/product slots.
    for token in [
        "Start Frame (Reference Image)",
        "End Frame (Optional)",
        "Upload start frame",
        "Upload end frame",
        'handleFileChange("start", e)',
        'handleFileChange("end", e)',
        "WorkspaceImageAssetSlot",
    ]:
        assert token in src, token
