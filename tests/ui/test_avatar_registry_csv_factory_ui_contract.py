"""UI source contract for the Avatar Registry CSV Factory staging panel.

The Avatar Registry page must expose the staged intake flow (import candidate
CSV -> validation report -> per-row approve/reject -> export/sync) and must
route candidate CSVs through the csv-factory endpoints, never straight into
the bridge sync.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_csv_factory_panel_present():
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "CSV Factory" in src
    assert "Import Candidate CSV" in src
    # Review controls.
    assert "Approve all valid" in src
    assert "Approve" in src
    assert "Reject" in src
    # Export + sync actions.
    assert "Export approved CSV" in src
    assert "Sync approved" in src


def test_csv_factory_uses_staged_endpoints():
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "/api/workspace/avatar-registry/csv-factory/import" in src
    assert "/api/workspace/avatar-registry/csv-factory/batches" in src
    assert "/review" in src
    assert "/export" in src
    assert "/sync`" in src


def test_csv_factory_sync_requires_confirmation():
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    handler = src.split("const handleFactorySync", 1)[1]
    handler = handler.split("const handleGenerateImage", 1)[0]
    assert "window.confirm" in handler


def test_csv_factory_surfaces_validation_report():
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "Validation:" in src
    assert "PASS_WITH_WARNINGS" in src
    assert "row.errors.join" in src
    # invalid rows can never be approved from the UI
    assert "disabled={isFactoryBusy || !row.valid}" in src


def test_create_avatar_manual_add_wired():
    """The Create Avatar card must expose a manual-add form wired to the
    add-manual endpoint with fail-closed redundancy messaging."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "Create Avatar" in src
    assert "/api/workspace/avatar-registry/add-manual" in src
    assert "handleAddManualAvatar" in src
    # Fail-closed redundancy surface (409 AVATAR_REDUNDANT).
    assert "AVATAR_REDUNDANT" in src
    assert "Avatar serupa sudah wujud" in src


def test_create_avatar_auto_generate_wired():
    """The Create Avatar card must expose an AI auto-generate action wired to
    the auto-generate endpoint with fail-closed 503/409/502 messaging."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "/api/workspace/avatar-registry/auto-generate" in src
    assert "handleAutoGenerateAvatar" in src
    assert "Auto-generate Avatar" in src
    # 503 must point operators to the AI Provider Settings text_assist lane.
    assert "AI Provider Settings" in src
    assert "text_assist" in src
    # Loading state while the LLM call is in flight.
    assert "isAutoGenerating" in src


def test_legacy_direct_sync_is_demoted_and_warned():
    """The legacy /avatar-registry/sync path must be explicitly labelled as
    legacy and warn that it bypasses the CSV Factory, so operators do not
    accidentally skip staging/review."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    # Explicit legacy label instead of a plain primary "Sync CSV" action.
    assert "Legacy Direct Sync" in src
    # Bypass warning is surfaced on the legacy handler.
    handler = src.split("const handleSyncUpload", 1)[1]
    handler = handler.split("const handleGenerateImage", 1)[0]
    assert "window.confirm" in handler
    assert "BYPASSES" in handler or "bypass" in handler.lower()
    # Legacy control still targets the legacy endpoint (not removed).
    assert "/api/workspace/avatar-registry/sync" in src


def test_avatar_registry_coverage_lens_present():
    """Phase A modernization: the page is framed as a live authority pool and
    shows the read-only coverage/usage lens with dependency notes."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "Live Avatar Authority Pool" in src
    assert "getRegistryCoverage" in src
    assert "Product-Fit Coverage" in src
    assert "Coverage Gaps" in src
    # Dependency notes for the modules that resolve against this pool.
    # (JSX line-wraps prose across newlines, so assert on wrap-stable tokens.)
    assert "Avatar Recommendation" in src
    assert "Creative Setup" in src
    assert "prompt compiler" in src
    assert "(R5)" in src


def test_avatar_registry_reconciliation_panel_present():
    """Phase C: read-only reconciliation panel with non-destructive labels."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "getRegistryReconciliation" in src
    assert "Registry Reconciliation" in src
    assert "Mapped" in src
    assert "Referenced" in src
    assert "Review candidates" in src
    # Candidates are never labelled delete-safe.
    assert "safe to delete" not in src.lower()
    assert "delete now" not in src.lower()


def test_avatar_registry_archive_delete_planning_present():
    """Phase D: read-only archive/delete planning panel with dry-run framing."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "getRegistryCleanupPlan" in src
    assert "Archive / Delete Planning" in src
    assert "Read-only dry-run" in src
    assert "No records are changed" in src
    assert "Owner approval required" in src
    assert "FUTURE_ARCHIVE_ELIGIBLE" in src
    assert "REVIEW_CANDIDATE" in src
    assert "safe to delete" not in src.lower()
    assert "delete now" not in src.lower()


def test_create_avatar_uses_controlled_dropdowns():
    """Standardization: Create Avatar wires descriptor fields to controlled
    dropdowns fed by the vocab endpoint, a persona dropdown + New persona, adds
    the previously-missing fields, and ties hijab to gender (M disables hijab)."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    # Vocab endpoint drives the dropdowns.
    assert "/api/workspace/avatar-registry/vocab" in src
    assert "vocab?.skin_tone" in src
    assert "vocab?.wardrobe" in src
    assert "vocab?.expression" in src
    # Persona dropdown + New persona option (no more raw free-text name).
    assert "manualPersonaNew" in src
    assert "New persona" in src
    # Persona list is rendered from the (now gender-filtered) persona source.
    assert "personasForGender" in src
    # Usage tags + constraint fields exist.
    assert "Usage tags" in src
    assert "usage_tags" in src
    # Dependent constraint: gender = M disables hijab (manual + auto forms).
    assert 'manualForm.gender === "M"' in src
    assert 'autoGender === "M"' in src


def test_create_avatar_dropdowns_are_gender_filtered():
    """Gender-aware standardization: the vocab endpoint supplies per-gender
    persona + wardrobe lists, and the form filters dependent dropdowns by the
    selected gender (so Gender=M never exposes female-only personas/wardrobe)."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    # Gender-aware payload is consumed from the vocab endpoint.
    assert "personas_by_gender" in src
    assert "gender_specific_fields" in src
    assert "vocab_by_gender" in src
    # Gender-filter helpers drive the dependent dropdowns.
    assert "personasForGender" in src
    assert 'optionsFor("wardrobe"' in src
    # Persona dropdown + manual wardrobe are filtered by the selected gender.
    assert "personasForGender(manualForm.gender)" in src
    assert 'optionsFor("wardrobe", manualForm.gender)' in src
    # Changing gender drops a now-incompatible wardrobe/persona (not just hijab).
    assert "wardrobeOpts" in src
    assert "personaOk" in src


def test_avatar_registry_phase_e_closeout_note():
    """Phase E closeout: the cleanup panel shows a read-only finalization note —
    Registry Modernization complete, no current archive/delete eligibility (when
    future_archive_eligible_total is 0), and owner approval + zero-reference
    dry-run proof required for any future cleanup. No delete/archive action added."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "Registry Modernization (Phases A" in src
    assert "No records are currently eligible for archive or delete" in src
    assert "zero-reference dry-run proof" in src
    assert "cleanup.future_archive_eligible_total === 0" in src
    assert "safe to delete" not in src.lower()
    assert "delete now" not in src.lower()
