"""Shared rendered-output BEHAVIORAL acceptance for product-video surfaces.

An MP4 existing is NOT success. This one shared seam inspects the RENDERED media
and returns a per-property PASS / FAIL / UNPROVEN verdict against the behavioral
contract of the producing surface — HYBRID (presenter-led), FACELESS
(human-presence, no face), and PRODUCT_MASCOT_MONTAGE (product mascot).

Design law (owner Round 3):
- Never silently PASS. A property is PASS only when the rendered media proves it.
- Properties this environment can cheaply falsify (ffprobe/ffmpeg/PIL): a
  truly-frozen clip fails NON_STATIC_SCENE; a clip with no audio stream fails
  SPOKEN_DIALOGUE_PRESENT.
- Properties that need vision (presenter/hands/mascot visible, no face/head,
  interaction, lip-sync, content-static) or trustworthy ASR (spoken dialogue vs
  BGM-only) are UNPROVEN unless an external prover is injected. UNPROVEN never
  becomes PASS; the surface routes to behavioral review.

Provider-free. Degrades safely: if ffmpeg/ffprobe are unavailable, media probes
return UNPROVEN rather than a false PASS.
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageChops, ImageStat

PROP_PASS = "PASS"
PROP_FAIL = "FAIL"
PROP_UNPROVEN = "UNPROVEN"

ACCEPT_PASS = "BEHAVIORAL_ACCEPTANCE_PASS"
ACCEPT_FAIL = "BEHAVIORAL_ACCEPTANCE_FAIL"
ACCEPT_REVIEW = "BEHAVIORAL_REVIEW_REQUIRED"

ACCEPTANCE_VERSION = "RENDERED_OUTPUT_ACCEPTANCE_V1"

# Owner Round 3 lane property sets (exact).
HYBRID_PROPERTIES = (
    "PRESENTER_VISIBLE", "PRESENTER_PRODUCT_INTERACTION", "SPOKEN_DIALOGUE_PRESENT",
    "LIPSYNC_PRESENT", "PRODUCT_FIDELITY", "NON_STATIC_SCENE", "BGM_ONLY_FALSE",
)
FACELESS_PROPERTIES = (
    "HUMAN_PRESENCE", "HAND_PRODUCT_INTERACTION", "NO_FACE_HEAD", "SPOKEN_DIALOGUE_PRESENT",
    "PRODUCT_FIDELITY", "NON_STATIC_SCENE", "BGM_ONLY_FALSE",
)
MONTAGE_PROPERTIES = (
    "MASCOT_VISIBLE", "MASCOT_IDENTITY_CONTINUITY", "MASCOT_ACTIVE_ACTION",
    "SPOKEN_DIALOGUE_PRESENT", "LIPSYNC_PRESENT", "PRODUCT_FIDELITY", "NON_STATIC_SCENE",
    "BGM_ONLY_FALSE",
)

_SURFACE_PROPERTIES = {
    "HYBRID": HYBRID_PROPERTIES,
    "FACELESS": FACELESS_PROPERTIES,
    "MONTAGE": MONTAGE_PROPERTIES,
    "PRODUCT_MASCOT_MONTAGE": MONTAGE_PROPERTIES,
}

# Frame-content (vision) properties — UNPROVEN without an injected vision prover.
# NON_STATIC_SCENE is vision-resolvable (a vision prover can confirm meaningful
# scene change), but a truly-frozen clip is a cheap proven FAIL that overrides.
_VISION_PROPERTIES = frozenset({
    "PRESENTER_VISIBLE", "PRESENTER_PRODUCT_INTERACTION", "LIPSYNC_PRESENT",
    "HUMAN_PRESENCE", "HAND_PRODUCT_INTERACTION", "NO_FACE_HEAD",
    "MASCOT_VISIBLE", "MASCOT_IDENTITY_CONTINUITY", "MASCOT_ACTIVE_ACTION",
    "NON_STATIC_SCENE",
})
# Speech/ASR properties — UNPROVEN without an injected speech prover (beyond the
# cheap "no audio stream at all" falsification).
_ASR_PROPERTIES = frozenset({"SPOKEN_DIALOGUE_PRESENT", "BGM_ONLY_FALSE"})


class RenderedOutputProbeError(RuntimeError):
    pass


def normalize_surface(surface: str | None) -> str:
    s = str(surface or "").strip().upper()
    if s in {"PRODUCT_MASCOT_MONTAGE"}:
        return "MONTAGE"
    return s


def surface_properties(surface: str) -> tuple[str, ...]:
    props = _SURFACE_PROPERTIES.get(normalize_surface(surface))
    if props is None:
        raise RenderedOutputProbeError(f"Unknown behavioral surface: {surface}")
    return props


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _run(cmd: list[str], timeout: int = 90) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def probe_media(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    out: dict[str, Any] = {
        "path": str(p), "exists": p.is_file() and p.stat().st_size > 0, "probed": False,
        "duration_s": None, "width": None, "height": None, "aspect_ratio": None,
        "has_video": False, "has_audio": False, "video_codec": None, "audio_codec": None,
    }
    ffprobe = _tool("ffprobe")
    if not out["exists"] or not ffprobe:
        return out
    code, stdout, _ = _run([
        ffprobe, "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height",
        "-show_entries", "format=duration", "-of", "json", str(p),
    ])
    if code != 0:
        return out
    try:
        data = json.loads(stdout)
    except ValueError:
        return out
    out["probed"] = True
    try:
        out["duration_s"] = round(float((data.get("format") or {}).get("duration")), 3)
    except (TypeError, ValueError):
        pass
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video" and not out["has_video"]:
            out.update(has_video=True, video_codec=stream.get("codec_name"),
                       width=stream.get("width"), height=stream.get("height"))
        elif stream.get("codec_type") == "audio" and not out["has_audio"]:
            out.update(has_audio=True, audio_codec=stream.get("codec_name"))
    if out["width"] and out["height"] and int(out["height"]) > 0:
        r = int(out["width"]) / int(out["height"])
        out["aspect_ratio"] = "9:16" if abs(r - 9 / 16) < 0.02 else (
            "16:9" if abs(r - 16 / 9) < 0.02 else f"{out['width']}x{out['height']}")
    return out


def analyze_motion(path: str | Path, *, fps: float = 2.0, work_dir: Path | None = None) -> dict[str, Any]:
    """Sample frames; falsify only a truly frozen clip. A product-only push-in has
    motion, so this can NOT prove content-static — that stays a vision concern."""
    import tempfile
    p = Path(path)
    out: dict[str, Any] = {"probed": False, "frame_count": 0, "max_diff": None,
                           "mean_diff": None, "truly_frozen": None, "frame_paths": []}
    ffmpeg = _tool("ffmpeg")
    if not (p.is_file() and ffmpeg):
        return out
    tmp = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="roa_frames_"))
    tmp.mkdir(parents=True, exist_ok=True)
    code, _, _ = _run([ffmpeg, "-v", "error", "-y", "-i", str(p),
                       "-vf", f"fps={fps},scale=200:-1", str(tmp / "f_%04d.png")], timeout=150)
    frames = sorted(tmp.glob("f_*.png"))
    if code != 0 or not frames:
        return out
    diffs: list[float] = []
    prev = None
    for f in frames:
        with Image.open(f) as im:
            g = im.convert("L").copy()
        if prev is not None:
            diffs.append(ImageStat.Stat(ImageChops.difference(g, prev)).mean[0])
        prev = g
    out.update(probed=True, frame_count=len(frames), frame_paths=[str(f) for f in frames])
    if diffs:
        out.update(max_diff=round(max(diffs), 2), mean_diff=round(sum(diffs) / len(diffs), 2),
                   truly_frozen=bool(max(diffs) < 1.5))
    return out


def analyze_audio(path: str | Path, *, work_dir: Path | None = None) -> dict[str, Any]:
    """Extract mono audio; prove only PRESENCE (a coarse speech/music heuristic is
    reported but never authoritative — dialogue-vs-BGM needs ASR)."""
    import tempfile
    p = Path(path)
    out: dict[str, Any] = {"probed": False, "audio_present": None, "speech_proven": False,
                           "speech_heuristic": None}
    ffmpeg = _tool("ffmpeg")
    if not (p.is_file() and ffmpeg):
        return out
    tmp = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="roa_audio_"))
    tmp.mkdir(parents=True, exist_ok=True)
    wav = tmp / "audio.wav"
    code, _, _ = _run([ffmpeg, "-v", "error", "-y", "-i", str(p), "-ac", "1", "-ar", "16000", str(wav)], timeout=120)
    if code != 0 or not wav.is_file():
        return out
    with wave.open(str(wav), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if not raw:
        return {**out, "probed": True, "audio_present": False}
    samples = struct.unpack("<%dh" % (len(raw) // 2), raw)
    win = max(1, int(sr * 0.5))
    rms = [(sum(x * x for x in samples[i:i + win]) / win) ** 0.5 for i in range(0, len(samples) - win, win)]
    out["probed"] = True
    peak = max(rms) if rms else 0.0
    out["audio_present"] = bool(peak > 50)
    if rms and peak > 0:
        mean = sum(rms) / len(rms)
        var = sum((x - mean) ** 2 for x in rms) / len(rms)
        cv = (var ** 0.5) / mean if mean else 0.0
        out["speech_heuristic"] = "VARIABLE_MAYBE_SPEECH" if cv > 0.35 else "STEADY_MUSIC_LIKE"
    return out


@dataclass
class SurfaceAcceptance:
    surface: str
    status: str
    properties: dict[str, str]
    unproven: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"surface": self.surface, "status": self.status, "properties": self.properties,
                "unproven": self.unproven, "failed": self.failed, "evidence": self.evidence,
                "acceptance_version": ACCEPTANCE_VERSION}


def evaluate_surface_acceptance(
    surface: str,
    media_path: str | Path,
    *,
    product_fidelity_status: str | None = None,
    vision_prover: Callable[[str, list[str]], dict[str, str]] | None = None,
    speech_prover: Callable[[str], dict[str, Any]] | None = None,
    work_dir: Path | None = None,
) -> SurfaceAcceptance:
    """Per-property behavioral verdict for one rendered clip.

    ``vision_prover(media_path, property_names) -> {PROP: PASS|FAIL|UNPROVEN}`` and
    ``speech_prover(media_path) -> {'dialogue_present': bool|None, 'bgm_only': bool|None}``
    are optional injected provers (Round 4 supplies them). Absent, the vision/ASR
    properties stay UNPROVEN and the surface routes to review — never a silent pass.
    """
    surface_n = normalize_surface(surface)
    props = surface_properties(surface_n)
    probe = probe_media(media_path)
    motion = analyze_motion(media_path, work_dir=work_dir)
    audio = analyze_audio(media_path, work_dir=work_dir)
    verdict: dict[str, str] = {}

    # PRODUCT_FIDELITY — inherited from the product-fidelity QC seam (defaults review).
    if "PRODUCT_FIDELITY" in props:
        pf = str(product_fidelity_status or "").upper()
        verdict["PRODUCT_FIDELITY"] = (
            PROP_PASS if pf in {"PRODUCT_FIDELITY_QC_PASS", "PASS"}
            else PROP_FAIL if pf in {"PRODUCT_FIDELITY_QC_FAIL", "FAIL"} else PROP_UNPROVEN)

    # Speech / BGM — optional ASR prover; else only "no audio stream" is a proven FAIL.
    speech = speech_prover(str(media_path)) if speech_prover else None
    for prop in ("SPOKEN_DIALOGUE_PRESENT", "BGM_ONLY_FALSE"):
        if prop not in props:
            continue
        if speech is not None:
            if prop == "SPOKEN_DIALOGUE_PRESENT":
                v = speech.get("dialogue_present")
                verdict[prop] = PROP_PASS if v is True else (PROP_FAIL if v is False else PROP_UNPROVEN)
            else:  # BGM_ONLY_FALSE
                v = speech.get("bgm_only")
                verdict[prop] = PROP_FAIL if v is True else (PROP_PASS if v is False else PROP_UNPROVEN)
        else:
            if prop == "SPOKEN_DIALOGUE_PRESENT" and audio.get("audio_present") is False:
                verdict[prop] = PROP_FAIL  # no audio stream at all -> no spoken dialogue
            else:
                verdict[prop] = PROP_UNPROVEN

    # Vision properties — optional vision prover; else UNPROVEN.
    vision_targets = [p for p in props if p in _VISION_PROPERTIES]
    vision_result = (
        vision_prover(str(media_path), list(vision_targets)) if (vision_prover and vision_targets) else {}
    )
    for prop in vision_targets:
        verdict[prop] = str(vision_result.get(prop, PROP_UNPROVEN)).upper()
    # Cheap falsification overrides vision: a truly frozen clip fails NON_STATIC_SCENE
    # regardless of any prover.
    if "NON_STATIC_SCENE" in props and motion.get("truly_frozen") is True:
        verdict["NON_STATIC_SCENE"] = PROP_FAIL

    for prop in props:
        verdict.setdefault(prop, PROP_UNPROVEN)

    failed = [p for p in props if verdict[p] == PROP_FAIL]
    unproven = [p for p in props if verdict[p] == PROP_UNPROVEN]
    status = ACCEPT_FAIL if failed else (ACCEPT_REVIEW if unproven else ACCEPT_PASS)
    return SurfaceAcceptance(
        surface=surface_n, status=status, properties=verdict, unproven=unproven, failed=failed,
        evidence={"probe": probe, "motion": {k: motion.get(k) for k in ("frame_count", "max_diff", "mean_diff", "truly_frozen")},
                  "audio": audio, "vision_prover": bool(vision_prover), "speech_prover": bool(speech_prover)},
    )


def acceptance_gate_status(acceptance: SurfaceAcceptance | dict[str, Any] | None) -> str:
    """Map a behavioral acceptance to a job status contribution. FAIL and REVIEW are
    both non-success; only a full PASS is behaviorally accepted."""
    status = acceptance.status if isinstance(acceptance, SurfaceAcceptance) else str((acceptance or {}).get("status") or "")
    if status == ACCEPT_PASS:
        return ACCEPT_PASS
    if status == ACCEPT_FAIL:
        return ACCEPT_FAIL
    return ACCEPT_REVIEW
