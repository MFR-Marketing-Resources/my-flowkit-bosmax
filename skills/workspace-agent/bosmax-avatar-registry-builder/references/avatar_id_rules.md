# Avatar ID Rules

## AvatarCode format

Use this regex:

```regex
^BOS_[FM]_[A-Z0-9]+(?:_[A-Z0-9]+)*_[0-9]{2,}$
```

Examples:

- `BOS_F_MAYA_01`
- `BOS_M_ADAM_01`
- `BOS_F_NUR_AINA_02`

## Gender prefix rules

- `BOS_F_` = female-coded avatar.
- `BOS_M_` = male-coded avatar.
- There is no neutral or mixed AvatarCode lane in V1.
- Neutral may describe wardrobe, pose, tone, or scene posture only.

## Sequence rules

- Continue from the highest existing number for the same character key.
- Never recycle a code after archive/delete.
- Avoid reusing a character key with a different gender prefix unless the operator explicitly approves a separate identity.

## Duplicate prevention

Reject:

- duplicate `AvatarCode`
- duplicate `CharacterName + Variant`
- code prefix that conflicts with the demographic inside `PromptV1`
- internal `AvatarCode` appearing inside `PromptV1`

## Reserved ledger policy

If the user provides existing CSV rows or an existing code list, treat all codes as reserved. Do not overwrite them. If no ledger is provided, state `LEDGER_NOT_PROVIDED` and generate conservative new names.
