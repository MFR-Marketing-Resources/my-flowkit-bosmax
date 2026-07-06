"""Unit tests for copy_similarity_service — zero-provider near-duplicate detection."""
import pytest

from agent.services.copy_similarity_service import (
    combined_similarity,
    compute_uniqueness_score,
    find_nearest,
    is_near_duplicate,
    jaccard,
    levenshtein_ratio,
    token_set,
)


# ── token_set ──────────────────────────────────────────────

def test_token_set_simple():
    assert token_set("hello world") == {"hello", "world"}


def test_token_set_casefold_and_punctuation():
    result = token_set("Hello, World! HELLO")
    assert result == {"hello", "world"}  # deduped, casefolded, no punct


def test_token_set_empty():
    assert token_set("") == set()


# ── jaccard ────────────────────────────────────────────────

def test_jaccard_identical():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_no_overlap():
    assert jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_partial():
    # {a,b,c} ∩ {b,c,d} = 2, union = 4
    assert jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(0.5)


def test_jaccard_both_empty():
    assert jaccard(set(), set()) == 1.0


# ── levenshtein_ratio ──────────────────────────────────────

def test_levenshtein_identical():
    assert levenshtein_ratio("hello", "hello") == 1.0


def test_levenshtein_completely_different():
    # "a" vs "bbbb" — 1 insertion + 3 substitutions or similar
    ratio = levenshtein_ratio("a", "bbbb")
    assert ratio < 0.5


def test_levenshtein_both_empty():
    assert levenshtein_ratio("", "") == 1.0


def test_levenshtein_one_empty():
    assert levenshtein_ratio("hello", "") == 0.0


def test_levenshtein_similar():
    # "sabun dobi isi ulang" vs "sabun dobi isi ulang best"
    ratio = levenshtein_ratio(
        "sabun dobi isi ulang",
        "sabun dobi isi ulang best",
    )
    assert ratio > 0.7


# ── combined_similarity ────────────────────────────────────

def test_combined_similarity_identical():
    fields = {"angle": "Value", "hook": "Hook text", "subhook": "Sub", "usp_set": ["U1", "U2"], "cta": "Buy now"}
    assert combined_similarity(fields, fields) == pytest.approx(1.0)


def test_combined_similarity_different():
    a = {"angle": "Beauty", "hook": "Kulit glowing?", "subhook": "", "usp_set": ["Cepat"], "cta": "Beli sekarang"}
    b = {"angle": "Laundry", "hook": "Baju wangi?", "subhook": "", "usp_set": ["Tahan lama"], "cta": "Checkout"}
    score = combined_similarity(a, b)
    assert score < 0.5


# ── is_near_duplicate ──────────────────────────────────────

def test_is_near_duplicate_true():
    a = {"angle": "Beauty", "hook": "Kulit cerah?", "subhook": "", "usp_set": ["Vitamin C"], "cta": "Beli"}
    b = {"angle": "Beauty", "hook": "Kulit cerah?", "subhook": "", "usp_set": ["Vitamin C"], "cta": "Beli sekarang"}
    is_dup, score = is_near_duplicate(a, b, threshold=0.80)
    assert is_dup is True
    assert score >= 0.80


def test_is_near_duplicate_false():
    a = {"angle": "Beauty", "hook": "Kulit glowing?", "usp_set": ["Cepat"], "cta": "Beli"}
    b = {"angle": "Laundry", "hook": "Baju wangi?", "usp_set": ["Tahan"], "cta": "Checkout"}
    is_dup, score = is_near_duplicate(a, b, threshold=0.80)
    assert is_dup is False


# ── find_nearest ───────────────────────────────────────────

def test_find_nearest_finds_match():
    candidate = {"angle": "Beauty", "hook": "Kulit cerah?", "usp_set": ["Vitamin C"], "cta": "Beli"}
    existing = [
        {"angle": "Laundry", "hook": "Baju wangi?", "usp_set": ["Tahan"], "cta": "Checkout"},
        {"angle": "Beauty", "hook": "Kulit cerah?", "usp_set": ["Vitamin C"], "cta": "Beli sekarang"},
    ]
    nearest, score = find_nearest(candidate, existing, threshold=0.80)
    assert nearest is not None
    assert score >= 0.80


def test_find_nearest_no_match():
    candidate = {"angle": "Beauty", "hook": "Kulit glowing?", "usp_set": ["Cepat"], "cta": "Beli"}
    existing = [
        {"angle": "Laundry", "hook": "Baju wangi?", "usp_set": ["Tahan"], "cta": "Checkout"},
    ]
    nearest, score = find_nearest(candidate, existing, threshold=0.80)
    assert nearest is None
    assert score < 0.80


def test_find_nearest_empty_list():
    nearest, score = find_nearest({"hook": "test"}, [])
    assert nearest is None
    assert score == 0.0


# ── compute_uniqueness_score ───────────────────────────────

def test_uniqueness_no_existing():
    score = compute_uniqueness_score({"hook": "unique"}, [])
    assert score == 1.0


def test_uniqueness_very_similar():
    candidate = {"hook": "Kulit cerah?", "usp_set": ["Vit C"], "cta": "Beli"}
    existing = [{"hook": "Kulit cerah?", "usp_set": ["Vit C"], "cta": "Beli sekarang"}]
    score = compute_uniqueness_score(candidate, existing)
    assert score < 0.3  # high similarity → low uniqueness


def test_uniqueness_different():
    candidate = {"hook": "Kulit glowing?", "usp_set": ["Cepat"], "cta": "Beli"}
    existing = [{"hook": "Baju wangi?", "usp_set": ["Tahan"], "cta": "Checkout"}]
    score = compute_uniqueness_score(candidate, existing)
    assert score > 0.5  # different → higher uniqueness
