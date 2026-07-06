"""Live DB verification for PR #231 target product IDs (optional, local only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.models.poster_readiness import PosterReadinessStatus
from agent.services.poster_readiness_service import PosterReadinessService

TARGETS = {
    "bosmax_oil": "b460ffbd-7d9d-4f6b-a570-0e9b1056439a",
    "bosmax_herbs": "90349f8c-9e14-4efe-988e-76ec60ea31f4",
    "minyak_warisan": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
}

_DB_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "flow_agent.db",
    Path(__file__).resolve().parents[2] / "data" / "flow_agent.db",
)


def _resolve_db_path() -> Path | None:
    for path in _DB_CANDIDATES:
        if path.is_file():
            return path
    return None


@pytest.fixture(scope="module")
def live_db_available() -> Path | None:
    return _resolve_db_path()


@pytest.mark.asyncio
@pytest.mark.parametrize("label,product_id", list(TARGETS.items()))
async def test_live_target_poster_readiness(label, product_id, live_db_available, monkeypatch):
    if live_db_available is None:
        pytest.skip("flow_agent.db not available in workspace — live target verification skipped")

    import agent.config as config
    import agent.db.schema as schema

    monkeypatch.setattr(config, "DB_PATH", live_db_available)
    monkeypatch.setattr(schema, "DB_PATH", live_db_available)
    schema._db_connection = None

    result = await PosterReadinessService.evaluate_product_id(product_id)
    assert result is not None, f"{label}: product row missing in DB"

    if label in {"bosmax_oil", "bosmax_herbs"}:
        assert result.poster_status == PosterReadinessStatus.POSTER_REPAIR_REQUIRED
        assert "CLAIM_RISK_HIGH" in result.blockers
        assert result.generation_allowed is False
        assert result.production_allowed is False
    elif label == "minyak_warisan":
        assert result.poster_status in {
            PosterReadinessStatus.POSTER_READY,
            PosterReadinessStatus.POSTER_REPAIR_REQUIRED,
            PosterReadinessStatus.POSTER_PREVIEW_ONLY,
        }
        if result.poster_status == PosterReadinessStatus.POSTER_READY:
            assert result.generation_allowed is True