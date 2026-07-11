# Current state repository audit

## End-to-end stages (video-centric production path)

| Stage | Input | Validation | Output state | Primary symbols | Evidence |
|-------|-------|------------|--------------|-----------------|----------|
| Product selection | product_id | CRUD / catalog | product row | `crud.get_product` | VERIFIED_CODE |
| Product truth / brief | product_id | `get_creative_brief` | brief + readiness | `product_creative_brief.py` | VERIFIED_CODE |
| Copy sets | product_id, modes | copy_set services | APPROVED copy sets | `copy_sets` API | VERIFIED_TEST |
| WGP authoring | operator / compiler | package validators | WGP DRAFT/READY | `workspace_generation_package_service` | VERIFIED_CODE |
| Batch prompt plan | BatchPromptRequest | `validate_mode_inputs` | N WGP rows + batch_run_id | `start_batch_prompt_run` | VERIFIED_CODE |
| Prompt approval | package_ids | status READY_MANUAL | production_status APPROVED | `approve_packages` | VERIFIED_TEST |
| Production run create | APPROVED ids | model required FAIL_CLOSED | production_run PENDING dry_run=1 | `send_to_production` | VERIFIED_TEST |
| Dry run | run_id | `build_execution_payload` | payload report, no credits | `run_production_queue` w/o confirm | VERIFIED_TEST |
| Live execution | confirm_live_credit_burn | blockers empty | make_video job | `_live_production_loop` | VERIFIED_CODE |
| Retrieval | job DONE | get_media / harvest | generated_artifact | `make_video` + `crud.insert_generated_artifact` | VERIFIED_RUNTIME (authority) |
| Library / QA | media_id | API list/get | operator review | `/api/flow/artifacts`, dashboard | VERIFIED_RUNTIME (authority) |

## Parallel legacy path (batch table)

| Stage | Behavior | Classification |
|-------|----------|----------------|
| POST `/api/batches/draft` | `create_batch_draft` → `batch` + `batch_variant` | VERIFIED_CODE |
| POST `/api/batches/{{id}}/queue` | Status QUEUED only; **no Flow** | VERIFIED_CODE |
| POST `/api/batches/{{id}}/execute-next` | `batch_executor` dry_run default | VERIFIED_TEST |

**Conflict:** Two batch metaphors coexist; modern prompt/production split uses WGP + `production_run`, not `batch_variant.queue_status` execution at scale.

## Protected integration points (do not rewrite without gate failure)

Per `AGENTS.md` / CURRENT_STATE: `/api/flow/execute-flow-job` → `make_video.start_generate`, negotiation, retrieval, `generated_artifact`, USER SETTINGS LAW.
