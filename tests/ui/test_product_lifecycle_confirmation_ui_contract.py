import re
from pathlib import Path

def test_product_lifecycle_confirmation_ux_contract():
    root = Path(__file__).parent.parent.parent
    path = root / "dashboard/src/pages/ProductsSalesAnalyzerPage.tsx"
    content = path.read_text(encoding="utf-8")
    
    # 1. Archive modal must display exact required phrase
    assert "Confirmation Phrase" in content
    assert "Type the exact phrase above to unlock submit." in content
    
    # 2. Copy Phrase button
    assert "Copy Phrase" in content
    assert "navigator.clipboard.writeText(lifecycleExpectedPhrase(lifecycleModal.action))" in content
    
    # 3. Use Required Phrase button
    assert "Use Expected Phrase" in content
    assert "lifecycleModal.confirmationPhrase: lifecycleExpectedPhrase(current.action)" in content or "confirmationPhrase: lifecycleExpectedPhrase(current.action)" in content
    
    # 4 & 5. Inline validation and disabled submit logic
    assert "exactly to continue" in content
    assert "errorMessage" in content
    
    # 6 & 7. Backend error handling
    assert "Archive confirmation phrase did not match" in content
    assert "ARCHIVE_CONFIRMATION_REQUIRED" in content
    assert "CONFIRMATION_REQUIRED" in content
    
    # 9. Same UX contract for archive, unarchive, delete test row only
    assert "UNARCHIVE_PRODUCT" in content
    assert "DELETE_TEST_ROW_ONLY" in content
    assert "ARCHIVE_PRODUCT" in content

def test_fastmoss_lifecycle_contract():
    root = Path(__file__).parent.parent.parent
    path = root / "dashboard/src/pages/ProductsSalesAnalyzerPage.tsx"
    content = path.read_text(encoding="utf-8")
    
    # 11. FASTMOSS hard delete/purge forbidden
    # The logic must prevent deleting FASTMOSS test rows, leaving no path to hard delete it
    assert "product.source !== 'FASTMOSS'" in content
