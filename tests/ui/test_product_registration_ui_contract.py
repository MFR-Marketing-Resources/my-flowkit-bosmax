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
    assert "Product URL" in content
    assert "Source URL" in content
    assert "TikTok Product URL" in content
    assert "TikTok Shop URL" in content
    assert "Commission Amount" in content
    assert "Commission Rate" in content
    assert "Currency" in content
    assert "Package Notes" in content
    assert "Media, Source & Commercial Evidence" in content
    assert "FASTMOSS_REFERENCE" in content
    assert "TIKTOKSHOP_DRAFT" in content
    assert "Run Smart Completion" in content


def test_product_knowledge_intake_form_keeps_evidence_fields_separate():
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/ProductKnowledgeIntakeForm.tsx").read_text(encoding="utf-8")

    assert "value={formData.product_url || ''}" in content
    assert "onChange={e => setFormData({ ...formData, product_url: e.target.value })}" in content
    assert "value={formData.source_url || ''}" in content
    assert "onChange={e => setFormData({ ...formData, source_url: e.target.value })}" in content
    assert "value={formData.tiktok_product_url || ''}" in content
    assert "onChange={e => setFormData({ ...formData, tiktok_product_url: e.target.value })}" in content
    assert "value={formData.tiktok_shop_url || ''}" in content
    assert "onChange={e => setFormData({ ...formData, tiktok_shop_url: e.target.value })}" in content
    assert "value={formData.product_url || formData.source_url || ''}" not in content
    assert "value={formData.tiktok_product_url || formData.tiktok_shop_url || ''}" not in content
    assert "product_url: e.target.value, source_url: e.target.value" not in content
    assert "tiktok_product_url: e.target.value, tiktok_shop_url: e.target.value" not in content

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
    assert '"single"' in content, 'Default "single" tab missing'
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


def test_products_page_has_persistent_bulk_convert_cta():
    """ProductsSalesAnalyzerPage must have a persistent top-level Bulk Convert FastMoss button."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/pages/ProductsSalesAnalyzerPage.tsx").read_text(encoding="utf-8")
    assert "Bulk Convert FastMoss" in content, "Persistent 'Bulk Convert FastMoss' button missing from Products page"
    assert "product-registration?tab=bulk" in content, "Persistent CTA must link to /product-registration?tab=bulk"


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
    assert "Recompute Selected" in content, "Recompute Selected action missing"
    assert "Approve Ready" in content, "Approve Ready action missing"
    assert "Reject" in content, "Reject action missing"
    assert "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH" in content, "Confirmation phrase gate missing"
    assert "Select FastMoss rows to enable bulk actions" in content, "Bulk action disabled helper text missing"


def test_bulk_fastmoss_recompute_modal_contract_and_summary_labels():
    """Recompute modal must stay no-approval only and expose summary counters."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/BulkFastMossConvertTab.tsx").read_text(encoding="utf-8")
    assert "Recompute Selected Rows" in content, "Recompute modal title missing"
    assert "It will not approve products." in content, "Recompute modal must explicitly deny approval"
    assert "RECOMPUTE_ONLY_NO_APPROVAL" in content, "Recompute confirmation phrase missing"
    assert "recomputed" in content, "Recompute summary label missing"
    assert "ready_for_approval" in content, "ready_for_approval summary label missing"
    assert "missing_required_field" in content, "missing_required_field summary label missing"
    assert "claim_risk" in content, "claim_risk summary label missing"
    assert "duplicate_suspected" in content, "duplicate_suspected summary label missing"
    assert "image_missing" in content, "image_missing summary label missing"
    assert "failed" in content, "failed summary label missing"
    assert "skipped" in content, "skipped summary label missing"


def test_bulk_fastmoss_recompute_button_enablement_contract():
    """Recompute button must depend on selected eligible statuses only."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/BulkFastMossConvertTab.tsx").read_text(encoding="utf-8")
    assert "RECOMPUTE_ELIGIBLE_STATUSES" in content, "Eligible recompute status list missing"
    assert "MISSING_REQUIRED_FIELD" in content, "MISSING_REQUIRED_FIELD must remain recomputable"
    assert "PENDING_DRAFT" in content, "PENDING_DRAFT must remain recomputable"
    assert "recomputeEligibleSelectedCount === 0" in content, "Eligible-count disable gate missing"
    assert "selected.size === 0" in content, "Selection-size disable gate missing"


def test_bulk_fastmoss_approve_phrase_remains_unchanged():
    """Approval phrase must remain separate from recompute phrase."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/BulkFastMossConvertTab.tsx").read_text(encoding="utf-8")
    assert "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH" in content, "Approval phrase must not change"
    assert "RECOMPUTE_ONLY_NO_APPROVAL" in content, "Recompute phrase must coexist with approval phrase"


