import { postAPI } from "./client";

// Final Prompt Approval Gate — client for the per-dispatch WYSIWYG approval
// lifecycle. The operator reviews (and optionally edits) the exact provider-ready
// prompt, then approves; only an APPROVED snapshot whose execution envelope
// matches the dispatch authorises generation. See agent/api/execution_approval.py.

export type ApprovalState =
  | "REVIEW_REQUIRED"
  | "EDITED"
  | "APPROVED"
  | "INVALIDATED"
  | "DISPATCHED";

export interface ExecutionApprovalSnapshot {
  snapshot_id: string;
  approval_state: ApprovalState;
  surface: string;
  logical_mode: string;
  final_prompt_text: string;
  prompt_sha256: string;
  execution_envelope_sha256: string;
  scan_clean: number;
  scan_json?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  invalidation_reason?: string | null;
}

// The provider-ready execution envelope frozen for review. It MUST mirror exactly
// what the surface will dispatch (same prompt + provider-affecting settings +
// resolved asset ids), so the dispatch boundary's envelope hash matches.
export interface ReviewEnvelope {
  surface: string;
  logical_mode: string;
  final_prompt_text: string;
  product_id?: string | null;
  source_mode?: string | null;
  model?: string | null;
  aspect?: string | null;
  duration_s?: number | null;
  count?: number | null;
  image_model?: string | null;
  asset_media_ids?: string[] | null;
  created_by?: string | null;
}

export function createReviewSnapshot(
  envelope: ReviewEnvelope,
): Promise<ExecutionApprovalSnapshot> {
  return postAPI<ExecutionApprovalSnapshot>("/api/execution-approval/review", envelope);
}

export function editSnapshot(
  snapshotId: string,
  editedPromptText: string,
  editorId?: string,
): Promise<ExecutionApprovalSnapshot> {
  return postAPI<ExecutionApprovalSnapshot>(
    `/api/execution-approval/${encodeURIComponent(snapshotId)}/edit`,
    { edited_prompt_text: editedPromptText, editor_id: editorId ?? null },
  );
}

export function approveSnapshot(
  snapshotId: string,
  approvedBy: string,
): Promise<ExecutionApprovalSnapshot> {
  return postAPI<ExecutionApprovalSnapshot>(
    `/api/execution-approval/${encodeURIComponent(snapshotId)}/approve`,
    { approved_by: approvedBy },
  );
}
