"""IMG Asset Factory v1 — ProductAssetGenerator preset consistency (fix H).

There is no frontend test runner in this repo, so this Python guard parses the
TypeScript preset source and enforces the invariant that motivated fix H:

  A ``requiredInputs`` entry that names a MANDATORY reference asset (a character
  reference or a scene reference/context *image*, not marked "(optional)") must
  agree with the matching ``requires*Reference`` flag, and vice versa.

Text-context inputs ("Scene context (text)", "Style context (text)") and
"(optional)" entries must NOT force a reference flag.
"""

import re
from pathlib import Path

PRESETS_PATH = (
    Path(__file__).resolve().parents[2]
    / "dashboard"
    / "src"
    / "components"
    / "product-asset-generator"
    / "presets.ts"
)

_TRIO = re.compile(
    r"requiredInputs:\s*(\[[^\]]*\])"
    r".*?requiresCharacterReference:\s*(true|false)"
    r".*?requiresSceneContextReference:\s*(true|false)",
    re.DOTALL,
)


def _entries(required_inputs_literal: str) -> list[str]:
    return re.findall(r'"([^"]*)"', required_inputs_literal)


def _mandates_character(entries: list[str]) -> bool:
    return any(
        "character reference" in e.lower() and "optional" not in e.lower()
        for e in entries
    )


def _mandates_scene_asset(entries: list[str]) -> bool:
    return any(
        (("scene reference" in e.lower()) or ("scene context image" in e.lower()))
        and "optional" not in e.lower()
        for e in entries
    )


def test_presets_file_exists():
    assert PRESETS_PATH.exists(), PRESETS_PATH


def test_every_preset_flag_agrees_with_required_inputs():
    text = PRESETS_PATH.read_text(encoding="utf-8")
    matches = _TRIO.findall(text)
    # One trio per preset — must equal the number of requiredInputs ARRAY blocks
    # ("requiredInputs: ["), which excludes the `requiredInputs: string[]` type decl.
    assert len(matches) == text.count("requiredInputs: [")
    assert len(matches) >= 14

    for required_inputs_literal, char_flag, scene_flag in matches:
        entries = _entries(required_inputs_literal)
        char_mandatory = _mandates_character(entries)
        scene_mandatory = _mandates_scene_asset(entries)

        if char_flag == "false":
            assert not char_mandatory, (
                f"requiresCharacterReference:false but requiredInputs mandates a "
                f"character reference: {entries}"
            )
        else:  # true
            assert char_mandatory, (
                f"requiresCharacterReference:true but requiredInputs never names a "
                f"character reference: {entries}"
            )

        if scene_flag == "false":
            assert not scene_mandatory, (
                f"requiresSceneContextReference:false but requiredInputs mandates a "
                f"scene reference asset: {entries}"
            )
        else:  # true
            assert scene_mandatory, (
                f"requiresSceneContextReference:true but requiredInputs never names a "
                f"scene reference asset: {entries}"
            )


def test_no_generated_avatar_preset_lists_bare_character_reference():
    """The exact regression: a generated-avatar preset must not imply a mandatory
    upload by listing the bare "Character reference" token."""
    text = PRESETS_PATH.read_text(encoding="utf-8")
    # The bare token (no "image") only ever belonged to generated-avatar presets
    # whose flag is false; those must now be relabeled away.
    assert '"Character reference"' not in text
    assert '"Scene reference"' not in text
