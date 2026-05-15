from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_prompt_preview_result_panel_uses_wrap_safe_warning_and_provenance_structure():
    source = _read("dashboard/src/components/prompt-preview/PromptPreviewResultPanel.tsx")

    for token in [
        "bosmax-json-block",
        "bosmax-pre-wrap-safe",
        "bosmax-warning-list",
        "bosmax-warning-chip",
        "bosmax-provenance-list",
        "bosmax-kv-row",
        "Provenance",
        "Planner Output",
        "Temporal Output",
    ]:
        assert token in source


def test_prompt_preview_page_keeps_long_header_tokens_wrap_safe():
    source = _read("dashboard/src/pages/PromptPreviewPage.tsx")

    assert "bosmax-wrap-safe mt-2 max-w-4xl text-sm text-slate-300" in source
    assert "bosmax-wrap-safe rounded-2xl border border-slate-800 bg-slate-900/60" in source
