# Validation Checklist

Use this checklist before returning final CSV.

## Schema

- Header exactly matches seed schema.
- No bridge/helper/generated columns are present.
- Every required field is filled.

## Codes

- `AvatarCode` matches `^BOS_[FM]_[A-Z0-9]+(?:_[A-Z0-9]+)*_[0-9]{2,}$`.
- No duplicate `AvatarCode`.
- No duplicate `CharacterName + Variant`.
- Code prefix agrees with the avatar's demographic.

## PromptV1

- No `Code:`.
- No `BOS_F_` or `BOS_M_`.
- No medical, cure, before-after, body transformation, intimate, unsafe baby, or clinical claims.
- Image prompt remains avatar-reference focused.

## Flags and tags

- `approved_flag` is exactly `TRUE` or `FALSE`.
- `usage_tags` is non-empty.
- Final output uses pipe-delimited tags.

## Category planning

- `female_count + male_count = total_count`.
- No rows are generated for `auto_plan_allowed: no` categories unless a senior manual approval is supplied.
- Review categories are marked with warnings and should default to `FALSE` unless operator approves.
