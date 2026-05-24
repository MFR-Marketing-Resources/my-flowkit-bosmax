import pytest

from agent.services.video_reviewer import (
    VISION_PROVIDER_EXECUTION_DISABLED_ERROR,
    review_scene_video,
)


@pytest.mark.asyncio
async def test_review_scene_video_fails_closed_when_vision_lane_disabled(monkeypatch):
    monkeypatch.setattr(
        "agent.services.video_reviewer.get_lane_provider",
        lambda lane: "anthropic",
    )
    monkeypatch.setattr(
        "agent.services.video_reviewer.is_lane_execution_enabled",
        lambda lane: False,
    )

    with pytest.raises(RuntimeError, match=VISION_PROVIDER_EXECUTION_DISABLED_ERROR):
        await review_scene_video(
            {
                "id": "scene-001",
                "vertical_video_url": "https://example.com/video.mp4",
            },
            [],
            orientation="VERTICAL",
        )
