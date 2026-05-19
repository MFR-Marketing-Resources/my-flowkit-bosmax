"""
Unit tests for Patches A–D of hotfix/fastmoss-smart-mapping-extraction.

Covers:
- Patch A: multi-pattern size/volume extraction in _extract_facts()
- Patch B: category-gated SIZE_OR_VOLUME_EVIDENCE in _evaluate_completion_status()
- Patch C: expanded bosmax_product_family.py vocabulary
- Patch D: category field passthrough from request → temp_product → family resolver
"""
from __future__ import annotations

import pytest

from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.product_knowledge_service import (
    _evaluate_completion_status,
    _extract_facts,
)


# ---------------------------------------------------------------------------
# Patch A — size/volume extraction
# ---------------------------------------------------------------------------

class TestSizeExtraction:
    """_extract_facts() must extract size/volume from Malaysian TikTok titles."""

    def _facts(self, text: str) -> dict:
        req = ProductKnowledgeCompleteRequest(
            product_name=text,
            paste_anything_about_product=text,
        )
        return _extract_facts(req)

    def test_liquid_ml_lowercase(self):
        assert "400ml" in self._facts("Toner Refa 400ml kulit sensitif")["size_or_volume"].lower()

    def test_liquid_ml_uppercase(self):
        result = self._facts("Face Wash 10ML")["size_or_volume"]
        assert result is not None
        assert "10" in result

    def test_count_pcs(self):
        result = self._facts("Vitamin C 50PCS tablet")["size_or_volume"]
        assert result is not None
        assert "50" in result

    def test_apparel_range_s_to_5xl(self):
        result = self._facts("Blouse Muslimah Saiz S-5XL Corak Bunga")["size_or_volume"]
        assert result is not None
        assert "S" in result.upper() and "XL" in result.upper()

    def test_apparel_range_m_l_xl(self):
        result = self._facts("Seluar Perempuan M-L-XL")["size_or_volume"]
        assert result is not None

    def test_apparel_spaced_sizes(self):
        result = self._facts("Dress Peplum XS S M L")["size_or_volume"]
        assert result is not None

    def test_free_size_english(self):
        result = self._facts("Telekung Premium Free Size")["size_or_volume"]
        assert result is not None
        assert "free" in result.lower() or "size" in result.lower()

    def test_free_size_malay(self):
        result = self._facts("Baju Kurung Moden Saiz Bebas")["size_or_volume"]
        assert result is not None

    def test_bidang_plain(self):
        result = self._facts("Kain Batik Bidang 45 Premium")["size_or_volume"]
        assert result is not None
        assert "45" in result

    def test_bidang_range(self):
        result = self._facts("Kain Cotton Bidang 45-48 dan 50-55")["size_or_volume"]
        assert result is not None
        assert "45" in result

    def test_dimension_x(self):
        result = self._facts("Bantal Peha 30x60cm Premium")["size_or_volume"]
        assert result is not None
        assert "30" in result

    def test_weight_g(self):
        result = self._facts("Serbuk Ubat 100g kegunaan harian")["size_or_volume"]
        assert result is not None
        assert "100" in result

    def test_weight_range_slash(self):
        result = self._facts("Protein Shake 100g/200g/400g pelbagai rasa")["size_or_volume"]
        assert result is not None

    def test_multi_unit_5_liter_5_kg(self):
        result = self._facts("Detergen Cecair 5 LITER / 5 KG")["size_or_volume"]
        assert result is not None

    def test_volume_1200ml_900ml(self):
        result = self._facts("Sabun Pencuci 1200ML/900ML")["size_or_volume"]
        assert result is not None
        assert "1200" in result or "900" in result

    def test_electronics_watt(self):
        result = self._facts("Blender Berkuasa 240W Isi Padu 1.5L")["size_or_volume"]
        assert result is not None

    def test_length_meter(self):
        result = self._facts("Kabel USB 1 Meter Panjang")["size_or_volume"]
        assert result is not None

    def test_length_ft_range(self):
        result = self._facts("Kain Langsir 4ft-12ft pelbagai saiz")["size_or_volume"]
        assert result is not None

    def test_sml_token(self):
        result = self._facts("Baju T-Shirt SML Cotton")["size_or_volume"]
        assert result is not None

    def test_freesize_joined(self):
        result = self._facts("Dress Kemeja Freesize Wanita")["size_or_volume"]
        assert result is not None


# ---------------------------------------------------------------------------
# Patch B — category-gated SIZE_OR_VOLUME_EVIDENCE
# ---------------------------------------------------------------------------

