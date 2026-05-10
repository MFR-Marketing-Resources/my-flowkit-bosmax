import { useEffect, useMemo, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'

import { fetchAPI, patchAPI, postAPI } from '../api/client'
import type { Product } from '../types'
import { formatCommissionDisplay, formatCurrencyDisplay, formatTaxonomyPath } from '../utils/productDisplay'

type ManualFormState = Partial<Product> & {
  image_base64?: string | null
  image_filename?: string | null
}

type TikTokFormState = {
  url: string
  raw_product_title: string
}

function emptyManualForm(): ManualFormState {
  return {
    raw_product_title: '',
    product_short_name: '',
    brand: '',
    category: '',
    subcategory: '',
    type: '',
    price: undefined,
    currency: 'MYR',
    commission_amount: undefined,
    commission_rate: '',
    image_url: '',
    source_url: '',
    product_type: '',
    silo: '',
    trigger_id: '',
    formula: '',
    copywriting_angle: '',
    claim_risk_level: '',
    physics_class: '',
    recommended_grip: '',
    hand_object_interaction: '',
    material_behavior: '',
    surface_behavior: '',
    unsafe_handling_rules: [],
    section_5_product_physics_prompt: '',
    image_base64: null,
    image_filename: null,
  }
}

function fieldValue(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return 'NOT_AVAILABLE'
  return String(value)
}

async function fileToBase64(file: File) {
  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const payload = reader.result
      if (typeof payload !== 'string') {
        reject(new Error('Failed to convert image file'))
        return
      }
      resolve(payload)
    }
    reader.onerror = () => reject(reader.error ?? new Error(`Failed to read ${file.name}`))
    reader.readAsDataURL(file)
  })
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

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border p-4" style={{ background: 'linear-gradient(180deg, rgba(15,23,42,0.8), rgba(15,23,42,0.42))', borderColor: 'var(--border)' }}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-sm font-bold" style={{ color: 'var(--text)' }}>{title}</h2>
          {subtitle ? <div className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>{subtitle}</div> : null}
        </div>
      </div>
      {children}
    </section>
  )
}

function KV({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-2 text-[11px] items-start border-b border-[var(--border)] py-1 last:border-0 hover:bg-slate-800/50">
      <div style={{ color: 'var(--muted)' }} className="font-semibold">{label}</div>
      <div style={{ color: 'var(--text)' }}>{fieldValue(value)}</div>
    </div>
  )
}

function imageStatusLabel(product: Product | null) {
  return product?.image_readiness_status || 'IMAGE_NOT_AVAILABLE'
}

function imageStatusDetail(product: Product | null) {
  return product?.image_readiness_detail || product?.image_failure_detail || ''
}

function imageErrorLabel(product: Product | null) {
  if (product?.local_image_path) return imageStatusLabel(product)
  return 'IMAGE_LOAD_FAILED'
}

function ImageFallback({ src, alt, className, emptyLabel, errorLabel }: { src?: string | null; alt?: string; className?: string; emptyLabel?: string; errorLabel?: string }) {
  const [err, setErr] = useState(false)
  if (!src) return <div className={`${className} flex items-center justify-center bg-slate-800 text-[10px] font-bold text-slate-500 text-center p-2`}>{emptyLabel || 'IMAGE_NOT_AVAILABLE'}</div>
  if (err) return <div className={`${className} flex items-center justify-center bg-red-900/20 text-[10px] font-bold text-red-500/70 border border-red-900/50 text-center p-2`}>{errorLabel || 'IMAGE_LOAD_FAILED'}</div>
  return <img src={src} alt={alt} className={className} onError={() => setErr(true)} />
}

export default function ProductsSalesAnalyzerPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState('FASTMOSS')
  const [readinessFilter] = useState('ALL')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)
  const [imageActionBusy, setImageActionBusy] = useState(false)
  const [imageMapImportBusy, setImageMapImportBusy] = useState(false)
  const [selectedImageUrl, setSelectedImageUrl] = useState('')
  const [manualForm, setManualForm] = useState<ManualFormState>(emptyManualForm)
  const [tikTokForm, setTikTokForm] = useState<TikTokFormState>({ url: '', raw_product_title: '' })
  const [activeTab, setActiveTab] = useState<'DETAILS' | 'BRIEF' | 'VARIATIONS' | 'PREVIEW'>('DETAILS')
  const [brief, setBrief] = useState<any | null>(null)
  const [variations, setVariations] = useState<any[]>([])
  const [promptPreview, setPromptPreview] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const selectedProduct = useMemo(() => products.find(product => product.id === selectedId) || null, [products, selectedId])
  const imageReadinessSummary = useMemo(() => {
    const summary = {
      READY: 0,
      CACHE_READY: 0,
      URL_MISSING: 0,
      DOWNLOAD_FAILED: 0,
      NOT_AVAILABLE: 0,
    }

    for (const product of products) {
      switch (product.image_readiness_status) {
        case 'IMAGE_READY':
          summary.READY += 1
          break
        case 'IMAGE_CACHE_READY':
          summary.CACHE_READY += 1
          break
        case 'IMAGE_DOWNLOAD_FAILED':
          summary.DOWNLOAD_FAILED += 1
          break
        case 'IMAGE_NOT_AVAILABLE':
          summary.NOT_AVAILABLE += 1
          break
        default:
          summary.URL_MISSING += 1
      }
    }
    return summary
  }, [products])

  useEffect(() => {
    setSelectedImageUrl(selectedProduct?.image_url || '')
    setBrief(null)
    setVariations([])
    setPromptPreview(null)
  }, [selectedProduct?.id, selectedProduct?.image_url])

  useEffect(() => {
    async function fetchData() {
      if (!selectedId) return
      if (activeTab === 'BRIEF') {
        try {
          const res = await fetchAPI<any>(`/api/products/${selectedId}/creative-brief`)
          setBrief(res)
        } catch (err) {
          console.error('Failed to fetch brief', err)
        }
      } else if (activeTab === 'VARIATIONS') {
        try {
          const res = await postAPI<any[]>(`/api/products/${selectedId}/variation-plan`, {})
          setVariations(res)
        } catch (err) {
          console.error('Failed to fetch variations', err)
        }
      }
    }
    fetchData()
  }, [selectedId, activeTab])

  async function loadProducts() {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (search.trim()) params.set('q', search.trim())
      if (sourceFilter !== 'ALL') params.set('source', sourceFilter)
      if (readinessFilter !== 'ALL') params.set('readiness', readinessFilter)
      params.set('limit', '500')
      const query = params.toString()
      const res = await fetchAPI<{items: Product[], total_count: number}>(`/api/products${query ? `?${query}` : ''}`)
      // No more slice logic, it natively returns exactly what matches.
      const rows = res.items || []
      setProducts(rows)
      setSelectedId(current => current && rows.some(row => row.id === current) ? current : rows[0]?.id || null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load products')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProducts()
  }, [])

  async function handleManualSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    setSaveSuccess(null)
    try {
      const payload = {
        ...manualForm,
        price: manualForm.price === undefined ? null : Number(manualForm.price),
        commission_amount: manualForm.commission_amount === undefined ? null : Number(manualForm.commission_amount),
      }
      const created = await postAPI<Product>('/api/products/manual', payload)
      setManualForm(emptyManualForm())
      await loadProducts()
      setSelectedId(created.id)
      setSaveSuccess(`Saved manually: ${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create manual product')
    } finally {
      setSaving(false)
    }
  }

  async function handleImageUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const base64 = await fileToBase64(file)
      setManualForm(f => ({ ...f, image_base64: base64, image_filename: file.name }))
    } catch (err) {
      alert('Failed to read image file')
    }
  }

  async function handleTikTokSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    setSaveSuccess(null)
    try {
      const response = await postAPI<{ product?: Product; error_code?: string; detail?: string }>('/api/products/import-tiktokshop', tikTokForm)
      if (response.error_code === 'TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED' || (response.detail && response.detail.includes('Not implemented'))) {
         setError('TikTok Shop extraction is NOT_IMPLEMENTED. Please use Manual Intake.')
         return
      }
      if (response.product) {
         setTikTokForm({ url: '', raw_product_title: '' })
         await loadProducts()
         setSelectedId(response.product.id)
         setSaveSuccess(`Imported Draft: ${response.product.id}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to register TikTok Shop product. NOT_IMPLEMENTED extraction.')
    } finally {
      setSaving(false)
    }
  }

  async function updateSelectedProductImage(payload: Record<string, unknown>, successMessage: string) {
    if (!selectedProduct) return
    setImageActionBusy(true)
    setError(null)
    setSaveSuccess(null)
    try {
      const updated = await patchAPI<Product>(`/api/products/${selectedProduct.id}`, payload)
      await loadProducts()
      setSelectedId(updated.id)
      setSaveSuccess(successMessage)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update selected product image state')
    } finally {
      setImageActionBusy(false)
    }
  }

  async function handleSelectedImageUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !selectedProduct) return
    setImageActionBusy(true)
    setError(null)
    setSaveSuccess(null)
    try {
      const base64 = await fileToBase64(file)
      const updated = await patchAPI<Product>(`/api/products/${selectedProduct.id}`, {
        image_base64: base64,
        image_filename: file.name,
        image_asset_status: 'READY',
        image_failure_detail: '',
      })
      await loadProducts()
      setSelectedId(updated.id)
      setSaveSuccess('Uploaded image and cached it locally for the selected product')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload image for selected product')
    } finally {
      e.target.value = ''
      setImageActionBusy(false)
    }
  }

  async function handlePreviewPrompt(variant: any) {
    if (!selectedId) return
    setPreviewLoading(true)
    try {
      const res = await postAPI<{ prompt: string }>(`/api/products/${selectedId}/prompt-preview`, variant)
      setPromptPreview(res.prompt)
      setActiveTab('PREVIEW')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate preview')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handlePasteImageUrl() {
    if (!selectedProduct || !selectedImageUrl.trim()) return
    await updateSelectedProductImage(
      {
        image_url: selectedImageUrl.trim(),
        local_image_path: '',
        asset_status: 'UNRESOLVED',
        image_asset_status: 'UNRESOLVED',
        image_failure_detail: '',
      },
      'Updated image URL for the selected product',
    )
  }

  async function handleCacheSelectedImage() {
    if (!selectedProduct) return
    setImageActionBusy(true)
    setError(null)
    setSaveSuccess(null)
    try {
      const result = await postAPI<{ status: string; detail?: string; local_image_path?: string }>(`/api/products/${selectedProduct.id}/cache-image`, {})
      await loadProducts()
      setSelectedId(selectedProduct.id)
      setSaveSuccess(result.status === 'success' ? 'Cached image successfully for the selected product' : (result.detail || 'Image cache attempt completed with a non-ready result'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cache selected product image')
    } finally {
      setImageActionBusy(false)
    }
  }

  async function handleMarkImageNotAvailable() {
    if (!selectedProduct) return
    await updateSelectedProductImage(
      {
        image_url: '',
        local_image_path: '',
        asset_status: 'UNRESOLVED',
        image_asset_status: 'NOT_AVAILABLE',
        image_failure_detail: 'Marked manually as image not available.',
      },
      'Marked the selected product image as not available',
    )
  }

  async function handleImageMapImport(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setImageMapImportBusy(true)
    setError(null)
    setSaveSuccess(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const response = await fetch('/api/products/import-image-map', {
        method: 'POST',
        body: formData,
      })
      const payload = await response.json() as { imported?: number; total_rows?: number; warnings?: string[]; detail?: string }
      if (!response.ok) {
        throw new Error(payload.detail || 'Failed to import image map')
      }
      await loadProducts()
      const warningSuffix = payload.warnings?.length ? ` (${payload.warnings.length} warning${payload.warnings.length === 1 ? '' : 's'})` : ''
      setSaveSuccess(`Imported image map rows: ${payload.imported || 0}/${payload.total_rows || 0}${warningSuffix}`)
      if (payload.warnings?.length) {
        setError(payload.warnings.slice(0, 5).join(' | '))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import image map')
    } finally {
      e.target.value = ''
      setImageMapImportBusy(false)
    }
  }

  return (
    <div className="grid grid-cols-[380px_1fr] h-full overflow-hidden">

      {/* Left: Complete Catalog Browser */}
      <div className="border-r flex flex-col bg-slate-900/30 overflow-hidden" style={{ borderColor: 'var(--border)' }}>
        <div className="p-4 border-b" style={{ borderColor: 'var(--border)' }}>
          <h2 className="text-sm font-bold mb-3">Products / Sales Analyzer</h2>
          <div className="grid grid-cols-2 gap-2 mb-3 text-[10px]">
            <div className="rounded border border-emerald-500/20 bg-emerald-500/10 p-2 text-emerald-200">READY: {imageReadinessSummary.READY}</div>
            <div className="rounded border border-sky-500/20 bg-sky-500/10 p-2 text-sky-200">CACHE_READY: {imageReadinessSummary.CACHE_READY}</div>
            <div className="rounded border border-amber-500/20 bg-amber-500/10 p-2 text-amber-200">URL_MISSING: {imageReadinessSummary.URL_MISSING}</div>
            <div className="rounded border border-rose-500/20 bg-rose-500/10 p-2 text-rose-200">DOWNLOAD_FAILED: {imageReadinessSummary.DOWNLOAD_FAILED}</div>
            <div className="rounded border border-slate-500/20 bg-slate-500/10 p-2 text-slate-200 col-span-2">NOT_AVAILABLE: {imageReadinessSummary.NOT_AVAILABLE} | TOTAL: {products.length}</div>
          </div>
          <div className="space-y-2">
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search products..."
              className="w-full bg-slate-900 border text-xs px-3 py-2 rounded"
              style={{ borderColor: 'var(--border)', color: 'var(--text)' }}
              onKeyDown={e => e.key === 'Enter' && loadProducts()}
            />
            <div className="flex gap-2">
              <select
                value={sourceFilter}
                onChange={e => setSourceFilter(e.target.value)}
                aria-label="Filter products by source"
                className="flex-1 bg-slate-900 border text-xs px-2 py-1.5 rounded"
                style={{ borderColor: 'var(--border)', color: 'var(--text)' }}
              >
                <option value="FASTMOSS">FastMoss</option>
                <option value="MANUAL">Manual</option>
                <option value="TIKTOKSHOP">TikTok Draft</option>
                <option value="TEST">Test / Fixture</option>
                <option value="ALL">All Sources</option>
              </select>
              <button
                onClick={loadProducts}
                className="bg-blue-600 hover:bg-blue-500 text-white text-xs px-3 py-1.5 rounded font-medium"
              >
                Search
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2" style={{ scrollbarWidth: 'thin' }}>
          {loading && <div className="text-center py-4 text-xs" style={{ color: 'var(--muted)' }}>Loading catalog...</div>}
          {!loading && products.length === 0 && <div className="text-center py-4 text-xs" style={{ color: 'var(--muted)' }}>No products found</div>}

          <div className="space-y-1">
            {products.map(product => (
              <div
                key={product.id}
                onClick={() => setSelectedId(product.id)}
                className={`flex gap-3 p-2 rounded cursor-pointer transition-colors ${selectedId === product.id ? 'bg-blue-900/30 border-blue-500/50 border' : 'hover:bg-slate-800 border border-transparent'}`}
              >
                <div className="flex-shrink-0 w-16 h-16 rounded overflow-hidden bg-slate-800">
                   <ImageFallback src={product.rendered_img_src} alt={product.product_short_name} className="w-full h-full object-cover" emptyLabel={imageStatusLabel(product)} errorLabel={imageErrorLabel(product)} />
                </div>
                <div className="flex-1 min-w-0 flex flex-col justify-between py-0.5">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="text-xs font-semibold truncate text-slate-200" title={product.raw_product_title}>{product.product_short_name || product.raw_product_title}</div>
                    {product.is_test_product ? <StatBadge label="TEST" tone="risk" /> : null}
                  </div>
                  <div className="text-[10px] text-slate-400 truncate mt-0.5">{formatTaxonomyPath(product.category, product.subcategory, product.type)}</div>
                  <div className="text-[10px] text-slate-500 truncate mt-0.5">{imageStatusLabel(product)}</div>
                  <div className="flex items-center justify-between mt-1 text-[10px]">
                    <span className="text-emerald-400">{formatCurrencyDisplay(product.price, product.currency)}</span>
                    <span className="text-orange-300">{formatCommissionDisplay(product)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right: Selected Detail / Forms */}
      <div className="overflow-y-auto p-6" style={{ scrollbarWidth: 'thin' }}>
        {error && <div className="mb-4 bg-red-900/30 border border-red-500/30 text-red-400 p-3 rounded text-sm text-center">{error}</div>}
        {saveSuccess && <div className="mb-4 bg-emerald-900/30 border border-emerald-500/30 text-emerald-400 p-3 rounded text-sm text-center flex justify-between"><span>{saveSuccess}</span><button onClick={() => setSaveSuccess(null)}>✕</button></div>}

        <div className="grid grid-cols-[1fr_300px] gap-6 items-start">
          <div className="space-y-6">

            {selectedProduct && (
              <div className="space-y-6">
                <div className="flex gap-1 border-b border-slate-800 pb-px">
                  {(['DETAILS', 'BRIEF', 'VARIATIONS', 'PREVIEW'] as const).map(tab => (
                    <button
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      className={`px-4 py-2 text-[11px] font-bold transition-all border-b-2 ${activeTab === tab ? 'border-blue-500 text-blue-400 bg-blue-500/5' : 'border-transparent text-slate-500 hover:text-slate-300'}`}
                    >
                      {tab}
                    </button>
                  ))}
                </div>

                {activeTab === 'DETAILS' && (
                  <>
                <Panel title="Database Record" subtitle={`ID: ${selectedProduct.id} | Source: ${selectedProduct.source}`}>
                  <div className="flex gap-4 mb-4">
                    <div className="w-24 h-24 rounded border border-slate-700 overflow-hidden flex-shrink-0">
                       <ImageFallback src={selectedProduct.rendered_img_src} alt="Product Thumbnail" className="w-full h-full object-cover" emptyLabel={imageStatusLabel(selectedProduct)} errorLabel={imageErrorLabel(selectedProduct)} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-lg font-bold truncate text-slate-100">{selectedProduct.product_short_name || selectedProduct.raw_product_title}</div>
                      <div className="text-xs text-slate-400 mt-1 pb-2 border-b border-slate-800">{selectedProduct.raw_product_title}</div>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {selectedProduct.prompt_readiness_status === 'READY' ? <StatBadge label="READY" tone="ready" /> : <StatBadge label={selectedProduct.prompt_readiness_status || 'MISSING_FIELDS'} tone="warn" />}
                        {selectedProduct.physics_class ? <StatBadge label={`DNA: ${selectedProduct.physics_class}`} tone="ready" /> : <StatBadge label="DNA: NONE" tone="neutral" />}
                        <StatBadge label={`${selectedProduct.mapping_source} | ${selectedProduct.mapping_confidence}`} tone="neutral" />
                        {selectedProduct.is_test_product ? <StatBadge label="TEST" tone="risk" /> : null}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-1 mt-4">
                    <KV label="Category Taxonomy" value={formatTaxonomyPath(selectedProduct.category, selectedProduct.subcategory, selectedProduct.type)} />
                    <KV label="Price & Currency" value={formatCurrencyDisplay(selectedProduct.price, selectedProduct.currency)} />
                    <KV label="Commission" value={formatCommissionDisplay(selectedProduct)} />
                    <KV label="Product Type ID" value={selectedProduct.product_type} />
                    <KV label="Silo" value={selectedProduct.silo} />
                    <KV label="Copywriting Angle" value={selectedProduct.copywriting_angle} />
                    <KV label="Trigger ID / Formula" value={`${selectedProduct.trigger_id} / ${selectedProduct.formula}`} />
                    <KV label="Claim Risk Level" value={selectedProduct.claim_risk_level} />
                  </div>
                </Panel>

                <Panel title="Product Handling / Physics DNA" subtitle="Resolved behavior properties">
                  <div className="space-y-1">
                    <KV label="Physics Class" value={selectedProduct.physics_class} />
                    <KV label="Scale / Fragility" value={`${selectedProduct.product_scale} | Fragility: ${selectedProduct.fragility_level}`} />
                    <KV label="Recommended Grip" value={selectedProduct.recommended_grip} />
                    <KV label="Hand Interaction" value={selectedProduct.hand_object_interaction} />
                    <KV label="Material Behavior" value={selectedProduct.material_behavior} />
                    <KV label="Surface Behavior" value={selectedProduct.surface_behavior} />
                    <KV label="Air Gap Rule" value={selectedProduct.air_gap_rule} />
                    <KV label="Unsafe Constraints" value={((selectedProduct as any).unsafe_handling_rules || []).join('; ')} />
                    <div className="mt-3 p-3 bg-slate-900/50 rounded border border-slate-800 text-xs font-mono text-purple-300 leading-relaxed">
                      {selectedProduct.section_5_product_physics_prompt || 'No Section 5 prompt generated.'}
                    </div>
                  </div>
                </Panel>

                <Panel title="Source & Maintenance" subtitle="Audit details">
                  <div className="space-y-1">
                    <KV label="Source URL" value={selectedProduct.source_url || selectedProduct.tiktok_product_url} />
                    <KV label="Image Source" value={selectedProduct.image_url} />
                    <KV label="Image Readiness" value={selectedProduct.image_readiness_status} />
                    <KV label="Image Readiness Detail" value={selectedProduct.image_readiness_detail || selectedProduct.image_failure_detail} />
                    <KV label="Local Image Path" value={selectedProduct.local_image_path} />
                    <KV label="Rendered Image Src" value={selectedProduct.rendered_img_src} />
                    <KV label="Image HTTP Status" value={selectedProduct.image_http_status} />
                    <KV label="Catalog Label" value={selectedProduct.catalog_label} />
                  </div>

                  {imageStatusDetail(selectedProduct) ? (
                    <div className="mt-4 rounded border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-300">
                      {imageStatusDetail(selectedProduct)}
                    </div>
                  ) : null}

                  <div className="mt-4 rounded border border-slate-800 bg-slate-950/60 p-3 space-y-3">
                    <div className="text-[11px] font-semibold text-slate-300">Image Actions</div>
                    <div className="flex flex-col gap-2">
                      <input
                        type="text"
                        value={selectedImageUrl}
                        onChange={e => setSelectedImageUrl(e.target.value)}
                        aria-label="Selected product image URL"
                        placeholder="Paste image URL"
                        className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200"
                      />
                      <div className="grid grid-cols-2 gap-2">
                        <button
                          type="button"
                          disabled={imageActionBusy || !selectedImageUrl.trim()}
                          onClick={handlePasteImageUrl}
                          className="bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 border border-blue-500/30 text-xs px-3 py-2 rounded disabled:opacity-50"
                        >
                          Paste Image URL
                        </button>
                        <button
                          type="button"
                          disabled={imageActionBusy}
                          onClick={handleCacheSelectedImage}
                          className="bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300 border border-emerald-500/30 text-xs px-3 py-2 rounded disabled:opacity-50"
                        >
                          Cache Image
                        </button>
                        <label className={`bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 text-xs px-3 py-2 rounded text-center cursor-pointer ${imageActionBusy ? 'opacity-50 cursor-not-allowed' : ''}`}>
                          Upload Image
                          <input type="file" accept="image/*" onChange={handleSelectedImageUpload} aria-label="Upload selected product image" className="hidden" disabled={imageActionBusy} />
                        </label>
                        <button
                          type="button"
                          disabled={imageActionBusy}
                          onClick={handleMarkImageNotAvailable}
                          className="bg-amber-600/20 hover:bg-amber-600/40 text-amber-300 border border-amber-500/30 text-xs px-3 py-2 rounded disabled:opacity-50"
                        >
                          Mark Image Not Available
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 rounded border border-slate-800 bg-slate-950/60 p-3 space-y-3">
                    <div className="text-[11px] font-semibold text-slate-300">Mode Readiness</div>
                    <div className="space-y-2">
                      {Object.entries(selectedProduct.mode_readiness || {}).map(([mode, readiness]) => (
                        <div key={mode} className="rounded border border-slate-800 bg-slate-900/60 p-2">
                          <div className="flex items-center justify-between gap-2 text-[11px]">
                            <span className="font-semibold text-slate-200">{mode}</span>
                            <StatBadge
                              label={readiness.status}
                              tone={readiness.status === 'READY' ? 'ready' : readiness.status === 'READY_OR_NEEDS_REVIEW' ? 'warn' : 'risk'}
                            />
                          </div>
                          <div className="mt-1 text-[10px] text-slate-400">{readiness.detail}</div>
                          {'asset_strategy' in readiness && readiness.asset_strategy ? <div className="mt-1 text-[10px] text-slate-500">Asset Strategy: {readiness.asset_strategy}</div> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                </Panel>
                  </>
                )}

                {activeTab === 'BRIEF' && brief && (
                  <div className="space-y-6">
                    <Panel title="Product Creative Brief" subtitle={`Brief ID: ${brief.brief_id}`}>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-4">
                          <h3 className="text-xs font-bold text-slate-300">Readiness Status</h3>
                          <div className="space-y-2">
                            {Object.entries(brief.readiness).map(([k, v]) => (
                              <div key={k} className="flex justify-between items-center text-[11px] p-2 bg-slate-900/50 rounded border border-slate-800">
                                <span className="text-slate-400">{k}</span>
                                <StatBadge label={v as string} tone={v === 'READY' ? 'ready' : 'risk'} />
                              </div>
                            ))}
                          </div>
                          {brief.missing_fields.length > 0 && (
                            <div className="p-3 bg-red-900/10 border border-red-500/20 rounded text-[10px] text-red-300">
                              <strong>Missing Fields:</strong> {brief.missing_fields.join(', ')}
                            </div>
                          )}
                        </div>
                        <div className="space-y-4">
                          <h3 className="text-xs font-bold text-slate-300">Copywriting Route</h3>
                          <div className="space-y-1">
                            <KV label="Silo" value={brief.copywriting_route.silo} />
                            <KV label="Formula" value={brief.copywriting_route.formula} />
                            <KV label="Trigger" value={brief.copywriting_route.trigger_id} />
                            <KV label="Risk Level" value={brief.copywriting_route.claim_risk_level} />
                          </div>
                        </div>
                      </div>
                    </Panel>

                    <Panel title="Physics DNA" subtitle="Biometric and material properties">
                       <div className="grid grid-cols-2 gap-4">
                         <div className="space-y-1">
                           <KV label="Class" value={brief.physics_dna.physics_class} />
                           <KV label="Scale" value={brief.physics_dna.product_scale} />
                           <KV label="Interaction" value={brief.physics_dna.hand_object_interaction} />
                         </div>
                         <div className="space-y-1">
                           <KV label="Material" value={brief.physics_dna.material_behavior} />
                           <KV label="Surface" value={brief.physics_dna.surface_behavior} />
                         </div>
                       </div>
                       <div className="mt-4 p-3 bg-slate-900/80 rounded border border-slate-800 font-mono text-[10px] text-purple-300">
                         {brief.physics_dna.section_5_product_physics_prompt}
                       </div>
                    </Panel>
                  </div>
                )}

                {activeTab === 'VARIATIONS' && (
                  <Panel title="Variation Matrix" subtitle="Product-to-Concept expansion">
                    <div className="space-y-4">
                      {variations.map((v) => (
                        <div key={v.variant_id} className="p-4 rounded-xl border border-slate-800 bg-slate-900/40 hover:bg-slate-900/60 transition-all">
                          <div className="flex justify-between items-start mb-3">
                             <div className="text-xs font-bold text-blue-400">Variant #{v.variation_index}</div>
                             <StatBadge label={v.readiness} tone={v.readiness === 'READY' ? 'ready' : 'risk'} />
                          </div>
                          <div className="grid grid-cols-2 gap-x-6 gap-y-2 mb-4">
                            <KV label="Hook Angle" value={v.hook_angle} />
                            <KV label="Scene Context" value={v.scene_context} />
                            <KV label="Camera Route" value={v.camera_route} />
                            <KV label="Strategy" value={v.asset_strategy} />
                          </div>
                          <button
                            onClick={() => handlePreviewPrompt(v)}
                            className="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 text-[10px] font-bold py-2 rounded uppercase tracking-wider border border-slate-700"
                          >
                            Preview 9-Section Prompt
                          </button>
                        </div>
                      ))}
                      {variations.length === 0 && <div className="text-center py-8 text-slate-500 text-xs">No variations generated.</div>}
                    </div>
                  </Panel>
                )}

                {activeTab === 'PREVIEW' && (
                  <Panel title="9-Section Prompt Preview" subtitle="Clean compiled output for Google Flow">
                    {previewLoading ? (
                      <div className="text-center py-12 text-slate-500 text-xs">Compiling prompt...</div>
                    ) : promptPreview ? (
                      <div className="space-y-4">
                        <div className="p-4 bg-slate-950 rounded-xl border border-slate-800 font-mono text-[11px] text-slate-300 leading-relaxed whitespace-pre-wrap select-all">
                          {promptPreview}
                        </div>
                        <div className="flex gap-2">
                           <button
                             onClick={() => { navigator.clipboard.writeText(promptPreview); setSaveSuccess("Prompt copied to clipboard"); }}
                             className="flex-1 bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 border border-blue-500/30 py-2 rounded text-xs font-bold"
                           >
                             Copy to Clipboard
                           </button>
                           <button
                             onClick={() => setActiveTab('VARIATIONS')}
                             className="px-6 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 py-2 rounded text-xs font-bold"
                           >
                             Back
                           </button>
                        </div>
                      </div>
                    ) : (
                      <div className="text-center py-12 text-slate-500 text-xs">Select a variant to preview prompt.</div>
                    )}
                  </Panel>
                )}
              </div>
            )}
            {!selectedProduct && !loading && (
              <div className="p-8 text-center text-slate-500 border border-slate-800 rounded bg-slate-900/20">
                Select a product from the catalog to view details.
              </div>
            )}

            <div className="border-t border-slate-800 my-8 pt-8">
              <Panel title="Manual Product Intake" subtitle="Inject non-FastMoss products directly using the identical intelligence schema.">
                <form onSubmit={handleManualSubmit} className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                     <div>
                       <label className="block text-[11px] mb-1 text-slate-400">Raw Title (Platform name) *</label>
                       <input required className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200 focus:border-blue-500" value={manualForm.raw_product_title || ''} onChange={e => setManualForm(f => ({ ...f, raw_product_title: e.target.value }))} />
                     </div>
                     <div>
                       <label className="block text-[11px] mb-1 text-slate-400">Short Name (Clean) *</label>
                       <input required className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200 focus:border-blue-500" value={manualForm.product_short_name || ''} onChange={e => setManualForm(f => ({ ...f, product_short_name: e.target.value }))} />
                     </div>
                     <div>
                       <label className="block text-[11px] mb-1 text-slate-400">Category *</label>
                       <input required className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200" value={manualForm.category || ''} onChange={e => setManualForm(f => ({ ...f, category: e.target.value }))} />
                     </div>
                     <div>
                       <label className="block text-[11px] mb-1 text-slate-400">Subcategory *</label>
                       <input required className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200" value={manualForm.subcategory || ''} onChange={e => setManualForm(f => ({ ...f, subcategory: e.target.value }))} />
                     </div>
                     <div>
                       <label className="block text-[11px] mb-1 text-slate-400">Type *</label>
                       <input required className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200" value={manualForm.type || ''} onChange={e => setManualForm(f => ({ ...f, type: e.target.value }))} />
                     </div>
                     <div>
                       <label className="block text-[11px] mb-1 text-slate-400">Price (Native Value) *</label>
                       <input required type="number" step="0.01" className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200" value={manualForm.price || ''} onChange={e => setManualForm(f => ({ ...f, price: e.target.value ? Number(e.target.value) : undefined }))} />
                     </div>
                     <div>
                       <label className="block text-[11px] mb-1 text-slate-400">Commission Rate (%)</label>
                       <input className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200" value={manualForm.commission_rate || ''} onChange={e => setManualForm(f => ({ ...f, commission_rate: e.target.value }))} />
                     </div>
                     <div>
                       <label className="block text-[11px] mb-1 text-slate-400">Source External URL</label>
                       <input className="w-full bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200" value={manualForm.source_url || ''} onChange={e => setManualForm(f => ({ ...f, source_url: e.target.value }))} />
                     </div>
                     <div className="col-span-2">
                       <label className="block text-[11px] mb-1 text-slate-400">Image Source (URL or Upload File)</label>
                       <div className="flex gap-2 items-center">
                         <input type="text" placeholder="https://" className="flex-1 bg-slate-900 border border-slate-700 text-xs p-2 rounded text-slate-200" value={manualForm.image_url || ''} onChange={e => setManualForm(f => ({ ...f, image_url: e.target.value }))} />
                         <span className="text-xs text-slate-500 text-center">OR</span>
                         <input type="file" accept="image/*" onChange={handleImageUpload} className="flex-1 text-xs file:bg-slate-800 file:border-0 file:rounded file:px-3 file:py-1 file:text-slate-300" />
                       </div>
                       {manualForm.image_base64 && <div className="mt-2 flex items-center gap-2"><img src={manualForm.image_base64} className="h-12 w-12 rounded object-cover border border-slate-700" alt="Preview"/> <span className="text-[10px] text-emerald-400">Image loaded for save</span></div>}
                     </div>
                  </div>
                  <div className="pt-2 flex justify-end">
                    <button disabled={saving} className="bg-emerald-600 hover:bg-emerald-500 text-white font-semibold flex items-center justify-center rounded px-4 py-2 text-xs shadow-md border-t border-emerald-400/50 disabled:opacity-50">
                      {saving ? 'Processing...' : 'Save Manual Product & Parse Intelligence'}
                    </button>
                  </div>
                </form>
              </Panel>
            </div>
          </div>

          <div className="space-y-6 sticky top-6">
            <Panel title="Image Acquisition" subtitle="Bulk import existing image/source URLs and commission metadata.">
              <label className={`flex items-center justify-center rounded border border-dashed border-slate-700 px-3 py-4 text-xs text-slate-300 ${imageMapImportBusy ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-sky-500/50 hover:text-sky-200'}`}>
                {imageMapImportBusy ? 'Importing image map...' : 'Import Image Map CSV / JSON'}
                <input type="file" accept=".csv,.json" onChange={handleImageMapImport} aria-label="Import image map file" className="hidden" disabled={imageMapImportBusy} />
              </label>
              <div className="mt-2 text-[10px] text-slate-500 leading-relaxed">
                Supported columns: product_id, raw_product_title, product_short_name, image_url, source_url, commission_amount, commission_rate.
              </div>
            </Panel>

            <Panel title="TikTok Shop Import" subtitle="Register a draft for maintenance.">
              <form onSubmit={handleTikTokSubmit} className="space-y-3">
                <div>
                  <label className="block text-[10px] mb-1 opacity-70">Shop URL</label>
                  <input
                    type="url"
                    required
                    value={tikTokForm.url}
                    onChange={e => setTikTokForm(f => ({ ...f, url: e.target.value }))}
                    className="w-full bg-slate-950 border text-xs px-2 py-1.5 rounded"
                    style={{ borderColor: 'var(--border)', color: 'var(--text)' }}
                    placeholder="https://shop.tiktok.com/..."
                  />
                </div>
                <div>
                  <label className="block text-[10px] mb-1 opacity-70">Draft Product Title (Fallback)</label>
                  <input
                    type="text"
                    required
                    value={tikTokForm.raw_product_title}
                    onChange={e => setTikTokForm(f => ({ ...f, raw_product_title: e.target.value }))}
                    className="w-full bg-slate-950 border text-xs px-2 py-1.5 rounded"
                    style={{ borderColor: 'var(--border)', color: 'var(--text)' }}
                  />
                </div>
                <button
                  type="submit"
                  disabled={saving}
                  className="w-full bg-blue-600/20 hover:bg-blue-600/40 text-blue-400 border border-blue-500/30 text-xs px-3 py-2 rounded font-medium disabled:opacity-50"
                >
                  Register Draft Link
                </button>
                <div className="text-[10px] text-slate-500 px-1 leading-relaxed mt-2 text-center">
                  If backend scraping is not implemented, this creates a draft record with NOT_IMPLEMENTED flag, requiring manual completion.
                </div>
              </form>
            </Panel>
          </div>

        </div>
      </div>
    </div>
  )
}
