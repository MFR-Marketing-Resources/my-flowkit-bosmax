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
    assert "Run Smart Completion" in content

def test_product_knowledge_result_panel_contract():
    root = Path(__file__).parent.parent.parent
    content = (root / "dashboard/src/components/product-registration/ProductKnowledgeResultPanel.tsx").read_text(encoding="utf-8")
    
    assert "suggested_bosmax_product_family" in content
    assert "claim_gate" in content
    assert "readiness_by_mode" in content
    assert "suggested_usp_list" in content
