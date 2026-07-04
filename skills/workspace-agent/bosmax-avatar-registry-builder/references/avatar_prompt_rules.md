# Avatar Prompt Rules

`PromptV1` is the image-factory prompt for one avatar reference image. It must be commercially safe and must not leak internal IDs.

## Required PromptV1 structure

Include these ideas in natural prose:

- create a photorealistic avatar reference image
- identity name only, not code
- demographic and market fit
- role
- styling/wardrobe
- hair and skin tone
- expression and pose
- environment and lighting
- camera framing
- safety language

## Forbidden in PromptV1

Fail the row if `PromptV1` contains:

- `Code:` in any casing
- `BOS_F_`
- `BOS_M_`
- raw CSV helper metadata
- image file names or upload IDs
- medical, cure, before-after, body transformation, intimate, unsafe baby, or clinical claim cues

## Safe PromptV1 example

```text
Create a photorealistic avatar reference image. Identity: Maya. Demographic: female young adult Malay Southeast Asian market fit. Role: accessories lifestyle presenter. Styling: modest smart casual. Hair: medium tidy. Skin tone: medium tan. Expression: calm confident. Pose: relaxed natural waist-up pose holding a small everyday accessory near chest level with the item facing camera. Environment: office desk with soft natural light. Camera framing: waist-up, clear face. Safety: fully clothed, respectful, suitable for general audience and commercial use.
```

## Safety block policy

Use `STANDARD_SAFETY_BLOCK` in the CSV column. In `PromptV1`, use concise safety wording. Do not claim certificates, medical safety, or professional endorsement.
