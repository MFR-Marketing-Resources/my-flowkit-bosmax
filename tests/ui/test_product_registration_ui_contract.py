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
