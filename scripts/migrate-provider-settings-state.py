"""Secret-safe copy and verification for the canonical provider settings file.

The migration layer may move the file bytes, but it must never expose the
provider values.  All summaries returned by this module contain only state
metadata and short SHA-256 fingerprints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


PROVIDER_IDS = ("qwen", "anthropic", "openai", "gemini", "deepseek")
LANE_IDS = ("text_assist", "vision")


class ProviderSettingsMigrationError(RuntimeError):
    """Raised when provider state cannot be migrated without overwriting it."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _key_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _safe_lane(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}
    provider_id = str(entry.get("provider_id") or "").strip().lower() or None
    model_id = str(entry.get("model_id") or "").strip() or None
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "execution_enabled": bool(entry.get("execution_enabled")),
        "configured_by_user": bool(entry.get("configured_by_user")),
    }


def inspect_settings(path: Path) -> dict[str, Any]:
    """Return provider state metadata without returning any key material."""

    path = path.resolve()
    if not path.is_file():
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_FILE_MISSING")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_FILE_INVALID") from exc
    if not isinstance(raw, dict):
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_FILE_INVALID")

    raw_providers = raw.get("providers")
    if not isinstance(raw_providers, dict):
        raw_providers = {}
    providers: dict[str, dict[str, Any]] = {}
    for provider_id in PROVIDER_IDS:
        entry = raw_providers.get(provider_id)
        if not isinstance(entry, dict):
            entry = {}
        value = entry.get("api_key") or ""
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        providers[provider_id] = {
            "has_key": bool(value),
            "key_length": len(value),
            "sha256_12": _key_fingerprint(value) if value else None,
            "updated_at": entry.get("updated_at"),
            "activated_at": entry.get("activated_at"),
            "default_model": entry.get("default_model"),
        }

    raw_lanes = raw.get("lanes")
    if not isinstance(raw_lanes, dict):
        raw_lanes = {}
    lanes = {lane: _safe_lane(raw_lanes.get(lane)) for lane in LANE_IDS}
    active_provider = str(raw.get("active_provider") or "").strip().lower() or None

    state_is_empty = (
        not any(
            provider["has_key"]
            or provider["updated_at"] is not None
            or provider["activated_at"] is not None
            or provider["default_model"] is not None
            for provider in providers.values()
        )
        and active_provider is None
        and not any(
            lane["provider_id"]
            or lane["model_id"]
            or lane["execution_enabled"]
            or lane["configured_by_user"]
            for lane in lanes.values()
        )
    )
    return {
        "path": str(path),
        "version": raw.get("version"),
        "active_provider": active_provider,
        "providers": providers,
        "lanes": lanes,
        "has_any_key": any(provider["has_key"] for provider in providers.values()),
        "state_is_empty": state_is_empty,
        "file_sha256": _sha256(path),
        "file_size": path.stat().st_size,
    }


def _assert_destination_safe(destination: Path) -> None:
    if not destination.exists():
        return
    try:
        summary = inspect_settings(destination)
    except ProviderSettingsMigrationError as exc:
        raise ProviderSettingsMigrationError(
            "PROVIDER_SETTINGS_DESTINATION_INVALID"
        ) from exc
    if summary["has_any_key"]:
        raise ProviderSettingsMigrationError(
            "PROVIDER_SETTINGS_DESTINATION_POPULATED"
        )
    if not summary["state_is_empty"]:
        raise ProviderSettingsMigrationError(
            "PROVIDER_SETTINGS_DESTINATION_CONFLICT"
        )


def migrate_provider_settings(source: Path, destination: Path) -> dict[str, Any]:
    """Copy source state atomically and verify source/destination metadata."""

    source = source.resolve()
    destination = destination.resolve()
    if not source.exists():
        return {
            "status": "SOURCE_ABSENT",
            "source_exists": False,
            "destination_exists": destination.is_file(),
        }
    if not source.is_file():
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_SOURCE_INVALID")

    source_summary = inspect_settings(source)
    _assert_destination_safe(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.migration-{os.getpid()}.tmp"
    )
    try:
        if temporary.exists():
            temporary.unlink()
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    except OSError as exc:
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_COPY_FAILED") from exc
    finally:
        if temporary.exists():
            temporary.unlink()

    destination_summary = inspect_settings(destination)
    if source_summary["file_sha256"] != destination_summary["file_sha256"]:
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_COPY_VERIFY_FAILED")
    if source_summary["providers"] != destination_summary["providers"]:
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_PROVIDER_VERIFY_FAILED")
    if source_summary["lanes"] != destination_summary["lanes"]:
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_LANE_VERIFY_FAILED")
    if source_summary["active_provider"] != destination_summary["active_provider"]:
        raise ProviderSettingsMigrationError("PROVIDER_SETTINGS_ACTIVE_VERIFY_FAILED")

    return {
        "status": "COPIED",
        "source_exists": True,
        "destination_exists": True,
        "source_file_sha256": source_summary["file_sha256"],
        "destination_file_sha256": destination_summary["file_sha256"],
        "source": source_summary,
        "destination": destination_summary,
    }


def _public_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Remove internal full-file hashes while retaining safe verification data."""

    result = dict(summary)
    for key in ("file_sha256", "source_file_sha256", "destination_file_sha256"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = value[:12]
    for key in ("source", "destination"):
        nested = result.get(key)
        if isinstance(nested, dict):
            result[key] = _public_summary(nested)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        result = migrate_provider_settings(args.source, args.destination)
    except ProviderSettingsMigrationError as exc:
        print(f"PROVIDER_SETTINGS_MIGRATION_FAILED:{exc}", file=sys.stderr)
        return 1
    output = _public_summary(result)
    if args.as_json:
        print(json.dumps(output, sort_keys=True))
    else:
        print(f"status: {output['status']}")
        print(f"source_exists: {output['source_exists']}")
        print(f"destination_exists: {output['destination_exists']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
