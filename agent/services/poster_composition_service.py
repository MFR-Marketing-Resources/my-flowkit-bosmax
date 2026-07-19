"""Canonical deterministic professional-poster composition resolver."""
from __future__ import annotations

import hashlib
import json
from typing import Any

_PROFILES = {
    "PGC_CAMPAIGN": {"profile":"campaign_product_hero_v1","anchor":"right","dominance":"70-80%","human":"optional","face":"upper-left protected","hook":"bold campaign headline","usp":"two proof lines","cta":"high-contrast campaign button","background":"controlled cinematic gradient","lighting":"campaign key light","props":"minimal hero","space":"left copy field","priority":["product","hook","cta","usp"]},
    "UGC_AUTHENTIC": {"profile":"authentic_routine_v1","anchor":"lower-right","dominance":"55-65%","human":"allowed","face":"upper-third protected when present","hook":"simple conversational headline","usp":"one practical proof line","cta":"soft but discoverable action","background":"believable everyday context","lighting":"ambient practical light","props":"routine-use only","space":"natural wall or counter field","priority":["human_product","hook","cta","usp"]},
    "MODEL_AMBASSADOR": {"profile":"ambassador_split_v1","anchor":"lower-left","dominance":"55-65%","human":"required","face":"upper-right exclusion zone","hook":"headline outside face-safe zone","usp":"restrained proof lines","cta":"polished advertising action","background":"polished editorial backdrop","lighting":"polished advertising light","props":"one supporting prop","space":"right copy column","priority":["model_product","hook","cta","usp"]},
    "CLEAN_STUDIO_CATALOGUE": {"profile":"studio_catalogue_v1","anchor":"center","dominance":"70-80%","human":"prohibited","face":"not applicable","hook":"restrained high-contrast headline","usp":"single concise support line","cta":"minimal catalogue action","background":"clean seamless studio","lighting":"controlled studio light","props":"none","space":"generous upper and lower field","priority":["product","hook","cta","usp"]},
    "LIFESTYLE_EDITORIAL": {"profile":"editorial_context_v1","anchor":"lower-right","dominance":"60-70%","human":"allowed","face":"upper-left protected when present","hook":"curated editorial headline","usp":"editorial support line","cta":"subtle premium action","background":"aspirational contextual setting","lighting":"refined natural light","props":"curated contextual props","space":"editorial left column","priority":["product","hook","usp","cta"]},
}

def _signature(plan: dict[str, Any]) -> str:
    stable = {k: plan[k] for k in ("canvas", "reading_order", "product", "copy", "typography", "scene")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]

def resolve_poster_composition(*, creative_direction: Any, recipe_id: str, frame_ratio: str, fields: dict[str, str], constraints: dict[str, Any] | None = None) -> dict[str, Any]:
    mode = str(getattr(creative_direction, "mode", "") or "")
    if not mode: return {}
    p = dict(_PROFILES[mode]); constraints = constraints or {}; suppressions = []
    product_locks = constraints.get("product_truth", {})
    if product_locks:
        suppressions.append({"property":"product.identity","reason":"PRODUCT_TRUTH_LOCK"})
    if constraints.get("operator_human_presence"):
        p["human"] = constraints["operator_human_presence"]; suppressions.append({"property":"scene.human_presence","reason":"OPERATOR_HARD_SELECTION"})
    if constraints.get("recipe_requires_human") and p["human"] == "prohibited":
        p["human"] = "required"; suppressions.append({"property":"scene.human_presence","reason":"RECIPE_REQUIRED_HUMAN"})
    if constraints.get("approved_identity_required") and p["human"] == "required":
        p["human"] = "approved identity only"; suppressions.append({"property":"scene.human_presence","reason":"APPROVED_IDENTITY_LOCK"})
    warnings=[]; copies=[v.strip().lower() for v in fields.values() if isinstance(v,str) and v.strip()]
    if len(fields.get("hook", ""))>48: warnings.append("HOOK_DENSITY_EXCEEDS_COMPOSITION_LIMIT")
    if len(fields.get("cta", ""))>24: warnings.append("CTA_DENSITY_EXCEEDS_COMPOSITION_LIMIT")
    if len([x for x in (fields.get("usp_1"),fields.get("usp_2"),fields.get("usp_3"),fields.get("usp_4")) if x])>3: warnings.append("USP_COUNT_EXCEEDS_COMPOSITION_LIMIT")
    if len(copies)!=len(set(copies)): warnings.append("DUPLICATE_COPY_DETECTED")
    plan={"schema_version":"wrna-poster-composition-v1","profile_id":p["profile"],"creative_mode":mode,"recipe_id":recipe_id,"authority_versions":{"creative_direction":str(getattr(creative_direction,"authority_version","") or ""),"representation_policy":str(getattr(creative_direction,"representation_policy_version","") or "")},"provenance":{"active_locks":sorted(constraints.keys()),"suppressions":suppressions},"canvas":{"frame_ratio":frame_ratio or "9:16","safe_margin":"5%","edge_exclusion":"text and CTA stay inside safe margin"},"reading_order":p["priority"],"product":{"anchor":constraints.get("recipe_product_anchor",p["anchor"]),"dominance":p["dominance"],"label_visibility":"required","real_world_scale":"required","prohibited_overlaps":["hook","cta","face"]},"copy":{"hook_zone":"upper-left","subhook_zone":"upper-left below hook","usp_zone":"left-middle","cta_zone":"lower-left","strategy":p["space"],"max_lines":{"hook":3,"subhook":3,"usp":3,"cta":2}},"typography":{"hook":p["hook"],"subhook":"supporting","usp":p["usp"],"cta":p["cta"]},"scene":{"lighting":p["lighting"],"human_presence":p["human"],"face_safe_rule":p["face"],"negative_space":p["space"],"background_complexity":p["background"],"prop_density":p["props"]},"quality_negative_rules":["no text covering product or face","no floating chips","no excessive badges","no duplicate product crop","no fabricated certification","no cluttered spec-sheet layout"],"warnings":warnings}
    plan["signature"]=_signature(plan); return plan

def render_composition_instruction(plan: dict[str, Any]) -> str:
    if not plan: return ""
    p=plan["product"]; c=plan["copy"]; s=plan["scene"]; t=plan["typography"]
    return f"Professional composition: {plan['canvas']['frame_ratio']} canvas; product anchored {p['anchor']} at {p['dominance']} visual dominance, label visible and real-world scale preserved. Reading order {' then '.join(plan['reading_order'])}. Keep hook {c['hook_zone']}, USP {c['usp_zone']} and CTA {c['cta_zone']} inside safe margin. {s['lighting']}; {s['background_complexity']}; {t['hook']}; {t['cta']}; {', '.join(plan['quality_negative_rules'])}."
