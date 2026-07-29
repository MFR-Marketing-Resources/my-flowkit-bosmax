"""Deterministic product-use grammar for buyer-facing video scenes.

This library sits below product taxonomy and above variation/prompt rendering.
It does not infer claims, mutate product truth, or replace operator-selected
creative inputs. USP and approved copy may change dialogue; product type keeps
the same physical action grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, TypedDict

from agent.authority.catalog_product_type_truth import (
    resolve_catalog_product_type_truth,
)
from agent.services.bosmax_product_family import derive_bosmax_product_family


class DirectScriptSlots(TypedDict):
    hook: tuple[str, ...]
    benefit: tuple[str, ...]
    cta: tuple[str, ...]


class SceneStrategyEntry(TypedDict):
    product_family: str
    product_type: str
    use_case: tuple[str, ...]
    allowed_scene_strategy: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    scene_contexts: tuple[str, ...]
    camera_routes: tuple[str, ...]
    avatar_hints: tuple[str, ...]
    wardrobe_hints: tuple[str, ...]
    direct_script_slots: DirectScriptSlots
    sensitive_handling_rules: tuple[str, ...]


class ResolvedDirectScriptSlots(TypedDict):
    hook: list[str]
    benefit: list[str]
    cta: list[str]


class ResolvedSceneStrategy(TypedDict):
    strategy_id: str
    resolution_source: str
    fallback_used: bool
    product_family: str
    product_type: str
    use_case: list[str]
    allowed_scene_strategy: list[str]
    allowed_actions: list[str]
    forbidden_actions: list[str]
    scene_contexts: list[str]
    camera_routes: list[str]
    avatar_hints: list[str]
    wardrobe_hints: list[str]
    direct_script_slots: ResolvedDirectScriptSlots
    sensitive_handling_rules: list[str]


class SelectedSceneStrategyVariant(TypedDict):
    scene_strategy_id: str
    allowed_scene_strategy: str
    allowed_action: str
    scene_context: str
    camera_route: str
    avatar_hint: str
    wardrobe_hint: str
    direct_hook: str
    direct_benefit: str
    direct_cta: str


_COMMON_PHYSICS_FORBIDDEN = (
    "physically impossible product use",
    "invented product transformation or before-and-after proof",
)

_COMMON_CLAIM_FORBIDDEN = (
    "unverifiable performance claims",
    "medical, cure, or guaranteed-result claims",
)


def _simple_scene_strategy(
    *,
    product_family: str,
    product_type: str,
    use_case: tuple[str, ...],
    allowed_scene_strategy: tuple[str, ...],
    allowed_actions: tuple[str, ...],
    scene_contexts: tuple[str, ...],
    camera_routes: tuple[str, ...],
    avatar_hints: tuple[str, ...],
    wardrobe_hints: tuple[str, ...],
    hook: tuple[str, ...],
    benefit: tuple[str, ...],
    cta: tuple[str, ...],
    forbidden_actions: tuple[str, ...] = (),
    sensitive_handling_rules: tuple[str, ...] = (),
) -> SceneStrategyEntry:
    """Build additive P5.7 scene entries with common safety invariants."""

    return {
        "product_family": product_family,
        "product_type": product_type,
        "use_case": use_case,
        "allowed_scene_strategy": allowed_scene_strategy,
        "allowed_actions": allowed_actions,
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            *forbidden_actions,
        ),
        "scene_contexts": scene_contexts,
        "camera_routes": camera_routes,
        "avatar_hints": avatar_hints,
        "wardrobe_hints": wardrobe_hints,
        "direct_script_slots": {
            "hook": hook,
            "benefit": benefit,
            "cta": cta,
        },
        "sensitive_handling_rules": sensitive_handling_rules,
    }


SCENE_STRATEGIES: dict[str, SceneStrategyEntry] = {
    "LIP_COLOR": {
        "product_family": "BEAUTY_PERSONAL_CARE",
        "product_type": "LIP_COLOR",
        "use_case": (
            "daily lip colour",
            "mirror touch-up",
            "hand swatch",
            "handbag touch-up",
        ),
        "allowed_scene_strategy": (
            "lip application with a clean mirror check",
            "hand swatch followed by shade reveal",
            "handbag touch-up before leaving",
            "vanity shade comparison with the product label visible",
        ),
        "allowed_actions": (
            "apply one clean pass to the lips",
            "swatch one shade on the back of the hand",
            "touch up the lip colour while looking into a mirror",
            "remove the product from a handbag and show the shade",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "apply the product to eyes or unrelated body areas",
        ),
        "scene_contexts": (
            "bright vanity mirror with a clean lip-colour setup",
            "daylight hand-swatch table with the shade and label visible",
            "handbag touch-up moment before leaving",
            "clean dressing-table shade comparison",
        ),
        "camera_routes": (
            "macro product tip to lip application, then mirror reaction",
            "top-down product reveal to close hand swatch",
            "medium handbag reveal to tight mirror touch-up",
            "label close-up to natural finished-lip framing",
        ),
        "avatar_hints": (
            "adult beauty buyer comfortable demonstrating a real touch-up",
            "adult creator with natural expressions and steady hand control",
        ),
        "wardrobe_hints": (
            "simple going-out outfit with clean neutral styling",
            "modest casual top that keeps focus on the lip shade",
        ),
        "direct_script_slots": {
            "hook": (
                "Sekali sapu warna terus naik.",
                "Nak touch-up cepat, tengok shade ni.",
            ),
            "benefit": (
                "Sapu, tengok cermin, terus nampak warnanya.",
                "Swatch dekat tangan dulu, senang pilih shade.",
            ),
            "cta": (
                "Pilih shade yang ngam dengan gaya korang.",
                "Kalau suka warna macam ni, semak shade sekarang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "BEAUTY_PERSONAL_CARE": {
        "product_family": "BEAUTY_PERSONAL_CARE",
        "product_type": "BEAUTY_PERSONAL_CARE",
        "use_case": (
            "sink-side routine",
            "vanity routine",
            "texture and packaging demonstration",
        ),
        "allowed_scene_strategy": (
            "clean sink-side product routine",
            "vanity texture demonstration",
            "label and dispenser walkthrough",
        ),
        "allowed_actions": (
            "dispense a small product-appropriate amount onto a clean fingertip",
            "show texture on the back of the hand",
            "open, close, and hold the packaging label-forward",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "apply to intimate areas",
            "show clinical or diagnostic proof",
        ),
        "scene_contexts": (
            "clean sink-side personal-care setup",
            "bright vanity with product texture visible",
            "simple bathroom shelf with label-forward handling",
        ),
        "camera_routes": (
            "label close-up to product-appropriate fingertip dispense",
            "macro texture reveal to practical routine framing",
            "dispenser detail to clean product hero",
        ),
        "avatar_hints": (
            "adult everyday personal-care buyer",
            "adult creator demonstrating a simple practical routine",
        ),
        "wardrobe_hints": (
            "clean casual homewear",
            "neutral modest top with no clinical styling",
        ),
        "direct_script_slots": {
            "hook": (
                "Tengok tekstur dan cara guna produk ni.",
                "Rutin ringkas bermula dengan sukatan yang betul.",
            ),
            "benefit": (
                "Ambil sedikit, tunjuk tekstur, kemudian guna ikut label.",
                "Pam atau picit ikut keperluan, tak perlu berlebihan.",
            ),
            "cta": (
                "Semak cara guna dan pilih yang sesuai untuk rutin korang.",
                "Kalau format ni sesuai, tengok butiran produk dulu.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "FRAGRANCE": {
        "product_family": "beauty_fragrance",
        "product_type": "FRAGRANCE",
        "use_case": (
            "getting-ready finishing touch",
            "handbag refresh",
            "social-ready outfit finish",
        ),
        "allowed_scene_strategy": (
            "final fragrance step before leaving",
            "handbag scent refresh",
            "social-ready outfit finishing moment",
            "bottle, cap, and nozzle product story",
        ),
        "allowed_actions": (
            "spritz once onto the wrist from a normal distance",
            "spritz lightly onto outer clothing where product directions allow",
            "remove the bottle from a handbag and replace the cap",
            "show the nozzle, cap, and label without fake scent particles",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "spray toward eyes, mouth, or another person's face",
            "visualize scent as medically active particles",
        ),
        "scene_contexts": (
            "dressing-table finishing touch before leaving",
            "handbag refresh in a clean social-ready setting",
            "outfit mirror check with fragrance as the final step",
            "clean vanity bottle hero with cap and nozzle detail",
        ),
        "camera_routes": (
            "bottle label close-up to one wrist spritz and outfit finish",
            "handbag reveal to nozzle detail and social-ready medium shot",
            "cap removal macro to mirror-ready final frame",
            "reflective bottle rotation to natural hand-held reveal",
        ),
        "avatar_hints": (
            "adult buyer getting ready for work or a social outing",
            "adult creator with a polished but believable routine",
        ),
        "wardrobe_hints": (
            "neat going-out outfit",
            "smart casual or modest social-ready styling",
        ),
        "direct_script_slots": {
            "hook": (
                "Sembur sikit sebelum keluar.",
                "Last step sebelum siap, pilih bau yang korang suka.",
            ),
            "benefit": (
                "Satu semburan, terus lengkap rutin bersiap.",
                "Saiz macam ni senang capai bila nak refresh.",
            ),
            "cta": (
                "Kalau suka gaya bau macam ni, semak variannya.",
                "Pilih scent yang paling ngam dengan rutin korang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "SPICE_SEASONING": {
        "product_family": "food_packaged",
        "product_type": "SPICE_SEASONING",
        "use_case": (
            "cooking preparation",
            "sprinkle into pan",
            "ingredient counter setup",
            "plated dish finish",
        ),
        "allowed_scene_strategy": (
            "ingredient-counter cooking preparation",
            "seasoning sprinkled into a hot pan",
            "stir-through cooking action",
            "pack-to-plated-dish finish",
        ),
        "allowed_actions": (
            "measure or pinch a small amount before cooking",
            "sprinkle the seasoning into a pan",
            "stir the seasoning through the dish",
            "place the pack beside the finished plated dish",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "eat dry seasoning directly from the pack",
            "show unsafe contact with an open flame",
        ),
        "scene_contexts": (
            "ingredient counter with pan and cooking tools ready",
            "stove-side seasoning moment with a clean pan view",
            "kitchen prep surface with measured seasoning",
            "finished plated dish with the seasoning pack beside it",
        ),
        "camera_routes": (
            "top-down ingredient setup to close sprinkle into pan",
            "pack label macro to side-angle stir-through action",
            "measured pinch close-up to plated-dish reveal",
            "pan action close-up to pack-and-dish hero frame",
        ),
        "avatar_hints": (
            "adult home cook demonstrating a normal meal-prep step",
            "adult buyer who values fast practical cooking",
        ),
        "wardrobe_hints": (
            "clean casual kitchen wear",
            "simple apron over everyday clothing",
        ),
        "direct_script_slots": {
            "hook": (
                "Tabur sikit, bau masakan terus naik.",
                "Nak masak cepat, mula dengan rempah yang betul.",
            ),
            "benefit": (
                "Sukat, tabur dalam kuali, kemudian gaul rata.",
                "Dari paket terus masuk langkah masak harian.",
            ),
            "cta": (
                "Kalau selalu masak menu ni, semak pilihan perisanya.",
                "Pilih perisa yang ngam dengan menu rumah korang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "PACKAGED_SAUCE_SAMBAL": {
        "product_family": "food_packaged",
        "product_type": "PACKAGED_SAUCE_SAMBAL",
        "use_case": (
            "meal preparation",
            "sauce added to cooking",
            "sambal serving",
            "plated dish pairing",
        ),
        "allowed_scene_strategy": (
            "open-and-spoon cooking preparation",
            "sauce stirred into a dish",
            "sambal served beside a meal",
            "sealed pack to plated pairing",
        ),
        "allowed_actions": (
            "open the jar or pack cleanly",
            "spoon a normal serving into the pan or dish",
            "stir sauce through the meal",
            "place the product beside the finished plate",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "pour an implausible quantity over the meal",
            "show unsafe food handling or broken seal integrity",
        ),
        "scene_contexts": (
            "clean kitchen counter with an open jar and serving spoon",
            "stove-side sauce stir-through moment",
            "dining table with sambal beside a plated meal",
            "sealed pack reveal followed by finished dish pairing",
        ),
        "camera_routes": (
            "label reveal to spoon serving close-up",
            "side-angle stir-through to plated meal",
            "top-down meal pairing with product in frame",
            "seal detail to jar-and-dish hero shot",
        ),
        "avatar_hints": (
            "adult home cook",
            "adult buyer serving a normal household meal",
        ),
        "wardrobe_hints": (
            "clean everyday kitchen wear",
            "simple casual dining outfit",
        ),
        "direct_script_slots": {
            "hook": (
                "Buka, cedok, terus masuk dalam hidangan.",
                "Nak tambah rasa, mula dengan satu sudu.",
            ),
            "benefit": (
                "Cedok ikut selera dan hidang bersama menu rumah.",
                "Gaul terus dalam masakan atau letak tepi pinggan.",
            ),
            "cta": (
                "Kalau menu ni selalu ada, semak pilihan rasanya.",
                "Pilih varian yang sesuai dengan hidangan korang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "PACKAGED_FOOD": {
        "product_family": "food_packaged",
        "product_type": "PACKAGED_FOOD",
        "use_case": (
            "pack opening",
            "normal serving",
            "meal pairing",
        ),
        "allowed_scene_strategy": (
            "sealed pack to normal serving",
            "serving-size product demonstration",
            "pack beside finished meal",
        ),
        "allowed_actions": (
            "show the intact seal and open the pack cleanly",
            "serve a normal product-appropriate portion",
            "place the product beside its intended meal context",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "show an unsafe or product-inappropriate serving method",
        ),
        "scene_contexts": (
            "clean kitchen counter with sealed pack",
            "simple serving table with a normal portion",
            "product pack beside its intended meal",
        ),
        "camera_routes": (
            "seal and label close-up to serving reveal",
            "top-down portion view to pack hero",
            "product close-up to meal-context wide shot",
        ),
        "avatar_hints": (
            "adult household food buyer",
            "adult creator demonstrating normal serving use",
        ),
        "wardrobe_hints": (
            "clean casual kitchen wear",
            "simple everyday dining outfit",
        ),
        "direct_script_slots": {
            "hook": (
                "Buka paket, terus nampak cara hidangnya.",
                "Tengok saiz hidangan dan cara guna produk ni.",
            ),
            "benefit": (
                "Hidang ikut sukatan yang sesuai untuk menu korang.",
                "Dari paket terus masuk rutin makan harian.",
            ),
            "cta": (
                "Semak rasa dan saiz yang sesuai.",
                "Kalau format ni mudah untuk korang, tengok pilihannya.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "LAUNDRY_DETERGENT": {
        "product_family": "LAUNDRY_DETERGENT_LIQUID_REFILL",
        "product_type": "LAUNDRY_DETERGENT",
        "use_case": (
            "laundry sorting",
            "detergent measuring",
            "washer loading",
            "refill storage",
        ),
        "allowed_scene_strategy": (
            "measure detergent during a laundry load",
            "refill pouch to bottle transfer",
            "laundry basket to washer routine",
            "utility-shelf storage and cap detail",
        ),
        "allowed_actions": (
            "measure detergent with the product cap or proper cup",
            "pour detergent into the washer drawer or basin as directed",
            "transfer a refill carefully into its intended bottle",
            "close the cap and return the pack to the utility shelf",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "ingest, taste, or apply detergent to skin",
            "mix detergent with unrelated household chemicals",
        ),
        "scene_contexts": (
            "clean laundry corner with basket, washer, and detergent",
            "washer drawer measuring moment",
            "utility counter refill transfer",
            "laundry shelf with cap and label visible",
        ),
        "camera_routes": (
            "laundry basket wide shot to measured-pour close-up",
            "label reveal to washer-drawer pour",
            "refill spout macro to stable bottle transfer",
            "cap close-up to clean utility-shelf hero",
        ),
        "avatar_hints": (
            "adult household buyer doing a normal laundry load",
            "adult creator demonstrating careful measuring",
        ),
        "wardrobe_hints": (
            "clean casual homewear",
            "simple practical laundry-day outfit",
        ),
        "direct_script_slots": {
            "hook": (
                "Sukat dulu, kemudian terus masuk cucian.",
                "Satu langkah ni memang terus masuk rutin dobi.",
            ),
            "benefit": (
                "Tuang ikut sukatan pada label, tak perlu agak-agak.",
                "Refill perlahan, tutup semula, terus simpan.",
            ),
            "cta": (
                "Semak saiz yang sesuai dengan rutin basuhan korang.",
                "Kalau selalu membasuh, tengok pilihan peknya.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "FABRIC_SOFTENER": {
        "product_family": "FABRIC_SOFTENER_LIQUID",
        "product_type": "FABRIC_SOFTENER",
        "use_case": (
            "fabric-care measuring",
            "washer softener drawer",
            "folded-laundry finish",
        ),
        "allowed_scene_strategy": (
            "measure softener for a laundry load",
            "pour into the correct washer compartment",
            "folded-laundry finishing moment",
        ),
        "allowed_actions": (
            "measure a product-appropriate amount",
            "pour into the softener compartment as directed",
            "close the bottle and fold finished laundry",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "ingest or apply fabric softener directly to skin",
            "pour directly onto worn clothing unless label directions allow it",
        ),
        "scene_contexts": (
            "clean laundry counter with softener and measuring cap",
            "washer softener-drawer close-up",
            "folded clean laundry beside the product",
        ),
        "camera_routes": (
            "cap measure macro to washer compartment",
            "label reveal to controlled pour",
            "folded-fabric texture close-up to product hero",
        ),
        "avatar_hints": (
            "adult household laundry buyer",
            "adult creator demonstrating a measured fabric-care step",
        ),
        "wardrobe_hints": (
            "clean casual homewear",
            "simple laundry-day outfit",
        ),
        "direct_script_slots": {
            "hook": (
                "Sukat, tuang, siap satu langkah penjagaan kain.",
                "Masuk ruang pelembut, bukan terus atas baju.",
            ),
            "benefit": (
                "Guna ikut sukatan pada label untuk setiap basuhan.",
                "Tutup semula botol selepas tuang dan terus simpan.",
            ),
            "cta": (
                "Semak varian yang sesuai dengan rutin dobi korang.",
                "Pilih saiz ikut kekerapan basuhan rumah.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "BABY_WIPES": {
        "product_family": "BABY_WIPES",
        "product_type": "BABY_WIPES",
        "use_case": (
            "pack opening",
            "single-sheet dispense",
            "diaper-bag packing",
            "clean changing-station setup",
        ),
        "allowed_scene_strategy": (
            "open the pack and pull one sheet cleanly",
            "pack wipes into a diaper bag",
            "changing-station product setup without body demonstration",
        ),
        "allowed_actions": (
            "open and reseal the wipes pack",
            "pull one sheet to show size and texture",
            "place the pack into a diaper bag",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "show intimate-area wiping or a baby body close-up",
            "claim sterilization, rash prevention, or medical protection",
        ),
        "scene_contexts": (
            "clean baby-care table with wipes pack and diaper bag",
            "nursery shelf with resealable pack",
            "changing-station product setup with no baby body in frame",
        ),
        "camera_routes": (
            "pack seal close-up to single-sheet pull",
            "top-down diaper-bag packing view",
            "label reveal to clean changing-station product hero",
        ),
        "avatar_hints": (
            "adult parent or caregiver",
            "adult household buyer demonstrating pack handling",
        ),
        "wardrobe_hints": (
            "clean modest casual homewear",
            "simple parent-on-the-go outfit",
        ),
        "direct_script_slots": {
            "hook": (
                "Buka penutup, tarik satu helai.",
                "Pek macam ni senang masuk beg bayi.",
            ),
            "benefit": (
                "Ambil satu helai dan tutup semula supaya pek kekal kemas.",
                "Tunjuk saiz helaian dan cara simpan pek.",
            ),
            "cta": (
                "Semak saiz pek yang sesuai untuk rumah atau beg bayi.",
                "Pilih pek ikut kegunaan harian korang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "BABY_DIAPER": {
        "product_family": "BABY_DIAPER",
        "product_type": "BABY_DIAPER",
        "use_case": (
            "pack opening",
            "diaper unfold and size check",
            "diaper-bag packing",
            "changing-station preparation",
        ),
        "allowed_scene_strategy": (
            "unfold one diaper on a clean table",
            "show waistband and fastening details",
            "pack diapers into a diaper bag",
        ),
        "allowed_actions": (
            "remove one diaper from the pack",
            "unfold and gently stretch the waistband on a table",
            "show the fastener and size marking",
            "place diapers into a diaper bag",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "show a baby body close-up or explicit diaper-changing action",
            "claim medical protection or guaranteed leak prevention",
        ),
        "scene_contexts": (
            "clean changing table with unopened diaper pack",
            "top-down diaper unfold and size-detail setup",
            "parent diaper-bag packing moment",
        ),
        "camera_routes": (
            "pack reveal to top-down diaper unfold",
            "waistband macro to fastener detail",
            "diaper stack close-up to bag-packing wide shot",
        ),
        "avatar_hints": (
            "adult parent or caregiver",
            "adult household buyer preparing a diaper bag",
        ),
        "wardrobe_hints": (
            "clean modest casual homewear",
            "simple practical parent outfit",
        ),
        "direct_script_slots": {
            "hook": (
                "Keluarkan satu, buka, terus nampak bentuknya.",
                "Tengok bahagian pinggang dan pelekat dulu.",
            ),
            "benefit": (
                "Buka atas meja supaya saiz dan kemasan jelas.",
                "Susun beberapa helai terus dalam beg bayi.",
            ),
            "cta": (
                "Semak saiz yang sesuai sebelum pilih pek.",
                "Pilih kuantiti ikut rutin harian keluarga.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "APPAREL": {
        "product_family": "fashion_apparel",
        "product_type": "APPAREL",
        "use_case": (
            "hanger reveal",
            "mirror try-on",
            "fabric and seam detail",
            "fold and styling comparison",
        ),
        "allowed_scene_strategy": (
            "hanger-to-mirror try-on",
            "fabric drape and seam walkthrough",
            "folded garment to styled outfit",
        ),
        "allowed_actions": (
            "hold the garment on a hanger",
            "wear the garment for a normal fit check",
            "pinch the fabric lightly to show texture",
            "show seams, hem, and silhouette",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "distort the wearer's body or garment proportions",
        ),
        "scene_contexts": (
            "clean wardrobe rail with garment on hanger",
            "full-length mirror try-on area",
            "fabric-detail table with folded garment",
        ),
        "camera_routes": (
            "hanger full shot to mirror fit check",
            "medium silhouette reveal to seam macro",
            "top-down fold to fabric-texture close-up",
        ),
        "avatar_hints": (
            "adult apparel buyer matching the intended size range",
            "adult creator showing a believable fit",
        ),
        "wardrobe_hints": (
            "neutral base layer appropriate for try-on",
            "simple styling that does not obscure the garment",
        ),
        "direct_script_slots": {
            "hook": (
                "Sarung terus nampak potongan baju ni.",
                "Tengok jatuhan kain dari depan sampai sisi.",
            ),
            "benefit": (
                "Angkat dekat cermin, kemudian tunjuk jahitan dan kain.",
                "Dari hanger terus nampak cara baju ni digayakan.",
            ),
            "cta": (
                "Semak ukuran sebelum pilih saiz.",
                "Pilih warna dan saiz yang paling ngam.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "MODESTWEAR": {
        "product_family": "fashion_modestwear",
        "product_type": "MODESTWEAR",
        "use_case": (
            "coverage check",
            "drape demonstration",
            "mirror styling",
            "fabric detail",
        ),
        "allowed_scene_strategy": (
            "modest mirror styling with coverage visible",
            "fabric drape and edge detail",
            "wardrobe colour pairing",
        ),
        "allowed_actions": (
            "drape the garment or scarf naturally",
            "show front, side, and back coverage",
            "pinch the fabric edge to show texture",
            "pair the item with a simple modest outfit",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "use styling that contradicts the modestwear use case",
        ),
        "scene_contexts": (
            "clean modest-fashion mirror area",
            "wardrobe rail with coordinated modest outfit",
            "fabric table with drape and edge detail",
        ),
        "camera_routes": (
            "full coverage mirror shot to fabric close-up",
            "front-to-side styling turn with steady framing",
            "top-down colour pairing to drape reveal",
        ),
        "avatar_hints": (
            "adult modest-fashion buyer",
            "adult creator comfortable showing coverage and drape",
        ),
        "wardrobe_hints": (
            "neutral inner layer with full coverage",
            "coordinated modest outfit",
        ),
        "direct_script_slots": {
            "hook": (
                "Tengok coverage dan jatuhan kain ni.",
                "Dari depan sampai sisi, potongan terus jelas.",
            ),
            "benefit": (
                "Gayakan depan cermin dan tunjuk bahagian tepi.",
                "Picit hujung kain sikit supaya tekstur nampak.",
            ),
            "cta": (
                "Semak ukuran dan pilih warna yang ngam.",
                "Pilih gaya yang sesuai dengan wardrobe korang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "SPORTSWEAR": {
        "product_family": "fashion_sportswear",
        "product_type": "SPORTSWEAR",
        "use_case": (
            "fit check",
            "normal movement",
            "fabric stretch",
            "seam detail",
        ),
        "allowed_scene_strategy": (
            "mirror fit and movement check",
            "light warm-up movement",
            "fabric and seam demonstration",
        ),
        "allowed_actions": (
            "wear the garment for a normal fit check",
            "perform a light stretch or walking movement",
            "show waistband, seam, and fabric detail",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "claim unverified athletic or body-performance outcomes",
        ),
        "scene_contexts": (
            "clean activewear fitting corner",
            "bright indoor warm-up space",
            "sportswear detail table with seams visible",
        ),
        "camera_routes": (
            "full fit shot to light movement tracking",
            "waistband close-up to walking medium shot",
            "fabric detail macro to mirror silhouette",
        ),
        "avatar_hints": (
            "adult activewear buyer",
            "adult creator performing light believable movement",
        ),
        "wardrobe_hints": (
            "complete modest activewear set",
            "simple sport-ready styling",
        ),
        "direct_script_slots": {
            "hook": (
                "Pakai, bergerak sikit, terus nampak fit.",
                "Tengok pinggang, jahitan, dan jatuhan kain.",
            ),
            "benefit": (
                "Buat gerakan ringan supaya potongan nampak jelas.",
                "Tunjuk kain dan jahitan sebelum pilih saiz.",
            ),
            "cta": (
                "Semak ukuran dan pilih fit yang sesuai.",
                "Pilih warna yang ngam dengan set sukan korang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "HOUSEHOLD_CLEANER": {
        "product_family": "HOUSEHOLD_CLEANER_GENERAL",
        "product_type": "HOUSEHOLD_CLEANER",
        "use_case": (
            "surface preparation",
            "product application to surface",
            "wipe-through",
            "cleaning-tool storage",
        ),
        "allowed_scene_strategy": (
            "apply cleaner to a suitable household surface",
            "controlled wipe-through demonstration",
            "nozzle, cap, and label walkthrough",
        ),
        "allowed_actions": (
            "apply a product-appropriate amount to a suitable surface",
            "wipe the surface with the correct cleaning cloth",
            "close the nozzle or cap after use",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "mix the cleaner with unrelated chemicals",
            "apply cleaner to food, skin, or an unsafe surface",
        ),
        "scene_contexts": (
            "clean utility counter with suitable test surface",
            "kitchen sink-side wipe-through setup",
            "household cleaning shelf with nozzle and label visible",
        ),
        "camera_routes": (
            "label and nozzle close-up to controlled surface application",
            "side-angle wipe-through to clean product hero",
            "cap detail to utility-shelf storage frame",
        ),
        "avatar_hints": (
            "adult household buyer",
            "adult creator demonstrating safe routine cleaning",
        ),
        "wardrobe_hints": (
            "clean practical homewear",
            "simple protective cleaning gloves where appropriate",
        ),
        "direct_script_slots": {
            "hook": (
                "Sapu pada permukaan yang sesuai, kemudian lap.",
                "Tengok nozzle dan cara guna produk ni.",
            ),
            "benefit": (
                "Guna ikut arahan label dan lap dengan kain yang sesuai.",
                "Tutup semula selepas guna dan simpan di tempatnya.",
            ),
            "cta": (
                "Semak permukaan yang sesuai sebelum guna.",
                "Pilih format yang sesuai dengan rutin rumah korang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "HOUSEHOLD_STORAGE": {
        "product_family": "HOUSEHOLD_STORAGE_ORGANIZER",
        "product_type": "HOUSEHOLD_STORAGE",
        "use_case": (
            "open and close",
            "item organization",
            "stacking",
            "before-and-after arrangement without fake transformation",
        ),
        "allowed_scene_strategy": (
            "empty-to-organized storage setup",
            "open-close and compartment demonstration",
            "safe stacking and shelf placement",
        ),
        "allowed_actions": (
            "open and close the storage product",
            "place suitable household items into compartments",
            "stack only as the product design allows",
            "place the organizer on a shelf or counter",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "overload, hang, or stack the product beyond its design",
        ),
        "scene_contexts": (
            "clean counter with items ready to organize",
            "open shelf with storage compartments visible",
            "drawer or wardrobe organization setup",
        ),
        "camera_routes": (
            "empty organizer top-down to filled compartment reveal",
            "hinge or drawer close-up to shelf wide shot",
            "safe stack side view to organized hero frame",
        ),
        "avatar_hints": (
            "adult household organization buyer",
            "adult creator demonstrating practical storage",
        ),
        "wardrobe_hints": (
            "clean casual homewear",
            "simple practical outfit",
        ),
        "direct_script_slots": {
            "hook": (
                "Buka, susun, terus nampak ruangnya.",
                "Tengok berapa bahagian yang boleh diisi.",
            ),
            "benefit": (
                "Masukkan barang ikut ruang dan tutup semula.",
                "Susun atas rak ikut bentuk produk.",
            ),
            "cta": (
                "Semak ukuran sebelum pilih organizer.",
                "Pilih saiz ikut ruang yang korang ada.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "ELECTRONICS_ACCESSORY": {
        "product_family": "ACCESSORY_SMALL_ITEM",
        "product_type": "ELECTRONICS_ACCESSORY",
        "use_case": (
            "unboxing",
            "connection",
            "device pairing",
            "desk or travel setup",
        ),
        "allowed_scene_strategy": (
            "accessory unbox and connector walkthrough",
            "connect to a compatible device",
            "desk or travel cable setup",
        ),
        "allowed_actions": (
            "show the connector or control clearly",
            "connect the accessory to a compatible device",
            "coil or store the accessory normally",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "connect to an incompatible port or show unsafe electrical use",
        ),
        "scene_contexts": (
            "clean desk with compatible device and accessory",
            "travel pouch cable-organizing setup",
            "connector-detail tabletop",
        ),
        "camera_routes": (
            "connector macro to compatible-device connection",
            "top-down unbox to desk setup",
            "control detail to normal storage frame",
        ),
        "avatar_hints": (
            "adult everyday device user",
            "adult buyer demonstrating a normal setup",
        ),
        "wardrobe_hints": (
            "clean casual desk-work outfit",
            "simple travel-ready styling",
        ),
        "direct_script_slots": {
            "hook": (
                "Tengok kepala sambungan sebelum pasang.",
                "Dari kotak terus masuk setup harian.",
            ),
            "benefit": (
                "Sambung pada port yang sesuai dan tunjuk cara simpan.",
                "Periksa connector dan kawalan sebelum guna.",
            ),
            "cta": (
                "Semak keserasian dengan peranti korang.",
                "Pilih jenis sambungan yang betul.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "ELECTRONICS_SMALL_DEVICE": {
        "product_family": "electronics_wearable",
        "product_type": "ELECTRONICS_SMALL_DEVICE",
        "use_case": (
            "unboxing",
            "power-on",
            "control demonstration",
            "desk or wrist setup",
        ),
        "allowed_scene_strategy": (
            "unbox and identify controls",
            "power-on and screen walkthrough",
            "normal desk or wearable use",
        ),
        "allowed_actions": (
            "remove the device from its packaging",
            "press the correct power or control button",
            "show the screen, indicator, or port",
            "place or wear the device as designed",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "invent software features or display states",
            "show unsafe charging or electrical handling",
        ),
        "scene_contexts": (
            "clean desk unboxing with device controls visible",
            "lifestyle tech setup with compatible accessories",
            "wrist or tabletop scale demonstration",
        ),
        "camera_routes": (
            "box reveal to power-button macro",
            "screen close-up to normal-use medium shot",
            "port detail to device-scale hero",
        ),
        "avatar_hints": (
            "adult everyday technology buyer",
            "adult creator demonstrating only visible verified controls",
        ),
        "wardrobe_hints": (
            "clean smart-casual tech outfit",
            "simple desk-work styling",
        ),
        "direct_script_slots": {
            "hook": (
                "Buka kotak, tekan butang, tengok paparan.",
                "Tengok saiz dan kawalan peranti ni.",
            ),
            "benefit": (
                "Tunjuk butang, port, dan skrin yang memang ada.",
                "Pasang ikut arahan dan guna pada setup yang sesuai.",
            ),
            "cta": (
                "Semak fungsi dan keserasian sebelum pilih.",
                "Pilih model yang sesuai dengan kegunaan korang.",
            ),
        },
        "sensitive_handling_rules": (),
    },
    "TRADITIONAL_HERBAL_OIL": {
        "product_family": "TRADITIONAL_WELLNESS",
        "product_type": "TRADITIONAL_HERBAL_OIL",
        "use_case": (
            "label-forward traditional oil introduction",
            "small external-use application",
            "gentle adult self-care routine",
            "shelf storage and daily portability",
        ),
        "allowed_scene_strategy": (
            "heritage bottle hero with the label visible",
            "cap opening followed by a small external-use application",
            "gentle forearm or wrist self-care massage",
            "daily or nightly shelf-and-bag routine",
        ),
        "allowed_actions": (
            "hold the bottle label-forward",
            "open the cap carefully and prepare a small amount",
            "apply a small amount to an adult forearm or wrist",
            "massage the external area gently as a normal self-care routine",
            "close the cap and store the bottle upright or in a small bag",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "eat, drink, ingest, or taste the oil",
            "apply the oil to eyes, broken skin, or intimate areas",
            "diagnose pain, disease, injury, or an anatomical condition",
            "show treatment, healing, recovery, or before-and-after results",
            "demonstrate use on a child",
            "invent ingredients, efficacy, dosage, or medical endorsement",
        ),
        "scene_contexts": (
            "warm heritage tabletop with the bottle label visible",
            "calm adult wrist or forearm self-care moment",
            "bedside shelf during a quiet nightly routine",
            "small travel bag with the closed bottle stored upright",
        ),
        "camera_routes": (
            "label-forward bottle hero to cap-opening close-up",
            "small external application to gentle forearm massage",
            "night-routine shelf reveal to closed-bottle storage",
            "hand-held portability shot to upright bag placement",
        ),
        "avatar_hints": (
            "adult buyer demonstrating a calm external-use routine",
            "adult creator handling the heritage bottle without outcome claims",
        ),
        "wardrobe_hints": (
            "fully covered neutral everyday clothing with forearm access",
            "modest home-routine styling with no clinical cues",
        ),
        "direct_script_slots": {
            "hook": (
                "Rutin warisan bermula dengan botol dan label yang jelas.",
                "Satu langkah ringkas untuk rutin luaran harian.",
            ),
            "benefit": (
                "Sapu sedikit pada bahagian luaran dan urut dengan lembut.",
                "Tutup semula dan simpan botol dengan kemas selepas guna.",
            ),
            "cta": (
                "Semak label dan ikut arahan penggunaan produk.",
                "Pilih format yang sesuai untuk rutin korang.",
            ),
        },
        "sensitive_handling_rules": (
            "External adult use only; no ingestion, intimate application, or child use.",
            "Scenes demonstrate handling and routine only, never treatment or efficacy.",
            "All application follows the visible product label and uses a small amount.",
        ),
    },
    "HERBAL_ROLL_ON_OIL": {
        "product_family": "TRADITIONAL_WELLNESS",
        "product_type": "HERBAL_ROLL_ON_OIL",
        "use_case": (
            "label-forward herbal roll-on introduction",
            "controlled external roll-on application",
            "gentle adult self-care routine",
            "pocket, shelf, or travel-bag storage",
        ),
        "allowed_scene_strategy": (
            "compact roll-on hero with label and applicator visible",
            "controlled wrist, forearm, or shoulder roll-on application",
            "gentle external self-care routine with no outcome claim",
            "portable daily carry and upright storage",
        ),
        "allowed_actions": (
            "hold the roll-on label-forward",
            "remove the cap and show the intact roll-on applicator",
            "roll a small amount onto an adult wrist, forearm, or covered shoulder area",
            "massage the external area gently only when the label supports it",
            "replace the cap and store the roll-on upright in a pocket or small bag",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "eat, drink, ingest, or taste the roll-on oil",
            "apply the product to eyes, broken skin, or intimate areas",
            "diagnose pain, nerves, disease, injury, or an anatomical condition",
            "show treatment, healing, recovery, or before-and-after results",
            "demonstrate use on a child",
            "invent ingredients, efficacy, dosage, or medical endorsement",
        ),
        "scene_contexts": (
            "clean tabletop with the compact roll-on label visible",
            "calm adult wrist or forearm application moment",
            "everyday desk or bedside self-care routine",
            "small travel bag or pocket portability setup",
        ),
        "camera_routes": (
            "label-forward roll-on hero to intact applicator close-up",
            "controlled external roll to gentle routine context",
            "desk or bedside reveal to capped upright storage",
            "hand-held compact-size shot to travel-bag placement",
        ),
        "avatar_hints": (
            "adult buyer demonstrating only a controlled external roll-on routine",
            "adult creator presenting portability without medical or performance claims",
        ),
        "wardrobe_hints": (
            "fully covered neutral everyday clothing with wrist or forearm access",
            "modest travel or desk-routine styling with no clinical cues",
        ),
        "direct_script_slots": {
            "hook": (
                "Format roll-on untuk rutin luaran yang ringkas.",
                "Pegang, semak label, dan lihat aplikator dengan jelas.",
            ),
            "benefit": (
                "Roll sedikit pada bahagian luaran mengikut arahan label.",
                "Tutup semula dan bawa dalam rutin harian korang.",
            ),
            "cta": (
                "Semak label sebelum guna.",
                "Pilih format mudah bawa untuk rutin korang.",
            ),
        },
        "sensitive_handling_rules": (
            "External adult use only; no ingestion, intimate application, or child use.",
            "The roll-on is presented as a portable routine format, not a treatment.",
            "No pain, nerve, medical, sexual-performance, or guaranteed-result framing.",
        ),
    },
    "SENSITIVE_WELLNESS": {
        "product_family": "SENSITIVE_WELLNESS",
        "product_type": "SENSITIVE_WELLNESS",
        "use_case": (
            "discreet product introduction",
            "sealed packaging walkthrough",
            "private shelf or drawer storage",
            "label and instructions review",
        ),
        "allowed_scene_strategy": (
            "discreet product-only tabletop introduction",
            "sealed pack, label, and instruction walkthrough",
            "private shelf, drawer, or toiletry-bag storage",
            "calm hand-held product presentation with no body demonstration",
        ),
        "allowed_actions": (
            "hold the sealed product label-forward",
            "show the outer packaging and instruction panel",
            "place the product in a private drawer or toiletry bag",
            "point to the label without demonstrating use on the body",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "eat, drink, ingest, or taste the product on camera",
            "apply the product to intimate areas or demonstrate intimate use",
            "show intimate-area, torso, pelvis, or body-part close-ups",
            "show medical-style proof, diagnosis, examination, or before-and-after results",
            "simulate sexual performance or explicit couple interaction",
        ),
        "scene_contexts": (
            "discreet premium tabletop with sealed product only",
            "private bathroom shelf with outer packaging visible",
            "closed drawer or toiletry-bag storage moment",
            "calm label-and-instructions close-up with no body demonstration",
        ),
        "camera_routes": (
            "sealed-pack hero to label and instruction-panel close-up",
            "calm hand-held product reveal to private-shelf placement",
            "top-down toiletry-bag storage with product-only framing",
            "outer-pack detail to discreet product hero",
        ),
        "avatar_hints": (
            "adult buyer presented only in a calm neutral role",
            "adult creator with no body demonstration or intimate performance",
        ),
        "wardrobe_hints": (
            "fully covered neutral smart-casual clothing",
            "modest non-clinical outfit with no body emphasis",
        ),
        "direct_script_slots": {
            "hook": (
                "Produk ni diterangkan secara ringkas dan discreet.",
                "Tengok label dan cara simpan produk ni.",
            ),
            "benefit": (
                "Semak maklumat pada kotak dan ikut arahan penggunaan.",
                "Simpan dengan kemas dan gunakan hanya seperti pada label.",
            ),
            "cta": (
                "Baca butiran produk sebelum membuat pilihan.",
                "Semak arahan dan pilih secara privasi.",
            ),
        },
        "sensitive_handling_rules": (
            "Product-only or sealed-pack scenes are the default.",
            "No ingestion, intimate application, body close-up, or medical-style proof.",
            "Dialogue stays discreet, factual, and free of medical or performance promises.",
        ),
    },
    "BOTTOM_APPAREL": _simple_scene_strategy(
        product_family="fashion_apparel",
        product_type="BOTTOM_APPAREL",
        use_case=("waist and length check", "fabric and seam review"),
        allowed_scene_strategy=(
            "hanger-to-waist-and-length inspection",
            "fabric, pocket, seam, and hem walkthrough",
        ),
        allowed_actions=(
            "hold the garment on a hanger and show the full length",
            "show waistband, pockets, seams, and hem without distorting fit",
        ),
        scene_contexts=("clean wardrobe rail", "full-length mirror area"),
        camera_routes=("full garment frame to waistband and hem details",),
        avatar_hints=("adult apparel buyer matching the intended size range",),
        wardrobe_hints=("neutral base layer suitable for a fit check",),
        hook=("Tengok potongan seluar dari pinggang sampai hujung.",),
        benefit=("Tunjuk pinggang, poket, jahitan dan labuh dengan jelas.",),
        cta=("Semak ukuran sebelum pilih saiz.",),
    ),
    "BODY_CLEANSER": _simple_scene_strategy(
        product_family="BEAUTY_PERSONAL_CARE",
        product_type="BODY_CLEANSER",
        use_case=("bathroom shelf routine", "texture and dispenser check"),
        allowed_scene_strategy=(
            "label-forward shower-shelf product walkthrough",
            "small texture dispense on a clean hand",
        ),
        allowed_actions=(
            "show the label and dispenser",
            "dispense a small amount onto a wet palm without body exposure",
        ),
        scene_contexts=("clean bathroom shelf", "sink-side hand demonstration"),
        camera_routes=("label close-up to controlled palm dispense",),
        avatar_hints=("adult personal-care buyer",),
        wardrobe_hints=("modest casual homewear",),
        hook=("Nak lihat tekstur pencuci badan ni?",),
        benefit=("Pam sedikit pada tapak tangan dan tunjuk cara bilas ikut label.",),
        cta=("Semak saiz dan arahan penggunaan.",),
        forbidden_actions=("show intimate body areas",),
    ),
    "FACIAL_CLEANSER": _simple_scene_strategy(
        product_family="BEAUTY_PERSONAL_CARE",
        product_type="FACIAL_CLEANSER",
        use_case=("sink-side face cleansing", "texture and rinse routine"),
        allowed_scene_strategy=(
            "small fingertip dispense beside a sink",
            "gentle external face-cleansing motion and rinse",
        ),
        allowed_actions=(
            "dispense a small amount onto clean fingertips",
            "demonstrate gentle external use while avoiding the eyes",
        ),
        scene_contexts=("bright sink-side skincare setup",),
        camera_routes=("product label to fingertip texture and rinse setup",),
        avatar_hints=("adult skincare buyer",),
        wardrobe_hints=("clean modest homewear",),
        hook=("Tengok sukatan pencuci muka untuk satu rutin.",),
        benefit=("Ambil sedikit dan guna dengan lembut ikut arahan label.",),
        cta=("Semak cara guna sebelum pilih.",),
        forbidden_actions=("apply inside the eyes or mouth",),
    ),
    "COMPLEXION_MAKEUP": _simple_scene_strategy(
        product_family="BEAUTY_PERSONAL_CARE",
        product_type="COMPLEXION_MAKEUP",
        use_case=("shade check", "small face-area application"),
        allowed_scene_strategy=(
            "jawline shade comparison",
            "small controlled complexion-makeup application",
        ),
        allowed_actions=(
            "show one small swatch near the jawline",
            "blend a small amount without before-and-after claims",
        ),
        scene_contexts=("bright vanity mirror",),
        camera_routes=("packaging and shade label to jawline swatch",),
        avatar_hints=("adult makeup buyer",),
        wardrobe_hints=("neutral top that keeps focus on shade",),
        hook=("Nak semak shade sebelum pilih?",),
        benefit=("Swatch sedikit dan lihat padanan dalam cahaya yang jelas.",),
        cta=("Semak pilihan shade yang tersedia.",),
    ),
    "NAIL_COLOR": _simple_scene_strategy(
        product_family="BEAUTY_PERSONAL_CARE",
        product_type="NAIL_COLOR",
        use_case=("single-nail shade check", "brush and bottle detail"),
        allowed_scene_strategy=(
            "brush and shade reveal",
            "single-nail application on a clean manicure surface",
        ),
        allowed_actions=(
            "show the brush and bottle label",
            "apply one thin coat to a clean fingernail",
        ),
        scene_contexts=("clean manicure table",),
        camera_routes=("bottle label to brush and single-nail close-up",),
        avatar_hints=("adult nail-colour buyer",),
        wardrobe_hints=("clean casual styling",),
        hook=("Tengok warna sebenar pada satu sapuan.",),
        benefit=("Tunjuk berus, tekstur dan satu lapisan dengan jelas.",),
        cta=("Semak pilihan warna.",),
        forbidden_actions=("apply near eyes or mouth",),
    ),
    "FACIAL_SERUM": _simple_scene_strategy(
        product_family="BEAUTY_PERSONAL_CARE",
        product_type="FACIAL_SERUM",
        use_case=("dropper amount check", "external skincare routine"),
        allowed_scene_strategy=(
            "dropper and texture walkthrough",
            "small external face-serum application",
        ),
        allowed_actions=(
            "show one controlled drop on the back of a clean hand",
            "pat a small amount onto external facial skin while avoiding eyes",
        ),
        scene_contexts=("bright skincare vanity",),
        camera_routes=("dropper macro to texture and gentle application",),
        avatar_hints=("adult skincare buyer",),
        wardrobe_hints=("clean neutral homewear",),
        hook=("Tengok tekstur serum dan sukatan satu rutin.",),
        benefit=("Guna sedikit dan sapu ikut arahan label.",),
        cta=("Semak ramuan dan cara guna.",),
        forbidden_actions=("claim clinical treatment or guaranteed skin change",),
    ),
    "MASCARA": _simple_scene_strategy(
        product_family="BEAUTY_PERSONAL_CARE",
        product_type="MASCARA",
        use_case=("wand check", "controlled lash application"),
        allowed_scene_strategy=(
            "mascara wand and brush detail",
            "single controlled upper-lash application",
        ),
        allowed_actions=(
            "show the wand and remove excess product at the tube edge",
            "apply carefully to upper lashes while keeping the eye steady",
        ),
        scene_contexts=("bright vanity mirror",),
        camera_routes=("tube label to wand macro and steady mirror frame",),
        avatar_hints=("adult makeup buyer",),
        wardrobe_hints=("neutral beauty-routine outfit",),
        hook=("Tengok bentuk berus maskara ni.",),
        benefit=("Tunjuk berus dan satu sapuan terkawal pada bulu mata.",),
        cta=("Semak jenis berus sebelum pilih.",),
        forbidden_actions=("touch the eyeball or share the applicator",),
        sensitive_handling_rules=("keep the applicator away from the eyeball",),
    ),
    "EYELINER": _simple_scene_strategy(
        product_family="BEAUTY_PERSONAL_CARE",
        product_type="EYELINER",
        use_case=("tip check", "controlled external lash-line application"),
        allowed_scene_strategy=(
            "eyeliner tip and hand-swatch detail",
            "short external upper-lash-line demonstration",
        ),
        allowed_actions=(
            "show the tip and draw one line on the back of a clean hand",
            "apply a short line along the external upper lash line",
        ),
        scene_contexts=("bright vanity mirror",),
        camera_routes=("tip macro to hand swatch and steady mirror frame",),
        avatar_hints=("adult makeup buyer",),
        wardrobe_hints=("neutral beauty-routine outfit",),
        hook=("Tengok hujung eyeliner dan garisan yang dibuat.",),
        benefit=("Swatch satu garisan sebelum guna dekat garis mata luar.",),
        cta=("Semak bentuk hujung dan warna.",),
        forbidden_actions=("apply inside the eye or waterline",),
        sensitive_handling_rules=("keep the tip outside the eye",),
    ),
    "WELLNESS_SUPPLEMENT": _simple_scene_strategy(
        product_family="health_supplement",
        product_type="WELLNESS_SUPPLEMENT",
        use_case=("sealed-pack review", "label-directed serving setup"),
        allowed_scene_strategy=(
            "sealed pack and nutrition-label walkthrough",
            "label-directed serving placed beside water",
        ),
        allowed_actions=(
            "show the intact seal and serving directions",
            "place the label-directed serving beside a glass of water",
        ),
        scene_contexts=("clean table with pack and water",),
        camera_routes=("seal and label close-up to serving setup",),
        avatar_hints=("adult supplement buyer",),
        wardrobe_hints=("ordinary non-clinical casual wear",),
        hook=("Semak label dan sukatan sebelum ambil.",),
        benefit=("Ikut arahan hidangan pada label produk.",),
        cta=("Baca label dan semak kesesuaian terlebih dahulu.",),
        forbidden_actions=("promise treatment, cure, energy, strength, or body change",),
        sensitive_handling_rules=("all health outcomes remain claim-gated",),
    ),
    "PACKAGED_SNACK": _simple_scene_strategy(
        product_family="food_packaged",
        product_type="PACKAGED_SNACK",
        use_case=("sealed-pack opening", "normal portion serving"),
        allowed_scene_strategy=(
            "sealed snack pack to bowl serving",
            "portion and texture walkthrough",
        ),
        allowed_actions=(
            "show the intact seal and open the pack cleanly",
            "serve a normal portion into a clean bowl",
        ),
        scene_contexts=("clean snack table",),
        camera_routes=("pack label and seal to portion close-up",),
        avatar_hints=("adult snack buyer",),
        wardrobe_hints=("simple casual wear",),
        hook=("Buka pek dan lihat saiz hidangannya.",),
        benefit=("Tuang satu hidangan biasa supaya tekstur jelas.",),
        cta=("Semak rasa dan saiz pek.",),
    ),
    "PET_FOOD": _simple_scene_strategy(
        product_family="pet_food",
        product_type="PET_FOOD",
        use_case=("pack and feeding-guide review", "pet-bowl serving"),
        allowed_scene_strategy=(
            "feeding-guide and pack walkthrough",
            "measured serving into a clean pet bowl",
        ),
        allowed_actions=(
            "show the species and feeding directions on the label",
            "serve a label-directed portion into a clean pet bowl",
        ),
        scene_contexts=("clean pet-feeding area",),
        camera_routes=("pack label to measured pet-bowl serving",),
        avatar_hints=("adult pet owner",),
        wardrobe_hints=("clean casual homewear",),
        hook=("Semak label makanan haiwan sebelum hidang.",),
        benefit=("Sukat ikut panduan dan letak dalam mangkuk bersih.",),
        cta=("Semak spesies, umur dan panduan hidangan.",),
        forbidden_actions=("serve pet food as human food",),
    ),
    "PACKAGED_BEVERAGE": _simple_scene_strategy(
        product_family="food_beverage",
        product_type="PACKAGED_BEVERAGE",
        use_case=("sealed beverage review", "normal pour"),
        allowed_scene_strategy=(
            "pack and serving-label walkthrough",
            "normal pour into a clean glass",
        ),
        allowed_actions=(
            "show the intact seal and label",
            "pour a normal serving into a clean glass",
        ),
        scene_contexts=("clean drink-preparation table",),
        camera_routes=("label and seal to controlled glass pour",),
        avatar_hints=("adult beverage buyer",),
        wardrobe_hints=("simple casual wear",),
        hook=("Tengok pek dan cara hidang minuman ni.",),
        benefit=("Tuang satu hidangan biasa supaya warna dan tekstur jelas.",),
        cta=("Semak rasa, ramuan dan saiz pek.",),
    ),
    "PANTRY_INGREDIENT": _simple_scene_strategy(
        product_family="food_packaged",
        product_type="PANTRY_INGREDIENT",
        use_case=("ingredient measuring", "recipe preparation"),
        allowed_scene_strategy=(
            "sealed ingredient pack to measured portion",
            "ingredient placed beside the intended recipe",
        ),
        allowed_actions=(
            "show the label and measure a recipe-appropriate amount",
            "place the ingredient beside the prepared dish",
        ),
        scene_contexts=("clean kitchen ingredient counter",),
        camera_routes=("pack label to measured ingredient and dish",),
        avatar_hints=("adult home cook",),
        wardrobe_hints=("clean kitchen wear",),
        hook=("Semak bahan dan sukatan sebelum masak.",),
        benefit=("Sukat ikut resipi dan tunjuk hasil hidangan.",),
        cta=("Semak jenis dan saiz pek.",),
    ),
    "BEDDING": _simple_scene_strategy(
        product_family="home_textiles",
        product_type="BEDDING",
        use_case=("size and fabric check", "bed setup"),
        allowed_scene_strategy=(
            "folded bedding to full bed setup",
            "fabric edge, seam, and size-label walkthrough",
        ),
        allowed_actions=(
            "unfold the bedding on a clean bed",
            "show fabric, seams, closures, and size label",
        ),
        scene_contexts=("clean bedroom with neutral bed",),
        camera_routes=("folded pack to full-bed view and fabric macro",),
        avatar_hints=("adult home-textile buyer",),
        wardrobe_hints=("clean casual homewear",),
        hook=("Tengok saiz dan fabrik sebelum pasang.",),
        benefit=("Bentang atas katil dan tunjuk jahitan serta label saiz.",),
        cta=("Semak ukuran katil sebelum pilih.",),
    ),
    "RUG_MAT": _simple_scene_strategy(
        product_family="home_textiles",
        product_type="RUG_MAT",
        use_case=("floor placement", "edge and backing check"),
        allowed_scene_strategy=(
            "rolled mat to flat floor placement",
            "surface, edge, and backing walkthrough",
        ),
        allowed_actions=(
            "unroll the mat on a clean dry floor",
            "show the surface, edge, thickness, and backing",
        ),
        scene_contexts=("clean dry home floor",),
        camera_routes=("rolled mat to top-down placement and edge macro",),
        avatar_hints=("adult home buyer",),
        wardrobe_hints=("clean casual homewear",),
        hook=("Tengok saiz tikar bila dibentang.",),
        benefit=("Tunjuk permukaan, tepi dan bahagian belakang dengan jelas.",),
        cta=("Semak ukuran ruang sebelum pilih.",),
        forbidden_actions=("claim slip prevention without verified evidence",),
    ),
    "BOOK": _simple_scene_strategy(
        product_family="books_media",
        product_type="BOOK",
        use_case=("cover and contents review", "reading setup"),
        allowed_scene_strategy=(
            "cover-to-contents walkthrough",
            "normal seated reading setup",
        ),
        allowed_actions=(
            "show the cover, spine, contents page, and sample spread",
            "hold the book naturally in a reading position",
        ),
        scene_contexts=("clean reading desk or chair",),
        camera_routes=("cover close-up to contents and page spread",),
        avatar_hints=("adult reader",),
        wardrobe_hints=("simple casual wear",),
        hook=("Tengok kulit, kandungan dan susun atur buku.",),
        benefit=("Buka beberapa halaman supaya format bacaan jelas.",),
        cta=("Semak tajuk dan edisi sebelum pilih.",),
    ),
    "HOME_FAN": _simple_scene_strategy(
        product_family="home_equipment",
        product_type="HOME_FAN",
        use_case=("control and guard check", "normal airflow setup"),
        allowed_scene_strategy=(
            "fan assembly and control walkthrough",
            "stable placement and indicator demonstration",
        ),
        allowed_actions=(
            "show the guard, base, cable, controls, and indicator",
            "place the fan on a stable surface and select one control",
        ),
        scene_contexts=("clean ventilated room",),
        camera_routes=("full device to guard, control, and base details",),
        avatar_hints=("adult home-appliance buyer",),
        wardrobe_hints=("simple casual homewear",),
        hook=("Tengok kawalan dan binaan kipas ni.",),
        benefit=("Tunjuk pelindung, tapak dan satu kawalan dengan jelas.",),
        cta=("Semak arahan dan spesifikasi produk.",),
        forbidden_actions=("put fingers or loose objects through the guard",),
    ),
    "VACUUM_CLEANER": _simple_scene_strategy(
        product_family="home_equipment",
        product_type="VACUUM_CLEANER",
        use_case=("attachment check", "small dry-floor demonstration"),
        allowed_scene_strategy=(
            "vacuum attachments and controls walkthrough",
            "short normal dry-floor cleaning pass",
        ),
        allowed_actions=(
            "show the nozzle, bin, filter, controls, and charging port",
            "make one short pass over a dry compatible floor",
        ),
        scene_contexts=("clean dry-floor home area",),
        camera_routes=("full device to attachment details and floor pass",),
        avatar_hints=("adult home-appliance buyer",),
        wardrobe_hints=("practical casual homewear",),
        hook=("Tengok aksesori dan kawalan vakum ni.",),
        benefit=("Pasang muncung yang betul dan buat satu laluan pendek.",),
        cta=("Semak permukaan sesuai dan arahan produk.",),
        forbidden_actions=("vacuum liquids unless the verified model permits it",),
    ),
    "VACUUM_SEALER": _simple_scene_strategy(
        product_family="home_equipment",
        product_type="VACUUM_SEALER",
        use_case=("bag placement", "seal-cycle walkthrough"),
        allowed_scene_strategy=(
            "food-sealer controls and bag placement",
            "single label-directed seal cycle",
        ),
        allowed_actions=(
            "place a compatible bag edge into the sealer",
            "close the lid and run one control according to instructions",
        ),
        scene_contexts=("clean dry kitchen counter",),
        camera_routes=("machine controls to bag edge and finished seal",),
        avatar_hints=("adult kitchen-appliance buyer",),
        wardrobe_hints=("clean kitchen wear",),
        hook=("Tengok cara letak beg pada mesin sealer.",),
        benefit=("Susun tepi beg, tutup penutup dan ikut satu kitaran.",),
        cta=("Semak jenis beg dan arahan mesin.",),
        forbidden_actions=("seal hot, sharp, or incompatible contents",),
    ),
    "GENERIC_FALLBACK": {
        "product_family": "GENERIC_UNCLASSIFIED",
        "product_type": "GENERIC_PRODUCT",
        "use_case": (
            "label-forward product introduction",
            "packaging walkthrough",
            "product-appropriate everyday context",
        ),
        "allowed_scene_strategy": (
            "clean product introduction",
            "label and packaging walkthrough",
            "product-appropriate everyday setup",
        ),
        "allowed_actions": (
            "hold the product label-forward",
            "show the packaging, opening, or control without inventing use",
            "place the product in a plausible everyday context",
        ),
        "forbidden_actions": (
            *_COMMON_PHYSICS_FORBIDDEN,
            *_COMMON_CLAIM_FORBIDDEN,
            "invent an action not supported by the product type",
        ),
        "scene_contexts": (
            "Modern minimalist kitchen",
            "Bright living room",
            "Professional studio",
        ),
        "camera_routes": (
            "Close-up tracking",
            "Static macro shot",
            "Slow pan",
        ),
        "avatar_hints": (
            "adult everyday buyer",
            "adult creator with neutral product-handling behavior",
        ),
        "wardrobe_hints": (
            "clean neutral casual clothing",
            "simple product-appropriate styling",
        ),
        "direct_script_slots": {
            "hook": (
                "Tengok produk dan cara pegangnya dengan jelas.",
                "Mula dengan label dan bentuk produk ni.",
            ),
            "benefit": (
                "Tunjuk bahagian penting tanpa mereka cara guna.",
                "Guna hanya dalam konteks yang sesuai dengan produk.",
            ),
            "cta": (
                "Semak butiran produk sebelum memilih.",
                "Pilih ikut kegunaan yang korang perlukan.",
            ),
        },
        "sensitive_handling_rules": (),
    },
}


def _catalog_specific_scene(
    *,
    product_family: str,
    product_type: str,
    use_case: str,
    scene: str,
    actions: tuple[str, str],
    context: str,
    hook: str,
    benefit: str,
    cta: str,
    forbidden_actions: tuple[str, ...] = (),
    sensitive_handling_rules: tuple[str, ...] = (),
) -> SceneStrategyEntry:
    """Build one exact-type scene grammar from reviewed Product Truth."""

    return _simple_scene_strategy(
        product_family=product_family,
        product_type=product_type,
        use_case=(use_case,),
        allowed_scene_strategy=(scene,),
        allowed_actions=actions,
        scene_contexts=(context,),
        camera_routes=("label and product detail to the verified physical action",),
        avatar_hints=("adult buyer demonstrating only the verified action",),
        wardrobe_hints=("clean neutral product-appropriate clothing",),
        hook=(hook,),
        benefit=(benefit,),
        cta=(cta,),
        forbidden_actions=forbidden_actions,
        sensitive_handling_rules=sensitive_handling_rules,
    )


SCENE_STRATEGIES.update(
    {
        "FACE_MASK": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="FACE_MASK",
            use_case="packet and mask-texture check",
            scene="controlled external face-mask application",
            actions=(
                "show the packet, label, and mask texture",
                "apply a thin external layer while avoiding eyes and lips",
            ),
            context="bright sink-side skincare setup",
            hook="Tengok tekstur masker sebelum sapu.",
            benefit="Sapu nipis dan elakkan mata serta bibir.",
            cta="Semak masa penggunaan pada label.",
            forbidden_actions=("apply inside the eyes, nose, or mouth",),
        ),
        "MOISTURIZER": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="MOISTURIZER",
            use_case="dispenser and texture check",
            scene="small external moisturizer application",
            actions=(
                "show the label and dispense one small amount",
                "spread the amount on clean external skin without outcome claims",
            ),
            context="bright skincare vanity",
            hook="Tengok tekstur pelembap dan sukatan satu rutin.",
            benefit="Guna sedikit pada kulit luar ikut arahan label.",
            cta="Semak ramuan dan cara penggunaan.",
        ),
        "SUNSCREEN": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="SUNSCREEN",
            use_case="label and external application check",
            scene="label-directed sunscreen routine",
            actions=(
                "show the visible sun-protection label without extending its claims",
                "dispense a controlled amount and apply externally as directed",
            ),
            context="bright morning skincare setup",
            hook="Semak label pelindung matahari sebelum guna.",
            benefit="Sapu pada kulit luar mengikut arahan produk.",
            cta="Rujuk label untuk sukatan dan penggunaan semula.",
            forbidden_actions=("invent SPF performance or protection duration",),
        ),
        "EYE_TREATMENT": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="EYE_TREATMENT",
            use_case="applicator and external eye-area check",
            scene="controlled outer eye-area application",
            actions=(
                "show the applicator and a very small amount",
                "dot externally around the orbital area while avoiding the eye",
            ),
            context="steady seated vanity setup",
            hook="Tengok aplikator rawatan kawasan mata.",
            benefit="Guna sedikit di kawasan luar dan jauhkan daripada mata.",
            cta="Ikut arahan label dengan teliti.",
            forbidden_actions=("apply inside the eye or on the waterline",),
            sensitive_handling_rules=("keep all product outside the eye",),
        ),
        "MAKEUP_SETTING_SPRAY": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="MAKEUP_SETTING_SPRAY",
            use_case="nozzle and spray-pattern check",
            scene="label-directed external setting-spray application",
            actions=(
                "show the nozzle and label-directed spray distance",
                "spray externally with eyes and mouth closed",
            ),
            context="ventilated bright vanity area",
            hook="Semak muncung dan jarak semburan.",
            benefit="Sembur ikut label dengan mata dan mulut tertutup.",
            cta="Semak arahan sebelum guna.",
            forbidden_actions=("spray into eyes, mouth, or an unventilated space",),
        ),
        "EYEBROW_MAKEUP": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="EYEBROW_MAKEUP",
            use_case="tip and shade check",
            scene="short external eyebrow-detail demonstration",
            actions=(
                "show the pencil, powder, or applicator tip",
                "make short controlled strokes on the external eyebrow",
            ),
            context="bright vanity mirror",
            hook="Tengok hujung aplikator dan warna kening.",
            benefit="Buat sapuan pendek supaya bentuknya jelas.",
            cta="Semak shade sebelum pilih.",
            forbidden_actions=("apply inside the eye",),
        ),
        "EYESHADOW": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="EYESHADOW",
            use_case="palette and shade check",
            scene="single-shade external eyelid demonstration",
            actions=(
                "show the palette shade and clean brush",
                "apply one shade to the external eyelid with the eye closed",
            ),
            context="bright vanity mirror",
            hook="Tengok satu shade daripada palet ini.",
            benefit="Sapu dengan berus bersih pada kelopak luar.",
            cta="Semak pilihan warna.",
            forbidden_actions=("apply inside the eye or share the applicator",),
        ),
        "FALSE_EYELASHES": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="FALSE_EYELASHES",
            use_case="lash-strip and size check",
            scene="product-only lash-strip fitting walkthrough",
            actions=(
                "show the lash strip, band, and pack label",
                "measure the strip beside a closed eyelid without applying adhesive",
            ),
            context="steady seated vanity setup",
            hook="Tengok bentuk dan panjang strip bulu mata.",
            benefit="Ukur pada mata tertutup sebelum ikut arahan pemasangan.",
            cta="Semak saiz dan arahan pelekat.",
            forbidden_actions=("apply unverified adhesive or touch the eyeball",),
            sensitive_handling_rules=("adhesive use remains label-directed",),
        ),
        "FACE_PRIMER": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="FACE_PRIMER",
            use_case="texture and small-amount check",
            scene="controlled external primer application",
            actions=(
                "show the dispenser and one small amount",
                "spread the amount on clean external facial skin",
            ),
            context="bright vanity mirror",
            hook="Tengok tekstur primer sebelum solekan.",
            benefit="Guna sedikit dan ratakan pada kulit luar.",
            cta="Semak arahan produk.",
        ),
        "MAKEUP_SET": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="MAKEUP_SET",
            use_case="set inventory and applicator check",
            scene="makeup-set component walkthrough",
            actions=(
                "lay out each included item without inventing missing components",
                "show one clean applicator beside its matching product",
            ),
            context="clean organized vanity table",
            hook="Semak semua item dalam set solekan ini.",
            benefit="Padankan setiap aplikator dengan produknya.",
            cta="Semak kandungan set sebelum pilih.",
            forbidden_actions=("share applicators between people",),
        ),
        "FACE_POWDER": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="FACE_POWDER",
            use_case="pan, shade, and applicator check",
            scene="light external face-powder application",
            actions=(
                "show the powder pan, shade, and clean applicator",
                "apply a light amount to external facial skin",
            ),
            context="bright vanity mirror",
            hook="Tengok shade dan tekstur bedak.",
            benefit="Ambil sedikit dengan aplikator bersih.",
            cta="Semak shade sebelum pilih.",
            forbidden_actions=("inhale or blow loose powder toward the face",),
        ),
        "BODY_OIL": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="BODY_OIL",
            use_case="bottle and external-use check",
            scene="small external body-oil application",
            actions=(
                "show the bottle label and dispense a small amount",
                "spread the oil gently on an adult forearm",
            ),
            context="calm product-only self-care table",
            hook="Tengok tekstur minyak badan ini.",
            benefit="Guna sedikit pada bahagian luar dan urut perlahan.",
            cta="Semak label sebelum guna.",
            forbidden_actions=("ingest or apply to intimate areas",),
            sensitive_handling_rules=("external adult use only",),
        ),
        "BODY_EXFOLIANT": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="BODY_EXFOLIANT",
            use_case="texture and gentle-use check",
            scene="controlled external exfoliant demonstration",
            actions=(
                "show a small amount and the visible texture",
                "massage gently on a wet adult forearm without abrasion",
            ),
            context="clean sink-side setup",
            hook="Tengok tekstur skrub sebelum guna.",
            benefit="Urut perlahan pada kulit luar tanpa tekanan kuat.",
            cta="Semak kekerapan pada label.",
            forbidden_actions=("scrub broken, irritated, or intimate skin",),
        ),
        "DEODORANT": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="DEODORANT",
            use_case="applicator and label check",
            scene="product-only deodorant applicator walkthrough",
            actions=(
                "show the sealed product, label, and applicator",
                "open and close the applicator without body exposure",
            ),
            context="clean bathroom shelf",
            hook="Semak jenis aplikator deodoran ini.",
            benefit="Tunjuk cara buka dan tutup dengan bersih.",
            cta="Ikut arahan penggunaan pada label.",
            forbidden_actions=("show intimate body exposure or apply to broken skin",),
        ),
        "HAIR_WASH": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="HAIR_WASH",
            use_case="dispenser and wash-step check",
            scene="label-directed hair-wash demonstration",
            actions=(
                "show the bottle and dispense a small amount into a wet palm",
                "work the product through wet hair while avoiding the eyes",
            ),
            context="clean shower-side haircare setup",
            hook="Tengok sukatan untuk satu cucian rambut.",
            benefit="Ratakan pada rambut basah dan bilas ikut label.",
            cta="Semak jenis rambut dan arahan.",
            forbidden_actions=("apply inside the eyes or ingest the product",),
        ),
        "HAIR_COLOR": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="HAIR_COLOR",
            use_case="sealed-kit and safety-label check",
            scene="product-only hair-colour kit walkthrough",
            actions=(
                "show every sealed component and the colour label",
                "point to patch-test and mixing instructions without opening chemicals",
            ),
            context="dry ventilated product-review table",
            hook="Semak warna dan semua komponen kit ini.",
            benefit="Baca arahan ujian tampalan sebelum mencampur.",
            cta="Ikut panduan keselamatan pada label.",
            forbidden_actions=("mix chemicals or apply colour without label proof",),
            sensitive_handling_rules=("patch-test instructions remain mandatory",),
        ),
        "HAIR_TREATMENT": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="HAIR_TREATMENT",
            use_case="texture and hair-length application check",
            scene="small label-directed hair-treatment application",
            actions=(
                "show the container and a small amount of product",
                "spread the amount through hair lengths as directed",
            ),
            context="clean haircare vanity",
            hook="Tengok tekstur rawatan rambut ini.",
            benefit="Guna sedikit pada bahagian rambut yang diarahkan.",
            cta="Semak tempoh dan cara bilas.",
            forbidden_actions=("invent scalp treatment or guaranteed hair growth",),
        ),
        "MAKEUP_REMOVER": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="MAKEUP_REMOVER",
            use_case="dispenser and removal check",
            scene="hand-swatch makeup-removal demonstration",
            actions=(
                "place a small amount on a clean cotton pad",
                "remove one makeup swatch from the back of a clean hand",
            ),
            context="bright sink-side setup",
            hook="Tengok cara remover angkat satu swatch.",
            benefit="Guna kapas bersih dan lap dengan lembut.",
            cta="Semak arahan untuk kawasan mata.",
            forbidden_actions=("rub inside the eye or reuse a dirty pad",),
        ),
        "LIP_TREATMENT": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="LIP_TREATMENT",
            use_case="applicator and external-lip check",
            scene="controlled external lip-treatment application",
            actions=(
                "show the applicator and a small amount",
                "apply a thin layer to the external lips",
            ),
            context="clean vanity mirror",
            hook="Tengok aplikator rawatan bibir ini.",
            benefit="Sapu nipis pada bibir luar ikut label.",
            cta="Semak ramuan sebelum guna.",
            forbidden_actions=("ingest or claim medical lip treatment",),
        ),
        "ORAL_CARE": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="ORAL_CARE",
            use_case="label-directed brushing setup",
            scene="toothbrush amount and normal brushing walkthrough",
            actions=(
                "show the label and place a small label-directed amount on a toothbrush",
                "demonstrate normal brushing without swallowing the product",
            ),
            context="clean bathroom sink",
            hook="Semak sukatan produk penjagaan mulut.",
            benefit="Berus seperti biasa dan jangan telan produk.",
            cta="Ikut arahan pada label.",
            forbidden_actions=("swallow the product or promise whitening outcomes",),
            sensitive_handling_rules=("no dental-treatment or guaranteed-result claim",),
        ),
        "FEMININE_HYGIENE": _catalog_specific_scene(
            product_family="SENSITIVE_WELLNESS",
            product_type="FEMININE_HYGIENE",
            use_case="sealed-pack and product-layer check",
            scene="product-only feminine-hygiene walkthrough",
            actions=(
                "show the sealed pack, size label, and outer instructions",
                "unwrap one item on a clean table and show its layers",
            ),
            context="discreet clean product-review table",
            hook="Semak saiz dan bentuk produk dengan discreet.",
            benefit="Buka satu pek dan tunjuk lapisan tanpa demonstrasi badan.",
            cta="Semak saiz dan arahan pada pek.",
            forbidden_actions=("show intimate use, body exposure, or medical claims",),
            sensitive_handling_rules=("product-only scenes are mandatory",),
        ),
        "TOP_APPAREL": _catalog_specific_scene(
            product_family="fashion_apparel",
            product_type="TOP_APPAREL",
            use_case="upper-garment construction check",
            scene="hanger-to-shoulder-and-hem walkthrough",
            actions=(
                "hold the top on a hanger and show its full front and back",
                "show collar, shoulder, sleeve, seam, and hem details",
            ),
            context="clean wardrobe rail",
            hook="Tengok potongan baju dari bahu sampai labuh.",
            benefit="Tunjuk kolar, lengan, jahitan dan kain.",
            cta="Semak ukuran sebelum pilih saiz.",
        ),
        "UNDERGARMENT": _catalog_specific_scene(
            product_family="fashion_apparel",
            product_type="UNDERGARMENT",
            use_case="garment construction and size-label check",
            scene="product-only undergarment walkthrough",
            actions=(
                "lay the garment flat and show the size label",
                "show band, strap, seam, and fastening details without try-on",
            ),
            context="private clean flat-lay table",
            hook="Semak struktur dan label saiz pakaian dalam.",
            benefit="Tunjuk jalur, tali dan jahitan tanpa try-on.",
            cta="Rujuk carta ukuran sebelum pilih.",
            forbidden_actions=("show intimate try-on or body exposure",),
            sensitive_handling_rules=("product-only demonstration is mandatory",),
        ),
        "SLEEPWEAR": _catalog_specific_scene(
            product_family="fashion_apparel",
            product_type="SLEEPWEAR",
            use_case="sleepwear fabric and set check",
            scene="hanger and flat-lay sleepwear walkthrough",
            actions=(
                "show every sleepwear piece on hangers or a clean flat lay",
                "show fabric, waistband, buttons, seams, and hem",
            ),
            context="calm bedroom wardrobe area",
            hook="Tengok semua bahagian set pakaian tidur.",
            benefit="Semak kain, pinggang, butang dan jahitan.",
            cta="Rujuk ukuran sebelum pilih.",
        ),
        "DRESS": _catalog_specific_scene(
            product_family="fashion_apparel",
            product_type="DRESS",
            use_case="dress silhouette and length check",
            scene="hanger-to-full-length dress walkthrough",
            actions=(
                "hold the dress on a hanger and show the full silhouette",
                "show neckline, waist, seams, and hem without distorting fit",
            ),
            context="full-length wardrobe area",
            hook="Tengok siluet dress dari atas sampai labuh.",
            benefit="Semak leher, pinggang, jahitan dan panjang.",
            cta="Rujuk ukuran sebelum pilih saiz.",
        ),
        "FOOTWEAR": _catalog_specific_scene(
            product_family="fashion_footwear",
            product_type="FOOTWEAR",
            use_case="sole, strap, and size-label check",
            scene="pair and outsole footwear walkthrough",
            actions=(
                "show the matching pair, size label, and upper construction",
                "turn one shoe to show the sole, strap, and fastening",
            ),
            context="clean footwear display bench",
            hook="Semak tapak, tali dan label saiz.",
            benefit="Pusing kasut untuk lihat binaan atas dan bawah.",
            cta="Rujuk ukuran kaki sebelum pilih.",
        ),
        "FROZEN_FOOD": _catalog_specific_scene(
            product_family="food_packaged",
            product_type="FROZEN_FOOD",
            use_case="cold-pack and cooking-instruction check",
            scene="sealed frozen-food pack to label-directed cooking setup",
            actions=(
                "show the intact cold pack, expiry information, and cooking directions",
                "prepare one portion using only the label-directed cooking method",
            ),
            context="clean kitchen beside the appropriate cooking appliance",
            hook="Semak pek sejuk dan arahan memasak.",
            benefit="Masak satu bahagian mengikut arahan label.",
            cta="Simpan dan masak pada suhu yang dinyatakan.",
            forbidden_actions=("taste raw frozen food or break cold-storage rules",),
        ),
        "CURTAIN": _catalog_specific_scene(
            product_family="home_textiles",
            product_type="CURTAIN",
            use_case="panel dimension and hanging check",
            scene="curtain panel to installed open-close walkthrough",
            actions=(
                "show one panel, heading type, width, and length",
                "hang the panel on a compatible rod and open and close it",
            ),
            context="bright window with a compatible curtain rod",
            hook="Semak lebar, panjang dan jenis kepala langsir.",
            benefit="Gantung satu panel dan tunjuk gerakan buka tutup.",
            cta="Ukur tingkap sebelum pilih.",
        ),
        "WALL_COVERING": _catalog_specific_scene(
            product_family="home_improvement",
            product_type="WALL_COVERING",
            use_case="sheet dimension and sample-placement check",
            scene="measured wall-covering sample installation",
            actions=(
                "measure the sheet and show the pattern repeat",
                "place a small sample on a clean dry compatible surface",
            ),
            context="clean dry wall sample board",
            hook="Semak ukuran dan sambungan corak.",
            benefit="Letak sampel kecil pada permukaan yang sesuai.",
            cta="Ukur dinding sebelum pilih kuantiti.",
            forbidden_actions=("cover electrical outlets or damaged wet surfaces",),
        ),
        "KNITTING_CROCHET": _catalog_specific_scene(
            product_family="craft_hobby",
            product_type="KNITTING_CROCHET",
            use_case="yarn, hook, and stitch check",
            scene="craft-material to short stitch walkthrough",
            actions=(
                "show the yarn label, fibre, colour, and hook or needle size",
                "make a short visible stitch sequence on a small sample",
            ),
            context="well-lit craft table",
            hook="Semak benang dan saiz alat sebelum mula.",
            benefit="Buat beberapa stitch supaya tekstur jelas.",
            cta="Padankan saiz alat dengan label benang.",
            forbidden_actions=("leave sharp tools accessible to children",),
        ),
    }
)


SCENE_STRATEGIES.update(
    {
        "CAR_CARE": _catalog_specific_scene(
            product_family="automotive_care",
            product_type="CAR_CARE",
            use_case="pack, applicator, and sample-panel check",
            scene="car-care product to controlled sample-panel walkthrough",
            actions=(
                "show the sealed pack, label, applicator, and stated surface compatibility",
                "demonstrate a small amount on a clean detached sample panel",
            ),
            context="well-lit ventilated automotive detailing bench",
            hook="Semak label dan kesesuaian permukaan.",
            benefit="Tunjuk aplikasi kecil pada panel sampel.",
            cta="Ikut arahan label sebelum guna pada kenderaan.",
            forbidden_actions=(
                "invent durability or protection claims",
                "apply to a moving or hot vehicle",
            ),
        ),
        "BABY_FEEDING": _catalog_specific_scene(
            product_family="baby_care",
            product_type="BABY_FEEDING",
            use_case="component, fit, and care-instruction check",
            scene="baby-feeding component inspection without feeding simulation",
            actions=(
                "show the sealed item, material label, size, and compatible parts",
                "assemble only the dry empty components on a clean table",
            ),
            context="sanitized bright tabletop away from children",
            hook="Semak saiz dan keserasian komponen.",
            benefit="Pasang komponen kosong supaya bentuknya jelas.",
            cta="Ikut arahan pembersihan dan umur pada label.",
            forbidden_actions=(
                "simulate feeding a real infant",
                "make anti-colic or medical claims",
            ),
            sensitive_handling_rules=(
                "keep all small parts away from children during demonstration",
            ),
        ),
        "BABY_SKINCARE": _catalog_specific_scene(
            product_family="baby_care",
            product_type="BABY_SKINCARE",
            use_case="pack, texture, and label-direction check",
            scene="baby-skincare pack to adult-hand texture demonstration",
            actions=(
                "show the sealed pack, ingredient label, age guidance, and amount",
                "dispense a tiny amount on an adult hand without applying to a baby",
            ),
            context="clean bright baby-care preparation table",
            hook="Semak label dan tekstur produk bayi.",
            benefit="Tunjuk sedikit tekstur pada tangan orang dewasa.",
            cta="Ikut arahan umur dan penggunaan pada label.",
            forbidden_actions=("apply the product to a real infant",),
            sensitive_handling_rules=("never imply treatment of a baby condition",),
        ),
        "BATH_LINEN": _catalog_specific_scene(
            product_family="home_textiles",
            product_type="BATH_LINEN",
            use_case="dimension, weave, and absorbency-material check",
            scene="folded bath linen to measured textile walkthrough",
            actions=(
                "show the full textile, care label, dimensions, weave, and edges",
                "fold and press the dry fabric to show thickness without performance claims",
            ),
            context="bright dry bathroom-supply table",
            hook="Semak saiz, tenunan dan kemasan.",
            benefit="Bentang dan tunjuk ketebalan kain.",
            cta="Rujuk ukuran dan arahan penjagaan.",
        ),
        "STATIONERY": _catalog_specific_scene(
            product_family="stationery",
            product_type="STATIONERY",
            use_case="count, dimensions, and paper-function check",
            scene="stationery pack to short desk-use walkthrough",
            actions=(
                "show the pack count, dimensions, finish, and intended paper function",
                "demonstrate one item briefly on a clean document or desk surface",
            ),
            context="well-lit office desk",
            hook="Semak saiz dan bilangan item.",
            benefit="Tunjuk satu kegunaan ringkas di meja.",
            cta="Pilih ikut format yang diperlukan.",
        ),
        "FASHION_ACCESSORY": _catalog_specific_scene(
            product_family="fashion_accessory",
            product_type="FASHION_ACCESSORY",
            use_case="fastener, dimensions, and finish check",
            scene="fashion accessory to fabric-swatch attachment walkthrough",
            actions=(
                "show the accessory dimensions, finish, back, and fastening mechanism",
                "attach it to a detached compatible fabric swatch",
            ),
            context="bright fashion-detail tabletop",
            hook="Semak pengikat dan kemasan aksesori.",
            benefit="Pasang pada sampel kain supaya mekanisme jelas.",
            cta="Padankan dengan jenis kain yang sesuai.",
            forbidden_actions=("pierce skin or attach near a real face",),
        ),
        "HEALTH_TEST_DEVICE": _catalog_specific_scene(
            product_family="health_device",
            product_type="HEALTH_TEST_DEVICE",
            use_case="sealed-kit, component, and instruction-label check",
            scene="health-test device pack inspection without diagnostic use",
            actions=(
                "show the sealed pack, included components, expiry, and instruction leaflet",
                "arrange unused components on a clean table without collecting a sample",
            ),
            context="clean neutral health-product tabletop",
            hook="Semak komponen dan arahan pada kit.",
            benefit="Susun komponen belum digunakan supaya jelas.",
            cta="Ikut arahan pengilang dan dapatkan nasihat profesional jika perlu.",
            forbidden_actions=(
                "collect blood, urine, or another biological sample",
                "interpret a result or make a diagnosis",
            ),
            sensitive_handling_rules=("never promise medical accuracy or outcomes",),
        ),
        "OUTDOOR_LIGHTING": _catalog_specific_scene(
            product_family="outdoor_equipment",
            product_type="OUTDOOR_LIGHTING",
            use_case="housing, controls, mount, and stated-rating check",
            scene="outdoor light to safe low-light control walkthrough",
            actions=(
                "show the housing, controls, mount, charging port, and stated ratings",
                "switch on briefly in a controlled low-light area without aiming at eyes",
            ),
            context="controlled indoor-outdoor test bench",
            hook="Semak binaan, kawalan dan cara pemasangan.",
            benefit="Hidupkan seketika untuk tunjuk mod sebenar.",
            cta="Rujuk rating dan arahan pengecasan.",
            forbidden_actions=("aim the beam at eyes or invent output and runtime claims",),
        ),
        "PLANT_CARE": _catalog_specific_scene(
            product_family="garden_care",
            product_type="PLANT_CARE",
            use_case="label, dosage, and dry-measure check",
            scene="plant-care pack to label-directed measuring walkthrough",
            actions=(
                "show the sealed pack, plant-use label, warnings, and dosage instructions",
                "measure a label-directed dry amount without applying it to a live plant",
            ),
            context="ventilated garden preparation bench",
            hook="Semak sukatan dan jenis tanaman pada label.",
            benefit="Ukur jumlah kering mengikut arahan.",
            cta="Ikut kadar penggunaan dan amaran label.",
            forbidden_actions=("invent growth or treatment outcomes",),
        ),
        "ELECTRICAL_DEVICE": _catalog_specific_scene(
            product_family="home_electrical",
            product_type="ELECTRICAL_DEVICE",
            use_case="certification, plug, rating, and warning check",
            scene="unpowered electrical device inspection",
            actions=(
                "show the unopened device, plug, rating label, certification, and warnings",
                "inspect the housing while keeping the device unplugged",
            ),
            context="dry electrical-safety inspection table",
            hook="Semak rating, plug dan tanda keselamatan.",
            benefit="Tunjuk binaan dalam keadaan tidak disambung.",
            cta="Gunakan hanya jika rating dan pensijilan sesuai.",
            forbidden_actions=(
                "plug in or open the device",
                "repeat electricity-saving claims",
            ),
            sensitive_handling_rules=("electrical safety review is mandatory",),
        ),
        "CLEANING_TOOL": _catalog_specific_scene(
            product_family="household_cleaning",
            product_type="CLEANING_TOOL",
            use_case="count, texture, and dry-wipe check",
            scene="cleaning material to small dry-surface walkthrough",
            actions=(
                "show the pack count, material, dimensions, texture, and disposal label",
                "wipe a small clean dry sample surface once",
            ),
            context="bright household utility table",
            hook="Semak bahan, saiz dan bilangan.",
            benefit="Tunjuk satu lap ringkas pada permukaan sampel.",
            cta="Gunakan ikut jenis permukaan pada label.",
        ),
        "FOOD_COVER": _catalog_specific_scene(
            product_family="kitchen_storage",
            product_type="FOOD_COVER",
            use_case="size, elasticity, and container-fit check",
            scene="food cover to empty-container fit walkthrough",
            actions=(
                "show the pack count, size range, material, and care instructions",
                "fit one clean cover over an empty compatible container",
            ),
            context="clean food-free kitchen table",
            hook="Semak saiz dan bahan penutup.",
            benefit="Pasang pada bekas kosong supaya muatnya jelas.",
            cta="Padankan saiz dengan bekas.",
            forbidden_actions=("claim airtight food safety without label evidence",),
        ),
        "HOME_DECOR": _catalog_specific_scene(
            product_family="home_decor",
            product_type="HOME_DECOR",
            use_case="dimensions, backing, and display-fit check",
            scene="home decor item to sample-display walkthrough",
            actions=(
                "show the full item, dimensions, front, back, and mounting method",
                "place it on a compatible sample display surface",
            ),
            context="bright neutral home-display wall or table",
            hook="Semak ukuran dan cara pemasangan.",
            benefit="Letak pada permukaan sampel supaya rupa jelas.",
            cta="Ukur ruang paparan dahulu.",
        ),
        "COOKWARE": _catalog_specific_scene(
            product_family="kitchen_cookware",
            product_type="COOKWARE",
            use_case="dimensions, base, handle, and compatibility check",
            scene="clean empty cookware inspection without heating",
            actions=(
                "show the empty cookware, dimensions, base, handle, lid, and compatibility label",
                "rotate it on a cold compatible hob without switching the hob on",
            ),
            context="clean unpowered kitchen hob",
            hook="Semak saiz, dasar dan pemegang.",
            benefit="Pusing perkakas kosong supaya binaan jelas.",
            cta="Padankan dengan jenis dapur pada label.",
            forbidden_actions=("heat empty cookware or invent non-stick performance",),
        ),
        "DRINKWARE": _catalog_specific_scene(
            product_family="kitchen_drinkware",
            product_type="DRINKWARE",
            use_case="capacity, lid, seal, and material check",
            scene="empty drinkware component inspection",
            actions=(
                "show the empty vessel, capacity marking, material, lid, straw, and seal",
                "assemble the dry lid and handle without adding liquid",
            ),
            context="clean dry kitchen table",
            hook="Semak kapasiti, bahan dan penutup.",
            benefit="Pasang komponen kering supaya struktur jelas.",
            cta="Rujuk suhu dan arahan penjagaan pada label.",
            forbidden_actions=("invent temperature-retention duration",),
        ),
        "SMALL_LIGHT": _catalog_specific_scene(
            product_family="home_lighting",
            product_type="SMALL_LIGHT",
            use_case="connector, controls, and brief illumination check",
            scene="small USB light to controlled powered demonstration",
            actions=(
                "show the connector, housing, controls, and stated power requirements",
                "connect briefly to a compatible test power source and show illumination",
            ),
            context="controlled electronics test desk",
            hook="Semak penyambung dan keperluan kuasa.",
            benefit="Hidupkan seketika pada sumber yang serasi.",
            cta="Padankan voltan sebelum menyambung.",
            forbidden_actions=("aim into eyes or use an incompatible power source",),
        ),
        "BLUSH": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="BLUSH",
            use_case="shade, texture, and controlled swatch check",
            scene="blush pack to hygienic arm-swatch walkthrough",
            actions=(
                "show the sealed pack, shade label, applicator, and texture",
                "apply one small swatch on a clean adult forearm",
            ),
            context="bright neutral makeup table",
            hook="Semak shade dan tekstur pemerah pipi.",
            benefit="Tunjuk satu swatch kecil dalam cahaya neutral.",
            cta="Pilih shade berdasarkan swatch sebenar.",
            forbidden_actions=("invent wear-time or waterproof claims",),
        ),
        "FISHING_GEAR": _catalog_specific_scene(
            product_family="outdoor_equipment",
            product_type="FISHING_GEAR",
            use_case="mechanism, spool, handle, and rating-label check",
            scene="fishing reel inspection without casting",
            actions=(
                "show the reel body, spool, handle, drag control, and printed ratings",
                "turn the handle slowly on a safe dry bench",
            ),
            context="dry outdoor-equipment workbench",
            hook="Semak spool, pemegang dan kawalan.",
            benefit="Pusing perlahan supaya mekanisme jelas.",
            cta="Padankan rating dengan setup pancing.",
            forbidden_actions=("cast a hook or repeat unverified load claims",),
        ),
        "FITNESS_EQUIPMENT": _catalog_specific_scene(
            product_family="fitness_equipment",
            product_type="FITNESS_EQUIPMENT",
            use_case="dimensions, fastener, and installation-instruction check",
            scene="fitness equipment inspection without body-weight loading",
            actions=(
                "show the bar, grips, adjustment range, contact pads, and instructions",
                "demonstrate the adjustment mechanism off the doorway",
            ),
            context="clear dry equipment inspection area",
            hook="Semak ukuran dan mekanisme pelarasan.",
            benefit="Tunjuk cara laras tanpa menanggung berat.",
            cta="Sahkan keserasian pintu dan had berat dahulu.",
            forbidden_actions=("mount or load the bar during the preview",),
        ),
        "AUTOMOTIVE_ACCESSORY": _catalog_specific_scene(
            product_family="automotive_accessory",
            product_type="AUTOMOTIVE_ACCESSORY",
            use_case="mount, adjustment, and compatibility check",
            scene="automotive accessory to stationary sample-mount walkthrough",
            actions=(
                "show the mount, joints, pads, controls, and compatibility information",
                "attach it to a detached sample surface and adjust it by hand",
            ),
            context="stationary automotive accessory bench",
            hook="Semak tapak, sendi dan keserasian.",
            benefit="Pasang pada sampel dan tunjuk pelarasan.",
            cta="Pastikan pandangan pemandu tidak terhalang.",
            forbidden_actions=("operate or install while a vehicle is moving",),
        ),
        "AUDIO_DEVICE": _catalog_specific_scene(
            product_family="consumer_audio",
            product_type="AUDIO_DEVICE",
            use_case="controls, ports, included parts, and pairing-label check",
            scene="audio device physical inspection without audio-performance claims",
            actions=(
                "show the device, controls, ports, included parts, and model label",
                "switch on briefly and show the status indicator without wearing it",
            ),
            context="quiet electronics inspection desk",
            hook="Semak kawalan, port dan aksesori.",
            benefit="Hidupkan seketika untuk tunjuk indikator.",
            cta="Semak keserasian sebelum pairing.",
            forbidden_actions=("invent sound quality, range, or battery claims",),
        ),
        "SEWING_TOOL": _catalog_specific_scene(
            product_family="craft_hobby",
            product_type="SEWING_TOOL",
            use_case="count, size, eye, and storage check",
            scene="sewing tool pack inspection without stitching",
            actions=(
                "show the sealed pack, item count, sizes, eyes, points, and storage case",
                "place one tool on a contrasting magnetic-safe work mat",
            ),
            context="bright adult-only craft table",
            hook="Semak bilangan dan saiz alat jahit.",
            benefit="Tunjuk satu item pada alas yang jelas.",
            cta="Simpan semua alat tajam selepas digunakan.",
            forbidden_actions=("perform stitching or leave sharp tools loose",),
            sensitive_handling_rules=("adult handling only",),
        ),
        "PET_LITTER": _catalog_specific_scene(
            product_family="pet_care",
            product_type="PET_LITTER",
            use_case="pack, granule, disposal, and tray-quantity check",
            scene="pet litter pack to clean empty-tray measuring walkthrough",
            actions=(
                "show the sealed pack, material, weight, warnings, and disposal guidance",
                "measure a small dry amount into a clean empty sample tray",
            ),
            context="ventilated pet-supply preparation area",
            hook="Semak bahan, berat dan panduan pelupusan.",
            benefit="Ukur sedikit ke dalam tray kosong.",
            cta="Ikut arahan ketebalan dan pelupusan.",
            forbidden_actions=("expose a real animal or make odor-control claims",),
        ),
        "CRAFT_MATERIAL": _catalog_specific_scene(
            product_family="craft_hobby",
            product_type="CRAFT_MATERIAL",
            use_case="component, ratio, warning, and unopened-material check",
            scene="craft material pack inspection without mixing",
            actions=(
                "show the sealed components, ratio label, warnings, PPE, and cure instructions",
                "arrange the unopened components and measuring tools on a protected surface",
            ),
            context="ventilated protected craft workbench",
            hook="Semak nisbah, amaran dan peralatan perlindungan.",
            benefit="Susun komponen tertutup supaya langkah jelas.",
            cta="Ikut nisbah dan keselamatan pada label.",
            forbidden_actions=("mix, heat, pour, or touch uncured resin",),
            sensitive_handling_rules=("PPE and ventilation are mandatory",),
        ),
        "PERSONAL_CARE_DEVICE": _catalog_specific_scene(
            product_family="beauty_personal_care",
            product_type="PERSONAL_CARE_DEVICE",
            use_case="attachments, controls, rating, and dry-operation check",
            scene="personal-care device inspection without body contact",
            actions=(
                "show the device, attachments, controls, rating, guard, and cleaning instructions",
                "switch on briefly while keeping it away from hair and skin",
            ),
            context="dry personal-care equipment table",
            hook="Semak aksesori, kawalan dan rating.",
            benefit="Hidupkan seketika tanpa sentuhan badan.",
            cta="Ikut arahan penggunaan dan pembersihan.",
            forbidden_actions=("use the device on a person during preview",),
        ),
        "BODY_MOISTURIZER": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="BODY_MOISTURIZER",
            use_case="pack, amount, texture, and external-use check",
            scene="body moisturizer to controlled adult-hand swatch",
            actions=(
                "show the pack, ingredient label, amount, and texture",
                "apply a small amount to a clean adult hand",
            ),
            context="bright neutral body-care table",
            hook="Semak tekstur dan sukatan krim badan.",
            benefit="Tunjuk sedikit pada tangan bersih.",
            cta="Ikut arahan penggunaan pada label.",
            forbidden_actions=("claim treatment or skin transformation",),
        ),
        "BODY_BATH": _catalog_specific_scene(
            product_family="BEAUTY_PERSONAL_CARE",
            product_type="BODY_BATH",
            use_case="pack, granule, dosage, and bath-direction check",
            scene="bath product to dry label-directed measuring walkthrough",
            actions=(
                "show the sealed pack, ingredient label, granule, warnings, and dosage",
                "measure a dry label-directed amount without preparing a bath",
            ),
            context="dry bright bathroom-supply table",
            hook="Semak butiran dan sukatan produk mandian.",
            benefit="Ukur jumlah kering mengikut label.",
            cta="Ikut arahan dan amaran pada pek.",
            forbidden_actions=("make pain-relief or therapeutic claims",),
        ),
        "CLEANING_EQUIPMENT": _catalog_specific_scene(
            product_family="household_cleaning",
            product_type="CLEANING_EQUIPMENT",
            use_case="attachments, controls, rating, and dry-operation check",
            scene="cleaning equipment inspection without pressurized use",
            actions=(
                "show the device, attachments, controls, rating, guards, and instructions",
                "operate a control briefly without water, debris, or contact with a surface",
            ),
            context="dry controlled equipment inspection area",
            hook="Semak aksesori, kawalan dan rating.",
            benefit="Tunjuk kawalan tanpa demonstrasi bertekanan.",
            cta="Ikut arahan keselamatan pengilang.",
            forbidden_actions=(
                "spray water, propel debris, or aim the device at a person",
                "repeat unverified pressure or power claims",
            ),
        ),
        "PEST_CONTROL": _catalog_specific_scene(
            product_family="household_pest_control",
            product_type="PEST_CONTROL",
            use_case="sealed-pack, active-label, warning, and placement check",
            scene="pest-control pack inspection without opening or deployment",
            actions=(
                "show the sealed pack, active label, warnings, expiry, and placement directions",
                "point to the labelled placement diagram without opening the product",
            ),
            context="ventilated adult-only safety table",
            hook="Semak amaran dan arahan kawalan perosak.",
            benefit="Tunjuk panduan penempatan pada label.",
            cta="Jauhkan daripada kanak-kanak dan haiwan.",
            forbidden_actions=(
                "open, ignite, spray, taste, or deploy the pest-control product",
                "promise elimination outcomes",
            ),
            sensitive_handling_rules=("sealed-pack demonstration only",),
        ),
        "KITCHEN_TOOL": _catalog_specific_scene(
            product_family="kitchen_tool",
            product_type="KITCHEN_TOOL",
            use_case="component, edge, dimensions, and assembly check",
            scene="clean kitchen tool inspection without food preparation",
            actions=(
                "show every component, dimensions, handle, edge, and care label",
                "assemble the clean dry components without adding food",
            ),
            context="clean dry kitchen worktop",
            hook="Semak komponen dan bahagian kerja alat.",
            benefit="Pasang komponen kering supaya bentuk jelas.",
            cta="Ikut arahan penggunaan dan pembersihan.",
            forbidden_actions=("cut or grate food during the preview",),
        ),
    }
)


@dataclass(frozen=True, slots=True)
class _StrategyRule:
    strategy_id: str
    families: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()


_MATCH_RULES = (
    _StrategyRule(
        "HERBAL_ROLL_ON_OIL",
        families=("HERBAL_ROLL_ON_OIL",),
        terms=(
            "herbal roll on oil",
            "herbal oil roll on",
            "bosmax herbs roll on",
            "bosmax herbs 5 ml",
        ),
    ),
    _StrategyRule(
        "TRADITIONAL_HERBAL_OIL",
        families=(
            "TRADITIONAL_HERBAL_OIL",
            "TRADITIONAL_HERBAL_OIL_BOTTLE",
        ),
        terms=(
            "traditional herbal oil",
            "minyak warisan cap burung",
            "minyak warisan tok cap burung",
        ),
    ),
    _StrategyRule(
        "SENSITIVE_WELLNESS",
        families=("MALE_HEALTH_SENSITIVE", "FEMALE_HEALTH_SENSITIVE"),
        terms=(
            "male health",
            "female health",
            "batin",
            "kuat lelaki",
            "tahan lama",
            "suami isteri",
            "perapat",
            "miss v",
            "intim wanita",
            "kewanitaan",
            "jamu wanita",
            "feminine wellness",
            "male wellness",
        ),
    ),
    _StrategyRule(
        "LIP_COLOR",
        terms=(
            "lipstick",
            "lipstik",
            "lip tint",
            "liptint",
            "lip gloss",
            "lipgloss",
            "lip liner",
            "lip colour",
            "lip color",
        ),
    ),
    _StrategyRule(
        "FRAGRANCE",
        families=("beauty_fragrance",),
        terms=("fragrance", "perfume", "body mist", "body spray", "eau de parfum"),
    ),
    _StrategyRule(
        "SPICE_SEASONING",
        terms=(
            "rempah",
            "spice",
            "seasoning",
            "serbuk perasa",
            "perencah",
            "cooking powder",
        ),
    ),
    _StrategyRule(
        "PACKAGED_SAUCE_SAMBAL",
        terms=("sambal", "sauce", "sos", "chili paste", "pes masakan"),
    ),
    _StrategyRule(
        "LAUNDRY_DETERGENT",
        families=("LAUNDRY_DETERGENT_LIQUID_REFILL",),
        terms=("laundry detergent", "detergen", "sabun dobi", "pencuci baju"),
    ),
    _StrategyRule(
        "FABRIC_SOFTENER",
        families=("FABRIC_SOFTENER_LIQUID",),
        terms=("fabric softener", "pelembut", "pewangi pakaian"),
    ),
    _StrategyRule(
        "BABY_WIPES",
        families=("BABY_WIPES",),
        terms=("baby wipes", "wet wipes", "tisu basah"),
    ),
    _StrategyRule(
        "BABY_DIAPER",
        families=("BABY_DIAPER",),
        terms=("baby diaper", "diaper", "lampin", "pull ups"),
    ),
    _StrategyRule(
        "MODESTWEAR",
        families=("fashion_modestwear",),
        terms=("modestwear", "tudung", "telekung", "khimar", "jubah"),
    ),
    _StrategyRule(
        "SPORTSWEAR",
        families=("fashion_sportswear",),
        terms=("sportswear", "activewear", "jersi", "jersey", "baju sukan"),
    ),
    _StrategyRule(
        "APPAREL",
        families=("APPAREL_SLEEPWEAR", "fashion_apparel"),
        terms=("apparel", "sleepwear", "baju tidur", "blouse", "dress"),
    ),
    _StrategyRule(
        "ELECTRONICS_ACCESSORY",
        terms=(
            "usb cable",
            "kabel",
            "charger",
            "pengecas",
            "power bank",
            "earphone",
            "earbuds",
            "phone holder",
        ),
    ),
    _StrategyRule(
        "ELECTRONICS_SMALL_DEVICE",
        families=("electronics_wearable",),
        terms=(
            "smartwatch",
            "small device",
            "mini device",
            "wireless device",
            "mini chopper",
            "blender",
            "mixer",
            "mini fan",
            "portable fan",
            "bluetooth speaker",
        ),
    ),
    _StrategyRule(
        "HOUSEHOLD_CLEANER",
        families=("HOUSEHOLD_CLEANER_GENERAL",),
        terms=("household cleaner", "floor cleaner", "toilet cleaner", "pencuci rumah"),
    ),
    _StrategyRule(
        "HOUSEHOLD_STORAGE",
        families=("HOUSEHOLD_STORAGE_ORGANIZER",),
        terms=("organizer", "storage", "bekas simpan", "rak simpan"),
    ),
    _StrategyRule(
        "BEAUTY_PERSONAL_CARE",
        families=("BEAUTY_PERSONAL_CARE",),
        terms=("beauty personal care", "skincare", "serum", "shampoo", "syampu"),
    ),
    _StrategyRule("PACKAGED_FOOD", families=("food_packaged",)),
)


_PRODUCT_TEXT_FIELDS = (
    "name",
    "raw_product_title",
    "product_display_name",
    "product_short_name",
    "category",
    "subcategory",
    "type",
    "product_type",
    "product_type_id",
    "silo",
)


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _joined_product_text(product: Mapping[str, object], use_case: str | None) -> str:
    parts = [_normalize(product.get(field)) for field in _PRODUCT_TEXT_FIELDS]
    if use_case:
        parts.append(_normalize(use_case))
    return " ".join(part for part in parts if part)


def _contains_term(haystack: str, term: str) -> bool:
    return f" {_normalize(term)} " in f" {haystack} "


def _copy_entry(
    strategy_id: str,
    entry: SceneStrategyEntry,
    *,
    resolution_source: str,
    fallback_used: bool,
) -> ResolvedSceneStrategy:
    slots = entry["direct_script_slots"]
    return {
        "strategy_id": strategy_id,
        "resolution_source": resolution_source,
        "fallback_used": fallback_used,
        "product_family": entry["product_family"],
        "product_type": entry["product_type"],
        "use_case": list(entry["use_case"]),
        "allowed_scene_strategy": list(entry["allowed_scene_strategy"]),
        "allowed_actions": list(entry["allowed_actions"]),
        "forbidden_actions": list(entry["forbidden_actions"]),
        "scene_contexts": list(entry["scene_contexts"]),
        "camera_routes": list(entry["camera_routes"]),
        "avatar_hints": list(entry["avatar_hints"]),
        "wardrobe_hints": list(entry["wardrobe_hints"]),
        "direct_script_slots": {
            "hook": list(slots["hook"]),
            "benefit": list(slots["benefit"]),
            "cta": list(slots["cta"]),
        },
        "sensitive_handling_rules": list(entry["sensitive_handling_rules"]),
    }


def resolve_scene_strategy(
    product: Mapping[str, object] | None,
    *,
    use_case: str | None = None,
) -> ResolvedSceneStrategy:
    """Resolve one immutable scene grammar without using USP or copy signals."""

    product_payload = dict(product or {})
    truth_mapping = resolve_catalog_product_type_truth(product_payload)
    if (
        truth_mapping is not None
        and truth_mapping.specific_scene_strategy_id is not None
    ):
        strategy_id = truth_mapping.specific_scene_strategy_id
        return _copy_entry(
            strategy_id,
            SCENE_STRATEGIES[strategy_id],
            resolution_source=(
                f"product_truth_source_type:{truth_mapping.product_type_group}"
            ),
            fallback_used=False,
        )

    family_context = derive_bosmax_product_family(product_payload)
    explicit_family = str(product_payload.get("bosmax_product_family") or "").strip()
    family = explicit_family or str(family_context["bosmax_product_family"])
    haystack = _joined_product_text(product_payload, use_case)

    for rule in _MATCH_RULES:
        if family in rule.families:
            return _copy_entry(
                rule.strategy_id,
                SCENE_STRATEGIES[rule.strategy_id],
                resolution_source=f"product_family:{family}",
                fallback_used=False,
            )
        if any(_contains_term(haystack, term) for term in rule.terms):
            return _copy_entry(
                rule.strategy_id,
                SCENE_STRATEGIES[rule.strategy_id],
                resolution_source=f"product_text:{rule.strategy_id}",
                fallback_used=False,
            )

    return _copy_entry(
        "GENERIC_FALLBACK",
        SCENE_STRATEGIES["GENERIC_FALLBACK"],
        resolution_source=f"fallback:{family or 'GENERIC_UNCLASSIFIED'}",
        fallback_used=True,
    )


def select_scene_strategy_variant(
    strategy: ResolvedSceneStrategy,
    variation_index: int,
) -> SelectedSceneStrategyVariant:
    """Select aligned scene/action/camera/copy slots deterministically."""

    offset = max(int(variation_index), 0)
    scripts = strategy["direct_script_slots"]
    return {
        "scene_strategy_id": strategy["strategy_id"],
        "allowed_scene_strategy": strategy["allowed_scene_strategy"][
            offset % len(strategy["allowed_scene_strategy"])
        ],
        "allowed_action": strategy["allowed_actions"][
            offset % len(strategy["allowed_actions"])
        ],
        "scene_context": strategy["scene_contexts"][
            offset % len(strategy["scene_contexts"])
        ],
        "camera_route": strategy["camera_routes"][
            offset % len(strategy["camera_routes"])
        ],
        "avatar_hint": strategy["avatar_hints"][
            offset % len(strategy["avatar_hints"])
        ],
        "wardrobe_hint": strategy["wardrobe_hints"][
            offset % len(strategy["wardrobe_hints"])
        ],
        "direct_hook": scripts["hook"][offset % len(scripts["hook"])],
        "direct_benefit": scripts["benefit"][offset % len(scripts["benefit"])],
        "direct_cta": scripts["cta"][offset % len(scripts["cta"])],
    }


def build_scene_strategy_context(
    strategy: ResolvedSceneStrategy,
    *,
    variation_index: int = 0,
    base_scene_context: str | None = None,
) -> str:
    """Render visual-only strategy instructions for the canonical compiler."""

    selected = select_scene_strategy_variant(strategy, variation_index)
    parts = [
        str(base_scene_context or "").strip() or selected["scene_context"],
        f"Allowed scene strategy: {selected['allowed_scene_strategy']}.",
        f"Allowed product action: {selected['allowed_action']}.",
        f"Camera route: {selected['camera_route']}.",
        f"Avatar hint: {selected['avatar_hint']}.",
        f"Wardrobe hint: {selected['wardrobe_hint']}.",
        "Forbidden actions: " + "; ".join(strategy["forbidden_actions"]) + ".",
    ]
    if strategy["sensitive_handling_rules"]:
        parts.append(
            "Sensitive handling rules: "
            + " ".join(strategy["sensitive_handling_rules"])
        )
    return " ".join(part for part in parts if part)
