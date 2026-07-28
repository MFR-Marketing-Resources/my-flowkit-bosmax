"""P3A authority registry for the first verified lip-colour product batch.

This is a bounded strategy registry, not a persistence layer. It contains only
the nine product IDs authorized by the owner after P2.6 review. Copy stays
product-specific while avoiding unsupported durability, medical, permanence,
platform-policy, and guaranteed-result claims.
"""
from __future__ import annotations

from typing import Final, Literal, TypedDict


class LipColorScriptSlot(TypedDict):
    hook_line: str
    demo_line: str
    benefit_line: str
    cta_line: str
    overlay_text: str


class LipColorCopyRegistryEntry(TypedDict):
    copy_strategy_id: str
    scene_action_index: Literal[0, 2]
    scripts: dict[int, LipColorScriptSlot]


LIP_COLOR_COPY_REGISTRY: Final[dict[str, LipColorCopyRegistryEntry]] = {
    "59a0a7cc-3374-4025-951a-9832fe9359e4": {
        "copy_strategy_id": "P3A_LIP_COLOR_TIME_PHORIA_FASTMOSS_V1",
        "scene_action_index": 0,
        "scripts": {
            8: {
                "hook_line": "Nak bibir nampak blur?",
                "demo_line": "Sapu Altera Lip Tint sekali.",
                "benefit_line": "Warna naik, garis bibir nampak lebih lembut.",
                "cta_line": "Semak shade korang.",
                "overlay_text": "BLURRING LIP TINT • PILIH SHADE",
            },
            10: {
                "hook_line": "Nak hasil bibir blur yang nampak kemas?",
                "demo_line": "Sapu Altera Lip Tint dan tunjuk dekat cermin.",
                "benefit_line": "Warna naik tanpa menutup tekstur bibir.",
                "cta_line": "Pilih shade korang.",
                "overlay_text": "HASIL BLUR • WARNA JELAS",
            },
            16: {
                "hook_line": "Nak hasil bibir blur yang kemas tanpa langkah rumit?",
                "demo_line": "Sapu Altera Lip Tint sekali, kemudian tunjuk warna dekat cermin.",
                "benefit_line": "Formula dua dalam satu beri warna sambil mengaburkan rupa garis bibir.",
                "cta_line": "Semak shade yang sesuai dengan gaya korang.",
                "overlay_text": "DUA DALAM SATU • KESAN BLUR",
            },
        },
    },
    "fcf0fff1-fc18-40da-b14c-ee44d1361413": {
        "copy_strategy_id": "P3A_LIP_COLOR_HIJAU_BLOOMING_MATTE_V1",
        "scene_action_index": 2,
        "scripts": {
            8: {
                "hook_line": "Nak warna bibir nampak semula jadi?",
                "demo_line": "Sapu Hijau Blooming Matte terus pada bibir.",
                "benefit_line": "Warna blooming terus nampak.",
                "cta_line": "Semak warnanya.",
                "overlay_text": "BLOOMING MATTE • WARNA NATURAL",
            },
            10: {
                "hook_line": "Nak shade yang ikut tona bibir?",
                "demo_line": "Sapu Hijau Blooming Matte dan tunjuk hasil dekat cermin.",
                "benefit_line": "Warna nampak natural dan kemas.",
                "cta_line": "Cuba shade ni.",
                "overlay_text": "WARNA IKUT TONA BIBIR",
            },
            16: {
                "hook_line": "Nak warna bibir yang nampak lebih natural untuk pakai harian?",
                "demo_line": "Sapu Hijau Blooming Matte pada bibir dan tunggu warna naik.",
                "benefit_line": "Hasil blooming menyesuaikan tona supaya look nampak semula jadi.",
                "cta_line": "Semak warna yang keluar pada bibir korang.",
                "overlay_text": "BLOOMING MATTE • HASIL NATURAL",
            },
        },
    },
    "7a75fcf1-0f34-487d-bcae-9cf65901f8fe": {
        "copy_strategy_id": "P3A_LIP_COLOR_CUBRE_MI_FULL_LOCK_V1",
        "scene_action_index": 0,
        "scripts": {
            8: {
                "hook_line": "Nak hasil matte dengan warna pekat?",
                "demo_line": "Sapu CUBRE MI pada bibir.",
                "benefit_line": "Warna matte terus nampak jelas.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "LIPMATTE • WARNA PEKAT",
            },
            10: {
                "hook_line": "Nak hasil matte dengan warna pekat?",
                "demo_line": "Sapu satu lapis dan tunjuk hasil dekat cermin.",
                "benefit_line": "Kemasan matte dengan warna yang nampak pekat.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "FULL LOCK • HASIL MATTE",
            },
            16: {
                "hook_line": "Lipmatte cepat hilang lepas pakai?",
                "demo_line": "Sapu CUBRE MI satu lapis dan buat mirror check.",
                "benefit_line": "Hasil matte dengan warna pekat nampak jelas dari dekat.",
                "cta_line": "Pilih shade yang sesuai dengan gaya korang.",
                "overlay_text": "CUBRE MI • MATTE + WARNA PEKAT",
            },
        },
    },
    "4c6e5722-9914-49cf-a0fa-204b452c4fe1": {
        "copy_strategy_id": "P3A_LIP_COLOR_DHERBS_LIPSTICK_V1",
        "scene_action_index": 0,
        "scripts": {
            8: {
                "hook_line": "Nak lipstick yang terus nampak warnanya?",
                "demo_line": "Sapu DHERBS sekali pada bibir.",
                "benefit_line": "Hasil warna nampak jelas.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "DHERBS LIPSTICK • WARNA JELAS",
            },
            10: {
                "hook_line": "Nak warna lipstick yang kemas?",
                "demo_line": "Sapu DHERBS dan tunjuk hasil dekat cermin.",
                "benefit_line": "Sapuan jelas dengan hasil bibir berwarna.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "SATU SAPUAN • HASIL JELAS",
            },
            16: {
                "hook_line": "Nak tengok DHERBS Lipstick ni betul-betul naik dekat bibir?",
                "demo_line": "Buka produk, sapu satu lapis dan buat mirror check.",
                "benefit_line": "Hasil warna nampak terus selepas sapuan.",
                "cta_line": "Semak shade sebelum pilih.",
                "overlay_text": "DHERBS • TUNJUK WARNA SEBENAR",
            },
        },
    },
    "abdb60ba-c8b8-433f-89b4-0b3a2f314f63": {
        "copy_strategy_id": "P3A_LIP_COLOR_KAXIER_GLOSS_SHIMMER_V1",
        "scene_action_index": 2,
        "scripts": {
            8: {
                "hook_line": "Nak bibir nampak berkilau?",
                "demo_line": "Sapu KAXIER Lip Gloss pada bibir.",
                "benefit_line": "Shimmer terus tangkap cahaya.",
                "cta_line": "Semak kilauannya.",
                "overlay_text": "LIP GLOSS • KILAU SHIMMER",
            },
            10: {
                "hook_line": "Nak hasil gloss yang terus menyerlah?",
                "demo_line": "Sapu KAXIER dan tunjuk bibir bawah cahaya.",
                "benefit_line": "Kilauan shimmer nampak jelas.",
                "cta_line": "Cuba look ni.",
                "overlay_text": "GLOSS + SHIMMER",
            },
            16: {
                "hook_line": "Bibir nampak flat bila pakai warna biasa?",
                "demo_line": "Sapu KAXIER Lip Gloss dan gerakkan bibir bawah cahaya.",
                "benefit_line": "Tekstur gloss dengan shimmer beri kilauan yang mudah nampak.",
                "cta_line": "Semak hasil gloss sebelum pilih.",
                "overlay_text": "KAXIER • KILAUAN BAWAH CAHAYA",
            },
        },
    },
    "4601bcd9-f29b-454e-8d64-31f8a9d2ef12": {
        "copy_strategy_id": "P3A_LIP_COLOR_KAXIER_LIQUID_MATTE_V1",
        "scene_action_index": 0,
        "scripts": {
            8: {
                "hook_line": "Nak liquid matte yang nampak kemas?",
                "demo_line": "Sapu satu lapis pada bibir.",
                "benefit_line": "Warna matte terus naik.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "LIQUID MATTE • 6ML",
            },
            10: {
                "hook_line": "Nak hasil liquid matte yang jelas?",
                "demo_line": "Sapu Kaxier dan tunjuk tekstur dekat cermin.",
                "benefit_line": "Warna pekat nampak kemas.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "TEKSTUR CAIR • HASIL MATTE",
            },
            16: {
                "hook_line": "Gincu cair selalu susah nak nampak rata?",
                "demo_line": "Sapu Kaxier Liquid Matte satu lapis pada bibir.",
                "benefit_line": "Tunjuk tekstur cair berubah kepada hasil matte yang kemas.",
                "cta_line": "Semak shade sebelum pilih.",
                "overlay_text": "KAXIER 6ML • LIQUID KE MATTE",
            },
        },
    },
    "a14cab39-1f3b-4648-8128-53e2a082e8b8": {
        "copy_strategy_id": "P3A_LIP_COLOR_MAYBELLINE_MATTE_INK_V1",
        "scene_action_index": 0,
        "scripts": {
            8: {
                "hook_line": "Nak warna matte yang terus naik?",
                "demo_line": "Sapu Maybelline Matte Ink pada bibir.",
                "benefit_line": "Warna pekat nampak jelas.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "MATTE INK • WARNA PEKAT",
            },
            10: {
                "hook_line": "Nak hasil matte untuk rutin sibuk?",
                "demo_line": "Sapu Matte Ink dan tunjuk dekat cermin.",
                "benefit_line": "Warna pekat dengan kemasan matte.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "HASIL MATTE • WARNA JELAS",
            },
            16: {
                "hook_line": "Gincu luntur masa rutin sibuk memang menyusahkan.",
                "demo_line": "Sapu Maybelline Matte Ink satu lapis pada bibir.",
                "benefit_line": "Tunjuk warna pekat dan kemasan matte dari dekat.",
                "cta_line": "Semak shade yang sesuai untuk korang.",
                "overlay_text": "MAYBELLINE • MATTE INK",
            },
        },
    },
    "3ad2d1bc-432f-427c-8518-e8bbb25e3712": {
        "copy_strategy_id": "P3A_LIP_COLOR_PISHINE_LIPMATTE_V1",
        "scene_action_index": 2,
        "scripts": {
            8: {
                "hook_line": "Nak lipmatte yang terus nampak warnanya?",
                "demo_line": "Sapu Pishine sekali pada bibir.",
                "benefit_line": "Hasil matte terus jelas.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "PISHINE • HASIL MATTE",
            },
            10: {
                "hook_line": "Nak warna matte untuk look harian?",
                "demo_line": "Sapu Pishine dan tunjuk hasil dekat cermin.",
                "benefit_line": "Warna naik dengan kemasan matte.",
                "cta_line": "Semak shade ni.",
                "overlay_text": "LIPMATTE • LOOK HARIAN",
            },
            16: {
                "hook_line": "Asyik pilih lipmatte tapi warna tak nampak jelas?",
                "demo_line": "Sapu Pishine satu lapis pada bibir dan buat mirror check.",
                "benefit_line": "Hasil matte dan warna terus nampak dari dekat.",
                "cta_line": "Semak shade sebelum pilih.",
                "overlay_text": "PISHINE • WARNA + HASIL MATTE",
            },
        },
    },
    "4ea83e03-9e04-4da2-828e-5d9b2d78fd5a": {
        "copy_strategy_id": "P3A_LIP_COLOR_TIME_PHORIA_MANUAL_V1",
        "scene_action_index": 2,
        "scripts": {
            8: {
                "hook_line": "Nak lip tint ringkas untuk touch-up?",
                "demo_line": "Sapu Altera 4G pada bibir.",
                "benefit_line": "Kesan blur terus nampak.",
                "cta_line": "Semak shade korang.",
                "overlay_text": "ALTERA 4G • WARNA + BLUR",
            },
            10: {
                "hook_line": "Nak touch-up bibir tanpa langkah rumit?",
                "demo_line": "Keluarkan Altera 4G dan sapu sekali.",
                "benefit_line": "Warna naik dengan hasil blur.",
                "cta_line": "Pilih shade korang.",
                "overlay_text": "KOMPAK • MUDAH TOUCH-UP",
            },
            16: {
                "hook_line": "Nak satu lip tint kompak untuk warna dan hasil blur?",
                "demo_line": "Keluarkan Altera 4G, sapu pada bibir dan buat mirror check.",
                "benefit_line": "Formula dua dalam satu beri warna sambil mengaburkan rupa garis bibir.",
                "cta_line": "Semak shade yang paling ngam.",
                "overlay_text": "ALTERA 4G • DUA DALAM SATU",
            },
        },
    },
}

P3A_ALLOWED_PRODUCT_IDS: Final[frozenset[str]] = frozenset(
    LIP_COLOR_COPY_REGISTRY
)
