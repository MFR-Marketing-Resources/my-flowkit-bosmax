import { useMemo, useState } from 'react'
import type { Project, TelemetryRequest } from '../../types'
import { formatKualaLumpurDateTime } from '../../utils/dateTime'
import {
  getTelemetryMode,
  getTelemetryPrimaryRemark,
  getTelemetryRequestLabel,
  getTelemetryStatusLabel,
  getTelemetryStatusTone,
  getTelemetryUpdatedAt,
  sortTelemetryByUpdatedAt,
  type ReportingStatusTone,
} from '../../utils/telemetryReporting'

type ProjectFilter = 'ALL' | 'WAITING' | 'RUNNING' | 'COMPLETED' | 'FAILED'

function StatusBadge({ tone, label }: { tone: ReportingStatusTone, label: string }) {
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
      {label}
    </span>
  )
}

function filterMatches(tone: ReportingStatusTone, filter: ProjectFilter) {
  if (filter === 'ALL') return true
  if (filter === 'WAITING') return tone === 'waiting'
  if (filter === 'RUNNING') return tone === 'running'
  if (filter === 'COMPLETED') return tone === 'success'
  if (filter === 'FAILED') return tone === 'failed'
  return true
}

interface ProjectHistoryPanelProps {
  projects: Project[]
  requests: TelemetryRequest[]
}

