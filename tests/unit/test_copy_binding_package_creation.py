"""Stage 2B — per-item Copy Set binding survives into the DURABLE package.

The gap this closes: ``create_workspace_execution_package`` could bind a copy
variant, but seeding a durable package re-compiled from the approved package
WITHOUT it, so the binding was lost before the package existed. Bulk fan-out
needs one approved variant per item, otherwise "no duplicate dialogue" is
unenforceable at the package level.

The contract proven here:
  * ``copy_set_id=None`` (every pre-existing caller) is byte-identical — the
    resolver is not even consulted, so no behaviour and no DB read changes.
  * ``copy_set_id="cs_x"`` binds that variant's compiler copy.
  * An explicit ``copy_intelligence`` still wins on top of a bound variant, so
    the batch path's ``hook_override`` keeps working.
  * An invalid / unapproved variant FAILS CLOSED (CopyBindingError).
  * N items bind N DISTINCT variants → N distinct dialogues.

Nothing here calls a provider, Flow, or a text-LLM, and nothing approves copy.
"""
import asyncio

import pytest

from agent.services import workspace_generation_package_service as svc


class _Boom(Exception):
    """Stand-in for CopyBindingError — proves fail-closed propagation."""


def _resolver(mapping, *, calls=None):
    async def _resolve(product_id, copy_set_id):
        if calls is not None:
            calls.append((product_id, copy_set_id))
        if copy_set_id not in mapping:
            raise _Boom(f"COPY_SET_NOT_APPROVED:{copy_set_id}")
        return {"copy_intelligence": mapping[copy_set_id], "lineage": {}, "warning": None}
    return _resolve


def _patch(monkeypatch, mapping, calls=None):
    import agent.services.copy_binding_service as cbs
    monkeypatch.setattr(cbs, "resolve_compiler_copy_intelligence", _resolver(mapping, calls=calls))


def _run(product_id, copy_set_id, copy_intelligence=None):
    return asyncio.run(svc._resolve_bound_copy_intelligence(
        product_id, copy_set_id, copy_intelligence))


# ── existing callers are untouched ───────────────────────────────────────────
def test_no_copy_set_id_does_not_consult_the_resolver(monkeypatch):
    """The default path must not even read the DB — zero behaviour change."""
    calls: list = []
    _patch(monkeypatch, {"cs1": {"hook": "bound"}}, calls=calls)
    assert _run("P", None, None) is None
    assert _run("P", "", None) is None
    assert calls == [], "resolver must not be consulted when copy_set_id is falsy"


def test_no_copy_set_id_passes_explicit_copy_intelligence_through_unchanged(monkeypatch):
    calls: list = []
    _patch(monkeypatch, {}, calls=calls)
    explicit = {"hook": "operator hook", "cta": "buy"}
    assert _run("P", None, explicit) is explicit
    assert calls == []


# ── binding works ────────────────────────────────────────────────────────────
def test_copy_set_id_binds_that_variants_compiler_copy(monkeypatch):
    _patch(monkeypatch, {"cs1": {"hook": "variant one", "cta": "cta one"}})
    out = _run("P", "cs1", None)
    assert out == {"hook": "variant one", "cta": "cta one"}


def test_explicit_copy_intelligence_wins_over_the_bound_variant(monkeypatch):
    """The batch path's hook_override must still apply over a bound variant."""
    _patch(monkeypatch, {"cs1": {"hook": "variant hook", "cta": "variant cta"}})
    out = _run("P", "cs1", {"hook": "override hook"})
    assert out["hook"] == "override hook"   # explicit wins
    assert out["cta"] == "variant cta"      # bound variant still supplies the rest


def test_invalid_or_unapproved_copy_set_fails_closed(monkeypatch):
    """An unapproved variant must raise, never silently fall back to landbank."""
    _patch(monkeypatch, {"cs1": {"hook": "ok"}})
    with pytest.raises(_Boom, match="COPY_SET_NOT_APPROVED:cs_missing"):
        _run("P", "cs_missing", None)


