"""Read-only verification helpers for previously persisted poster artifacts.

E1 replay must prove the existing chain without re-submitting to a provider or
mutating the canonical database.  This module deliberately has no database or
transport dependency; it only hashes an already materialised local file.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def verify_existing_artifact(
    path: str | Path,
    expected_sha256: str,
) -> dict[str, Any]:
    """Verify one persisted artifact without provider or database side effects."""

    artifact_path = Path(path)
    base: dict[str, Any] = {
        "path": str(artifact_path),
        "expected_sha256": expected_sha256,
        "provider_operation_count": 0,
        "db_mutation_count": 0,
    }
    if not artifact_path.is_file():
        return {**base, "status": "MISSING_ARTIFACT", "actual_sha256": ""}
    try:
        actual_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    except OSError as exc:
        return {
            **base,
            "status": "ARTIFACT_READ_ERROR",
            "actual_sha256": "",
            "error": type(exc).__name__,
        }
    if actual_sha256 != expected_sha256:
        return {
            **base,
            "status": "ARTIFACT_HASH_MISMATCH",
            "actual_sha256": actual_sha256,
        }
    return {
        **base,
        "status": "REPLAY_VERIFIED",
        "actual_sha256": actual_sha256,
    }
