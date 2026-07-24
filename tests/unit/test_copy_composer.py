"""Phase C1 — deterministic, angle-coherent composition from the component pool."""
from agent.services import copy_component_service as comp
from agent.services import copy_composer_service as svc

A1, A2 = "ang_colic0000001", "ang_aches0000002"
ANGLES = [
    {"angle_key": A1, "label": "Anak menangis malam kerana perut kembung"},
    {"angle_key": A2, "label": "Sengal badan selepas bekerja"},
]


def _c(cid, ctype, angle, content, usage=0):
    return {
        "component_id": cid,
        "component_type": ctype,
        "angle_key": angle,
        "content": content,
        "status": comp.STATUS_APPROVED,
        "archived": 0,
        "usage_count": usage,
    }


def _pool(angle, tag, hooks=2, subs=2, usps=2, ctas=2):
    out = []
    for i in range(hooks):
        out.append(_c(f"{tag}h{i}", comp.HOOK, angle, f"{tag} hook {i}"))
    for i in range(subs):
        out.append(_c(f"{tag}s{i}", comp.SUBHOOK, angle, f"{tag} subhook {i}"))
    for i in range(usps):
        out.append(_c(f"{tag}u{i}", comp.USP_SET, angle, f'["{tag} usp {i}"]'))
    for i in range(ctas):
        out.append(_c(f"{tag}c{i}", comp.CTA, angle, f"{tag} cta {i}"))
    return out


FULL = _pool(A1, "colic") + _pool(A2, "aches")


def test_output_slots_mirror_copy_set():
    out = svc.compose(FULL, ANGLES, 1)
    item = out["items"][0]
    assert set(item) >= {"angle", "hook", "subhook", "usp_set", "cta", "formula_family"}
    assert isinstance(item["usp_set"], list)
    assert "body" not in item


def test_composition_is_angle_coherent():
    """THE safety property: a colic hook must never meet an aches subhook."""
    out = svc.compose(FULL, ANGLES, 16)
    for item in out["items"]:
        tag = "colic" if item["angle_key"] == A1 else "aches"
        assert item["hook"].startswith(tag)
        assert item["subhook"].startswith(tag)
        assert item["cta"].startswith(tag)


def test_round_robin_spreads_across_angles():
    """Anti-monoculture: 4 requests must not all land on one angle."""
    out = svc.compose(FULL, ANGLES, 4)
    keys = [i["angle_key"] for i in out["items"]]
    assert keys.count(A1) == 2
    assert keys.count(A2) == 2
    assert keys[0] != keys[1]  # alternating, not draining angle 1 first


def test_hook_varies_fastest_so_early_output_looks_different():
    out = svc.compose(FULL, ANGLES, 4)
    colic = [i for i in out["items"] if i["angle_key"] == A1]
    assert colic[0]["hook"] != colic[1]["hook"]


def test_is_deterministic():
    a = svc.compose(FULL, ANGLES, 8)
    b = svc.compose(FULL, ANGLES, 8)
    assert [i["combination_fingerprint"] for i in a["items"]] == [
        i["combination_fingerprint"] for i in b["items"]
    ]


def test_no_duplicate_combinations():
    out = svc.compose(FULL, ANGLES, 32)
    fps = [i["combination_fingerprint"] for i in out["items"]]
    assert len(fps) == len(set(fps))


def test_capacity_is_respected_and_shortfall_reported():
    """2x2x2x2 per angle x 2 angles = 32 max. Asking for 40 yields 32 + a
    shortfall -- never a padded duplicate."""
    out = svc.compose(FULL, ANGLES, 40)
    assert out["produced"] == 32
    assert out["shortfall"] == 8
    assert len({i["combination_fingerprint"] for i in out["items"]}) == 32


def test_formulas_multiply_capacity():
    out = svc.compose(FULL, ANGLES, 64, formula_families=["PAS", "AIDA"])
    assert out["produced"] == 64
    assert {i["formula_family"] for i in out["items"]} == {"PAS", "AIDA"}


