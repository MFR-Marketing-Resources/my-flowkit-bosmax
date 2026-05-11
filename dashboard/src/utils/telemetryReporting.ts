import type { TelemetryRequest, TelemetryRequestDetail } from '../types'
import { formatKualaLumpurDateTime } from './dateTime'

const REQUEST_TYPE_LABELS: Record<string, string> = {
  MANUAL_FLOW_JOB: 'Manual Flow Run',
  GENERATE_IMAGE: 'Image Generation',
  REGENERATE_IMAGE: 'Image Regeneration',
  EDIT_IMAGE: 'Image Edit',
  GENERATE_VIDEO: 'Text to Video',
  REGENERATE_VIDEO: 'Video Regeneration',
  GENERATE_VIDEO_REFS: 'Ingredients to Video',
  TRUE_F2V: 'Frames to Video',
  UPSCALE_VIDEO: 'Video Upscale',
  GENERATE_CHARACTER_IMAGE: 'Reference Generation',
  REGENERATE_CHARACTER_IMAGE: 'Reference Regeneration',
  EDIT_CHARACTER_IMAGE: 'Reference Edit',
}

const MODE_LABELS: Record<string, string> = {
  T2V: 'Text to Video',
  F2V: 'Frames to Video',
  I2V: 'Ingredients to Video',
  IMG: 'Image Generation',
  REFS: 'Reference Images',
  UPSCALE: 'Upscale',
  UNKNOWN: 'Unclassified',
}

export type ReportingStatusTone = 'waiting' | 'running' | 'success' | 'failed' | 'neutral'

export function getTelemetryRequestLabel(trace: TelemetryRequest) {
  return REQUEST_TYPE_LABELS[trace.request_type || ''] || trace.request_type || 'Unknown Work'
}

export function getTelemetryMode(trace: TelemetryRequest) {
  if (trace.mode && MODE_LABELS[trace.mode]) return trace.mode
  switch (trace.request_type) {
    case 'MANUAL_FLOW_JOB':
      return trace.mode || 'UNKNOWN'
    case 'TRUE_F2V':
      return 'F2V'
    case 'GENERATE_VIDEO_REFS':
      return 'I2V'
    case 'GENERATE_VIDEO':
    case 'REGENERATE_VIDEO':
      return 'T2V'
    case 'GENERATE_IMAGE':
    case 'REGENERATE_IMAGE':
    case 'EDIT_IMAGE':
      return 'IMG'
    case 'GENERATE_CHARACTER_IMAGE':
    case 'REGENERATE_CHARACTER_IMAGE':
    case 'EDIT_CHARACTER_IMAGE':
      return 'REFS'
    case 'UPSCALE_VIDEO':
      return 'UPSCALE'
    default:
      return 'UNKNOWN'
  }
}

export function getTelemetryModeLabel(trace: TelemetryRequest) {
  const mode = getTelemetryMode(trace)
  return MODE_LABELS[mode] || mode
}

export function getTelemetryStage(trace: TelemetryRequest) {
  return trace.google_flow_stage || trace.extension_stage || trace.worker_stage || 'NO_STAGE'
}

export function getTelemetryPrimaryRemark(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null) {
  if (trace.error_message) return trace.error_message

  const lastMeaningfulStage = detail?.stages
    ?.slice()
    .reverse()
    .find(stage => stage.message && stage.message.trim().length > 0)

  if (lastMeaningfulStage?.message) return lastMeaningfulStage.message

  if (trace.status === 'FAILED') return 'Job failed without a backend remark.'
  if (trace.status === 'COMPLETED') return 'Completed successfully.'
  if (trace.status === 'FLOW_RUNNING') return 'Google Flow is processing the job.'
  if (trace.status === 'WAITING_FLOW') return 'Queued and waiting for the Flow bridge.'
  if (trace.status === 'PROCESSING') return 'Worker is processing this request.'
  if (trace.status === 'QUEUED') return 'Queued and waiting for a worker slot.'
  return 'No remark available yet.'
}

export function getTelemetryStatusTone(status: string | null | undefined): ReportingStatusTone {
  switch (status) {
    case 'QUEUED':
    case 'WAITING_FLOW':
      return 'waiting'
    case 'PROCESSING':
    case 'FLOW_RUNNING':
      return 'running'
    case 'COMPLETED':
      return 'success'
    case 'FAILED':
      return 'failed'
    default:
      return 'neutral'
  }
}

export function getTelemetryStatusLabel(status: string | null | undefined) {
  switch (status) {
    case 'QUEUED':
      return 'Queued'
    case 'WAITING_FLOW':
      return 'Waiting for Flow'
    case 'PROCESSING':
      return 'Processing'
    case 'FLOW_RUNNING':
      return 'Running in Flow'
    case 'COMPLETED':
      return 'Completed'
    case 'FAILED':
      return 'Failed'
    default:
      return status || 'Unknown'
  }
}

export function formatRelativeTime(value: string | null | undefined) {
  if (!value) return 'unknown'
  const diffMs = Date.now() - new Date(value).getTime()
  if (!Number.isFinite(diffMs)) return 'unknown'

  const seconds = Math.max(0, Math.round(diffMs / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

export function formatExactDateTime(value: string | null | undefined) {
  return formatKualaLumpurDateTime(value)
}

export function getTelemetryUpdatedAt(trace: TelemetryRequest) {
  return trace.last_heartbeat_at || trace.completed_at || trace.failed_at || trace.started_at || trace.created_at
}

export function sortTelemetryByUpdatedAt(traces: TelemetryRequest[]) {
  return traces.slice().sort((left, right) => {
    return new Date(getTelemetryUpdatedAt(right)).getTime() - new Date(getTelemetryUpdatedAt(left)).getTime()
  })
}

export function getTelemetrySummaryCounts(traces: TelemetryRequest[]) {
  return traces.reduce((acc, trace) => {
    const tone = getTelemetryStatusTone(trace.status)
    acc.total += 1
    if (tone === 'waiting') acc.waiting += 1
    if (tone === 'running') acc.running += 1
    if (tone === 'success') acc.completed += 1
    if (tone === 'failed') acc.failed += 1
    return acc
  }, { total: 0, waiting: 0, running: 0, completed: 0, failed: 0 })
}