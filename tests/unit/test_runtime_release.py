"""Fail-closed production runtime provenance lock tests.

Proves the launcher refuses to serve stale/mutable/mismatched source and that the
canonical release passes — the structural fix for the recurring RUNTIME
PROVENANCE DRIFT incident.
"""

from pathlib import Path

import pytest

from agent import runtime_release as rr

SHA = "a" * 40
OTHER_SHA = "b" * 40


def _make_release(tmp_path, *, sha=SHA, bundle="index-ABC.js", with_manifest=True, manifest_bundle=None, db=None):
    root = tmp_path / "releases" / sha
    (root / "agent").mkdir(parents=True)
    (root / "agent" / "main.py").write_text("# stub", encoding="utf-8")
    dist = root / "dashboard" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(f'<script type="module" src="/assets/{bundle}"></script>', encoding="utf-8")
    if with_manifest:
        rr.write_manifest(
            root, deployed_sha=sha, deployed_at="2026-08-10T00:00:00Z",
            dashboard_bundle=(manifest_bundle or bundle), db_path=db or "unused",
        )
    return root


@pytest.fixture
def env(tmp_path, monkeypatch):
    dev = tmp_path / "_ref_flowkit"
    dev.mkdir()
    canon = dev / "flow_agent.db"
    canon.write_text("db", encoding="utf-8")
    monkeypatch.setenv("BOSMAX_DEV_ROOT", str(dev))
    monkeypatch.setenv("BOSMAX_CANONICAL_DB", str(canon))
    return dev, str(canon)


@pytest.fixture
def clean_git(monkeypatch):
    monkeypatch.setattr(rr, "git_head", lambda _r: SHA)
    monkeypatch.setattr(rr, "git_is_dirty", lambda _r: False)


def test_manifest_round_trip(tmp_path):
    root = _make_release(tmp_path)
    m = rr.read_manifest(root)
    assert m["deployed_sha"] == SHA and m["schema"] == "bosmax-runtime-manifest/1"
    assert m["dashboard_bundle"] == "index-ABC.js"


def test_default_canonical_db_uses_stable_runtime_state_root(monkeypatch, tmp_path):
    monkeypatch.delenv("BOSMAX_CANONICAL_DB", raising=False)
    monkeypatch.setenv("BOSMAX_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.delenv("BOSMAX_CANONICAL_STATE_ROOT", raising=False)

    assert rr.canonical_state_root() == (tmp_path / "runtime" / "state").resolve()
    assert rr.canonical_db_path() == (tmp_path / "runtime" / "state" / "flow_agent.db").resolve()


def test_canonical_release_passes(env, clean_git, tmp_path):
    _dev, canon = env
    root = _make_release(tmp_path, db=canon)
    ok, code, prov = rr.validate_production_release(root, canon)
    assert ok is True and code is None
    assert prov["canonical_runtime"] is True and prov["source_stale"] is False


def test_dev_root_forbidden(env, clean_git, tmp_path):
    # If production is (mis)launched from the dev root itself -> fail closed.
    dev, canon = env
    (dev / "agent").mkdir()
    (dev / "agent" / "main.py").write_text("# stub", encoding="utf-8")
    (dev / "dashboard" / "dist").mkdir(parents=True)
    (dev / "dashboard" / "dist" / "index.html").write_text('src="/assets/index-ABC.js"', encoding="utf-8")
    rr.write_manifest(dev, deployed_sha=SHA, deployed_at="x", dashboard_bundle="index-ABC.js", db_path=canon)
    ok, code, _ = rr.validate_production_release(dev, canon)
    assert ok is False and code == rr.ERR_DEV_ROOT


def test_manifest_missing(env, clean_git, tmp_path):
    _dev, canon = env
    root = _make_release(tmp_path, with_manifest=False, db=canon)
    ok, code, _ = rr.validate_production_release(root, canon)
    assert ok is False and code == rr.ERR_MANIFEST_MISSING


def test_sha_unresolvable(env, monkeypatch, tmp_path):
    _dev, canon = env
    monkeypatch.setattr(rr, "git_head", lambda _r: None)
    monkeypatch.setattr(rr, "git_is_dirty", lambda _r: False)
    root = _make_release(tmp_path, db=canon)
    ok, code, _ = rr.validate_production_release(root, canon)
    assert ok is False and code == rr.ERR_SHA_UNRESOLVABLE


def test_dirty_release_forbidden(env, monkeypatch, tmp_path):
    _dev, canon = env
    monkeypatch.setattr(rr, "git_head", lambda _r: SHA)
    monkeypatch.setattr(rr, "git_is_dirty", lambda _r: True)
    root = _make_release(tmp_path, db=canon)
    ok, code, _ = rr.validate_production_release(root, canon)
    assert ok is False and code == rr.ERR_DIRTY


def test_sha_mismatch(env, monkeypatch, tmp_path):
    _dev, canon = env
    monkeypatch.setattr(rr, "git_head", lambda _r: OTHER_SHA)  # HEAD != manifest deployed_sha
    monkeypatch.setattr(rr, "git_is_dirty", lambda _r: False)
    root = _make_release(tmp_path, sha=SHA, db=canon)
    ok, code, _ = rr.validate_production_release(root, canon)
    assert ok is False and code == rr.ERR_SHA_MISMATCH


def test_db_path_mismatch(env, clean_git, tmp_path):
    _dev, canon = env
    root = _make_release(tmp_path, db=canon)
    ok, code, _ = rr.validate_production_release(root, str(tmp_path / "some-other.db"))
    assert ok is False and code == rr.ERR_DB_PATH


def test_bundle_mismatch(env, clean_git, tmp_path):
    _dev, canon = env
    # manifest claims a different bundle than the built index.html serves
    root = _make_release(tmp_path, bundle="index-BUILT.js", manifest_bundle="index-OLD.js", db=canon)
    ok, code, _ = rr.validate_production_release(root, canon)
    assert ok is False and code == rr.ERR_BUNDLE


def test_resolve_flags_dev_root_serving_and_stale(env, monkeypatch, tmp_path):
    dev, canon = env
    monkeypatch.setattr(rr, "git_head", lambda _r: "c" * 40)
    monkeypatch.setattr(rr, "git_is_dirty", lambda _r: True)
    prov = rr.resolve_provenance(dev, canon, origin_main=SHA)
    assert prov["dev_root_serving_production"] is True
    assert prov["canonical_runtime"] is False
    assert prov["source_stale"] is True
