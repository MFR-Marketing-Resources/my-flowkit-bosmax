"""COPY-CORRECTIVE-B03: placeholder safety scan must be token-boundary aware —
a real size like 6XXXL / XXXL is content, not an unfilled "xxx" placeholder.
"""
from agent.services.copy_set_service import scan_copy_safety


def _f(hook="", usp=None, cta="beli sekarang"):
    return {"angle": "", "hook": hook, "subhook": "", "usp_set": usp or [], "cta": cta}


def test_real_size_not_flagged_as_placeholder():
    r = scan_copy_safety(
        _f(hook="Karpet saiz 6XXXL menutup ruang tamu", usp=["Saiz 6XXXL besar", "Anti-slip"])
    )
    assert "UNRESOLVED_PLACEHOLDER" not in r["violations"]
    assert r["safe"] is True

    r2 = scan_copy_safety(_f(hook="Baju saiz XXXL selesa", usp=["Muat XXL hingga XXXL"]))
    assert "UNRESOLVED_PLACEHOLDER" not in r2["violations"]


def test_standalone_placeholder_still_flagged():
    r = scan_copy_safety(_f(hook="Beli xxx sekarang", usp=["Guna xxx harian"]))
    assert "UNRESOLVED_PLACEHOLDER" in r["violations"]
    r2 = scan_copy_safety(_f(hook="TODO fill this", usp=["ok"]))
    assert "UNRESOLVED_PLACEHOLDER" in r2["violations"]
    r3 = scan_copy_safety(_f(hook="Harga tbd", usp=["nanti"]))
    assert "UNRESOLVED_PLACEHOLDER" in r3["violations"]
