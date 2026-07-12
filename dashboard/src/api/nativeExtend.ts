// Typed client for the native Flow Extend surface. All calls go through the ONE
// authoritative backend path (/api/flow/extend-run) or the read-only resolver /
// lineage endpoints. Live execution is available only after the backend issues a
// process-local, single-use authorization bound to the reviewed plan and count.
import { getAPI, postAPI } from './client';

export interface NativeExtendResolution {
  route_id: string;
  transport_proven: boolean;
  duration_plan_authorized: boolean;
  block_plan: number[] | null;
  parent_ready: boolean;
  project_ready: boolean;
  scene_ready: boolean;
  project_scene_ready: boolean;
  route_executable: boolean;
  final_concat_export_available: boolean;
  model_key: string;
  block_duration_seconds: number;
  planned_block_count: number;
  planned_operation_count: number;
  blockers: string[];
}

export interface ExtendPlanBlock {
  block_index: number;
  position: number;
  parent_operation_id: string | null;
  child_operation_id: string | null;
  needs_submit?: boolean;
  polling_state: string;
  planned_request?: {
    endpoint: string;
    videoModelKey: string;
    videoInput: Record<string, unknown>;
    sceneContext: Record<string, unknown>;
  };
}

export interface ExtendRunResult {
  dry_run: boolean;
  project_id: string;
  scene_id: string;
  source_operation_id: string;
  planned_operation_count: number;
  block_count: number;
  model_key: string;
  blocks: ExtendPlanBlock[];
  plan?: unknown[];
  chain?: string[];
}

export interface ExtendLineageRow {
  extend_lineage_id: string;
  block_index: number | null;
  block_position: number | null;
  parent_operation_id: string | null;
  child_operation_id: string | null;
  child_primary_media_id: string | null;
  polling_state: string;
}

export interface ExtendBlockInput {
  block_index: number;
  position: number;
  prompt: string;
  is_final?: boolean;
}

export interface NativeExtendLiveAuthorization {
  authorization_token: string;
  planned_operation_count: number;
  expires_in_seconds: number;
}

export interface NativeExtendRunInput {
  project_id: string;
  scene_id: string;
  source_operation_id: string;
  blocks: ExtendBlockInput[];
  aspect_ratio?: string;
  dry_run: boolean;
  confirm_live_credit_burn?: boolean;
  confirmed_extend_operation_count?: number;
  live_authorization_token?: string;
}

export async function resolveNativeExtend(input: {
  project_id?: string | null;
  scene_id?: string | null;
  source_operation_id?: string | null;
  planned_block_count?: number;
  total_duration_seconds?: number | null;
}): Promise<NativeExtendResolution> {
  return postAPI('/api/flow/native-extend/resolve', input);
}

/** DRY-RUN ONLY. Returns the resume-aware plan + planned_operation_count; spends nothing. */
export async function previewNativeExtend(input: {
  project_id: string;
  scene_id: string;
  source_operation_id: string;
  blocks: ExtendBlockInput[];
  aspect_ratio?: string;
}): Promise<ExtendRunResult> {
  return postAPI('/api/flow/extend-run', { ...input, dry_run: true });
}

export async function requestNativeExtendLiveAuthorization(
  input: NativeExtendRunInput,
): Promise<NativeExtendLiveAuthorization> {
  return postAPI('/api/flow/native-extend/live-authorization', input);
}

export async function runNativeExtend(input: NativeExtendRunInput): Promise<ExtendRunResult> {
  return postAPI('/api/flow/extend-run', input);
}

export async function fetchNativeExtendLineage(
  projectId: string,
): Promise<{ lineage: ExtendLineageRow[]; count: number }> {
  return getAPI(`/api/flow/native-extend/lineage?project_id=${encodeURIComponent(projectId)}`);
}

// ─── Extend source auto-inheritance (SEV-1 UX repair — no raw ids) ───────────
export interface ExtendSourceCandidate {
  media_id: string;
  job_id: string | null;
  project_id: string;
  created_at: string | null;
  product_id: string | null;
  product_name: string | null;
  request_id: string | null;
  workspace_generation_package_id: string | null;
}

export interface ExtendResolvedSource {
  project_id: string;
  scene_id: string;
  source_operation_id: string;
  scene_display_name: string | null;
  verified: boolean;
}

/** Finished Block-1 clips usable as Extend parents (newest first, zero credit). */
export async function fetchNativeExtendSourceCandidates(
  limit = 8,
): Promise<{ candidates: ExtendSourceCandidate[]; count: number }> {
  return getAPI(`/api/flow/native-extend/source-candidates?limit=${limit}`);
}

