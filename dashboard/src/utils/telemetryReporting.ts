import type { TelemetryRequest, TelemetryRequestDetail, TelemetryStageEvent } from '../types'
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

export type TelemetryExecutionState = 'done' | 'current' | 'failed' | 'pending'

export interface TelemetryExecutionDiagnosis {
  code: string
  label: string
  tone: ReportingStatusTone
  summary: string
  detail: string
}

export interface TelemetryExecutionCheckpoint {
  id: string
  label: string
  state: TelemetryExecutionState
  timestamp: string | null
  detail: string
}

const UI_VALIDATION_TOKENS = [
  'JOB_PROMPT_EMPTY',
  'VALIDATION_FAILED',
]

const EXTENSION_BRIDGE_TOKENS = [
  'ERR_MESSAGE_RESPONSE_TIMEOUT',
  'ERR_NO_RECEIVER',
  'ERR_CONTENT_SCRIPT_STALE',
  'ERR_TAB_RELOADED',
  'MESSAGE_SEND_FAILED',
  'MESSAGE PORT CLOSED',
  'PORT CLOSED',
  'NO_FLOW_TAB',
  'FLOW DOM PING FAILED',
]

const CONTENT_DOM_TOKENS = [
  'FLOW_MODE_MISMATCH',
  'PROMPT_FIELD_NOT_FOUND',
  'PROMPT_INSERT_FAILED',
  'PROMPT_INSERT_LOCKED_OR_UNTRUSTED',
  'GENERATE_ARROW_NOT_FOUND',
  'GENERATE_ARROW_DISABLED_AFTER_PROMPT',
  'START_FRAME_UPLOAD_FAILED',
  'END_FRAME_UPLOAD_FAILED',
  'INGREDIENTS_UPLOAD_FAILED',
  'IMAGE_UPLOAD_FAILED',
  '_UPLOAD_FAILED',
  'ASSET_PREVIEW_NOT_VISIBLE',
  'CAPTCHA_FAILED',
]

const BACKEND_API_TOKENS = [
  'API_REQUEST_FAILED',
  'TRPC_FETCH_FAILED',
  'API_',
  'HTTP ',
  'HTTP_',
  '404',
  '500',
]

function secondsSince(value: string | null | undefined) {
  if (!value) return Number.POSITIVE_INFINITY
  const diffMs = Date.now() - new Date(value).getTime()
  if (!Number.isFinite(diffMs)) return Number.POSITIVE_INFINITY
  return Math.max(0, Math.round(diffMs / 1000))
}

function collectTelemetryTokens(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null) {
  return [
    trace.request_id,
    trace.request_type || '',
    trace.mode || '',
    trace.status || '',
    trace.google_flow_stage || '',
    trace.extension_stage || '',
    trace.worker_stage || '',
    trace.error_code || '',
    trace.error_message || '',
    ...(detail?.stages || []).flatMap(stage => [stage.stage, stage.status, stage.message || '', stage.source]),
  ].join(' ').toUpperCase()
}

function includesAnyToken(haystack: string, tokens: string[]) {
  return tokens.some(token => haystack.includes(token))
}

function findFirstStage(stages: TelemetryStageEvent[] | undefined, predicate: (stage: TelemetryStageEvent) => boolean) {
  return stages?.find(predicate) || null
}

function hasGenerationSignal(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null) {
  if (trace.status === 'FLOW_RUNNING') return true
  if (trace.google_flow_stage === 'GENERATION_STARTED') return true

  return Boolean(findFirstStage(detail?.stages, stage => (
    stage.stage === 'GENERATION_STARTED'
    || stage.stage === 'VIDEO_JOB_RUNNING_OR_GENERATED'
    || stage.stage === 'GENERATE_CLICKED'
    || stage.stage === 'FLOW_JOB_COMPLETED'
  )))
}

function hasExtensionSignal(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null) {
  if (trace.extension_stage) return true

  return Boolean(findFirstStage(detail?.stages, stage => (
    stage.source === 'extension'
    || stage.stage === 'FLOW_MODE_SELECTED'
    || stage.stage === 'FLOW_MODE_VERIFIED'
    || stage.stage === 'PROMPT_VISIBLE'
  )))
}

function hasWorkerSignal(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null) {
  if (trace.worker_stage || trace.started_at) return true
  return Boolean(findFirstStage(detail?.stages, stage => stage.source === 'worker' || stage.stage.startsWith('WORKER_')))
}

function getFailureStepCode(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null) {
  const diagnosis = classifyTelemetryExecution(trace, detail)
  switch (diagnosis.code) {
    case 'ui_validation':
    case 'backend_api':
      return 'backend_accepted'
    case 'worker':
    case 'stuck_worker':
      return 'worker_picked_up'
    case 'extension_messaging':
      return 'extension_bridge'
    case 'content_dom':
    case 'google_flow':
    case 'stuck_flow':
      return 'flow_execution'
    default:
      return 'outcome_recorded'
  }
}

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

