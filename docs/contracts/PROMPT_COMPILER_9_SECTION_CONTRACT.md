# 9-SECTION PROMPT COMPILER CONTRACT

## OBJECTIVE
Define the transformation logic from high-level variation plans into valid Google Flow video prompts.

## COMPILER INPUTS
- `Product Creative Brief`
- `Variant Plan`
- `Engine`
- `Duration`
- `Language`
- `Google Flow Mode`
- `Asset Strategy`

## REQUIRED OUTPUT STRUCTURE (9 SECTIONS)
1. **Biometric Anchor DNA & Temporal Persistence**: Subject consistency and facial anchors.
2. **Lighting & Scene Physics**: Environment lighting, atmosphere, and volumetric properties.
3. **Camera & Framing**: Shot type, focal length, movement, and orientation.
4. **Visual Action & Expansion**: Narrative movement and interaction.
5. **Product Physics & HOI**: Surface behavior, scale, and Hand-Object Interaction (Uses `section_5_product_physics_prompt`).
6. **Dialogue & Silo Purity**: Speech/narrator text and thematic consistency (Uses selected formula/trigger/copywriting angle).
7. **Audio Sync & Tone**: Acoustic environment and mood.
8. **Temporal Chaining & Manifold Logic**: Multi-clip coherence and state transitions.
9. **Overlay & Typography**: UI elements, text blocks, and branding (Uses `overlay_strategy`).

## ACCEPTANCE CRITERIA
- **Purity**: Final output must be the clean prompt only.
- **Scrubbing**: No internal tags, metadata, schema markers, or placeholder leakage.
- **DNA Integrity**: Section 5 MUST use the `section_5_product_physics_prompt` from the brief.
- **Silo Integrity**: Section 6 MUST adhere to the selected copywriting silo/formula.
- **Visual Branding**: Section 9 MUST reflect the selected overlay strategy.
