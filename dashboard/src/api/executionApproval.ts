import { getAPI, postAPI } from "./client";

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
  manifest_id?: string | null;
  manifest_item_key?: string | null;
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

export function invalidateSnapshot(
  snapshotId: string,
  reason: string,
): Promise<ExecutionApprovalSnapshot> {
  return postAPI<ExecutionApprovalSnapshot>(
    `/api/execution-approval/${encodeURIComponent(snapshotId)}/invalidate`,
    { reason },
  );
}

// Server-side prepare: the backend compiles the FINAL provider-ready prompt
// (product-truth grounding for IMG happens BEFORE review — never after approval)
// and freezes a REVIEW_REQUIRED snapshot. The modal shows the returned grounded
// final_prompt_text; the dispatch recomputes the SAME identity, so the approved
// prompt is dispatched EXACT. Prefer this over createReviewSnapshot for any
// surface whose prompt is grounded/compiled server-side (IMG).
export interface PrepareDispatchRequest {
  surface: string;
  logical_mode: string;
  prompt: string;
  product_id?: string | null;
  source_mode?: string | null;
  model?: string | null;
  aspect?: string | null;
  duration_s?: number | null;
  count?: number | null;
  image_model?: string | null;
  asset_media_ids?: string[] | null;
  visual_lane_id?: string | null;
  reference_pack_id?: string | null;
  creative_mode?: string | null;
  created_by?: string | null;
}

export function prepareDispatch(
  req: PrepareDispatchRequest,
): Promise<ExecutionApprovalSnapshot> {
  return postAPI<ExecutionApprovalSnapshot>("/api/execution-approval/prepare", req);
}

// --------------------------------------------------------------------------- //
// Approved Generation Manifest (multi-operation explicit approval)
// --------------------------------------------------------------------------- //

export type ManifestState = "REVIEW_REQUIRED" | "APPROVED" | "INVALIDATED";

export interface ApprovalManifest {
  manifest_id: string;
  surface: string;
  state: ManifestState;
  item_count: number;
  run_ref?: string | null;
  product_id?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  invalidation_reason?: string | null;
  items: ExecutionApprovalSnapshot[];
}

export function getManifest(manifestId: string): Promise<ApprovalManifest> {
  return getAPI<ApprovalManifest>(
    `/api/execution-approval/manifest/${encodeURIComponent(manifestId)}`,
  );
}

export function approveManifest(
  manifestId: string,
  approvedBy: string,
): Promise<ApprovalManifest> {
  return postAPI<ApprovalManifest>(
    `/api/execution-approval/manifest/${encodeURIComponent(manifestId)}/approve`,
    { approved_by: approvedBy },
  );
}

export function invalidateManifest(
  manifestId: string,
  reason: string,
): Promise<ApprovalManifest> {
  return postAPI<ApprovalManifest>(
    `/api/execution-approval/manifest/${encodeURIComponent(manifestId)}/invalidate`,
    { reason },
  );
}

export function editManifestItem(
  manifestId: string,
  snapshotId: string,
  editedPromptText: string,
  editorId?: string,
): Promise<ApprovalManifest> {
  return postAPI<ApprovalManifest>(
    `/api/execution-approval/manifest/${encodeURIComponent(manifestId)}` +
      `/item/${encodeURIComponent(snapshotId)}/edit`,
    { edited_prompt_text: editedPromptText, editor_id: editorId ?? null },
  );
}

// Materialise the montage run's per-scene FINAL prompts into a review manifest.
export function materializeMontageManifest(runId: string): Promise<ApprovalManifest> {
  return postAPI<ApprovalManifest>(
    `/api/montage/runs/${encodeURIComponent(runId)}/materialize-approval-manifest`,
    {},
  );
}
