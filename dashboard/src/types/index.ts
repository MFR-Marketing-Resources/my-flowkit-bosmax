// Enums
export type RequestType = 'GENERATE_IMAGE' | 'REGENERATE_IMAGE' | 'EDIT_IMAGE' | 'GENERATE_VIDEO' | 'REGENERATE_VIDEO' | 'GENERATE_VIDEO_REFS' | 'TRUE_F2V' | 'UPSCALE_VIDEO' | 'GENERATE_CHARACTER_IMAGE' | 'REGENERATE_CHARACTER_IMAGE' | 'EDIT_CHARACTER_IMAGE'
export type StatusType = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
export type Orientation = 'VERTICAL' | 'HORIZONTAL'
export type ChainType = 'ROOT' | 'CONTINUATION' | 'INSERT'
export type EntityType = 'character' | 'location' | 'creature' | 'visual_asset' | 'generic_troop' | 'faction'
export type ProjectStatus = 'ACTIVE' | 'ARCHIVED' | 'DELETED'

// Models — match the Python models exactly
export interface Project {
  id: string
  name: string
  description: string | null
  story: string | null
  thumbnail_url: string | null
  language: string
  status: ProjectStatus
  user_paygate_tier: string | null
  material: string
  narrator_voice: string | null
  narrator_ref_audio: string | null
  created_at: string
  updated_at: string
}

export interface Character {
  id: string
  name: string
  entity_type: EntityType
  description: string | null
  image_prompt: string | null
  voice_description: string | null
  reference_image_url: string | null
  media_id: string | null
  created_at: string
  updated_at: string
}

export interface Video {
  id: string
  project_id: string
  title: string
  description: string | null
  display_order: number
  status: string
  vertical_url: string | null
  horizontal_url: string | null
  thumbnail_url: string | null
  duration: number | null
  resolution: string | null
  created_at: string
  updated_at: string
}

export interface Scene {
  id: string
  video_id: string
  display_order: number
  prompt: string | null
  image_prompt: string | null
  video_prompt: string | null
  character_names: string | null  // JSON string array
  parent_scene_id: string | null
  chain_type: ChainType
  source: string | null
  vertical_image_url: string | null
  vertical_image_media_id: string | null
  vertical_image_status: StatusType
  vertical_video_url: string | null
  vertical_video_media_id: string | null
  vertical_video_status: StatusType
  vertical_upscale_url: string | null
  vertical_upscale_media_id: string | null
  vertical_upscale_status: StatusType
  horizontal_image_url: string | null
  horizontal_image_media_id: string | null
  horizontal_image_status: StatusType
  horizontal_video_url: string | null
  horizontal_video_media_id: string | null
  horizontal_video_status: StatusType
  horizontal_upscale_url: string | null
  horizontal_upscale_media_id: string | null
  horizontal_upscale_status: StatusType
  narrator_text: string | null
  trim_start: number | null
  trim_end: number | null
  duration: number | null
  created_at: string
  updated_at: string
}