export function getTelemetryCurrentOwner(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null) {
  if (trace.status === 'COMPLETED') return 'Result recorded in backend'
  if (trace.status === 'FAILED') {
    const latestStage = detail?.stages?.[detail.stages.length - 1]
    if (latestStage?.source === 'worker') return 'Worker controller'
    if (latestStage?.source === 'extension') return 'Extension content bridge'
    return 'Backend telemetry'
  }
  if (hasGenerationSignal(trace, detail)) return 'Google Flow runtime'
  if (hasExtensionSignal(trace, detail)) return 'Extension content bridge'
  if (hasWorkerSignal(trace, detail)) return 'Worker controller'
  return 'Backend intake'
}

export function getTelemetryStuckRemark(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null) {
  if (trace.status === 'COMPLETED' || trace.status === 'FAILED') return null

  const tone = getTelemetryStatusTone(trace.status)
  const idleSeconds = trace.idle_seconds ?? secondsSince(getTelemetryUpdatedAt(trace))
  const workerSeen = hasWorkerSignal(trace, detail)
  const extensionSeen = hasExtensionSignal(trace, detail)
  const generationSeen = hasGenerationSignal(trace, detail)

  if (generationSeen && idleSeconds >= 90) {
    return `Generation started but no completion callback arrived for ${idleSeconds}s.`
  }

  if (workerSeen && !extensionSeen && idleSeconds >= 60) {
    return `Worker picked up the request but no extension bridge stage was recorded for ${idleSeconds}s.`
  }

  if (extensionSeen && !generationSeen && idleSeconds >= 60) {
    return `Extension/content DOM started but did not reach generation start for ${idleSeconds}s.`
  }

  if (tone === 'waiting' && idleSeconds >= 60) {
    return `Request has been waiting for ${idleSeconds}s without a new stage.`
  }

  if (tone === 'running' && idleSeconds >= 90) {
    return `Request has been running for ${idleSeconds}s with no stage movement.`
  }

  return null
}

export function classifyTelemetryExecution(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null): TelemetryExecutionDiagnosis {
  const tone = getTelemetryStatusTone(trace.status)
  const tokens = collectTelemetryTokens(trace, detail)
  const stuckRemark = getTelemetryStuckRemark(trace, detail)
  const generationSeen = hasGenerationSignal(trace, detail)
  const extensionSeen = hasExtensionSignal(trace, detail)
  const workerSeen = hasWorkerSignal(trace, detail)

  if (trace.status === 'COMPLETED') {
    return {
      code: 'completed',
      label: 'Completed',
      tone: 'success',
      summary: 'The request reached a final completed state.',
      detail: 'Backend telemetry recorded a completed outcome for this request.',
    }
  }

  if (stuckRemark) {
    return {
      code: generationSeen ? 'stuck_flow' : 'stuck_worker',
      label: 'Stuck / Silent',
      tone: 'failed',
      summary: stuckRemark,
      detail: generationSeen
        ? 'Flow generation appears to have started, but the system did not receive a final callback.'
        : 'The request is alive in telemetry but handoff movement stopped before a reliable outcome was recorded.',
    }
  }

  if (includesAnyToken(tokens, UI_VALIDATION_TOKENS)) {
    return {
      code: 'ui_validation',
      label: 'UI Validation',
      tone: 'failed',
      summary: 'The request payload failed a required prompt or input validation step.',
      detail: 'The UI or intake layer did not provide enough valid data for DOM execution to continue.',
    }
  }

  if (includesAnyToken(tokens, EXTENSION_BRIDGE_TOKENS)) {
    return {
      code: 'extension_messaging',
      label: 'Extension Messaging',
      tone: 'failed',
      summary: 'The request failed while background and content-script messaging were handing off the job.',
      detail: 'The browser extension bridge did not maintain a stable message path to the Flow DOM executor.',
    }
  }

  if (includesAnyToken(tokens, BACKEND_API_TOKENS) && !extensionSeen) {
    return {
      code: 'backend_api',
      label: 'Backend API',
      tone: 'failed',
      summary: 'The request failed during backend or API intake before Flow execution progressed.',
      detail: 'The telemetry shows an API or backend failure signature before extension/Flow stage progression became visible.',
    }
  }

  if (includesAnyToken(tokens, CONTENT_DOM_TOKENS)) {
    return {
      code: 'content_dom',
      label: 'Content DOM Action',
      tone: 'failed',
      summary: 'The Flow page was reached, but DOM interaction failed during mode, asset, prompt, or generate-button execution.',
      detail: 'This usually means the extension touched the Flow page but could not complete the required DOM action reliably.',
    }
  }

  if (tokens.includes('WORKER_FAILED') || (trace.worker_stage || '').startsWith('WORKER_') && trace.status === 'FAILED') {
    return {
      code: 'worker',
      label: 'Worker',
      tone: 'failed',
      summary: 'The worker controller accepted the job but recorded a failed backend execution outcome.',
      detail: 'The failure occurred after queue intake, inside worker dispatch, retry, or result handling.',
    }
  }

  if (generationSeen || trace.status === 'FLOW_RUNNING') {
    return {
      code: 'google_flow',
      label: 'Google Flow',
      tone: tone === 'running' ? 'running' : 'failed',
      summary: trace.status === 'FAILED'
        ? 'The request reached Flow execution, but the final result from Flow was unsuccessful.'
        : 'The request is inside Flow execution right now.',
      detail: 'Flow-side generation signals were recorded, so the handoff beyond DOM interaction has already happened.',
    }
  }

  if (workerSeen) {
    return {
      code: 'worker_active',
      label: 'Worker Active',
      tone: 'running',
      summary: 'The worker has picked up the request and is advancing toward the extension/Flow bridge.',
      detail: 'Queue intake is finished; the next evidence should come from extension bridge stages or Flow execution stages.',
    }
  }

  if (tone === 'waiting') {
    return {
      code: 'queued',
      label: 'Queued',
      tone: 'waiting',
      summary: 'The request has a receipt in telemetry and is waiting for the next handoff.',
      detail: 'Queue acceptance is recorded, but the request has not yet produced enough worker or extension evidence.',
    }
  }

  return {
    code: 'intake',
    label: 'Backend Intake',
    tone: 'neutral',
    summary: 'Telemetry receipt exists, but the request has not produced enough downstream evidence yet.',
    detail: 'Use the handoff trail below to see the first missing transition.',
  }
}

