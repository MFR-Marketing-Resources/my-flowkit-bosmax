// On-Demand Copy Renderer (Round 2) API client.
// Imports ONLY ./client so this feature stays disjoint from the Copy Register V2
// module. SYSTEM OWNS STRUCTURE; AI ONLY STITCHES. A benefit-render candidate is a
// distinct authority — NEVER a V2 binding.
import { getAPI, patchAPI, postAPI } from './client'

export type CopyRenderLane = 'HYBRID' | 'FACELESS'
export type CopyRenderStatus = 'OPEN' | 'TARGET_COMPLETE' | 'FINALIZED' | 'STALE' | 'CANCELLED'
export type CandidateStatus = 'SHOWN' | 'LOCKED' | 'SKIPPED' | 'FINALIZED'

export interface CopyRenderStage {
  stage_key: string
  text: string
}

export interface CopyRenderCandidate {
  candidate_id: string
  status: CandidateStatus
  recipe_fingerprint: string
  text_digest: string
  batch_id: string
  artifact_id: string
  full_copy_text: string | null
  word_count: number | null
  stages: CopyRenderStage[]
}

export interface CopyRenderBatchView {
  batch_id: string
  batch_number: number
  request_id: string
  action: 'GENERATE' | 'REGENERATE'
  status: 'RESERVED' | 'RUNNING' | 'SHOWN' | 'FAILED'
  provider_calls: number | null
  cache_hit_count: number | null
  failure_code: string | null
}

export interface CopyRenderSession {
  session_id: string
  product_id: string
  benefit_id: string
  lane: CopyRenderLane
  duration_seconds: number
  target_language: string
  formula_id: string
  word_budget: number
  target_count: number
  locked_count: number
  status: CopyRenderStatus
  regenerate_enabled: boolean
  total_unique_capacity: number
  used_recipe_count: number
  remaining_unique_capacity: number
  candidates: CopyRenderCandidate[]
  batches: CopyRenderBatchView[]
  finalized_at: string | null
  // present only on the Generate/Regenerate response
  provider_calls?: number
  batch_id?: string
}

export interface PreparedPackage {
  candidate_id: string
  package_id?: string
  artifact_id?: string
  reused?: boolean
  status: 'READY' | 'PACKAGE_ERROR'
  execution_allowed?: boolean
  blockers?: string[]
  prompt_fingerprint?: string
  error?: string
  detail?: string
}

export interface PrepareResult {
  session_id: string
  lane: CopyRenderLane
  package_count: number
  packages: PreparedPackage[]
  enqueued: boolean
}

export interface SelectedResult {
  session_id: string
  status: CopyRenderStatus
  count: number
  selected: {
    candidate_id: string
    status: CandidateStatus
    recipe_fingerprint: string
    full_copy_text: string | null
    word_count: number | null
    stages: CopyRenderStage[]
  }[]
}

const BASE = '/api/copy-render'
const q = (v: string) => encodeURIComponent(v)

/** A fresh per-Generate idempotency key. The SAME logical request never burns two
 * provider calls; a retry after failure must use a NEW request_id. */
export function newRequestId(): string {
  const g = globalThis as { crypto?: { randomUUID?: () => string } }
  if (g.crypto?.randomUUID) return `req-${g.crypto.randomUUID()}`
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

export interface CreateSessionInput {
  product_id: string
  benefit_id: string
  lane: CopyRenderLane
  target_count: number
  duration_seconds: number
  target_language?: string
  formula_id?: string | null
  /** Governed Avatar Registry presenter for a presenter-led (HYBRID) session, so the
   * session carries the visual config the backend requires before prepare-selected
   * (COPY_RENDER_HYBRID_AVATAR_REQUIRED). Reuse the operator's already-selected
   * presenter — never a default/substitute. Omit for avatar-exempt lanes (FACELESS). */
  avatar_id?: string | null
}

export async function createSession(input: CreateSessionInput): Promise<CopyRenderSession> {
  return postAPI(`${BASE}/sessions`, input)
}

export async function getSession(sessionId: string): Promise<CopyRenderSession> {
  return getAPI(`${BASE}/sessions/${q(sessionId)}`)
}

export async function updateTarget(sessionId: string, targetCount: number): Promise<CopyRenderSession> {
  return patchAPI(`${BASE}/sessions/${q(sessionId)}/target`, { target_count: targetCount })
}

/** Generate or Regenerate 5 suggestions. Pass a fresh requestId (see newRequestId). */
export async function generateSuggestions(sessionId: string, requestId: string): Promise<CopyRenderSession> {
  return postAPI(`${BASE}/sessions/${q(sessionId)}/suggestions`, { request_id: requestId })
}

export async function lockCandidate(candidateId: string): Promise<CopyRenderSession> {
  return postAPI(`${BASE}/candidates/${q(candidateId)}/lock`, {})
}

export async function unlockCandidate(candidateId: string): Promise<CopyRenderSession> {
  return postAPI(`${BASE}/candidates/${q(candidateId)}/unlock`, {})
}

export async function finalizeSession(sessionId: string): Promise<CopyRenderSession> {
  return postAPI(`${BASE}/sessions/${q(sessionId)}/finalize`, {})
}

export async function getSelected(sessionId: string): Promise<SelectedResult> {
  return getAPI(`${BASE}/sessions/${q(sessionId)}/selected`)
}

/** Materialize N READY prompt packages from the FINALIZED selection. This NEVER
 * enqueues production, runs video, or touches the Copy Register V2 binding. */
export async function prepareSelected(sessionId: string): Promise<PrepareResult> {
  return postAPI(`${BASE}/sessions/${q(sessionId)}/prepare-selected`, {})
}
