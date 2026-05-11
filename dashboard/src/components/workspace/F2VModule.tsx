import { useState, useEffect, type ChangeEvent } from 'react'
import { Upload, ArrowRight, Info, LoaderCircle, CircleAlert, CircleCheckBig } from 'lucide-react'
import { fetchAPI, patchAPI, postAPI } from '../../api/client'
import { useWebSocketContext } from '../../contexts/WebSocketContext'
import type { Product, UploadedAsset, Orientation, Project, Video, Scene, Request } from '../../types'

type LocalUploadedAsset = UploadedAsset & {
  file: File
  previewUrl: string
}

interface ActiveProjectInfo {
  project_id: string | null
  project_name: string | null
  video_id: string | null
  orientation?: string | null
  material?: string | null
  status?: string | null
  source: string
}

interface FlowUploadResponse {
  media_id: string
}

interface GeneratedPromptResponse {
  prompt: string
}

const WORKSPACE_VIDEO_TITLE = 'BOSMAX F2V Workspace'

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result)
        return
      }
      reject(new Error('Could not read image data.'))
    }
    reader.onerror = () => reject(reader.error ?? new Error('Could not read image data.'))
    reader.readAsDataURL(file)
  })
}

function buildWorkspaceProjectName(product: Product | null): string {
  const shortName = product?.product_short_name?.trim() || product?.product_display_name?.trim() || 'Workspace'
  return `BOSMAX F2V ${shortName}`
}

interface F2VModuleProps {
  onExecute: (data: any) => void
  isExecuting: boolean
}

