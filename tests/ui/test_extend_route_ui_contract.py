"""UI contract: the operator surface distinguishes independent blocks vs native
Extend vs Download-Project-ZIP vs final concat export, and NEVER labels the
Download Project ZIP as the combined final video."""
import os

_TS = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "dashboard", "src", "utils", "nativeExtendCapability.ts")


def _read():
    with open(_TS, encoding="utf-8") as f:
        return f.read()


def test_four_distinct_routes_present():
    t = _read()
    for label in ["Independent Block Plan", "Native Flow Extend",
                  "Download Project ZIP", "Final Timeline Render"]:
        assert label in t, f"missing route label: {label}"


def test_download_zip_not_labelled_combined_final_video():
    t = _read()
    assert "NOT a combined final video" in t
    assert "consumes no generation credit" in t


def test_final_render_authorized_but_execute_gated():
    t = _read()
    # captured contract makes the final render selectable — but the copy must keep
    # the explicit-confirmation gate and never offer the ZIP as a substitute.
    assert "ONE combined full-duration MP4" in t
    assert "explicit confirmation" in t
    assert "not a substitute" in t.lower()


def test_native_extend_route_declared_authorized():
    t = _read()
    assert "GOOGLE_FLOW_NATIVE_EXTEND" in t
    assert "veo_3_1_extension_lite" in t
