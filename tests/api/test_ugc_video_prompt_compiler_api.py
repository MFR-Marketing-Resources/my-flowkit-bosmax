from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_prompt_compiler_config_api_returns_central_policy(monkeypatch):
    client = TestClient(_build_app())
    response = client.get("/api/workspace/prompt-compiler-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generation_modes"] == ["SINGLE", "EXTEND"]
    assert payload["allowed_block_durations_seconds"] == [6, 8, 10, 12, 15, 20, 25]


def test_ugc_video_prompt_compile_api_returns_compiled_payload(monkeypatch):
    async def fake_compile(**kwargs):
        return {
            "final_compiled_prompt_text": "Block 1 (ANCHOR)\nUse one visible creator persona.",
            "prompt_blocks": [
                {
                    "block_id": "block_1",
                    "block_index": 1,
                    "block_role": "ANCHOR",
                    "duration_seconds": 8,
                    "shot_count": 2,
                    "dialogue_word_budget": 13,
                    "continuation_from_block_id": None,
                    "compiled_prompt_text": "Block 1",
                    "shot_plan": ["Shot 1", "Shot 2"],
                }
            ],
            "compiler_version": "ugc_video_prompt_compiler_v1",
            "generation_mode": "SINGLE",
            "total_duration_seconds": 8,
            "camera_style": "UGC_IPHONE_RAW",
            "character_presence": "VISIBLE_CREATOR",
            "creator_persona": "DEFAULT_CREATOR",
            "target_language": "BM_MS",
            "shot_plan": [{"block_index": 1, "shot_count": 2, "shots": ["Shot 1", "Shot 2"]}],
            "dialogue_word_budget_per_block": [13],
            "prompt_fingerprint": "compiled_fp_001",
            "warnings": [],
            "blockers": [],
            "source_of_truth_notes": ["Compiler note"],
            "continuation_lineage": [],
            "runtime_config_snapshot": {"defaults": {"block_duration_seconds": 8}},
            "product_id": "prod-001",
            "mode": "F2V",
        }

    monkeypatch.setattr("agent.api.workspace_packages.compile_workspace_prompt_preview", fake_compile)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/ugc-video-prompt-compile",
        json={"product_id": "prod-001", "mode": "F2V"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["compiler_version"] == "ugc_video_prompt_compiler_v1"
    assert payload["generation_mode"] == "SINGLE"
    assert payload["prompt_blocks"][0]["shot_count"] == 2
