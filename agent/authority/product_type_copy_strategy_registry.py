"""P4 product-type copy strategy authority.

The registry is keyed by verified taxonomy, never by product ID. Templates are
preview-only and receive deterministic, claim-scanned product facts at runtime.
"""
from __future__ import annotations

from typing import Final, Literal, TypedDict


ProductTypeCopyStrategyKey = tuple[str, str, str]


class ProductTypeCopyScriptTemplate(TypedDict):
    hook_line: str
    demo_line: str
    benefit_line: str
    cta_line: str
    overlay_text: str


class ProductTypeCopyStrategyEntry(TypedDict):
    copy_strategy_id: str
    source_strategy: Literal["PRODUCT_TYPE_COPY_STRATEGY_REGISTRY"]
    scene_action_indices: tuple[int, ...]
    scene_result_template: str
    scripts: dict[int, ProductTypeCopyScriptTemplate]


def _fixed_strategy(
    *,
    copy_strategy_id: str,
    scene_result_template: str,
    hook_line: str,
    demo_line: str,
    benefit_line: str,
    cta_line: str,
    overlay_text: str,
) -> ProductTypeCopyStrategyEntry:
    """Build concise fixed-copy entries for exact Product Truth types."""

    script: ProductTypeCopyScriptTemplate = {
        "hook_line": hook_line,
        "demo_line": demo_line,
        "benefit_line": benefit_line,
        "cta_line": cta_line,
        "overlay_text": overlay_text,
    }
    return {
        "copy_strategy_id": copy_strategy_id,
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1),
        "scene_result_template": scene_result_template,
        "scripts": {
            8: dict(script),
            10: dict(script),
            16: dict(script),
        },
    }


