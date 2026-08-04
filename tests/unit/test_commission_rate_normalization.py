"""Commission rate normalization — the shared derivation must be truthful for
BOTH stored forms: FastMoss percent strings ('5%') and Kalodata decimals
('0.05'). Regression for `derive_commission_amount` dividing an already-decimal
Kalodata rate by 100 again (commission amounts came out ~100x too small).
"""
from __future__ import annotations

from decimal import Decimal

from agent.services.product_intelligence import (
    derive_commission_amount,
    normalize_commission_rate,
)


def test_normalize_handles_percent_decimal_and_bare_forms():
    assert normalize_commission_rate("5%") == Decimal("0.05")      # FastMoss percent
    assert normalize_commission_rate("0.05") == Decimal("0.05")    # Kalodata decimal
    assert normalize_commission_rate("5") == Decimal("0.05")       # bare number = percent
    assert normalize_commission_rate("14%") == Decimal("0.14")
    assert normalize_commission_rate("100%") == Decimal("1")


def test_normalize_missing_or_bad():
    assert normalize_commission_rate("-") is None
    assert normalize_commission_rate("") is None
    assert normalize_commission_rate(None) is None
    assert normalize_commission_rate("n/a") is None


def test_derive_amount_agrees_across_forms():
    # 100 x 5% == 100 x 0.05 == 100 x "5" == 5.00
    assert derive_commission_amount(100, "5%") == 5.0
    assert derive_commission_amount(100, "0.05") == 5.0
    assert derive_commission_amount(100, "5") == 5.0


def test_derive_amount_kalodata_decimal_regression():
    # the exact bug: 26.5 x "0.05" must be ~1.33, NOT ~0.01
    amt = derive_commission_amount(26.5, "0.05")
    assert amt == 1.33
    assert amt > 1.0


def test_derive_amount_none_when_underivable():
    assert derive_commission_amount(None, "5%") is None
    assert derive_commission_amount(26.5, "-") is None
    assert derive_commission_amount(26.5, None) is None
