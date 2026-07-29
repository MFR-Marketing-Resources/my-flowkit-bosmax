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
