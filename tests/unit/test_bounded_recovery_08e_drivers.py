"""Mission-08E bounded recovery drivers — guarantees that must hold without a database.

These tests pin the SAFETY SURFACE of the two 08E drivers, not their happy path. Each one
protects a property that, if it silently regressed, would let a bounded recovery mutate more
than it was authorized to:

  * the cohort hash must actually bind the authorized IDs *and* the authority values;
  * the excluded REVIEW_REQUIRED product must be structurally unreachable;
  * `category` must never be writable by the L1 driver;
  * fill-empty-only must be a refusal, not a silent skip.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _load(module_name: str, relative: str):
    spec = importlib.util.spec_from_file_location(module_name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


fingerprint_driver = _load(
    "_08e_fingerprint_driver", "scripts/strategy_fingerprint_reconciliation_08e.py")
l1_driver = _load(
    "_08e_l1_driver", "scripts/product_l1_identity_bounded_08e.py")

EXCLUDED_PRODUCT = "8e75f1a8-ba43-444e-8b40-c71d140c76c5"


# ── fingerprint reconciliation driver ────────────────────────────────────────
def test_fingerprint_cohort_hash_matches_declared_constant():
    """The published constant must be the real hash of the authorized cohort."""
    cohort = fingerprint_driver.load_authorized_cohort()
    assert cohort == tuple(sorted(fingerprint_driver.AUTHORIZED_08E_IDS))
    assert (fingerprint_driver.cohort_set_sha256(cohort)
            == fingerprint_driver.COHORT_SHA256)


def test_fingerprint_driver_refuses_a_tampered_cohort():
    tampered = fingerprint_driver.AUTHORIZED_08E_IDS + ("some-other-product-id",)
    with pytest.raises(fingerprint_driver.CohortAuthorizationError, match="COHORT_SHA_MISMATCH"):
        fingerprint_driver.load_authorized_cohort(tampered, fingerprint_driver.COHORT_SHA256)


def test_review_required_product_is_structurally_unreachable():
    """Even with a matching hash, the excluded product must be refused."""
    assert EXCLUDED_PRODUCT in fingerprint_driver.FORBIDDEN_IDS
    assert EXCLUDED_PRODUCT not in fingerprint_driver.AUTHORIZED_08E_IDS

    smuggled = fingerprint_driver.AUTHORIZED_08E_IDS + (EXCLUDED_PRODUCT,)
    with pytest.raises(fingerprint_driver.CohortAuthorizationError):
        fingerprint_driver.load_authorized_cohort(
            smuggled, fingerprint_driver.cohort_set_sha256(smuggled))


def test_fingerprint_driver_rejects_duplicate_ids():
    dupes = fingerprint_driver.AUTHORIZED_08E_IDS + (fingerprint_driver.AUTHORIZED_08E_IDS[0],)
    with pytest.raises(fingerprint_driver.CohortAuthorizationError):
        fingerprint_driver.load_authorized_cohort(
            dupes, fingerprint_driver.cohort_set_sha256(dupes))


# ── L1 identity driver ───────────────────────────────────────────────────────
def test_l1_cohort_hash_binds_ids_and_authority_values():
    """Changing an authority VALUE (not just an ID) must invalidate the hash."""
    assert l1_driver.load_authorized_cohort() == tuple(sorted(l1_driver.AUTHORIZED_L1))

    mutated = {pid: dict(v) for pid, v in l1_driver.AUTHORIZED_L1.items()}
    first = sorted(mutated)[0]
    mutated[first]["type"] = "Something Else Entirely"
    assert (l1_driver.cohort_set_sha256(mutated) != l1_driver.COHORT_SHA256)
    with pytest.raises(l1_driver.CohortAuthorizationError, match="COHORT_SHA_MISMATCH"):
        l1_driver.load_authorized_cohort(mutated, l1_driver.COHORT_SHA256)


def test_category_is_never_writable_by_the_l1_driver():
    """Owner instruction: do not mutate category. Structural, not a matter of care."""
    assert "category" not in l1_driver.WRITABLE_COLUMNS
    assert "category" not in l1_driver.FILL_ONLY_COLUMNS
    # and it is actively guarded as an identity column that must survive the write
    assert "category" in l1_driver.IDENTITY_GUARD_COLUMNS


def test_l1_writable_columns_are_exactly_the_authorized_set():
    assert set(l1_driver.WRITABLE_COLUMNS) == {
        "subcategory", "type",
        "mapping_status", "mapping_missing_fields",
        "prompt_readiness_status", "prompt_missing_fields",
        "updated_at",
    }
    assert set(l1_driver.FILL_ONLY_COLUMNS) == {"subcategory", "type"}


def test_l1_authority_values_are_the_owner_authorized_pairs():
    assert l1_driver.AUTHORIZED_L1 == {
        "013b7710-a55e-4053-9224-e1149f052f57": {
            "subcategory": "Building Supplies",
            "type": "Wallpaper & Wall Trim",
        },
        "ae47b55b-58d4-441e-97d3-0d6c785bb530": {
            "subcategory": "Home Care Supplies",
            "type": "Pest & Weed Control",
        },
    }
    assert EXCLUDED_PRODUCT not in l1_driver.AUTHORIZED_L1


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_detection_drives_fill_empty_only(value):
    assert l1_driver._blank(value) is True


@pytest.mark.parametrize("value", ["Building Supplies", "0", "x"])
def test_non_blank_values_are_protected_from_overwrite(value):
    assert l1_driver._blank(value) is False
