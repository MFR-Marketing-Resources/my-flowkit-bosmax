"""A manually-registered product must be able to carry the SAME evidence fields as a
FastMoss/Kalodata product (benefits/usage/target/ingredients/warnings/knowledge), with
the source URLs the only optional difference. Regression: ManualProductRequest was a
thin identity/commerce model with no evidence slots, so the manual intake dropped the
operator's product knowledge before it reached intelligence.
"""
from agent.api.products import ManualProductRequest
from agent.services.product_intake_service import evidence_from_product_payload

_EVIDENCE = {
    "benefits_text": "Deep moisturizing, soothes dry skin",
    "usage_text": "Apply twice daily",
    "target_customer_text": "Adults with dry skin",
    "ingredients_text": "Shea butter, vitamin E",
    "warnings_text": "Patch test before use",
    "product_knowledge_text": "A herbal moisturizing cream.",
    "size_or_volume": "60g",
    "package_notes": "Single jar",
}


def test_manual_request_accepts_evidence_fields():
    dump = ManualProductRequest(product_name="Bosmax Herbs Manual", **_EVIDENCE).model_dump()
    for key, val in _EVIDENCE.items():
        assert dump[key] == val
    # URLs remain optional (not required) and default to None
    for url in ("product_url", "source_url", "tiktok_product_url", "tiktok_shop_url", "image_url"):
        assert dump[url] is None


def test_manual_payload_forwards_evidence_to_intake():
    payload = ManualProductRequest(product_name="X", **_EVIDENCE).model_dump()
    dec = evidence_from_product_payload(payload, lane="PRODUCTS_MANUAL").declared_evidence_fields
    for key, val in _EVIDENCE.items():
        assert dec.get(key) == val


def test_manual_evidence_is_lane_agnostic_vs_fastmoss():
    fields = {"benefits_text": "Deep moisturizing", "usage_text": "Apply daily"}
    manual = evidence_from_product_payload(dict(fields), lane="PRODUCTS_MANUAL").declared_evidence_fields
    fastmoss = evidence_from_product_payload(dict(fields), lane="FASTMOSS_PROMOTED").declared_evidence_fields
    assert manual == fastmoss == fields
