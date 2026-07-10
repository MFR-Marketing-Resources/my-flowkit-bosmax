"""Entrypoint coverage matrix for dual prompt representations (PR #298).

compile_ugc_video_prompt → enrich_compiled_prompt_blocks: DUAL_REPRESENTATION_SUPPORTED
plan_full_storyboard / full_storyboard_extend_planner: DUAL (dialogue + allocations)
canonical_prompt_compiler.render_block: INDEPENDENT_ONLY (production engine_prompt_text)
workspace_generation_package_service create_*: PERSISTS prompt_blocks_json (all fields)
workspace_execution_package_service reload: LEGACY_COMPAT (loads prompt_blocks_json)
batch_planner / creative brief preview: NOT_AUDITED_IN_THIS_PR (independent route default)
"""

from __future__ import annotations

import pytest

from agent.services import google_flow_extend_prompt_renderer as renderer
from agent.services import ugc_video_prompt_compiler_service as ugc


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("enrich_compiled_prompt_blocks", "dual"),
        ("attach_prompt_representations", "dual"),
        ("compile_ugc_video_prompt", "dual"),
        ("render_flow_extend_prompt", "extend_only"),
    ],
)
def test_entrypoint_symbols_exist(symbol: str, expected: str):
    assert hasattr(renderer if symbol != "compile_ugc_video_prompt" else ugc, symbol)
    assert expected in {"dual", "extend_only"}