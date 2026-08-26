// Benefit On-Demand Copy source (Round 2) — self-contained Step-2 body: pick an
// atom-ready benefit, then render/lock/finalize scripts into N READY packages.
// Self-contained hooks keep host pages free of any hook-ordering change. This is a
// DISTINCT authority (BENEFIT_COPY_RENDER_V1) — never a Copy Register V2 binding.
import { useEffect, useState } from 'react'
import { getProductCapacity, type BenefitCapacity } from '../../api/creativeFactory'
import type { CopyRenderLane } from '../../api/copyRender'
import OnDemandCopyRendererPanel from './OnDemandCopyRendererPanel'

export interface BenefitCopySourceSectionProps {
  productId?: string | null
  lane: CopyRenderLane
  durationSeconds: number
  targetLanguage?: string
  /** Neutral readiness signal — TRUE once a finalized rendered selection exists.
   * This is NOT the Copy Register V2 readiness signal. */
  onReadyChange?: (ready: boolean) => void
}

export function BenefitCopySourceSection(props: BenefitCopySourceSectionProps) {
  const { productId, lane, durationSeconds, targetLanguage = 'BM_MS', onReadyChange } = props
  const [benefits, setBenefits] = useState<BenefitCapacity[]>([])
  const [benefitId, setBenefitId] = useState<string>('')
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    onReadyChange?.(false)
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
          onChange={(e) => { setBenefitId(e.target.value); onReadyChange?.(false) }}
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
          onCopySelected={() => onReadyChange?.(true)}
        />
      ) : null}
    </div>
  )
}

export default BenefitCopySourceSection
