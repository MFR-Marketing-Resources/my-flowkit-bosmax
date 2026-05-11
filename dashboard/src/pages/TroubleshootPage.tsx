import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Copy, RefreshCcw } from 'lucide-react'
import { fetchAPI } from '../api/client'
import LogViewer from '../components/logs/LogViewer'
import type { TelemetryRequest, TelemetryRequestDetail } from '../types'
import { formatKualaLumpurDateTime } from '../utils/dateTime'
import {
  getTelemetryModeLabel,
  getTelemetryPrimaryRemark,
  getTelemetryRequestLabel,
  getTelemetryStage,
  getTelemetryStatusLabel,
  getTelemetryStatusTone,
  getTelemetryUpdatedAt,
  sortTelemetryByUpdatedAt,
} from '../utils/telemetryReporting'

function buildIncidentBrief(trace: TelemetryRequest | null, detail: TelemetryRequestDetail | null) {
  if (!trace) return 'No failed incident selected.'

  const timeline = detail?.stages?.length
    ? detail.stages.map(stage => `- ${formatKualaLumpurDateTime(stage.timestamp)} | ${stage.source} | ${stage.stage} | ${stage.status}${stage.message ? ` | ${stage.message}` : ''}`).join('\n')
    : '- No stage history recorded.'

  return [
    'BOSMAX Troubleshoot Brief',
    `Captured: ${formatKualaLumpurDateTime(getTelemetryUpdatedAt(trace))}`,
    `Request ID: ${trace.request_id}`,
    `Project ID: ${trace.project_id || 'N/A'}`,
    `Video ID: ${trace.video_id || 'N/A'}`,
    `Scene ID: ${trace.scene_id || 'N/A'}`,
    `Mode: ${getTelemetryModeLabel(trace)}`,
    `Request Type: ${getTelemetryRequestLabel(trace)}`,
    `Status: ${getTelemetryStatusLabel(trace.status)}`,
    `Current Stage: ${getTelemetryStage(trace)}`,
    `Primary Remark: ${getTelemetryPrimaryRemark(trace, detail)}`,
    '',
    'Stage Timeline:',
    timeline,
  ].join('\n')
}

