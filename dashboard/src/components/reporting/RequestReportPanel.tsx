import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Clock3, LoaderCircle, RefreshCcw } from 'lucide-react'
import { fetchAPI } from '../../api/client'
import type { TelemetryRequest, TelemetryRequestDetail } from '../../types'
import {
  formatExactDateTime,
  formatRelativeTime,
  getTelemetryModeLabel,
  getTelemetryPrimaryRemark,
  getTelemetryRequestLabel,
  getTelemetryStage,
  getTelemetryStatusLabel,
  getTelemetryStatusTone,
  getTelemetryUpdatedAt,
  sortTelemetryByUpdatedAt,
} from '../../utils/telemetryReporting'

type StatusFilter = 'ALL' | 'WAITING' | 'RUNNING' | 'COMPLETED' | 'FAILED'

function StatusBadge({ status }: { status: string }) {
  const tone = getTelemetryStatusTone(status)
  const palette = tone === 'failed'
    ? 'border-red-500/40 bg-red-500/10 text-red-200'
    : tone === 'success'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
      : tone === 'running'
        ? 'border-blue-500/40 bg-blue-500/10 text-blue-200'
        : tone === 'waiting'
          ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
          : 'border-slate-700 bg-slate-900 text-slate-300'

  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] ${palette}`}>
      {getTelemetryStatusLabel(status)}
    </span>
  )
}

function StatusIcon({ status }: { status: string }) {
  const tone = getTelemetryStatusTone(status)
  if (tone === 'failed') return <AlertTriangle size={16} className="text-red-300" />
  if (tone === 'success') return <CheckCircle2 size={16} className="text-emerald-300" />
  if (tone === 'running') return <LoaderCircle size={16} className="text-blue-300 animate-spin" />
  return <Clock3 size={16} className="text-amber-300" />
}

function matchesStatusFilter(trace: TelemetryRequest, statusFilter: StatusFilter) {
  const tone = getTelemetryStatusTone(trace.status)
  if (statusFilter === 'ALL') return true
  if (statusFilter === 'WAITING') return tone === 'waiting'
  if (statusFilter === 'RUNNING') return tone === 'running'
  if (statusFilter === 'COMPLETED') return tone === 'success'
  if (statusFilter === 'FAILED') return tone === 'failed'
  return true
}

interface RequestReportPanelProps {
  requests: TelemetryRequest[]
  title: string
  description: string
  emptyMessage: string
  maxItems?: number
  showSearch?: boolean
  showStatusFilters?: boolean
  onRefresh?: () => void
}

export default function RequestReportPanel({
  requests,
  title,
  description,
  emptyMessage,
  maxItems,
  showSearch = true,
  showStatusFilters = true,
  onRefresh,
}: RequestReportPanelProps) {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TelemetryRequestDetail | null>(null)
  const [detailError, setDetailError] = useState('')
  const [detailLoading, setDetailLoading] = useState(false)

  const filteredRequests = useMemo(() => {
    const query = search.toLowerCase().trim()
    const sorted = sortTelemetryByUpdatedAt(requests)
    const matched = sorted.filter(trace => {
      if (!matchesStatusFilter(trace, statusFilter)) return false
      if (!query) return true

      const haystack = [
        trace.request_id,
        getTelemetryRequestLabel(trace),
        getTelemetryModeLabel(trace),
        getTelemetryStage(trace),
        trace.error_message || '',
        trace.request_type || '',
        trace.mode || '',
      ].join(' ').toLowerCase()

      return haystack.includes(query)
    })

    return typeof maxItems === 'number' ? matched.slice(0, maxItems) : matched
  }, [maxItems, requests, search, statusFilter])

  useEffect(() => {
    if (!selectedRequestId && filteredRequests.length > 0) {
      setSelectedRequestId(filteredRequests[0].request_id)
      return
    }

    if (selectedRequestId && !filteredRequests.some(trace => trace.request_id === selectedRequestId)) {
      setSelectedRequestId(filteredRequests[0]?.request_id || null)
    }
  }, [filteredRequests, selectedRequestId])

  useEffect(() => {
    if (!selectedRequestId) {
      setDetail(null)
      setDetailError('')
      return
    }

    let disposed = false
    setDetailLoading(true)
    setDetailError('')

    fetchAPI<TelemetryRequestDetail>(`/api/telemetry/requests/${selectedRequestId}`)
      .then(payload => {
        if (disposed) return
        setDetail(payload)
      })
      .catch(error => {
        if (disposed) return
        setDetail(null)
        setDetailError(error.message || 'Failed to load request detail.')
      })
      .finally(() => {
        if (disposed) return
        setDetailLoading(false)
      })

    return () => {
      disposed = true
    }
  }, [selectedRequestId])

  const selectedTrace = filteredRequests.find(trace => trace.request_id === selectedRequestId) || null
  const selectedRemark = selectedTrace ? getTelemetryPrimaryRemark(selectedTrace, detail) : 'Select a job to view detail.'

  return (
    <div className="rounded-3xl border border-slate-800 bg-slate-950/80 overflow-hidden">
      <div className="border-b border-slate-800 px-5 py-4 bg-slate-900/70">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold tracking-[0.18em] uppercase text-slate-200">{title}</h3>
            <p className="mt-1 max-w-2xl text-xs text-slate-400">{description}</p>
          </div>
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              className="inline-flex items-center gap-2 rounded-full border border-slate-700 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200"
            >
              <RefreshCcw size={14} /> Refresh
            </button>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {showStatusFilters && (['ALL', 'WAITING', 'RUNNING', 'COMPLETED', 'FAILED'] as StatusFilter[]).map(filter => (
            <button
              key={filter}
              type="button"
              onClick={() => setStatusFilter(filter)}
              className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${statusFilter === filter ? 'border-blue-400/60 bg-blue-500/10 text-blue-200' : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'}`}
            >
              {filter}
            </button>
          ))}
          {showSearch && (
            <input
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder="Search request ID, mode, stage, error..."
              className="ml-auto min-w-[240px] rounded-full border border-slate-700 bg-slate-950 px-4 py-2 text-xs text-slate-200 outline-none placeholder:text-slate-500 focus:border-blue-400/50"
            />
          )}
        </div>
      </div>

      <div className="grid gap-0 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.95fr)]">
        <div className="min-h-[420px] border-b border-slate-800 xl:border-b-0 xl:border-r">
          {filteredRequests.length === 0 ? (
            <div className="px-5 py-6 text-sm text-slate-400">{emptyMessage}</div>
          ) : (
            <div className="divide-y divide-slate-800">
              {filteredRequests.map(trace => {
                const selected = trace.request_id === selectedRequestId
                return (
                  <button
                    key={trace.request_id}
                    type="button"
                    onClick={() => setSelectedRequestId(trace.request_id)}
                    className={`w-full px-5 py-4 text-left transition ${selected ? 'bg-blue-500/10' : 'bg-transparent hover:bg-slate-900/60'}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                          <StatusIcon status={trace.status} />
                          <span className="truncate">{getTelemetryRequestLabel(trace)}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                          <span>{getTelemetryModeLabel(trace)}</span>
                          <span className="font-mono">{trace.request_id}</span>
                          <span>{formatRelativeTime(getTelemetryUpdatedAt(trace))}</span>
                        </div>
                      </div>
                      <StatusBadge status={trace.status} />
                    </div>

                    <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
                      <div>
                        <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Current Stage</div>
                        <div className="mt-1 text-xs font-medium text-slate-200">{getTelemetryStage(trace)}</div>
                      </div>
                      <div>
                        <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Remark</div>
                        <div className="mt-1 line-clamp-2 text-xs text-slate-300">{getTelemetryPrimaryRemark(trace)}</div>
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        <div className="min-h-[420px] bg-slate-950/60 px-5 py-5">
          {!selectedTrace ? (
            <div className="text-sm text-slate-400">Select a job to inspect its status timeline and troubleshooting remark.</div>
          ) : (
            <div className="grid gap-4">
              <div>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Selected Job</div>
                    <div className="mt-2 text-lg font-semibold text-slate-100">{getTelemetryRequestLabel(selectedTrace)}</div>
                    <div className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">{getTelemetryModeLabel(selectedTrace)} • {selectedTrace.request_id}</div>
                  </div>
                  <StatusBadge status={selectedTrace.status} />
                </div>
              </div>

              <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
                <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Operator Remark</div>
                <div className="mt-2 text-sm text-slate-200">{selectedRemark}</div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs text-slate-300">
                <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Last Update</div>
                  <div className="mt-1 font-medium">{formatExactDateTime(getTelemetryUpdatedAt(selectedTrace))}</div>
                </div>
                <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Created</div>
                  <div className="mt-1 font-medium">{formatExactDateTime(selectedTrace.created_at)}</div>
                </div>
                <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Started</div>
                  <div className="mt-1 font-medium">{formatExactDateTime(selectedTrace.started_at)}</div>
                </div>
                <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Ended</div>
                  <div className="mt-1 font-medium">{formatExactDateTime(selectedTrace.completed_at || selectedTrace.failed_at)}</div>
                </div>
              </div>

              <div>
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Stage Timeline</div>
                {detailLoading ? (
                  <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">Loading stage detail...</div>
                ) : detailError ? (
                  <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{detailError}</div>
                ) : detail?.stages?.length ? (
                  <div className="grid gap-2">
                    {detail.stages.map(stage => (
                      <div key={stage.id} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-200">{stage.stage}</div>
                            <div className="mt-1 text-[11px] text-slate-500">{stage.source} • {formatExactDateTime(stage.timestamp)}</div>
                          </div>
                          <StatusBadge status={stage.status} />
                        </div>
                        <div className="mt-2 text-xs text-slate-300">{stage.message || 'No remark for this stage.'}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">No stage timeline recorded for this request yet.</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}