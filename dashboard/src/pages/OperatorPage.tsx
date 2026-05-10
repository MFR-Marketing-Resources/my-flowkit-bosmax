import { useEffect, useState, type ReactNode } from 'react'
import { fetchAPI, patchAPI, postAPI } from '../api/client'
import type {
  BatchStatus,
  BlueprintResponse,
  Character,
  ContentPackSummary,
  FlowReadinessSmokeResult,
  ReloadFlowTabResult,
  Orientation,
  OperatorProduct,
  OperatorPreflightResponse,
  Project,
  ProductMapping,
  Scene,
  Video,
  CreatedState,
  UploadedAsset,
  ManualEntityType,
  Product,
  Request,
  LocalAgentStatus,
  TelemetrySummary,
} from '../types'
import { useWebSocketContext } from '../contexts/WebSocketContext'
import OperatorManual from '../components/operator/OperatorManual'


function TelemetryDashboard({ summary }: { summary: TelemetrySummary | null }) {
  if (!summary) return null

  const items = [
    { label: 'Today', value: summary.total_today, color: 'var(--text)' },
    { label: 'Queued', value: summary.queued, color: 'var(--muted)' },
    { label: 'Processing', value: summary.processing, color: 'var(--blue)' },
    { label: 'Waiting Flow', value: summary.waiting_flow, color: 'var(--accent)' },
    { label: 'Flow Running', value: summary.flow_running, color: 'var(--yellow)' },
    { label: 'Success', value: summary.completed, color: 'var(--green)' },
    { label: 'Failed', value: summary.failed, color: 'var(--red)' },
  ]

  return (
    <Card className="mb-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-widest" style={{ color: 'var(--muted)' }}>System Telemetry (Real-time)</h3>
        {summary.last_job_status && (
          <div className="flex items-center gap-2">
            <span className="text-[10px] opacity-60">Last Job:</span>
            <span className={`text-[10px] font-bold ${summary.last_job_status === 'COMPLETED' ? 'text-green-400' : 'text-red-400'}`}>
              {summary.last_job_status}
            </span>
          </div>
        )}
      </div>
      
      <div className="grid grid-cols-4 sm:grid-cols-7 gap-2">
        {items.map(item => (
          <div key={item.label} className="p-2 rounded border flex flex-col items-center justify-center bg-black/20" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
            <div className="text-lg font-bold" style={{ color: item.color }}>{item.value}</div>
            <div className="text-[9px] uppercase tracking-tighter opacity-60">{item.label}</div>
          </div>
        ))}
      </div>

      {(summary.last_stage || summary.last_error) && (
        <div className="mt-2 p-2 rounded bg-black/30 border border-white/5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 truncate">
            <span className="text-[9px] font-bold text-accent uppercase">Live Stage:</span>
            <span className="text-[10px] font-mono truncate">{summary.last_stage || 'IDLE'}</span>
          </div>
          {summary.last_error && (
            <div className="flex items-center gap-2 truncate max-w-[50%]">
              <span className="text-[9px] font-bold text-red-500 uppercase">Alert:</span>
              <span className="text-[10px] text-red-400 italic truncate">{summary.last_error}</span>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

type OperatorForm = {
  product_name: string
  category: string
  sub_category: string
  type_angle: string
  product_type: string
  target_language: string
  duration_target: string
  engine_id: string
  avatar_id: string
  headwear_style: string
  camera_style: string
  scene_context: string
  trigger_id: string
  silo_id: string
  submode_formula: string
  hook: string
  usp_1: string
  usp_2: string
  usp_3: string
  body: string
  material: string
  orientation: Orientation
  physics_class: string
  recommended_grip: string
  product_scale: string
  fragility_level: string
  hand_object_interaction: string
  material_behavior: string
  surface_behavior: string
  air_gap_rule: string
  unsafe_handling_rules: string[]
  section_5_product_physics_prompt: string
  cta: string
  media_id: string
  camera_handling_notes: string
}



type UploadImageBase64Response = {
  media_id: string
}

const emptyForm: OperatorForm = {
  product_name: '',
  category: '',
  sub_category: '',
  type_angle: '',
  product_type: '',
  target_language: 'Malay',
  duration_target: '8s',
  engine_id: 'VEO_3_1',
  avatar_id: '',
  headwear_style: 'AUTO',
  camera_style: 'UGC_IPHONE_RAW',
  scene_context: '',
  trigger_id: '',
  silo_id: '',
  submode_formula: '',
  hook: '',
  usp_1: '',
  usp_2: '',
  usp_3: '',
  body: '',
  cta: '',
  material: 'realistic',
  orientation: 'VERTICAL',
  physics_class: '',
  recommended_grip: '',
  product_scale: '',
  fragility_level: '',
  hand_object_interaction: '',
  material_behavior: '',
  surface_behavior: '',
  air_gap_rule: '',
  unsafe_handling_rules: [],
  section_5_product_physics_prompt: '',
  media_id: '',
  camera_handling_notes: '',
}

function FieldLabel({ children }: { children: string }) {
  return <label className="text-xs font-bold" style={{ color: 'var(--muted)' }}>{children}</label>
}

function StatBadge({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'ready' | 'warn' | 'risk' }) {
  const styles = {
    neutral: { background: 'rgba(148,163,184,0.12)', color: 'var(--text)', border: '1px solid rgba(148,163,184,0.2)' },
    ready: { background: 'rgba(34,197,94,0.12)', color: '#86efac', border: '1px solid rgba(34,197,94,0.2)' },
    warn: { background: 'rgba(245,158,11,0.12)', color: '#fcd34d', border: '1px solid rgba(245,158,11,0.2)' },
    risk: { background: 'rgba(239,68,68,0.12)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.2)' },
  } as const
  return <span className="px-2 py-1 rounded text-[10px] font-semibold" style={styles[tone]}>{label}</span>
}

function ReadOnlyField({ label, value }: { label: string, value: string | null | undefined }) {
  return (
    <div className="flex flex-col gap-1">
      <FieldLabel>{label}</FieldLabel>
      <div className="px-2 py-1.5 rounded text-xs min-h-[32px] flex items-center" style={{ background: 'var(--surface)', color: value ? 'var(--text)' : 'var(--muted)', border: '1px solid var(--border)' }}>
        {value || '—'}
      </div>
    </div>
  )
}

function formatList(items: string[] | null | undefined) {
  return items && items.length > 0 ? items.join(', ') : '—'
}

function statusTone(status: string | null | undefined): 'neutral' | 'ready' | 'warn' | 'risk' {
  if (!status) return 'neutral'
  if (status === 'READY' || status === 'PASS') return 'ready'
  if (status === 'NEEDS_REVIEW' || status === 'MISSING_FIELDS' || status === 'NOT_CHECKED') return 'warn'
  return 'risk'
}

function Card({ children, className = "", style = {} }: { children: ReactNode, className?: string, style?: any }) {
  return (
    <div className={`p-4 rounded-xl border grid gap-4 transition-all duration-300 ${className}`} style={{ background: 'var(--card)', border: '1px solid var(--border)', boxShadow: '0 4px 20px -5px rgba(0,0,0,0.3)', ...style }}>
      {children}
    </div>
  )
}

function FlowRuntimePlan({
  mode,
  orientation,
  prompt,
  startAsset,
  endAsset,
  promptSource = 'System-generated product prompt'
}: {
  mode: string,
  orientation: Orientation,
  prompt: string,
  startAsset?: string | null,
  endAsset?: string | null,
  promptSource?: string
}) {
  const mapping: Record<string, any> = {
    TRUE_F2V: { lane: 'Frames', routeFamily: 'Video', model: 'Veo 3.1 - Lite', submit: 'right arrow' },
    GENERATE_VIDEO: { lane: 'Ingredients', routeFamily: 'Video', model: 'Veo 3.1 - Lite', submit: 'right arrow' },
    EDIT_IMAGE: { lane: 'Images', routeFamily: 'Image', model: 'Nano Banana 2', submit: 'generate button' },
    GENERATE_VIDEO_REFS: { lane: 'Ingredients', routeFamily: 'Video', model: 'Veo 3.1 - Lite', submit: 'right arrow' },
  }

  const plan = mapping[mode] || { lane: 'Unknown', routeFamily: 'Unknown', model: 'Unknown', submit: 'Unknown' }

  return (
    <div className="p-3 rounded border grid gap-2 text-[11px]" style={{ background: 'rgba(59,130,246,0.03)', border: '1px solid rgba(59,130,246,0.15)' }}>
      <div className="flex items-center gap-2 mb-1">
        <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></div>
        <span className="font-bold text-xs uppercase tracking-wider" style={{ color: 'var(--accent)' }}>Google Flow Runtime Plan</span>
      </div>
      
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 opacity-90">
        <div style={{ color: 'var(--muted)' }}>BOSMAX Mode:</div> <div className="font-mono text-[10px]">{mode}</div>
        <div style={{ color: 'var(--muted)' }}>Google Flow Label:</div> <div className="font-bold">{plan.lane}</div>
        <div style={{ color: 'var(--muted)' }}>Route Family:</div> <div className="font-bold">{plan.routeFamily}</div>
        <div style={{ color: 'var(--muted)' }}>Aspect Ratio:</div> <div className="font-bold">{orientation === 'VERTICAL' ? '9:16' : '16:9'}</div>
        <div style={{ color: 'var(--muted)' }}>Count:</div> <div className="font-bold">1x</div>
        <div style={{ color: 'var(--muted)' }}>Model:</div> <div className="font-bold">{plan.model}</div>
        <div style={{ color: 'var(--muted)' }}>Start Frame:</div> <div className="truncate">{startAsset || (mode === 'GENERATE_VIDEO' || mode === 'EDIT_IMAGE' || mode === 'TRUE_F2V' ? 'Product image / uploaded media' : 'Not used')}</div>
        <div style={{ color: 'var(--muted)' }}>End Frame:</div> <div className="truncate">{endAsset || 'Not used'}</div>
        <div style={{ color: 'var(--muted)' }}>Prompt Source:</div> <div className="italic">{promptSource}</div>
        <div style={{ color: 'var(--muted)' }}>Expected Submit:</div> <div className="font-bold flex items-center gap-1">{plan.submit}</div>
      </div>

      <div className="mt-2 border-t pt-2 border-blue-900/20">
        <div style={{ color: 'var(--muted)', fontSize: '10px' }} className="mb-1">Prompt Preview:</div>
        <div className="p-2 rounded font-mono text-[10px] leading-tight max-h-20 overflow-y-auto whitespace-pre-wrap" style={{ background: 'rgba(0,0,0,0.2)', color: 'var(--text)' }}>
          {prompt || '(Empty)'}
        </div>
      </div>

      <div className="mt-1 text-[9px] italic" style={{ color: 'var(--muted)' }}>
        Note: Google Flow settings are selected automatically by the Chrome extension. This panel shows the canonical SOP label the runtime will target.
      </div>
    </div>
  )
}

function AutomationReport({ reportJson }: { reportJson: string | null }) {
  if (!reportJson) return null
  
  let report: { ok: boolean, stages: Array<{ stage: string, status: string }>, error?: string }
  try {
    report = JSON.parse(reportJson)
  } catch (e) {
    return <div className="text-[10px] text-red-400 p-2">Invalid report data</div>
  }

  return (
    <div className="mt-3 p-3 rounded border grid gap-2" style={{ background: 'rgba(0,0,0,0.15)', border: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-bold uppercase tracking-wider flex items-center gap-2">
          <span>Execution Proof</span>
          {report.ok ? (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-green-900/40 text-green-400 border border-green-700/50">SUCCESS</span>
          ) : (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-900/40 text-red-400 border border-red-700/50">FAILED</span>
          )}
        </div>
        {report.error && <div className="text-[10px] text-red-400 font-mono truncate max-w-[200px]">{report.error}</div>}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 border-t pt-2 border-gray-800">
        {(report.stages || []).map((s, i) => (
          <div key={i} className="flex items-center justify-between gap-4 text-[10px] font-mono">
            <span style={{ color: 'var(--muted)' }}>{s.stage}</span>
            <span className={`font-bold ${
              s.status === 'YES' || s.status === 'PASS' ? 'text-green-400' : 
              s.status === 'NO' || s.status === 'FAIL' ? 'text-red-400' : 
              s.status === 'MAYBE' ? 'text-yellow-400' : 'text-blue-400'
            }`}>
              {s.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}


function SearchableSelect<T>({
  options,
  value,
  onChange,
  getLabel,
  getSublabel,
  placeholder = 'Search...',
  maxHeight = '260px'
}: {
  options: T[]
  value: string
  onChange: (val: T) => void
  getLabel: (opt: T) => string
  getSublabel?: (opt: T) => string
  placeholder?: string
  maxHeight?: string
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  
  const filtered = options.filter(opt => {
    const l = getLabel(opt).toLowerCase()
    const s = getSublabel ? getSublabel(opt).toLowerCase() : ''
    return l.includes(search.toLowerCase()) || s.includes(search.toLowerCase())
  })

  const selected = options.find(opt => (opt as any).id === value || (opt as any).product_name === value || (opt as any).name === value)
  
  return (
    <div className="relative">
      <div 
        onClick={() => setOpen(!open)}
        className="px-2 py-1.5 rounded text-xs cursor-pointer border flex justify-between items-center transition-colors hover:border-muted"
        style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
      >
        <span className="truncate flex-1">{selected ? getLabel(selected) : placeholder}</span>
        <span className="text-[10px] opacity-50 ml-2">{open ? '▲' : '▼'}</span>
      </div>
      
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div 
            className="absolute z-50 mt-1 w-full rounded border shadow-2xl overflow-hidden flex flex-col animate-in fade-in zoom-in duration-100"
            style={{ background: 'var(--card)', border: '1px solid var(--border)', maxHeight: '350px', left: 0 }}
          >
            <div className="p-2" style={{ background: 'var(--surface)' }}>
              <input 
                autoFocus
                placeholder="Search..."
                className="w-full p-2 text-xs rounded border outline-none"
                style={{ background: 'var(--card)', border: '1px solid var(--border)', color: 'var(--text)' }}
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            <div className="overflow-y-auto flex-1 scrollbar-thin scrollbar-thumb-muted" style={{ maxHeight }}>
              {filtered.map((opt, i) => (
                <div 
                  key={i}
                  onClick={() => {
                    onChange(opt)
                    setOpen(false)
                    setSearch('')
                  }}
                  className={`p-2 text-xs cursor-pointer hover:bg-blue-600/10 border-b last:border-0 transition-colors ${
                    ((opt as any).id === value || (opt as any).product_name === value || (opt as any).name === value) ? 'bg-blue-600/20' : ''
                  }`}
                  style={{ borderBottomColor: 'var(--border)' }}
                >
                  <div className="font-bold truncate">{getLabel(opt)}</div>
                  {getSublabel && <div className="text-[10px] opacity-60 truncate">{getSublabel(opt)}</div>}
                </div>
              ))}
              {filtered.length === 0 && <div className="p-4 text-center text-xs opacity-50">No results found</div>}
            </div>
          </div>
        </>
      )}
    </div>
  )
}




function stripExtension(name: string) {
  return name.replace(/\.[^/.]+$/, '')
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const payload = result.startsWith('data:') && result.includes(',')
        ? result.split(',', 2)[1]
        : result
      resolve(payload)
    }
    reader.onerror = () => reject(reader.error ?? new Error(`Failed to read ${file.name}`))
    reader.readAsDataURL(file)
  })
}

function mergeUniqueAssets(items: UploadedAsset[]) {
  const byMediaId = new Map<string, UploadedAsset>()
  for (const item of items) byMediaId.set(item.mediaId, item)
  return Array.from(byMediaId.values())
}

function mappingToOperatorProduct(mapping: ProductMapping): OperatorProduct {
  return {
    product_id: mapping.product_id || null,
    product_name: mapping.raw_product_title,
    raw_product_title: mapping.raw_product_title,
    product_short_name: mapping.product_short_name,
    product_display_name: mapping.raw_product_title,
    category: mapping.category,
    sub_category: mapping.subcategory,
    type_angle: mapping.type,
    product_type: mapping.product_type,
    silo_id: mapping.silo,
    trigger_id: mapping.trigger_id,
    submode_formula: mapping.formula,
    mode_recommendations: mapping.mode_recommendations,
    copywriting_angle: mapping.copywriting_angle,
    claim_risk_level: mapping.claim_risk_level,
    mapping_source: mapping.mapping_source,
    mapping_confidence: mapping.mapping_confidence,
    missing_fields: mapping.prompt_missing_fields || mapping.missing_fields,
    raw_category: null,
    avg_price_rm: null,
    status: null,
    copy_angle: null,
    hook: null,
    usp_1: null,
    usp_2: null,
    usp_3: null,
    body: null,
    cta: null,
    shop_name: null,
  }
}

function productToOperatorProduct(product: Product): OperatorProduct {
  return {
    product_id: product.product_id || product.id || null,
    product_name: product.raw_product_title,
    raw_product_title: product.raw_product_title,
    product_short_name: product.product_short_name,
    product_display_name: product.product_display_name,
    category: product.category || '',
    sub_category: product.subcategory || '',
    type_angle: product.type || '',
    product_type: product.product_type || null,
    silo_id: product.silo || null,
    trigger_id: product.trigger_id || null,
    submode_formula: product.formula || null,
    mode_recommendations: product.mode_recommendations || [],
    copywriting_angle: product.copywriting_angle || null,
    claim_risk_level: product.claim_risk_level || null,
    mapping_source: product.mapping_source || product.source,
    mapping_confidence: product.mapping_confidence || null,
    missing_fields: product.mapping_missing_fields || product.prompt_missing_fields || product.missing_fields || [],
    raw_category: null,
    avg_price_rm: product.price ?? product.price_min ?? null,
    status: product.mapping_review_status || null,
    copy_angle: product.copywriting_angle || null,
    hook: null,
    usp_1: null,
    usp_2: null,
    usp_3: null,
    body: null,
    cta: null,
    shop_name: product.shop_name || null,
  }
}

function mergeMappingIntoProduct(mapping: ProductMapping, existing?: Product | null): Product {
  return {
    id: mapping.product_id || existing?.id || '',
    product_id: mapping.product_id || existing?.product_id || existing?.id || '',
    source: existing?.source || 'MANUAL',
    raw_product_title: mapping.raw_product_title,
    product_display_name: existing?.product_display_name || mapping.raw_product_title,
    product_short_name: mapping.product_short_name,
    source_url: existing?.source_url || existing?.tiktok_product_url || null,
    brand: existing?.brand || null,
    category: mapping.category || null,
    subcategory: mapping.subcategory || null,
    type: mapping.type || null,
    price: existing?.price ?? existing?.price_min ?? null,
    currency: existing?.currency || 'MYR',
    commission_amount: existing?.commission_amount ?? null,
    commission_rate: existing?.commission_rate ?? existing?.commission ?? null,
    product_type: mapping.product_type || null,
    silo: mapping.silo || null,
    trigger_id: mapping.trigger_id || null,
    formula: mapping.formula || null,
    mode_recommendations: mapping.mode_recommendations,
    copywriting_angle: mapping.copywriting_angle || null,
    claim_risk_level: mapping.claim_risk_level || null,
    mapping_source: mapping.mapping_source,
    mapping_confidence: mapping.mapping_confidence,
    mapping_review_status: mapping.mapping_review_status || null,
    mapping_status: mapping.mapping_status || null,
    mapping_missing_fields: mapping.mapping_missing_fields || mapping.missing_fields || [],
    prompt_readiness_status: mapping.prompt_readiness_status || null,
    prompt_missing_fields: mapping.prompt_missing_fields || [],
    physics_class: mapping.physics_class || null,
    product_scale: mapping.product_scale || null,
    hand_object_interaction: mapping.hand_object_interaction || null,
    recommended_grip: mapping.recommended_grip || null,
    handling_notes: mapping.handling_notes || null,
    air_gap_rule: mapping.air_gap_rule || null,
    material_behavior: mapping.material_behavior || null,
    surface_behavior: mapping.surface_behavior || null,
    fragility_level: mapping.fragility_level || null,
    camera_handling_notes: mapping.camera_handling_notes || null,
    scene_context: mapping.scene_context || null,
    camera_style: mapping.camera_style || null,
    camera_behavior: mapping.camera_behavior || null,
    camera_shot: mapping.camera_shot || null,
    unsafe_handling_rules: mapping.unsafe_handling_rules || [],
    section_4_hint: mapping.section_4_hint || null,
    section_5_physics_hint: mapping.section_5_physics_hint || null,
    section_6_copy_hint: mapping.section_6_copy_hint || null,
    section_9_overlay_hint: mapping.section_9_overlay_hint || null,
    section_4_visual_action_prompt: mapping.section_4_visual_action_prompt || null,
    section_5_product_physics_prompt: mapping.section_5_product_physics_prompt || null,
    section_6_dialogue_prompt: mapping.section_6_dialogue_prompt || null,
    section_9_overlay_prompt: mapping.section_9_overlay_prompt || null,
    missing_fields: mapping.missing_fields,
    notes: mapping.notes,
    shop_name: existing?.shop_name || null,
    price_min: existing?.price_min || null,
    price_max: existing?.price_max || null,
    commission: existing?.commission || null,
    image_url: existing?.image_url || null,
    tiktok_product_url: existing?.tiktok_product_url || null,
    fastmoss_source_file: existing?.fastmoss_source_file || null,
    image_asset_status: existing?.image_asset_status || existing?.asset_status || 'UNRESOLVED',
    asset_status: existing?.asset_status || 'UNRESOLVED',
    media_id: existing?.media_id || null,
    local_image_path: existing?.local_image_path || null,
    created_at: existing?.created_at || '',
    updated_at: existing?.updated_at || '',
  }
}

export function DeploymentStatusCard({
  agentStatus,
  extensionConnected,
}: {
  agentStatus: LocalAgentStatus | null
  extensionConnected: boolean
}) {
  if (!agentStatus) return null

  const isOnline = agentStatus.extension_connected && agentStatus.extension_state === 'IDLE'
  const deploymentMode = 'LOCAL_AGENT'
  const autoStartEnabled = agentStatus.auto_start_enabled

  return (
    <Card className="border-amber-700/20" style={{ background: 'linear-gradient(135deg, rgba(217,119,6,0.05), rgba(217,119,6,0.01))' }}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <span className={`w-2 h-2 rounded-full ${isOnline ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
          Deployment Status
        </h3>
        <div className={`text-[10px] px-2 py-0.5 rounded font-bold ${isOnline ? 'bg-green-600/20 text-green-400' : 'bg-red-600/20 text-red-400'}`}>
          {isOnline ? 'ONLINE' : 'OFFLINE'}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50 mb-1">Mode</div>
          <div className="text-xs font-bold">{deploymentMode}</div>
        </div>
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50 mb-1">Auto-Start</div>
          <div className={`text-xs font-bold ${autoStartEnabled ? 'text-green-400' : 'text-yellow-400'}`}>
            {autoStartEnabled ? 'INSTALLED' : 'NOT SET'}
          </div>
        </div>
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50 mb-1">Extension</div>
          <div className={`text-xs font-bold ${extensionConnected ? 'text-green-400' : 'text-red-400'}`}>
            {extensionConnected ? 'CONNECTED' : 'OFFLINE'}
          </div>
        </div>
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50 mb-1">Last Check</div>
          <div className="text-xs font-mono">{agentStatus.last_health_check ? new Date(agentStatus.last_health_check).toLocaleTimeString() : '—'}</div>
        </div>
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50 mb-1">License</div>
          <div className={`text-xs font-bold ${agentStatus.license_status === 'UNLICENSED' ? 'text-yellow-400' : 'text-green-400'}`}>
            {agentStatus.license_status}
          </div>
        </div>
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50 mb-1">Approval</div>
          <div className={`text-xs font-bold ${agentStatus.approval_status === 'PENDING_APPROVAL' ? 'text-yellow-400' : 'text-green-400'}`}>
            {agentStatus.approval_status}
          </div>
        </div>
      </div>

      {agentStatus.offline_reason && (
        <div className="p-2 rounded mb-3 bg-red-600/10 border border-red-800/30">
          <div className="text-[8px] uppercase opacity-60 mb-1">Offline Reason</div>
          <div className="text-[11px] font-mono text-red-400">{agentStatus.offline_reason}</div>
        </div>
      )}

      <div className="p-2 rounded bg-black/20 border border-white/5 text-[9px]">
        <div className="opacity-60 mb-1">Cross-PC Deployment Notes</div>
        <div className="text-[10px] leading-relaxed opacity-70">
          This local agent runs only on this Windows PC. To use BOSMAX from another PC, install the local agent there too.
          For shared account/data across PCs, a hosted/hybrid backend is required. Do not expect 24/7 cross-PC availability
          from local-only agents.
        </div>
      </div>
    </Card>
  )
}

export function SystemHealthPanel({
  telemetry,
  agentStatus,
  checkingAgent,
  smokeTesting,
  diagnosing,
  extensionConnected,
  onCheckAgent,
  onRefreshTelemetry,
  onRunSelfTest,
  onRunSmokeTest,
  onExportDiagnostics
}: {
  telemetry: TelemetrySummary | null
  agentStatus: LocalAgentStatus | null
  checkingAgent: boolean
  smokeTesting: boolean
  diagnosing: boolean
  extensionConnected: boolean
  onCheckAgent: () => void
  onRefreshTelemetry: () => void
  onRunSelfTest: () => void
  onRunSmokeTest: () => void
  onExportDiagnostics: () => void
}) {
  return (
    <Card className="border-blue-900/30" style={{ background: 'rgba(30,58,138,0.05)' }}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text)' }}>
          <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          System Health & Flow Readiness
        </h3>
        <div className="flex items-center gap-2">
          <button onClick={onCheckAgent} disabled={checkingAgent} className="text-[10px] px-2 py-1 rounded bg-gray-800 border border-gray-700 hover:border-blue-500 transition-all">
            {checkingAgent ? 'Checking...' : 'Check Local Agent'}
          </button>
          <button onClick={onExportDiagnostics} disabled={diagnosing} className="text-[10px] px-2 py-1 rounded bg-gray-800 border border-gray-700 hover:border-blue-500 transition-all">
            {diagnosing ? 'Exporting...' : 'Diagnostics Bundle'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50">Local Agent</div>
          <div className={`text-xs font-bold ${agentStatus ? 'text-green-400' : 'text-yellow-400'}`}>
            {agentStatus ? 'ONLINE' : 'UNKNOWN'}
          </div>
        </div>
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50">Extension</div>
          <div className={`text-xs font-bold ${extensionConnected ? 'text-green-400' : 'text-red-400'}`}>
            {extensionConnected ? 'CONNECTED' : 'OFFLINE'}
          </div>
        </div>
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50">Serving Mode</div>
          <div className="text-xs font-bold truncate">{agentStatus?.dashboard_serving_mode || '-'}</div>
        </div>
        <div className="p-2 rounded bg-black/20 border border-white/5">
          <div className="text-[8px] uppercase opacity-50">Last Heartbeat</div>
          <div className="text-xs font-mono">{telemetry?.last_stage ? new Date().toLocaleTimeString() : '-'}</div>
        </div>
      </div>

      <div className="flex gap-2 flex-wrap mb-4">
        <button onClick={onRefreshTelemetry} className="px-3 py-1.5 rounded text-[10px] font-bold bg-blue-600/20 text-blue-400 border border-blue-800/50 hover:bg-blue-600/30 transition-all">
          Refresh Telemetry
        </button>
        <button onClick={onRunSelfTest} className="px-3 py-1.5 rounded text-[10px] font-bold bg-green-600/20 text-green-400 border border-green-800/50 hover:bg-green-600/30 transition-all">
          Run Telemetry Self-Test
        </button>
        <button onClick={onRunSmokeTest} disabled={smokeTesting} className="px-3 py-1.5 rounded text-[10px] font-bold bg-purple-600/20 text-purple-400 border border-purple-800/50 hover:bg-purple-600/30 transition-all">
          {smokeTesting ? 'Checking Flow...' : 'Check Flow Readiness'}
        </button>
      </div>

      {telemetry && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 p-2 rounded bg-black/10 border border-white/5 text-[10px]">
          <div><span className="opacity-50">Total Today:</span> <span className="font-mono text-blue-400">{telemetry.total_today}</span></div>
          <div><span className="opacity-50">Completed:</span> <span className="font-mono text-green-400">{telemetry.completed}</span></div>
          <div><span className="opacity-50">Failed:</span> <span className="font-mono text-red-400">{telemetry.failed}</span></div>
          <div><span className="opacity-50">Processing:</span> <span className="font-mono text-blue-300 animate-pulse">{telemetry.processing}</span></div>
          <div><span className="opacity-50">Avg Idle:</span> <span className="font-mono">{telemetry.idle_seconds}s</span></div>
          <div><span className="opacity-50">Last Stage:</span> <span className="font-bold text-accent">{telemetry.last_stage || 'IDLE'}</span></div>
        </div>
      )}
    </Card>
  )
}

export default function OperatorPage() {
  const [pack, setPack] = useState<ContentPackSummary | null>(null)
  const [form, setForm] = useState<OperatorForm>(emptyForm)
  const [selectedProductName, setSelectedProductName] = useState('')
  const [blueprint, setBlueprint] = useState<BlueprintResponse | null>(null)
  const [created, setCreated] = useState<CreatedState | null>(null)
  const [projectCharacters, setProjectCharacters] = useState<Character[]>([])
  const [videoScenes, setVideoScenes] = useState<Scene[]>([])
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null)
  const [activeBatchType, setActiveBatchType] = useState<string>('')
  const [loadingPack, setLoadingPack] = useState(true)
  const [building, setBuilding] = useState(false)
  const [creating, setCreating] = useState(false)
  const [queueing, setQueueing] = useState(false)
  const [uploadingAssets, setUploadingAssets] = useState(false)
  const [submittingManual, setSubmittingManual] = useState(false)
  const [message, setMessage] = useState('')
  const [manualFiles, setManualFiles] = useState<File[]>([])
  const [uploadedAssets, setUploadedAssets] = useState<UploadedAsset[]>([])
  const [manualAssetName, setManualAssetName] = useState('')
  const [manualEntityType, setManualEntityType] = useState<ManualEntityType>('visual_asset')
  const [selectedSceneId, setSelectedSceneId] = useState('')
  const [manualPrompt, setManualPrompt] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [generatingPrompt, setGeneratingPrompt] = useState(false)
  const [f2vStartAssetId, setF2vStartAssetId] = useState('')
  const [f2vEndAssetId, setF2vEndAssetId] = useState('')
  const [f2vStartFile, setF2vStartFile] = useState<File | null>(null)
  const [f2vEndFile, setF2vEndFile] = useState<File | null>(null)
  const [uploadingF2vStart, setUploadingF2vStart] = useState(false)
  const [uploadingF2vEnd, setUploadingF2vEnd] = useState(false)
  const [catalogProducts, setCatalogProducts] = useState<Product[]>([])
  const [canonicalProducts, setCanonicalProducts] = useState<Product[]>([])
  const [selectedCatalogProduct, setSelectedCatalogProduct] = useState<Product | null>(null)
  const [resolvedMapping, setResolvedMapping] = useState<ProductMapping | null>(null)
  const [operatorPreflight, setOperatorPreflight] = useState<OperatorPreflightResponse | null>(null)
  const [flowReadiness, setFlowReadiness] = useState<FlowReadinessSmokeResult | null>(null)
  const [mappingBusy, setMappingBusy] = useState(false)
  const [repairingMapping, setRepairingMapping] = useState(false)
  const [backfillingMappings, setBackfillingMappings] = useState(false)
  const [advancedOverrideOpen, setAdvancedOverrideOpen] = useState(false)
  const [overrideDraft, setOverrideDraft] = useState({ category: '', subcategory: '', type: '' })
  const [manualProductName, setManualProductName] = useState('')
  const [manualProducts, setManualProducts] = useState<OperatorProduct[]>([])
  const [catalogSearchQuery, setCatalogSearchQuery] = useState('')
  const [searchingCatalog, setSearchingCatalog] = useState(false)
  const [importingCatalog, setImportingCatalog] = useState(false)
  const [recentRequests, setRecentRequests] = useState<Request[]>([])
  const [hoveredMode, setHoveredMode] = useState<string | null>(null)
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [agentStatus, setAgentStatus] = useState<LocalAgentStatus | null>(null)
  const [checkingAgent, setCheckingAgent] = useState(false)
  const [smokeTesting, setSmokeTesting] = useState(false)
  const [reloadingFlowTab, setReloadingFlowTab] = useState(false)
  const [diagnosing, setDiagnosing] = useState(false)
  const [brief, setBrief] = useState<any | null>(null)
  const [promptPreview, setPromptPreview] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [allProjects, setAllProjects] = useState<Project[]>([])
  const [allVideos, setAllVideos] = useState<Video[]>([])
  const [, setFetchingProjects] = useState(false)
  const [, setFetchingVideos] = useState(false)

  const { isConnected: backendConnected, extensionConnected } = useWebSocketContext()
  const availableProducts = [...manualProducts, ...canonicalProducts.map(productToOperatorProduct)]
  const selectedScene = videoScenes.find(item => item.id === selectedSceneId)
  const selectedProductId = selectedCatalogProduct?.id || resolvedMapping?.product_id || ''
  const preflight = operatorPreflight?.preflight || null
  const systemVideoPrompt = systemPrompt || selectedScene?.video_prompt || selectedScene?.prompt || ''
  const manualPromptOverride = manualPrompt.trim()
  const resolvedVideoPrompt = manualPromptOverride || systemVideoPrompt
  const promptSource = manualPromptOverride ? 'USER_OVERRIDE' : (systemVideoPrompt ? 'SYSTEM' : 'MISSING')
  const blueprintBlocked = !preflight?.build_allowed
  const executionBlocked = blueprintBlocked || Boolean(flowReadiness?.primary_blocker)

  // True F2V Readiness Rules
  const f2vResolvedPromptReady = resolvedVideoPrompt.trim().length > 0
  const f2vSystemPromptReady = systemVideoPrompt.trim().length > 0
  const f2vStartReady = !!f2vStartAssetId
  const f2vEndReady = !!f2vEndAssetId
  const f2vDifferentAssets = !f2vEndReady || f2vStartAssetId !== f2vEndAssetId
  const f2vSceneReady = !!selectedSceneId
  const f2vReady =
    f2vSceneReady &&
    f2vStartReady &&
    f2vResolvedPromptReady &&
    f2vDifferentAssets &&
    !submittingManual &&
    !uploadingAssets &&
    !uploadingF2vStart &&
    !uploadingF2vEnd

  const f2vBlockingReasons: string[] = []
  const f2vAdvisoryReasons: string[] = []
  if (!f2vSceneReady) f2vBlockingReasons.push('Select a target scene.')
  if (!f2vStartReady) f2vBlockingReasons.push('Upload a Start Frame to Flow.')
  if (f2vStartReady && f2vEndReady && !f2vDifferentAssets) f2vBlockingReasons.push('Start and End frames must be different assets.')
  if (!f2vResolvedPromptReady) {
    if (!f2vSystemPromptReady && !manualPromptOverride) {
      f2vBlockingReasons.push('System prompt generating...')
    } else {
      f2vBlockingReasons.push('ERROR: SYSTEM_PROMPT_MISSING')
    }
  }
  if (uploadingAssets) f2vBlockingReasons.push('Wait for upload to finish.')
  if (uploadingF2vStart) f2vBlockingReasons.push('Wait for Start Frame upload to finish.')
  if (uploadingF2vEnd) f2vBlockingReasons.push('Wait for End Frame upload to finish.')
  if (submittingManual) f2vBlockingReasons.push('Submission already running.')

  if (!f2vEndReady) f2vAdvisoryReasons.push('End Frame is optional. Use it only if you want last-frame control.')

  useEffect(() => {
    setFetchingProjects(true)
    fetchAPI<Project[]>('/api/projects')
      .then(setAllProjects)
      .finally(() => setFetchingProjects(false))
  }, [created])

  useEffect(() => {
    if (!created?.project.id) return
    setFetchingVideos(true)
    fetchAPI<Video[]>(`/api/videos?project_id=${created.project.id}`)
      .then(setAllVideos)
      .finally(() => setFetchingVideos(false))
  }, [created?.project.id])

  useEffect(() => {
    const timer = window.setInterval(() => {
      fetchAPI<TelemetrySummary>('/api/telemetry/summary')
        .then(setTelemetry)
        .catch(() => {})
    }, 3000)
    return () => window.clearInterval(timer)
  }, [])

  async function loadCanonicalProducts(limit = 200) {
    const response = await fetchAPI<{ items: Product[] }>(`/api/products?limit=${limit}&offset=0`)
    setCanonicalProducts(response.items || [])
    return response.items || []
  }


  useEffect(() => {
    setLoadingPack(true)
    fetchAPI<ContentPackSummary>('/api/operator/content-pack')
      .then(data => {
        setPack(data)
        const firstProduct = data.products[0]
        setForm({
          ...emptyForm,
          engine_id: data.engines[0] ?? emptyForm.engine_id,
          duration_target: data.durations_by_engine[data.engines[0] ?? emptyForm.engine_id]?.[0] ?? emptyForm.duration_target,
          avatar_id: data.avatars[0] ?? '',
          headwear_style: data.headwear_styles[0] ?? emptyForm.headwear_style,
          camera_style: data.camera_styles[0] ?? emptyForm.camera_style,
          target_language: data.language_defaults[0] ?? emptyForm.target_language,
          material: data.materials[0] ?? emptyForm.material,
          product_name: firstProduct?.product_short_name ?? firstProduct?.product_name ?? '',
          category: '',
          sub_category: '',
          type_angle: '',
          hook: firstProduct?.hook ?? '',
          usp_1: firstProduct?.usp_1 ?? '',
          usp_2: firstProduct?.usp_2 ?? '',
          usp_3: firstProduct?.usp_3 ?? '',
          body: firstProduct?.body ?? '',
          cta: firstProduct?.cta ?? '',
          scene_context: '',
        })
        setSelectedProductName(firstProduct?.product_name ?? '')
        setResolvedMapping(null)
        setOverrideDraft({ category: '', subcategory: '', type: '' })
        if (firstProduct) {
          void resolveProductMapping({
            product_name: firstProduct.raw_product_title || firstProduct.product_name,
            source: 'FASTMOSS',
            category: firstProduct.category,
            subcategory: firstProduct.sub_category,
            type: firstProduct.type_angle,
          })
        }
      })
      .catch(err => setMessage(`Failed to load content pack: ${String(err)}`))
      .finally(() => setLoadingPack(false))
  }, [])

  useEffect(() => {
    void loadCanonicalProducts().catch(err => setMessage(`Failed to load canonical products: ${String(err)}`))
  }, [])

  useEffect(() => {
    if (!pack || !form.engine_id) return
    const durations = pack.durations_by_engine[form.engine_id] ?? []
    if (durations.length > 0 && !durations.includes(form.duration_target)) {
      setForm(current => ({ ...current, duration_target: durations[0] }))
    }
  }, [pack, form.engine_id, form.duration_target])

  useEffect(() => {
    if (!created || !activeBatchType) return
    if (batchStatus?.done) return
    const timer = window.setInterval(() => {
      fetchAPI<BatchStatus>(`/api/requests/batch-status?video_id=${created.video.id}&type=${activeBatchType}&orientation=${form.orientation}`)
        .then(setBatchStatus)
        .catch(() => {})
    }, 5000)
    return () => window.clearInterval(timer)
  }, [created, activeBatchType, batchStatus?.done, form.orientation])

  useEffect(() => {
    if (!created) return
    const timer = window.setInterval(() => {
      fetchAPI<Request[]>(`/api/requests/snapshot?project_id=${created.project.id}&limit=5`)
        .then(setRecentRequests)
        .catch(() => {})
    }, 4000)
    return () => window.clearInterval(timer)
  }, [created])

  useEffect(() => {
    if (!created) {
      setProjectCharacters([])
      setVideoScenes([])
      setSelectedSceneId('')
      setUploadedAssets([])
      return
    }
    void refreshCreatedResources(created)
  }, [created])

  async function syncSelectedProductState(productId: string) {
    const [product, mapping, preflightResponse] = await Promise.all([
      fetchAPI<Product>(`/api/products/${productId}`),
      fetchAPI<ProductMapping>(`/api/products/${productId}/mapping`),
      fetchAPI<OperatorPreflightResponse>(`/api/operator/preflight?product_id=${encodeURIComponent(productId)}`),
    ])

    setSelectedCatalogProduct(product)
    setResolvedMapping(mapping)
    setOperatorPreflight(preflightResponse)
    setCanonicalProducts(current => current.map(item => item.id === product.id ? product : item))
    setManualProducts(current => current.map(item => item.product_id === product.id ? productToOperatorProduct(product) : item))
    return { product, mapping, preflightResponse }
  }

  async function backfillMappings() {
    setBackfillingMappings(true)
    try {
      const result = await postAPI<any>('/api/products/backfill-mapping', {})
      await loadCanonicalProducts()
      if (selectedProductId) {
        await syncSelectedProductState(selectedProductId)
      }
      setMessage(`Backfill complete: ${result.total_products_processed} processed, ${result.total_mapping_ready} READY, ${result.total_needs_review} NEEDS_REVIEW, ${result.total_blocked} BLOCKED.`)
    } catch (err) {
      setMessage(`Backfill failed: ${String(err)}`)
    } finally {
      setBackfillingMappings(false)
    }
  }

  async function repairSelectedProductMapping() {
    if (!selectedProductId) {
      setMessage('Select a product before repairing mapping.')
      return
    }

    setRepairingMapping(true)
    try {
      await postAPI(`/api/products/${selectedProductId}/repair-mapping`, {})
      await syncSelectedProductState(selectedProductId)
      setFlowReadiness(null)
      setMessage('Product mapping repaired and preflight refreshed.')
    } catch (err) {
      setMessage(`Repair mapping failed: ${String(err)}`)
    } finally {
      setRepairingMapping(false)
    }
  }

  function updateField<K extends keyof OperatorForm>(field: K, value: OperatorForm[K]) {
    setForm(current => ({ ...current, [field]: value }))
  }

  async function resolveProductMapping(payload: Record<string, unknown>) {
    setMappingBusy(true)
    try {
      const mapping = await postAPI<ProductMapping>('/api/products/map', payload)
      setResolvedMapping(mapping)
      setFlowReadiness(null)
      setOverrideDraft({
        category: mapping.category || '',
        subcategory: mapping.subcategory || '',
        type: mapping.type || '',
      })
      setForm(current => ({
        ...current,
        product_name: mapping.product_short_name || current.product_name,
        category: mapping.category || '',
        sub_category: mapping.subcategory || '',
        type_angle: mapping.type || '',
        product_type: mapping.product_type || '',
        trigger_id: mapping.trigger_id || '',
        silo_id: mapping.silo || '',
        submode_formula: mapping.formula || '',
        physics_class: mapping.physics_class || '',
        recommended_grip: mapping.recommended_grip || '',
        product_scale: mapping.product_scale || '',
        fragility_level: mapping.fragility_level || '',
        hand_object_interaction: mapping.hand_object_interaction || '',
        material_behavior: mapping.material_behavior || '',
        surface_behavior: mapping.surface_behavior || '',
        air_gap_rule: mapping.air_gap_rule || '',
        unsafe_handling_rules: mapping.unsafe_handling_rules || [],
        section_5_product_physics_prompt: mapping.section_5_product_physics_prompt || '',
        scene_context: mapping.scene_context || mapping.raw_product_title || current.scene_context,
      }))
      if (mapping.product_id) {
        await syncSelectedProductState(mapping.product_id)
      } else {
        setOperatorPreflight(null)
      }
      const mappingMissing = mapping.mapping_missing_fields || mapping.missing_fields || []
      if ((mapping.mapping_status || 'READY') !== 'READY') {
        setMessage(`Mapping ${mapping.mapping_status || 'NEEDS_REVIEW'}: ${mappingMissing.join(', ')}`)
      }
      return mapping
    } catch (err) {
      setMessage('Product mapping failed: ' + String(err))
      return null
    } finally {
      setMappingBusy(false)
    }
  }

  function applyProduct(productName: string) {
    setSelectedProductName(productName)
    const product = availableProducts.find(item => item.product_name === productName)
    if (!product) return
    setForm(current => ({
      ...current,
      hook: product.hook ?? '',
      usp_1: product.usp_1 ?? '',
      usp_2: product.usp_2 ?? '',
      usp_3: product.usp_3 ?? '',
      body: product.body ?? '',
      cta: product.cta ?? '',
    }))
    void resolveProductMapping({
      product_id: product.product_id || undefined,
      product_name: product.raw_product_title || product.product_name,
      source: product.mapping_source === 'MANUAL' ? 'MANUAL' : 'FASTMOSS',
      category: product.category,
      subcategory: product.sub_category,
      type: product.type_angle,
      persist: Boolean(product.product_id),
    })
  }

  async function refreshCreatedResources(current: CreatedState) {
    const [characters, scenes] = await Promise.all([
      fetchAPI<Character[]>(`/api/projects/${current.project.id}/characters`),
      fetchAPI<Scene[]>(`/api/scenes?video_id=${current.video.id}`),
    ])
    setProjectCharacters(characters)
    setVideoScenes(scenes)
    setSelectedSceneId(existing => existing || scenes[0]?.id || '')
  }

  // Auto-generate system prompt when product changes
  useEffect(() => {
    if (!form.product_name) {
      setSystemPrompt('')
      return
    }

    setGeneratingPrompt(true)
    fetchAPI<{prompt: string, prompt_source: string}>(`/api/products/${encodeURIComponent(form.product_name)}/prompt?mode=TRUE_F2V`)
      .then(res => {
        if (res?.prompt) {
          setSystemPrompt(res.prompt)
        }
      })
      .catch(() => setSystemPrompt(''))
      .finally(() => setGeneratingPrompt(false))
  }, [form.product_name])


  async function selectProject(p: Project) {
    setFetchingVideos(true)
    try {
      const videos = await fetchAPI<Video[]>(`/api/videos?project_id=${p.id}`)
      setAllVideos(videos)
      if (videos.length > 0) {
        setCreated({ project: p, video: videos[0] })
      } else {
        setCreated(null) // Or handle project without videos
      }
    } catch (err) {
      setMessage(`Failed to load videos for project: ${String(err)}`)
    } finally {
      setFetchingVideos(false)
    }
  }

  async function selectVideo(v: Video) {
    if (!created) return
    setCreated({ ...created, video: v })
  }

  async function checkAgent() {
    setCheckingAgent(true)
    try {
      const status = await fetchAPI<LocalAgentStatus>('/api/local-agent/status')
      setAgentStatus(status)
      setMessage('Local Agent status refreshed.')
    } catch (err) {
      setMessage(`Agent check failed: ${String(err)}`)
    } finally {
      setCheckingAgent(false)
    }
  }

  async function runTelemetrySelfTest() {
    try {
      const res = await postAPI<any>('/api/telemetry/self-test', {})
      setMessage(`Telemetry self-test: ${res.ok ? 'PASS' : 'FAIL'} (ID: ${res.test_id})`)
    } catch (err) {
      setMessage(`Self-test failed: ${String(err)}`)
    }
  }

  async function runF2VSmokeTest() {
    setSmokeTesting(true)
    try {
      const res = await postAPI<FlowReadinessSmokeResult>('/api/operator/flow-readiness-smoke', {
        product_id: selectedProductId || undefined,
        mode: 'F2V',
      })
      setFlowReadiness(res)
      setMessage(res.primary_blocker ? `Flow readiness blocked: ${res.primary_blocker}` : 'Flow readiness is READY.')
    } catch (err) {
      setMessage(`Flow readiness check failed: ${String(err)}`)
    } finally {
      setSmokeTesting(false)
    }
  }

  async function reloadFlowTabAndReinject() {
    setReloadingFlowTab(true)
    try {
      const result = await postAPI<ReloadFlowTabResult>('/api/operator/reload-flow-tab', {})
      setMessage(result.ok ? 'Flow tab reloaded and content script re-injected.' : `Flow tab reload/reinject failed: ${result.error || 'UNKNOWN'}`)
      await runF2VSmokeTest()
    } catch (err) {
      setMessage(`Flow tab reload/reinject failed: ${String(err)}`)
    } finally {
      setReloadingFlowTab(false)
    }
  }

  async function exportDiagnostics() {
    setDiagnosing(true)
    try {
      const bundle = await postAPI<any>('/api/diagnostics/export', {})
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `flowkit_diagnostics_${new Date().toISOString().replace(/[:.]/g, '-')}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setMessage('Diagnostics bundle exported successfully.')
    } catch (err) {
      setMessage(`Export failed: ${String(err)}`)
    } finally {
      setDiagnosing(false)
    }
  }

  async function buildBlueprint() {
    if (blueprintBlocked) {
      setMessage(preflight?.blocking_reason || 'Product preflight is blocked. Repair mapping before building the blueprint.')
      return
    }
    setBuilding(true)
    setMessage('')
    try {
      const data = await postAPI<BlueprintResponse>('/api/operator/blueprint', form as unknown as Record<string, unknown>)
      setBlueprint(data)
      setCreated(null)
      setBatchStatus(null)
      setActiveBatchType('')
      setMessage('Blueprint compiled from BOSMAX content pack.')
    } catch (err) {
      setMessage(`Blueprint build failed: ${String(err)}`)
    } finally {
      setBuilding(false)
    }
  }

  async function createProjectFromBlueprint() {
    if (!blueprint) return
    if (blueprintBlocked) {
      setMessage(preflight?.blocking_reason || 'Product preflight is blocked. Repair mapping before creating the project.')
      return
    }
    setCreating(true)
    setMessage('')
    try {
      const project = await postAPI<Project>('/api/projects', blueprint.project as Record<string, unknown>)
      const video = await postAPI<Video>('/api/videos', {
        ...(blueprint.video as Record<string, unknown>),
        project_id: project.id,
      })

      for (const scene of blueprint.scenes) {
        await postAPI<Scene>('/api/scenes', {
          video_id: video.id,
          display_order: scene.display_order,
          prompt: scene.prompt,
          image_prompt: scene.image_prompt,
          video_prompt: scene.video_prompt,
          character_names: scene.character_names,
          chain_type: scene.chain_type,
        })
      }

      setCreated({ project, video })
      setMessage(`Project created: ${project.name}`)
    } catch (err) {
      setMessage(`Project creation failed: ${String(err)}`)
    } finally {
      setCreating(false)
    }
  }

  async function queueRequests(type: 'GENERATE_CHARACTER_IMAGE' | 'GENERATE_IMAGE' | 'GENERATE_VIDEO' | 'GENERATE_VIDEO_REFS' | 'UPSCALE_VIDEO') {
    if (!created) return
    if (executionBlocked) {
      setMessage(flowReadiness?.primary_blocker || preflight?.blocking_reason || 'Preflight is blocked. Repair mapping and re-check Flow readiness before executing.')
      return
    }
    setQueueing(true)
    setMessage('')
    try {
      if (type === 'GENERATE_CHARACTER_IMAGE') {
        const characters = await fetchAPI<Character[]>(`/api/projects/${created.project.id}/characters`)
        await postAPI('/api/requests/batch', {
          requests: characters.map(character => ({
            type,
            project_id: created.project.id,
            character_id: character.id,
          })),
        })
        setMessage('Reference image queue submitted.')
        setActiveBatchType('')
        setBatchStatus(null)
        return
      }

      const scenes = await fetchAPI<Scene[]>(`/api/scenes?video_id=${created.video.id}`)
      await postAPI('/api/requests/batch', {
        requests: scenes.map(scene => ({
          type,
          project_id: created.project.id,
          video_id: created.video.id,
          scene_id: scene.id,
          orientation: form.orientation,
        })),
      })

      setActiveBatchType(type)
      const status = await fetchAPI<BatchStatus>(`/api/requests/batch-status?video_id=${created.video.id}&type=${type}&orientation=${form.orientation}`)
      setBatchStatus(status)

      const labels: Record<string, string> = {
        GENERATE_IMAGE: 'Image generation queue submitted.',
        GENERATE_VIDEO: 'Ingredients queue submitted.',
        GENERATE_VIDEO_REFS: 'Frames queue submitted.',
        UPSCALE_VIDEO: 'Upscale queue submitted.',
      }
      setMessage(labels[type] ?? 'Queue submitted.')
    } catch (err) {
      setMessage(`Queue submission failed: ${String(err)}`)
    } finally {
      setQueueing(false)
    }
  }

  async function uploadManualAssets() {
    if (!created || manualFiles.length === 0) return
    setUploadingAssets(true)
    setMessage('')

    try {
      const nextAssets: UploadedAsset[] = []

      for (const [index, file] of manualFiles.entries()) {
        const imageBase64 = await fileToBase64(file)
        const upload = await postAPI<UploadImageBase64Response>('/api/flow/upload-image-base64', {
          image_base64: imageBase64,
          mime_type: file.type || 'image/png',
          project_id: created.project.id,
          file_name: file.name,
        })

        const label = manualAssetName.trim() && manualFiles.length === 1
          ? manualAssetName.trim()
          : `${stripExtension(file.name)}${manualFiles.length > 1 ? `-${index + 1}` : ''}`

        const existing = projectCharacters.find(character => character.name === label)
        let character: Character
        if (existing) {
          character = await patchAPI<Character>(`/api/characters/${existing.id}`, {
            entity_type: manualEntityType,
            media_id: upload.media_id,
          })
        } else {
          character = await postAPI<Character>('/api/characters', {
            name: label,
            entity_type: manualEntityType,
            media_id: upload.media_id,
          })
          await postAPI(`/api/projects/${created.project.id}/characters/${character.id}`, {})
        }

        nextAssets.push({
          label,
          mediaId: upload.media_id,
          characterId: character.id,
          entityType: manualEntityType,
          fileName: file.name,
        })
      }

      setUploadedAssets(current => mergeUniqueAssets([...current, ...nextAssets]))
      await refreshCreatedResources(created)
      setManualFiles([])
      setMessage(`Upload complete. ${nextAssets.length} asset${nextAssets.length === 1 ? '' : 's'} now available in Start/End dropdowns.`)
    } catch (err) {
      setMessage(`Photo upload failed: ${String(err)}`)
    } finally {
      setUploadingAssets(false)
    }
  }

  async function uploadSingleF2vFrame(kind: 'start' | 'end') {
    const file = kind === 'start' ? f2vStartFile : f2vEndFile
    if (!created || !file) return

    const setUploading = kind === 'start' ? setUploadingF2vStart : setUploadingF2vEnd
    setUploading(true)
    setMessage('')

    try {
      const imageBase64 = await fileToBase64(file)
      const upload = await postAPI<UploadImageBase64Response>('/api/flow/upload-image-base64', {
        image_base64: imageBase64,
        mime_type: file.type || 'image/png',
        project_id: created.project.id,
        file_name: file.name,
      })

      const label = `F2V ${kind === 'start' ? 'Start' : 'End'} - ${stripExtension(file.name)}`

      const character = await postAPI<Character>('/api/characters', {
        name: label,
        entity_type: 'visual_asset',
        media_id: upload.media_id,
      })
      await postAPI(`/api/projects/${created.project.id}/characters/${character.id}`, {})

      const asset: UploadedAsset = {
        label,
        mediaId: upload.media_id,
        characterId: character.id,
        entityType: 'visual_asset',
        fileName: file.name,
      }

      setUploadedAssets(current => mergeUniqueAssets([...current, asset]))
      if (kind === 'start') {
        setF2vStartAssetId(upload.media_id)
        setF2vStartFile(null)
      } else {
        setF2vEndAssetId(upload.media_id)
        setF2vEndFile(null)
      }

      await refreshCreatedResources(created)
      setMessage(`${kind === 'start' ? 'Start' : 'End'} frame uploaded and assigned to Frames.`)
    } catch (err) {
      setMessage(`${kind === 'start' ? 'Start' : 'End'} frame upload failed: ${String(err)}`)
    } finally {
      setUploading(false)
    }
  }


  async function searchCatalog() {
    setSearchingCatalog(true)
    try {
      const results = await fetchAPI<{ items: Product[] }>('/api/products/search?q=' + encodeURIComponent(catalogSearchQuery))
      setCatalogProducts(results.items || [])
    } catch (err) {
      setMessage('Catalog search failed: ' + String(err))
    } finally {
      setSearchingCatalog(false)
    }
  }

  async function applyCatalogProduct(product: any) {
    setSelectedCatalogProduct(product)
    setSelectedProductName(product.raw_product_title)
    const mapping = await resolveProductMapping({
      product_id: product.id,
      product_name: product.raw_product_title,
      source: product.source,
      category: product.category,
      subcategory: product.subcategory,
      type: product.type,
      persist: true,
    })
    if (mapping) {
      setSelectedCatalogProduct(mergeMappingIntoProduct(mapping, product))
      await fetchBrief(product.id)
    }
    try {
      const res = await fetchAPI<{ prompt: string }>('/api/products/' + product.id + '/prompt?mode=F2V')
      if (res.prompt) setManualPrompt(res.prompt)
    } catch (err) {}
    try {
      await postAPI('/api/products/' + product.id + '/resolve-assets', {})
    } catch (err) {}
  }

  async function importCatalog() {
    setImportingCatalog(true)
    try {
      const res = await postAPI<any>('/api/products/import-fastmoss', {})
      if (res.ok) {
        await loadCanonicalProducts()
        setMessage('Imported ' + res.imported + ' products.')
      }
    } catch (err) { setMessage('Import error: ' + String(err)) }
    finally { setImportingCatalog(false) }
  }

  async function fetchBrief(productId: string) {
    try {
      const res = await fetchAPI<any>(`/api/products/${productId}/creative-brief`)
      setBrief(res)
    } catch (err) {
      console.error('Failed to fetch brief', err)
      setBrief(null)
    }
  }

  async function handlePromptPreview() {
    const productId = selectedCatalogProduct?.id || resolvedMapping?.product_id
    if (!productId) return
    setPreviewLoading(true)
    try {
      const res = await postAPI<{ prompt: string }>(`/api/products/${productId}/prompt-preview`, {
        variation_index: 0,
        hook_angle: form.hook,
        scene_context: form.scene_context,
        google_flow_mode: hoveredMode || 'EDIT_IMAGE'
      })
      setPromptPreview(res.prompt)
    } catch (err) {
      setMessage(`Preview failed: ${String(err)}`)
    } finally {
      setPreviewLoading(false)
    }
  }

  async function resolveManualProduct() {
    const title = manualProductName.trim()
    if (!title) {
      setMessage('Enter a manual product name first.')
      return
    }
    const mapping = await resolveProductMapping({
      product_name: title,
      source: 'MANUAL',
      persist: true,
    })
    if (!mapping) return

    const manualProduct = mappingToOperatorProduct(mapping)
    setManualProducts(current => [manualProduct, ...current.filter(item => item.product_name !== manualProduct.product_name)])
    setSelectedCatalogProduct(mergeMappingIntoProduct(mapping))
    setSelectedProductName(manualProduct.product_name)
  }

  async function applyAdvancedOverride() {
    const title = resolvedMapping?.raw_product_title || selectedCatalogProduct?.raw_product_title || form.product_name
    if (!title) {
      setMessage('Select or resolve a product before applying overrides.')
      return
    }

    const mapping = await resolveProductMapping({
      product_id: selectedCatalogProduct?.id || undefined,
      product_name: title,
      source: selectedCatalogProduct?.source || (resolvedMapping?.mapping_source === 'manual' ? 'MANUAL' : 'FASTMOSS'),
      override_category: overrideDraft.category,
      override_subcategory: overrideDraft.subcategory,
      override_type: overrideDraft.type,
      persist: Boolean(selectedCatalogProduct?.id),
    })

    if (mapping && selectedCatalogProduct) {
      setSelectedCatalogProduct(mergeMappingIntoProduct(mapping, selectedCatalogProduct))
    }
  }

  async function submitManual(mode: 'EDIT_IMAGE' | 'GENERATE_VIDEO' | 'GENERATE_VIDEO_REFS' | 'TRUE_F2V') {
    if (!created) return
    if (!selectedSceneId) {
      setMessage('Select a target scene first.')
      return
    }

    const scene = videoScenes.find(item => item.id === selectedSceneId)
    if (!scene) {
      setMessage('Selected scene not found.')
      return
    }

    if (mode === 'TRUE_F2V') {
      if (!f2vSceneReady) {
        setMessage('Select a target scene first.')
        return
      }
      if (!f2vStartAssetId) {
        setMessage('Upload a Start Frame to Flow.')
        return
      }
      if (f2vEndAssetId && !f2vDifferentAssets) {
        setMessage('Start and End frames must be different assets.')
        return
      }
      if (!f2vResolvedPromptReady) {
        setMessage('ERROR: SYSTEM_PROMPT_MISSING. Resolved prompt is required before submit.')
        return
      }
      if (!f2vSystemPromptReady && !manualPromptOverride) {
        setMessage('Waiting for system prompt generation. Please wait a moment...')
        return
      }
      if (uploadingAssets) {
        setMessage('Wait for upload to finish.')
        return
      }
      if (uploadingF2vStart) {
        setMessage('Wait for Start Frame upload to finish.')
        return
      }
      if (uploadingF2vEnd) {
        setMessage('Wait for End Frame upload to finish.')
        return
      }
    } else if (uploadedAssets.length === 0) {
      setMessage('Upload at least one photo first.')
      return
    }

    setSubmittingManual(true)
    setMessage('')

    try {
      const scenePatch: Record<string, unknown> = {}
      const prompt = manualPromptOverride

      if (mode === 'EDIT_IMAGE' && prompt) {
        scenePatch.image_prompt = prompt
      }

      if ((mode === 'GENERATE_VIDEO' || mode === 'GENERATE_VIDEO_REFS' || mode === 'TRUE_F2V') && prompt) {
        scenePatch.video_prompt = prompt
      }

      if (mode === 'GENERATE_VIDEO') {
        if (form.orientation === 'VERTICAL') {
          scenePatch.vertical_image_media_id = uploadedAssets[0].mediaId
          scenePatch.vertical_image_status = 'COMPLETED'
        } else {
          scenePatch.horizontal_image_media_id = uploadedAssets[0].mediaId
          scenePatch.horizontal_image_status = 'COMPLETED'
        }
      }

      if (mode === 'TRUE_F2V') {
        scenePatch.video_prompt = resolvedVideoPrompt
        if (form.orientation === 'VERTICAL') {
          scenePatch.vertical_image_media_id = f2vStartAssetId
          scenePatch.vertical_image_status = 'COMPLETED'
          if (f2vEndAssetId) {
            scenePatch.vertical_end_scene_media_id = f2vEndAssetId
          } else {
            // Ensure no end frame is sent for start-only F2V
            scenePatch.vertical_end_scene_media_id = null
          }
        } else {
          scenePatch.horizontal_image_media_id = f2vStartAssetId
          scenePatch.horizontal_image_status = 'COMPLETED'
          if (f2vEndAssetId) {
            scenePatch.horizontal_end_scene_media_id = f2vEndAssetId
          } else {
            // Ensure no end frame is sent for start-only F2V
            scenePatch.horizontal_end_scene_media_id = null
          }
        }
      }

      if (mode === 'GENERATE_VIDEO_REFS') {
        const mergedNames = Array.from(new Set([
          ...(scene.character_names ?? []),
          ...uploadedAssets.map(asset => asset.label),
        ]))
        scenePatch.character_names = mergedNames
      }

      if (Object.keys(scenePatch).length > 0) {
        await patchAPI<Scene>(`/api/scenes/${scene.id}`, scenePatch)
      }

      const requestType = mode

      await postAPI('/api/requests/batch', {
        requests: [{
          type: requestType,
          project_id: created.project.id,
          video_id: created.video.id,
          scene_id: scene.id,
          orientation: form.orientation,
          ...(mode === 'EDIT_IMAGE' ? { source_media_id: uploadedAssets[0].mediaId } : {}),
        }],
      })

      setActiveBatchType(requestType)
      const status = await fetchAPI<BatchStatus>(`/api/requests/batch-status?video_id=${created.video.id}&type=${requestType}&orientation=${form.orientation}`)
      setBatchStatus(status)
      await refreshCreatedResources(created)

      const labels: Record<string, string> = {
        EDIT_IMAGE: 'Images submit sent with uploaded base photo.',
        GENERATE_VIDEO: 'Ingredients submit sent with uploaded start frame.',
        GENERATE_VIDEO_REFS: 'Frames submit sent with uploaded reference photos.',
        TRUE_F2V: f2vEndAssetId
          ? 'Frames submit sent with explicit Start and End frames.'
          : 'Frames submit sent with explicit Start frame and generated prompt.',
      }
      setMessage(labels[mode])
    } catch (err) {
      setMessage(`Manual submit failed: ${String(err)}`)
    } finally {
      setSubmittingManual(false)
    }
  }

  if (loadingPack) {
    return <div className="text-xs" style={{ color: 'var(--muted)' }}>Loading operator content pack...</div>
  }

  if (!pack) {
    return <div className="text-xs" style={{ color: 'var(--red)' }}>Operator content pack unavailable.</div>
  }

  const durationOptions = pack.durations_by_engine[form.engine_id] ?? []

  return (
    <div className="flex flex-col gap-4 max-w-5xl mx-auto p-4 sm:p-6 pb-24">
      <TelemetryDashboard summary={telemetry} />

      <DeploymentStatusCard
        agentStatus={agentStatus}
        extensionConnected={extensionConnected}
      />

      <SystemHealthPanel
        telemetry={telemetry}
        agentStatus={agentStatus}
        checkingAgent={checkingAgent}
        smokeTesting={smokeTesting}
        diagnosing={diagnosing}
        extensionConnected={extensionConnected}
        onCheckAgent={checkAgent}
        onRefreshTelemetry={() => {
          fetchAPI<TelemetrySummary>('/api/telemetry/summary').then(setTelemetry)
        }}
        onRunSelfTest={runTelemetrySelfTest}
        onRunSmokeTest={runF2VSmokeTest}
        onExportDiagnostics={exportDiagnostics}
      />

      <Card className="border-blue-500/20" style={{ background: 'linear-gradient(135deg, rgba(59,130,246,0.05), rgba(59,130,246,0.01))' }}>
        {message && (
          <div className="rounded px-3 py-2 text-xs" style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)' }}>
            {message}
          </div>
        )}
      </Card>

      <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Product Intelligence</h2>
          <button 
            onClick={importCatalog} 
            disabled={importingCatalog}
            className="text-[10px] px-2 py-0.5 rounded bg-blue-600/20 hover:bg-blue-600/40 text-blue-400 border border-blue-600/30"
          >
            {importingCatalog ? 'Importing...' : 'Sync FastMoss'}
          </button>
        </div>
        <div className="flex gap-2">
          <input
            placeholder="Search catalog (e.g. Diaper, Sumikko)..."
            value={catalogSearchQuery}
            onChange={e => setCatalogSearchQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && searchCatalog()}
            className="flex-1 px-2 py-1.5 rounded text-xs"
            style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
          />
          <button
            onClick={searchCatalog}
            disabled={searchingCatalog}
            className="px-3 py-1.5 rounded text-xs font-bold"
            style={{ background: 'var(--primary)', color: 'white' }}
          >
            {searchingCatalog ? '...' : 'Search'}
          </button>
        </div>
        <div className="grid gap-2 md:grid-cols-[1fr_auto]">
          <input
            placeholder="Manual product name for non-FastMoss mapping..."
            value={manualProductName}
            onChange={e => setManualProductName(e.target.value)}
            className="px-2 py-1.5 rounded text-xs"
            style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
          />
          <button
            onClick={resolveManualProduct}
            disabled={mappingBusy}
            className="px-3 py-1.5 rounded text-xs font-bold"
            style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
          >
            {mappingBusy ? 'Resolving...' : 'Resolve + Save Manual Product'}
          </button>
        </div>
        {catalogProducts.length > 0 && (
          <div className="flex flex-col gap-1 max-h-48 overflow-y-auto pr-1">
            {catalogProducts.map(p => (
              <div
                key={p.id}
                onClick={() => applyCatalogProduct(p)}
                className={`p-2 rounded text-xs cursor-pointer border transition-colors ${
                  selectedCatalogProduct?.id === p.id 
                    ? 'bg-blue-600/20 border-blue-600/50' 
                    : 'bg-surface/50 border-border hover:border-muted'
                }`}
              >
                <div className="font-bold flex justify-between items-center">
                  <span>{p.product_short_name}</span>
                  <span className="text-[10px] opacity-50 uppercase">{p.source}</span>
                </div>
                <div className="text-[10px] opacity-70 truncate">{p.raw_product_title}</div>
              </div>
            ))}
          </div>
        )}
      </Card>


      {selectedCatalogProduct && (
        <Card>
          <div className="flex gap-4">
            {selectedCatalogProduct.image_url && (
              <div className="w-24 h-24 rounded border overflow-hidden bg-surface flex-shrink-0">
                <img src={selectedCatalogProduct.image_url} alt="Product" className="w-full h-full object-contain" />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-bold truncate" style={{ color: 'var(--text)' }}>{selectedCatalogProduct.product_short_name}</h3>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2">
                <div className="text-[10px] opacity-60">Display Name:</div>
                <div className="text-[10px] truncate">{selectedCatalogProduct.product_display_name}</div>
                <div className="text-[10px] opacity-60">Category:</div>
                <div className="text-[10px] truncate">{selectedCatalogProduct.category}</div>
                <div className="text-[10px] opacity-60">Subcategory:</div>
                <div className="text-[10px] truncate">{selectedCatalogProduct.subcategory}</div>
                <div className="text-[10px] opacity-60">Type:</div>
                <div className="text-[10px] truncate">{selectedCatalogProduct.type}</div>
                <div className="text-[10px] opacity-60">Mapping Source:</div>
                <div className="text-[10px] font-bold text-blue-400 uppercase">{selectedCatalogProduct.mapping_source || selectedCatalogProduct.source}</div>
                <div className="text-[10px] opacity-60">Mapping Confidence:</div>
                <div className="text-[10px] truncate">{selectedCatalogProduct.mapping_confidence || '—'}</div>
                <div className="text-[10px] opacity-60">Mapping Status:</div>
                <div className="text-[10px] truncate">{selectedCatalogProduct.mapping_status || operatorPreflight?.preflight.mapping_status || '—'}</div>
              </div>
            </div>
          </div>
          <div className="mt-2 pt-2 border-t" style={{ borderTopColor: 'var(--border)' }}>
            <div className="text-[10px] font-bold opacity-50 mb-1">RAW TITLE (AUDIT):</div>
            <div className="text-[10px] opacity-70 leading-relaxed">{selectedCatalogProduct.raw_product_title}</div>
          </div>
        </Card>
      )}

      <Card>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Product Intelligence Preflight</h3>
            <div className="text-[11px]" style={{ color: 'var(--muted)' }}>
              System-owned mapping, creative, prompt, and Flow readiness evidence for the selected product.
            </div>
          </div>
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={repairSelectedProductMapping}
              disabled={!selectedProductId || repairingMapping}
              className="px-3 py-1.5 rounded text-[10px] font-bold"
              style={{ background: 'rgba(245,158,11,0.14)', color: '#fcd34d', border: '1px solid rgba(245,158,11,0.3)' }}
            >
              {repairingMapping ? 'Repairing...' : 'Repair Mapping'}
            </button>
            <button
              onClick={backfillMappings}
              disabled={backfillingMappings}
              className="px-3 py-1.5 rounded text-[10px] font-bold"
              style={{ background: 'rgba(59,130,246,0.14)', color: '#93c5fd', border: '1px solid rgba(59,130,246,0.3)' }}
            >
              {backfillingMappings ? 'Backfilling...' : 'Backfill All Mappings'}
            </button>
            <button
              onClick={runF2VSmokeTest}
              disabled={smokeTesting}
              className="px-3 py-1.5 rounded text-[10px] font-bold"
              style={{ background: 'rgba(168,85,247,0.14)', color: '#d8b4fe', border: '1px solid rgba(168,85,247,0.3)' }}
            >
              {smokeTesting ? 'Checking...' : 'Check Flow Readiness'}
            </button>
          </div>
        </div>

        {!selectedProductId ? (
          <div className="text-xs" style={{ color: 'var(--muted)' }}>
            Select or resolve a product to see exact mapping gaps, repair actions, and execution gates.
          </div>
        ) : (
          <>
            <div className="flex gap-2 flex-wrap">
              <StatBadge label={`Mapping ${preflight?.mapping_status || 'UNKNOWN'}`} tone={statusTone(preflight?.mapping_status)} />
              <StatBadge label={`Physics ${preflight?.physics_dna_status || 'UNKNOWN'}`} tone={statusTone(preflight?.physics_dna_status)} />
              <StatBadge label={`Creative ${preflight?.creative_brief_status || 'UNKNOWN'}`} tone={statusTone(preflight?.creative_brief_status)} />
              <StatBadge label={`Prompt ${preflight?.prompt_readiness_status || 'UNKNOWN'}`} tone={statusTone(preflight?.prompt_readiness_status)} />
              <StatBadge label={`Flow ${flowReadiness?.status || preflight?.flow_readiness_status || 'NOT_CHECKED'}`} tone={statusTone(flowReadiness?.status || preflight?.flow_readiness_status)} />
            </div>

            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
              <ReadOnlyField label="Mapping Missing Fields" value={formatList(preflight?.missing_fields)} />
              <ReadOnlyField label="Creative Missing Fields" value={formatList(preflight?.creative_missing_fields)} />
              <ReadOnlyField label="Prompt Missing Fields" value={formatList(preflight?.prompt_missing_fields)} />
              <ReadOnlyField label="Blocking Reason" value={flowReadiness?.primary_blocker || preflight?.blocking_reason || '—'} />
              <ReadOnlyField label="Repair Action" value={preflight?.repair_action || '—'} />
              <ReadOnlyField label="Backfill Action" value={preflight?.backfill_action || '—'} />
            </div>

            {flowReadiness && (
              <div className="grid gap-3 rounded-lg border p-3" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)' }}>
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold" style={{ color: 'var(--text)' }}>Flow Readiness Diagnostic</div>
                  {flowReadiness.primary_blocker === 'CONTENT_SCRIPT_STALE_OR_NOT_INJECTED' && (
                    <button
                      onClick={reloadFlowTabAndReinject}
                      disabled={reloadingFlowTab || smokeTesting}
                      className="px-3 py-1.5 rounded text-[10px] font-bold"
                      style={{ background: 'rgba(59,130,246,0.14)', color: '#93c5fd', border: '1px solid rgba(59,130,246,0.3)' }}
                    >
                      {reloadingFlowTab ? 'Reloading...' : 'Reload Flow Tab / Re-inject Content Script'}
                    </button>
                  )}
                </div>
                <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
                  <ReadOnlyField label="Extension Runtime" value={flowReadiness.extension_runtime} />
                  <ReadOnlyField label="Flow Tab Found" value={String(flowReadiness.flow_tab_found)} />
                  <ReadOnlyField label="Flow Tab ID" value={flowReadiness.flow_tab_id != null ? String(flowReadiness.flow_tab_id) : '—'} />
                  <ReadOnlyField label="Flow URL" value={flowReadiness.flow_url || '—'} />
                  <ReadOnlyField label="Extension Protocol" value={flowReadiness.extension_protocol_version || '—'} />
                  <ReadOnlyField label="Content Script Protocol" value={flowReadiness.content_script_protocol_version || '—'} />
                  <ReadOnlyField label="Content Script Loaded" value={String(flowReadiness.content_script_loaded)} />
                  <ReadOnlyField label="Content Script Alive" value={String(flowReadiness.content_script_alive)} />
                  <ReadOnlyField label="Last Content Script Seen" value={flowReadiness.last_content_script_seen_at || '—'} />
                  <ReadOnlyField label="Signed In Likely" value={String(flowReadiness.signed_in_likely)} />
                  <ReadOnlyField label="Composer Found" value={String(flowReadiness.composer_found)} />
                  <ReadOnlyField label="Composer Editable" value={String(flowReadiness.composer_editable)} />
                  <ReadOnlyField label="Generate Button Found" value={String(flowReadiness.generate_button_found)} />
                  <ReadOnlyField label="Current Mode Visible" value={flowReadiness.current_mode_visible} />
                  <ReadOnlyField label="Blocking Modal Detected" value={String(flowReadiness.blocking_modal_detected)} />
                  <ReadOnlyField label="Primary Blocker" value={flowReadiness.primary_blocker || '—'} />
                  <ReadOnlyField label="Last Checked At" value={flowReadiness.last_checked_at || '—'} />
                  <ReadOnlyField label="Raw Error" value={flowReadiness.raw_error || '—'} />
                </div>
                {flowReadiness.primary_blocker === 'CONTENT_SCRIPT_STALE_OR_NOT_INJECTED' && (
                  <div className="rounded px-3 py-2 text-xs" style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', color: 'var(--text)' }}>
                    CONTENT_SCRIPT_STALE_OR_NOT_INJECTED. Reload Flow Tab / Re-inject Content Script required.
                  </div>
                )}
              </div>
            )}

            {(preflight?.blocking_reason || flowReadiness?.primary_blocker) && (
              <div className="rounded px-3 py-2 text-xs" style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', color: 'var(--text)' }}>
                Buttons are gated until the visible blocker clears. No fake READY state is shown.
              </div>
            )}
          </>
        )}
      </Card>

      <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold" style={{ color: 'var(--text)' }}>BOSMAX Operator</h2>
          <span className="text-xs" style={{ color: 'var(--muted)' }}>{pack.pack_dir}</span>
        </div>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <div className="flex flex-col gap-1">
            <FieldLabel>Product</FieldLabel>
            <SearchableSelect
              options={availableProducts}
              value={selectedProductName}
              onChange={(p: any) => applyProduct(p.product_name)}
              getLabel={(p: any) => p.product_short_name || p.product_name}
              getSublabel={(p: any) => `${p.category || 'Unmapped'} | ${p.type_angle || p.sub_category || 'Needs review'}`}
            />
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Engine</FieldLabel>
            <SearchableSelect
              options={pack.engines.map(e => ({ name: e }))}
              value={form.engine_id}
              onChange={(e: any) => updateField('engine_id', e.name)}
              getLabel={(e: any) => e.name}
            />
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Duration</FieldLabel>
            <select value={form.duration_target} onChange={e => updateField('duration_target', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {durationOptions.map(duration => (
                <option key={duration} value={duration}>{duration}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Orientation</FieldLabel>
            <select value={form.orientation} onChange={e => updateField('orientation', e.target.value as Orientation)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              <option value="VERTICAL">VERTICAL</option>
              <option value="HORIZONTAL">HORIZONTAL</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Avatar</FieldLabel>
            <SearchableSelect
              options={pack.avatars.map(a => ({ name: a }))}
              value={form.avatar_id}
              onChange={(a: any) => updateField('avatar_id', a.name)}
              getLabel={(a: any) => a.name}
            />
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Headwear</FieldLabel>
            <select value={form.headwear_style} onChange={e => updateField('headwear_style', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.headwear_styles.map(item => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Camera Style</FieldLabel>
            <select value={form.camera_style} onChange={e => updateField('camera_style', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.camera_styles.map(item => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Material</FieldLabel>
            <select value={form.material} onChange={e => updateField('material', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.materials.map(item => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Target Language</FieldLabel>
            <select value={form.target_language} onChange={e => updateField('target_language', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.language_defaults.map(item => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>

        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Resolved Product Mapping</h3>
          <button
            type="button"
            onClick={() => setAdvancedOverrideOpen(current => !current)}
            className="px-2 py-1 rounded text-[10px] font-bold"
            style={{ background: advancedOverrideOpen ? 'rgba(59,130,246,0.15)' : 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
          >
            {advancedOverrideOpen ? 'Hide Advanced Override' : 'Advanced Override'}
          </button>
        </div>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <ReadOnlyField label="Product ID" value={resolvedMapping?.product_id} />
          <ReadOnlyField label="Category" value={form.category} />
          <ReadOnlyField label="Subcategory" value={form.sub_category} />
          <ReadOnlyField label="Type" value={form.type_angle} />
          <ReadOnlyField label="Product Type" value={form.product_type} />
          <ReadOnlyField label="Silo" value={form.silo_id} />
          <ReadOnlyField label="Trigger ID" value={form.trigger_id} />
          <ReadOnlyField label="Formula" value={form.submode_formula} />
          <ReadOnlyField label="Mapping Confidence" value={resolvedMapping?.mapping_confidence} />
          <ReadOnlyField label="Mapping Source" value={resolvedMapping?.mapping_source} />
          <ReadOnlyField label="Readiness" value={resolvedMapping?.prompt_readiness_status} />
          <ReadOnlyField label="Copywriting Angle" value={resolvedMapping?.copywriting_angle} />
          <ReadOnlyField label="Claim Risk" value={resolvedMapping?.claim_risk_level} />
          <ReadOnlyField label="Recommended Lanes" value={resolvedMapping?.mode_recommendations?.join(', ')} />
          <ReadOnlyField label="Physics Class" value={form.physics_class} />
          <ReadOnlyField label="Scale" value={form.product_scale} />
          <ReadOnlyField label="Fragility" value={form.fragility_level} />
          <ReadOnlyField label="Grip" value={form.recommended_grip} />
          <ReadOnlyField label="Handling Notes" value={form.camera_handling_notes} />
          <ReadOnlyField label="Hand Interact" value={form.hand_object_interaction} />
          <ReadOnlyField label="Material" value={form.material_behavior} />
          <ReadOnlyField label="Surface" value={form.surface_behavior} />
          <ReadOnlyField label="Air Gap" value={form.air_gap_rule} />
          <ReadOnlyField label="Unsafe" value={form.unsafe_handling_rules?.join('; ')} />
          <ReadOnlyField label="S5 PMT" value={form.section_5_product_physics_prompt} />
        </div>
        {resolvedMapping?.missing_fields?.length ? (
          <div className="rounded px-3 py-2 text-xs" style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)', color: 'var(--text)' }}>
            Mapping needs review for: {resolvedMapping.missing_fields.join(', ')}.
          </div>
        ) : null}
        {resolvedMapping?.prompt_missing_fields?.length ? (
          <div className="rounded px-3 py-2 text-xs" style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.25)', color: 'var(--text)' }}>
            Prompt readiness missing: {resolvedMapping.prompt_missing_fields.join(', ')}.
          </div>
        ) : null}
        {advancedOverrideOpen && (
          <div className="grid gap-3 rounded-lg border p-3" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)' }}>
            <div className="text-xs font-semibold" style={{ color: 'var(--text)' }}>Advanced Override</div>
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
              <div className="flex flex-col gap-1">
                <FieldLabel>Override Category</FieldLabel>
                <input value={overrideDraft.category} onChange={e => setOverrideDraft(current => ({ ...current, category: e.target.value }))} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              </div>
              <div className="flex flex-col gap-1">
                <FieldLabel>Override Subcategory</FieldLabel>
                <input value={overrideDraft.subcategory} onChange={e => setOverrideDraft(current => ({ ...current, subcategory: e.target.value }))} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              </div>
              <div className="flex flex-col gap-1">
                <FieldLabel>Override Type</FieldLabel>
                <input value={overrideDraft.type} onChange={e => setOverrideDraft(current => ({ ...current, type: e.target.value }))} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              </div>
            </div>
            <div className="flex justify-end">
              <button onClick={applyAdvancedOverride} disabled={mappingBusy} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
                {mappingBusy ? 'Applying...' : 'Apply Advanced Override'}
              </button>
            </div>
          </div>
        )}
        <div className="flex flex-col gap-1">
          <FieldLabel>Scene Context</FieldLabel>
          <textarea value={form.scene_context} onChange={e => updateField('scene_context', e.target.value)} rows={3} className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
        </div>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
          <div className="flex flex-col gap-1">
            <FieldLabel>Hook</FieldLabel>
            <textarea value={form.hook} onChange={e => updateField('hook', e.target.value)} rows={3} className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel>USP 1</FieldLabel>
            <textarea value={form.usp_1} onChange={e => updateField('usp_1', e.target.value)} rows={3} className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel>USP 2</FieldLabel>
            <textarea value={form.usp_2} onChange={e => updateField('usp_2', e.target.value)} rows={3} className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel>USP 3</FieldLabel>
            <textarea value={form.usp_3} onChange={e => updateField('usp_3', e.target.value)} rows={3} className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <FieldLabel>Body</FieldLabel>
          <textarea value={form.body} onChange={e => updateField('body', e.target.value)} rows={4} className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
        </div>
        <div className="flex flex-col gap-1">
          <FieldLabel>CTA</FieldLabel>
          <textarea value={form.cta} onChange={e => updateField('cta', e.target.value)} rows={2} className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
        </div>
        <div className="flex gap-3 flex-wrap">
          <button onClick={buildBlueprint} disabled={building || blueprintBlocked} className="px-4 py-2 rounded text-xs font-semibold" style={{ background: blueprintBlocked ? 'var(--border)' : 'var(--accent)', color: blueprintBlocked ? 'var(--muted)' : '#fff', border: '1px solid var(--accent)' }}>
            {building ? 'Building...' : 'Build Blueprint'}
          </button>
          <button onClick={createProjectFromBlueprint} disabled={!blueprint || creating || blueprintBlocked} className="px-4 py-2 rounded text-xs font-semibold" style={{ background: !blueprint || blueprintBlocked ? 'var(--border)' : 'rgba(34,197,94,0.2)', color: !blueprint || blueprintBlocked ? 'var(--muted)' : 'var(--green)', border: '1px solid var(--border)' }}>
            {creating ? 'Creating...' : 'Create Project'}
          </button>
        </div>
        {blueprintBlocked && (
          <div className="rounded px-3 py-2 text-xs" style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', color: 'var(--text)' }}>
            Build/Create blocked: {flowReadiness?.primary_blocker || preflight?.blocking_reason || 'Selected product is not ready.'}
          </div>
        )}
      </Card>

      {blueprint && (
        <Card>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Blueprint Preview</h3>
          <div className="text-xs" style={{ color: 'var(--muted)' }}>
            {(blueprint.project.name as string) || 'Unnamed project'}
          </div>
          <div className="text-xs whitespace-pre-wrap" style={{ color: 'var(--text)' }}>
            {(blueprint.project.story as string) || ''}
          </div>
          <div className="grid gap-3">
            {blueprint.scenes.map(scene => (
              <div key={scene.display_order} className="rounded p-3" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                <div className="text-xs font-bold mb-1" style={{ color: 'var(--accent)' }}>
                  Scene {scene.display_order + 1}
                </div>
                <div className="text-xs" style={{ color: 'var(--text)' }}>{scene.prompt}</div>
                <div className="text-xs mt-2" style={{ color: 'var(--muted)' }}>{scene.video_prompt}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Generation Controls</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="flex flex-col gap-1">
            <FieldLabel>Active Project</FieldLabel>
            <SearchableSelect
              options={allProjects}
              value={created?.project.id || ''}
              onChange={selectProject}
              getLabel={(p: Project) => p.name}
              getSublabel={(p: Project) => p.id}
              placeholder="Select a historical project..."
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel>Active Video</FieldLabel>
            <SearchableSelect
              options={allVideos}
              value={created?.video.id || ''}
              onChange={selectVideo}
              getLabel={(v: Video) => v.title}
              getSublabel={(v: Video) => v.id}
              placeholder="Select a video..."
            />
          </div>
        </div>
        <div className="rounded p-3 text-xs grid gap-1" style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--muted)' }}>
          <div style={{ color: 'var(--text)' }}>Operator lane status</div>
          <div>Supported now: `Images`, `Ingredients`, `Frames`, `Text to Video`.</div>
          <div>Direct Text to Video is visible for naming completeness but remains NOT WIRED / NOT NATIVE.</div>
          <div>Do not confuse `Ingredients` with true `Frames` start-plus-end frame generation.</div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => queueRequests('GENERATE_CHARACTER_IMAGE')} disabled={!created || queueing || executionBlocked} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: !created || queueing || executionBlocked ? 'var(--muted)' : 'var(--text)', border: '1px solid var(--border)' }}>
            Generate Ingredients
          </button>
          <button onClick={() => queueRequests('GENERATE_IMAGE')} disabled={!created || queueing || executionBlocked} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: !created || queueing || executionBlocked ? 'var(--muted)' : 'var(--text)', border: '1px solid var(--border)' }}>
            Generate Images
          </button>
          <button onClick={() => queueRequests('GENERATE_VIDEO')} disabled={!created || queueing || executionBlocked} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: !created || queueing || executionBlocked ? 'var(--muted)' : 'var(--text)', border: '1px solid var(--border)' }}>
            Generate Ingredients
          </button>
          <button onClick={() => queueRequests('GENERATE_VIDEO_REFS')} disabled={!created || queueing || executionBlocked} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: !created || queueing || executionBlocked ? 'var(--muted)' : 'var(--text)', border: '1px solid var(--border)' }}>
            Generate Frames
          </button>
          <button disabled className="px-3 py-2 rounded text-xs font-semibold opacity-70 cursor-not-allowed" style={{ background: 'var(--surface)', color: 'var(--muted)', border: '1px solid var(--border)' }}>
            Generate Text to Video — NOT WIRED
          </button>
          <button onClick={() => queueRequests('UPSCALE_VIDEO')} disabled={!created || queueing || executionBlocked} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: !created || queueing || executionBlocked ? 'var(--muted)' : 'var(--text)', border: '1px solid var(--border)' }}>
            Upscale
          </button>
        </div>
        {executionBlocked && (
          <div className="rounded px-3 py-2 text-xs" style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', color: 'var(--text)' }}>
            Execute blocked: {flowReadiness?.primary_blocker || preflight?.blocking_reason || 'Selected product is not ready.'}
          </div>
        )}
        <div className="text-xs" style={{ color: 'var(--muted)' }}>
          T2V in this repo is not a native single-shot queue type. The verified path here is prompt to image to video.
        </div>
        {batchStatus && (
          <div className="grid gap-2 text-xs" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
            <div style={{ color: 'var(--text)' }}>Type: {activeBatchType}</div>
            <div style={{ color: 'var(--text)' }}>Total: {batchStatus.total}</div>
            <div style={{ color: 'var(--text)' }}>Pending: {batchStatus.pending}</div>
            <div style={{ color: 'var(--text)' }}>Processing: {batchStatus.processing}</div>
            <div style={{ color: 'var(--text)' }}>Completed: {batchStatus.completed}</div>
            <div style={{ color: 'var(--text)' }}>Failed: {batchStatus.failed}</div>
          </div>
        )}
      </Card>

      <OperatorManual
        created={created}
        selectedSceneId={selectedSceneId}
        uploadedAssets={uploadedAssets}
        manualPrompt={manualPrompt}
        resolvedVideoPromptReady={resolvedVideoPrompt.trim().length > 0}
        submittingManual={submittingManual}
        uploadingAssets={uploadingAssets}
        backendConnected={backendConnected}
        extensionConnected={extensionConnected || false}
      />

      <Card>
        <div className="flex items-center justify-between gap-3">

          <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Manual Upload and Submit</h3>
          <span className="text-xs" style={{ color: 'var(--muted)' }}>
            Images uses uploaded base photo, Ingredients uses the first uploaded start frame, Frames uses explicit start and end assets.
          </span>
        </div>

        {!created ? (
          <div className="text-xs" style={{ color: 'var(--muted)' }}>
            Create a project first. Then this panel will expose photo upload plus submit buttons for Images, Ingredients, and Frames.
          </div>
        ) : (
          <>
            <div className="rounded p-3 text-xs grid gap-1" style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--muted)' }}>
              <div>Supported here: `Generate Images`, `Generate Ingredients`, `Generate Frames`, `Generate Text to Video — NOT WIRED`.</div>
              <div>`Frames` requires explicit selection of Start and End frame assets from your uploads.</div>
            </div>
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
              <div className="flex flex-col gap-1">
                <FieldLabel>Target Scene</FieldLabel>
                <SearchableSelect
                  options={videoScenes}
                  value={selectedSceneId}
                  onChange={(s: any) => setSelectedSceneId(s.id)}
                  getLabel={(s: any) => `Scene ${s.display_order + 1} - ${s.prompt || s.video_prompt || 'Untitled'}`}
                  getSublabel={(s: any) => s.video_prompt || s.prompt}
                />
              </div>

              <div className="flex flex-col gap-1">
                <FieldLabel>Asset Type</FieldLabel>
                <select value={manualEntityType} onChange={e => setManualEntityType(e.target.value as ManualEntityType)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
                  <option value="visual_asset">visual_asset</option>
                  <option value="character">character</option>
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <FieldLabel>Asset Label</FieldLabel>
                <input value={manualAssetName} onChange={e => setManualAssetName(e.target.value)} placeholder="Optional override for single upload" className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              </div>
            </div>

              <div className="flex flex-col gap-1">
                <FieldLabel>Upload Photo</FieldLabel>
                <div className="text-[10px] mb-1" style={{ color: 'var(--accent)' }}>
                  <b>Step 1:</b> Choose a file. <b>Step 2:</b> Click "Upload Photo to Flow".<br />
                  Only uploaded assets appear in Start/End dropdowns.
                </div>
                <input type="file" accept="image/*" multiple onChange={e => setManualFiles(Array.from(e.target.files ?? []))} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                <div className="text-xs" style={{ color: 'var(--muted)' }}>
                  {manualFiles.length > 0
                    ? `${manualFiles.length} file selected: ${manualFiles.map(file => file.name).join(', ')}`
                    : 'Choose one photo for Images/Ingredients or multiple photos for manual reference uploads.'}
                </div>
              </div>

            <div className="flex flex-col gap-1">
              <FieldLabel>Prompt Override (optional)</FieldLabel>
              <textarea value={manualPrompt} onChange={e => setManualPrompt(e.target.value)} rows={3} placeholder="Optional prompt override for the selected scene." className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              <div className="rounded p-2 text-[10px]" style={{ background: 'rgba(15,23,42,0.35)', border: '1px solid var(--border)', color: 'var(--muted)' }}>
                {systemVideoPrompt.trim().length > 0 ? (
                  <>
                    <div className="font-bold" style={{ color: 'var(--text)' }}>System-generated prompt used when override is empty:</div>
                    <div className="mt-1 whitespace-pre-wrap" style={{ color: 'var(--muted)' }}>{systemVideoPrompt}</div>
                  </>
                ) : (
                  <div style={{ color: 'var(--red)' }}>Generated scene prompt missing. Enter a prompt override.</div>
                )}
              </div>
            </div>

            {brief && (
              <div className="p-3 rounded border grid gap-2 text-[11px]" style={{ background: 'rgba(34,197,94,0.03)', border: '1px solid rgba(34,197,94,0.15)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-green-500"></div>
                    <span className="font-bold text-xs uppercase tracking-wider" style={{ color: 'var(--green)' }}>Product Creative Brief Readiness</span>
                  </div>
                  <StatBadge label={brief.missing_fields.length === 0 ? 'READY' : 'NEEDS_REVIEW'} tone={brief.missing_fields.length === 0 ? 'ready' : 'risk'} />
                </div>
                <div className="grid grid-cols-2 gap-2 opacity-90">
                  {Object.entries(brief.readiness).map(([k, v]) => (
                    <div key={k} className="flex justify-between items-center px-2 py-1 bg-black/20 rounded">
                       <span style={{ color: 'var(--muted)' }}>{k}</span>
                       <span className={v === 'READY' ? 'text-green-400' : 'text-red-400'}>{v as string}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex flex-col gap-2">
              <div className="flex justify-between items-center">
                <FieldLabel>Runtime Verification</FieldLabel>
                <button
                  onClick={handlePromptPreview}
                  disabled={previewLoading || !brief}
                  className="text-[10px] font-bold text-blue-400 hover:text-blue-300 transition-colors uppercase tracking-widest flex items-center gap-1"
                >
                  {previewLoading ? 'Compiling...' : 'Preview 9-Section Prompt'}
                  <span className="text-[8px]">▶</span>
                </button>
              </div>
              {promptPreview && (
                <div className="mb-2 p-3 rounded bg-slate-950 border border-blue-500/30 font-mono text-[10px] text-blue-100 whitespace-pre-wrap select-all max-h-40 overflow-y-auto">
                  {promptPreview}
                </div>
              )}
              <FlowRuntimePlan
                mode={hoveredMode || 'EDIT_IMAGE'}
                orientation={form.orientation}
                prompt={resolvedVideoPrompt}
                startAsset={uploadedAssets[0]?.label}
                promptSource={manualPromptOverride ? 'Manual override' : 'System-generated product prompt'}
              />
            </div>

            <div className="flex gap-2 flex-wrap" onMouseLeave={() => setHoveredMode(null)}>
              <button 
                onMouseEnter={() => setHoveredMode('EDIT_IMAGE')}
                onClick={uploadManualAssets} 
                disabled={uploadingAssets || manualFiles.length === 0} 
                className="px-3 py-2 rounded text-xs font-semibold transition-all hover:scale-[1.02]" 
                style={{ background: 'var(--accent)', color: '#fff', border: '1px solid var(--accent)' }}
              >
                {uploadingAssets ? 'Uploading...' : 'Upload Photo to Flow'}
              </button>
              <button 
                onMouseEnter={() => setHoveredMode('EDIT_IMAGE')}
                onClick={() => submitManual('EDIT_IMAGE')} 
                disabled={submittingManual || uploadedAssets.length === 0 || !selectedSceneId} 
                className="px-3 py-2 rounded text-xs font-semibold transition-all hover:scale-[1.02]" 
                style={{ background: 'rgba(59,130,246,0.14)', color: 'var(--accent)', border: '1px solid var(--border)' }}
              >
                Generate Images
              </button>
              <button 
                onMouseEnter={() => setHoveredMode('GENERATE_VIDEO')}
                onClick={() => submitManual('GENERATE_VIDEO')} 
                disabled={submittingManual || uploadedAssets.length === 0 || !selectedSceneId} 
                className="px-3 py-2 rounded text-xs font-semibold transition-all hover:scale-[1.02]" 
                style={{ background: 'rgba(34,197,94,0.14)', color: 'var(--green)', border: '1px solid var(--border)' }}
              >
                Generate Ingredients
              </button>
              <button 
                onMouseEnter={() => setHoveredMode('GENERATE_VIDEO_REFS')}
                onClick={() => submitManual('GENERATE_VIDEO_REFS')} 
                disabled={submittingManual || uploadedAssets.length === 0 || !selectedSceneId} 
                className="px-3 py-2 rounded text-xs font-semibold transition-all hover:scale-[1.02]" 
                style={{ background: 'rgba(245,158,11,0.14)', color: 'var(--yellow)', border: '1px solid var(--border)' }}
              >
                Generate Frames
              </button>
            </div>

            <div className="rounded p-3 flex flex-col gap-3" style={{ background: 'rgba(168,85,247,0.05)', border: '1px solid rgba(168,85,247,0.2)' }}>
              <div className="flex items-center justify-between">
                <div className="text-xs font-bold" style={{ color: 'var(--accent)' }}>Frames / Start Frame + Optional End Frame</div>
                <div className="text-[10px]" style={{ color: 'var(--muted)' }}>
                  End Frame is optional in this lane.
                </div>
              </div>
                <div className="text-[10px]" style={{ color: 'var(--accent)' }}>
                  Frames uses one required image and one optional control frame:
                  <ol className="list-decimal ml-4 mt-1">
                    <li>Upload Start Frame.</li>
                    <li>Optional: Upload End Frame for last-frame control.</li>
                    <li>Review the generated scene prompt or add an override.</li>
                    <li>Generate Frames.</li>
                  </ol>
                </div>
              <div className="text-[10px]" style={{ color: 'var(--muted)' }}>
                Uploaded assets available for selection: {uploadedAssets.length}
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-2 p-2 rounded" style={{ background: 'rgba(0,0,0,0.1)', border: '1px solid var(--border)' }}>
                  <FieldLabel>Start Frame</FieldLabel>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={e => setF2vStartFile(e.target.files?.[0] ?? null)}
                    className="text-[10px]"
                  />
                  <button
                    onClick={() => uploadSingleF2vFrame('start')}
                    disabled={!f2vStartFile || uploadingF2vStart}
                    className="px-2 py-1 rounded text-[10px] font-bold"
                    style={{ background: 'var(--accent)', color: '#fff' }}
                  >
                    {uploadingF2vStart ? 'Uploading...' : 'Upload Start Frame to Flow'}
                  </button>
                  <div className="text-[10px]" style={{ color: f2vStartAssetId ? 'var(--green)' : 'var(--muted)' }}>
                    Status: {uploadingF2vStart ? 'Uploading...' : f2vStartAssetId ? 'Uploaded' : f2vStartFile ? 'Selected' : 'Not selected'}
                  </div>
                  <div className="flex flex-col gap-1 mt-1 border-t pt-1 border-gray-700">
                    <FieldLabel>Or select uploaded Start asset</FieldLabel>
                    <SearchableSelect
                      options={uploadedAssets}
                      value={f2vStartAssetId}
                      onChange={(a: any) => setF2vStartAssetId(a.mediaId)}
                      getLabel={(a: any) => a.label}
                      getSublabel={(a: any) => a.fileName}
                      placeholder="Choose existing..."
                      maxHeight="180px"
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-2 p-2 rounded" style={{ background: 'rgba(0,0,0,0.1)', border: '1px solid var(--border)' }}>
                  <FieldLabel>End Frame (optional)</FieldLabel>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={e => setF2vEndFile(e.target.files?.[0] ?? null)}
                    className="text-[10px]"
                  />
                  <button
                    onClick={() => uploadSingleF2vFrame('end')}
                    disabled={!f2vEndFile || uploadingF2vEnd}
                    className="px-2 py-1 rounded text-[10px] font-bold"
                    style={{ background: 'var(--accent)', color: '#fff' }}
                  >
                    {uploadingF2vEnd ? 'Uploading...' : 'Upload End Frame to Flow'}
                  </button>
                  <div className="text-[10px]" style={{ color: f2vEndAssetId ? 'var(--green)' : 'var(--muted)' }}>
                    Status: {uploadingF2vEnd ? 'Uploading...' : f2vEndAssetId ? 'Uploaded' : f2vEndFile ? 'Selected' : 'Not selected'}
                  </div>
                  <div className="flex flex-col gap-1 mt-1 border-t pt-1 border-gray-700">
                    <FieldLabel>Or select uploaded End asset</FieldLabel>
                    <SearchableSelect
                      options={uploadedAssets}
                      value={f2vEndAssetId}
                      onChange={(a: any) => setF2vEndAssetId(a.mediaId)}
                      getLabel={(a: any) => a.label}
                      getSublabel={(a: any) => a.fileName}
                      placeholder="Choose existing..."
                      maxHeight="180px"
                    />
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <FieldLabel>Runtime Verification</FieldLabel>
                <FlowRuntimePlan
                  mode="TRUE_F2V"
                  orientation={form.orientation}
                  prompt={resolvedVideoPrompt}
                  startAsset={uploadedAssets.find(a => a.mediaId === f2vStartAssetId)?.label}
                  endAsset={uploadedAssets.find(a => a.mediaId === f2vEndAssetId)?.label}
                  promptSource={manualPromptOverride ? 'Manual override' : 'System-generated product prompt'}
                />
              </div>

              <div className="flex flex-col gap-2 p-2 rounded border-2" style={{ background: 'rgba(34,197,94,0.04)', borderColor: f2vSystemPromptReady ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)' }}>
                <div className="flex items-center justify-between">
                  <FieldLabel>System Generated Prompt</FieldLabel>
                  <div className={`text-[9px] font-bold px-2 py-0.5 rounded ${f2vSystemPromptReady ? 'bg-green-600/20 text-green-400' : 'bg-red-600/20 text-red-400'}`}>
                    {f2vSystemPromptReady ? 'READY' : (generatingPrompt ? 'GENERATING...' : 'MISSING')}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[10px]">
                  <div>
                    <div style={{ color: 'var(--muted)' }}>Source:</div>
                    <div className="font-mono">{promptSource}</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--muted)' }}>Length:</div>
                    <div className="font-mono">{resolvedVideoPrompt.length} chars</div>
                  </div>
                </div>
                <div className="p-2 rounded text-[10px] leading-tight max-h-24 overflow-y-auto font-mono whitespace-pre-wrap" style={{ background: 'rgba(0,0,0,0.2)', color: systemVideoPrompt ? 'var(--green)' : 'var(--muted)', border: `1px solid ${systemVideoPrompt ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}` }}>
                  {systemVideoPrompt || '(System prompt will be generated when you select a product)'}
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <FieldLabel>Optional User Override Prompt</FieldLabel>
                <input
                  type="text"
                  placeholder="Leave empty to use system-generated prompt..."
                  value={manualPrompt}
                  onChange={e => setManualPrompt(e.target.value)}
                  className="px-2 py-1 rounded text-xs"
                  style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
                />
                {manualPrompt.trim() && (
                  <div className="mt-1 p-2 rounded text-[10px] italic" style={{ background: 'rgba(245,158,11,0.05)', border: '1px dashed var(--yellow)', color: 'var(--yellow)' }}>
                    <strong>Override Active:</strong> Using your manual prompt instead of system-generated one.
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-2">
                {f2vBlockingReasons.length > 0 || f2vAdvisoryReasons.length > 0 ? (
                  <div className="flex flex-wrap gap-x-3 gap-y-1">
                    {f2vBlockingReasons.map((reason, i) => (
                      <div key={i} className="text-[10px] flex items-center gap-1" style={{ color: 'var(--red)' }}>
                        <span className="w-1 h-1 rounded-full" style={{ background: 'var(--red)' }}></span>
                        {reason}
                      </div>
                    ))}
                    {f2vAdvisoryReasons.map((reason, i) => (
                      <div key={`advisory-${i}`} className="text-[10px] flex items-center gap-1" style={{ color: 'var(--yellow)' }}>
                        <span className="w-1 h-1 rounded-full" style={{ background: 'var(--yellow)' }}></span>
                        {reason}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[10px] font-bold" style={{ color: 'var(--green)' }}>
                    Frames ready: Start frame and resolved prompt are set.
                  </div>
                )}

                <button onClick={() => submitManual('TRUE_F2V')} disabled={!f2vReady} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: !f2vReady ? 'var(--border)' : 'rgba(168,85,247,0.14)', color: !f2vReady ? 'var(--muted)' : 'var(--accent)', border: `1px solid ${!f2vReady ? 'var(--border)' : 'rgba(168,85,247,0.4)'}` }}>
                  Generate Frames
                </button>
              </div>
            </div>

            <div className="text-xs" style={{ color: 'var(--muted)' }}>
              Existing project refs linked here: {projectCharacters.map(character => character.name).join(', ') || 'none'}
            </div>
          </>
        )}
      </Card>

      <Card className="mt-4 border-accent/20" style={{ background: 'rgba(59,130,246,0.02)' }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Recent Automation Results</h3>
            {telemetry && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/20 text-blue-400 border border-blue-800/30 font-mono">
                {telemetry.processing > 0 ? `WORKING ON ${telemetry.processing} JOBS` : 'SYSTEM IDLE'}
              </span>
            )}
          </div>
          <span className="text-[10px]" style={{ color: 'var(--muted)' }}>Latest telemetry snapshot</span>
        </div>
        
        <div className="grid gap-4 max-h-[600px] overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-muted">
          {recentRequests.length === 0 ? (
            <div className="text-xs italic text-center py-8" style={{ color: 'var(--muted)' }}>No historical telemetry found for this project.</div>
          ) : (
            recentRequests.map(req => (
              <div key={req.id} className="p-3 rounded border transition-all hover:border-accent/30" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700">{req.type}</span>
                    <span className="text-[10px] font-mono" style={{ color: 'var(--muted)' }}>{req.id.slice(0, 8)}</span>
                    <span className="text-[10px]" style={{ color: 'var(--muted)' }}>{new Date(req.created_at || '').toLocaleTimeString()}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {req.status === 'COMPLETED' && <span className="text-[10px] text-green-400 font-bold border-b border-green-900/50">COMPLETED</span>}
                    {req.status === 'FAILED' && <span className="text-[10px] text-red-400 font-bold border-b border-red-900/50">FAILED</span>}
                    {req.status === 'PROCESSING' && <span className="text-[10px] text-blue-400 font-bold animate-pulse">FLOW RUNNING</span>}
                    {req.status === 'PENDING' && <span className="text-[10px] text-gray-400 font-bold">QUEUED</span>}
                  </div>
                </div>
                
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2 p-2 rounded bg-black/10 border border-white/5">
                  <div className="flex flex-col">
                    <span className="text-[8px] uppercase opacity-50">Elapsed</span>
                    <span className="text-[10px] font-mono">
                      {req.started_at && req.completed_at 
                        ? `${Math.round((new Date(req.completed_at).getTime() - new Date(req.started_at).getTime()) / 1000)}s`
                        : req.started_at 
                          ? `${Math.round((Date.now() - new Date(req.started_at).getTime()) / 1000)}s`
                          : '-'}
                    </span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[8px] uppercase opacity-50">Idle Time</span>
                    <span className="text-[10px] font-mono text-yellow-500/80">
                      {req.queued_at && req.started_at 
                        ? `${Math.round((new Date(req.started_at).getTime() - new Date(req.queued_at).getTime()) / 1000)}s`
                        : '-'}
                    </span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[8px] uppercase opacity-50">Worker Stage</span>
                    <span className="text-[10px] font-bold text-blue-300 truncate">{req.worker_stage || 'PENDING'}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[8px] uppercase opacity-50">Heartbeat</span>
                    <span className="text-[10px] font-mono truncate">
                      {req.last_heartbeat_at ? new Date(req.last_heartbeat_at).toLocaleTimeString() : 'NONE'}
                    </span>
                  </div>
                </div>

                <div className="text-[10px] mb-2" style={{ color: 'var(--muted)' }}>
                  <div className="flex items-center justify-between">
                    <span>Scene: <span className="font-mono text-text">{req.scene_id?.slice(0, 8)}...</span></span>
                  </div>
                  {req.error_message && (
                    <div className="mt-2 p-2 rounded bg-red-900/10 border border-red-900/20 text-red-400 font-bold italic text-[9px] whitespace-pre-wrap">
                      FAILURE: {req.error_message}
                    </div>
                  )}
                </div>

                <AutomationReport reportJson={req.automation_report} />
              </div>
            ))
          )}
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Pack Notes</h3>
        <div className="grid gap-2">
          {pack.notes.map(note => (
            <div key={note} className="text-xs" style={{ color: 'var(--muted)' }}>{note}</div>
          ))}
        </div>
      </Card>
    </div>
  )
}
