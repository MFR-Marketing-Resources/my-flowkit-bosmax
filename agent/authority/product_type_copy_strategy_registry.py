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
}

PRODUCT_TYPE_COPY_STRATEGY_KEYS: Final[frozenset[ProductTypeCopyStrategyKey]] = (
    frozenset(PRODUCT_TYPE_COPY_STRATEGY_REGISTRY)
)
