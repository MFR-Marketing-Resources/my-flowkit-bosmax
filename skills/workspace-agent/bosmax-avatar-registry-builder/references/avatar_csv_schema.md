# Avatar CSV Schema

Use this schema for BOSMAX Avatar Registry Builder V1. It targets the repo seed CSV, not the local runtime bridge.

## Exact header order

```csv
CharacterName,Variant,AvatarCode,SkinTone,HairStyle,Wardrobe,Environment,Lighting,Camera,Expression,SafetyBlock,PromptV1,approved_flag,usage_tags
```

The header order is mandatory. Do not add or remove columns.

## Column rules

| Column | Required | Rule |
|---|---:|---|
| `CharacterName` | yes | Human-readable avatar identity name. Use title case. |
| `Variant` | yes | Variant label such as `Office 01`, `Desk Small Items 01`, or `Home Storage 02`. Must be unique per `CharacterName`. |
| `AvatarCode` | yes | Metadata code only. Must match `^BOS_[FM]_[A-Z0-9]+(?:_[A-Z0-9]+)*_[0-9]{2,}$`. |
| `SkinTone` | yes | Natural descriptor such as `Light tan`, `Medium tan`, or `Tan SEA`. |
| `HairStyle` | yes | Concrete, non-glamourized hair descriptor. |
| `Wardrobe` | yes | Fully clothed, respectful, market-fit outfit. |
| `Environment` | yes | Concrete scene setting. Avoid unsupported product claims. |
| `Lighting` | yes | Lighting description, not a generated-image claim. |
| `Camera` | yes | Framing such as `Waist-up`, `Half-body`, or `Close product hold`. |
| `Expression` | yes | Natural expression. |
| `SafetyBlock` | yes | Use `STANDARD_SAFETY_BLOCK` unless a future approved enum is added. |
| `PromptV1` | yes | Image-factory prompt. Must not contain `Code:`, `BOS_F_`, or `BOS_M_`. |
| `approved_flag` | yes | Explicit `TRUE` or `FALSE`. Blank is forbidden. |
| `usage_tags` | yes | Pipe-delimited tags, for example `UGC|desk|office`. |

## Forbidden columns in V1

Reject these bridge/helper/generated columns in seed-schema output:

- `Name`
- `Avatar Poster Upload`
- `AvatarCode_Generated`
- `AvatarCode_Mismatch`
- `Avatar_Generation_Source`
- `Avatar_Last_Generated_At`
- `Avatar_Wiring_Status`
- `PromptV1_Generated`
- `PromptV1_Mismatch`

## Minimal safe sample row

See `assets/avatar_registry_template.seed.csv`. The sample keeps `AvatarCode` in the metadata column and omits internal code from `PromptV1`.
