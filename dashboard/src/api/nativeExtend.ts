// Typed client for the native Flow Extend surface. All calls go through the ONE
// authoritative backend path (/api/flow/extend-run) or the read-only resolver /
// lineage endpoints. Nothing here can spend credits: preview is dry-run only, and a
// live run is intentionally NOT exposed from the dashboard (it runs server-side
// through the orchestrator with NATIVE_EXTEND_ENABLED + a bounded confirmed count).
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
  output_url: string | null;
}

export interface ExtendBlockInput {
  block_index: number;
  position: number;
  prompt: string;
  is_final?: boolean;
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

export async function fetchNativeExtendLineage(
  projectId: string,
): Promise<{ lineage: ExtendLineageRow[]; count: number }> {
  return getAPI(`/api/flow/native-extend/lineage?project_id=${encodeURIComponent(projectId)}`);
}
