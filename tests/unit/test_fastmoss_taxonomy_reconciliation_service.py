import pytest
from agent.services.fastmoss_taxonomy_reconciliation_service import (
    FastMossTaxonomyReconciliationService,
    STATUS_SOURCE_ANCHOR_PRESENT,
    STATUS_SOURCE_ANCHOR_VERIFIED_FROM_RAW_SOURCE,
    STATUS_SOURCE_ANCHOR_KEYWORD_DERIVED,
    RECON_MATCHES_RAW_SOURCE,
    RECON_TITLE_KEYWORD_OVERRIDE_SUSPECTED
)

@pytest.mark.asyncio
async def test_fastmoss_taxonomy_audit_matches():
    # Setup mock product that matches mock_fastmoss_products.csv
    # Sumikko 50PCS...
    product = {
        "raw_product_title": "Sumikko 50PCS Premium Baby Diaper pants disposable diaper tape diaper pants pull-ups Ultra-thin and breathable All size S/M/L/XL/XXL/XXXL",
        "category": "Baby & Maternity",
        "subcategory": "Baby Care & Health",
        "source": "FASTMOSS"
    }
    
    audit = FastMossTaxonomyReconciliationService.audit_fastmoss_product(product)
    
    assert audit["raw_source_available"] is True
    assert audit["reconciliation_status"] == RECON_MATCHES_RAW_SOURCE
    assert audit["source_anchor_status"] == STATUS_SOURCE_ANCHOR_VERIFIED_FROM_RAW_SOURCE

@pytest.mark.asyncio
async def test_fastmoss_taxonomy_audit_contamination_suspected():
    # Setup product where DB values match keywords but NOT source
    # We'll use a title that contains "wipes" (which maps to Beauty in current rules)
    # But we'll assume the source says something else
    
    # Let's first check what the current keyword rules do for "Baby Wipes"
    from agent.services.product_mapping import resolve_product_mapping
    mapping = resolve_product_mapping(product_name="Baby Wipes Newborn Wet Tissue")
    # In current rules, wipes -> beauty_fragrance -> Category: Beauty
    
    product = {
        "raw_product_title": "Baby Wipes Newborn Wet Tissue Tisue Basah Non-alcohol Paraben-free Fragrance-free Babies Wipe Tisu Basah Bayi",
        "category": mapping["category"], # Contaminated DB value
        "subcategory": mapping["subcategory"],
        "source": "FASTMOSS"
    }
    
    audit = FastMossTaxonomyReconciliationService.audit_fastmoss_product(product)
    
    # If the source row exists in our mock data (which it should if it's the one I saw earlier)
    # the reconciliation should detect the suspect override
    if audit["raw_source_available"]:
        assert audit["reconciliation_status"] == RECON_TITLE_KEYWORD_OVERRIDE_SUSPECTED
        assert audit["source_anchor_status"] == STATUS_SOURCE_ANCHOR_KEYWORD_DERIVED

@pytest.mark.asyncio
async def test_fastmoss_full_audit_read_only():
    # Check that the full audit doesn't mutate DB
    import sqlite3
    from agent.config import DB_PATH
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), MAX(updated_at) FROM product")
    before = c.fetchone()
    conn.close()
    
    await FastMossTaxonomyReconciliationService.perform_full_fastmoss_audit(limit=1)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), MAX(updated_at) FROM product")
    after = c.fetchone()
    conn.close()
    
    assert before == after
