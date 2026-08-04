"""Sell price + Comm amt queue columns — rate normalization must be truthful for
BOTH stored forms (FastMoss percent strings, Kalodata decimals), and commission
amount must equal sell price x normalized rate.
"""
from __future__ import annotations

from agent.services.fastmoss_bulk_promotion_service import (
    _normalize_commission_rate,
    _queue_commission_amount,
    _resolve_ref_sell_price,
)


def test_normalize_rate_fastmoss_percent_string():
    assert _normalize_commission_rate("5%") == 0.05
    assert _normalize_commission_rate("14%") == 0.14


def test_normalize_rate_kalodata_decimal_string():
    # Kalodata stores the rate ALREADY as a fraction — must NOT divide again.
    assert _normalize_commission_rate("0.05") == 0.05
    assert _normalize_commission_rate("0.11") == 0.11


def test_normalize_rate_bare_number_is_percent():
    assert _normalize_commission_rate("5") == 0.05
    assert _normalize_commission_rate("10") == 0.10


def test_normalize_rate_missing_or_dash():
    assert _normalize_commission_rate("-") is None
    assert _normalize_commission_rate("") is None
    assert _normalize_commission_rate(None) is None
    assert _normalize_commission_rate("n/a") is None


def test_commission_amount_both_sources_agree():
    # 100 x 5% == 100 x 0.05 == 100 x "5" == 5.00
    assert _queue_commission_amount(100.0, "5%") == 5.0
    assert _queue_commission_amount(100.0, "0.05") == 5.0
    assert _queue_commission_amount(100.0, "5") == 5.0
    assert _queue_commission_amount(20.0, "10%") == 2.0


def test_commission_amount_none_when_unusable():
    assert _queue_commission_amount(26.5, "-") is None
    assert _queue_commission_amount(None, "5%") is None
    assert _queue_commission_amount(26.5, None) is None


def test_resolve_sell_price():
    assert _resolve_ref_sell_price({"price": 26.5}) == 26.5
    assert _resolve_ref_sell_price({"price": "39.54"}) == 39.54
    assert _resolve_ref_sell_price({"price": None}) is None
    assert _resolve_ref_sell_price({}) is None
