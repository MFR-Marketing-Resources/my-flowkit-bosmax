import { useState, useEffect, useCallback } from 'react'
import { Image, Film, Zap, Users } from 'lucide-react'
import { fetchAPI } from '../../api/client'
import { useWebSocketContext } from '../../contexts/WebSocketContext'
import type { Character, Scene, TelemetryRequest } from '../../types'
import StageNode from './StageNode'
import SceneCard from './SceneCard'
import { getTraceStage, isActiveTelemetryStatus, shortId } from '../../utils/requestTrace'

type ExpandedStage = 'refs' | 'image' | 'video' | 'upscale' | null

interface PipelineViewProps {
  projectId: string
  videoId: string
}

function deriveStatus(completed: number, total: number, hasFailure: boolean) {
  if (total === 0) return 'pending' as const
  if (hasFailure) return 'failed' as const
  if (completed === total) return 'completed' as const
  if (completed > 0) return 'processing' as const
  return 'pending' as const
}

export default function PipelineView({ projectId, videoId }: PipelineViewProps) {
  const [chars, setChars] = useState<Character[]>([])
  const [scenes, setScenes] = useState<Scene[]>([])
  const [telemetryRequests, setTelemetryRequests] = useState<TelemetryRequest[]>([])
  const [expanded, setExpanded] = useState<ExpandedStage>(null)
  const { lastEvent } = useWebSocketContext()

  const load = useCallback(async () => {
    const [c, s, t] = await Promise.all([
      fetchAPI<Character[]>(`/api/projects/${projectId}/characters`),
      fetchAPI<Scene[]>(`/api/scenes?video_id=${videoId}`),
      fetchAPI<TelemetryRequest[]>(`/api/telemetry/requests?video_id=${videoId}&limit=100`),
    ])
    setChars(c)
    setScenes(s)
    setTelemetryRequests(t)
  }, [projectId, videoId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!lastEvent) return
    const t = lastEvent.type
    if (t === 'scene_updated' || t === 'character_updated' || t === 'request_completed' || t === 'request_failed' || t === 'request_created' || t === 'request_updated') {
      load()
    }
  }, [lastEvent, load])

  const activeTelemetry = telemetryRequests.filter(trace => isActiveTelemetryStatus(trace.status))

  const findStageTrace = (types: string[]) => activeTelemetry.find(trace => types.includes(trace.request_type || '')) || null

  const stageTrace = {
    refs: findStageTrace(['GENERATE_CHARACTER_IMAGE', 'REGENERATE_CHARACTER_IMAGE', 'EDIT_CHARACTER_IMAGE']),
    image: findStageTrace(['GENERATE_IMAGE', 'REGENERATE_IMAGE', 'EDIT_IMAGE']),
    video: findStageTrace(['GENERATE_VIDEO', 'REGENERATE_VIDEO', 'GENERATE_VIDEO_REFS', 'TRUE_F2V']),
    upscale: findStageTrace(['UPSCALE_VIDEO']),
  }

  // Helpers — pick whichever orientation has data
  const imgStatus = (s: Scene) =>
    s.vertical_image_status !== 'PENDING' ? s.vertical_image_status : s.horizontal_image_status
  const vidStatus = (s: Scene) =>
    s.vertical_video_status !== 'PENDING' ? s.vertical_video_status : s.horizontal_video_status
  const upsStatus = (s: Scene) =>
    s.vertical_upscale_status !== 'PENDING' ? s.vertical_upscale_status : s.horizontal_upscale_status

  // Stats
  const refsCompleted = chars.filter(c => c.media_id).length
  const refsTotal = chars.length

  const imagesCompleted = scenes.filter(s => imgStatus(s) === 'COMPLETED').length
  const imagesFailed = scenes.some(s => imgStatus(s) === 'FAILED')

  const videosCompleted = scenes.filter(s => vidStatus(s) === 'COMPLETED').length
  const videosFailed = scenes.some(s => vidStatus(s) === 'FAILED')

  const upscaleCompleted = scenes.filter(s => upsStatus(s) === 'COMPLETED').length
  const upscaleFailed = scenes.some(s => upsStatus(s) === 'FAILED')

  const total = scenes.length

  const stages = [
    {
      key: 'refs' as const,
      name: 'Refs',
      icon: Users,
      completed: refsCompleted,
      total: refsTotal,
      status: deriveStatus(refsCompleted, refsTotal, false),
      activeRequestId: stageTrace.refs ? shortId(stageTrace.refs.request_id) : null,
      lastStage: getTraceStage(stageTrace.refs),
    },
    {
      key: 'image' as const,
      name: 'Images',
      icon: Image,
      completed: imagesCompleted,
      total,
      status: deriveStatus(imagesCompleted, total, imagesFailed),
      activeRequestId: stageTrace.image ? shortId(stageTrace.image.request_id) : null,
      lastStage: getTraceStage(stageTrace.image),
    },
    {
      key: 'video' as const,
      name: 'Videos',
      icon: Film,
      completed: videosCompleted,
      total,
      status: deriveStatus(videosCompleted, total, videosFailed),
      activeRequestId: stageTrace.video ? shortId(stageTrace.video.request_id) : null,
      lastStage: getTraceStage(stageTrace.video),
    },
    {
      key: 'upscale' as const,
      name: 'Upscale',
      icon: Zap,
      completed: upscaleCompleted,
      total,
      status: deriveStatus(upscaleCompleted, total, upscaleFailed),
      activeRequestId: stageTrace.upscale ? shortId(stageTrace.upscale.request_id) : null,
      lastStage: getTraceStage(stageTrace.upscale),
    },
  ]

  const toggle = (key: ExpandedStage) => setExpanded(prev => prev === key ? null : key)

  return (
    <div className="flex flex-col gap-4">
      {/* Stage nodes row */}
      <div className="flex items-stretch gap-2">
        {stages.map((stage, i) => (
          <div key={stage.key} className="flex items-center gap-2 flex-1 min-w-0">
            <StageNode
              name={stage.name}
              icon={stage.icon}
              completed={stage.completed}
              total={stage.total}
              status={stage.status}
              activeRequestId={stage.activeRequestId}
              lastStage={stage.lastStage}
              isExpanded={expanded === stage.key}
              onClick={() => toggle(stage.key)}
            />
            {i < stages.length - 1 && (
              <span className="flex-shrink-0 text-sm" style={{ color: 'var(--muted)' }}>→</span>
            )}
          </div>
        ))}
      </div>

      {/* Expanded scene grid */}
      {expanded && expanded !== 'refs' && scenes.length > 0 && (
        <div>
          <div className="text-xs mb-2 font-semibold uppercase tracking-wider" style={{ color: 'var(--muted)' }}>
            {expanded} — {scenes.length} scenes
          </div>
          <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))' }}>
            {scenes.map(scene => (
              <SceneCard key={scene.id} scene={scene} stage={expanded as 'image' | 'video' | 'upscale'} />
            ))}
          </div>
        </div>
      )}

      {/* Expanded refs grid */}
      {expanded === 'refs' && chars.length > 0 && (
        <div>
          <div className="text-xs mb-2 font-semibold uppercase tracking-wider" style={{ color: 'var(--muted)' }}>
            refs — {chars.length} entities
          </div>
          <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))' }}>
            {chars.map(c => (
              <div
                key={c.id}
                className="flex flex-col gap-1.5 p-2 rounded text-xs"
                style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
              >
                <div
                  className="w-full rounded overflow-hidden flex items-center justify-center"
                  style={{ aspectRatio: '3/4', background: 'var(--surface)', maxHeight: '80px' }}
                >
                  {c.reference_image_url ? (
                    <img src={c.reference_image_url} alt={c.name} className="w-full h-full object-cover" />
                  ) : (
                    <span style={{ color: 'var(--muted)', fontSize: '10px' }}>No image</span>
                  )}
                </div>
                <div className="font-semibold truncate" style={{ color: 'var(--text)' }}>{c.name}</div>
                <div style={{ color: 'var(--muted)', fontSize: '10px' }}>{c.entity_type}</div>
                <div style={{ color: c.media_id ? 'var(--green)' : 'var(--muted)', fontSize: '10px' }}>
                  {c.media_id ? 'Ready' : 'Pending'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