def test_bulk_fastmoss_duplicate_review_lane_contract():
    """Duplicate review lane must expose modal actions, phrase gate, and linked badge."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/BulkFastMossConvertTab.tsx").read_text(encoding="utf-8")
    assert "Review Duplicate" in content, "Duplicate review action missing"
    assert "FastMoss Row" in content, "Duplicate modal left-side comparison missing"
    assert "Existing Product Candidate" in content, "Duplicate modal right-side comparison missing"
    assert "LINK_TO_EXISTING_PRODUCT" in content, "Link action missing"
    assert "MARK_FALSE_DUPLICATE" in content, "False duplicate action missing"
    assert "KEEP_BLOCKED" in content, "Keep blocked action missing"
    assert "REJECT_REFERENCE" in content, "Reject reference action missing"
    assert "CLEAR_DUPLICATE_FOR_REVIEW" in content, "False duplicate confirmation phrase missing"
    assert "LINKED TO PRODUCT TRUTH" in content, "Linked badge missing"
    assert "Use linked Product Truth for content generation" in content, "Linked content-generation policy hint missing"


def test_bulk_fastmoss_duplicate_review_link_requires_product_contract():
    """Duplicate review modal must enforce linked product id before link confirmation."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/BulkFastMossConvertTab.tsx").read_text(encoding="utf-8")
    assert "bulk-fastmoss-linked-product-id" in content, "Linked product id field missing"
    assert 'duplicateAction === "LINK_TO_EXISTING_PRODUCT"' in content, "Link action gate missing"
    assert "duplicateLinkProductId.trim().length === 0" in content, "Linked product id required disable gate missing"


def test_bulk_fastmoss_detail_drawer_and_row_actions_contract():
    """BulkFastMoss rows must support detail review and safe row-level actions."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/BulkFastMossConvertTab.tsx").read_text(encoding="utf-8")
    assert "Product Detail" in content, "Row detail drawer heading missing"
    assert "Click to review details" in content, "Row detail affordance missing"
    assert "Source Links" in content, "Drawer source links section missing"
    assert "Open Draft Editor" in content, "Drawer draft editor shortcut missing"
    assert "handleRecomputeRow" in content, "Single-row recompute helper missing"
    assert "handleSingleApprove" in content, "Single-row approve helper missing"
    assert "Review Duplicate" in content, "Duplicate drawer action missing"
    assert "Reject" in content, "Drawer reject action missing"
    assert "force-approve-claim-risk" not in content, "Claim-risk override route must not be introduced in safe salvage lane"
    assert "Import Enriched" not in content, "Unsafe import lane must not be introduced without proof"
    assert "Export Missing" not in content, "Unsafe export lane must not be introduced without proof"


def test_product_registration_page_has_open_bulk_fastmoss_header_cta():
    """ProductRegistrationPage must have a prominent 'Open Bulk FastMoss Convert' button in header."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/pages/ProductRegistrationPage.tsx").read_text(encoding="utf-8")
    assert "Open Bulk FastMoss Convert" in content, "'Open Bulk FastMoss Convert' header CTA missing"
    assert "Bulk FastMoss Convert" in content, "Tab label missing"
    assert "Sync Queue" not in content, "Sync Queue is on child component, not this page"


def test_product_registration_page_draft_pagination_compacts_long_page_ranges():
    """Draft review pagination must use a compact ellipsis strategy."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/pages/ProductRegistrationPage.tsx").read_text(encoding="utf-8")
    assert "flex-wrap" in content, "Draft pagination container should wrap on narrow layouts"
    assert 'pages: (number | string)[] = []' in content, "Compact pagination pages buffer missing"
    assert 'pages.push(`e${pg}`)' in content, "Ellipsis sentinel generation missing"
    assert 'typeof pg === "string"' in content, "Ellipsis render branch missing"


def test_smart_registration_single_product_flow_still_intact():
    """Single Product intake flow must not be removed by bulk hotfix."""
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/pages/ProductRegistrationPage.tsx").read_text(encoding="utf-8")
    assert "AIFormPack" in content
    assert "ProductKnowledgeIntakeForm" in content
    assert "RegistrationReviewDraftPanel" in content
    assert '"single"' in content
