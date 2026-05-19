import { useState, useEffect, useCallback } from 'react'
import type {
  BulkQueuePage,
  BulkQueueStats,
  BulkCreateDraftsResult,
  BulkApproveResult,
  BulkClaimRisk,
  BulkImageReadiness,
  BulkPromotionStatus,
} from '../../types'
import { getAPI, postAPI, patchAPI } from '../../api/client'

const RISK_BADGE: Record<string, string> = {
  LOW: 'bg-emerald-500/20 text-emerald-400',
  MEDIUM: 'bg-amber-500/20 text-amber-400',
  HIGH: 'bg-red-500/20 text-red-400',
  UNKNOWN: 'bg-slate-500/20 text-slate-400',
}

const STATUS_BADGE: Record<string, string> = {
  PENDING_DRAFT: 'bg-slate-500/20 text-slate-400',
  DRAFT_GENERATED: 'bg-blue-500/20 text-blue-400',
  READY_FOR_APPROVAL: 'bg-emerald-500/20 text-emerald-400',
  NEEDS_REVIEW: 'bg-amber-500/20 text-amber-400',
  MISSING_REQUIRED_FIELD: 'bg-orange-500/20 text-orange-400',
  CLAIM_RISK: 'bg-red-500/20 text-red-400',
  IMAGE_MISSING: 'bg-yellow-500/20 text-yellow-400',
  DUPLICATE_SUSPECTED: 'bg-purple-500/20 text-purple-400',
  APPROVED: 'bg-teal-500/20 text-teal-400',
  REJECTED: 'bg-slate-700/40 text-slate-500',
}

const ALL_STATUSES: BulkPromotionStatus[] = [
  'PENDING_DRAFT', 'DRAFT_GENERATED', 'READY_FOR_APPROVAL', 'NEEDS_REVIEW',
  'MISSING_REQUIRED_FIELD', 'CLAIM_RISK', 'IMAGE_MISSING', 'DUPLICATE_SUSPECTED',
  'APPROVED', 'REJECTED',
]

interface Props {
  onOpenDraft?: (draftId: string) => void
}

