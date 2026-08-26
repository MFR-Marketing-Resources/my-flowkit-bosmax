// Benefit On-Demand Copy source (Round 2) — self-contained Step-2 body: pick an
// atom-ready benefit, then render/lock/finalize scripts into N READY packages.
// Self-contained hooks keep host pages free of any hook-ordering change. This is a
// DISTINCT authority (BENEFIT_COPY_RENDER_V1) — never a Copy Register V2 binding.
import { useEffect, useState } from 'react'
import { getProductCapacity, type BenefitCapacity } from '../../api/creativeFactory'
import type { CopyRenderLane } from '../../api/copyRender'
import OnDemandCopyRendererPanel from './OnDemandCopyRendererPanel'

/** Immutable request-scoped execution identity of a finalized Benefit On-Demand
 * selection. This is a DISTINCT authority (BENEFIT_COPY_RENDER_V1) — never a Copy
 * Register V2 binding. The host page threads `candidate_id` into the compile and
 * generate request context so `resolve_execution_copy` resolves this exact rendered
 * copy instead of falling back to the persisted product-global Copy V2 binding. */
export interface BenefitCopyExecutionContext {
  authority_kind: 'BENEFIT_COPY_RENDER_V1'
  lane: CopyRenderLane
  session_id: string
  candidate_id: string
  duration_seconds: number
}

export interface BenefitCopySourceSectionProps {
  productId?: string | null
  lane: CopyRenderLane
  durationSeconds: number
  targetLanguage?: string
  /** Neutral readiness signal — TRUE once a finalized rendered selection exists.
   * This is NOT the Copy Register V2 readiness signal. */
  onReadyChange?: (ready: boolean) => void
  /** Propagate (or clear) the selected finalized execution identity so the host
   * operator carries `benefit_copy_render.candidate_id` into compile/generate.
   * Emitted `null` whenever the selection is not/no-longer valid. Without this the
   * operator would only know `copyReady=true` and silently fall back to Copy V2. */
  onSelectedCopyChange?: (context: BenefitCopyExecutionContext | null) => void
}

export function BenefitCopySourceSection(props: BenefitCopySourceSectionProps) {
  const { productId, lane, durationSeconds, targetLanguage = 'BM_MS', onReadyChange, onSelectedCopyChange } = props
  const [benefits, setBenefits] = useState<BenefitCapacity[]>([])
  const [benefitId, setBenefitId] = useState<string>('')
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    onReadyChange?.(false)
    onSelectedCopyChange?.(null)
    setBenefitId('')
    if (!productId) {
      setBenefits([])
      return
    }
    let cancelled = false
    void getProductCapacity(productId)
      .then((cap) => {
        if (cancelled) return
        const ready = (cap.per_benefit || []).filter((b) => b.ready && (b.combinations ?? 0) > 0)
        setBenefits(ready)
        setLoadError(null)
      })
      .catch((e) => {
        if (cancelled) return
        setBenefits([])
        setLoadError(e instanceof Error ? e.message : 'Failed to load benefits.')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId])

  if (!productId) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/30 p-4 text-xs text-slate-500">
        Select a product in Step 1 to render benefit-driven copy.
      </div>
    )
  }

  return (
    <div className="space-y-3" data-testid="benefit-copy-source">
      <div className="space-y-1.5">
        <label htmlFor="cr-benefit" className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
          Benefit
        </label>
        <select
          id="cr-benefit" value={benefitId}
          onChange={(e) => { setBenefitId(e.target.value); onReadyChange?.(false); onSelectedCopyChange?.(null) }}
          className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200"
        >
          <option value="">Choose an atom-ready benefit…</option>
          {benefits.map((b) => (
            <option key={b.benefit_id} value={b.benefit_id}>
              {b.benefit || b.benefit_id} · {b.combinations} recipes
            </option>
          ))}
        </select>
        {loadError ? (
          <div className="text-[11px] text-rose-300">{loadError}</div>
        ) : benefits.length === 0 ? (
          <div className="text-[11px] text-slate-500">
            No atom-ready benefit yet. Build Creative Atoms for a VERIFIED benefit first.
          </div>
        ) : null}
      </div>

      {benefitId ? (
        <OnDemandCopyRendererPanel
          key={benefitId}
          productId={productId}
          benefitId={benefitId}
          lane={lane}
          durationSeconds={durationSeconds}
          targetLanguage={targetLanguage}
          onCopySelected={({ session, prepared }) => {
            // Carry the finalized selection identity up so the operator sends
            // benefit_copy_render.candidate_id (never collapse it to copyReady=true).
            const pkg =
              (prepared.packages || []).find((p) => p.status === 'READY' && p.candidate_id) ??
              (prepared.packages || []).find((p) => p.candidate_id)
            if (pkg?.candidate_id) {
              onSelectedCopyChange?.({
                authority_kind: 'BENEFIT_COPY_RENDER_V1',
                lane,
                session_id: session.session_id,
                candidate_id: pkg.candidate_id,
                duration_seconds: session.duration_seconds,
              })
              onReadyChange?.(true)
            } else {
              onSelectedCopyChange?.(null)
              onReadyChange?.(false)
            }
          }}
        />
      ) : null}
    </div>
  )
}

export default BenefitCopySourceSection
