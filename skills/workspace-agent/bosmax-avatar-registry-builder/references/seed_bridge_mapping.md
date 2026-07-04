# Seed vs Bridge Mapping

## Decision

BOSMAX Avatar Registry Builder V1 emits seed-schema CSV only. Bridge export mode is held until a proper runtime staging/import contract exists.

## Seed authority

The seed schema is the repo-safe CSV contract:

```csv
CharacterName,Variant,AvatarCode,SkinTone,HairStyle,Wardrobe,Environment,Lighting,Camera,Expression,SafetyBlock,PromptV1,approved_flag,usage_tags
```

## Runtime bridge warning

The BOSMAX runtime may use a local bridge file at `data/avatar_registry/AVATAR_POOL_NORMALIZED.csv` when it exists. That file is a local runtime override, not Skill V1 authority. It may be ignored by Git and may contain helper/generated columns.

## V1 bridge policy

- Do not read the local bridge as canonical truth.
- Do not emit bridge/helper/generated columns.
- Do not create a bridge-format CSV.
- Do not claim compatibility with a local machine's ignored bridge state.
- Document bridge questions as `BRIDGE_MODE_HELD`.

## Future bridge mode prerequisites

Only add bridge export mode after the BOSMAX system has a real staging/import module with:

1. canonical import preview
2. duplicate and reserved-code ledger
3. archive/delete semantics
4. approved row promotion
5. deterministic field mapping
6. runtime tests
