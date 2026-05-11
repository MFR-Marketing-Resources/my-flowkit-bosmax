import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import F2VModule from '../components/workspace/F2VModule'
import T2VModule from '../components/workspace/T2VModule'
import I2VModule from '../components/workspace/I2VModule'
import IMGModule from '../components/workspace/IMGModule'
import { fetchAPI } from '../api/client'
import RequestReportPanel from '../components/reporting/RequestReportPanel'
import type { TelemetryRequest } from '../types'

type OperatorNoticeTone = 'idle' | 'info' | 'success' | 'error'

interface OperatorTelemetryResponse {
  telemetry: {
    request_id: string
    status: string
    google_flow_stage: string | null
    extension_stage: string | null
    worker_stage: string | null
    error_message: string | null
  }
  stages: Array<{
    id: string
    stage: string
    status: string
    message: string | null
    source: string
    timestamp: string
  }>
}

interface OperatorNotice {
  tone: OperatorNoticeTone
  title: string
  detail: string
  requestId: string | null
}

const ACTIVE_TELEMETRY_STATUSES = new Set(['QUEUED', 'PROCESSING', 'WAITING_FLOW', 'FLOW_RUNNING'])

function getNoticeTone(status: string | null | undefined): OperatorNoticeTone {
  if (!status) return 'info'
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'error'
  return 'info'
}

function getLatestStageLabel(payload: OperatorTelemetryResponse | null) {
  if (!payload) return 'WAITING_FOR_TELEMETRY'
  return payload.telemetry.google_flow_stage
    || payload.telemetry.extension_stage
    || payload.telemetry.worker_stage
    || payload.stages.at(-1)?.stage
    || 'WAITING_FOR_TELEMETRY'
}

interface OperatorPageProps {
  mode?: 'T2V' | 'F2V' | 'I2V' | 'IMG'
}

