"""IMG Cockpit UI contract (PR #2).

Deterministic text-parse (no browser/server) asserting the dedicated operator
cockpit page exists, is routed, exposes every required control, and honestly
gates + labels the credit-spending live-generation path.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_cockpit_route_nav_and_import_registered():
    app = _read("dashboard/src/App.tsx")
    assert 'import ImgCockpitPage from "./pages/ImgCockpitPage"' in app
    assert '/assets/img-cockpit' in app
    assert '<ImgCockpitPage />' in app
    assert 'IMG Cockpit' in app  # nav label


def test_cockpit_exposes_all_workflow_controls():
    page = _read("dashboard/src/pages/ImgCockpitPage.tsx")
    for token in [
        # 1 lane selector, 2 product picker, 3 avatar, 4 scene/style, 5 preview
        "Select IMG lane",
        "SearchableProductSelect",
        "CHARACTER_REFERENCE",
        "Avatar Registry",
        "SCENE_CONTEXT_REFERENCE",
        "STYLE_REFERENCE",
        "Compile suggested prompt",
        "compileWorkspacePromptPreview",
        # 7 register output, 8 review, 9 save
        "Register a real output",
        "Finished artifact",
        "Upload file",
        "PENDING_REVIEW",
        "APPROVED",
        "REJECTED",
        "Save to Creative Library",
        "saveImgOutputToLibrary",
        # 10 reuse visibility
        "Ingredients (I2V)",
        "/operator/i2v",
    ]:
        assert token in page, token


def test_cockpit_generate_is_gated_and_honestly_labeled():
    page = _read("dashboard/src/pages/ImgCockpitPage.tsx")
    # Honesty labels must be present verbatim.
    assert "NOT_FIRED_IN_SESSION" in page
    assert "EXTERNAL_RUNTIME_NOT_VERIFIED" in page
    # The generate button opens an explicit confirm; live gen only runs from the
    # confirmed handler — it must never auto-fire.
    assert "setShowGenConfirm(true)" in page
    assert "handleConfirmedGenerate" in page
    assert "Confirm & Generate (live)" in page or "Confirm &amp; Generate (live)" in page
    assert "spends credits" in page
    # The one place that calls the real generation lane is the confirmed handler.
    assert "startImgGeneration" in page


def test_cockpit_approval_requires_all_pass():
    page = _read("dashboard/src/pages/ImgCockpitPage.tsx")
    # Approve requires ALL truth statuses to PASS via canApprove (mirrors the backend
    # APPROVAL_REQUIRES_ALL_TRUTH_PASS gate) — not merely "not UNVERIFIED".
    assert "approvalBlocked" in page
    assert "canApprove" in page
    assert "APPROVAL_REQUIRES_ALL_TRUTH_PASS" in page


def test_cockpit_generate_sends_selected_refs():
    page = _read("dashboard/src/pages/ImgCockpitPage.tsx")
    # Selected references are resolved into image_media_ids and actually sent to
    # generation — not ignored.
    assert "resolveGenerationInputs" in page
    assert "image_media_ids: genResolution.mediaIds" in page
    # Generate is blocked when the lane's required visual truth cannot resolve.
    assert "genResolution.blocked" in page
    assert "Generate payload preview" in page


def test_cockpit_pickers_are_approved_only():
    page = _read("dashboard/src/pages/ImgCockpitPage.tsx")
    # Reuse safety: only APPROVED references feed generation/lineage.
    assert "isReusableAsset" in page
    assert "approvedCharacter" in page
    assert "approvedScene" in page
    assert "approvedStyle" in page


def test_cockpit_rejected_is_archived():
    page = _read("dashboard/src/pages/ImgCockpitPage.tsx")
    # A REJECTED output is archived via the real endpoint so it cannot be reused.
    assert "archiveCreativeAsset(asset.asset_id)" in page
    assert 'reviewDecision === "REJECTED"' in page


def test_img_cockpit_logic_helpers_encode_the_gates():
    logic = _read("dashboard/src/pages/imgCockpitLogic.ts")
    assert "export function canApprove" in logic
    assert "export function resolveGenerationInputs" in logic
    assert "export function isReusableAsset" in logic
    # canApprove requires every status === "PASS".
    assert 'statuses.identity === "PASS"' in logic
    assert 'statuses.scale === "PASS"' in logic
    assert 'statuses.claim === "PASS"' in logic
    # reusable requires APPROVED + ACTIVE.
    assert 'asset.review_status === "APPROVED"' in logic
    assert 'asset.status === "ACTIVE"' in logic
    # resolveGenerationInputs blocks a product-truth lane with no resolvable media.
    assert "lane?.requires_product_id" in logic
    assert "blocked = true" in logic
    assert "mediaId" in logic


def test_img_factory_client_wires_gated_generation():
    api = _read("dashboard/src/api/imgFactory.ts")
    assert "export async function startImgGeneration" in api
    assert "export async function pollImgGenerationJob" in api
    assert "export async function fetchImageArtifacts" in api
    assert "/api/flow/generate" in api
    assert "/api/flow/generate-job/" in api
    assert "/api/flow/artifacts?kind=image" in api
