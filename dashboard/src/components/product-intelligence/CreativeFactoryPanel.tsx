// Creative Factory — deterministic capacity summary + the governed batch build.
// Capacity reads are provider-free. "Build Verified Benefits" previews the exact
// number of provider calls and requires explicit confirmation before spending
// them (amendment 4). English strings; distinct vocabulary from the frozen V3
// "Copywriting Landbank".
import { useCallback, useEffect, useState } from 'react'

import {
  buildVerified,
  getBuildPlan,
  getProductCapacity,
  type BatchBuildResult,
  type BuildPlan,
  type ProductCapacity,
} from '../../api/creativeFactory'
import { Badge, Section } from '../ui'

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

export function CreativeFactoryPanel({
  productId,
  reloadToken = 0,
  onMutate,
}: {
  productId: string
  reloadToken?: number
  onMutate?: () => void
}) {
  const [capacity, setCapacity] = useState<ProductCapacity | null>(null)
  const [plan, setPlan] = useState<BuildPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [building, setBuilding] = useState(false)
  const [result, setResult] = useState<BatchBuildResult | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [cap, pl] = await Promise.all([getProductCapacity(productId), getBuildPlan(productId)])
      setCapacity(cap)
      setPlan(pl)
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setLoading(false)
    }
  }, [productId])

  useEffect(() => {
    void reload()
  }, [reload, reloadToken])

  const runBatch = useCallback(async () => {
    if (!confirm) return
    setBuilding(true)
    setError(null)
    setResult(null)
    try {
      const res = await buildVerified(productId, true)
      setResult(res)
      setConfirm(false)
      await reload()
      onMutate?.()
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBuilding(false)
    }
  }, [confirm, productId, reload, onMutate])

  const totals = capacity?.totals
  const expectedCalls = plan?.expected_provider_calls ?? 0

  return (
    <Section
      step="2"
      title="Creative Factory · Build Capacity"
      helper="Verified benefits build into reusable Angle / Hook / Body / CTA atoms (162 combinations per complete benefit). Capacity is computed deterministically — reading it never calls a provider."
      action={
        capacity ? (
          <Badge tone={capacity.creative_factory_ready ? 'success' : 'neutral'}>
            {capacity.creative_factory_ready ? 'FACTORY READY' : 'NOT READY'}
          </Badge>
        ) : null
      }
    >
      {error && (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200" role="alert">
          {error}
        </p>
      )}

      {loading && <p className="text-xs text-slate-500">Loading capacity…</p>}

      {!loading && capacity && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6" data-testid="capacity-tiles">
            <Tile label="Verified" value={capacity.verified_benefits} />
            <Tile label="Ready" value={capacity.ready_benefits} />
            <Tile label="Angles" value={totals?.angles ?? 0} />
            <Tile label="Hooks" value={totals?.hooks ?? 0} />
            <Tile label="Bodies" value={totals?.bodies ?? 0} />
            <Tile label="Combinations" value={totals?.combinations ?? 0} highlight />
          </div>

          <div className="rounded-md border border-slate-800 bg-slate-950 p-3" data-testid="batch-build">
            <p className="text-xs text-slate-300">
              Build all verified benefits — <b>{plan?.verified_benefit_count ?? 0}</b> benefit(s), which will
              spend <b data-testid="expected-calls">{expectedCalls}</b> provider call(s) (one per benefit).
            </p>
            <label className="mt-2 flex items-center gap-2 text-xs text-slate-300">
              <input
                type="checkbox"
                checked={confirm}
                onChange={(e) => setConfirm(e.target.checked)}
                disabled={expectedCalls === 0 || building}
                data-testid="batch-confirm"
              />
              I confirm spending {expectedCalls} provider call(s).
            </label>
            <button
              type="button"
              className="mt-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-200 disabled:opacity-40"
              disabled={!confirm || expectedCalls === 0 || building}
              onClick={() => void runBatch()}
              data-testid="batch-build-button"
            >
              {building ? 'Building…' : 'Build Verified Benefits'}
            </button>
            {result && (
              <p className="mt-2 text-xs text-slate-400" data-testid="batch-result">
                {result.provider_calls} call(s) ·{' '}
                {result.results.filter((r) => r.status === 'COMPLETED').length} completed ·{' '}
                {result.results.filter((r) => r.status === 'FAILED').length} failed
              </p>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2 pr-2">Benefit</th>
                  <th className="py-2 pr-2">Status</th>
                  <th className="py-2 pr-2">Combinations</th>
                  <th className="py-2 pr-2">Complete</th>
                  <th className="py-2 pr-2">Stale</th>
                </tr>
              </thead>
              <tbody data-testid="per-benefit-capacity">
                {capacity.per_benefit.length === 0 && (
                  <tr>
                    <td colSpan={5} className="py-3 text-slate-500">
                      No benefits yet.
                    </td>
                  </tr>
                )}
                {capacity.per_benefit.map((b) => (
                  <tr key={b.benefit_id} className="border-t border-slate-800">
                    <td className="py-2 pr-2 text-slate-200">{b.benefit ?? b.benefit_id}</td>
                    <td className="py-2 pr-2 text-slate-400">{b.status ?? '—'}</td>
                    <td className="py-2 pr-2 text-slate-100">{b.combinations}</td>
                    <td className="py-2 pr-2">{b.complete ? '✓' : '—'}</td>
                    <td className="py-2 pr-2 text-slate-400">{b.stale_atoms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Section>
  )
}

function Tile({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div
      className={`rounded-md border px-3 py-2 ${
        highlight ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-slate-800 bg-slate-950'
      }`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-lg font-bold ${highlight ? 'text-emerald-200' : 'text-slate-100'}`}>{value}</div>
    </div>
  )
}