export default function ProjectHistoryPanel({ projects, requests }: ProjectHistoryPanelProps) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<ProjectFilter>('ALL')

  const rows = useMemo(() => {
    const query = search.toLowerCase().trim()

    return projects
      .map(project => {
        const traces = sortTelemetryByUpdatedAt(requests.filter(trace => trace.project_id === project.id))
        const latestTrace = traces[0] || null
        const latestVideoTrace = traces.find(trace => ['T2V', 'F2V', 'I2V', 'UPSCALE'].includes(getTelemetryMode(trace))) || null
        const latestImageTrace = traces.find(trace => ['IMG', 'REFS'].includes(getTelemetryMode(trace))) || null

        const counts = traces.reduce((acc, trace) => {
          const tone = getTelemetryStatusTone(trace.status)
          if (tone === 'waiting') acc.waiting += 1
          if (tone === 'running') acc.running += 1
          if (tone === 'success') acc.completed += 1
          if (tone === 'failed') acc.failed += 1
          return acc
        }, { waiting: 0, running: 0, completed: 0, failed: 0 })

        const tone = latestTrace ? getTelemetryStatusTone(latestTrace.status) : 'neutral'
        const latestRemark = latestTrace ? getTelemetryPrimaryRemark(latestTrace) : 'No telemetry recorded for this project yet.'
        const latestUpdatedAt = latestTrace ? getTelemetryUpdatedAt(latestTrace) : project.updated_at || project.created_at

        return {
          project,
          latestTrace,
          latestVideoTrace,
          latestImageTrace,
          counts,
          tone,
          latestRemark,
          latestUpdatedAt,
        }
      })
      .filter(row => {
        if (!filterMatches(row.tone, filter)) return false
        if (!query) return true

        const haystack = [
          row.project.name,
          row.project.description || '',
          row.latestTrace?.request_id || '',
          row.latestTrace?.error_message || '',
          row.latestVideoTrace?.request_id || '',
          row.latestImageTrace?.request_id || '',
          row.latestRemark,
        ].join(' ').toLowerCase()

        return haystack.includes(query)
      })
      .sort((left, right) => new Date(right.latestUpdatedAt).getTime() - new Date(left.latestUpdatedAt).getTime())
  }, [filter, projects, requests, search])

  return (
    <div className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-950/80">
      <div className="border-b border-slate-800 bg-slate-900/70 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-200">Project History</h3>
            <p className="mt-1 max-w-3xl text-xs text-slate-400">This is the operator-grade project history view. Check execution status, latest video and image work, failure remarks, and execution timestamps in Kuala Lumpur time.</p>
          </div>
          <div className="rounded-full border border-slate-700 bg-slate-950 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300">
            Kuala Lumpur time • MYT
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {(['ALL', 'WAITING', 'RUNNING', 'COMPLETED', 'FAILED'] as ProjectFilter[]).map(option => (
            <button
              key={option}
              type="button"
              onClick={() => setFilter(option)}
              className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${filter === option ? 'border-blue-400/60 bg-blue-500/10 text-blue-200' : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'}`}
            >
              {option}
            </button>
          ))}

          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="Search project, request ID, remark, error..."
            className="w-full rounded-full border border-slate-700 bg-slate-950 px-4 py-2 text-xs text-slate-200 outline-none placeholder:text-slate-500 focus:border-blue-400/50 sm:ml-auto sm:w-auto sm:min-w-[280px]"
          />
        </div>
      </div>

      <div className="grid gap-4 p-5 xl:grid-cols-2">
        {rows.length === 0 ? (
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 px-4 py-6 text-sm text-slate-400">
            No project history matched the current filters.
          </div>
        ) : rows.map(row => (
          <section key={row.project.id} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-lg font-semibold text-slate-100">{row.project.name}</div>
                <div className="mt-1 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                  Project {row.project.id} • created {formatKualaLumpurDateTime(row.project.created_at)}
                </div>
              </div>
              <StatusBadge tone={row.tone} label={row.latestTrace ? getTelemetryStatusLabel(row.latestTrace.status) : row.project.status} />
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 text-xs text-slate-300 md:grid-cols-4">
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Waiting</div>
                <div className="mt-1 text-lg font-semibold text-amber-200">{row.counts.waiting}</div>
              </div>
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Running</div>
                <div className="mt-1 text-lg font-semibold text-blue-200">{row.counts.running}</div>
              </div>
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Completed</div>
                <div className="mt-1 text-lg font-semibold text-emerald-200">{row.counts.completed}</div>
              </div>
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Failed</div>
                <div className="mt-1 text-lg font-semibold text-red-200">{row.counts.failed}</div>
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Latest Video Activity</div>
                {row.latestVideoTrace ? (
                  <>
                    <div className="mt-2 flex items-center gap-2">
                      <StatusBadge tone={getTelemetryStatusTone(row.latestVideoTrace.status)} label={getTelemetryStatusLabel(row.latestVideoTrace.status)} />
                    </div>
                    <div className="mt-2 text-sm font-medium text-slate-100">{getTelemetryRequestLabel(row.latestVideoTrace)}</div>
                    <div className="mt-1 text-xs text-slate-400">{formatKualaLumpurDateTime(getTelemetryUpdatedAt(row.latestVideoTrace))}</div>
                  </>
                ) : (
                  <div className="mt-2 text-xs text-slate-400">No video activity recorded yet.</div>
                )}
              </div>

              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Latest Image Activity</div>
                {row.latestImageTrace ? (
                  <>
                    <div className="mt-2 flex items-center gap-2">
                      <StatusBadge tone={getTelemetryStatusTone(row.latestImageTrace.status)} label={getTelemetryStatusLabel(row.latestImageTrace.status)} />
                    </div>
                    <div className="mt-2 text-sm font-medium text-slate-100">{getTelemetryRequestLabel(row.latestImageTrace)}</div>
                    <div className="mt-1 text-xs text-slate-400">{formatKualaLumpurDateTime(getTelemetryUpdatedAt(row.latestImageTrace))}</div>
                  </>
                ) : (
                  <div className="mt-2 text-xs text-slate-400">No image activity recorded yet.</div>
                )}
              </div>
            </div>

            <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Latest Remark</div>
              <div className="mt-2 text-sm text-slate-200">{row.latestRemark}</div>
              <div className="mt-2 text-[11px] uppercase tracking-[0.16em] text-slate-500">Last updated {formatKualaLumpurDateTime(row.latestUpdatedAt)}</div>
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}