// Benefit-Centric Creative Factory (Round 1) API client.
// Imports ONLY ./client so this feature stays disjoint from the frozen
// Copy Register V2 / Storyboard V3 modules.
import { deleteAPI, getAPI, patchAPI, postAPI } from './client'

export type BenefitStatus = 'DRAFT' | 'VERIFIED' | 'REVIEW_REQUIRED' | 'BLOCKED' | 'ARCHIVED'
export type ReviewAction = 'VERIFY' | 'BLOCK'

export interface PiSimilarity {
  score: number
  matched_text: string | null
  method: string | null
}

export interface PiCheck {
  verdict?: BenefitStatus
  reason?: string
  hard_safety_blocked?: boolean
  claim_gate?: string | null
  claim_risk_level?: string | null
  has_authority?: boolean
  snapshot_id?: string | null
  snapshot_version?: number | null
  similarity?: PiSimilarity
  similarity_threshold?: number
  evidence_counts?: Record<string, number>
}

export interface Benefit {
  benefit_id: string
  product_id: string
  canonical_text: string
  benefit: string
  usage_hint: string | null
  status: BenefitStatus
  pi_snapshot_id: string | null
  pi_snapshot_version: number | null
  pi_check: PiCheck
  provenance: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface BenefitCapacity {
  benefit_id: string
  angles: number
  hooks: number
  bodies: number
  ctas: number
  combinations: number
  stale_atoms: number
  complete: boolean
  status?: BenefitStatus
  benefit?: string
  ready?: boolean
}

export interface ProductCapacity {
  product_id: string
  benefit_counts: Record<string, number>
  verified_benefits: number
  ready_benefits: number
  creative_factory_ready: boolean
  totals: { angles: number; hooks: number; bodies: number; ctas: number; combinations: number }
  default_benefit_capacity: number
  per_benefit: BenefitCapacity[]
}

export interface BuildPlan {
  product_id: string
  verified_benefit_count: number
  expected_provider_calls: number
  benefits: { benefit_id: string; benefit: string }[]
}

export interface BuildResult {
  build_id: string
  benefit_id: string
  status: string
  provider_calls: number
  counts: { angles: number; hooks: number; bodies: number; ctas: number }
  capacity: BenefitCapacity
}

export interface BatchBuildResult {
  product_id: string
  confirmed: boolean
  verified_benefit_count: number
  provider_calls: number
  results: { benefit_id: string; status: string; error?: string; message?: string }[]
}

export interface ReviewContext {
  benefit: Benefit
  usage_hint: string | null
  current_check: PiCheck
  approved_snapshot: Record<string, unknown> | null
  reviews: Record<string, unknown>[]
  resolvable: boolean
}

const BASE = '/api/creative-factory'
const q = (v: string) => encodeURIComponent(v)

export async function listBenefits(productId: string): Promise<{ product_id: string; benefits: Benefit[]; count: number }> {
  return getAPI(`${BASE}/benefits?product_id=${q(productId)}`)
}

export async function createBenefit(
  productId: string,
  benefit: string,
  usageHint?: string | null,
): Promise<Benefit> {
  return postAPI(`${BASE}/benefits`, {
    product_id: productId,
    benefit,
    usage_hint: usageHint ?? null,
  })
}

export async function updateBenefit(
  benefitId: string,
  fields: { benefit?: string; usage_hint?: string | null },
): Promise<Benefit> {
  return patchAPI(`${BASE}/benefits/${q(benefitId)}`, fields)
}

export async function deleteBenefit(benefitId: string): Promise<void> {
  return deleteAPI(`${BASE}/benefits/${q(benefitId)}`)
}

export async function recheckBenefit(benefitId: string): Promise<Benefit> {
  return postAPI(`${BASE}/benefits/${q(benefitId)}/recheck`, {})
}

export async function getReviewContext(benefitId: string): Promise<ReviewContext> {
  return getAPI(`${BASE}/benefits/${q(benefitId)}/review-context`)
}

export async function resolveReview(
  benefitId: string,
  action: ReviewAction,
  reviewerNote: string,
): Promise<Benefit> {
  return postAPI(`${BASE}/benefits/${q(benefitId)}/review`, {
    action,
    reviewer_note: reviewerNote,
  })
}

export async function buildBenefit(productId: string, benefitId: string): Promise<BuildResult> {
  return postAPI(`${BASE}/build`, { product_id: productId, benefit_id: benefitId })
}

export async function getBuildPlan(productId: string): Promise<BuildPlan> {
  return getAPI(`${BASE}/build-plan?product_id=${q(productId)}`)
}

export async function buildVerified(productId: string, confirm: boolean): Promise<BatchBuildResult> {
  return postAPI(`${BASE}/build-verified`, { product_id: productId, confirm })
}

export async function getProductCapacity(productId: string): Promise<ProductCapacity> {
  return getAPI(`${BASE}/capacity?product_id=${q(productId)}`)
}
