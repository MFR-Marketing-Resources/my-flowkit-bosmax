# Product Physics DNA Contract

## Purpose

Product Physics DNA is the structured handling layer that turns a product category into camera-safe manipulation instructions.
It exists so section 5 prompt material is derived from repeatable rules instead of ad hoc prompt writing.

## Canonical Physics Fields

Every physics response must expose:

- `product_id`
- `physics_class`
- `product_scale`
- `hand_object_interaction`
- `recommended_grip`
- `air_gap_rule`
- `material_behavior`
- `surface_behavior`
- `fragility_level`
- `camera_handling_notes`
- `unsafe_handling_rules`
- `section_5_product_physics_prompt`
- `physics_dna_status`

## Classification Rules

The current baseline classes are:

- `A`: small rigid handheld beauty objects like fragrance bottles
- `B`: small food containers or sealed packs like sambal jars or sachets
- `D`: large soft household goods like carpets and pillows
- `FLEXIBLE_FABRIC`: garments and cloth-based products
- `SOFT_PACKAGED_GOODS`: compressible packaged goods like diapers

If no rule matches:

- the physics fields remain blank
- `physics_dna_status` must become `MISSING_FIELDS`
- readiness must degrade accordingly

## Safety Rules

Physics DNA must never:

- invent unsupported product behavior
- imply safety, medical, or efficacy claims that do not exist in the input data
- hide brand labels with fingers when the grip rule says the front panel should remain visible
- produce impossible floating or deformation behavior for soft goods

## Section 5 Prompt Rule

`section_5_product_physics_prompt` must be a compact, camera-oriented summary of:

- class
- scale
- grip
- air-gap rule
- material response
- surface response
- fragility
- handling notes
- unsafe handling prohibitions

## Operator Integration

When a product is selected, Operator must be able to show:

- `Physics Class`
- `Recommended Grip`
- `Product Handling Notes`
- `Section 5 Product Physics Prompt`
- `9-Section Readiness`

## Validation Baseline

The following examples must remain covered by tests:

- diaper
- jersey or athleisure garment
- pants or bottoms
- body spray or fragrance
- sambal or sauce food product
- unknown manual product requiring review
