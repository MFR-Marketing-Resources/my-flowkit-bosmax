"""Poster copy quality guard — expert e-commerce rules (POSTER_EXPERT_SYSTEM_REDESIGN_V1)."""

from agent.models.poster_copy_quality import PosterCopyQualityRequest
from agent.services.poster_copy_quality_service import (
    evaluate_poster_copy,
    map_legacy_to_poster,
)


def _codes(report, severity=None):
    return {
        f.code for f in report.findings if severity is None or f.severity == severity
    }


def _good(**over) -> PosterCopyQualityRequest:
    base = dict(
        archetype="PRODUCT_HERO",
        language="ms",
        max_chips=2,
        poster_headline="Minyak warisan pilihan keluarga",
        poster_support_line="Formula tradisional yang dipercayai.",
        poster_chips=["Formula warisan", "Mudah dibawa"],
        poster_cta="Dapatkan sekarang",
    )
    base.update(over)
    return PosterCopyQualityRequest(**base)


def test_clean_expert_copy_passes():
    r = evaluate_poster_copy(_good())
    assert r.ok is True
    assert r.block_count == 0


def test_headline_too_long_flags():
    warn = evaluate_poster_copy(_good(poster_headline="Satu dua tiga empat lima enam tujuh lapan"))
    assert "HEADLINE_TOO_LONG" in _codes(warn)
    block = evaluate_poster_copy(
        _good(poster_headline="Satu dua tiga empat lima enam tujuh lapan sembilan sepuluh sebelas")
    )
    assert "HEADLINE_TOO_LONG" in _codes(block, "BLOCK")
    assert block.ok is False


def test_missing_headline_and_cta_block():
    r = evaluate_poster_copy(_good(poster_headline="", poster_cta=""))
    assert {"HEADLINE_MISSING", "CTA_MISSING"} <= _codes(r, "BLOCK")
    assert r.ok is False


def test_too_many_chips_blocks_per_archetype():
    r = evaluate_poster_copy(_good(max_chips=2, poster_chips=["A satu", "B dua", "C tiga"]))
    assert "TOO_MANY_CHIPS" in _codes(r, "BLOCK")


def test_chip_too_long_warns():
    r = evaluate_poster_copy(_good(poster_chips=["Ini satu chip yang terlalu panjang sekali", "Ok"]))
    assert "CHIP_TOO_LONG" in _codes(r, "WARN")


def test_cta_too_long():
    assert "CTA_TOO_LONG" in _codes(
        evaluate_poster_copy(_good(poster_cta="Dapatkan sebotol sekarang juga hari")), "WARN"
    )
    assert "CTA_TOO_LONG" in _codes(
        evaluate_poster_copy(_good(poster_cta="Dapatkan sebotol sekarang juga hari ini terus segera")),
        "BLOCK",
    )


def test_support_line_paragraph_warns():
    r = evaluate_poster_copy(
        _good(poster_support_line="Ini ayat pertama. Ini ayat kedua yang panjang lagi.")
    )
    assert "SUPPORT_TOO_LONG" in _codes(r, "WARN")


def test_medical_relief_copy_blocks():
    for bad in ("perut kembung", "legakan kembung", "sakit", "cure", "relief", "rawat"):
        r = evaluate_poster_copy(_good(poster_headline=f"Produk {bad} keluarga"))
        assert "MEDICAL_RELIEF_CLAIM" in _codes(r, "BLOCK"), bad
        assert r.ok is False


def test_child_health_copy_double_blocks():
    r = evaluate_poster_copy(
        _good(poster_headline="Anak menangis", poster_support_line="legakan kembung anak")
    )
    assert "MEDICAL_RELIEF_CLAIM" in _codes(r, "BLOCK")
    assert "CHILD_HEALTH_CLAIM" in _codes(r, "BLOCK")


def test_video_script_style_warns():
    r = evaluate_poster_copy(
        _good(
            poster_headline="Anak menangis malam? Mungkin sebab sesuatu",
            poster_support_line="Jangan biarkan masalah ini berlarutan esoknya.",
        )
    )
    # video-script markers present (mungkin / jangan biar / berlarutan) -> WARN
    assert "VIDEO_SCRIPT_STYLE" in _codes(r, "WARN")


def test_too_many_ideas_warns():
    r = evaluate_poster_copy(
        _good(
            poster_headline="Warisan tradisional keluarga",
            poster_chips=["Saiz kecil mudah", "Promo harga jimat"],
        )
    )
    assert "TOO_MANY_IDEAS" in _codes(r, "WARN")


def test_forbidden_default_screenshot_copy_is_blocked():
    # The exact weak/video-style copy from the reported screenshot must not pass.
    r = evaluate_poster_copy(
        _good(
            poster_headline="Anak menangis malam? Mungkin perut kembung.",
            poster_support_line="Anak tak selesa, tidur terganggu. Jangan biar masalah ini berlarutan.",
            poster_chips=["Sapu sedikit, legakan kembung.", "Saiz 25ml mudah dibawa"],
        )
    )
    assert r.ok is False
    assert "MEDICAL_RELIEF_CLAIM" in _codes(r, "BLOCK")
    assert "VIDEO_SCRIPT_STYLE" in _codes(r, "WARN")


def test_map_legacy_to_poster():
    mapped = map_legacy_to_poster(
        {"hook": "H", "subhook": "S", "usp_1": "A", "usp_2": "B", "usp_3": "", "cta": "C"}
    )
    assert mapped["poster_headline"] == "H"
    assert mapped["poster_support_line"] == "S"
    assert mapped["poster_chips"] == ["A", "B"]
    assert mapped["poster_cta"] == "C"
