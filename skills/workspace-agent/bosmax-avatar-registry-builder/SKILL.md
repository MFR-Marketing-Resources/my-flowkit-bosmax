---
name: bosmax-avatar-registry-builder
description: bosmax avatar registry csv builder, validator, and category planner for chatgpt workspace agent workflows. use when the user needs to create, review, normalize, or validate BOSMAX avatar registry CSV rows for upload into BOSMAX Avatar Registry, generate avatar pools by product group, enforce AvatarCode governance, prevent PromptV1 metadata leaks, or produce operator-ready CSV and validation reports from product/category notes or uploaded reference workbooks.
---

# BOSMAX Avatar Registry Builder

## Mission

Generate and validate BOSMAX Avatar Registry CSV source rows for operator review. Target the repo seed CSV schema only. Treat runtime bridge CSVs as non-authoritative local overrides unless a future bridge mode is explicitly approved.

This skill does not generate avatar images, spend credits, edit BOSMAX runtime files, or claim a CSV is production-ready when validation fails.

## Authority boundaries

1. Output only the seed schema in `references/avatar_csv_schema.md`.
2. Do not emit bridge/helper/generated columns. See `references/seed_bridge_mapping.md` only to understand what to avoid.
3. Keep `AvatarCode` as CSV metadata only. Never place `Code:`, `BOS_F_`, or `BOS_M_` inside `PromptV1`.
4. Use explicit `TRUE` or `FALSE` for `approved_flag`; never leave it blank.
5. Use pipe-delimited `usage_tags` in final output, for example `UGC|desk|office`.
6. Exclude operator workbooks from the skill package. Treat uploaded workbooks such as FastMoss exports as external input only.

## Workflow

### 1. Classify the request

Identify whether the user needs one of these jobs:

- create a new avatar registry CSV
- add rows to an existing registry
- plan avatars by product group/category
- validate or normalize an uploaded CSV
- produce a generation prompt for another AI to fill the CSV
- audit a CSV before BOSMAX upload

Ask for missing essentials only when required: target group/category, target count, gender mix, existing codes to avoid, and whether output should be CSV only or CSV plus report.

### 2. Load only the needed references

- CSV/schema job: read `references/avatar_csv_schema.md` and `references/avatar_id_rules.md`.
- Product group planning: read `references/avatar_category_planner.md`.
- PromptV1 writing: read `references/avatar_prompt_rules.md`.
- QA/audit: read `references/validation_checklist.md`.
- Bridge questions: read `references/seed_bridge_mapping.md`.

### 3. Build or update rows

Create rows with the exact seed header order:

`CharacterName,Variant,AvatarCode,SkinTone,HairStyle,Wardrobe,Environment,Lighting,Camera,Expression,SafetyBlock,PromptV1,approved_flag,usage_tags`

When planning from a product group, use explicit `female_count` and `male_count` quotas. Do not create a neutral or mixed AvatarCode lane. Use `BOS_F_...` for female-coded avatars and `BOS_M_...` for male-coded avatars.

### 4. Validate before claiming readiness

Use `scripts/validate_avatar_registry_csv.py` when a CSV file is available. For generated text-only CSV, apply the same checklist manually and clearly state that file-level validation still needs to be run after the CSV is saved.

Recommended commands:

```bash
python scripts/validate_avatar_registry_csv.py validate-only avatar_registry.csv
python scripts/validate_avatar_registry_csv.py normalize-output avatar_registry.csv --output avatar_registry.normalized.seed.csv --report avatar_registry.validation-report.json
```

### 5. Return operator-ready deliverables

Return these artifacts when applicable:

1. seed-schema CSV
2. JSON-style validation report or checklist summary
3. operator notes listing warnings, assumptions, blocked categories, duplicate risks, and unresolved decisions

Use `assets/avatar_registry_template.seed.csv` as a starter file. Use `assets/chatgpt_avatar_csv_generation_prompt.md` when the user wants a portable prompt for another AI.

## Hard blocks

Return a blocked result instead of CSV-ready output when:

- target category is `UNKNOWN_REVIEW_REQUIRED` and no classification is provided
- user asks for medical, cure, intimate, virility, reproductive, or unsafe baby-use visual assumptions
- `PromptV1` contains internal code metadata
- `AvatarCode` conflicts are unresolved
- CSV header does not match seed schema
- bridge/helper/generated columns are present in a supposed seed-schema upload

## Output style

Be direct and audit-oriented. Separate `READY`, `WARNINGS`, and `BLOCKERS`. Never claim a CSV can be uploaded safely unless it passes validation.
