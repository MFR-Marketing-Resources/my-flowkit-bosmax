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

  const { isConnected: backendConnected, extensionConnected } = useWebSocketContext()

  // True F2V Readiness Rules
  const f2vPromptReady = manualPrompt.trim().length > 0
  const f2vStartReady = !!f2vStartAssetId
  const f2vEndReady = !!f2vEndAssetId
  const f2vDifferentAssets = f2vStartAssetId && f2vEndAssetId && f2vStartAssetId !== f2vEndAssetId
  const f2vSceneReady = !!selectedSceneId
  const f2vReady =
    f2vSceneReady &&
    f2vStartReady &&
    f2vEndReady &&
    f2vPromptReady &&
    f2vDifferentAssets &&
    !submittingManual &&
    !uploadingAssets

  const f2vBlockingReasons = []
  if (uploadedAssets.length < 2) f2vBlockingReasons.push('Upload at least two photos to Flow.')
  if (!f2vSceneReady) f2vBlockingReasons.push('Select a target scene.')
  if (!f2vStartReady) f2vBlockingReasons.push('Select a Start Frame asset.')
  if (!f2vEndReady) f2vBlockingReasons.push('Select an End Frame asset.')
  if (f2vStartReady && f2vEndReady && !f2vDifferentAssets) f2vBlockingReasons.push('Start and End frames must be different assets.')
  if (!f2vPromptReady) f2vBlockingReasons.push('Enter a transition prompt.')
  if (uploadingAssets) f2vBlockingReasons.push('Wait for upload to finish.')
  if (submittingManual) f2vBlockingReasons.push('Submission already running.')



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
      if (!f2vStartAssetId || !f2vEndAssetId) {
        setMessage('Select both Start and End assets for True F2V.')
        return
      }
      if (!f2vDifferentAssets) {
        setMessage('Start and End frames must be different assets.')
        return
      }
      if (!f2vPromptReady) {
        setMessage('Enter a transition prompt for True F2V.')
        return
      }
      if (uploadingAssets) {
        setMessage('Wait for upload to finish.')
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
      const prompt = manualPrompt.trim()

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
        if (form.orientation === 'VERTICAL') {
          scenePatch.vertical_image_media_id = f2vStartAssetId
          scenePatch.vertical_image_status = 'COMPLETED'
          scenePatch.vertical_end_scene_media_id = f2vEndAssetId
        } else {
          scenePatch.horizontal_image_media_id = f2vStartAssetId
          scenePatch.horizontal_image_status = 'COMPLETED'
          scenePatch.horizontal_end_scene_media_id = f2vEndAssetId
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
        TRUE_F2V: 'True F2V submit sent with explicit Start and End frames.',
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
          <h2 className="text-sm font-bold" style={{ color: 'var(--text)' }}>BOSMAX Operator</h2>
          <span className="text-xs" style={{ color: 'var(--muted)' }}>{pack.pack_dir}</span>
        </div>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <div className="flex flex-col gap-1">
            <FieldLabel>Product</FieldLabel>
            <select value={selectedProductName} onChange={e => applyProduct(e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.products.map(product => (
                <option key={product.product_name} value={product.product_name}>{product.product_name}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel>Engine</FieldLabel>
            <select value={form.engine_id} onChange={e => updateField('engine_id', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.engines.map(engine => (
                <option key={engine} value={engine}>{engine}</option>
              ))}
            </select>
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
            <select value={form.avatar_id} onChange={e => updateField('avatar_id', e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
              {pack.avatars.map(avatar => (
                <option key={avatar} value={avatar}>{avatar}</option>
              ))}
            </select>
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
                <select value={selectedSceneId} onChange={e => setSelectedSceneId(e.target.value)} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
                  {videoScenes.map(scene => (
                    <option key={scene.id} value={scene.id}>
                      {`Scene ${scene.display_order + 1} - ${scene.prompt ?? scene.video_prompt ?? 'Untitled'}`}
                    </option>
                  ))}
                </select>
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
              <FieldLabel>Submit Prompt Override</FieldLabel>
              <textarea value={manualPrompt} onChange={e => setManualPrompt(e.target.value)} rows={3} placeholder="Optional prompt override for the selected scene." className="px-2 py-1.5 rounded text-xs resize-y" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
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
                <div className="text-xs font-bold" style={{ color: 'var(--accent)' }}>True F2V / Start + End Frames</div>
                <div className="text-[10px]" style={{ color: 'var(--muted)' }}>
                  Use I2V for start-frame-only video.
                </div>
              </div>
              <div className="text-[10px]" style={{ color: 'var(--muted)' }}>
                True F2V requires two different uploaded assets and a transition prompt.
              </div>
              <div className="text-[10px]" style={{ color: 'var(--accent)' }}>
                Uploaded assets available for F2V: {uploadedAssets.length}
              </div>
              {uploadedAssets.length < 2 && (
                <div className="text-[10px] font-bold" style={{ color: 'var(--yellow)' }}>
                  Upload at least two photos to Flow before using True F2V.
                  Chosen files are not available until "Upload Photo to Flow" is clicked.
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <FieldLabel>Start Frame Asset</FieldLabel>
                  <select value={f2vStartAssetId} onChange={e => setF2vStartAssetId(e.target.value)} disabled={uploadedAssets.length === 0} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)', opacity: uploadedAssets.length === 0 ? 0.5 : 1 }}>
                    <option value="">Select start asset...</option>
                    {uploadedAssets.map(asset => (
                      <option key={asset.mediaId} value={asset.mediaId}>{asset.label}</option>
                    ))}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <FieldLabel>End Frame Asset</FieldLabel>
                  <select value={f2vEndAssetId} onChange={e => setF2vEndAssetId(e.target.value)} disabled={uploadedAssets.length === 0} className="px-2 py-1.5 rounded text-xs" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)', opacity: uploadedAssets.length === 0 ? 0.5 : 1 }}>
                    <option value="">Select end asset...</option>
                    {uploadedAssets.map(asset => (
                      <option key={asset.mediaId} value={asset.mediaId}>{asset.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                {f2vBlockingReasons.length > 0 ? (
                  <div className="flex flex-wrap gap-x-3 gap-y-1">
                    {f2vBlockingReasons.map((reason, i) => (
                      <div key={i} className="text-[10px] flex items-center gap-1" style={{ color: 'var(--red)' }}>
                        <span className="w-1 h-1 rounded-full" style={{ background: 'var(--red)' }}></span>
                        {reason}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[10px] font-bold" style={{ color: 'var(--green)' }}>
                    True F2V ready: Start + End frames and transition prompt are set.
                  </div>
                )}

                <button onClick={() => submitManual('TRUE_F2V')} disabled={!f2vReady} className="px-3 py-2 rounded text-xs font-semibold" style={{ background: !f2vReady ? 'var(--border)' : 'rgba(168,85,247,0.14)', color: !f2vReady ? 'var(--muted)' : 'var(--accent)', border: `1px solid ${!f2vReady ? 'var(--border)' : 'rgba(168,85,247,0.4)'}` }}>
                  Submit True F2V / Start + End Frames
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