export default function BulkFastMossConvertTab({ onOpenDraft }: Props) {
  const [stats, setStats] = useState<BulkQueueStats | null>(null)
  const [queue, setQueue] = useState<BulkQueuePage | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [filterRisk, setFilterRisk] = useState<string>('')
  const [filterImage, setFilterImage] = useState<string>('')
  const [filterCategory, setFilterCategory] = useState<string>('')
  const [filterQ, setFilterQ] = useState<string>('')
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 50

  // Approval modal
  const [showApproveModal, setShowApproveModal] = useState(false)
  const [approvePhrase, setApprovePhrase] = useState('')

  const fetchStats = useCallback(async () => {
    try {
      const s = await getAPI<BulkQueueStats>('/api/fastmoss-bulk/queue/stats')
      setStats(s)
    } catch { /* non-fatal */ }
  }, [])

  const fetchQueue = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filterStatus) params.set('promotion_status', filterStatus)
      if (filterRisk) params.set('claim_risk_level', filterRisk)
      if (filterImage) params.set('image_readiness', filterImage)
      if (filterCategory) params.set('category', filterCategory)
      if (filterQ) params.set('q', filterQ)
      params.set('page', String(page))
      params.set('page_size', String(PAGE_SIZE))
      const data = await getAPI<BulkQueuePage>(`/api/fastmoss-bulk/queue?${params}`)
      setQueue(data)
    } catch (e: any) {
      setActionError(String(e?.message || 'Failed to load queue'))
    } finally {
      setLoading(false)
    }
  }, [filterStatus, filterRisk, filterImage, filterCategory, filterQ, page])

  useEffect(() => { fetchStats(); fetchQueue() }, [fetchStats, fetchQueue])

  const handleSync = async () => {
    setSyncing(true)
    setActionMessage(null)
    setActionError(null)
    try {
      const r = await postAPI<{ synced: number; skipped: number; errors: number }>(
        '/api/fastmoss-bulk/queue/sync', {}
      )
      setActionMessage(`Sync complete — synced: ${r.synced}, skipped: ${r.skipped}, errors: ${r.errors}`)
      await fetchStats()
      await fetchQueue()
    } catch (e: any) {
      setActionError(String(e?.message || 'Sync failed'))
    } finally {
      setSyncing(false)
    }
  }

  const handleGenerateSelected = async () => {
    if (!selected.size) return
    setActionMessage(null)
    setActionError(null)
    setLoading(true)
    try {
      const r = await postAPI<BulkCreateDraftsResult>('/api/fastmoss-bulk/queue/bulk-create-drafts', {
        reference_ids: Array.from(selected),
      })
      const newErrors: Record<string, string> = {}
      r.results.forEach(row => {
        if (row.status === 'ERROR') newErrors[row.reference_id] = row.error || 'UNKNOWN_ERROR'
      })
      setRowErrors(prev => ({ ...prev, ...newErrors }))
      setActionMessage(`Drafts — created: ${r.success}, failed: ${r.failed}`)
      setSelected(new Set())
      await fetchStats()
      await fetchQueue()
    } catch (e: any) {
      setActionError(String(e?.message || 'Bulk create failed'))
    } finally {
      setLoading(false)
    }
  }

  const handleApproveConfirm = async () => {
    if (approvePhrase !== 'PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH') {
      setActionError('Incorrect confirmation phrase')
      return
    }
    setShowApproveModal(false)
    setActionMessage(null)
    setActionError(null)
    setLoading(true)
    try {
      const r = await postAPI<BulkApproveResult>('/api/fastmoss-bulk/queue/bulk-approve-drafts', {
        reference_ids: Array.from(selected),
        confirmation_phrase: approvePhrase,
      })
      const newErrors: Record<string, string> = {}
      r.results.forEach(row => {
        if (row.outcome === 'FAILED') newErrors[row.reference_id] = row.reason || 'COMMIT_FAILED'
      })
      setRowErrors(prev => ({ ...prev, ...newErrors }))
      setActionMessage(`Approved: ${r.approved}, skipped (not ready): ${r.skipped}, failed: ${r.failed}`)
      setSelected(new Set())
      setApprovePhrase('')
      await fetchStats()
      await fetchQueue()
    } catch (e: any) {
      setActionError(String(e?.message || 'Bulk approve failed'))
    } finally {
      setLoading(false)
    }
  }

  const handleRejectSelected = async () => {
    if (!selected.size) return
    setActionMessage(null)
    setActionError(null)
    setLoading(true)
    try {
      await Promise.all(
        Array.from(selected).map(id =>
          patchAPI(`/api/fastmoss-bulk/queue/${id}/status`, { promotion_status: 'REJECTED' })
        )
      )
      setActionMessage(`Rejected ${selected.size} rows`)
      setSelected(new Set())
      await fetchStats()
      await fetchQueue()
    } catch (e: any) {
      setActionError(String(e?.message || 'Reject failed'))
    } finally {
      setLoading(false)
    }
  }

  const toggleRow = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    const ids = queue?.items.map(r => r.reference_id) || []
    if (ids.every(id => selected.has(id))) {
      setSelected(prev => { const next = new Set(prev); ids.forEach(id => next.delete(id)); return next })
    } else {
      setSelected(prev => { const next = new Set(prev); ids.forEach(id => next.add(id)); return next })
    }
  }

  const clearFilters = () => {
    setFilterStatus(''); setFilterRisk(''); setFilterImage('')
    setFilterCategory(''); setFilterQ(''); setPage(1)
  }

  const totalPages = queue ? Math.ceil(queue.total / PAGE_SIZE) : 1
  const allOnPageSelected = (queue?.items || []).every(r => selected.has(r.reference_id))

  return (
    <div className="space-y-5">
      {/* Stats Bar */}
      {stats && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Queue Stats</span>
            <button
              onClick={handleSync}
              disabled={syncing}
              className="px-3 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white text-[10px] font-bold uppercase tracking-widest transition-all"
            >
              {syncing ? 'Syncing…' : 'Sync from FastMoss'}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.by_status).map(([status, count]) => (
              <button
                key={status}
                onClick={() => { setFilterStatus(filterStatus === status ? '' : status); setPage(1) }}
                className={`px-2 py-0.5 rounded text-[9px] font-bold cursor-pointer transition-all ${STATUS_BADGE[status] || 'bg-slate-700/40 text-slate-400'} ${filterStatus === status ? 'ring-1 ring-white/20' : ''}`}
              >
                {status}: {count}
              </button>
            ))}
            <span className="px-2 py-0.5 rounded text-[9px] font-bold bg-slate-700/30 text-slate-400">
              Total: {stats.total}
            </span>
          </div>
        </div>
      )}

      {/* Action / Error Messages */}
      {actionMessage && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-xs text-emerald-400">
          {actionMessage}
          <button onClick={() => setActionMessage(null)} className="ml-3 text-slate-500 hover:text-white">✕</button>
        </div>
      )}
      {actionError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
          {actionError}
          <button onClick={() => setActionError(null)} className="ml-3 text-slate-500 hover:text-white">✕</button>
        </div>
      )}

      {/* Filters */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex flex-wrap gap-2 items-end">
          <div>
            <label className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1">Status</label>
            <select
              value={filterStatus}
              onChange={e => { setFilterStatus(e.target.value); setPage(1) }}
              className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1"
            >
              <option value="">All</option>
              {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1">Risk</label>
            <select
              value={filterRisk}
              onChange={e => { setFilterRisk(e.target.value); setPage(1) }}
              className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1"
            >
              <option value="">All</option>
              {(['LOW', 'MEDIUM', 'HIGH', 'UNKNOWN'] as BulkClaimRisk[]).map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1">Image</label>
            <select
              value={filterImage}
              onChange={e => { setFilterImage(e.target.value); setPage(1) }}
              className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1"
            >
              <option value="">All</option>
              {(['IMAGE_PRESENT', 'IMAGE_MISSING'] as BulkImageReadiness[]).map(v => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1">Category</label>
            <input
              type="text"
              value={filterCategory}
              onChange={e => { setFilterCategory(e.target.value); setPage(1) }}
              placeholder="category…"
              className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1 w-28"
            />
          </div>
          <div>
            <label className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1">Search</label>
            <input
              type="text"
              value={filterQ}
              onChange={e => { setFilterQ(e.target.value); setPage(1) }}
              placeholder="product title…"
              className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1 w-36"
            />
          </div>
          <button
            onClick={clearFilters}
            className="px-2 py-1 rounded-lg bg-slate-700/50 text-slate-400 hover:text-white text-[10px] uppercase tracking-widest transition-all"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Bulk Action Bar */}
      {selected.size > 0 && (
        <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/10 px-4 py-3 flex items-center gap-3 flex-wrap">
          <span className="text-xs font-bold text-indigo-300">{selected.size} selected</span>
          <button
            onClick={handleGenerateSelected}
            disabled={loading}
            className="px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white text-[10px] font-bold uppercase tracking-widest transition-all"
          >
            Generate Drafts
          </button>
          <button
            onClick={() => { setApprovePhrase(''); setShowApproveModal(true) }}
            disabled={loading}
            className="px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 text-white text-[10px] font-bold uppercase tracking-widest transition-all"
          >
            Approve Ready
          </button>
          <button
            onClick={handleRejectSelected}
            disabled={loading}
            className="px-3 py-1 rounded-lg bg-red-700/60 hover:bg-red-600/60 disabled:bg-slate-800 text-red-200 text-[10px] font-bold uppercase tracking-widest transition-all"
          >
            Reject Selected
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="ml-auto text-[9px] text-slate-500 hover:text-white uppercase tracking-widest"
          >
            Clear selection
          </button>
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-500 text-xs">Loading…</div>
        ) : !queue || queue.items.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-xs">
            No queue rows found.{' '}
            {!stats?.total ? 'Click "Sync from FastMoss" to load reference rows.' : 'Try adjusting filters.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-slate-300">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-900/80">
                  <th className="px-3 py-2 w-8">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={toggleAll}
                      className="accent-indigo-500"
                    />
                  </th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest w-64">Product</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">Category</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">Risk</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">Image</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">Sold</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">Comm%</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">Status</th>
                  <th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">Draft</th>
                </tr>
              </thead>
              <tbody>
                {queue.items.map(row => (
                  <tr
                    key={row.reference_id}
                    className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
                      selected.has(row.reference_id) ? 'bg-indigo-500/5' : ''
                    }`}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(row.reference_id)}
                        onChange={() => toggleRow(row.reference_id)}
                        className="accent-indigo-500"
                      />
                    </td>
                    <td className="px-3 py-2 w-64">
                      <div className="font-medium text-white truncate max-w-[240px]" title={row.raw_product_title}>
                        {row.raw_product_title}
                      </div>
                      {rowErrors[row.reference_id] && (
                        <div className="text-[9px] text-red-400 truncate max-w-[240px] mt-0.5">
                          {rowErrors[row.reference_id]}
                        </div>
                      )}
                      {row.error_message && !rowErrors[row.reference_id] && (
                        <div className="text-[9px] text-orange-400 truncate max-w-[240px] mt-0.5">
                          {row.error_message}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-400 truncate max-w-[100px]">{row.category || '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${RISK_BADGE[row.claim_risk_level] || 'bg-slate-600/20 text-slate-400'}`}>
                        {row.claim_risk_level}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {row.image_readiness === 'IMAGE_PRESENT' ? (
                        row.image_url ? (
                          <img
                            src={row.image_url}
                            alt=""
                            className="w-8 h-8 rounded object-cover border border-slate-700"
                            onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                          />
                        ) : (
                          <span className="text-[9px] text-emerald-400 font-bold">✓</span>
                        )
                      ) : (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-yellow-500/20 text-yellow-400">MISSING</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-400">{row.sold_count ?? '—'}</td>
                    <td className="px-3 py-2 text-slate-400">{row.commission_rate ?? '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${STATUS_BADGE[row.promotion_status] || 'bg-slate-600/20 text-slate-400'}`}>
                        {row.promotion_status.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {row.draft_id ? (
                        onOpenDraft ? (
                          <button
                            onClick={() => onOpenDraft(row.draft_id!)}
                            className="text-[9px] font-bold text-indigo-400 hover:text-indigo-200 underline underline-offset-2 transition-colors"
                          >
                            {row.draft_id.slice(0, 14)}…
                          </button>
                        ) : (
                          <span className="text-[9px] text-slate-500 font-mono">{row.draft_id.slice(0, 12)}…</span>
                        )
                      ) : (
                        <span className="text-[9px] text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {queue && queue.total > PAGE_SIZE && (
        <div className="flex items-center justify-between px-1">
          <span className="text-[10px] text-slate-500">
            {queue.total} rows — page {page} of {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-2 py-1 rounded-lg bg-slate-800 text-slate-400 hover:text-white disabled:opacity-40 text-[10px] uppercase tracking-widest"
            >
              ‹ Prev
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-2 py-1 rounded-lg bg-slate-800 text-slate-400 hover:text-white disabled:opacity-40 text-[10px] uppercase tracking-widest"
            >
              Next ›
            </button>
          </div>
        </div>
      )}

      {/* Approve Modal */}
      {showApproveModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl w-full max-w-md space-y-5">
            <div>
              <h3 className="text-lg font-bold text-white">Confirm Bulk Approval</h3>
              <p className="text-xs text-slate-400 mt-1">
                This will commit all <strong className="text-white">READY_FOR_APPROVAL</strong> rows from your selection into canonical product truth.
                Non-ready rows will be skipped automatically.
              </p>
            </div>

            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
              <strong>Governance:</strong> Only LOW claim risk, image-present, complete rows will be committed.
              MEDIUM, HIGH, IMAGE_MISSING rows are automatically skipped.
            </div>

            <div>
              <label className="text-[10px] text-slate-400 uppercase tracking-widest block mb-2">
                Type the confirmation phrase exactly:
              </label>
              <div className="text-[10px] font-mono text-indigo-300 bg-slate-800 rounded px-2 py-1 mb-2">
                PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH
              </div>
              <input
                type="text"
                value={approvePhrase}
                onChange={e => setApprovePhrase(e.target.value)}
                placeholder="Type phrase here…"
                autoFocus
                className="w-full bg-slate-800 border border-slate-700 focus:border-indigo-500 rounded-lg text-xs text-white px-3 py-2 outline-none"
              />
              {approvePhrase && approvePhrase !== 'PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH' && (
                <p className="text-[9px] text-red-400 mt-1">Phrase does not match</p>
              )}
            </div>

            <div className="flex gap-3 justify-end">
              <button
                onClick={() => { setShowApproveModal(false); setApprovePhrase('') }}
                className="px-4 py-2 rounded-xl bg-slate-800 text-slate-400 hover:text-white text-xs font-bold uppercase tracking-widest transition-all"
              >
                Cancel
              </button>
              <button
                onClick={handleApproveConfirm}
                disabled={approvePhrase !== 'PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH'}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-bold uppercase tracking-widest transition-all"
              >
                Confirm Promote
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
