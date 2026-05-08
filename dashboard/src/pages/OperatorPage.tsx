import { useEffect, useState, type ReactNode } from 'react'
import { fetchAPI, patchAPI, postAPI } from '../api/client'
import type {
  BatchStatus,
  BlueprintResponse,
  Character,
  ContentPackSummary,
  Orientation,
  Project,
  Scene,
  Video,
  CreatedState,
  UploadedAsset,
  ManualEntityType,
  Product,
} from '../types'
import { useWebSocketContext } from '../contexts/WebSocketContext'
import OperatorManual from '../components/operator/OperatorManual'




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
  cta: string
  material: string
  orientation: Orientation
}



type UploadImageBase64Response = {
  media_id: string
}

const emptyForm: OperatorForm = {
  product_name: '',
  category: '',
  sub_category: '',
  type_angle: '',
  product_type: 'STEALTH',
  target_language: 'Malay',
  duration_target: '8s',
  engine_id: 'VEO_3_1',
  avatar_id: '',
  headwear_style: 'AUTO',
  camera_style: 'UGC_IPHONE_RAW',
  scene_context: '',
  trigger_id: '',
  silo_id: '',
  submode_formula: 'PAS',
  hook: '',
  usp_1: '',
  usp_2: '',
  usp_3: '',
  body: '',
  cta: '',
  material: 'realistic',
  orientation: 'VERTICAL',
}

