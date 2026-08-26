// Creative Execution Recipe (Round 3) API client.
// Imports ONLY ./client so this feature stays disjoint from the Copy Register V2
// and On-Demand Copy Render modules. SYSTEM OWNS VISUAL VARIATION SELECTION /
// RECIPE LINEAGE / PROMPT SNAPSHOTS. Provider-free: nothing here enqueues
// production, spends credits, or touches the Copy Register V2 binding.
//
// One CreativeExecutionRecipeV1 binds one immutable rendered-copy identity
// (BENEFIT_COPY_RENDER_V1) + a production recipe (HYBRID/FACELESS/MONTAGE) + one
// deterministic governed visual variation + duration. `compile` materialises an
// immutable prompt snapshot (an existing workspace_execution_package). `remix`
// keeps the SAME copy identity and produces a NEW governed visual variation.
import { getAPI, postAPI } from './client'

export type ProductionRecipe = 'HYBRID' | 'FACELESS' | 'MONTAGE'

/** One durable CreativeExecutionRecipeV1 row. Only the load-bearing columns are
 * typed explicitly; the remaining lineage/snapshot columns pass through the index
 * signature. `status` is typically "DRAFT" or "FINALIZED". */
export interface CreativeExecutionRecipe {
  recipe_id: string
  recipe_identity_digest: string
  product_id: string
  production_recipe: ProductionRecipe
  candidate_id: string
  copy_session_id?: string | null
  artifact_id?: string | null
  benefit_id?: string | null
  copy_text_digest?: string | null
  copy_source?: string | null
  visual_variation_fingerprint: string
  visual_resolver_version?: string | null
  avatar_id?: string | null
  treatment_id?: string | null
  requested_total_duration_seconds?: number | null
  generation_mode?: string | null
  status: string
  workspace_execution_package_id?: string | null
  prompt_fingerprint?: string | null
  compiler_version?: string | null
  recipe_schema_version?: string
  created_at?: string
  finalized_at?: string | null
  [key: string]: unknown
}

export interface CreateExecutionRecipesRequest {
  candidate_id: string
  production_recipe: ProductionRecipe
  visual_count: number
  duration_seconds?: number
  avatar_id?: string
  treatment_id?: string
  seed?: string
}

/** Response of create + remix: N recipes for ONE immutable copy across N distinct
 * governed visual variations (SAME_SCRIPT_DIFF_VISUALS). */
export interface CreateExecutionRecipesResult {
  product_id: string
  production_recipe: ProductionRecipe
  copy_lane: string
  candidate_id: string
  requested_count: number
  unique_visual_capacity: number
  controlled_reuse_count: number
  recipes: CreativeExecutionRecipe[]
}

export interface ListExecutionRecipesParams {
  candidate_id?: string
  product_id?: string
  production_recipe?: ProductionRecipe
}

export interface ListExecutionRecipesResult {
  recipes: CreativeExecutionRecipe[]
  count: number
}

export interface CompileExecutionRecipeResult {
  recipe: CreativeExecutionRecipe
  reused: boolean
  workspace_execution_package_id: string | null
  prompt_fingerprint: string | null
  blockers?: string[]
}

export interface RemixExecutionRecipeRequest {
  seed: string
  visual_count?: number
}

const BASE = '/api/creative-execution-recipe'
const enc = (v: string) => encodeURIComponent(v)

/** Create `visual_count` recipes from ONE finalized rendered-copy candidate. */
export async function createExecutionRecipes(
  body: CreateExecutionRecipesRequest,
): Promise<CreateExecutionRecipesResult> {
  return postAPI(`${BASE}/recipes`, body)
}

export async function getExecutionRecipe(
  recipeId: string,
): Promise<CreativeExecutionRecipe> {
  return getAPI(`${BASE}/recipes/${enc(recipeId)}`)
}

export async function listExecutionRecipes(
  params: ListExecutionRecipesParams = {},
): Promise<ListExecutionRecipesResult> {
  const query = new URLSearchParams()
  if (params.candidate_id) query.set('candidate_id', params.candidate_id)
  if (params.product_id) query.set('product_id', params.product_id)
  if (params.production_recipe) query.set('production_recipe', params.production_recipe)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return getAPI(`${BASE}/recipes${suffix}`)
}

/** Provider-free compile into an immutable prompt snapshot. Idempotent: a FINALIZED
 * recipe returns its existing snapshot with `reused: true`. */
export async function compileExecutionRecipe(
  recipeId: string,
): Promise<CompileExecutionRecipeResult> {
  return postAPI(`${BASE}/recipes/${enc(recipeId)}/compile`, {})
}

/** Same copy identity, NEW governed visual variation(s). No copy-provider call. */
export async function remixExecutionRecipe(
  recipeId: string,
  body: RemixExecutionRecipeRequest,
): Promise<CreateExecutionRecipesResult> {
  return postAPI(`${BASE}/recipes/${enc(recipeId)}/remix`, body)
}
