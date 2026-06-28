"""Single-source-of-truth guard for the extension build id.

Locks in the fix for build-id drift: the JS build constants (background, runner,
content) must all be equal, no PowerShell launcher/repair script may hardcode a
*different* build id, and content scripts must be statically injected (so a stale
dynamically-registered script cannot mask the real build).
"""
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
EXT = BASE / "extension"
SCRIPTS = BASE / "scripts"

_JS_CONSTANTS = {
    "content-flow-dom.js": r"FLOW_KIT_DOM_BUILD_ID\s*=\s*['\"]([^'\"]+)['\"]",
    "background.js": r"\bBUILD_ID\s*=\s*['\"]([^'\"]+)['\"]",
    "f2v-flow-queue-runner.js": r"F2V_FLOW_QUEUE_RUNNER_BUILD_ID\s*=\s*['\"]([^'\"]+)['\"]",
}
_BUILD_LITERAL = re.compile(r"flowkit-[a-z0-9-]*\d{4}-\d{2}-\d{2}[a-z0-9-]*")


def _extract(filename: str, pattern: str) -> str:
    text = (EXT / filename).read_text(encoding="utf-8")
    match = re.search(pattern, text)
    assert match, f"build id constant not found in {filename}"
    return match.group(1)


def test_js_build_constants_share_one_ssot():
    ids = {name: _extract(name, pat) for name, pat in _JS_CONSTANTS.items()}
    assert len(set(ids.values())) == 1, f"build id drift across JS files: {ids}"


def test_powershell_scripts_do_not_pin_a_divergent_build_id():
    canonical = _extract("content-flow-dom.js", _JS_CONSTANTS["content-flow-dom.js"])
    offenders = []
    for ps in SCRIPTS.glob("*.ps1"):
        text = ps.read_text(encoding="utf-8", errors="ignore")
        for literal in set(_BUILD_LITERAL.findall(text)):
            if literal != canonical:
                offenders.append((ps.name, literal))
    assert not offenders, f"PowerShell scripts hardcode divergent build ids: {offenders}"


def test_content_scripts_are_statically_injected():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    content_scripts = manifest.get("content_scripts") or []
    assert content_scripts, "content_scripts must be statically declared in manifest"
    assert "content-flow-dom.js" in content_scripts[0]["js"]


def test_no_dynamic_content_script_registration():
    for js in EXT.glob("*.js"):
        text = js.read_text(encoding="utf-8", errors="ignore")
        assert "registerContentScripts" not in text, (
            f"{js.name} dynamically registers content scripts; this reintroduces the "
            "stale-registration class of build-identity bug"
        )
