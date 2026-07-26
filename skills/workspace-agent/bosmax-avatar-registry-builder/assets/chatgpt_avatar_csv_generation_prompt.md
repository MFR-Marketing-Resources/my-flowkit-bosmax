# BOSMAX Avatar Registry CSV Generation Prompt

Use this prompt with any AI to generate BOSMAX Avatar Registry CSV rows.

```text
You are generating BOSMAX Avatar Registry seed-schema CSV rows.

Target output:
- CSV only unless asked for a validation report.
- Use exact header:
CharacterName,Variant,AvatarCode,SkinTone,HairStyle,Wardrobe,Environment,Lighting,Camera,Expression,SafetyBlock,PromptV1,approved_flag,usage_tags,AgeBand

Rules:
1. Output seed schema only. Do not add bridge/helper/generated columns.
2. AvatarCode must match ^BOS_[FM]_[A-Z0-9]+(?:_[A-Z0-9]+)*_[0-9]{2,}$.
3. Use BOS_F for female-coded avatars and BOS_M for male-coded avatars. Do not create neutral/mixed code prefixes.
4. AvatarCode is metadata only. Do not place Code:, BOS_F_, or BOS_M_ inside PromptV1.
5. approved_flag must be TRUE or FALSE, never blank.
6. usage_tags must use pipe delimiter such as UGC|desk|office.
7. PromptV1 must describe a fully clothed, respectful, commercial-safe photorealistic avatar reference image.
8. Do not make medical, cure, before-after, body-transformation, intimate, unsafe baby, or clinical claims.
9. For review/no-auto categories, mark rows FALSE or block output until operator approval.
10. Before claiming ready-to-upload, validate schema, duplicates, AvatarCode format, approved_flag, usage_tags, and PromptV1 metadata leak.
11. AgeBand must be one controlled value: Child (6-12), Teen (13-17), Young adult (18-29), Adult (30-54), Older adult (55-69), or Senior (70+). Child and teen rows must be family-safe and non-sexualized.

If existing AvatarCodes are provided, treat them as reserved and continue numbering without reuse.
```