PRODUCT_TYPE_COPY_STRATEGY_REGISTRY: Final[
    dict[ProductTypeCopyStrategyKey, ProductTypeCopyStrategyEntry]
] = {
    ("beauty_makeup", "lipstick_lip_tint", "LIP_COLOR"): {
        "copy_strategy_id": "P4_LIP_COLOR_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 2),
        "scene_result_template": (
            "show shade, colour payoff, texture, and finished-lip result clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat {finish_descriptor}?",
                "demo_line": "Sapu {product_reference} pada bibir.",
                "benefit_line": "{benefit_evidence}.",
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
            10: {
                "hook_line": "Nak lihat {finish_descriptor} dengan lebih jelas?",
                "demo_line": "Sapu {product_reference}, kemudian tunjuk shade.",
                "benefit_line": "{benefit_evidence}.",
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
            16: {
                "hook_line": (
                    "Nak lihat shade dan {finish_descriptor} sebelum pilih?"
                ),
                "demo_line": (
                    "Sapu {product_reference} pada bibir, kemudian tunjuk tekstur "
                    "dan hasil akhir."
                ),
                "benefit_line": (
                    "{benefit_evidence} untuk mudah bandingkan pilihan."
                ),
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
        },
    },
    ("food_cooking", "rempah_seasoning", "SPICE_SEASONING"): {
        "copy_strategy_id": "P4_REMPAH_SEASONING_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (1, 2, 3),
        "scene_result_template": (
            "show the cooking process and finished {use_context} result clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak masak {use_context}?",
                "demo_line": "Tabur {product_reference} dan gaul rata.",
                "benefit_line": "{benefit_evidence}.",
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
            10: {
                "hook_line": (
                    "Nak masak {use_context} dengan langkah yang ringkas?"
                ),
                "demo_line": (
                    "Masukkan {product_reference}, kemudian gaul sampai rata."
                ),
                "benefit_line": "{benefit_evidence}.",
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
            16: {
                "hook_line": (
                    "Nak sediakan {use_context} dengan langkah rempah yang jelas?"
                ),
                "demo_line": (
                    "Masukkan {product_reference}, gaul rata dan teruskan proses "
                    "memasak."
                ),
                "benefit_line": (
                    "{benefit_evidence} sambil proses masak mudah diikuti."
                ),
                "cta_line": "{cta_prompt}",
                "overlay_text": "{overlay_label}",
            },
        },
    },
    ("baby_care", "baby_diaper", "BABY_DIAPER"): {
        "copy_strategy_id": "P4_BABY_DIAPER_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2),
        "scene_result_template": (
            "show the diaper structure, fastener, and size marking clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat struktur lampin?",
                "demo_line": "Buka dan tunjuk pengikatnya.",
                "benefit_line": "Butiran saiz mudah dilihat.",
                "cta_line": "Semak pilihan saiz.",
                "overlay_text": "STRUKTUR LAMPIN",
            },
            10: {
                "hook_line": "Nak lihat struktur lampin dengan jelas?",
                "demo_line": "Buka, bentang dan tunjuk pengikatnya.",
                "benefit_line": "Tanda saiz mudah dilihat.",
                "cta_line": "Semak pilihan saiz.",
                "overlay_text": "STRUKTUR DAN SAIZ",
            },
            16: {
                "hook_line": "Nak periksa struktur lampin sebelum pilih saiz?",
                "demo_line": (
                    "Keluarkan satu, bentang di meja dan tunjuk pengikatnya."
                ),
                "benefit_line": "Struktur dan tanda saiz dapat dilihat dengan jelas.",
                "cta_line": "Semak pilihan saiz pada pek.",
                "overlay_text": "SEMAK STRUKTUR DAN SAIZ",
            },
        },
    },
    (
        "electronics_accessory",
        "electronics_accessory",
        "ELECTRONICS_ACCESSORY",
    ): {
        "copy_strategy_id": "P4_ELECTRONICS_ACCESSORY_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 2),
        "scene_result_template": (
            "show the connector, control, and normal storage method clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Perlu aksesori sambungan?",
                "demo_line": "Tunjuk penyambung dan cara simpan.",
                "benefit_line": "Butiran sambungan mudah dilihat.",
                "cta_line": "Semak jenis yang sesuai.",
                "overlay_text": "SEMAK JENIS SAMBUNGAN",
            },
            10: {
                "hook_line": "Nak semak aksesori sebelum digunakan?",
                "demo_line": "Tunjuk penyambung, kawalan dan cara simpan.",
                "benefit_line": "Butiran sambungan mudah dilihat.",
                "cta_line": "Semak jenis yang sesuai.",
                "overlay_text": "BUTIRAN AKSESORI",
            },
            16: {
                "hook_line": "Nak kenali jenis aksesori dengan jelas?",
                "demo_line": (
                    "Tunjuk penyambung dan kawalan, kemudian simpan dengan kemas."
                ),
                "benefit_line": "Bentuk sambungan dan cara simpan dapat dilihat jelas.",
                "cta_line": "Semak keserasian dalam arahan produk.",
                "overlay_text": "SEMAK SAMBUNGAN DAN ARAHAN",
            },
        },
    },
    (
        "electronics_accessory",
        "electronics_wearable",
        "ELECTRONICS_SMALL_DEVICE",
    ): {
        "copy_strategy_id": "P4_ELECTRONICS_WEARABLE_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2),
        "scene_result_template": (
            "show the device controls, indicator, and ports clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat kawalan peranti?",
                "demo_line": "Tunjuk butang, indikator dan port.",
                "benefit_line": "Butiran peranti mudah dilihat.",
                "cta_line": "Semak arahan produk.",
                "overlay_text": "KAWALAN DAN PORT",
            },
            10: {
                "hook_line": "Nak kenali kawalan peranti?",
                "demo_line": "Buka pek dan tunjuk butang serta indikator.",
                "benefit_line": "Butiran peranti mudah dilihat.",
                "cta_line": "Semak arahan produk.",
                "overlay_text": "SEMAK KAWALAN PERANTI",
            },
            16: {
                "hook_line": "Nak lihat kawalan utama sebelum guna peranti?",
                "demo_line": (
                    "Keluarkan dari pek, tekan kawalan yang betul dan tunjuk "
                    "indikator."
                ),
                "benefit_line": "Butang, indikator dan port dapat dilihat jelas.",
                "cta_line": "Ikut arahan penggunaan produk.",
                "overlay_text": "KAWALAN PERANTI YANG JELAS",
            },
        },
    },
    ("fashion_apparel", "apparel", "APPAREL"): {
        "copy_strategy_id": "P4_APPAREL_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 2, 3),
        "scene_result_template": (
            "show the garment fabric, seams, hem, and silhouette clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat potongan pakaian?",
                "demo_line": "Gantung dan tunjuk jahitan serta tekstur.",
                "benefit_line": "Butiran fabrik mudah dilihat.",
                "cta_line": "Semak pilihan pakaian.",
                "overlay_text": "POTONGAN DAN FABRIK",
            },
            10: {
                "hook_line": "Nak lihat potongan pakaian dengan jelas?",
                "demo_line": "Gantung, tunjuk jahitan, kelim dan tekstur.",
                "benefit_line": "Butiran fabrik mudah dilihat.",
                "cta_line": "Semak pilihan pakaian.",
                "overlay_text": "BUTIRAN PAKAIAN",
            },
            16: {
                "hook_line": "Nak periksa potongan dan fabrik sebelum pilih?",
                "demo_line": (
                    "Gantung pakaian, tunjuk jahitan, kelim dan tekstur kain."
                ),
                "benefit_line": "Siluet dan butiran fabrik dapat dilihat dengan jelas.",
                "cta_line": "Semak pilihan saiz dan pakaian.",
                "overlay_text": "SEMAK POTONGAN DAN FABRIK",
            },
        },
    },
    ("fashion_apparel", "modestwear", "MODESTWEAR"): {
        "copy_strategy_id": "P4_MODESTWEAR_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2),
        "scene_result_template": (
            "show the natural drape, coverage, and fabric edge clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat jatuhan kain?",
                "demo_line": "Bentang dan tunjuk tepi serta tekstur.",
                "benefit_line": "Butiran kain mudah dilihat.",
                "cta_line": "Semak pilihan warna.",
                "overlay_text": "JATUHAN DAN TEKSTUR",
            },
            10: {
                "hook_line": "Nak lihat jatuhan modestwear dengan jelas?",
                "demo_line": "Bentang, tunjuk liputan dan tekstur tepi.",
                "benefit_line": "Butiran kain mudah dilihat.",
                "cta_line": "Semak pilihan warna.",
                "overlay_text": "BUTIRAN MODESTWEAR",
            },
            16: {
                "hook_line": "Nak periksa jatuhan dan liputan sebelum pilih?",
                "demo_line": (
                    "Bentang secara semula jadi, tunjuk sisi dan tekstur tepi."
                ),
                "benefit_line": "Jatuhan serta butiran kain dapat dilihat dengan jelas.",
                "cta_line": "Semak pilihan warna dan gaya.",
                "overlay_text": "SEMAK JATUHAN DAN LIPUTAN",
            },
        },
    },
    ("fashion_apparel", "sportswear", "SPORTSWEAR"): {
        "copy_strategy_id": "P4_SPORTSWEAR_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (2,),
        "scene_result_template": (
            "show the waistband, seams, and fabric detail clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat pakaian sukan?",
                "demo_line": "Tunjuk pinggang, jahitan dan fabrik.",
                "benefit_line": "Butiran pakaian mudah dilihat.",
                "cta_line": "Semak pilihan saiz.",
                "overlay_text": "BUTIRAN PAKAIAN SUKAN",
            },
            10: {
                "hook_line": "Nak lihat pakaian sukan dengan jelas?",
                "demo_line": "Tunjuk pinggang, jahitan dan tekstur fabrik.",
                "benefit_line": "Butiran pakaian mudah dilihat.",
                "cta_line": "Semak pilihan saiz.",
                "overlay_text": "JAHITAN DAN FABRIK",
            },
            16: {
                "hook_line": "Nak periksa butiran pakaian sukan sebelum pilih?",
                "demo_line": (
                    "Tunjuk bahagian pinggang, jahitan dan tekstur fabrik."
                ),
                "benefit_line": "Potongan dan butiran kain dapat dilihat dengan jelas.",
                "cta_line": "Semak pilihan saiz pada produk.",
                "overlay_text": "SEMAK PINGGANG DAN JAHITAN",
            },
        },
    },
    ("food_cooking", "sambal", "PACKAGED_SAUCE_SAMBAL"): {
        "copy_strategy_id": "P4_SAMBAL_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2),
        "scene_result_template": (
            "show a normal sambal serving and the finished dish clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak tambah sambal pada hidangan?",
                "demo_line": "Buka, sudukan sedikit dan gaul.",
                "benefit_line": "Cara hidangan mudah dilihat.",
                "cta_line": "Semak pilihan sambal.",
                "overlay_text": "CARA HIDANG SAMBAL",
            },
            10: {
                "hook_line": "Nak lihat cara hidang sambal?",
                "demo_line": "Buka pek, sudukan sedikit dan gaul.",
                "benefit_line": "Bahagian hidangan mudah dilihat.",
                "cta_line": "Semak pilihan sambal.",
                "overlay_text": "SAMBAL UNTUK HIDANGAN",
            },
            16: {
                "hook_line": "Nak lihat sambal digunakan dalam hidangan?",
                "demo_line": (
                    "Buka pek dengan bersih, sudukan bahagian biasa dan gaul."
                ),
                "benefit_line": "Cara penggunaan dan hasil hidangan dapat dilihat jelas.",
                "cta_line": "Semak pilihan sambal pada produk.",
                "overlay_text": "SEMAK CARA HIDANG SAMBAL",
            },
        },
    },
    ("food_cooking", "sauce", "PACKAGED_SAUCE_SAMBAL"): {
        "copy_strategy_id": "P4_SAUCE_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2),
        "scene_result_template": (
            "show a normal sauce serving and the finished dish clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Sos untuk hidangan hari ini?",
                "demo_line": "Buka, sudukan sedikit dan gaul.",
                "benefit_line": "Cara hidangan mudah dilihat.",
                "cta_line": "Semak pilihan sos.",
                "overlay_text": "CARA HIDANG SOS",
            },
            10: {
                "hook_line": "Nak lihat cara guna sos?",
                "demo_line": "Buka pek, sudukan sedikit dan gaul.",
                "benefit_line": "Bahagian hidangan mudah dilihat.",
                "cta_line": "Semak pilihan sos.",
                "overlay_text": "SOS UNTUK HIDANGAN",
            },
            16: {
                "hook_line": "Nak lihat sos digunakan dalam hidangan?",
                "demo_line": (
                    "Buka pek dengan bersih, sudukan bahagian biasa dan gaul."
                ),
                "benefit_line": "Cara penggunaan dan hasil hidangan dapat dilihat jelas.",
                "cta_line": "Semak pilihan sos pada produk.",
                "overlay_text": "SEMAK CARA HIDANG SOS",
            },
        },
    },
    ("food_ready_to_eat", "instant_food", "PACKAGED_FOOD"): {
        "copy_strategy_id": "P4_INSTANT_FOOD_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 2),
        "scene_result_template": (
            "show the intact pack and intended meal context clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak sediakan makanan segera?",
                "demo_line": "Buka pek dan ikut arahan penyediaan.",
                "benefit_line": "Langkah penyediaan mudah dilihat.",
                "cta_line": "Semak pilihan pek.",
                "overlay_text": "IKUT ARAHAN PENYEDIAAN",
            },
            10: {
                "hook_line": "Nak lihat langkah makanan segera?",
                "demo_line": "Buka pek bersih dan ikut arahan penyediaan.",
                "benefit_line": "Langkah penggunaan mudah dilihat.",
                "cta_line": "Semak pilihan pek.",
                "overlay_text": "LANGKAH MAKANAN SEGERA",
            },
            16: {
                "hook_line": "Nak lihat cara sediakan makanan segera?",
                "demo_line": (
                    "Tunjuk pek yang utuh, buka bersih dan ikut arahan produk."
                ),
                "benefit_line": "Langkah penyediaan dapat dilihat dengan jelas.",
                "cta_line": "Semak arahan pada pek produk.",
                "overlay_text": "SEMAK ARAHAN PADA PEK",
            },
        },
    },
    ("food_ready_to_eat", "packaged_food", "PACKAGED_FOOD"): {
        "copy_strategy_id": "P4_PACKAGED_FOOD_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 2),
        "scene_result_template": (
            "show the intact pack and product-appropriate meal context clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat cara penggunaan?",
                "demo_line": "Buka pek dan ikut arahan produk.",
                "benefit_line": "Langkah penggunaan mudah dilihat.",
                "cta_line": "Semak arahan pek.",
                "overlay_text": "IKUT ARAHAN PRODUK",
            },
            10: {
                "hook_line": "Nak lihat penggunaan makanan berpek?",
                "demo_line": "Tunjuk pek utuh dan ikut arahan produk.",
                "benefit_line": "Konteks hidangan mudah dilihat.",
                "cta_line": "Semak arahan pek.",
                "overlay_text": "ARAHAN MAKANAN BERPEK",
            },
            16: {
                "hook_line": "Nak lihat cara guna makanan berpek?",
                "demo_line": (
                    "Tunjuk pek yang utuh, buka bersih dan ikut arahan produk."
                ),
                "benefit_line": "Langkah penggunaan dapat dilihat dengan jelas.",
                "cta_line": "Semak arahan pada pek produk.",
                "overlay_text": "SEMAK PEK DAN ARAHAN",
            },
        },
    },
    ("fragrance", "fragrance", "FRAGRANCE"): {
        "copy_strategy_id": "P4_FRAGRANCE_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 3),
        "scene_result_template": (
            "show one wrist spritz and the bottle details clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat cara guna wangian?",
                "demo_line": "Sembur sekali pada pergelangan tangan.",
                "benefit_line": "Botol dan muncung mudah dilihat.",
                "cta_line": "Semak pilihan wangian.",
                "overlay_text": "SATU SEMBURAN PADA PERGELANGAN",
            },
            10: {
                "hook_line": "Nak lihat penggunaan wangian dengan jelas?",
                "demo_line": "Sembur sekali pada pergelangan dari jarak biasa.",
                "benefit_line": "Butiran botol mudah dilihat.",
                "cta_line": "Semak pilihan wangian.",
                "overlay_text": "CARA GUNA WANGIAN",
            },
            16: {
                "hook_line": "Nak lihat cara penggunaan wangian yang ringkas?",
                "demo_line": (
                    "Tunjuk muncung dan label, kemudian sembur sekali pada "
                    "pergelangan."
                ),
                "benefit_line": "Botol dan cara penggunaan dapat dilihat jelas.",
                "cta_line": "Semak arahan pada produk wangian.",
                "overlay_text": "SEMAK BOTOL DAN ARAHAN",
            },
        },
    },
    ("home_storage", "storage_organizer", "HOUSEHOLD_STORAGE"): {
        "copy_strategy_id": "P4_STORAGE_ORGANIZER_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 3),
        "scene_result_template": (
            "show suitable items placed in the organizer without overloading it"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak susun barang dengan jelas?",
                "demo_line": "Buka dan isi ruang yang sesuai.",
                "benefit_line": "Bahagian simpanan mudah dilihat.",
                "cta_line": "Semak pilihan penyusun.",
                "overlay_text": "RUANG SIMPANAN YANG JELAS",
            },
            10: {
                "hook_line": "Nak lihat ruang penyusun barang?",
                "demo_line": "Buka, isi ruang sesuai dan letak kemas.",
                "benefit_line": "Bahagian simpanan mudah dilihat.",
                "cta_line": "Semak pilihan penyusun.",
                "overlay_text": "SEMAK RUANG PENYUSUN",
            },
            16: {
                "hook_line": "Nak lihat cara guna penyusun tanpa berlebihan?",
                "demo_line": (
                    "Buka ruang, letak barang yang sesuai dan susun di rak."
                ),
                "benefit_line": "Kompartmen dan susunan dapat dilihat dengan jelas.",
                "cta_line": "Semak saiz serta arahan produk.",
                "overlay_text": "SUSUN IKUT RUANG PRODUK",
            },
        },
    },
    (
        "household_cleaning",
        "household_cleaner",
        "HOUSEHOLD_CLEANER",
    ): {
        "copy_strategy_id": "P4_HOUSEHOLD_CLEANER_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2),
        "scene_result_template": (
            "show product-appropriate surface cleaning and safe closure clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat langkah pembersihan?",
                "demo_line": "Guna sedikit pada permukaan yang sesuai.",
                "benefit_line": "Lap dan tutup semula muncung.",
                "cta_line": "Semak arahan produk.",
                "overlay_text": "GUNA PADA PERMUKAAN SESUAI",
            },
            10: {
                "hook_line": "Nak lihat cara guna pencuci?",
                "demo_line": "Guna sedikit, lap permukaan sesuai dan tutup.",
                "benefit_line": "Langkah penggunaan mudah dilihat.",
                "cta_line": "Semak arahan produk.",
                "overlay_text": "IKUT ARAHAN PENCUCI",
            },
            16: {
                "hook_line": "Nak lihat langkah penggunaan pencuci yang jelas?",
                "demo_line": (
                    "Guna amaun sesuai pada permukaan yang betul, kemudian lap."
                ),
                "benefit_line": "Muncung ditutup semula selepas digunakan.",
                "cta_line": "Semak arahan keselamatan produk.",
                "overlay_text": "PERMUKAAN SESUAI SAHAJA",
            },
        },
    },
    ("household_laundry", "detergent", "LAUNDRY_DETERGENT"): {
        "copy_strategy_id": "P4_LAUNDRY_DETERGENT_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 3),
        "scene_result_template": (
            "show normal detergent measurement and directed washer use clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat sukatan detergen?",
                "demo_line": "Sukat dan tuang mengikut arahan.",
                "benefit_line": "Langkah penggunaan mudah dilihat.",
                "cta_line": "Semak arahan label.",
                "overlay_text": "SUKAT IKUT ARAHAN",
            },
            10: {
                "hook_line": "Nak lihat cara sukat detergen?",
                "demo_line": "Sukat, tuang ke ruang yang diarahkan dan tutup.",
                "benefit_line": "Langkah penggunaan mudah dilihat.",
                "cta_line": "Semak arahan label.",
                "overlay_text": "ARAHAN DETERGEN",
            },
            16: {
                "hook_line": "Nak lihat langkah penggunaan detergen yang jelas?",
                "demo_line": (
                    "Sukat dengan penutup, tuang ke ruang mesin yang diarahkan."
                ),
                "benefit_line": "Pek ditutup dan disimpan semula selepas digunakan.",
                "cta_line": "Semak sukatan pada label produk.",
                "overlay_text": "SUKAT DAN SIMPAN DENGAN BETUL",
            },
        },
    },
    ("household_laundry", "softener", "FABRIC_SOFTENER"): {
        "copy_strategy_id": "P4_FABRIC_SOFTENER_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2),
        "scene_result_template": (
            "show normal softener measurement and directed compartment use clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Nak lihat sukatan pelembut?",
                "demo_line": "Sukat dan tuang ke ruang pelembut.",
                "benefit_line": "Langkah penggunaan mudah dilihat.",
                "cta_line": "Semak arahan label.",
                "overlay_text": "RUANG PELEMBUT SAHAJA",
            },
            10: {
                "hook_line": "Nak lihat cara guna pelembut?",
                "demo_line": "Sukat, tuang ke ruang pelembut dan tutup.",
                "benefit_line": "Langkah penggunaan mudah dilihat.",
                "cta_line": "Semak arahan label.",
                "overlay_text": "ARAHAN PELEMBUT FABRIK",
            },
            16: {
                "hook_line": "Nak lihat langkah penggunaan pelembut yang jelas?",
                "demo_line": (
                    "Sukat amaun sesuai, tuang ke ruang pelembut dan tutup botol."
                ),
                "benefit_line": "Cara penggunaan dapat dilihat dengan jelas.",
                "cta_line": "Semak sukatan pada label produk.",
                "overlay_text": "SUKAT IKUT LABEL PRODUK",
            },
        },
    },
    (
        "traditional_wellness",
        "traditional_herbal_oil",
        "TRADITIONAL_HERBAL_OIL",
    ): {
        "copy_strategy_id": "P4_TRADITIONAL_HERBAL_OIL_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2, 3, 4),
        "scene_result_template": (
            "show the label, small external-use amount, gentle routine, and "
            "closed-bottle storage clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Rutin warisan untuk harian.",
                "demo_line": "Sapu sedikit ikut label.",
                "benefit_line": "Mudah dibawa dan disimpan.",
                "cta_line": "Semak arahan sebelum guna.",
                "overlay_text": "RUTIN LUARAN WARISAN",
            },
            10: {
                "hook_line": "Rutin warisan dalam format mudah bawa.",
                "demo_line": "Pegang botol, semak label, sapu sedikit.",
                "benefit_line": "Untuk penjagaan luaran harian.",
                "cta_line": "Ikut arahan pada label.",
                "overlay_text": "SEMAK LABEL SEBELUM GUNA",
            },
            16: {
                "hook_line": (
                    "Warisan harian dalam satu rutin luaran yang ringkas."
                ),
                "demo_line": (
                    "Pegang botol, buka penutup dan sapu sedikit pada lengan."
                ),
                "benefit_line": (
                    "Urut lembut, kemudian tutup dan simpan botol dengan kemas."
                ),
                "cta_line": "Semak label sebelum guna.",
                "overlay_text": "SAPU SEDIKIT IKUT LABEL",
            },
        },
    },
    (
        "traditional_wellness",
        "herbal_roll_on_oil",
        "HERBAL_ROLL_ON_OIL",
    ): {
        "copy_strategy_id": "P4_HERBAL_ROLL_ON_OIL_PRODUCT_TYPE_V1",
        "source_strategy": "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY",
        "scene_action_indices": (0, 1, 2, 4),
        "scene_result_template": (
            "show the label, intact applicator, controlled external roll, and "
            "capped upright storage clearly"
        ),
        "scripts": {
            8: {
                "hook_line": "Rutin ringkas dalam satu roll-on.",
                "demo_line": "Roll sedikit pada pergelangan.",
                "benefit_line": "Mudah dibawa setiap hari.",
                "cta_line": "Semak label sebelum guna.",
                "overlay_text": "ROLL-ON UNTUK RUTIN LUARAN",
            },
            10: {
                "hook_line": "Roll-on ringkas untuk rutin luaran harian.",
                "demo_line": "Tunjuk label dan roll sedikit pada pergelangan.",
                "benefit_line": "Mudah dibawa dan disimpan.",
                "cta_line": "Semak arahan sebelum guna.",
                "overlay_text": "FORMAT MUDAH BAWA",
            },
            16: {
                "hook_line": (
                    "Format roll-on menjadikan rutin luaran lebih ringkas."
                ),
                "demo_line": (
                    "Tunjuk label, buka penutup dan roll sedikit pada lengan."
                ),
                "benefit_line": (
                    "Tutup semula dan simpan tegak dalam beg selepas guna."
                ),
                "cta_line": "Ikut arahan pada label.",
                "overlay_text": "ROLL SEDIKIT IKUT LABEL",
            },
        },
    },
    ("baby_care", "baby_wipes", "BABY_WIPES"): _fixed_strategy(
        copy_strategy_id="P4_BABY_WIPES_PRODUCT_TYPE_V1",
        scene_result_template="show the pack, sheet size, and reseal method clearly",
        hook_line="Tengok saiz helaian tisu.",
        demo_line="Buka dan tarik satu helai.",
        benefit_line="Tutup semula pek dengan kemas.",
        cta_line="Semak saiz pek.",
        overlay_text="HELAIAN DAN PEK",
    ),
    (
        "sensitive_wellness",
        "male_wellness",
        "SENSITIVE_WELLNESS",
    ): _fixed_strategy(
        copy_strategy_id="P4_MALE_WELLNESS_PRODUCT_TYPE_V1",
        scene_result_template="show sealed packaging and label directions clearly",
        hook_line="Semak label sebelum pilih.",
        demo_line="Tunjuk pek dan arahan hidangan.",
        benefit_line="Ikut sukatan pada label.",
        cta_line="Baca butiran produk.",
        overlay_text="SEMAK LABEL",
    ),
    (
        "sensitive_wellness",
        "female_wellness",
        "SENSITIVE_WELLNESS",
    ): _fixed_strategy(
        copy_strategy_id="P4_FEMALE_WELLNESS_PRODUCT_TYPE_V1",
        scene_result_template="show sealed packaging and label directions clearly",
        hook_line="Semak label sebelum pilih.",
        demo_line="Tunjuk pek dan arahan hidangan.",
        benefit_line="Ikut sukatan pada label.",
        cta_line="Baca butiran produk.",
        overlay_text="SEMAK LABEL",
    ),
    (
        "home_equipment",
        "blender",
        "ELECTRONICS_SMALL_DEVICE",
    ): _fixed_strategy(
        copy_strategy_id="P4_BLENDER_PRODUCT_TYPE_V1",
        scene_result_template="show the controls, jar, lid, and base clearly",
        hook_line="Tengok komponen pengisar.",
        demo_line="Tunjuk balang, penutup dan kawalan.",
        benefit_line="Butiran mesin mudah dilihat.",
        cta_line="Semak arahan produk.",
        overlay_text="KOMPONEN PENGISAR",
    ),
    (
        "home_equipment",
        "chopper",
        "ELECTRONICS_SMALL_DEVICE",
    ): _fixed_strategy(
        copy_strategy_id="P4_CHOPPER_PRODUCT_TYPE_V1",
        scene_result_template="show the controls, bowl, lid, and blade housing clearly",
        hook_line="Tengok komponen pencincang.",
        demo_line="Tunjuk mangkuk, penutup dan kawalan.",
        benefit_line="Butiran mesin mudah dilihat.",
        cta_line="Semak arahan produk.",
        overlay_text="KOMPONEN PENCINCANG",
    ),
    ("fashion_apparel", "bottom_apparel", "BOTTOM_APPAREL"): _fixed_strategy(
        copy_strategy_id="P4_BOTTOM_APPAREL_PRODUCT_TYPE_V1",
        scene_result_template="show the waistband, pockets, seams, and hem clearly",
        hook_line="Tengok potongan seluar.",
        demo_line="Tunjuk pinggang, poket dan labuh.",
        benefit_line="Butiran fabrik mudah dilihat.",
        cta_line="Semak ukuran saiz.",
        overlay_text="POTONGAN DAN SAIZ",
    ),
    (
        "beauty_personal_care",
        "body_cleanser",
        "BODY_CLEANSER",
    ): _fixed_strategy(
        copy_strategy_id="P4_BODY_CLEANSER_PRODUCT_TYPE_V1",
        scene_result_template="show the dispenser, texture, and label directions clearly",
        hook_line="Tengok tekstur pencuci badan.",
        demo_line="Pam sedikit pada tapak tangan.",
        benefit_line="Guna ikut arahan label.",
        cta_line="Semak saiz produk.",
        overlay_text="TEKSTUR DAN SUKATAN",
    ),
    ("beauty_skincare", "facial_cleanser", "FACIAL_CLEANSER"): _fixed_strategy(
        copy_strategy_id="P4_FACIAL_CLEANSER_PRODUCT_TYPE_V1",
        scene_result_template="show the texture, small amount, and rinse setup clearly",
        hook_line="Tengok sukatan pencuci muka.",
        demo_line="Ambil sedikit pada hujung jari.",
        benefit_line="Guna ikut arahan label.",
        cta_line="Semak cara guna.",
        overlay_text="SUKATAN PENCUCI MUKA",
    ),
    (
        "beauty_makeup",
        "complexion_makeup",
        "COMPLEXION_MAKEUP",
    ): _fixed_strategy(
        copy_strategy_id="P4_COMPLEXION_MAKEUP_PRODUCT_TYPE_V1",
        scene_result_template="show the shade, texture, and controlled swatch clearly",
        hook_line="Nak semak shade?",
        demo_line="Swatch sedikit dekat garis rahang.",
        benefit_line="Padanan warna mudah dilihat.",
        cta_line="Semak pilihan shade.",
        overlay_text="SEMAK SHADE",
    ),
    ("beauty_makeup", "nail_color", "NAIL_COLOR"): _fixed_strategy(
        copy_strategy_id="P4_NAIL_COLOR_PRODUCT_TYPE_V1",
        scene_result_template="show the brush, shade, and single-nail coat clearly",
        hook_line="Tengok warna satu sapuan.",
        demo_line="Tunjuk berus dan satu lapisan.",
        benefit_line="Shade mudah dilihat.",
        cta_line="Semak pilihan warna.",
        overlay_text="WARNA SATU SAPUAN",
    ),
    ("beauty_skincare", "facial_serum", "FACIAL_SERUM"): _fixed_strategy(
        copy_strategy_id="P4_FACIAL_SERUM_PRODUCT_TYPE_V1",
        scene_result_template="show the dropper, texture, and controlled amount clearly",
        hook_line="Tengok tekstur serum.",
        demo_line="Tunjuk satu titis terkawal.",
        benefit_line="Guna ikut arahan label.",
        cta_line="Semak ramuan produk.",
        overlay_text="SATU TITIS TERKAWAL",
    ),
    ("beauty_makeup", "mascara", "MASCARA"): _fixed_strategy(
        copy_strategy_id="P4_MASCARA_PRODUCT_TYPE_V1",
        scene_result_template="show the wand, brush, and controlled lash application clearly",
        hook_line="Tengok bentuk berus maskara.",
        demo_line="Tunjuk berus dan satu sapuan.",
        benefit_line="Butiran aplikator mudah dilihat.",
        cta_line="Semak jenis berus.",
        overlay_text="BENTUK BERUS",
    ),
    ("beauty_makeup", "eyeliner", "EYELINER"): _fixed_strategy(
        copy_strategy_id="P4_EYELINER_PRODUCT_TYPE_V1",
        scene_result_template="show the tip and controlled external line clearly",
        hook_line="Tengok hujung eyeliner.",
        demo_line="Swatch satu garisan pada tangan.",
        benefit_line="Bentuk garisan mudah dilihat.",
        cta_line="Semak warna produk.",
        overlay_text="HUJUNG DAN GARISAN",
    ),
    (
        "sensitive_wellness",
        "wellness_supplement",
        "WELLNESS_SUPPLEMENT",
    ): _fixed_strategy(
        copy_strategy_id="P4_WELLNESS_SUPPLEMENT_PRODUCT_TYPE_V1",
        scene_result_template="show the seal, serving directions, and label clearly",
        hook_line="Semak label sebelum ambil.",
        demo_line="Tunjuk pek dan arahan hidangan.",
        benefit_line="Ikut sukatan pada label.",
        cta_line="Baca butiran produk.",
        overlay_text="SEMAK LABEL",
    ),
    (
        "food_ready_to_eat",
        "packaged_snack",
        "PACKAGED_SNACK",
    ): _fixed_strategy(
        copy_strategy_id="P4_PACKAGED_SNACK_PRODUCT_TYPE_V1",
        scene_result_template="show the seal, texture, and normal portion clearly",
        hook_line="Tengok isi pek snek.",
        demo_line="Buka dan tuang satu hidangan.",
        benefit_line="Tekstur mudah dilihat.",
        cta_line="Semak rasa produk.",
        overlay_text="ISI DAN HIDANGAN",
    ),
    ("pet_care", "pet_food", "PET_FOOD"): _fixed_strategy(
        copy_strategy_id="P4_PET_FOOD_PRODUCT_TYPE_V1",
        scene_result_template="show the species label and measured pet serving clearly",
        hook_line="Semak label makanan haiwan.",
        demo_line="Sukat ke dalam mangkuk bersih.",
        benefit_line="Ikut panduan hidangan.",
        cta_line="Semak umur haiwan.",
        overlay_text="PANDUAN HIDANGAN",
    ),
    (
        "food_beverage",
        "packaged_beverage",
        "PACKAGED_BEVERAGE",
    ): _fixed_strategy(
        copy_strategy_id="P4_PACKAGED_BEVERAGE_PRODUCT_TYPE_V1",
        scene_result_template="show the seal, label, and normal pour clearly",
        hook_line="Tengok cara hidang minuman.",
        demo_line="Buka dan tuang satu hidangan.",
        benefit_line="Warna mudah dilihat.",
        cta_line="Semak rasa produk.",
        overlay_text="SATU HIDANGAN",
    ),
    (
        "food_cooking",
        "pantry_ingredient",
        "PANTRY_INGREDIENT",
    ): _fixed_strategy(
        copy_strategy_id="P4_PANTRY_INGREDIENT_PRODUCT_TYPE_V1",
        scene_result_template="show the label, measured ingredient, and dish clearly",
        hook_line="Semak bahan sebelum masak.",
        demo_line="Sukat ikut resipi hidangan.",
        benefit_line="Langkah masak mudah diikuti.",
        cta_line="Semak saiz pek.",
        overlay_text="SUKAT IKUT RESIPI",
    ),
    ("home_textiles", "bedding", "BEDDING"): _fixed_strategy(
        copy_strategy_id="P4_BEDDING_PRODUCT_TYPE_V1",
        scene_result_template="show the size label, fabric, seams, and bed setup clearly",
        hook_line="Tengok saiz set cadar.",
        demo_line="Bentang dan tunjuk jahitannya.",
        benefit_line="Butiran fabrik mudah dilihat.",
        cta_line="Semak ukuran katil.",
        overlay_text="SAIZ DAN FABRIK",
    ),
    ("home_textiles", "rug_mat", "RUG_MAT"): _fixed_strategy(
        copy_strategy_id="P4_RUG_MAT_PRODUCT_TYPE_V1",
        scene_result_template="show the size, surface, edge, and backing clearly",
        hook_line="Tengok saiz tikar.",
        demo_line="Bentang dan tunjuk permukaannya.",
        benefit_line="Tepi mudah dilihat.",
        cta_line="Semak ukuran ruang.",
        overlay_text="SAIZ DAN PERMUKAAN",
    ),
    ("books_media", "book", "BOOK"): _fixed_strategy(
        copy_strategy_id="P4_BOOK_PRODUCT_TYPE_V1",
        scene_result_template="show the cover, contents, and page layout clearly",
        hook_line="Tengok kandungan buku.",
        demo_line="Buka kulit dan beberapa halaman.",
        benefit_line="Susun atur mudah dilihat.",
        cta_line="Semak tajuk buku.",
        overlay_text="KULIT DAN KANDUNGAN",
    ),
    ("home_equipment", "home_fan", "HOME_FAN"): _fixed_strategy(
        copy_strategy_id="P4_HOME_FAN_PRODUCT_TYPE_V1",
        scene_result_template="show the guard, base, controls, and indicator clearly",
        hook_line="Tengok kawalan kipas.",
        demo_line="Tunjuk pelindung, tapak dan butang.",
        benefit_line="Butiran mesin mudah dilihat.",
        cta_line="Semak arahan produk.",
        overlay_text="KAWALAN DAN TAPAK",
    ),
    (
        "home_equipment",
        "vacuum_cleaner",
        "VACUUM_CLEANER",
    ): _fixed_strategy(
        copy_strategy_id="P4_VACUUM_CLEANER_PRODUCT_TYPE_V1",
        scene_result_template="show the nozzle, bin, filter, and controls clearly",
        hook_line="Tengok aksesori vakum.",
        demo_line="Tunjuk muncung, penapis dan kawalan.",
        benefit_line="Komponen mudah dilihat.",
        cta_line="Semak arahan produk.",
        overlay_text="AKSESORI DAN KAWALAN",
    ),
    ("home_equipment", "vacuum_sealer", "VACUUM_SEALER"): _fixed_strategy(
        copy_strategy_id="P4_VACUUM_SEALER_PRODUCT_TYPE_V1",
        scene_result_template="show the controls, compatible bag, and finished seal clearly",
        hook_line="Tengok cara guna sealer.",
        demo_line="Letak beg dan tutup penutup.",
        benefit_line="Hasil seal mudah dilihat.",
        cta_line="Semak jenis beg.",
        overlay_text="CARA LETAK BEG",
    ),
}


