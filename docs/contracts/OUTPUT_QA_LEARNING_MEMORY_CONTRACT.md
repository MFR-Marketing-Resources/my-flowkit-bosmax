# OUTPUT QA + LEARNING MEMORY CONTRACT

## OBJECTIVE
Define the persistence schema for output tracking, quality assessment, and iterative learning.

## DATA SCHEMA
```json
{
  "batch_id": "uuid",
  "variant_id": "uuid",
  "request_id": "uuid",
  "product_id": "uuid",
  "prompt_used": "full_9_section_string",
  "asset_used": "filename_or_url",
  "flow_mode": "Images | Text to Video | Ingredients | Frames",
  "engine": "VEO_3_1",
  "duration": 8,
  "generation_status": "COMPLETED | FAILED | TIMEOUT",
  "output_url": "platform_url",
  "local_path": "filesystem_path",
  "qa_status": "PASSED | REJECTED | PENDING",
  "qa_notes": "reviewer_feedback",
  "failure_reason": "tech_error_code",
  "reuse_score": 1.0,
  "avoid_next_time_rules": [
    "rule_description"
  ]
}
```

## CAPABILITIES
- **Root Cause Mapping**: Link technical failures back to specific UI states or network conditions.
- **Visual Feedback Loop**: Store QA feedback to influence future prompt compiler logic.
- **Audit Trail**: Maintain a complete history of all generations for credit reconciliation and performance analysis.
