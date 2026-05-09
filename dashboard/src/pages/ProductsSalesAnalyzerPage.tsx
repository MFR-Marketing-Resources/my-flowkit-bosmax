import { useEffect, useMemo, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'

import { fetchAPI, postAPI } from '../api/client'
import type { Product } from '../types'

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

function ImageFallback({ src, alt, className }: { src?: string | null; alt?: string; className?: string }) {
  const [err, setErr] = useState(false)
  if (!src) return <div className={`${className} flex items-center justify-center bg-slate-800 text-[10px] font-bold text-slate-500 text-center p-2`}>IMAGE_NOT_AVAILABLE</div>
  if (err) return <div className={`${className} flex items-center justify-center bg-red-900/20 text-[10px] font-bold text-red-500/70 border border-red-900/50 text-center p-2`}>IMAGE_LOAD_FAILED</div>
  return <img src={src} alt={alt} className={className} onError={() => setErr(true)} />
}

export default function ProductsSalesAnalyzerPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState('ALL')
  const [readinessFilter] = useState('ALL')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)
  const [manualForm, setManualForm] = useState<ManualFormState>(emptyManualForm)
  const [tikTokForm, setTikTokForm] = useState<TikTokFormState>({ url: '', raw_product_title: '' })

  const selectedProduct = useMemo(() => products.find(product => product.id === selectedId) || null, [products, selectedId])

  async function loadProducts() {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (search.trim()) params.set('q', search.trim())
      if (sourceFilter !== 'ALL') params.set('source', sourceFilter)
      if (readinessFilter !== 'ALL') params.set('readiness', readinessFilter)
      const query = params.toString()
      const rows = await fetchAPI<Product[]>(`/api/products${query ? `?${query}` : ''}`)
      // No more slice logic, it natively returns exactly what matches.
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
        price: manualForm.price ? Number(manualForm.price) : null,
        commission_amount: manualForm.commission_amount ? Number(manualForm.commission_amount) : null,
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

  return (
    <div className="grid grid-cols-[380px_1fr] h-full overflow-hidden">

      {/* Left: Complete Catalog Browser */}
      <div className="border-r flex flex-col bg-slate-900/30 overflow-hidden" style={{ borderColor: 'var(--border)' }}>
        <div className="p-4 border-b" style={{ borderColor: 'var(--border)' }}>
          <h2 className="text-sm font-bold mb-3">Products / Sales Analyzer</h2>
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
                className="flex-1 bg-slate-900 border text-xs px-2 py-1.5 rounded"
                style={{ borderColor: 'var(--border)', color: 'var(--text)' }}
              >
                <option value="ALL">All Sources</option>
                <option value="FASTMOSS">FastMoss</option>
                <option value="MANUAL">Manual</option>
                <option value="TIKTOKSHOP_DRAFT">TikTok Draft</option>
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
                   <ImageFallback src={product.local_image_path ? `/api/files/${encodeURIComponent(product.local_image_path)}` : product.image_url} alt={product.product_short_name} className="w-full h-full object-cover" />
                </div>
                <div className="flex-1 min-w-0 flex flex-col justify-between py-0.5">
                  <div className="text-xs font-semibold truncate text-slate-200" title={product.raw_product_title}>{product.product_short_name || product.raw_product_title}</div>
                  <div className="text-[10px] text-slate-400 truncate mt-0.5">{product.category} &rsaquo; {product.subcategory} &rsaquo; {product.type}</div>
                  <div className="flex items-center justify-between mt-1 text-[10px]">
                     <span className="text-emerald-400">{product.currency} {fieldValue(product.price)}</span>
                     <span className="text-orange-300">Comm: {fieldValue(product.commission_amount)} / {fieldValue(product.commission_rate)}</span>
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
                <Panel title="Database Record" subtitle={`ID: ${selectedProduct.id} | Source: ${selectedProduct.source}`}>
                  <div className="flex gap-4 mb-4">
                    <div className="w-24 h-24 rounded border border-slate-700 overflow-hidden flex-shrink-0">
                       <ImageFallback src={selectedProduct.local_image_path ? `/api/files/${encodeURIComponent(selectedProduct.local_image_path)}` : selectedProduct.image_url} alt="Product Thumbnail" className="w-full h-full object-cover" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-lg font-bold truncate text-slate-100">{selectedProduct.product_short_name || selectedProduct.raw_product_title}</div>
                      <div className="text-xs text-slate-400 mt-1 pb-2 border-b border-slate-800">{selectedProduct.raw_product_title}</div>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {selectedProduct.prompt_readiness_status === 'READY' ? <StatBadge label="READY" tone="ready" /> : <StatBadge label={selectedProduct.prompt_readiness_status || 'MISSING_FIELDS'} tone="warn" />}
                        {selectedProduct.physics_class ? <StatBadge label={`DNA: ${selectedProduct.physics_class}`} tone="ready" /> : <StatBadge label="DNA: NONE" tone="neutral" />}
                        <StatBadge label={`${selectedProduct.mapping_source} | ${selectedProduct.mapping_confidence}`} tone="neutral" />
                      </div>
                    </div>
                  </div>

                  <div className="space-y-1 mt-4">
                    <KV label="Category Taxonomy" value={`${selectedProduct.category} > ${selectedProduct.subcategory} > ${selectedProduct.type}`} />
                    <KV label="Price & Currency" value={`${fieldValue(selectedProduct.price)} ${fieldValue(selectedProduct.currency)}`} />
                    <KV label="Commission" value={`Amount: ${fieldValue(selectedProduct.commission_amount)} | Rate: ${fieldValue(selectedProduct.commission_rate)}`} />
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
                  </div>
                </Panel>
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