class TestSizeEvidenceGate:
    """_evaluate_completion_status() must NOT flag SIZE_OR_VOLUME_EVIDENCE for exempt categories."""

    def _eval(self, category: str, family: str, has_size: bool = False):
        req = ProductKnowledgeCompleteRequest(
            product_name="Test Product",
            paste_anything_about_product="some description",
            price=10.0,
            currency="MYR",
            commission_rate="10%",
            commission_amount=1.0,
            category=category,
        )
        facts = {"size_or_volume": "M-L-XL"} if has_size else {}
        intelligence = {"bosmax_product_family": family}
        _, _, missing = _evaluate_completion_status(req, facts, intelligence)
        return missing

    def test_fashion_apparel_no_size_not_blocked(self):
        missing = self._eval(category="Fashion", family="fashion_apparel")
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_muslim_fashion_no_size_not_blocked(self):
        missing = self._eval(category="Muslim Fashion", family="fashion_modestwear")
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_books_no_size_not_blocked(self):
        missing = self._eval(category="Books", family="stationery_paper")
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_apparel_sleepwear_no_size_not_blocked(self):
        missing = self._eval(category="Womenswear and Underwear", family="APPAREL_SLEEPWEAR")
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_accessories_no_size_not_blocked(self):
        missing = self._eval(category="Accessories", family="ACCESSORY_SMALL_ITEM")
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_home_decor_no_size_not_blocked(self):
        missing = self._eval(category="Home Decor", family="HOME_TEXTILE")
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_electronics_accessories_no_size_not_blocked(self):
        missing = self._eval(category="Phones & Electronics", family="electronics_wearable")
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_beauty_no_size_IS_blocked(self):
        req = ProductKnowledgeCompleteRequest(
            product_name="Serum Muka",
            paste_anything_about_product="description",
            price=20.0,
            currency="MYR",
            commission_rate="5%",
            commission_amount=1.0,
            category="Beauty Personal Care",
        )
        facts = {}
        intelligence = {"bosmax_product_family": "BEAUTY_PERSONAL_CARE"}
        _, _, missing = _evaluate_completion_status(req, facts, intelligence)
        assert "SIZE_OR_VOLUME_EVIDENCE" in missing

    def test_food_no_size_IS_blocked(self):
        req = ProductKnowledgeCompleteRequest(
            product_name="Sambal Ikan",
            paste_anything_about_product="description",
            price=8.0,
            currency="MYR",
            commission_rate="5%",
            commission_amount=0.4,
            category="Food Beverage",
        )
        facts = {}
        intelligence = {"bosmax_product_family": "food_packaged"}
        _, _, missing = _evaluate_completion_status(req, facts, intelligence)
        assert "SIZE_OR_VOLUME_EVIDENCE" in missing

    def _eval_real_title(self, title: str, category: str):
        req = ProductKnowledgeCompleteRequest(
            product_name=title,
            paste_anything_about_product=title,
            price=20.0,
            currency="MYR",
            commission_rate="5%",
            commission_amount=1.0,
            category=category,
        )
        facts = _extract_facts(req)
        family = derive_bosmax_product_family(
            {
                "raw_product_title": title,
                "product_display_name": title,
                "category": category,
            }
        )["bosmax_product_family"]
        _, _, missing = _evaluate_completion_status(
            req,
            facts,
            {"bosmax_product_family": family},
        )
        return family, facts, missing

    @pytest.mark.parametrize(
        ("title", "category"),
        [
            (
                "Quinnbella Brow Gel Eyebrow Tint Brow Sculpt Lift Eyebrow Styling Long Lasting Waterproof Eyebrow Soap",
                "Beauty & Personal Care",
            ),
            (
                "[LESSXCOCO]Waterproof Mascara Long LastingNatural Curling Eye Lash Makeup Maskara EyelashBlack",
                "Beauty & Personal Care",
            ),
            (
                "KAXIER Eyeshadow Two-tone Cream Eyeshadow Stick Pearlescent Long Lasting Waterproof Easy To Color Eye Makeup",
                "Beauty & Personal Care",
            ),
            (
                "Hijau Lipstik Blooming Matte lip tint lipstick tahan lama waterprooftidak melekat dicawan",
                "Beauty & Personal Care",
            ),
            (
                "Yessica's Waterproof Foundation Long Lasting Matte Concealer Full Coverage Invisible Pores Flawless Base",
                "Beauty & Personal Care",
            ),
            (
                "[NEW 2026] ANAS Powder Blusher DUO #06",
                "Beauty & Personal Care",
            ),
        ],
    )
    def test_real_decorative_titles_no_size_not_blocked(self, title: str, category: str):
        family, _, missing = self._eval_real_title(title, category)
        assert family == "BEAUTY_PERSONAL_CARE"
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_real_phone_holder_no_size_not_blocked(self):
        title = "HOTOP 360 Rotatable Car Phone Holder For Dashboard And Windshield Suction Cup Cell Phone Mount"
        family, _, missing = self._eval_real_title(title, "Automotive & Motorcycle")
        assert family == "ACCESSORY_SMALL_ITEM"
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    def test_real_visible_size_title_clears_size_block(self):
        title = "Adult Diaper pants 9pcs/1pack comfortable fit overnight protection"
        family, facts, missing = self._eval_real_title(title, "Baby & Maternity")
        assert family == "BABY_DIAPER"
        assert facts.get("size_or_volume") is not None
        assert "SIZE_OR_VOLUME_EVIDENCE" not in missing

    @pytest.mark.parametrize(
        ("title", "category", "expected_family"),
        [
            (
                "SUISCO Syampu Keratin Rawatan Rambut Hair Care Set",
                "Beauty & Personal Care",
                "BEAUTY_PERSONAL_CARE",
            ),
            (
                "Original Roach Ant Umpan Semut Lipas repellent spray",
                "Home Supplies",
                "HOUSEHOLD_CLEANER_GENERAL",
            ),
            (
                "Diamond Coating Ceramic Car Coating Spray Nano Quick Coating",
                "Automotive & Motorcycle",
                None,
            ),
        ],
    )
    def test_real_measurable_titles_without_size_stay_blocked(
        self,
        title: str,
        category: str,
        expected_family: str | None,
    ):
        family, _, missing = self._eval_real_title(title, category)
        if expected_family is not None:
            assert family == expected_family
        assert "SIZE_OR_VOLUME_EVIDENCE" in missing


