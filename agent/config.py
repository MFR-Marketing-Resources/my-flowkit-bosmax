"""Configuration constants."""
import json
import os
import sys
import tempfile
from pathlib import Path


# ─── .env bootstrap ──────────────────────────────────────────
# Load the repo-root ``.env`` into ``os.environ`` EARLY — before any config
# value is read — so the documented "edit .env and restart" operator workflow
# actually takes effect on a bare ``python -m agent.main``. Rules:
#   * Existing OS environment variables stay authoritative (override=False).
#   * A missing ``.env`` is a silent no-op; startup must never fail here.
#   * python-dotenv is used WHEN AVAILABLE, but is NOT a hard dependency: the
#     agent is sometimes launched by an external supervisor (uv/uvicorn) in an
#     interpreter that has fastapi/uvicorn but not python-dotenv. In that case a
#     built-in parser loads the same file, so durability never depends on which
#     interpreter runs the agent.
#   * Values are never logged — keeps POSTIZ_API_KEY and other secrets out of logs.
def _parse_env_file(path, override=False):
    """Dependency-free .env loader (KEY=VALUE, ``#`` comments, optional
    ``export`` prefix, single/double quotes). OS env stays authoritative unless
    ``override``. Never logs values. Returns True if any key was set."""
    loaded = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if override or key not in os.environ:
            os.environ[key] = val
            loaded = True
    return loaded


def _load_env_file(env_path=None, override=False):
    """Load a dotenv file into ``os.environ`` without leaking values.

    Returns True only when a file was actually loaded. ``override`` is False by
    default so pre-existing OS env vars win over the file. Prefers python-dotenv
    when importable, else falls back to a built-in parser so the load works in
    any interpreter (a missing python-dotenv must NOT silently skip .env).
    """
    path = Path(env_path) if env_path is not None else (Path(__file__).parent.parent / ".env")
    try:
        if not path.is_file():
            return False
    except Exception:
        return False
    try:
        from dotenv import load_dotenv
        return bool(load_dotenv(dotenv_path=str(path), override=override))
    except Exception:
        # python-dotenv absent (or errored) — use the built-in parser.
        try:
            return _parse_env_file(path, override=override)
        except Exception:
            return False


# Auto-load at import time, except under pytest (keep the suite hermetic — the
# env-loading tests exercise ``_load_env_file`` explicitly with temp files).
if not (
    "pytest" in sys.modules
    or "PYTEST_CURRENT_TEST" in os.environ
    or "PYTEST_VERSION" in os.environ
):
    _load_env_file()

# ─── Paths ───────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("FLOW_AGENT_DIR", Path(__file__).parent.parent))


def _running_under_pytest() -> bool:
    return (
        "PYTEST_CURRENT_TEST" in os.environ
        or "PYTEST_VERSION" in os.environ
        or "pytest" in sys.modules
    )


if _running_under_pytest():
    DB_PATH = Path(tempfile.gettempdir()) / f"flowkit-pytest-{os.getpid()}.db"
else:
    DB_PATH = BASE_DIR / "flow_agent.db"
OPERATOR_PACK_DIR = Path(
    os.environ.get(
        "FLOW_OPERATOR_PACK_DIR",
        Path.home() / "Desktop" / "The Real Avengers Bosmax - Copy",
    )
)

# ─── API Server ──────────────────────────────────────────────
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8100"))

# ─── WebSocket Server (extension connects here) ─────────────
WS_HOST = os.environ.get("WS_HOST", "127.0.0.1")
WS_PORT = int(os.environ.get("WS_PORT", "8101"))

# ─── Google Flow API ────────────────────────────────────────
GOOGLE_FLOW_API = "https://aisandbox-pa.googleapis.com"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY")
RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY", "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV")

# ─── Worker ──────────────────────────────────────────────────
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
VIDEO_POLL_INTERVAL = int(os.environ.get("VIDEO_POLL_INTERVAL", "10"))  # polling interval for video/upscale status
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))
VIDEO_POLL_TIMEOUT = int(os.environ.get("VIDEO_POLL_TIMEOUT", "420"))
API_COOLDOWN = int(os.environ.get("API_COOLDOWN", "10"))  # seconds between API calls (anti-spam)
MAX_CONCURRENT_REQUESTS = int(os.environ.get("MAX_CONCURRENT_REQUESTS", "5"))  # Google Flow max parallel requests
STALE_PROCESSING_TIMEOUT = int(os.environ.get("STALE_PROCESSING_TIMEOUT", "600"))  # 10 min

# ─── Model Keys (loaded from models.json for easy updates) ──
_MODELS_FILE = Path(__file__).parent / "models.json"
with open(_MODELS_FILE) as _f:
    _MODELS = json.load(_f)

VIDEO_MODELS = _MODELS["video_models"]
UPSCALE_MODELS = _MODELS["upscale_models"]
IMAGE_MODELS = _MODELS["image_models"]