export function buildTelemetryHandoffTimeline(trace: TelemetryRequest, detail?: TelemetryRequestDetail | null): TelemetryExecutionCheckpoint[] {
  const failureStep = trace.status === 'FAILED' ? getFailureStepCode(trace, detail) : null
  const workerStarted = findFirstStage(detail?.stages, stage => stage.source === 'worker' || stage.stage === 'WORKER_STARTED')
  const extensionStarted = findFirstStage(detail?.stages, stage => stage.source === 'extension' || stage.stage === 'FLOW_MODE_SELECTED' || stage.stage === 'FLOW_MODE_VERIFIED')
  const generationStarted = findFirstStage(detail?.stages, stage => stage.stage === 'GENERATION_STARTED' || stage.stage === 'VIDEO_JOB_RUNNING_OR_GENERATED' || stage.stage === 'GENERATE_CLICKED')
  const finalStage = detail?.stages?.[detail.stages.length - 1] || null

  const checkpoints: TelemetryExecutionCheckpoint[] = [
    {
      id: 'submission_receipt',
      label: 'Submission Receipt',
      state: 'done',
      timestamp: trace.created_at,
      detail: 'The backend created a durable telemetry receipt for this request.',
    },
    {
      id: 'backend_accepted',
      label: 'Backend Accepted',
      state: failureStep === 'backend_accepted' ? 'failed' : 'done',
      timestamp: trace.queued_at || trace.created_at,
      detail: 'Queue metadata and request identifiers are stored in backend telemetry.',
    },
    {
      id: 'worker_picked_up',
      label: 'Worker Picked Up',
      state: workerStarted
        ? 'done'
        : failureStep === 'worker_picked_up'
          ? 'failed'
          : getTelemetryStatusTone(trace.status) === 'waiting'
            ? 'pending'
            : 'current',
      timestamp: workerStarted?.timestamp || trace.started_at,
      detail: workerStarted
        ? 'The worker controller accepted the request for processing.'
        : 'Waiting for a worker slot or first worker heartbeat.',
    },
    {
      id: 'extension_bridge',
      label: 'Extension Bridge',
      state: extensionStarted
        ? 'done'
        : failureStep === 'extension_bridge'
          ? 'failed'
          : workerStarted
            ? 'current'
            : 'pending',
      timestamp: extensionStarted?.timestamp || null,
      detail: extensionStarted
        ? 'The browser extension reached the Flow page and emitted bridge stages.'
        : 'Waiting for extension/background/content-script handoff evidence.',
    },
    {
      id: 'flow_execution',
      label: 'Flow Execution',
      state: generationStarted
        ? trace.status === 'COMPLETED' || trace.status === 'FAILED'
          ? 'done'
          : 'current'
        : failureStep === 'flow_execution'
          ? 'failed'
          : extensionStarted
            ? 'current'
            : 'pending',
      timestamp: generationStarted?.timestamp || null,
      detail: generationStarted
        ? 'Generate was triggered and Flow-side progression was observed.'
        : 'Waiting for generation start or Flow runtime evidence.',
    },
    {
      id: 'outcome_recorded',
      label: 'Outcome Recorded',
      state: trace.status === 'COMPLETED'
        ? 'done'
        : trace.status === 'FAILED'
          ? 'failed'
          : 'current',
      timestamp: trace.completed_at || trace.failed_at || finalStage?.timestamp || null,
      detail: trace.status === 'COMPLETED'
        ? 'Backend telemetry finalized this request as completed.'
        : trace.status === 'FAILED'
          ? 'Backend telemetry finalized this request as failed.'
          : 'The system is still waiting for a final outcome callback.',
    },
  ]

  return checkpoints
}