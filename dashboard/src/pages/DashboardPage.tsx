import { useEffect, useMemo, useState } from 'react'
import { fetchAPI } from '../api/client'
import { useWebSocketContext } from '../contexts/WebSocketContext'
import type { Project, TelemetryRequest, Video } from '../types'
import PipelineView from '../components/pipeline/PipelineView'
import { buildStandardTraceLabel, getLatestTraceForProject, getLatestTraceForVideo, getTraceElapsedSeconds, getTraceIdleSeconds, getTraceMeta, getTraceStage, getTraceUpdatedAt, isActiveTelemetryStatus, shortId } from '../utils/requestTrace'

interface SelectorOption {
  id: string
  label: string
  meta: string
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
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
        className="w-full px-3 py-2 rounded text-left border transition-opacity disabled:opacity-50"
        style={{ background: 'var(--card)', border: '1px solid var(--border)', color: 'var(--text)' }}
      >
        <div className="truncate text-xs font-semibold">{selected?.label || placeholder}</div>
        <div className="truncate text-[10px] opacity-60">{selected?.meta || 'Searchable, scrollable selector'}</div>
      </button>

      {open && !disabled && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className="absolute z-50 mt-1 w-full rounded border overflow-hidden shadow-2xl"
            style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
          >
            <div className="p-2 border-b" style={{ borderBottomColor: 'var(--border)', background: 'var(--surface)' }}>
              <input
                autoFocus
                value={search}
                onChange={event => setSearch(event.target.value)}
                placeholder="Search by short label, status, request ID, engine..."
                className="w-full p-2 text-xs rounded border outline-none"
                style={{ background: 'var(--card)', border: '1px solid var(--border)', color: 'var(--text)' }}
              />
            </div>
            <div className="overflow-y-auto" style={{ maxHeight: '320px' }}>
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
                  className="w-full p-3 text-left border-b hover:bg-blue-600/10"
                  style={{ borderBottomColor: 'var(--border)' }}
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
  const [projects, setProjects] = useState<Project[]>([])
  const [videos, setVideos] = useState<Video[]>([])
  const [telemetryRequests, setTelemetryRequests] = useState<TelemetryRequest[]>([])
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [selectedVideo, setSelectedVideo] = useState<string>('')
  const { lastEvent } = useWebSocketContext()

  useEffect(() => {
    fetchAPI<Project[]>('/api/projects').then(setProjects).catch(() => {})
  }, [])

  useEffect(() => {
    const loadTelemetry = () => {
      fetchAPI<TelemetryRequest[]>('/api/telemetry/requests?limit=200').then(setTelemetryRequests).catch(() => {})
    }

    loadTelemetry()
    const timer = window.setInterval(loadTelemetry, 4000)
    return () => window.clearInterval(timer)
  }, [])

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
      fetchAPI<TelemetryRequest[]>('/api/telemetry/requests?limit=200').then(setTelemetryRequests).catch(() => {})
    }
  }, [lastEvent])

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

  const activeJobs = useMemo(() => telemetryRequests
    .filter(trace => isActiveTelemetryStatus(trace.status))
    .map(trace => {
      const project = projects.find(item => item.id === trace.project_id) || null
      const video = videos.find(item => item.id === trace.video_id) || null
      const meta = getTraceMeta(project, video)
      return {
        request_id: trace.request_id,
        request_type: trace.request_type || 'UNKNOWN',
        productShortName: meta.productShortName,
        categoryPath: meta.categoryPath,
        engine: meta.engine,
        duration: meta.duration,
        status: trace.status,
        lastStage: getTraceStage(trace),
        lastError: trace.error_message || '',
        elapsedSeconds: getTraceElapsedSeconds(trace),
        idleSeconds: getTraceIdleSeconds(trace),
        createdAt: trace.created_at,
        updatedAt: getTraceUpdatedAt(trace),
      }
    }), [projects, telemetryRequests, videos])

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Selectors */}
      <div className="flex items-start gap-3 flex-wrap">
        <TraceableSelect
          value={selectedProject}
          options={projectOptions}
          placeholder="Select project..."
          onChange={setSelectedProject}
        />

        <TraceableSelect
          value={selectedVideo}
          options={videoOptions}
          placeholder="Select video..."
          disabled={!selectedProject || videos.length === 0}
          onChange={setSelectedVideo}
        />
      </div>

      <div className="rounded-xl border p-4 grid gap-3" style={{ background: 'var(--card)', border: '1px solid var(--border)' }}>
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Current Running Job</h3>
          <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--muted)' }}>
            traceable by request ID
          </span>
        </div>

        {activeJobs.length === 0 ? (
          <div className="text-xs" style={{ color: 'var(--muted)' }}>No active running job.</div>
        ) : activeJobs.map(job => (
          <div key={job.request_id} className="rounded-lg border p-3 grid gap-2" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2 text-xs">
              <div><span className="opacity-50">request_id:</span> <span className="font-mono">{job.request_id}</span></div>
              <div><span className="opacity-50">request_type:</span> <span className="font-semibold">{job.request_type}</span></div>
              <div><span className="opacity-50">product_short_name:</span> <span className="font-semibold">{job.productShortName}</span></div>
              <div><span className="opacity-50">category/subcategory/type:</span> <span>{job.categoryPath}</span></div>
              <div><span className="opacity-50">engine:</span> <span>{job.engine}</span></div>
              <div><span className="opacity-50">duration:</span> <span>{job.duration}</span></div>
              <div><span className="opacity-50">status:</span> <span>{job.status}</span></div>
              <div><span className="opacity-50">last_stage:</span> <span className="font-mono">{job.lastStage}</span></div>
              <div><span className="opacity-50">last_error:</span> <span>{job.lastError || '—'}</span></div>
              <div><span className="opacity-50">elapsed_seconds:</span> <span className="font-mono">{job.elapsedSeconds}</span></div>
              <div><span className="opacity-50">idle_seconds:</span> <span className="font-mono">{job.idleSeconds}</span></div>
              <div><span className="opacity-50">created_at:</span> <span>{formatDateTime(job.createdAt)}</span></div>
              <div><span className="opacity-50">updated_at:</span> <span>{formatDateTime(job.updatedAt)}</span></div>
            </div>
          </div>
        ))}
      </div>

      {/* Pipeline view */}
      {selectedProject && selectedVideo ? (
        <PipelineView projectId={selectedProject} videoId={selectedVideo} />
      ) : (
        <div className="flex items-center justify-center flex-1" style={{ color: 'var(--muted)' }}>
          Select a project and video to view the pipeline
        </div>
      )}
    </div>
  )
}
