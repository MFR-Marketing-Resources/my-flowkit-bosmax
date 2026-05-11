import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { fetchAPI } from '../api/client'
import { useWebSocketContext } from '../contexts/WebSocketContext'
import type { Project, TelemetryRequest, Video } from '../types'
import PipelineView from '../components/pipeline/PipelineView'
import ProjectHistoryPanel from '../components/reporting/ProjectHistoryPanel'
import RequestReportPanel from '../components/reporting/RequestReportPanel'
import { formatKualaLumpurDateTime } from '../utils/dateTime'
import { buildStandardTraceLabel, getLatestTraceForProject, getLatestTraceForVideo, shortId } from '../utils/requestTrace'
import { getTelemetryModeLabel, getTelemetrySummaryCounts, sortTelemetryByUpdatedAt } from '../utils/telemetryReporting'

interface SelectorOption {
  id: string
  label: string
  meta: string
}

function formatDateTime(value: string | null | undefined) {
  return formatKualaLumpurDateTime(value)
}

function TraceableSelect({
  value,
  options,
  placeholder,
  disabled = false,
  onChange,
}: {
  value: string
  options: SelectorOption[]
  placeholder: string
  disabled?: boolean
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    const query = search.toLowerCase().trim()
    if (!query) return options
    return options.filter(option => `${option.label} ${option.meta}`.toLowerCase().includes(query))
  }, [options, search])

  const selected = options.find(option => option.id === value)

  return (
    <div className="relative min-w-[320px] max-w-full">
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen(prev => !prev)}
        className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-left text-slate-100 transition-opacity disabled:opacity-50"
      >
        <div className="truncate text-xs font-semibold">{selected?.label || placeholder}</div>
        <div className="truncate text-[10px] opacity-60">{selected?.meta || 'Searchable, scrollable selector'}</div>
      </button>

      {open && !disabled && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className="absolute z-50 mt-1 w-full overflow-hidden rounded border border-slate-700 bg-slate-950 shadow-2xl"
          >
            <div className="border-b border-slate-700 bg-slate-900 p-2">
              <input
                autoFocus
                value={search}
                onChange={event => setSearch(event.target.value)}
                placeholder="Search by short label, status, request ID, engine..."
                className="w-full rounded border border-slate-700 bg-slate-950 p-2 text-xs text-slate-100 outline-none"
              />
            </div>
            <div className="max-h-80 overflow-y-auto">
              {filtered.length === 0 ? (
                <div className="p-3 text-xs opacity-60">No matching items.</div>
              ) : filtered.map(option => (
                <button
                  type="button"
                  key={option.id}
                  onClick={() => {
                    onChange(option.id)
                    setOpen(false)
                    setSearch('')
                  }}
                  className="w-full border-b border-slate-700 p-3 text-left hover:bg-blue-600/10"
                >
                  <div className="truncate text-xs font-semibold">{option.label}</div>
                  <div className="truncate text-[10px] opacity-60">{option.meta}</div>
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default function DashboardPage() {
  const location = useLocation()
  const [projects, setProjects] = useState<Project[]>([])
  const [videos, setVideos] = useState<Video[]>([])
  const [telemetryRequests, setTelemetryRequests] = useState<TelemetryRequest[]>([])
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [selectedVideo, setSelectedVideo] = useState<string>('')
  const { lastEvent } = useWebSocketContext()
  const isPortalMode = new URLSearchParams(location.search).get('portal') === 'side'

  const loadTelemetry = useCallback(() => {
    fetchAPI<TelemetryRequest[]>('/api/telemetry/requests?limit=200').then(setTelemetryRequests).catch(() => {})
  }, [])

  useEffect(() => {
    fetchAPI<Project[]>('/api/projects').then(setProjects).catch(() => {})
  }, [])

  useEffect(() => {
    loadTelemetry()
    const timer = window.setInterval(loadTelemetry, 4000)
    return () => window.clearInterval(timer)
  }, [loadTelemetry])

  useEffect(() => {
    if (!selectedProject) {
      setVideos([])
      setSelectedVideo('')
      return
    }
    fetchAPI<Video[]>(`/api/videos?project_id=${selectedProject}`)
      .then(v => {
        setVideos(v)
        if (v.length > 0) setSelectedVideo(v[0].id)
        else setSelectedVideo('')
      })
      .catch(() => {})
  }, [selectedProject])

  // Re-fetch projects list on WS events that may add new projects
  useEffect(() => {
    if (!lastEvent) return
    if (lastEvent.type === 'project_created' || lastEvent.type === 'request_created' || lastEvent.type === 'request_updated' || lastEvent.type === 'request_completed' || lastEvent.type === 'request_failed') {
      fetchAPI<Project[]>('/api/projects').then(setProjects).catch(() => {})
      loadTelemetry()
    }
  }, [lastEvent, loadTelemetry])

  const selectedProjectRecord = projects.find(project => project.id === selectedProject) || null

  const projectOptions = useMemo(() => projects.map(project => {
    const trace = getLatestTraceForProject(telemetryRequests, project.id)
    return {
      id: project.id,
      label: buildStandardTraceLabel(project, null, trace),
      meta: `created ${formatDateTime(project.created_at)} | status ${trace?.status || 'NO_STATUS'} | request ${shortId(trace?.request_id)}`,
    }
  }), [projects, telemetryRequests])

  const videoOptions = useMemo(() => videos.map(video => {
    const trace = getLatestTraceForVideo(telemetryRequests, video.id)
    return {
      id: video.id,
      label: buildStandardTraceLabel(selectedProjectRecord, video, trace),
      meta: `created ${formatDateTime(video.created_at)} | status ${trace?.status || video.status || 'NO_STATUS'} | request ${shortId(trace?.request_id)}`,
    }
  }), [videos, telemetryRequests, selectedProjectRecord])

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

      <ProjectHistoryPanel projects={projects} requests={visibleTelemetry} />

      <div className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
        <div className="flex items-start gap-3 flex-wrap">
          <TraceableSelect
            value={selectedProject}
            options={projectOptions}
            placeholder="Select project for pipeline drill-down..."
            onChange={setSelectedProject}
          />

          <TraceableSelect
            value={selectedVideo}
            options={videoOptions}
            placeholder="Select video for pipeline drill-down..."
            disabled={!selectedProject || videos.length === 0}
            onChange={setSelectedVideo}
          />
        </div>

        <div className="mt-5">
          {selectedProject && selectedVideo ? (
            <PipelineView projectId={selectedProject} videoId={selectedVideo} />
          ) : (
            <div className="flex flex-1 items-center justify-center text-slate-400">
              Select a project and video to view the pipeline
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
