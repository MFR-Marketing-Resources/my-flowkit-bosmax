import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { fetchAPI } from '../api/client'
import { useWebSocketContext } from '../contexts/WebSocketContext'
import type { TelemetryRequest } from '../types'
import RequestReportPanel from '../components/reporting/RequestReportPanel'
import { getTelemetryModeLabel, getTelemetrySummaryCounts, sortTelemetryByUpdatedAt } from '../utils/telemetryReporting'

export default function DashboardPage() {
  const location = useLocation()
  const [telemetryRequests, setTelemetryRequests] = useState<TelemetryRequest[]>([])
  const { lastEvent } = useWebSocketContext()
  const isPortalMode = new URLSearchParams(location.search).get('portal') === 'side'

  const loadTelemetry = useCallback(() => {
    fetchAPI<TelemetryRequest[]>('/api/telemetry/requests?limit=200').then(setTelemetryRequests).catch(() => {})
  }, [])

  useEffect(() => {
    loadTelemetry()
    const timer = window.setInterval(loadTelemetry, 4000)
    return () => window.clearInterval(timer)
  }, [loadTelemetry])

  // Refresh the live job feed on any request lifecycle event.
  useEffect(() => {
    if (!lastEvent) return
    if (lastEvent.type === 'project_created' || lastEvent.type === 'request_created' || lastEvent.type === 'request_updated' || lastEvent.type === 'request_completed' || lastEvent.type === 'request_failed') {
      loadTelemetry()
    }
  }, [lastEvent, loadTelemetry])

  const visibleTelemetry = useMemo(() => sortTelemetryByUpdatedAt(
    telemetryRequests.filter(trace => trace.request_type !== 'TELEMETRY_SELF_TEST'),
  ), [telemetryRequests])

  const summary = useMemo(() => getTelemetrySummaryCounts(visibleTelemetry), [visibleTelemetry])

  const modeSummary = useMemo(() => {
    const counts = new Map<string, number>()
    for (const trace of visibleTelemetry) {
      const modeLabel = getTelemetryModeLabel(trace)
      counts.set(modeLabel, (counts.get(modeLabel) || 0) + 1)
    }
    return Array.from(counts.entries()).slice(0, 4)
  }, [visibleTelemetry])

  return (
    <div className="flex flex-col gap-6 h-full">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: 'Waiting', value: summary.waiting, tone: 'text-amber-200 border-amber-500/30 bg-amber-500/10' },
          { label: 'Running', value: summary.running, tone: 'text-blue-200 border-blue-500/30 bg-blue-500/10' },
          { label: 'Completed', value: summary.completed, tone: 'text-emerald-200 border-emerald-500/30 bg-emerald-500/10' },
          { label: 'Failed', value: summary.failed, tone: 'text-red-200 border-red-500/30 bg-red-500/10' },
        ].map(card => (
          <div key={card.label} className={`rounded-3xl border px-5 py-4 ${card.tone}`}>
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] opacity-80">{card.label}</div>
            <div className="mt-3 text-3xl font-semibold">{card.value}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.9fr)]">
        <RequestReportPanel
          requests={visibleTelemetry}
          title="Work Reporting"
          description="This is the main reporting surface for jobs across video, image, ingredients, frames, references, and upscale. Read status, current stage, and failure remark here first."
          emptyMessage="No jobs recorded yet. Submit work from any operator page and it will appear here."
          onRefresh={loadTelemetry}
        />

        <div className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
          <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-200">Reporting Guide</div>
          <div className="mt-4 grid gap-3 text-sm text-slate-300">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">How to Read Status</div>
              <div className="mt-2">Waiting means job is accepted but not yet inside Flow. Running means worker or Google Flow is actively processing. Completed means job finished. Failed means the remark should be your first troubleshooting reference. Exact timestamps in this operations center are shown in Kuala Lumpur time.</div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Most Recent Modes</div>
              <div className="mt-3 grid gap-2">
                {modeSummary.length === 0 ? (
                  <div className="text-slate-400">No mode activity yet.</div>
                ) : modeSummary.map(([modeLabel, count]) => (
                  <div key={modeLabel} className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                    <span>{modeLabel}</span>
                    <span className="font-semibold text-slate-100">{count}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Troubleshoot Desk</div>
                  <div className="mt-2 text-slate-300">Open the dedicated troubleshoot page when you need a copy-ready AI brief for failed jobs, stage history, and live bug-facing event traces.</div>
                </div>
                <Link to={isPortalMode ? '/troubleshoot?portal=side' : '/troubleshoot'} className="rounded-full border border-slate-700 bg-slate-950 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200">
                  Open
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