def test_resolver_returning_no_copy_falls_back_to_explicit(monkeypatch):
    """Degraded resolve (no copy) must not wipe an operator's explicit copy."""
    import agent.services.copy_binding_service as cbs

    async def _resolve(product_id, copy_set_id):
        return {"copy_intelligence": None, "lineage": {}, "warning": "COPY_SET_NOT_SELECTED"}
    monkeypatch.setattr(cbs, "resolve_compiler_copy_intelligence", _resolve)
    explicit = {"hook": "operator"}
    assert _run("P", "cs1", explicit) is explicit


# ── N items keep DISTINCT identity ───────────────────────────────────────────
def test_n_items_bind_n_distinct_variants(monkeypatch):
    """The whole point of Stage 2B: each item gets its own approved variant."""
    mapping = {f"cs{i}": {"hook": f"hook {i}", "cta": f"cta {i}"} for i in range(3)}
    _patch(monkeypatch, mapping)
    bound = [_run("P", f"cs{i}", None) for i in range(3)]
    assert len({b["hook"] for b in bound}) == 3
    assert bound[0] != bound[1] != bound[2]


def test_same_variant_twice_yields_identical_copy(monkeypatch):
    """Reusing one variant must NOT masquerade as two distinct items — this is
    exactly what the fan-out gate's duplicate-dialogue check then rejects."""
    _patch(monkeypatch, {"cs1": {"hook": "same", "cta": "same"}})
    assert _run("P", "cs1", None) == _run("P", "cs1", None)


# ── creator signatures accept the new optional param, defaulted None ─────────
@pytest.mark.parametrize("creator_name", [
    "create_t2v_generation_package",
    "create_f2v_generation_package",
    "create_i2v_generation_package",
])
def test_creators_accept_optional_copy_set_id_defaulting_to_none(creator_name):
    import inspect
    sig = inspect.signature(getattr(svc, creator_name))
    assert "copy_set_id" in sig.parameters, f"{creator_name} must accept copy_set_id"
    param = sig.parameters["copy_set_id"]
    assert param.default is None, f"{creator_name}.copy_set_id must default to None"
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("creator_name", [
    "create_t2v_generation_package",
    "create_f2v_generation_package",
    "create_i2v_generation_package",
])
def test_creators_bind_copy_before_compiling(creator_name):
    """The binding must happen ahead of the compile call, or the package would be
    compiled with unbound copy and the variant would be lost again."""
    import inspect
    src = inspect.getsource(getattr(svc, creator_name))
    assert "_resolve_bound_copy_intelligence" in src
    assert src.index("_resolve_bound_copy_intelligence") < src.index("compile_ugc_video_prompt")


def test_seeding_route_threads_the_weps_bound_copy_set():
    """/from-execution-package is where the binding used to be dropped."""
    import pathlib
    src = pathlib.Path("agent/api/workspace_generation_packages.py").read_text(encoding="utf-8")
    assert '(lineage.get("copy_binding") or {}).get("copy_set_id")' in src
    assert src.count("copy_set_id=_bound_copy_set_id") == 3, "F2V + I2V + T2V must all thread it"


def test_no_count_n_shortcut_introduced():
    """Bulk is N packages, never one count:N submission."""
    import inspect
    from agent.services import production_queue_service as pq
    assert "max(1, min(4, int(count or 1)))" in inspect.getsource(pq.send_to_production)


def test_binding_path_calls_no_provider_flow_or_llm():
    """The binding seam is pure DB read + dict merge.

    Scans CODE only — comments and the docstring are stripped, so prose like
    'never fires a provider' cannot pass or fail this check."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(svc._resolve_bound_copy_intelligence)))
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]          # drop the docstring
    code = ast.unparse(ast.Module(body=fn.body, type_ignores=[]))
    for forbidden in ("start_generate", "flow_client", "generate_candidate",
                      "ai_copy_provider", "requests.", "httpx", "aiohttp"):
        assert forbidden not in code, f"binding path must not reference {forbidden}"
