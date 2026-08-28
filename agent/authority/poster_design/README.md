# Poster Design Authority Pack

## Purpose

This folder is the **authority and reference pack for BOSMAX poster/image prompt generation**.
It contains commercial design rules, platform specifications, visual language standards,
typography, copywriting, color psychology, ecommerce product handling, visual proof,
and post-processing rules — all scoped exclusively to poster/image/commercial visual
prompt construction.

## Status: Reference Only (This PR)

This authority pack is **reference-only** for this PR. There is no runtime poster
generator, no UI, and no backend API wired to these files yet. They are organized,
registered, and audit-ready so that future poster modules can consume them cleanly
without confusion with the existing video prompt compiler authority.

## Runtime Status

- **Integration status:** NOT YET WIRED to any runtime module
- **Scope:** Poster/image prompt generation only
- **Intended runtime contract:** Operator selects product, angle, hook, subhook,
  USP fields, CTA, platform, language, and poster mode → system constructs final
  image prompt using this authority pack

## File Organization

### Strict Authority Files (Sovereign — always loaded)

These files define the non-negotiable core rules for poster prompt generation.
They take precedence over satellite files on any conflict.

| File | Purpose |
|------|---------|
| `Platform_Specs_v1_STRICT.yaml` | Platform aspect ratios, safe zones, format constraints |
| `Model_Behaviour_v1_STRICT.yaml` | Image model behavior rules, hallucination prevention |
| `Prompt_Framework_v1_STRICT.yaml` | Prompt architecture, routing, output modes |
| `Visual_Language_v1_STRICT.yaml` | Visual hierarchy, lighting, composition, camera kinematics |
| `PostProcessing_v1_STRICT.yaml` | Export pipeline, compression, platform delivery profiles |
| `Commercial_Design_Intelligence_v1_STRICT.yaml` | Commercial poster elevation engine, selling angle logic |

### Satellite Reference Files (Conditionally Loaded)

These files provide domain-specific guidance loaded only when relevant context is
detected (product/ecommerce, text/CTA overlay, color strategy, proof posters, or
real estate).

| File | Loaded When |
|------|-------------|
| `Ecommerce_Product_v1_SATELLITE.yaml` | Ecommerce or product listing context |
| `Typography_v1_SATELLITE.yaml` | Text/CTA/overlay rendering needed |
| `Copywriting_v1_SATELLITE.yaml` | Copy/headline/CTA text needed |
| `Color_Testing_v1_SATELLITE.yaml` | Color psychology or A/B testing context |
| `Visual_Proof_v1_SATELLITE.yaml` | Proof or conversion poster context |
| `RealEstate_v1_SATELLITE.yaml` | Property or real estate context |

### Portable Skill Files

| File | Purpose |
|------|---------|
| `BOSMAX_UNIVERSAL_COMMERCIAL_DESIGN_SKILL.md` | Portable skill for weak brief elevation across AI agents |
| `Custom_Instruction.txt` | System instruction for SEA Visual Intelligence Engine (v3.2 compact) |

## Resolution Order

1. Always read all strict/sovereign files first.
2. Conditionally load satellite files based on context (product, text, color, proof, real estate).
3. Sovereign YAML overrides satellite YAML on conflict.
4. Portable skill files supplement the YAML authority; the YAML is the source of truth on rule conflicts.

## Separation from Video Prompt Compiler

**This folder must NOT be automatically mixed with video prompt compiler authority files.**
The video prompt compiler (`agent/authority/VIDEO_PROMPT_COMPILER_TEMPLATES.yaml`,
`agent/authority/BOSMAX_CUSTOM_INSTRUCTION.txt`, etc.) serves a different pipeline
(video generation via GROK/Google Flow). Poster authority serves image/poster
generation. Mixing them would cause metadata leakage, wrong routing, and unstable
prompts.

## Future Runtime Contract

When the poster generation module is built, it will:
- Accept operator inputs: product_id, product_truth, angle, hook, subhook, usp1-3, cta, platform, language, poster_mode
- Load the strict authority files unconditionally
- Load satellite files conditionally based on context
- Output: final_image_prompt, negative_prompt, optional_metadata_handoff
