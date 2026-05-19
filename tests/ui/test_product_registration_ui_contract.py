import re
from pathlib import Path

def test_product_registration_ui_files_exist():
    root = Path(__file__).parent.parent.parent
    files = [
        "dashboard/src/pages/ProductRegistrationPage.tsx",
        "dashboard/src/components/product-registration/ProductKnowledgeIntakeForm.tsx",
        "dashboard/src/components/product-registration/ProductKnowledgeResultPanel.tsx",
    ]
    for f in files:
        assert (root / f).exists(), f"Missing UI file: {f}"

def test_product_registration_route_registered():
    root = Path(__file__).parent.parent.parent
    app_tsx = (root / "dashboard/src/App.tsx").read_text(encoding="utf-8")
    
    # Check NavLink entry in NAV_GROUPS
    assert 'to: "/product-registration"' in app_tsx
    assert 'label: "Smart Registration"' in app_tsx
    
    # Check Route entry
    assert 'path="/product-registration"' in app_tsx
    assert "element={<ProductRegistrationPage />}" in app_tsx

def test_product_knowledge_intake_form_contract():
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/ProductKnowledgeIntakeForm.tsx").read_text(encoding="utf-8")
    
    assert "postAPI" in content
    assert "/api/product-knowledge/complete" in content
    assert "product_name" in content
    assert "product_knowledge_text" in content
    assert "Image URL" in content
    assert "Upload Product Image" in content
    assert "Product URL / Source URL" in content
    assert "TikTok Shop Product / Shop URL" in content
    assert "Commission Amount" in content
    assert "Commission Rate" in content
    assert "Currency" in content
    assert "Package Notes" in content
    assert "Media, Source & Commercial Evidence" in content
    assert "FASTMOSS_REFERENCE" in content
    assert "TIKTOKSHOP_DRAFT" in content
    assert "Run Smart Completion" in content

def test_product_knowledge_result_panel_contract():
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/ProductKnowledgeResultPanel.tsx").read_text(encoding="utf-8")
    
    assert "suggested_bosmax_product_family" in content
    assert "claim_gate" in content
    assert "readiness_by_mode" in content
    assert "suggested_usp_list" in content
    assert "Image Analysis Status" in content
    assert "Image Provider" in content
    assert "Extraction Status" in content


def test_ai_form_pack_contract():
    root = Path(__file__).parent.parent.parent
    file_path = "dashboard/src/components/product-registration/AIFormPack.tsx"
    assert (root / file_path).exists(), f"Missing UI file: {file_path}"
    
    content = (root / file_path).read_text(encoding="utf-8")
    assert "Download Form Template" in content
    assert "Copy AI Coaching Prompt" in content
    assert "Parse & Run Smart Completion" in content
    assert "/api/product-knowledge/import-ai-form" in content
    assert "AIFormImportResponse" in content
    assert 'accept=".md,.markdown,.json,.JSON,.txt"' in content
    assert "Accepted formats:" in content
    assert "Error Code:" in content
    assert "Parser Strategy" in content
    assert "Create Review Draft" in Path(root / "dashboard/src/pages/ProductRegistrationPage.tsx").read_text(encoding="utf-8")
    service_content = (root / "agent/services/product_knowledge_service.py").read_text(encoding="utf-8")
    assert '"image_url": "UNKNOWN"' in service_content
    assert '"tiktok_shop_url": "UNKNOWN"' in service_content
    assert "commission amount" in service_content.lower()

def test_product_registration_review_draft_ui_contract():
    root = Path(__file__).parent.parent.parent
    path = root / "dashboard/src/pages/ProductRegistrationPage.tsx"
    content = path.read_text(encoding="utf-8")

    # Verify Review Queue integration
    assert "Registration Review Queue" in content
    assert "Create Review Draft" in content
    assert "RegistrationReviewDraftPanel" in content
    assert "review-draft-section" in content
    assert "Smart Product Registration" in content


# ---------------------------------------------------------------------------
# Hotfix: bulk FastMoss Convert entrypoint discoverability
# ---------------------------------------------------------------------------

def test_product_registration_page_has_both_tabs():
    """Both tab buttons must be present in ProductRegistrationPage."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/pages/ProductRegistrationPage.tsx").read_text(encoding="utf-8")
    assert "Single Product" in content, "Single Product tab button missing"
    assert "Bulk FastMoss Convert" in content, "Bulk FastMoss Convert tab button missing"
    assert "BulkFastMossConvertTab" in content, "BulkFastMossConvertTab import/render missing"
    assert "activeTab" in content, "activeTab state missing"


def test_product_registration_page_url_deep_link_support():
    """?tab=bulk query param must initialise activeTab and be written on tab switch."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/pages/ProductRegistrationPage.tsx").read_text(encoding="utf-8")
    assert "useSearchParams" in content, "useSearchParams import missing — ?tab=bulk not supported"
    assert "tab=bulk" in content, "tab=bulk param not referenced in page"
    assert "setSearchParams" in content, "URL is not updated on tab switch"


def test_product_registration_page_single_product_default():
    """Single Product tab must remain the default when no query param is set."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/pages/ProductRegistrationPage.tsx").read_text(encoding="utf-8")
    # The initialiser must fall back to 'single' when param is absent
    assert "'single'" in content, "Default 'single' tab missing"
    # Single Product UI components must still be present
    assert "AIFormPack" in content
    assert "ProductKnowledgeIntakeForm" in content
    assert "RegistrationReviewDraftPanel" in content


def test_products_page_fastmoss_warning_has_bulk_cta():
    """FastMoss reference-only warning in ProductsSalesAnalyzerPage must include a CTA."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/pages/ProductsSalesAnalyzerPage.tsx").read_text(encoding="utf-8")
    assert "Open Bulk FastMoss Convert" in content, "CTA label missing from FastMoss warning"
    assert "tab=bulk" in content, "CTA link must target ?tab=bulk"
    assert "product-registration?tab=bulk" in content, "CTA must link to /product-registration?tab=bulk"


def test_workspace_product_select_fastmoss_warning_has_bulk_cta():
    """Reference-only banner in SearchableProductSelect must include a CTA."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/workspace/SearchableProductSelect.tsx").read_text(encoding="utf-8")
    assert "Open Bulk FastMoss Convert" in content, "CTA label missing from workspace reference-only banner"
    assert "product-registration?tab=bulk" in content, "CTA must target /product-registration?tab=bulk"


def test_bulk_fastmoss_convert_tab_component_exists_with_operator_actions():
    """BulkFastMossConvertTab must expose all required operator actions."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/BulkFastMossConvertTab.tsx").read_text(encoding="utf-8")
    assert "Sync Queue" in content, "Sync Queue action missing"
    assert "Generate Drafts" in content, "Generate Drafts action missing"
    assert "Approve Ready" in content, "Approve Ready action missing"
    assert "Reject" in content, "Reject action missing"
    assert "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH" in content, "Confirmation phrase gate missing"