export default function TroubleshootPage() {
  const [requests, setRequests] = useState<TelemetryRequest[]>([])
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TelemetryRequestDetail | null>(null)
  const [detailError, setDetailError] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const load = () => {
      fetchAPI<TelemetryRequest[]>('/api/telemetry/requests?limit=200')
        .then(setRequests)
        .catch(() => {})
    }

    load()
    const timer = window.setInterval(load, 4000)
    return () => window.clearInterval(timer)
  }, [])

  const incidents = useMemo(() => sortTelemetryByUpdatedAt(
    requests.filter(trace => trace.status === 'FAILED' || Boolean(trace.error_message)),
  ), [requests])

  const summary = useMemo(() => {
    return requests.reduce((acc, trace) => {
      const tone = getTelemetryStatusTone(trace.status)
      if (tone === 'waiting') acc.waiting += 1
      if (tone === 'running') acc.running += 1
      if (tone === 'success') acc.completed += 1
      if (tone === 'failed') acc.failed += 1
      return acc
    }, { waiting: 0, running: 0, completed: 0, failed: 0 })
  }, [requests])

  useEffect(() => {
    if (!selectedRequestId && incidents.length > 0) {
      setSelectedRequestId(incidents[0].request_id)
      return
    }

    if (selectedRequestId && !incidents.some(trace => trace.request_id === selectedRequestId)) {
      setSelectedRequestId(incidents[0]?.request_id || null)
    }
  }, [incidents, selectedRequestId])

  useEffect(() => {
    if (!selectedRequestId) {
      setDetail(null)
      setDetailError('')
      return
    }

    let disposed = false

    fetchAPI<TelemetryRequestDetail>(`/api/telemetry/requests/${selectedRequestId}`)
      .then(payload => {
        if (disposed) return
        setDetail(payload)
        setDetailError('')
      })
      .catch(error => {
        if (disposed) return
        setDetail(null)
        setDetailError(error.message || 'Failed to load incident detail.')
      })

    return () => {
      disposed = true
    }
  }, [selectedRequestId])

  const selectedTrace = incidents.find(trace => trace.request_id === selectedRequestId) || null
  const incidentBrief = useMemo(() => buildIncidentBrief(selectedTrace, detail), [detail, selectedTrace])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(incidentBrief)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="flex h-full flex-col gap-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: 'Pending', value: summary.waiting, tone: 'text-amber-200 border-amber-500/30 bg-amber-500/10' },
          { label: 'Processing', value: summary.running, tone: 'text-blue-200 border-blue-500/30 bg-blue-500/10' },
          { label: 'Success', value: summary.completed, tone: 'text-emerald-200 border-emerald-500/30 bg-emerald-500/10' },
          { label: 'Failed', value: summary.failed, tone: 'text-red-200 border-red-500/30 bg-red-500/10' },
        ].map(card => (
          <div key={card.label} className={`rounded-3xl border px-5 py-4 ${card.tone}`}>
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] opacity-80">{card.label}</div>
            <div className="mt-3 text-3xl font-semibold">{card.value}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.3fr)]">
        <div className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-950/80">
          <div className="border-b border-slate-800 bg-slate-900/70 px-5 py-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-200">Incident Queue</div>
                <p className="mt-1 text-xs text-slate-400">Recent failed jobs and bug-facing incidents. Pick one incident and copy the AI brief on the right.</p>
              </div>
              <div className="rounded-full border border-slate-700 bg-slate-950 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300">
                MYT timestamps
              </div>
            </div>
          </div>

          <div className="divide-y divide-slate-800">
            {incidents.length === 0 ? (
              <div className="px-5 py-6 text-sm text-slate-400">No failed incidents recorded right now.</div>
            ) : incidents.map(trace => (
              <button
                key={trace.request_id}
                type="button"
                onClick={() => setSelectedRequestId(trace.request_id)}
                className={`w-full px-5 py-4 text-left transition ${selectedRequestId === trace.request_id ? 'bg-red-500/10' : 'hover:bg-slate-900/60'}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                      <AlertTriangle size={16} className="text-red-300" />
                      <span className="truncate">{getTelemetryRequestLabel(trace)}</span>
                    </div>
                    <div className="mt-1 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                      {getTelemetryModeLabel(trace)} • {trace.request_id}
                    </div>
                  </div>
                  <span className="rounded-full border border-red-500/40 bg-red-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-red-200">
                    {getTelemetryStatusLabel(trace.status)}
                  </span>
                </div>

                <div className="mt-3 line-clamp-2 text-xs text-slate-300">{getTelemetryPrimaryRemark(trace)}</div>
                <div className="mt-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">{formatKualaLumpurDateTime(getTelemetryUpdatedAt(trace))}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-950/80">
          <div className="border-b border-slate-800 bg-slate-900/70 px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-200">AI Incident Brief</div>
                <p className="mt-1 text-xs text-slate-400">Use this brief when you need to send exact failure context to AI without manually piecing together timestamps, stages, and remarks.</p>
              </div>
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-2 rounded-full border border-slate-700 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200"
              >
                <Copy size={14} /> {copied ? 'Copied' : 'Copy brief'}
              </button>
            </div>
          </div>

          <div className="grid gap-4 px-5 py-5">
            {!selectedTrace ? (
              <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">Select an incident from the queue to build an AI-ready troubleshooting brief.</div>
            ) : (
              <>
                <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-lg font-semibold text-slate-100">{getTelemetryRequestLabel(selectedTrace)}</div>
                      <div className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">{getTelemetryModeLabel(selectedTrace)} • {selectedTrace.request_id}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedRequestId(selectedTrace.request_id)}
                      className="inline-flex items-center gap-2 rounded-full border border-slate-700 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200"
                    >
                      <RefreshCcw size={14} /> Refresh incident
                    </button>
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-200">
                      <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Primary Remark</div>
                      <div className="mt-2">{getTelemetryPrimaryRemark(selectedTrace, detail)}</div>
                    </div>
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-200">
                      <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Last Known Stage</div>
                      <div className="mt-2">{getTelemetryStage(selectedTrace)}</div>
                      <div className="mt-2 text-xs text-slate-500">{formatKualaLumpurDateTime(getTelemetryUpdatedAt(selectedTrace))}</div>
                    </div>
                  </div>
                </div>

                <textarea
                  readOnly
                  title="AI incident brief"
                  value={incidentBrief}
                  className="min-h-[280px] w-full rounded-2xl border border-slate-800 bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-200 outline-none"
                />

                {detailError ? (
                  <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{detailError}</div>
                ) : detail?.stages?.length ? (
                  <div className="grid gap-2">
                    {detail.stages.map(stage => (
                      <div key={stage.id} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-200">{stage.stage}</div>
                            <div className="mt-1 text-[11px] text-slate-500">{stage.source} • {formatKualaLumpurDateTime(stage.timestamp)}</div>
                          </div>
                          <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] ${stage.status === 'FAILED' ? 'border-red-500/40 bg-red-500/10 text-red-200' : 'border-slate-700 bg-slate-950 text-slate-300'}`}>
                            {stage.status}
                          </span>
                        </div>
                        <div className="mt-2 text-xs text-slate-300">{stage.message || 'No stage note recorded.'}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
        <div className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-slate-200">Live Event Trace</div>
        <LogViewer />
      </div>
    </div>
  )
}