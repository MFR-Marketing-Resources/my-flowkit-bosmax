# Avatar Category Planner

Use this matrix when planning avatar pools from BOSMAX product groups. Counts are AvatarCode-prefix quotas. `female_count + male_count` must equal `total_count`. `operator_override_allowed` means the operator may manually adjust the generated plan after review.

| Group | auto_plan_allowed | total_count | female_count | male_count | operator_override_allowed | allowed_roles | allowed_environments | blocked_visual_assumptions | required_usage_tags | reviewer_note |
|---|---|---:|---:|---:|---|---|---|---|---|---|
| ACCESSORIES_AND_SMALL_ITEMS | yes | 10 | 8 | 2 | true | presenter, hand-demo, styling-demo, lifestyle-demo | desk, office, car interior, cafe, mirror area, shelf | medical benefit, fake luxury status, impossible scale, body-transformation implication | `UGC`, context tag such as `office`, `home`, `car`, `desk` | Default business lane. Keep product scale and handling literal. |
| STATIONERY_AND_GIFTING | yes | 8 | 5 | 3 | true | presenter, gifting-demo, flatlay-support, packaging-demo | study desk, office desk, festive table, bookshelf, home desk | spiritual guarantee, academic-result promise, collectible-value inflation | `UGC`, `desk` or `gift` | Religious/book rows may require respectful copy review even if planner is auto-allowed. |
| HOME_ORGANIZATION | yes | 8 | 6 | 2 | true | presenter, organizing-demo, shelf-demo, storage-demo | bedroom, wardrobe, laundry corner, kitchen shelf, entryway | impossible storage capacity, fake before-after transformation, industrial setup mismatch | `UGC`, `home` | Favor practical home UGC framing over studio polish. |
| ELECTRONICS_AND_GADGETS | yes | 8 | 5 | 3 | true | presenter, feature-demo, device-demo, unbox-support | desk, car interior, office, commute, gym bag area | fake UI, fake specs, sci-fi glow effects, unsupported waterproof/ruggedness signals | `UGC`, `tech` | Device truth and hand interaction fidelity are mandatory. |
| FASHION_AND_APPAREL | review | 8 | 6 | 2 | true | presenter, outfit-demo, texture-demo, movement-demo | mirror, hallway, boutique-like home corner, cafe, walkway | sensualization, body-shape exaggeration, skin-exposure drift, false slimming/performance implication | `UGC`, apparel context tag such as `fashion`, `home`, `studio` | Review for modestwear, intimate apparel, body-sensitive titles, and claim-adjacent copy. |
| BEAUTY_AND_PERSONAL_CARE | review | 8 | 7 | 1 | true | presenter, routine-demo, vanity-demo, packaging-demo | vanity, bathroom shelf, dressing table, bedroom mirror | medical cure, dermatology implication, dramatic before-after, exaggerated skin transformation | `UGC`, `beauty`, optional `home` | Review required for claim posture and sensitive skin/health wording. |
| BABY_AND_MATERNITY | review | 6 | 6 | 0 | true | caregiver-demo, presenter, packaging-demo, routine-demo | nursery, diaper station, bedroom, living room | unsafe infant handling, exposed infant dependency, clinical efficacy, hygiene overclaim | `UGC`, `home`, babycare context tag | Use female-coded caregiver defaults only for planning convenience; operator may widen later. |
| FOOD_AND_BEVERAGE | review | 6 | 4 | 2 | true | presenter, serving-demo, packaging-demo, table-demo | dining table, kitchen counter, pantry, cafe table | explicit health claim, fake ingredient freshness, exaggerated portion size, unsafe consumption cue | `UGC`, `food`, `home` or `table` | Review needed for ingestible truth, halal/cultural cues, and claim-safe language. |
| HEALTH_AND_WELLNESS | no | 0 | 0 | 0 | true | none until approved | none until approved | cure claim, symptom relief, body transformation, dosage implication, professional-medical framing | none until approved | Manual review required before any avatar planning. |
| FEMALE_HEALTH_SENSITIVE | no | 0 | 0 | 0 | true | none until approved | none until approved | intimate anatomy implication, sensualization, embarrassment framing, reproductive/medical implication | none until approved | Manual review required. No auto-plan. |
| MALE_HEALTH_SENSITIVE | no | 0 | 0 | 0 | true | none until approved | none until approved | virility framing, body-performance implication, shame/fix framing, medical implication | none until approved | Manual review required. No auto-plan. |
| UNKNOWN_REVIEW_REQUIRED | no | 0 | 0 | 0 | true | none until classified | none until classified | all category assumptions blocked | none until classified | Classification must be settled first. |

## Planning rules

- For `auto_plan_allowed: yes`, generate candidate rows and mark warnings for any sensitive language.
- For `auto_plan_allowed: review`, generate only if the operator explicitly asks for review-mode candidates; mark them `FALSE` in `approved_flag` unless told otherwise.
- For `auto_plan_allowed: no`, do not generate avatar rows. Return a review block and ask for classification or approval.
- Never invent product benefits, medical effects, body transformation, or clinical usage from a product group name.
