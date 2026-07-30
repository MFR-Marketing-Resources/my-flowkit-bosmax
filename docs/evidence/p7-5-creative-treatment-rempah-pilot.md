# P7.5-C Creative Treatment Rempah Pilot Evidence

## Authority boundary

- Pilot Product Type: `SPICE_SEASONING`
- Selected fixture product: Rempah Nasi Khowmok
- Canonical product ID: `0a26caf0-1bc6-43a9-a267-7d2a1dbaccab`
- Alternate allowed product: Rempah Ayam Madu
- Alternate canonical ID: `3f0e0206-a21a-4db6-a323-170ce505703f`
- Sambal Nyet substitution: forbidden
- Canonical data readiness: `NOT VERIFIED`

The fixture does not create or approve canonical records. It proves the
contract deterministically without mutating product, treatment, provider, or
runtime state.

## Deterministic fixture

- Four allowed SPICE_SEASONING action sequences
- Three distinct grammars per action: UGC, PGC, CINEMATIC
- Twelve canonical treatment templates
- One approved five-member same-dialogue Variation Group
- Five distinct visual fingerprints
- Generic fallback use: 0
- Provider calls: 0
- Credit spend: 0

UGC is presenter-led and creator-authentic. PGC is product-led, controlled, and
has no visible presenter. CINEMATIC uses deliberate lens, lighting, camera, and
continuity language. Every grammar preserves the approved action and shot
sequence as structured prompt material.

## Proof surface

`tests/unit/test_creative_treatment_rempah_pilot.py` locks the exact product
allowlist, template count, four-action coverage, three-format coverage,
same-dialogue group invariant, five distinct visual fingerprints, deterministic
fixture hash, fallback prohibition, provider-call count, and credit-spend count.

`tests/unit/test_creative_treatment_prompt_compiler.py` proves the three
grammars compile differently while remaining deterministic and preserving
treatment lineage.

`tests/unit/test_creative_production_treatment_integration.py` proves one video
candidate per treatment, explicit treatment authority, legacy-lineage
rejection, and lineage insertion before payload hashing.