function FieldLabel({ children }: { children: string }) {
  return <label className="text-xs font-bold" style={{ color: 'var(--muted)' }}>{children}</label>
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


function Card({ children }: { children: ReactNode }) {
  return (
    <section
      className="rounded-lg p-4 flex flex-col gap-3"
      style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
    >
      {children}
    </section>
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
  const [f2vStartAssetId, setF2vStartAssetId] = useState('')
  const [f2vEndAssetId, setF2vEndAssetId] = useState('')
  const [f2vStartFile, setF2vStartFile] = useState<File | null>(null)
  const [f2vEndFile, setF2vEndFile] = useState<File | null>(null)
  const [uploadingF2vStart, setUploadingF2vStart] = useState(false)
  const [uploadingF2vEnd, setUploadingF2vEnd] = useState(false)
  const [catalogProducts, setCatalogProducts] = useState<Product[]>([])
  const [selectedCatalogProduct, setSelectedCatalogProduct] = useState<Product | null>(null)
  const [catalogSearchQuery, setCatalogSearchQuery] = useState('')
  const [searchingCatalog, setSearchingCatalog] = useState(false)
  const [importingCatalog, setImportingCatalog] = useState(false)

  const { isConnected: backendConnected, extensionConnected } = useWebSocketContext()
  const selectedScene = videoScenes.find(item => item.id === selectedSceneId)
  const systemVideoPrompt = selectedScene?.video_prompt || selectedScene?.prompt || ''
  const manualPromptOverride = manualPrompt.trim()
  const resolvedVideoPrompt = manualPromptOverride || systemVideoPrompt

  // True F2V Readiness Rules
  const f2vResolvedPromptReady = resolvedVideoPrompt.trim().length > 0
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
  if (!f2vResolvedPromptReady) f2vBlockingReasons.push('Generated scene prompt missing. Enter a prompt override.')
  if (uploadingAssets) f2vBlockingReasons.push('Wait for upload to finish.')
  if (uploadingF2vStart) f2vBlockingReasons.push('Wait for Start Frame upload to finish.')
  if (uploadingF2vEnd) f2vBlockingReasons.push('Wait for End Frame upload to finish.')
  if (submittingManual) f2vBlockingReasons.push('Submission already running.')

  if (!f2vEndReady) f2vAdvisoryReasons.push('End Frame is optional. Use it only if you want last-frame control.')



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
          product_type: data.product_types[0] ?? emptyForm.product_type,
          trigger_id: data.triggers[0] ?? '',
          silo_id: data.silos[0] ?? '',
          submode_formula: data.formulas[0] ?? emptyForm.submode_formula,
          target_language: data.language_defaults[0] ?? emptyForm.target_language,
          material: data.materials[0] ?? emptyForm.material,
          product_name: firstProduct?.product_name ?? '',
          category: firstProduct?.category ?? '',
          sub_category: firstProduct?.sub_category ?? '',
          type_angle: firstProduct?.type_angle ?? '',
          hook: firstProduct?.hook ?? '',
          usp_1: firstProduct?.usp_1 ?? '',
          usp_2: firstProduct?.usp_2 ?? '',
          usp_3: firstProduct?.usp_3 ?? '',
          body: firstProduct?.body ?? '',
          cta: firstProduct?.cta ?? '',
          scene_context: firstProduct ? `${firstProduct.category} environment with ${firstProduct.type_angle}` : '',
        })
        setSelectedProductName(firstProduct?.product_name ?? '')
      })
      .catch(err => setMessage(`Failed to load content pack: ${String(err)}`))
      .finally(() => setLoadingPack(false))
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
    if (!created) {
      setProjectCharacters([])
      setVideoScenes([])
      setSelectedSceneId('')
      setUploadedAssets([])
      return
    }
    void refreshCreatedResources(created)
  }, [created])

  function updateField<K extends keyof OperatorForm>(field: K, value: OperatorForm[K]) {
    setForm(current => ({ ...current, [field]: value }))
  }

  function applyProduct(productName: string) {
    setSelectedProductName(productName)
    const product = pack?.products.find(item => item.product_name === productName)
    if (!product) return
    setForm(current => ({
      ...current,
      product_name: product.product_name,
      category: product.category,
      sub_category: product.sub_category,
      type_angle: product.type_angle,
      hook: product.hook ?? '',
      usp_1: product.usp_1 ?? '',
      usp_2: product.usp_2 ?? '',
      usp_3: product.usp_3 ?? '',
      body: product.body ?? '',
      cta: product.cta ?? '',
      scene_context: `${product.category} environment with ${product.type_angle}`,
    }))
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

  async function buildBlueprint() {
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
        GENERATE_VIDEO: 'I2V queue submitted.',
        GENERATE_VIDEO_REFS: 'Ingredients / Refs to Video queue submitted.',
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
      setMessage(`${kind === 'start' ? 'Start' : 'End'} frame uploaded and assigned to True F2V.`)
    } catch (err) {
      setMessage(`${kind === 'start' ? 'Start' : 'End'} frame upload failed: ${String(err)}`)
    } finally {
      setUploading(false)
    }
  }


  async function searchCatalog() {
    setSearchingCatalog(true)
    try {
      const results = await fetchAPI<any[]>('/api/products/search?q=' + encodeURIComponent(catalogSearchQuery))
      setCatalogProducts(results)
    } catch (err) {
      setMessage('Catalog search failed: ' + String(err))
    } finally {
      setSearchingCatalog(false)
    }
  }

  async function applyCatalogProduct(product: any) {
    setSelectedCatalogProduct(product)
    setForm(current => ({
      ...current,
      product_name: product.product_short_name,
      category: product.category || current.category,
      sub_category: product.subcategory || current.sub_category,
      scene_context: product.raw_product_title,
    }))
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
      if (res.ok) setMessage('Imported ' + res.imported + ' products.')
    } catch (err) { setMessage('Import error: ' + String(err)) }
    finally { setImportingCatalog(false) }
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
        setMessage('Generated scene prompt missing. Enter a prompt override.')
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

      const requestType = mode === 'TRUE_F2V' ? 'GENERATE_VIDEO' : mode

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
        EDIT_IMAGE: 'IMG / Edit Image submit sent with uploaded base photo.',
        GENERATE_VIDEO: 'I2V submit sent with uploaded start frame.',
        GENERATE_VIDEO_REFS: 'Ingredients / Refs to Video submit sent with uploaded reference photos.',
        TRUE_F2V: f2vEndAssetId
          ? 'True F2V submit sent with explicit Start and End frames.'
          : 'True F2V submit sent with explicit Start frame and generated prompt.',
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
    <div className="flex flex-col gap-4">
      {message && (
        <div className="rounded px-3 py-2 text-xs" style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)' }}>
          {message}
        </div>
      )}


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
                <div className="text-[10px] opacity-60">Source:</div>
                <div className="text-[10px] font-bold text-blue-400 uppercase">{selectedCatalogProduct.source}</div>
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
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold" style={{ color: 'var(--text)' }}>BOSMAX Operator</h2>
          <span className="text-xs" style={{ color: 'var(--muted)' }}>{pack.pack_dir}</span>
        </div>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <div className="flex flex-col gap-1">
            <FieldLabel>Product</FieldLabel>
            <SearchableSelect
              options={pack.products}
              value={selectedProductName}
              onChange={(p: any) => applyProduct(p.product_name)}
              getLabel={(p: any) => p.product_short_name || p.product_name}
              getSublabel={(p: any) => p.category + ' | ' + p.type_angle}
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
            <FieldLabel>Product Type</FieldLabel>
            <select value={form.product_type} onChange={e => updateField('product_type', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.product_types.map(item => (
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

          <div className="flex flex-col gap-1">
            <FieldLabel>Silo</FieldLabel>
            <select value={form.silo_id} onChange={e => updateField('silo_id', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.silos.map(item => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Trigger</FieldLabel>
            <select value={form.trigger_id} onChange={e => updateField('trigger_id', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.triggers.map(item => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Formula</FieldLabel>
            <select value={form.submode_formula} onChange={e => updateField('submode_formula', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.formulas.map(item => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-bold" style={{ color: 'var(--text)' }}>Campaign Inputs</h3>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
          <div className="flex flex-col gap-1">
            <FieldLabel>Category</FieldLabel>
            <input value={form.category} onChange={e => updateField('category', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel>Sub Category</FieldLabel>
            <input value={form.sub_category} onChange={e => updateField('sub_category', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel>Type Angle</FieldLabel>
            <input value={form.type_angle} onChange={e => updateField('type_angle', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
          </div>
        </div>
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
          <button onClick={buildBlueprint} disabled={building} className="px-4 py-2 rounded text-xs font-semibold" style={{ background: 'var(--accent)', color: '#fff', border: '1px solid var(--accent)' }}>
            {building ? 'Building...' : 'Build Blueprint'}
          </button>
          <button onClick={createProjectFromBlueprint} disabled={!blueprint || creating} className="px-4 py-2 rounded text-xs font-semibold" style={{ background: !blueprint ? 'var(--border)' : 'rgba(34,197,94,0.2)', color: !blueprint ? 'var(--muted)' : 'var(--green)', border: '1px solid var(--border)' }}>
            {creating ? 'Creating...' : 'Create Project'}
          </button>
        </div>
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
        <div className="text-xs" style={{ color: 'var(--muted)' }}>
          {created
            ? `Active project: ${created.project.name} | video: ${created.video.title}`
            : 'Create a project from the blueprint before queueing generation.'}
        </div>
        <div className="rounded p-3 text-xs grid gap-1" style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--muted)' }}>
          <div style={{ color: 'var(--text)' }}>Operator lane status</div>
          <div>Supported now: `IMG / Edit Image`, `I2V / Start Image to Video`, `Ingredients / Refs to Video`, `True F2V / Start + End Frames`.</div>
          <div>Direct T2V: NOT WIRED / NOT NATIVE.</div>
          <div>Do not confuse `Ingredients / Refs to Video` with true `F2V` start-plus-end frame generation.</div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => queueRequests('GENERATE_CHARACTER_IMAGE')} disabled={!created || queueing} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
            Generate Ingredients / Refs
          </button>
          <button onClick={() => queueRequests('GENERATE_IMAGE')} disabled={!created || queueing} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
            Generate Images
          </button>
          <button onClick={() => queueRequests('GENERATE_VIDEO')} disabled={!created || queueing} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
            Generate Videos (I2V Start Image)
          </button>
          <button onClick={() => queueRequests('GENERATE_VIDEO_REFS')} disabled={!created || queueing} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
            Generate Videos (Ingredients / Refs)
          </button>
          <button onClick={() => queueRequests('UPSCALE_VIDEO')} disabled={!created || queueing} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
            Upscale
          </button>
        </div>
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
            IMG uses uploaded base photo, I2V uses the first uploaded start frame, Ingredients / Refs uses uploaded reference photos.
          </span>
        </div>

        {!created ? (
          <div className="text-xs" style={{ color: 'var(--muted)' }}>
            Create a project first. Then this panel will expose photo upload plus submit buttons for IMG, I2V, and Ingredients / Refs to Video.
          </div>
        ) : (
          <>
            <div className="rounded p-3 text-xs grid gap-1" style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--muted)' }}>
              <div>Supported here: `Submit IMG`, `Submit I2V`, `Submit Ingredients / Refs`, `Submit True F2V`.</div>
              <div>`True F2V` requires explicit selection of Start and End frame assets from your uploads.</div>
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
                    : 'Choose one photo for IMG/I2V or multiple photos for Ingredients / Refs to Video.'}
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

            <div className="flex gap-2 flex-wrap">
              <button onClick={uploadManualAssets} disabled={uploadingAssets || manualFiles.length === 0} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'var(--accent)', color: '#fff', border: '1px solid var(--accent)' }}>
                {uploadingAssets ? 'Uploading...' : 'Upload Photo to Flow'}
              </button>
              <button onClick={() => submitManual('EDIT_IMAGE')} disabled={submittingManual || uploadedAssets.length === 0 || !selectedSceneId} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'rgba(59,130,246,0.14)', color: 'var(--accent)', border: '1px solid var(--border)' }}>
                Submit IMG / Edit Image
              </button>
              <button onClick={() => submitManual('GENERATE_VIDEO')} disabled={submittingManual || uploadedAssets.length === 0 || !selectedSceneId} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'rgba(34,197,94,0.14)', color: 'var(--green)', border: '1px solid var(--border)' }}>
                Submit I2V - Start Image to Video
              </button>
              <button onClick={() => submitManual('GENERATE_VIDEO_REFS')} disabled={submittingManual || uploadedAssets.length === 0 || !selectedSceneId} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: 'rgba(245,158,11,0.14)', color: 'var(--yellow)', border: '1px solid var(--border)' }}>
                Submit Ingredients / Refs to Video
              </button>
            </div>

            <div className="rounded p-3 flex flex-col gap-3" style={{ background: 'rgba(168,85,247,0.05)', border: '1px solid rgba(168,85,247,0.2)' }}>
              <div className="flex items-center justify-between">
                <div className="text-xs font-bold" style={{ color: 'var(--accent)' }}>True F2V / Start Frame + Optional End Frame</div>
                <div className="text-[10px]" style={{ color: 'var(--muted)' }}>
                  End Frame is optional in this lane.
                </div>
              </div>
                <div className="text-[10px]" style={{ color: 'var(--accent)' }}>
                  True F2V uses one required image and one optional control frame:
                  <ol className="list-decimal ml-4 mt-1">
                    <li>Upload Start Frame.</li>
                    <li>Optional: Upload End Frame for last-frame control.</li>
                    <li>Review the generated scene prompt or add an override.</li>
                    <li>Submit True F2V.</li>
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

              <div className="flex flex-col gap-1">
                <FieldLabel>Prompt Override (Optional)</FieldLabel>
                <input
                  type="text"
                  placeholder="Leave empty to use system scene prompt..."
                  value={manualPrompt}
                  onChange={e => setManualPrompt(e.target.value)}
                  className="px-2 py-1 rounded text-xs"
                  style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}
                />
                <div className="mt-1 p-2 rounded text-[10px] italic" style={{ background: 'rgba(59,130,246,0.05)', border: '1px dashed var(--blue)', color: 'var(--blue)' }}>
                  <strong>Resolved Prompt:</strong> {manualPrompt.trim() ? manualPrompt : (resolvedVideoPrompt || 'Waiting for scene...')}
                </div>
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
                    True F2V ready: Start frame and resolved prompt are set.
                  </div>
                )}

                <button onClick={() => submitManual('TRUE_F2V')} disabled={!f2vReady} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: !f2vReady ? 'var(--border)' : 'rgba(168,85,247,0.14)', color: !f2vReady ? 'var(--muted)' : 'var(--accent)', border: `1px solid ${!f2vReady ? 'var(--border)' : 'rgba(168,85,247,0.4)'}` }}>
                  Submit True F2V / Start Frame + Optional End
                </button>
              </div>
            </div>

            <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
              {uploadedAssets.length === 0 ? (
                <div className="text-xs" style={{ color: 'var(--muted)' }}>No uploaded assets yet.</div>
              ) : uploadedAssets.map(asset => (
                <div key={asset.mediaId} className="rounded p-3 text-xs" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                  <div style={{ color: 'var(--text)' }}>{asset.label}</div>
                  <div style={{ color: 'var(--muted)' }}>{asset.entityType}</div>
                  <div style={{ color: 'var(--accent)' }}>{asset.mediaId}</div>
                </div>
              ))}
            </div>

            <div className="text-xs" style={{ color: 'var(--muted)' }}>
              Existing project refs linked here: {projectCharacters.map(character => character.name).join(', ') || 'none'}
            </div>
          </>
        )}
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
