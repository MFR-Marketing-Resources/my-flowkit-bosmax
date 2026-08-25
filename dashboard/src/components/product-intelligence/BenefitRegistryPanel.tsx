// Benefit Registry — the row-based foundation of the Benefit-Centric Creative
// Factory. Normal fields are Benefit (required) + Usage Hint (optional). Every
// row shows its deterministic Product-Intelligence verdict; REVIEW_REQUIRED rows
// open an audited manual VERIFY / BLOCK review. All strings are English.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  buildBenefit,
  createBenefit,
  deleteBenefit,
  getReviewContext,
  listBenefits,
  recheckBenefit,
  resolveReview,
  updateBenefit,
  type Benefit,
  type BenefitStatus,
  type ReviewAction,
  type ReviewContext,
} from '../../api/creativeFactory'
import { Badge, type BadgeTone, Section } from '../ui'

const STATUS_TONE: Record<BenefitStatus, BadgeTone> = {
  VERIFIED: 'success',
  REVIEW_REQUIRED: 'warn',
  BLOCKED: 'danger',
  DRAFT: 'neutral',
  ARCHIVED: 'neutral',
}

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

export function BenefitRegistryPanel({
  productId,
  onMutate,
}: {
  productId: string
  onMutate?: () => void
}) {
  const [benefits, setBenefits] = useState<Benefit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const [newBenefit, setNewBenefit] = useState('')
  const [newUsage, setNewUsage] = useState('')

  const [editId, setEditId] = useState<string | null>(null)
  const [editBenefit, setEditBenefit] = useState('')
  const [editUsage, setEditUsage] = useState('')

  const [reviewFor, setReviewFor] = useState<ReviewContext | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listBenefits(productId)
      setBenefits(res.benefits)
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setLoading(false)
    }
  }, [productId])

  useEffect(() => {
    void reload()
  }, [reload])

  const afterMutate = useCallback(async () => {
    await reload()
    onMutate?.()
  }, [reload, onMutate])

  const handleAdd = useCallback(async () => {
    if (!newBenefit.trim()) return
    setBusyId('__add__')
    setError(null)
    try {
      await createBenefit(productId, newBenefit.trim(), newUsage.trim() || null)
      setNewBenefit('')
      setNewUsage('')
      await afterMutate()
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusyId(null)
    }
  }, [productId, newBenefit, newUsage, afterMutate])

  const runRow = useCallback(
    async (id: string, fn: () => Promise<unknown>) => {
      setBusyId(id)
      setError(null)
      try {
        await fn()
        await afterMutate()
      } catch (e) {
        setError(errMessage(e))
      } finally {
        setBusyId(null)
      }
    },
    [afterMutate],
  )

  const beginEdit = (b: Benefit) => {
    setEditId(b.benefit_id)
    setEditBenefit(b.canonical_text)
    setEditUsage(b.usage_hint ?? '')
  }

  const saveEdit = (b: Benefit) =>
    runRow(b.benefit_id, async () => {
      await updateBenefit(b.benefit_id, { benefit: editBenefit.trim(), usage_hint: editUsage.trim() || null })
      setEditId(null)
    })

  const openReview = async (b: Benefit) => {
    setBusyId(b.benefit_id)
    setError(null)
    try {
      setReviewFor(await getReviewContext(b.benefit_id))
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusyId(null)
    }
  }

  const submitReview = (benefitId: string, action: ReviewAction, note: string) =>
    runRow(benefitId, async () => {
      await resolveReview(benefitId, action, note)
      setReviewFor(null)
    })

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const b of benefits) c[b.status] = (c[b.status] ?? 0) + 1
    return c
  }, [benefits])

  return (
    <Section
      step="1"
      title="Benefit Registry"
      helper="One row per product benefit. Benefit is required; Usage Hint is optional guidance (never a mandatory scene). Each row is cross-checked against approved Product Intelligence."
      action={
        <div className="flex gap-2 text-[10px] text-slate-400" data-testid="benefit-status-counts">
          <span>{benefits.length} total</span>
          <span className="text-emerald-300">{counts.VERIFIED ?? 0} verified</span>
          <span className="text-amber-300">{counts.REVIEW_REQUIRED ?? 0} review</span>
          <span className="text-red-300">{counts.BLOCKED ?? 0} blocked</span>
        </div>
      }
    >
      {error && (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200" role="alert">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-end gap-2" data-testid="add-benefit-form">
        <label className="flex-1 min-w-[220px] space-y-1">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">Benefit (required)</span>
          <input
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="e.g. Membantu melegakan rasa kembung"
            value={newBenefit}
            onChange={(e) => setNewBenefit(e.target.value)}
            data-testid="new-benefit-input"
          />
        </label>
        <label className="flex-1 min-w-[180px] space-y-1">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">Usage Hint (optional)</span>
          <input
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="e.g. Sapu sedikit pada bahagian perut"
            value={newUsage}
            onChange={(e) => setNewUsage(e.target.value)}
            data-testid="new-usage-input"
          />
        </label>
        <button
          type="button"
          className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-200 disabled:opacity-50"
          disabled={!newBenefit.trim() || busyId === '__add__'}
          onClick={() => void handleAdd()}
          data-testid="add-benefit-button"
        >
          + Add Benefit
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-xs">
          <thead className="text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-2 pr-2">#</th>
              <th className="py-2 pr-2">Benefit</th>
              <th className="py-2 pr-2">Usage Hint</th>
              <th className="py-2 pr-2">PI Check</th>
              <th className="py-2 pr-2">Status</th>
              <th className="py-2 pr-2">Actions</th>
            </tr>
          </thead>
          <tbody className="align-top" data-testid="benefit-rows">
            {loading && (
              <tr>
                <td colSpan={6} className="py-4 text-slate-500">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && benefits.length === 0 && (
              <tr>
                <td colSpan={6} className="py-4 text-slate-500">
                  No benefits yet. Add the first benefit above.
                </td>
              </tr>
            )}
            {!loading &&
              benefits.map((b, i) => {
                const isEditing = editId === b.benefit_id
                const busy = busyId === b.benefit_id
                return (
                  <tr key={b.benefit_id} className="border-t border-slate-800" data-testid={`benefit-row-${b.benefit_id}`}>
                    <td className="py-2 pr-2 text-slate-500">{i + 1}</td>
                    <td className="py-2 pr-2 text-slate-100">
                      {isEditing ? (
                        <input
                          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
                          value={editBenefit}
                          onChange={(e) => setEditBenefit(e.target.value)}
                        />
                      ) : (
                        b.canonical_text
                      )}
                    </td>
                    <td className="py-2 pr-2 text-slate-300">
                      {isEditing ? (
                        <input
                          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
                          value={editUsage}
                          onChange={(e) => setEditUsage(e.target.value)}
                        />
                      ) : (
                        b.usage_hint || <span className="text-slate-600">—</span>
                      )}
                    </td>
                    <td className="py-2 pr-2 text-slate-400">
                      <span title={b.pi_check?.reason ?? ''}>{b.pi_check?.reason ?? '—'}</span>
                      {typeof b.pi_check?.similarity?.score === 'number' && (
                        <span className="ml-1 text-slate-600">({b.pi_check.similarity.score})</span>
                      )}
                    </td>
                    <td className="py-2 pr-2">
                      <Badge tone={STATUS_TONE[b.status]}>{b.status}</Badge>
                    </td>
                    <td className="py-2 pr-2">
                      <div className="flex flex-wrap gap-1">
                        {isEditing ? (
                          <>
                            <RowButton disabled={busy} onClick={() => void saveEdit(b)}>
                              Save
                            </RowButton>
                            <RowButton disabled={busy} onClick={() => setEditId(null)}>
                              Cancel
                            </RowButton>
                          </>
                        ) : (
                          <>
                            <RowButton disabled={busy} onClick={() => beginEdit(b)}>
                              Edit
                            </RowButton>
                            <RowButton disabled={busy} onClick={() => void runRow(b.benefit_id, () => recheckBenefit(b.benefit_id))}>
                              Re-check
                            </RowButton>
                            {b.status === 'REVIEW_REQUIRED' && (
                              <RowButton tone="warn" disabled={busy} onClick={() => void openReview(b)}>
                                Review
                              </RowButton>
                            )}
                            {b.status === 'VERIFIED' && (
                              <RowButton
                                tone="success"
                                disabled={busy}
                                onClick={() => void runRow(b.benefit_id, () => buildBenefit(productId, b.benefit_id))}
                              >
                                Build atoms
                              </RowButton>
                            )}
                            <RowButton tone="danger" disabled={busy} onClick={() => void runRow(b.benefit_id, () => deleteBenefit(b.benefit_id))}>
                              Remove
                            </RowButton>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
          </tbody>
        </table>
      </div>

      {reviewFor && (
        <ReviewModal
          context={reviewFor}
          onClose={() => setReviewFor(null)}
          onResolve={(action, note) => void submitReview(reviewFor.benefit.benefit_id, action, note)}
        />
      )}
    </Section>
  )
}

function RowButton({
  children,
  onClick,
  disabled,
  tone = 'neutral',
}: {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
  tone?: 'neutral' | 'success' | 'warn' | 'danger'
}) {
  const tones: Record<string, string> = {
    neutral: 'border-slate-700 text-slate-300 hover:bg-slate-800',
    success: 'border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/10',
    warn: 'border-amber-500/40 text-amber-200 hover:bg-amber-500/10',
    danger: 'border-red-500/40 text-red-200 hover:bg-red-500/10',
  }
  return (
    <button
      type="button"
      className={`rounded border px-2 py-1 text-[10px] font-semibold disabled:opacity-40 ${tones[tone]}`}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

function ReviewModal({
  context,
  onClose,
  onResolve,
}: {
  context: ReviewContext
  onClose: () => void
  onResolve: (action: ReviewAction, note: string) => void
}) {
  const [note, setNote] = useState('')
  const check = context.current_check
  const snapshot = context.approved_snapshot as
    | { benefits?: string[]; allowed_claims?: string[]; snapshot_id?: string; version?: number }
    | null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" data-testid="review-modal">
      <div className="w-full max-w-lg space-y-3 rounded-2xl border border-slate-700 bg-slate-900 p-5 text-sm">
        <h4 className="text-sm font-bold text-slate-100">Review benefit</h4>
        <p className="text-slate-200">{context.benefit.canonical_text}</p>
        {context.usage_hint && <p className="text-xs text-slate-400">Usage: {context.usage_hint}</p>}
        <div className="rounded-md border border-slate-800 bg-slate-950 p-3 text-xs text-slate-300 space-y-1">
          <p>Reason: {check?.reason ?? '—'}</p>
          <p>
            Similarity: {check?.similarity?.score ?? 0}
            {check?.similarity?.matched_text ? ` → "${check.similarity.matched_text}"` : ''}
          </p>
          <p>Claim gate: {check?.claim_gate ?? '—'}</p>
          {snapshot && (
            <p className="text-slate-500">
              PI snapshot {snapshot.snapshot_id ?? '—'} v{snapshot.version ?? '—'}
              {snapshot.benefits ? ` · ${snapshot.benefits.length} approved benefits` : ''}
            </p>
          )}
        </div>
        <label className="block space-y-1">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">Reviewer note (required)</span>
          <textarea
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            data-testid="review-note"
          />
        </label>
        <div className="flex justify-end gap-2">
          <RowButton onClick={onClose}>Cancel</RowButton>
          <RowButton tone="danger" disabled={!note.trim()} onClick={() => onResolve('BLOCK', note.trim())}>
            Block Benefit
          </RowButton>
          <RowButton tone="success" disabled={!note.trim()} onClick={() => onResolve('VERIFY', note.trim())}>
            Verify Benefit
          </RowButton>
        </div>
      </div>
    </div>
  )
}