export default function OperatorPage({ mode: propMode }: OperatorPageProps) {
  const location = useLocation()
  const [isExecuting, setIsExecuting] = useState(false)
  const [modeRequests, setModeRequests] = useState<TelemetryRequest[]>([])
  const [notice, setNotice] = useState<OperatorNotice>({
    tone: 'idle',
    title: 'Idle',
    detail: 'Submit a job to start Google Flow automation.',
    requestId: null,
  })
  const pollTimerRef = useRef<number | null>(null)

  const pathMode = location.pathname.split('/').pop()?.toUpperCase()
  const mode = propMode || (pathMode === 'T2V' || pathMode === 'F2V' || pathMode === 'I2V' || pathMode === 'IMG' ? pathMode : 'F2V')

  useEffect(() => {
    return () => {
      if (pollTimerRef.current != null) {
        window.clearTimeout(pollTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    const loadModeRequests = () => {
      fetchAPI<TelemetryRequest[]>('/api/telemetry/requests?limit=120')
        .then(items => {
          const filtered = items.filter(trace => trace.request_type === 'MANUAL_FLOW_JOB' && trace.mode === mode)
          setModeRequests(filtered)
        })
        .catch(() => {})
    }

    loadModeRequests()
    const timer = window.setInterval(loadModeRequests, 4000)
    return () => window.clearInterval(timer)
  }, [mode])

  const handleExecute = async (data: any) => {
    setIsExecuting(true)
    console.log('Operator executing:', data)
    if (pollTimerRef.current != null) {
      window.clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }

    const requestId = `manual_${crypto.randomUUID().replace(/-/g, '').slice(0, 8)}`
    setNotice({
      tone: 'info',
      title: 'Submitting to Flow',
      detail: 'Bridge request accepted locally. Waiting for telemetry from the extension.',
      requestId,
    })

    const pollTelemetry = async (targetRequestId: string) => {
      try {
        const response = await fetch(`/api/telemetry/requests/${targetRequestId}`)
        if (response.status === 404) {
          pollTimerRef.current = window.setTimeout(() => {
            void pollTelemetry(targetRequestId)
          }, 1200)
          return
        }

        if (!response.ok) {
          throw new Error(`Telemetry HTTP ${response.status}`)
        }

        const payload = await response.json() as OperatorTelemetryResponse
        const stageLabel = getLatestStageLabel(payload)
        const status = payload.telemetry.status
        const errorMessage = payload.telemetry.error_message || payload.stages.at(-1)?.message || null

        setNotice({
          tone: getNoticeTone(status),
          title: status === 'COMPLETED' ? 'Generation started' : status === 'FAILED' ? 'Generation failed' : 'Flow job running',
          detail: errorMessage ? `${stageLabel}: ${errorMessage}` : `Latest stage: ${stageLabel}`,
          requestId: targetRequestId,
        })

        if (status === 'FAILED') {
          setIsExecuting(false)
          return
        }

        if (status === 'COMPLETED' || !ACTIVE_TELEMETRY_STATUSES.has(status)) {
          setIsExecuting(false)
          return
        }

        pollTimerRef.current = window.setTimeout(() => {
          void pollTelemetry(targetRequestId)
        }, 1500)
      } catch (error: any) {
        setNotice({
          tone: 'error',
          title: 'Telemetry unavailable',
          detail: error.message || 'Failed to read live Flow telemetry.',
          requestId: targetRequestId,
        })
        setIsExecuting(false)
      }
    }

    try {
      const response = await fetch('/api/flow/execute-flow-job', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...data, request_id: requestId })
      })
      
      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || 'Execution failed')
      }
      
      const result = await response.json()
      console.log('Execution result:', result)
      setNotice({
        tone: 'info',
        title: 'Flow job accepted',
        detail: 'Automation bridge accepted the request. Tracking stage updates now.',
        requestId,
      })
      void pollTelemetry(requestId)
    } catch (error: any) {
      console.error('Execution error:', error)
      setNotice({
        tone: 'error',
        title: 'Execution error',
        detail: error.message || 'Execution failed.',
        requestId,
      })
      alert(`Execution Error: ${error.message}`)
      setIsExecuting(false)
    }
  }

  const renderModule = () => {
    switch (mode) {
      case 'F2V':
        return <F2VModule onExecute={handleExecute} isExecuting={isExecuting} />
      case 'T2V':
        return <T2VModule onExecute={handleExecute} isExecuting={isExecuting} />
      case 'I2V':
        return <I2VModule onExecute={handleExecute} isExecuting={isExecuting} />
      case 'IMG':
        return <IMGModule onExecute={handleExecute} isExecuting={isExecuting} />
      default:
        return <div className="p-8 text-slate-400">Please select a workspace module from the sidebar.</div>
    }
  }

  return (
    <div className="h-full p-8 flex flex-col bg-slate-950">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white tracking-tight">{mode} Production Workspace</h2>
          <p className="text-slate-400 text-sm italic">Automating Google Flow with BOSMAX V4 precision.</p>
        </div>
        <div className="flex items-center gap-4">
           <div className="px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[10px] font-bold uppercase tracking-widest">
             Mode: {mode === 'F2V' ? 'Frames to Video' : mode}
           </div>
        </div>
      </div>

      <div className={`mb-6 rounded-2xl border px-4 py-3 text-sm ${notice.tone === 'error' ? 'border-red-500/40 bg-red-500/10 text-red-200' : notice.tone === 'success' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' : notice.tone === 'info' ? 'border-blue-500/40 bg-blue-500/10 text-blue-200' : 'border-slate-800 bg-slate-900/40 text-slate-300'}`}>
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="font-semibold tracking-wide">{notice.title}</div>
            <div className="text-xs opacity-90 mt-1">{notice.detail}</div>
          </div>
          <div className="text-[10px] uppercase tracking-[0.2em] opacity-70">
            {notice.requestId ? `req ${notice.requestId}` : 'no active request'}
          </div>
        </div>
      </div>

      <div className="grid flex-1 min-h-0 gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.95fr)]">
        <div className="min-h-0">
          {renderModule()}
        </div>

        <div className="min-h-0">
          <RequestReportPanel
            requests={modeRequests}
            title={`${mode === 'F2V' ? 'Frames' : mode === 'T2V' ? 'Text to Video' : mode === 'I2V' ? 'Ingredients' : 'Image'} Workspace Jobs`}
            description="This is the work list for the current operator page. Use it to confirm whether a run is waiting, processing, completed, or failed, and read the remark before troubleshooting."
            emptyMessage="No jobs recorded for this workspace yet. New submissions from this page will appear here automatically."
            maxItems={18}
          />
        </div>
      </div>
    </div>
  )
}
