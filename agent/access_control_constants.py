"""Canonical human-account roles and permissions for Staff & Access V1.

This module is intentionally dependency-free so the database seed, the
server-side route guard, and the admin UI can share one permission vocabulary.
There is no SYSTEM human role; internal service routes are classified by the
route policy instead.
"""

from __future__ import annotations


ROLE_SEEDS: tuple[tuple[str, str, str], ...] = (
    ("OWNER", "Owner", "Full human administration and production authority."),
    ("MANAGER", "Manager", "Operational management without account or provider-secret administration."),
    ("OPERATOR", "Operator", "Production execution and operational control."),
    ("EDITOR", "Editor", "Product, copy, asset, and planning authoring."),
    ("VIEWER", "Viewer", "Read-only access to permitted BOSMAX workspaces."),
)

PERMISSION_SEEDS: tuple[tuple[str, str, str], ...] = (
    ("system.settings.read", "Read system settings", "Read non-secret system configuration and status."),
    ("system.settings.manage", "Manage system settings", "Change system configuration and diagnostic controls."),
    ("staff.read", "Read staff", "View staff profiles and account status."),
    ("staff.manage", "Manage staff", "Create, edit, suspend, reactivate, reset, and terminate staff accounts."),
    ("roles.read", "Read roles", "View roles and their permissions."),
    ("roles.manage", "Manage roles", "Assign roles and change role permission grants."),
    ("sessions.read", "Read sessions", "View active human sessions."),
    ("sessions.revoke", "Revoke sessions", "Revoke one or more human sessions."),
    ("audit.read", "Read access audit", "View access-control audit events."),
    ("products.read", "Read products", "Read product catalog and product truth."),
    ("products.create", "Create products", "Create or import product records."),
    ("products.update", "Update products", "Edit product records and product truth."),
    ("products.archive", "Archive products", "Archive or retire product records through approved flows."),
    ("copy.read", "Read copy", "Read copywriting and prompt authority."),
    ("copy.create", "Create copy", "Create copy drafts and plans."),
    ("copy.update", "Update copy", "Edit copy drafts and plans."),
    ("copy.archive", "Archive copy", "Archive copy through immutable lifecycle endpoints."),
    ("copy.approve", "Approve copy", "Approve copy and authority records."),
    ("assets.read", "Read assets", "Read creative assets and media library."),
    ("assets.create", "Create assets", "Create or ingest creative assets."),
    ("assets.update", "Update assets", "Edit asset metadata and preparation state."),
    ("assets.archive", "Archive assets", "Archive assets without physical historical deletion."),
    ("production.read", "Read production", "Read production plans, packages, and generation status."),
    ("production.plan", "Plan production", "Prepare production plans and provider-free previews."),
    ("production.execute", "Execute production", "Authorize and dispatch approved production work."),
    ("production.control", "Control production", "Pause, resume, cancel, retry, and control running work."),
    ("production.approve", "Approve production", "Approve production manifests and execution gates."),
    ("poster.read", "Read posters", "Read poster recipes and deliverables."),
    ("poster.create", "Create posters", "Create poster drafts and deterministic compositions."),
    ("poster.update", "Update posters", "Edit poster drafts and settings."),
    ("poster.approve", "Approve posters", "Approve poster deliverables or live image gates."),
    ("reporting.read", "Read reporting", "Read authenticated staff performance and operational reporting."),
    ("publishing.read", "Read publishing", "Read publishing records and status."),
    ("publishing.execute", "Execute publishing", "Publish approved content through configured channels."),
    ("jobs.read", "Read jobs", "Read queues and job status."),
    ("jobs.control", "Control jobs", "Control queues and retry/cancel jobs."),
    ("provider.read", "Read providers", "Read provider state without exposing credentials."),
    ("provider.manage", "Manage providers", "Manage provider configuration and credentials."),
)

_ALL_READ = tuple(
    code
    for code, _, _ in PERMISSION_SEEDS
    if code.endswith(".read")
    and not code.startswith(("staff.", "roles.", "sessions.", "audit."))
)

ROLE_PERMISSION_CODES: dict[str, tuple[str, ...]] = {
    "OWNER": tuple(code for code, _, _ in PERMISSION_SEEDS),
    "MANAGER": tuple(
        code
        for code, _, _ in PERMISSION_SEEDS
        if code
        not in {
            "staff.manage",
            "staff.read",
            "roles.manage",
            "roles.read",
            "sessions.revoke",
            "sessions.read",
            "audit.read",
            "provider.manage",
            "system.settings.manage",
        }
    ),
    "OPERATOR": tuple(
        sorted(
            set(_ALL_READ)
            | {
                "production.plan",
                "production.execute",
                "production.control",
                "production.approve",
                "jobs.control",
            }
        )
    ),
    "EDITOR": tuple(
        sorted(
            set(_ALL_READ)
            | {
                "products.create",
                "products.update",
                "copy.create",
                "copy.update",
                "copy.approve",
                "assets.create",
                "assets.update",
                "poster.create",
                "poster.update",
                "production.plan",
            }
        )
    ),
    "VIEWER": tuple(sorted(_ALL_READ)),
}

ROLE_CODES = frozenset(code for code, _, _ in ROLE_SEEDS)
PERMISSION_CODES = frozenset(code for code, _, _ in PERMISSION_SEEDS)