export interface Request {
  id: string
  project_id: string | null
  video_id: string | null
  scene_id: string | null
  character_id: string | null
  type: RequestType
  orientation: Orientation | null
  status: StatusType
  request_id: string | null
  media_id: string | null
  output_url: string | null
  error_message: string | null
  automation_report: string | null
  retry_count: number
  worker_stage: string | null
  last_heartbeat_at: string | null
  queued_at: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

// WebSocket event
export interface WSHealthData {
  status: string
  extension_connected: boolean
}

export interface WSSnapshotData {
  health: WSHealthData
  requests: Request[]
  worker: {
    active: number
    slots: number
  }
}

export interface WSEvent {
  type: 'health' | 'snapshot' | 'request_created' | 'request_updated' | 'ping' | string
  data: WSHealthData | WSSnapshotData | Request | Record<string, unknown>
  timestamp: string
}

export interface OperatorProduct {
  product_id?: string | null
  product_name: string
  raw_product_title?: string | null
  product_short_name: string | null
  product_display_name: string | null
  category: string
  sub_category: string
  type_angle: string
  product_type?: string | null
  silo_id?: string | null
  trigger_id?: string | null
  submode_formula?: string | null
  mode_recommendations?: string[]
  copywriting_angle?: string | null
  claim_risk_level?: string | null
  mapping_source?: string | null
  mapping_confidence?: string | null
  missing_fields?: string[]
  raw_category: string | null
  avg_price_rm: number | null
  status: string | null
  copy_angle: string | null
  hook: string | null
  usp_1: string | null
  usp_2: string | null
  usp_3: string | null
  body: string | null
  cta: string | null
  shop_name: string | null
}

export interface WorkbookSummary {
  workbook: string
  sheets: string[]
}

export interface ContentPackSummary {
  pack_dir: string
  available: boolean
  files: string[]
  engines: string[]
  durations_by_engine: Record<string, string[]>
  avatars: string[]
  headwear_styles: string[]
  camera_styles: string[]
  product_types: string[]
  triggers: string[]
  silos: string[]
  formulas: string[]
  materials: string[]
  language_defaults: string[]
  products: OperatorProduct[]
  workbooks: WorkbookSummary[]
  notes: string[]
}

export interface BlueprintScene {
  display_order: number
  prompt: string
  image_prompt: string
  video_prompt: string
  character_names: string[]
  chain_type: ChainType
}

export interface BlueprintResponse {
  project: Record<string, unknown>
  video: Record<string, unknown>
  scenes: BlueprintScene[]
  notes: string[]
}

export interface BatchStatus {
  total: number
  pending: number
  processing: number
  completed: number
  failed: number
  done: boolean
  all_succeeded: boolean
  orientation: Orientation | null
}

export interface CreatedState {
  project: Project
  video: Video
}

export type ManualEntityType = 'character' | 'visual_asset'

export interface UploadedAsset {
  label: string
  mediaId: string
  characterId: string
  entityType: ManualEntityType
  fileName: string
}

export interface Product {
  id: string
  product_id?: string
  source: 'FASTMOSS' | 'TIKTOKSHOP' | 'MANUAL' | 'IMPORTED'
  source_url?: string | null
  brand?: string | null
  raw_product_title: string
  product_display_name: string
  product_short_name: string
  category: string | null
  subcategory: string | null
  type: string | null
  price?: number | null
  currency?: string | null
  commission_amount?: number | null
  commission_rate?: string | null
  product_type?: string | null
  silo?: string | null
  trigger_id?: string | null
  formula?: string | null
  mode_recommendations?: string[]
  copywriting_angle?: string | null
  claim_risk_level?: string | null
  mapping_source?: 'FASTMOSS' | 'MANUAL' | 'FALLBACK' | null
  mapping_confidence?: 'HIGH' | 'MEDIUM' | 'LOW' | 'NEEDS_REVIEW' | null
  mapping_review_status?: string | null
  prompt_readiness_status?: 'READY' | 'NEEDS_REVIEW' | 'MISSING_FIELDS' | null
  prompt_missing_fields?: string[]
  physics_dna_status?: 'READY' | 'MISSING_FIELDS' | null
  physics_class?: string | null
  product_scale?: string | null
  hand_object_interaction?: string | null
  recommended_grip?: string | null
  air_gap_rule?: string | null
  material_behavior?: string | null
  surface_behavior?: string | null
  fragility_level?: string | null
  camera_handling_notes?: string | null
  unsafe_handling_rules?: string[]
  section_4_visual_action_prompt?: string | null
  section_5_product_physics_prompt?: string | null
  section_6_dialogue_prompt?: string | null
  section_9_overlay_prompt?: string | null
  missing_fields?: string[]
  notes?: string[]
  shop_name: string | null
  price_min: number | null
  price_max: number | null
  commission: string | null
  image_url: string | null
  tiktok_product_url: string | null
  fastmoss_source_file: string | null
  image_asset_status?: string | null
  image_failure_detail?: string | null
  image_readiness_status?: 'IMAGE_READY' | 'IMAGE_NOT_AVAILABLE' | 'IMAGE_DOWNLOAD_FAILED' | 'IMAGE_URL_MISSING' | 'IMAGE_URL_MISSING_FROM_SOURCE' | 'IMAGE_CACHE_READY' | null
  image_readiness_detail?: string | null
  mode_readiness?: Record<string, {
    status: string
    detail: string
    missing_fields: string[]
    asset_strategy?: string
  }>
  asset_status: 'UNRESOLVED' | 'DOWNLOADED' | 'UPLOADED_TO_FLOW'
  media_id: string | null
  local_image_path: string | null
  created_at: string
  updated_at: string
}

export interface ProductMapping {
  product_id: string
  raw_product_title: string
  product_short_name: string
  category: string
  subcategory: string
  type: string
  product_type: string
  silo: string
  trigger_id: string
  formula: string
  mode_recommendations: string[]
  copywriting_angle: string
  claim_risk_level: string
  mapping_source: 'FASTMOSS' | 'MANUAL' | 'FALLBACK'
  mapping_confidence: 'HIGH' | 'MEDIUM' | 'LOW' | 'NEEDS_REVIEW'
  mapping_review_status?: string
  prompt_readiness_status?: 'READY' | 'NEEDS_REVIEW' | 'MISSING_FIELDS'
  prompt_missing_fields?: string[]
  physics_class?: string
  product_scale?: string
  hand_object_interaction?: string
  recommended_grip?: string
  air_gap_rule?: string
  material_behavior?: string
  surface_behavior?: string
  fragility_level?: string
  camera_handling_notes?: string
  unsafe_handling_rules?: string[]
  section_4_visual_action_prompt?: string
  section_5_product_physics_prompt?: string
  section_6_dialogue_prompt?: string
  section_9_overlay_prompt?: string
  missing_fields: string[]
  notes: string[]
}

export interface LocalAgentRegistration {
  operator_id: string | null
  device_id: string
  approval_status: string
  license_status: string
  registered_at: string | null
  updated_at: string
}

export interface LocalAgentStatus {
  task_name: string
  health_url: string
  dashboard_url: string
  dashboard_serving_mode: string
  repair_command: string
  extension_connected: boolean
  extension_state: string
  offline_reason: string | null
  auto_start_enabled: boolean
  last_health_check: string | null
  license_status: string
  approval_status: string
  registration: LocalAgentRegistration
}

export interface TelemetrySummary {
  total_today: number
  queued: number
  processing: number
  waiting_flow: number
  flow_running: number
  completed: number
  failed: number
  last_job_status: string
  last_stage: string
  last_error: string
  idle_seconds: number
}

export interface TelemetryRequest {
  request_id: string
  project_id: string | null
  video_id: string | null
  scene_id: string | null
  product_id: string | null
  request_type: RequestType | string | null
  mode: string | null
  status: string
  google_flow_stage: string | null
  extension_stage: string | null
  worker_stage: string | null
  queued_at: string | null
  started_at: string | null
  last_heartbeat_at: string | null
  completed_at: string | null
  failed_at: string | null
  duration_seconds: number | null
  idle_seconds: number | null
  processing_seconds: number | null
  error_code: string | null
  error_message: string | null
  created_at: string
}
