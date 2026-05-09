import type { Project, TelemetryRequest, Video } from '../types'

const ACTIVE_STATUSES = new Set(['QUEUED', 'PROCESSING', 'WAITING_FLOW', 'FLOW_RUNNING'])

function cleanSegment(value: string | null | undefined) {
  return (value || '').trim()
}

export function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : 'none'
}

export function isActiveTelemetryStatus(status: string | null | undefined) {
  return !!status && ACTIVE_STATUSES.has(status)
}

export function getTraceStage(trace?: TelemetryRequest | null) {
  return trace?.google_flow_stage || trace?.extension_stage || trace?.worker_stage || 'IDLE'
}

export function getTraceUpdatedAt(trace?: TelemetryRequest | null) {
  return trace?.last_heartbeat_at || trace?.completed_at || trace?.failed_at || trace?.started_at || trace?.created_at || ''
}

export function getTraceElapsedSeconds(trace?: TelemetryRequest | null) {
  if (!trace) return 0
  if (typeof trace.processing_seconds === 'number') return Math.round(trace.processing_seconds)
  const start = trace.started_at || trace.created_at
  const end = trace.completed_at || trace.failed_at
  if (!start) return 0
  const startMs = new Date(start).getTime()
  const endMs = end ? new Date(end).getTime() : Date.now()
  return Math.max(0, Math.round((endMs - startMs) / 1000))
}

export function getTraceIdleSeconds(trace?: TelemetryRequest | null) {
  if (!trace) return 0
  if (typeof trace.idle_seconds === 'number') return Math.round(trace.idle_seconds)
  if (trace.queued_at && trace.started_at) {
    return Math.max(0, Math.round((new Date(trace.started_at).getTime() - new Date(trace.queued_at).getTime()) / 1000))
  }
  return 0
}

export function getTraceCategoryPath(project?: Project | null) {
  const parts = cleanSegment(project?.description)
    .split('/')
    .map(part => part.trim())
    .filter(Boolean)

  if (parts.length === 0) return 'Unmapped'
  return parts.join('/')
}

export function getTraceMeta(project?: Project | null, video?: Video | null) {
  const nameParts = cleanSegment(project?.name || '')
    .split('|')
    .map(part => part.trim())
    .filter(Boolean)

  const productShortName = nameParts[0] || cleanSegment(video?.title) || 'Unknown Product'
  const engine = nameParts[1] || cleanSegment(video?.description?.split(' ')[0]) || 'UNKNOWN'
  const duration = nameParts[2] || (video?.duration ? `${video.duration}s` : 'n/a')

  return {
    productShortName,
    categoryPath: getTraceCategoryPath(project),
    engine,
    duration,
  }
}

export function buildStandardTraceLabel(project?: Project | null, video?: Video | null, trace?: TelemetryRequest | null) {
  const meta = getTraceMeta(project, video)
  const status = trace?.status || 'NO_STATUS'
  return `${meta.productShortName} | ${meta.categoryPath} | ${meta.engine} | ${meta.duration} | ${status} | ${shortId(trace?.request_id)}`
}

export function getLatestTraceForProject(traces: TelemetryRequest[], projectId: string) {
  return traces.find(trace => trace.project_id === projectId) || null
}

export function getLatestTraceForVideo(traces: TelemetryRequest[], videoId: string) {
  return traces.find(trace => trace.video_id === videoId) || null
}