_P57_ACTIVATED_COPY_TYPES: Final[
    dict[
        ProductTypeCopyStrategyKey,
        tuple[str, str, str, str, str, str],
    ]
] = {
    ("beauty_skincare", "face_mask", "FACE_MASK"): (
        "show the packet, texture, and controlled external layer clearly",
        "Tengok tekstur masker.",
        "Sapu nipis sambil elakkan mata.",
        "Langkah penggunaan mudah dilihat.",
        "Semak masa pada label.",
        "TEKSTUR MASKER",
    ),
    ("beauty_skincare", "moisturizer", "MOISTURIZER"): (
        "show the dispenser, texture, and small external amount clearly",
        "Tengok tekstur pelembap.",
        "Pam satu sukatan kecil.",
        "Cara penggunaan mudah dilihat.",
        "Semak arahan produk.",
        "SUKATAN KECIL",
    ),
    ("beauty_skincare", "sunscreen", "SUNSCREEN"): (
        "show the visible label and controlled external application clearly",
        "Semak label pelindung matahari.",
        "Sapu mengikut arahan produk.",
        "Butiran penggunaan mudah dilihat.",
        "Rujuk label produk.",
        "SEMAK LABEL",
    ),
    ("beauty_skincare", "eye_treatment", "EYE_TREATMENT"): (
        "show the applicator and controlled outer eye-area amount clearly",
        "Tengok aplikator kawasan mata.",
        "Titik sedikit di kawasan luar.",
        "Sukatan mudah dilihat.",
        "Ikut arahan label.",
        "KAWASAN LUAR SAHAJA",
    ),
    (
        "beauty_makeup",
        "makeup_setting_spray",
        "MAKEUP_SETTING_SPRAY",
    ): (
        "show the nozzle, label-directed distance, and external spray clearly",
        "Semak muncung semburan.",
        "Sembur ikut jarak pada label.",
        "Cara semburan mudah dilihat.",
        "Semak arahan produk.",
        "JARAK SEMBURAN",
    ),
    ("beauty_makeup", "eyebrow_makeup", "EYEBROW_MAKEUP"): (
        "show the applicator, shade, and short eyebrow strokes clearly",
        "Tengok warna kening.",
        "Buat beberapa sapuan pendek.",
        "Bentuk aplikator mudah dilihat.",
        "Semak shade produk.",
        "SAPUAN PENDEK",
    ),
    ("beauty_makeup", "eyeshadow", "EYESHADOW"): (
        "show the palette, clean brush, and one external eyelid shade clearly",
        "Tengok satu shade palet.",
        "Sapu dengan berus bersih.",
        "Warna mudah dilihat.",
        "Semak pilihan shade.",
        "SATU SHADE",
    ),
    (
        "beauty_makeup",
        "false_eyelashes",
        "FALSE_EYELASHES",
    ): (
        "show the lash strip, band, and measured length clearly",
        "Tengok bentuk strip bulu mata.",
        "Ukur tanpa memakai pelekat.",
        "Panjang strip mudah dilihat.",
        "Semak arahan pemasangan.",
        "BENTUK DAN PANJANG",
    ),
    ("beauty_makeup", "face_primer", "FACE_PRIMER"): (
        "show the dispenser, texture, and small external amount clearly",
        "Tengok tekstur primer.",
        "Guna satu sukatan kecil.",
        "Cara ratakan mudah dilihat.",
        "Semak arahan produk.",
        "TEKSTUR PRIMER",
    ),
    ("beauty_makeup", "makeup_set", "MAKEUP_SET"): (
        "show every included item and its matching applicator clearly",
        "Semak kandungan set solekan.",
        "Susun semua item di meja.",
        "Setiap komponen mudah dilihat.",
        "Semak senarai kandungan.",
        "SEMUA KOMPONEN",
    ),
    ("beauty_makeup", "face_powder", "FACE_POWDER"): (
        "show the pan, shade, clean applicator, and light amount clearly",
        "Tengok shade bedak.",
        "Ambil sedikit dengan aplikator.",
        "Tekstur mudah dilihat.",
        "Semak pilihan shade.",
        "SHADE DAN TEKSTUR",
    ),
    ("beauty_personal_care", "body_oil", "BODY_OIL"): (
        "show the bottle, texture, and small adult external amount clearly",
        "Tengok tekstur minyak badan.",
        "Sapu sedikit pada lengan.",
        "Cara penggunaan mudah dilihat.",
        "Semak label produk.",
        "KEGUNAAN LUARAN",
    ),
    (
        "beauty_personal_care",
        "body_exfoliant",
        "BODY_EXFOLIANT",
    ): (
        "show the visible texture and gentle external motion clearly",
        "Tengok tekstur skrub.",
        "Urut perlahan pada kulit luar.",
        "Tekstur mudah dilihat.",
        "Semak kekerapan pada label.",
        "URUT PERLAHAN",
    ),
    ("beauty_personal_care", "deodorant", "DEODORANT"): (
        "show the sealed product, label, and applicator clearly",
        "Semak jenis aplikator deodoran.",
        "Buka dan tutup dengan bersih.",
        "Bentuk aplikator mudah dilihat.",
        "Ikut arahan label.",
        "JENIS APLIKATOR",
    ),
    ("beauty_personal_care", "hair_wash", "HAIR_WASH"): (
        "show the dispenser, controlled amount, and wet-hair step clearly",
        "Tengok sukatan cucian rambut.",
        "Ratakan pada rambut basah.",
        "Langkah cucian mudah dilihat.",
        "Semak arahan bilas.",
        "SUKATAN CUCIAN",
    ),
    ("beauty_personal_care", "hair_color", "HAIR_COLOR"): (
        "show the sealed kit, colour label, and safety instructions clearly",
        "Semak warna kit rambut.",
        "Tunjuk semua komponen tertutup.",
        "Arahan keselamatan mudah dilihat.",
        "Baca panduan ujian tampalan.",
        "KIT DAN ARAHAN",
    ),
    (
        "beauty_personal_care",
        "hair_treatment",
        "HAIR_TREATMENT",
    ): (
        "show the container, texture, and small hair-length amount clearly",
        "Tengok tekstur penjagaan rambut.",
        "Guna sedikit pada rambut.",
        "Cara penggunaan mudah dilihat.",
        "Semak tempoh pada label.",
        "TEKSTUR PENJAGAAN",
    ),
    (
        "beauty_personal_care",
        "makeup_remover",
        "MAKEUP_REMOVER",
    ): (
        "show a clean pad removing one hand swatch clearly",
        "Tengok satu swatch ditanggalkan.",
        "Lap dengan kapas bersih.",
        "Langkah remover mudah dilihat.",
        "Semak arahan produk.",
        "SATU SWATCH",
    ),
    (
        "beauty_personal_care",
        "lip_treatment",
        "LIP_TREATMENT",
    ): (
        "show the applicator and thin external lip layer clearly",
        "Tengok aplikator penjagaan bibir.",
        "Sapu nipis pada bibir luar.",
        "Sukatan mudah dilihat.",
        "Semak ramuan produk.",
        "SAPUAN NIPIS",
    ),
    ("beauty_personal_care", "oral_care", "ORAL_CARE"): (
        "show the label-directed toothbrush amount and normal brushing clearly",
        "Semak sukatan penjagaan mulut.",
        "Letak sedikit pada berus.",
        "Langkah penggunaan mudah dilihat.",
        "Ikut arahan label.",
        "SUKATAN BERUS",
    ),
    (
        "sensitive_wellness",
        "feminine_hygiene",
        "FEMININE_HYGIENE",
    ): (
        "show the sealed pack, size label, and product layers clearly",
        "Semak saiz secara discreet.",
        "Buka satu item di meja.",
        "Lapisan produk mudah dilihat.",
        "Semak arahan pada pek.",
        "SAIZ DAN LAPISAN",
    ),
    ("fashion_apparel", "top_apparel", "TOP_APPAREL"): (
        "show the full top, collar, sleeve, seams, and hem clearly",
        "Tengok potongan baju.",
        "Tunjuk kolar, lengan dan jahitan.",
        "Butiran kain mudah dilihat.",
        "Semak ukuran saiz.",
        "POTONGAN DAN JAHITAN",
    ),
    ("fashion_apparel", "undergarment", "UNDERGARMENT"): (
        "show the flat garment, size label, band, strap, and seams clearly",
        "Semak struktur pakaian dalam.",
        "Bentang tanpa demonstrasi badan.",
        "Label saiz mudah dilihat.",
        "Rujuk carta ukuran.",
        "STRUKTUR DAN SAIZ",
    ),
    ("fashion_apparel", "sleepwear", "SLEEPWEAR"): (
        "show every sleepwear piece, fabric, waistband, and seams clearly",
        "Tengok semua item pakaian tidur.",
        "Bentang dan tunjuk jahitannya.",
        "Butiran kain mudah dilihat.",
        "Rujuk ukuran saiz.",
        "SET PAKAIAN TIDUR",
    ),
    ("fashion_apparel", "dress", "DRESS"): (
        "show the full dress silhouette, neckline, waist, and hem clearly",
        "Tengok siluet dress.",
        "Tunjuk leher, pinggang dan labuh.",
        "Potongan mudah dilihat.",
        "Rujuk ukuran saiz.",
        "SILUET DAN LABUH",
    ),
    ("fashion_footwear", "footwear", "FOOTWEAR"): (
        "show the pair, size label, upper, sole, strap, and fastening clearly",
        "Semak binaan kasut.",
        "Pusing dan tunjuk tapaknya.",
        "Tali dan saiz mudah dilihat.",
        "Rujuk ukuran kaki.",
        "TAPAK DAN SAIZ",
    ),
    ("food_ready_to_eat", "frozen_food", "FROZEN_FOOD"): (
        "show the cold pack, expiry, cooking directions, and cooked portion clearly",
        "Semak pek makanan sejuk.",
        "Masak ikut arahan label.",
        "Langkah penyediaan mudah dilihat.",
        "Semak suhu penyimpanan.",
        "ARAHAN MEMASAK",
    ),
    ("home_textiles", "curtain", "CURTAIN"): (
        "show the panel width, length, heading, and open-close motion clearly",
        "Semak ukuran langsir.",
        "Gantung dan buka satu panel.",
        "Gerakan kain mudah dilihat.",
        "Ukur tingkap dahulu.",
        "LEBAR DAN PANJANG",
    ),
    ("home_improvement", "wall_covering", "WALL_COVERING"): (
        "show the sheet dimensions, pattern repeat, and small sample clearly",
        "Semak ukuran penutup dinding.",
        "Letak satu sampel kecil.",
        "Sambungan corak mudah dilihat.",
        "Ukur dinding dahulu.",
        "UKURAN DAN CORAK",
    ),
    (
        "craft_hobby",
        "knitting_crochet",
        "KNITTING_CROCHET",
    ): (
        "show the yarn label, tool size, and short stitch sample clearly",
        "Semak benang dan alat.",
        "Buat beberapa stitch pendek.",
        "Tekstur benang mudah dilihat.",
        "Padankan saiz alat.",
        "BENANG DAN STITCH",
    ),
}