/** Verify one finished clip inside its project and return the full parent context. */
export async function resolveNativeExtendSource(input: {
  media_id: string;
  project_id: string;
}): Promise<ExtendResolvedSource> {
  return postAPI('/api/flow/native-extend/resolve-source', input);
}


// ─── ONE logical full-video job (final timeline render) ─────────────────────
export interface VideoJob {
  job_id: string;
  status: string;
  scene_id?: string | null;
  segments?: string[];
  segments_needed?: number;
  requested_duration_seconds?: number | null;
  final_media_id?: string | null;
  final_local_path?: string | null;
  final_duration_s?: number | null;
  next?: string;
}

export interface FinalizeResult {
  dry_run: boolean;
  status: string;
  job_id: string;
  planned_render_operation_count?: number;
  final_media_id?: string;
  measured_duration_s?: number;
  size_mb?: number;
  sha256?: string;
}

export async function createVideoJob(input: {
  source_media_id: string;
  project_id: string;
  requested_total_duration_seconds: number;
  product_id?: string | null;
  product_name?: string | null;
}): Promise<VideoJob> {
  return postAPI('/api/flow/video-jobs', input);
}

export async function finalizeVideoJob(
  jobId: string,
  input: { dry_run: boolean; confirm_live_credit_burn?: boolean },
): Promise<FinalizeResult> {
  return postAPI(`/api/flow/video-jobs/${encodeURIComponent(jobId)}/finalize`, input);
}


// ─── Durable, server-owned full-video job ───────────────────────────────────
export interface VideoJobPlan {
  job_id: string;
  status: string;
  plan_fingerprint: string;
  reused?: boolean;
  plan: {
    requested_seconds: number;
    segment_count: number;
    operation_counts: {
      initial_generation: number;
      extend: number;
      final_render: number;
      total: number;
    };
    credit_estimate: Record<string, string>;
  };
}

export interface VideoJobStatus {
  job_id: string;
  status: string;
  human_stage: string;
  error_code?: string | null;
  requested_duration_seconds?: number | null;
  product_name?: string | null;
  plan?: VideoJobPlan['plan'];
  final_media_id?: string | null;
  final_duration_s?: number | null;
  complete: boolean;
  credit_summary: 'NOT_SPENT' | 'MAY_HAVE_SPENT' | 'SPENT' | 'UNKNOWN';
  no_credit_used: boolean;
}

export interface VideoJobAuthorization {
  job_id: string;
  authorization_token: string;
  authorization_id?: string;
  expires_in_seconds: number;
}

export type VideoJobPlanIntent = {
  product_id?: string | null;
  product_name?: string | null;
  execution_package_id?: string | null;
  approved_asset_sha256?: string | null;
  requested_total_duration_seconds: number;
  engine?: string | null;
  model?: string | null;
  aspect_ratio?: string;
  initial_prompt_fingerprint?: string | null;
  execution_mode?: string;
  client_request_nonce?: string | null;
};

export interface VideoJobLookup {
  found: boolean;
  job_id?: string;
  status?: string;
  plan_fingerprint?: string;
  plan?: VideoJobPlan['plan'] | null;
  logical_job_key?: string;
}

/** READ-ONLY mount/refresh restore: returns the existing logical job (if any)
 *  without creating a job, resolving authority, or writing anything. */
export async function lookupVideoJob(intent: VideoJobPlanIntent): Promise<VideoJobLookup> {
  return postAPI('/api/flow/video-jobs/lookup', intent);
}

export async function planVideoJob(intent: VideoJobPlanIntent): Promise<VideoJobPlan> {
  return postAPI('/api/flow/video-jobs/plan', intent);
}

export async function authorizeVideoJob(
  jobId: string,
  confirmedPlanFingerprint: string,
): Promise<VideoJobAuthorization> {
  return postAPI(`/api/flow/video-jobs/${encodeURIComponent(jobId)}/authorize`, {
    confirmed_plan_fingerprint: confirmedPlanFingerprint,
  });
}

export async function startVideoJob(jobId: string): Promise<VideoJobStatus> {
  return postAPI(`/api/flow/video-jobs/${encodeURIComponent(jobId)}/start`, {});
}

export async function getVideoJobStatus(jobId: string): Promise<VideoJobStatus> {
  return getAPI(`/api/flow/video-jobs/${encodeURIComponent(jobId)}/status`);
}