# ---------------------------------------------------------------------------
# Patch C — expanded bosmax_product_family vocabulary
# ---------------------------------------------------------------------------

class TestBosmaxFamilyExpansion:
    """derive_bosmax_product_family() must resolve newly-added product types."""

    def _family(self, title: str, category: str = "", subcategory: str = "") -> str:
        product = {
            "raw_product_title": title,
            "product_display_name": title,
            "category": category,
            "subcategory": subcategory,
        }
        return derive_bosmax_product_family(product)["bosmax_product_family"]

    def test_stokin_resolves_apparel(self):
        assert self._family("Stokin Kaki Wanita 3 Pasang") == "fashion_apparel"

    def test_socks_resolves_apparel(self):
        assert self._family("Cotton socks ankle 5-pack") == "fashion_apparel"

    def test_mascara_resolves_beauty(self):
        assert self._family("Mascara Tahan Lama Waterproof") == "BEAUTY_PERSONAL_CARE"

    def test_eyeliner_resolves_beauty(self):
        assert self._family("Eyeliner Pen Hitam Tajam") == "BEAUTY_PERSONAL_CARE"

    def test_lipstick_resolves_beauty(self):
        assert self._family("Lipstik Matte Korea") == "BEAUTY_PERSONAL_CARE"

    def test_lip_gloss_resolves_beauty(self):
        assert self._family("Lip Gloss Viral TikTok") == "BEAUTY_PERSONAL_CARE"

    def test_phone_holder_resolves_accessory_small_item(self):
        assert (
            self._family(
                "HOTOP 360 Rotatable Car Phone Holder Dashboard Windshield Suction Cup Cell Phone Mount",
                "Automotive & Motorcycle",
            )
            == "ACCESSORY_SMALL_ITEM"
        )

    def test_syampu_resolves_beauty(self):
        assert self._family("Syampu Anti Gugur Rambut") == "BEAUTY_PERSONAL_CARE"

    def test_shampoo_resolves_beauty(self):
        assert self._family("Shampoo Keratin 300ml") == "BEAUTY_PERSONAL_CARE"

    def test_usb_cable_resolves_electronics(self):
        assert self._family("Kabel USB Type-C 1 Meter Fast Charge") == "electronics_wearable"

    def test_charger_resolves_electronics(self):
        assert self._family("Pengecas Wireless 65W") == "electronics_wearable"

    def test_buku_resolves_stationery(self):
        assert self._family("Buku Panduan Solat Lengkap") == "stationery_paper"

    def test_wirid_resolves_stationery(self):
        assert self._family("Wirid Dan Doa Harian Islam") == "stationery_paper"

    def test_wall_sticker_resolves_home_textile(self):
        assert self._family("Wall Sticker Hiasan Dinding Bilik") == "HOME_TEXTILE"

    def test_telekung_resolves_modestwear(self):
        assert self._family("Telekung Renda Eksklusif Premium") == "fashion_modestwear"

    def test_scarf_resolves_modestwear(self):
        assert self._family("Scarf Printed Korea Kualiti Premium") == "fashion_modestwear"

    def test_bra_resolves_apparel(self):
        assert self._family("Wireless Bra Tanpa Keluli Lembut") == "fashion_apparel"

    def test_tissue_resolves_baby_wipes(self):
        assert self._family("Tisu Muka Lembut 200 Helai") == "BABY_WIPES"

    def test_tracksuit_resolves_sportswear(self):
        assert self._family("Tracksuit Lelaki Casual Sport") == "fashion_sportswear"

    def test_blender_resolves_organizer(self):
        assert self._family("Blender Pelbagai Fungsi 800W") == "HOUSEHOLD_STORAGE_ORGANIZER"

    def test_pillowcase_resolves_home_textile(self):
        assert self._family("Sarung Bantal Tidur Premium Lembut") == "HOME_TEXTILE"
