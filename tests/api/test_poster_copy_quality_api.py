from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_prompt import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_quality_endpoint_flags_bad_copy():
    r = _client().post(
        "/api/poster/copy/quality",
        json={
            "archetype": "PRODUCT_HERO",
            "max_chips": 2,
            "poster_headline": "Anak menangis malam? Mungkin perut kembung.",
            "poster_support_line": "Tidur terganggu, jangan biar berlarutan.",
            "poster_chips": ["legakan kembung", "b", "c"],
            "poster_cta": "Dapatkan",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    codes = {f["code"] for f in body["findings"]}
    assert "MEDICAL_RELIEF_CLAIM" in codes
    assert "TOO_MANY_CHIPS" in codes


def test_quality_endpoint_passes_clean_copy():
    r = _client().post(
        "/api/poster/copy/quality",
        json={
            "archetype": "PRODUCT_HERO",
            "max_chips": 2,
            "poster_headline": "Minyak warisan keluarga",
            "poster_support_line": "Formula tradisional dipercayai.",
            "poster_chips": ["Formula warisan", "Mudah dibawa"],
            "poster_cta": "Dapatkan sekarang",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