export default function F2VModule({ onExecute, isExecuting }: F2VModuleProps) {
  const { extensionConnected } = useWebSocketContext()
  const [products, setProducts] = useState<Product[]>([])
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null)
  const [prompt, setPrompt] = useState('')
  const [orientation, setOrientation] = useState<Orientation>('VERTICAL')
  const [model, setModel] = useState('Veo 3.1 - Pro')
  const [startAsset, setStartAsset] = useState<LocalUploadedAsset | null>(null)
  const [endAsset, setEndAsset] = useState<LocalUploadedAsset | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [statusMessage, setStatusMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [lastRequest, setLastRequest] = useState<Request | null>(null)

  useEffect(() => {
    fetchAPI<{ items: Product[] }>('/api/products?limit=50').then(res => {
      setProducts(res.items)
    })
  }, [])

  useEffect(() => {
    if (!selectedProduct || prompt.trim()) {
      return
    }

    let cancelled = false
    fetchAPI<GeneratedPromptResponse>(`/api/products/${selectedProduct.id}/prompt?mode=TRUE_F2V`)
      .then((res) => {
        if (!cancelled && res.prompt) {
          setPrompt(res.prompt)
        }
      })
      .catch(() => {})

    return () => {
      cancelled = true
    }
  }, [selectedProduct, prompt])

  useEffect(() => {
    return () => {
      if (startAsset?.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(startAsset.previewUrl)
      }
      if (endAsset?.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(endAsset.previewUrl)
      }
    }
  }, [startAsset, endAsset])

  const buildLocalAsset = async (file: File, label: string, currentAsset: LocalUploadedAsset | null): Promise<LocalUploadedAsset> => {
    if (!file.type.startsWith('image/')) {
      throw new Error('Only image files are supported for F2V slots.')
    }

    if (currentAsset?.previewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(currentAsset.previewUrl)
    }

    return {
      label,
      mediaId: '',
      characterId: '',
      entityType: 'visual_asset',
      fileName: file.name,
      file,
      previewUrl: URL.createObjectURL(file),
    }
  }

  const handleStartUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) {
      return
    }

    try {
      setErrorMessage(null)
      setStatusMessage('')
      setStartAsset(await buildLocalAsset(file, 'Start Frame', startAsset))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to load the start frame.')
    } finally {
      event.target.value = ''
    }
  }

  const handleEndUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) {
      return
    }

    try {
      setErrorMessage(null)
      setStatusMessage('')
      setEndAsset(await buildLocalAsset(file, 'End Frame', endAsset))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to load the end frame.')
    } finally {
      event.target.value = ''
    }
  }

  const uploadAssetToFlow = async (asset: LocalUploadedAsset, projectId: string): Promise<LocalUploadedAsset> => {
    if (asset.mediaId) {
      return asset
    }

    const imageBase64 = await readFileAsDataUrl(asset.file)
    const upload = await postAPI<FlowUploadResponse>('/api/flow/upload-image-base64', {
      image_base64: imageBase64,
      mime_type: asset.file.type || 'image/png',
      project_id: projectId,
      file_name: asset.fileName,
    })

    return {
      ...asset,
      mediaId: upload.media_id,
    }
  }

  const ensureWorkspaceContext = async () => {
    const active = await fetchAPI<ActiveProjectInfo>('/api/active-project')

    let project: Project
    if (active.project_id) {
      project = await fetchAPI<Project>(`/api/projects/${active.project_id}`)
    } else {
      project = await postAPI<Project>('/api/projects', {
        name: buildWorkspaceProjectName(selectedProduct),
        description: 'Auto-created by the BOSMAX V4 Frames workspace.',
        material: 'realistic',
      })

      await fetchAPI<ActiveProjectInfo>('/api/active-project', {
        method: 'PUT',
        body: JSON.stringify({ project_id: project.id }),
      })
    }

    const videos = await fetchAPI<Video[]>(`/api/videos?project_id=${project.id}`)
    let video = videos.find((item) => item.title === WORKSPACE_VIDEO_TITLE)

    if (!video) {
      video = await postAPI<Video>('/api/videos', {
        project_id: project.id,
        title: WORKSPACE_VIDEO_TITLE,
        description: 'Dedicated BOSMAX F2V workspace video lane.',
        orientation,
      })
    }

    const scenes = await fetchAPI<Scene[]>(`/api/scenes?video_id=${video.id}`)
    let scene = scenes[0]

    if (!scene) {
      scene = await postAPI<Scene>('/api/scenes', {
        video_id: video.id,
        display_order: 0,
        prompt: prompt.trim() || 'Generate a premium frames-to-video sequence.',
        video_prompt: prompt.trim() || 'Generate a premium frames-to-video sequence.',
        transition_prompt: prompt.trim() || 'Generate a premium frames-to-video sequence.',
        source: 'user',
      })
    }

    return { project, video, scene }
  }

  const waitForRequest = async (requestId: string): Promise<Request> => {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const current = await fetchAPI<Request>(`/api/requests/${requestId}`)
      setLastRequest(current)

      if (current.status === 'COMPLETED' || current.status === 'FAILED') {
        return current
      }

      await new Promise((resolve) => window.setTimeout(resolve, 2500))
    }

    throw new Error('Timed out while waiting for the Flow worker to finish.')
  }

  const handleExecute = async () => {
    if (!prompt.trim() || !startAsset) {
      return
    }

    setIsSubmitting(true)
    setErrorMessage(null)
    setStatusMessage('Resolving workspace context...')
    setLastRequest(null)

    try {
      const { project, video, scene } = await ensureWorkspaceContext()

      setStatusMessage('Uploading start frame to Google Flow...')
      const uploadedStartAsset = await uploadAssetToFlow(startAsset, project.id)
      setStartAsset(uploadedStartAsset)

      let uploadedEndAsset: LocalUploadedAsset | null = null
      if (endAsset) {
        setStatusMessage('Uploading end frame to Google Flow...')
        uploadedEndAsset = await uploadAssetToFlow(endAsset, project.id)
        setEndAsset(uploadedEndAsset)
      }

      const prefix = orientation === 'VERTICAL' ? 'vertical' : 'horizontal'
      const updatedScene = await patchAPI<Scene>(`/api/scenes/${scene.id}`, {
        prompt: prompt.trim(),
        video_prompt: prompt.trim(),
        transition_prompt: prompt.trim(),
        [`${prefix}_image_media_id`]: uploadedStartAsset.mediaId,
        [`${prefix}_image_status`]: 'COMPLETED',
        [`${prefix}_video_media_id`]: null,
        [`${prefix}_video_url`]: null,
        [`${prefix}_video_status`]: 'PENDING',
        [`${prefix}_upscale_media_id`]: null,
        [`${prefix}_upscale_url`]: null,
        [`${prefix}_upscale_status`]: 'PENDING',
        [`${prefix}_end_scene_media_id`]: uploadedEndAsset?.mediaId ?? null,
      })

      setStatusMessage('Queueing BOSMAX TRUE_F2V job...')
      const request = await postAPI<Request>('/api/requests', {
        type: 'TRUE_F2V',
        orientation,
        project_id: project.id,
        video_id: video.id,
        scene_id: updatedScene.id,
      })

      setLastRequest(request)
      onExecute({
        requestId: request.id,
        projectId: project.id,
        videoId: video.id,
        sceneId: updatedScene.id,
        productId: selectedProduct?.id ?? null,
        prompt,
        orientation,
        model,
        startAsset: uploadedStartAsset,
        endAsset: uploadedEndAsset,
      })

      setStatusMessage(`Request ${request.id.slice(0, 8)} queued. Waiting for worker result...`)
      const finalRequest = await waitForRequest(request.id)

      if (finalRequest.status === 'FAILED') {
        throw new Error(finalRequest.error_message || 'Flow worker failed to complete the F2V request.')
      }

      setStatusMessage(`F2V request ${finalRequest.id.slice(0, 8)} completed successfully.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to execute the F2V workflow.')
      setStatusMessage('')
    } finally {
      setIsSubmitting(false)
    }
  }

  const isBusy = isExecuting || isSubmitting

  return (
    <div className="flex h-full gap-6">
      {/* Main Workspace */}
      <div className="flex-1 space-y-6 overflow-y-auto pr-2">
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">1. Reference Product</h3>
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40">
            <select 
              aria-label="Reference product"
              title="Reference product"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 text-sm text-slate-200 outline-none focus:border-blue-500 transition-colors"
              value={selectedProduct?.id || ''}
              onChange={(e) => {
                const p = products.find(p => p.id === e.target.value)
                setSelectedProduct(p || null)
              }}
            >
              <option value="">Select a product from catalog...</option>
              {products.map(p => (
                <option key={p.id} value={p.id}>{p.raw_product_title}</option>
              ))}
            </select>
          </div>
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">2. Visual Assets (F2V Slots)</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="group relative aspect-[9/16] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
               {startAsset ? (
                 <img src={startAsset.previewUrl} alt="Start frame preview" className="w-full h-full object-cover" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-xs font-bold text-slate-500 group-hover:text-slate-300">Start Frame</span>
                 </>
               )}
               <input type="file" accept="image/*" aria-label="Upload start frame" title="Upload start frame" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleStartUpload} />
            </div>

            <div className="group relative aspect-[9/16] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
               {endAsset ? (
                 <img src={endAsset.previewUrl} alt="End frame preview" className="w-full h-full object-cover" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-xs font-bold text-slate-500 group-hover:text-slate-300">End Frame (Optional)</span>
                 </>
               )}
               <input type="file" accept="image/*" aria-label="Upload end frame" title="Upload end frame" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleEndUpload} />
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">3. Prompt Injection (9-Section DNA)</h3>
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            <textarea 
              className="w-full h-48 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
              placeholder="Paste your professional prompt here..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <div className="flex items-center gap-2 text-[10px] text-slate-500 italic">
              <Info size={12} />
              <span>Ensure your prompt follows the F2V Frames mode requirements for best results.</span>
            </div>
          </div>
        </section>

        {(statusMessage || errorMessage || lastRequest || !extensionConnected) && (
          <section className="space-y-3">
            <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">4. Runtime Status</h3>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 space-y-3 text-xs">
              {!extensionConnected && (
                <div className="flex items-start gap-2 text-amber-300">
                  <CircleAlert size={16} className="mt-0.5" />
                  <span>The Flow extension currently appears offline. The workspace can still attempt the request, but the backend must reconnect before Flow can finish it.</span>
                </div>
              )}
              {statusMessage && (
                <div className="flex items-start gap-2 text-sky-300">
                  {isBusy ? <LoaderCircle size={16} className="mt-0.5 animate-spin" /> : <CircleCheckBig size={16} className="mt-0.5" />}
                  <span>{statusMessage}</span>
                </div>
              )}
              {errorMessage && (
                <div className="flex items-start gap-2 text-rose-300">
                  <CircleAlert size={16} className="mt-0.5" />
                  <span>{errorMessage}</span>
                </div>
              )}
              {lastRequest && (
                <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-slate-300">
                  <div>Request: <span className="font-mono">{lastRequest.id}</span></div>
                  <div>Status: <span className="font-semibold">{lastRequest.status}</span></div>
                </div>
              )}
            </div>
          </section>
        )}
        
        <div className="pt-4">
          <button 
            onClick={handleExecute}
            disabled={isBusy || !prompt.trim() || !startAsset}
            className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
          >
            {isBusy ? 'Executing Golden Sequence...' : 'START GENERATION'}
            {!isBusy && <ArrowRight size={18} />}
          </button>
        </div>
      </div>

      {/* Google Flow Mirror Panel */}
      <div className="w-72 flex-shrink-0 flex flex-col gap-6">
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">Flow Mirror Settings</h3>
          <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-6">
            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Aspect Ratio</label>
              <div className="grid grid-cols-2 gap-2">
                <button 
                  onClick={() => setOrientation('VERTICAL')}
                  className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === 'VERTICAL' ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-slate-950 border-slate-800 text-slate-500'}`}
                >
                  9:16 (Vertical)
                </button>
                <button 
                  onClick={() => setOrientation('HORIZONTAL')}
                  className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === 'HORIZONTAL' ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-slate-950 border-slate-800 text-slate-500'}`}
                >
                  16:9 (Horizontal)
                </button>
              </div>
            </div>

            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Generation Model</label>
              <select 
                value={model}
                onChange={(e) => setModel(e.target.value)}
                aria-label="Generation model"
                title="Generation model"
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] font-bold text-slate-300 outline-none"
              >
                <option>Veo 3.1 - Pro</option>
                <option>Veo 3.1 - Lite</option>
                <option>Nano Banana 2</option>
              </select>
            </div>

            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Count</label>
              <div className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-[10px] font-bold text-slate-400">
                1 Video
              </div>
            </div>
          </div>
        </section>

        <section className="flex-1 p-6 rounded-2xl border border-blue-500/10 bg-blue-500/5">
           <h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-widest mb-2">F2V Context</h4>
           <p className="text-[10px] text-blue-300/60 leading-relaxed italic">
             In Frames mode, Google Flow creates motion between your Start and End frames. 
             Stability is guaranteed by your reference assets.
           </p>
        </section>
      </div>
    </div>
  )
}