# Native Flow Extend model key, per captured aspect ratio (live evidence
# 2026-07-11: portrait -> veo_3_1_extension_lite). FAILS CLOSED for any aspect
# ratio without captured evidence — the Extend builder NEVER silently downgrades
# to an independent-block model (USER SETTINGS ARE LAW). Landscape is included
# because the extension model key is aspect-independent, but any other/unknown
# ratio resolves to None and hard-errors upstream.
EXTEND_VIDEO_MODELS = _MODELS.get("extend_video_models", {
    "VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_extension_lite",
    "VIDEO_ASPECT_RATIO_LANDSCAPE": "veo_3_1_extension_lite",
})

# ─── API Endpoints ───────────────────────────────────────────
ENDPOINTS = {
    "generate_images": "/v1/projects/{project_id}/flowMedia:batchGenerateImages",
    "generate_video": "/v1/video:batchAsyncGenerateVideoStartImage",
    "generate_video_start_end": "/v1/video:batchAsyncGenerateVideoStartAndEndImage",
    "generate_video_references": "/v1/video:batchAsyncGenerateVideoReferenceImages",
    "upscale_video": "/v1/video:batchAsyncGenerateVideoUpsampleVideo",
    # Native Google Flow Extend (continuation of a prior clip). Captured live
    # 2026-07-11 (see .ai/experiments/aisandbox_extend_discovery). Direct aisandbox
    # RPC over the same authenticated extension relay — NOT the flowCreationAgent lane.
    "generate_video_extend": "/v1/video:batchAsyncGenerateVideoExtendVideo",
    "upscale_image": "/v1/flow/upsampleImage",
    "upload_image": "/v1/flow/uploadImage",
    "check_video_status": "/v1/video:batchCheckAsyncVideoGenerationStatus",
    "get_credits": "/v1/credits",
    "get_media": "/v1/media/{media_id}",
    # flowCreationAgent — current Omni/V2 conversational video path (captured live 2026-06-29)
    "create_agent_session": "/v1/flowCreationAgent/sessions",
    "agent_stream_chat": "/v1/flowCreationAgent:streamChat?alt=sse",
}

# ─── Output Directories ─────────────────────────────────────
OUTPUT_DIR = BASE_DIR / "output"
SHARED_OUTPUT_DIR = OUTPUT_DIR / "_shared"
TTS_TEMPLATES_DIR = SHARED_OUTPUT_DIR / "tts_templates"
MUSIC_OUTPUT_DIR = SHARED_OUTPUT_DIR / "music"
PRODUCT_REGISTRATION_DRAFTS_DIR = BASE_DIR / "data" / "product_registration" / "drafts"

# ─── TTS (OmniVoice) ─────────────────────────────────────────
TTS_MODEL = os.environ.get("TTS_MODEL", "k2-fsa/OmniVoice")
TTS_DEVICE = os.environ.get("TTS_DEVICE", "cpu")  # MPS produces gibberish; CPU+fp32 works
TTS_SAMPLE_RATE = int(os.environ.get("TTS_SAMPLE_RATE", "24000"))

# ─── Review / Claude Vision ──────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "claude-haiku-4-5-20251001")
REVIEW_FPS_LIGHT = float(os.environ.get("REVIEW_FPS_LIGHT", "4"))
REVIEW_FPS_DEEP = float(os.environ.get("REVIEW_FPS_DEEP", "8"))
REVIEW_MAX_FRAMES = int(os.environ.get("REVIEW_MAX_FRAMES", "64"))

# ─── Suno (Music Generation) — sunoapi.org ──────────────────
def _load_suno_key() -> str:
    """Load Suno API key: env var first, then channel_rules.json fallback."""
    key = os.environ.get("SUNO_API_KEY", "")
    if key:
        return key
    channels_dir = BASE_DIR / "youtube" / "channels"
    if channels_dir.exists():
        for rules_file in channels_dir.glob("*/channel_rules.json"):
            try:
                rules = json.loads(rules_file.read_text())
                key = rules.get("api_keys", {}).get("suno", "")
                if key:
                    return key
            except (json.JSONDecodeError, OSError):
                continue
    return ""

SUNO_API_KEY = _load_suno_key()
SUNO_BASE_URL = os.environ.get("SUNO_BASE_URL", "https://api.sunoapi.org")
SUNO_MODEL = os.environ.get("SUNO_MODEL", "V4")
SUNO_CALLBACK_URL = os.environ.get("SUNO_CALLBACK_URL", f"http://{API_HOST}:{API_PORT}/api/music/callback")
SUNO_POLL_INTERVAL = int(os.environ.get("SUNO_POLL_INTERVAL", "5"))
SUNO_POLL_TIMEOUT = int(os.environ.get("SUNO_POLL_TIMEOUT", "600"))

# ─── Header Randomization Pools ─────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
]

CHROME_VERSIONS = [
    '"Google Chrome";v="109", "Chromium";v="109"',
    '"Google Chrome";v="110", "Chromium";v="110"',
    '"Google Chrome";v="111", "Chromium";v="111"',
    '"Google Chrome";v="113", "Not-A.Brand";v="24"',
    '"Google Chrome";v="120", "Not-A.Brand";v="24"',
    '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
]

BROWSER_VALIDATIONS = [
    "SgDQo8mvrGRdD61Pwo8wyWVgYgs=",
]

CLIENT_DATA = [
    "CKi1yQEIh7bJAQiktskBCKmdygEIvorLAQiUocsBCIagzQEYv6nKARjRp88BGKqwzwE=",
]