def test_excluded_fingerprints_are_never_re_emitted():
    first = svc.compose(FULL, ANGLES, 8)
    used = {i["combination_fingerprint"] for i in first["items"]}
    second = svc.compose(FULL, ANGLES, 8, exclude_fingerprints=used)
    assert not used & {i["combination_fingerprint"] for i in second["items"]}


def test_lru_components_are_consumed_first():
    pool = _pool(A1, "colic")
    for c in pool:
        if c["component_id"] == "colich0":
            c["usage_count"] = 99  # heavily used -> must come last
    out = svc.compose(pool, [ANGLES[0]], 1)
    assert out["items"][0]["hook"] == "colic hook 1"


def test_global_components_serve_every_angle():
    pool = [c for c in FULL if c["component_type"] != comp.CTA]
    pool.append(_c("gcta", comp.CTA, "", "Klik pautan di bawah"))
    out = svc.compose(pool, ANGLES, 4)
    assert out["produced"] == 4
    assert {i["cta"] for i in out["items"]} == {"Klik pautan di bawah"}


def test_angle_missing_a_type_is_blocked_not_silently_dropped():
    pool = _pool(A1, "colic") + [
        c for c in _pool(A2, "aches") if c["component_type"] != comp.CTA
    ]
    out = svc.compose(pool, ANGLES, 8)
    assert out["blocked_angles"] == [A2]
    assert all(i["angle_key"] == A1 for i in out["items"])
    assert any(w.startswith("ANGLE_BLOCKED:") for w in out["warnings"])


def test_unapproved_and_archived_components_are_never_composed():
    pool = list(FULL)
    pool.append(_c("bad1", comp.HOOK, A1, "UNREVIEWED HOOK"))
    pool[-1]["status"] = "COMPONENT_REVIEW_REQUIRED"
    pool.append(_c("bad2", comp.HOOK, A1, "ARCHIVED HOOK"))
    pool[-1]["archived"] = 1
    out = svc.compose(pool, ANGLES, 32)
    hooks = {i["hook"] for i in out["items"]}
    assert "UNREVIEWED HOOK" not in hooks
    assert "ARCHIVED HOOK" not in hooks


def test_usp_set_json_array_is_parsed():
    out = svc.compose(FULL, ANGLES, 1)
    assert out["items"][0]["usp_set"] == ["colic usp 0"]


def test_fingerprint_is_order_insensitive():
    a = svc.combination_fingerprint(["h1", "s1", "u1", "c1"], "PAS")
    b = svc.combination_fingerprint(["c1", "u1", "s1", "h1"], "PAS")
    assert a == b
    assert a != svc.combination_fingerprint(["h1", "s1", "u1", "c1"], "AIDA")


def test_composition_reports_its_own_angle_coverage():
    """Phase C2 wired in: round-robin makes skew unlikely, but the composer must
    still MEASURE it — nothing else in the lane does."""
    out = svc.compose(FULL, ANGLES, 8)
    cov = out["coverage"]
    assert cov["status"] == "COVERAGE_OK"
    assert cov["angles_covered"] == 2
    assert cov["missing_angles"] == []
    assert cov["per_angle"][0]["angle_label"]  # pain text, not a hash


def test_coverage_flags_a_pool_that_is_deep_on_one_angle_only():
    """A2 has 4 combinations, A1 has 16. Asking for 20 drains A2 and the batch
    tilts to A1 — exactly the skew the gate exists to surface."""
    thin = _pool(A1, "colic") + _pool(A2, "aches", hooks=1, subs=1, usps=1, ctas=1)
    out = svc.compose(thin, ANGLES, 20)
    keys = [i["angle_key"] for i in out["items"]]
    assert keys.count(A1) > keys.count(A2)
    assert out["coverage"]["dominant_angle"] == A1
    assert out["coverage"]["status"] != "COVERAGE_OK"


def test_empty_inputs_are_safe():
    assert svc.compose([], ANGLES, 5)["produced"] == 0
    assert svc.compose(FULL, [], 5)["produced"] == 0
    assert svc.compose(FULL, ANGLES, 0)["produced"] == 0