for _strategy_key, (
    _scene_result,
    _hook,
    _demo,
    _benefit,
    _cta,
    _overlay,
) in _P57_ACTIVATED_COPY_TYPES.items():
    _product_type_group = _strategy_key[1]
    PRODUCT_TYPE_COPY_STRATEGY_REGISTRY[_strategy_key] = _fixed_strategy(
        copy_strategy_id=(
            f"P4_{_product_type_group.upper()}_PRODUCT_TYPE_V1"
        ),
        scene_result_template=_scene_result,
        hook_line=_hook,
        demo_line=_demo,
        benefit_line=_benefit,
        cta_line=_cta,
        overlay_text=_overlay,
    )


_P58_ACTIVATED_COPY_TYPES: dict[
    ProductTypeCopyStrategyKey,
    tuple[str, str, str, str, str, str],
] = {
    ("automotive_care", "car_surface_coating", "CAR_CARE"): (
        "show the label, applicator, compatibility, and small sample panel clearly",
        "Semak label produk penjagaan kereta.",
        "Tunjuk sedikit pada panel sampel.",
        "Cara aplikasi mudah dilihat.",
        "Ikut arahan label.",
        "LABEL DAN APLIKATOR",
    ),
    ("baby_care", "baby_feeding_accessory", "BABY_FEEDING"): (
        "show the feeding component, size, fit, and care label clearly",
        "Semak saiz komponen bayi.",
        "Pasang komponen kosong di meja.",
        "Keserasian bentuk mudah dilihat.",
        "Rujuk arahan pembersihan.",
        "SAIZ DAN KESERASIAN",
    ),
    ("baby_care", "baby_skincare", "BABY_SKINCARE"): (
        "show the sealed pack, age guidance, label, and texture clearly",
        "Semak label produk bayi.",
        "Tunjuk tekstur pada tangan dewasa.",
        "Jumlah dan tekstur mudah dilihat.",
        "Ikut arahan umur pada label.",
        "LABEL DAN TEKSTUR",
    ),
    ("home_textiles", "bath_linen", "BATH_LINEN"): (
        "show the full textile, dimensions, weave, edge, and care label clearly",
        "Semak saiz kain mandian.",
        "Bentang dan tunjuk tenunan.",
        "Ketebalan dan kemasan mudah dilihat.",
        "Rujuk arahan penjagaan.",
        "SAIZ DAN TENUNAN",
    ),
    ("stationery", "sticky_note", "STATIONERY"): (
        "show the sheet count, dimensions, finish, and one desk use clearly",
        "Semak saiz nota.",
        "Tunjuk satu penggunaan di meja.",
        "Bilangan dan format mudah dilihat.",
        "Pilih ikut kegunaan.",
        "SAIZ DAN BILANGAN",
    ),
    ("stationery", "gift_stationery", "STATIONERY"): (
        "show the stationery dimensions, finish, attachment, and pack count clearly",
        "Semak butiran hadiah alat tulis.",
        "Tunjuk satu item di meja.",
        "Kemasan dan saiz mudah dilihat.",
        "Pilih ikut acara.",
        "BUTIRAN HADIAH",
    ),
    ("stationery", "money_packet", "STATIONERY"): (
        "show the packet count, dimensions, flap, and print clearly",
        "Semak saiz sampul.",
        "Buka satu sampul kosong.",
        "Cetakan dan penutup mudah dilihat.",
        "Pilih reka bentuk.",
        "SAIZ DAN CETAKAN",
    ),
    ("fashion_accessory", "brooch", "FASHION_ACCESSORY"): (
        "show the brooch dimensions, finish, back, and fastener clearly",
        "Semak pengikat kerongsang.",
        "Pasang pada sampel kain.",
        "Kemasan depan dan belakang jelas.",
        "Padankan dengan kain.",
        "PENGIKAT DAN KEMASAN",
    ),
    ("health_device", "pregnancy_test", "HEALTH_TEST_DEVICE"): (
        "show the sealed test pack, expiry, components, and leaflet clearly",
        "Semak kit ujian tertutup.",
        "Susun komponen belum digunakan.",
        "Arahan dan tarikh luput mudah dilihat.",
        "Ikut arahan pengilang.",
        "KIT DAN ARAHAN",
    ),
    ("health_device", "health_monitor", "HEALTH_TEST_DEVICE"): (
        "show the sealed monitor, unused components, model, and leaflet clearly",
        "Semak komponen alat pemantauan.",
        "Susun item belum digunakan.",
        "Model dan arahan mudah dilihat.",
        "Ikut arahan pengilang.",
        "KOMPONEN DAN MODEL",
    ),
    ("home_lighting", "outdoor_light", "OUTDOOR_LIGHTING"): (
        "show the housing, controls, mount, charging port, and stated ratings clearly",
        "Semak binaan lampu luar.",
        "Hidupkan seketika tanpa menghala ke mata.",
        "Kawalan dan pemasangan mudah dilihat.",
        "Rujuk rating label.",
        "BINAAN DAN KAWALAN",
    ),
    ("garden_care", "plant_care", "PLANT_CARE"): (
        "show the plant-care label, warnings, and one dry measured amount clearly",
        "Semak sukatan penjagaan tanaman.",
        "Ukur jumlah kering ikut label.",
        "Dos dan amaran mudah dilihat.",
        "Ikut kadar pada label.",
        "SUKATAN DAN AMARAN",
    ),
    ("home_electrical", "power_saver_device", "ELECTRICAL_DEVICE"): (
        "show the unplugged device, plug, rating, certification, and warnings clearly",
        "Semak rating alat elektrik.",
        "Tunjuk binaan tanpa sambungan.",
        "Plug dan amaran mudah dilihat.",
        "Sahkan pensijilan dahulu.",
        "RATING DAN AMARAN",
    ),
    ("household_cleaning", "cleaning_cloth", "CLEANING_TOOL"): (
        "show the material, count, dimensions, texture, and one dry wipe clearly",
        "Semak bahan kain pembersih.",
        "Tunjuk satu lap pada sampel.",
        "Tekstur dan saiz mudah dilihat.",
        "Padankan dengan permukaan.",
        "BAHAN DAN SAIZ",
    ),
    ("kitchen_storage", "food_cover", "FOOD_COVER"): (
        "show the cover sizes, material, and fit on an empty container clearly",
        "Semak saiz penutup makanan.",
        "Pasang pada bekas kosong.",
        "Keanjalan dan muatnya mudah dilihat.",
        "Padankan dengan bekas.",
        "SAIZ DAN MUAT",
    ),
    ("home_decor", "photo_frame", "HOME_DECOR"): (
        "show the frame dimensions, front, back, and mounting method clearly",
        "Semak ukuran bingkai.",
        "Letak pada permukaan sampel.",
        "Bahagian depan dan belakang jelas.",
        "Ukur ruang paparan.",
        "UKURAN DAN PEMASANGAN",
    ),
    ("kitchen_cookware", "pan_wok", "COOKWARE"): (
        "show the empty pan dimensions, base, handle, and compatibility clearly",
        "Semak binaan kuali.",
        "Pusing perkakas kosong.",
        "Dasar dan pemegang mudah dilihat.",
        "Padankan dengan jenis dapur.",
        "DASAR DAN PEMEGANG",
    ),
    ("kitchen_cookware", "grill_pan", "COOKWARE"): (
        "show the empty grill pan dimensions, surface, base, and handle clearly",
        "Semak binaan grill pan.",
        "Pusing perkakas kosong.",
        "Permukaan dan dasar mudah dilihat.",
        "Padankan dengan jenis dapur.",
        "PERMUKAAN DAN DASAR",
    ),
    ("kitchen_drinkware", "insulated_bottle", "DRINKWARE"): (
        "show the empty bottle capacity, lid, seal, straw, and material clearly",
        "Semak kapasiti botol.",
        "Pasang komponen kering.",
        "Penutup dan seal mudah dilihat.",
        "Rujuk arahan penjagaan.",
        "KAPASITI DAN PENUTUP",
    ),
    ("home_lighting", "usb_light", "SMALL_LIGHT"): (
        "show the connector, housing, controls, and brief illumination clearly",
        "Semak penyambung lampu.",
        "Hidupkan pada sumber serasi.",
        "Binaan dan cahaya sebenar jelas.",
        "Padankan voltan.",
        "PENYAMBUNG DAN CAHAYA",
    ),
    ("beauty_makeup", "blush", "BLUSH"): (
        "show the shade, texture, applicator, and one hygienic swatch clearly",
        "Semak shade pemerah pipi.",
        "Tunjuk satu swatch kecil.",
        "Warna dan tekstur mudah dilihat.",
        "Pilih berdasarkan swatch.",
        "SHADE DAN TEKSTUR",
    ),
    ("outdoor_equipment", "headlamp", "OUTDOOR_LIGHTING"): (
        "show the headlamp housing, controls, strap, port, and mode indicator clearly",
        "Semak binaan headlamp.",
        "Hidupkan seketika tanpa menghala ke mata.",
        "Tali dan kawalan mudah dilihat.",
        "Rujuk rating label.",
        "TALI DAN KAWALAN",
    ),
    ("outdoor_equipment", "fishing_reel", "FISHING_GEAR"): (
        "show the reel body, spool, handle, control, and printed rating clearly",
        "Semak mekanisme reel.",
        "Pusing pemegang perlahan.",
        "Spool dan kawalan mudah dilihat.",
        "Padankan dengan setup.",
        "SPOOL DAN KAWALAN",
    ),
    ("fitness_equipment", "pull_up_bar", "FITNESS_EQUIPMENT"): (
        "show the bar, grips, adjustment range, pads, and instructions clearly",
        "Semak bar senaman.",
        "Tunjuk pelarasan tanpa beban.",
        "Grip dan julat saiz mudah dilihat.",
        "Sahkan keserasian pintu.",
        "GRIP DAN PELARASAN",
    ),
    ("automotive_accessory", "phone_mount", "AUTOMOTIVE_ACCESSORY"): (
        "show the mount, joints, pads, controls, and sample attachment clearly",
        "Semak pelekap telefon.",
        "Pasang pada permukaan sampel.",
        "Sendi dan pelarasan mudah dilihat.",
        "Jangan halang pandangan pemandu.",
        "TAPAK DAN SENDI",
    ),
    ("consumer_audio", "wireless_earbuds", "AUDIO_DEVICE"): (
        "show the earbuds, case, controls, ports, and status indicator clearly",
        "Semak komponen audio.",
        "Hidupkan seketika tanpa dipakai.",
        "Port dan indikator mudah dilihat.",
        "Semak keserasian.",
        "KOMPONEN DAN PORT",
    ),
    ("consumer_audio", "radio", "AUDIO_DEVICE"): (
        "show the radio controls, bands, ports, model, and status indicator clearly",
        "Semak kawalan radio.",
        "Hidupkan seketika untuk indikator.",
        "Band dan port mudah dilihat.",
        "Semak spesifikasi model.",
        "KAWALAN DAN BAND",
    ),
    ("craft_hobby", "sewing_tool", "SEWING_TOOL"): (
        "show the sealed sewing-tool count, sizes, eyes, points, and case clearly",
        "Semak set alat jahit.",
        "Letak satu item pada alas.",
        "Saiz dan bentuk mudah dilihat.",
        "Simpan alat tajam.",
        "BILANGAN DAN SAIZ",
    ),
    ("pet_care", "cat_litter", "PET_LITTER"): (
        "show the litter pack, material, weight, disposal label, and dry measure clearly",
        "Semak bahan pasir kucing.",
        "Ukur sedikit ke tray kosong.",
        "Berat dan panduan mudah dilihat.",
        "Ikut arahan pelupusan.",
        "BAHAN DAN BERAT",
    ),
    ("craft_hobby", "epoxy_resin", "CRAFT_MATERIAL"): (
        "show the sealed resin components, ratio, warnings, PPE, and tools clearly",
        "Semak nisbah resin.",
        "Susun komponen tertutup.",
        "Amaran dan alat mudah dilihat.",
        "Ikut keselamatan label.",
        "NISBAH DAN AMARAN",
    ),
    (
        "beauty_personal_care",
        "personal_care_device",
        "PERSONAL_CARE_DEVICE",
    ): (
        "show the device attachments, controls, rating, guard, and dry operation clearly",
        "Semak alat penjagaan diri.",
        "Hidupkan tanpa sentuhan badan.",
        "Aksesori dan kawalan mudah dilihat.",
        "Ikut arahan pembersihan.",
        "AKSESORI DAN KAWALAN",
    ),
    ("beauty_personal_care", "body_moisturizer", "BODY_MOISTURIZER"): (
        "show the pack, amount, texture, and one adult-hand swatch clearly",
        "Semak tekstur krim badan.",
        "Tunjuk sedikit pada tangan.",
        "Sukatan dan tekstur mudah dilihat.",
        "Ikut arahan label.",
        "SUKATAN DAN TEKSTUR",
    ),
    (
        "sensitive_wellness",
        "traditional_herbal_preparation",
        "SENSITIVE_WELLNESS",
    ): (
        "show the sealed herbal product, weight, ingredients, warnings, and label clearly",
        "Semak label produk herba.",
        "Tunjuk pek tertutup dan sukatan.",
        "Bahan dan amaran mudah dilihat.",
        "Ikut arahan label.",
        "BAHAN DAN AMARAN",
    ),
    ("beauty_personal_care", "bath_salt", "BODY_BATH"): (
        "show the bath-salt pack, granule, warnings, and dry measured amount clearly",
        "Semak produk mandian.",
        "Ukur jumlah kering ikut label.",
        "Butiran dan sukatan mudah dilihat.",
        "Ikut arahan pek.",
        "BUTIRAN DAN SUKATAN",
    ),
    ("home_decor", "decorative_magnet", "HOME_DECOR"): (
        "show the magnet dimensions, front, back, print, and sample placement clearly",
        "Semak saiz magnet.",
        "Letak pada permukaan sampel.",
        "Cetakan dan belakang mudah dilihat.",
        "Pilih ikut ruang paparan.",
        "SAIZ DAN CETAKAN",
    ),
    ("household_cleaning", "trash_bag", "CLEANING_TOOL"): (
        "show the bag count, dimensions, material, seam, and disposal label clearly",
        "Semak saiz beg sampah.",
        "Buka satu beg kosong.",
        "Jahitan dan bahan mudah dilihat.",
        "Pilih ikut tong.",
        "SAIZ DAN BAHAN",
    ),
    ("home_decor", "candle", "HOME_DECOR"): (
        "show the unlit candle count, dimensions, wick, and safety label clearly",
        "Semak saiz lilin.",
        "Tunjuk sumbu tanpa menyalakan.",
        "Bilangan dan bentuk mudah dilihat.",
        "Ikut amaran kebakaran.",
        "SAIZ DAN SUMBU",
    ),
    ("household_pest_control", "pest_control", "PEST_CONTROL"): (
        "show the sealed pest-control pack, warnings, expiry, and placement label clearly",
        "Semak amaran produk perosak.",
        "Tunjuk panduan pada pek.",
        "Arahan dan tarikh mudah dilihat.",
        "Jauhkan daripada kanak-kanak.",
        "AMARAN DAN ARAHAN",
    ),
    ("automotive_care", "car_care_fluid", "CAR_CARE"): (
        "show the sealed car-care fluid, compatibility, warnings, and amount clearly",
        "Semak cecair penjagaan kenderaan.",
        "Tunjuk label dan sukatan.",
        "Keserasian mudah dilihat.",
        "Ikut arahan pengilang.",
        "LABEL DAN SUKATAN",
    ),
    ("kitchen_tool", "kitchen_tool", "KITCHEN_TOOL"): (
        "show every kitchen-tool component, dimensions, handle, and edge clearly",
        "Semak komponen alat dapur.",
        "Pasang komponen kering.",
        "Pemegang dan bahagian kerja jelas.",
        "Ikut arahan penggunaan.",
        "KOMPONEN DAN PEMEGANG",
    ),
    ("stationery", "notebook", "STATIONERY"): (
        "show the notebook dimensions, page count, cover, binding, and paper clearly",
        "Semak saiz buku nota.",
        "Buka beberapa halaman kosong.",
        "Jilidan dan kertas mudah dilihat.",
        "Pilih ikut kegunaan.",
        "HALAMAN DAN JILIDAN",
    ),
    ("fashion_apparel", "apparel_set", "APPAREL"): (
        "show every apparel-set piece, size label, fabric, seams, and silhouette clearly",
        "Semak semua item set.",
        "Bentang dan tunjuk jahitan.",
        "Potongan dan kain mudah dilihat.",
        "Rujuk ukuran saiz.",
        "SET DAN UKURAN",
    ),
    (
        "household_cleaning",
        "baby_bottle_cleanser",
        "HOUSEHOLD_CLEANER",
    ): (
        "show the sealed cleanser, amount, warnings, and bottle-care directions clearly",
        "Semak label pencuci botol.",
        "Tunjuk sukatan tanpa menuang.",
        "Arahan dan amaran mudah dilihat.",
        "Ikut arahan bilasan.",
        "SUKATAN DAN BILASAN",
    ),
    ("household_cleaning", "cleaning_tool", "CLEANING_TOOL"): (
        "show the cleaning tool dimensions, material, joints, and adjustment clearly",
        "Semak alat pembersihan.",
        "Tunjuk pelarasan tanpa habuk.",
        "Bahan dan sendi mudah dilihat.",
        "Padankan dengan ruang.",
        "BAHAN DAN PELARASAN",
    ),
    (
        "household_cleaning",
        "pressure_washer",
        "CLEANING_EQUIPMENT",
    ): (
        "show the pressure-washer attachments, controls, rating, and guards clearly",
        "Semak aksesori alat pencuci.",
        "Tunjuk kawalan tanpa air.",
        "Rating dan sambungan mudah dilihat.",
        "Ikut arahan keselamatan.",
        "AKSESORI DAN RATING",
    ),
    ("garden_care", "plant_support", "PLANT_CARE"): (
        "show the plant-support pieces, dimensions, joints, and assembly clearly",
        "Semak rangka sokongan tanaman.",
        "Pasang satu bahagian di meja.",
        "Ukuran dan sendi mudah dilihat.",
        "Padankan dengan ruang tanaman.",
        "UKURAN DAN SENDI",
    ),
    ("craft_hobby", "craft_material", "CRAFT_MATERIAL"): (
        "show the craft material count, dimensions, colours, warnings, and tools clearly",
        "Semak bahan kraf.",
        "Susun beberapa item di meja.",
        "Warna dan saiz mudah dilihat.",
        "Ikut amaran penggunaan.",
        "WARNA DAN SAIZ",
    ),
    ("stationery", "gift_bag", "STATIONERY"): (
        "show the gift-bag dimensions, material, handle, closure, and print clearly",
        "Semak saiz beg hadiah.",
        "Buka satu beg kosong.",
        "Pemegang dan cetakan mudah dilihat.",
        "Pilih ikut saiz hadiah.",
        "SAIZ DAN PEMEGANG",
    ),
    ("household_cleaning", "air_duster", "CLEANING_EQUIPMENT"): (
        "show the air-duster attachments, controls, rating, guard, and charging port clearly",
        "Semak aksesori air duster.",
        "Tunjuk kawalan tanpa meniup.",
        "Port dan rating mudah dilihat.",
        "Ikut arahan keselamatan.",
        "PORT DAN RATING",
    ),
}

for _strategy_key, (
    _scene_result,
    _hook,
    _demo,
    _benefit,
    _cta,
    _overlay,
) in _P58_ACTIVATED_COPY_TYPES.items():
    _product_type_group = _strategy_key[1]
    PRODUCT_TYPE_COPY_STRATEGY_REGISTRY[_strategy_key] = _fixed_strategy(
        copy_strategy_id=f"P4_{_product_type_group.upper()}_PRODUCT_TYPE_V1",
        scene_result_template=_scene_result,
        hook_line=_hook,
        demo_line=_demo,
        benefit_line=_benefit,
        cta_line=_cta,
        overlay_text=_overlay,
    )


PRODUCT_TYPE_COPY_STRATEGY_KEYS: Final[frozenset[ProductTypeCopyStrategyKey]] = (
    frozenset(PRODUCT_TYPE_COPY_STRATEGY_REGISTRY)
)
