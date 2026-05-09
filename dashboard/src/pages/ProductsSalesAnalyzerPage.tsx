import { useEffect, useMemo, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'

import { fetchAPI, patchAPI, postAPI } from '../api/client'
import type { Product } from '../types'

type ManualFormState = {
  raw_product_title: string
  category: string
  subcategory: string
  type: string
  price: string
  commission_rate: string
  image_url: string
  source_url: string
  image_base64: string | null
  image_filename: string | null
}

type TikTokFormState = {
  url: string
  raw_product_title: string
}

function emptyManualForm(): ManualFormState {
  return {
    raw_product_title: '',
    category: '',
    subcategory: '',
    type: '',
    price: '',
    commission_rate: '',
    image_url: '',
    source_url: '',
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
    <div className="grid grid-cols-[100px_1fr] gap-2 text-[11px] items-start">
      <div style={{ color: 'var(--muted)' }}>{label}</div>
      <div style={{ color: 'var(--text)' }}>{fieldValue(value)}</div>
    </div>
  )
}

export default function ProductsSalesAnalyzerPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState('ALL')
  const [readinessFilter, setReadinessFilter] = useState('ALL')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [manualForm, setManualForm] = useState<ManualFormState>(emptyManualForm)
  const [tikTokForm, setTikTokForm] = useState<TikTokFormState>({ url: '', raw_product_title: '' })
  const [editDraft, setEditDraft] = useState<Partial<Product>>({})

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

  useEffect(() => {
    setEditDraft(selectedProduct || {})
  }, [selectedProduct])

  async function handleManualSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const created = await postAPI<Product>('/api/products/manual', {
        ...manualForm,
        price: manualForm.price ? Number(manualForm.price) : null,
        commission_rate: manualForm.commission_rate || null,
      })
      setManualForm(emptyManualForm())
      await loadProducts()
      setSelectedId(created.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create manual product')
    } finally {
      setSaving(false)
    }
  }

  async function handleTikTokSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const response = await postAPI<{ product: Product; error_code: string }>('/api/products/import-tiktokshop', tikTokForm)
      await loadProducts()
      setSelectedId(response.product.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to register TikTok Shop product')
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveDraft() {
    if (!selectedProduct) return
    setSaving(true)
    setError(null)
    try {
      const updated = await patchAPI<Product>(`/api/products/${selectedProduct.id}`, {
        raw_product_title: editDraft.raw_product_title,
        product_display_name: editDraft.product_display_name,
        product_short_name: editDraft.product_short_name,
        category: editDraft.category,
        subcategory: editDraft.subcategory,
        type: editDraft.type,
        price: editDraft.price,
        commission_rate: editDraft.commission_rate,
        image_url: editDraft.image_url,
        source_url: editDraft.source_url,
        product_type: editDraft.product_type,
        silo: editDraft.silo,
        trigger_id: editDraft.trigger_id,
        formula: editDraft.formula,
        copywriting_angle: editDraft.copywriting_angle,
        claim_risk_level: editDraft.claim_risk_level,
        physics_class: editDraft.physics_class,
        recommended_grip: editDraft.recommended_grip,
        camera_handling_notes: editDraft.camera_handling_notes,
        section_5_product_physics_prompt: editDraft.section_5_product_physics_prompt,
      })
      setProducts(current => current.map(product => product.id === updated.id ? updated : product))
      setSelectedId(updated.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update product')
    } finally {
      setSaving(false)
    }
  }

  async function handleImageUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    const imageBase64 = await fileToBase64(file)
    setManualForm(current => ({ ...current, image_base64: imageBase64, image_filename: file.name }))
  }

  const readinessTone = selectedProduct?.prompt_readiness_status === 'READY'
    ? 'ready'
    : selectedProduct?.prompt_readiness_status === 'NEEDS_REVIEW'
      ? 'warn'
      : 'risk'

  return (
    <div className="space-y-5">
      <section className="rounded-3xl border p-5 overflow-hidden" style={{ background: 'radial-gradient(circle at top left, rgba(14,165,233,0.16), rgba(15,23,42,0.94) 58%)', borderColor: 'rgba(14,165,233,0.18)' }}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-2xl">
            <div className="text-[10px] font-bold tracking-[0.3em] uppercase mb-2" style={{ color: '#7dd3fc' }}>Products / Sales Analyzer</div>
            <h1 className="text-2xl font-black" style={{ color: 'var(--text)' }}>Product intelligence foundation with mapping, physics DNA, and 9-section readiness.</h1>
            <p className="text-sm mt-2" style={{ color: 'var(--muted)' }}>
              This module manages FastMoss imports, manual products, TikTok Shop draft intake, and the product-side inputs required before any real creative generation path.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatBadge label={`${products.length} products`} />
            <StatBadge label={selectedProduct?.prompt_readiness_status || 'NO_SELECTION'} tone={readinessTone} />
            <StatBadge label={selectedProduct?.physics_class || 'NO_PHYSICS'} tone={selectedProduct?.physics_class ? 'ready' : 'warn'} />
          </div>
        </div>
      </section>

      {error ? (
        <div className="rounded-xl border px-4 py-3 text-sm" style={{ background: 'rgba(239,68,68,0.08)', borderColor: 'rgba(239,68,68,0.22)', color: '#fca5a5' }}>
          {error}
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-5">
          <Panel title="Catalog" subtitle="Query the enriched product inventory and inspect readiness state.">
            <div className="grid gap-3">
              <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search products..." className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              <div className="grid grid-cols-2 gap-3">
                <select value={sourceFilter} onChange={event => setSourceFilter(event.target.value)} className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
                  <option value="ALL">All Sources</option>
                  <option value="FASTMOSS">FASTMOSS</option>
                  <option value="MANUAL">MANUAL</option>
                  <option value="TIKTOKSHOP">TIKTOKSHOP</option>
                  <option value="IMPORTED">IMPORTED</option>
                </select>
                <select value={readinessFilter} onChange={event => setReadinessFilter(event.target.value)} className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
                  <option value="ALL">All Readiness</option>
                  <option value="READY">READY</option>
                  <option value="NEEDS_REVIEW">NEEDS_REVIEW</option>
                  <option value="MISSING_FIELDS">MISSING_FIELDS</option>
                </select>
              </div>
              <button onClick={loadProducts} disabled={loading} className="px-3 py-2 rounded-xl text-sm font-semibold" style={{ background: 'var(--primary)', color: 'white' }}>
                {loading ? 'Loading...' : 'Refresh Catalog'}
              </button>
            </div>
            <div className="mt-4 space-y-2 max-h-[520px] overflow-y-auto pr-1">
              {products.map(product => (
                <button key={product.id} onClick={() => setSelectedId(product.id)} className="w-full text-left rounded-2xl border p-3 transition-colors" style={{ background: product.id === selectedId ? 'rgba(14,165,233,0.12)' : 'rgba(15,23,42,0.32)', borderColor: product.id === selectedId ? 'rgba(14,165,233,0.35)' : 'var(--border)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold" style={{ color: 'var(--text)' }}>{product.product_short_name}</div>
                    <StatBadge label={product.prompt_readiness_status || 'UNKNOWN'} tone={product.prompt_readiness_status === 'READY' ? 'ready' : product.prompt_readiness_status === 'NEEDS_REVIEW' ? 'warn' : 'risk'} />
                  </div>
                  <div className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>{product.raw_product_title}</div>
                  <div className="flex flex-wrap gap-2 mt-3">
                    <StatBadge label={product.source} />
                    <StatBadge label={product.physics_class || 'NO_PHYSICS'} tone={product.physics_class ? 'ready' : 'warn'} />
                    <StatBadge label={product.mapping_confidence || 'UNMAPPED'} tone={product.mapping_confidence === 'HIGH' ? 'ready' : product.mapping_confidence === 'NEEDS_REVIEW' ? 'warn' : 'neutral'} />
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Manual Intake" subtitle="Register products that do not exist in FastMoss yet.">
            <form className="grid gap-3" onSubmit={handleManualSubmit}>
              <input value={manualForm.raw_product_title} onChange={event => setManualForm(current => ({ ...current, raw_product_title: event.target.value }))} placeholder="Raw product title" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              <div className="grid grid-cols-3 gap-2">
                <input value={manualForm.category} onChange={event => setManualForm(current => ({ ...current, category: event.target.value }))} placeholder="Category" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                <input value={manualForm.subcategory} onChange={event => setManualForm(current => ({ ...current, subcategory: event.target.value }))} placeholder="Subcategory" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                <input value={manualForm.type} onChange={event => setManualForm(current => ({ ...current, type: event.target.value }))} placeholder="Type" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input value={manualForm.price} onChange={event => setManualForm(current => ({ ...current, price: event.target.value }))} placeholder="Price" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                <input value={manualForm.commission_rate} onChange={event => setManualForm(current => ({ ...current, commission_rate: event.target.value }))} placeholder="Commission rate" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              </div>
              <input value={manualForm.image_url} onChange={event => setManualForm(current => ({ ...current, image_url: event.target.value }))} placeholder="Image URL" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              <input value={manualForm.source_url} onChange={event => setManualForm(current => ({ ...current, source_url: event.target.value }))} placeholder="Source URL / audit link" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              <label className="text-[11px]" style={{ color: 'var(--muted)' }}>
                Upload manual image
                <input type="file" accept="image/*" onChange={handleImageUpload} className="block mt-1 text-[11px]" />
              </label>
              <button type="submit" disabled={saving} className="px-3 py-2 rounded-xl text-sm font-semibold" style={{ background: 'var(--primary)', color: 'white' }}>
                {saving ? 'Saving...' : 'Save Manual Product'}
              </button>
            </form>
          </Panel>

          <Panel title="TikTok Shop Intake" subtitle="Store the URL and create an honest draft when extraction is not implemented.">
            <form className="grid gap-3" onSubmit={handleTikTokSubmit}>
              <input value={tikTokForm.url} onChange={event => setTikTokForm(current => ({ ...current, url: event.target.value }))} placeholder="https://shop.tiktok.com/..." className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              <input value={tikTokForm.raw_product_title} onChange={event => setTikTokForm(current => ({ ...current, raw_product_title: event.target.value }))} placeholder="Optional manual title" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
              <button type="submit" disabled={saving} className="px-3 py-2 rounded-xl text-sm font-semibold" style={{ background: 'rgba(245,158,11,0.18)', color: '#fcd34d', border: '1px solid rgba(245,158,11,0.24)' }}>
                {saving ? 'Registering...' : 'Register TikTok Shop Draft'}
              </button>
            </form>
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel title="Analyzer Detail" subtitle="Inspect mapping, physics DNA, readiness, and edit the normalized product record.">
            {!selectedProduct ? (
              <div className="text-sm" style={{ color: 'var(--muted)' }}>Select a product from the catalog to inspect its intelligence profile.</div>
            ) : (
              <div className="grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)]">
                <div className="space-y-3">
                  {selectedProduct.image_url ? (
                    <img src={selectedProduct.image_url} alt={selectedProduct.product_short_name} className="w-full aspect-square rounded-2xl object-cover border" style={{ borderColor: 'var(--border)' }} />
                  ) : (
                    <div className="w-full aspect-square rounded-2xl border flex items-center justify-center text-xs text-center p-4" style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}>
                      No remote image available.
                      <br />
                      Local path: {fieldValue(selectedProduct.local_image_path)}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <StatBadge label={selectedProduct.source} />
                    <StatBadge label={selectedProduct.prompt_readiness_status || 'UNKNOWN'} tone={readinessTone} />
                    <StatBadge label={selectedProduct.physics_class || 'NO_PHYSICS'} tone={selectedProduct.physics_class ? 'ready' : 'warn'} />
                  </div>
                </div>

                <div className="space-y-5">
                  <div className="grid gap-3 md:grid-cols-2">
                    <KV label="Short name" value={selectedProduct.product_short_name} />
                    <KV label="Display name" value={selectedProduct.product_display_name} />
                    <KV label="Category" value={selectedProduct.category} />
                    <KV label="Subcategory" value={selectedProduct.subcategory} />
                    <KV label="Type" value={selectedProduct.type} />
                    <KV label="Brand" value={selectedProduct.brand} />
                    <KV label="Price" value={selectedProduct.price} />
                    <KV label="Commission" value={selectedProduct.commission_rate} />
                    <KV label="Copywriting" value={selectedProduct.copywriting_angle} />
                    <KV label="Claim risk" value={selectedProduct.claim_risk_level} />
                    <KV label="Physics class" value={selectedProduct.physics_class} />
                    <KV label="Recommended grip" value={selectedProduct.recommended_grip} />
                    <KV label="Handling notes" value={selectedProduct.camera_handling_notes} />
                    <KV label="Section 5" value={selectedProduct.section_5_product_physics_prompt} />
                  </div>

                  <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--border)', background: 'rgba(15,23,42,0.32)' }}>
                    <div className="text-xs font-semibold mb-3" style={{ color: 'var(--text)' }}>9-Section Readiness</div>
                    <div className="grid gap-2 text-[11px]">
                      <KV label="Section 4" value={selectedProduct.section_4_visual_action_prompt} />
                      <KV label="Section 5" value={selectedProduct.section_5_product_physics_prompt} />
                      <KV label="Section 6" value={selectedProduct.section_6_dialogue_prompt} />
                      <KV label="Section 9" value={selectedProduct.section_9_overlay_prompt} />
                      <KV label="Missing" value={selectedProduct.prompt_missing_fields?.join(', ') || 'NONE'} />
                    </div>
                  </div>

                  <div className="rounded-2xl border p-4" style={{ borderColor: 'var(--border)', background: 'rgba(15,23,42,0.32)' }}>
                    <div className="text-xs font-semibold mb-3" style={{ color: 'var(--text)' }}>Edit Product Intelligence</div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <input value={editDraft.product_short_name || ''} onChange={event => setEditDraft(current => ({ ...current, product_short_name: event.target.value }))} placeholder="Short name" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.product_display_name || ''} onChange={event => setEditDraft(current => ({ ...current, product_display_name: event.target.value }))} placeholder="Display name" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.category || ''} onChange={event => setEditDraft(current => ({ ...current, category: event.target.value }))} placeholder="Category" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.subcategory || ''} onChange={event => setEditDraft(current => ({ ...current, subcategory: event.target.value }))} placeholder="Subcategory" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.type || ''} onChange={event => setEditDraft(current => ({ ...current, type: event.target.value }))} placeholder="Type" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={String(editDraft.price || '')} onChange={event => setEditDraft(current => ({ ...current, price: event.target.value ? Number(event.target.value) : null }))} placeholder="Price" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.commission_rate || ''} onChange={event => setEditDraft(current => ({ ...current, commission_rate: event.target.value }))} placeholder="Commission rate" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.image_url || ''} onChange={event => setEditDraft(current => ({ ...current, image_url: event.target.value }))} placeholder="Image URL" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.copywriting_angle || ''} onChange={event => setEditDraft(current => ({ ...current, copywriting_angle: event.target.value }))} placeholder="Copywriting angle" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.claim_risk_level || ''} onChange={event => setEditDraft(current => ({ ...current, claim_risk_level: event.target.value }))} placeholder="Claim risk level" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.physics_class || ''} onChange={event => setEditDraft(current => ({ ...current, physics_class: event.target.value }))} placeholder="Physics class" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                      <input value={editDraft.recommended_grip || ''} onChange={event => setEditDraft(current => ({ ...current, recommended_grip: event.target.value }))} placeholder="Recommended grip" className="px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                    </div>
                    <textarea value={editDraft.camera_handling_notes || ''} onChange={event => setEditDraft(current => ({ ...current, camera_handling_notes: event.target.value }))} placeholder="Handling notes" rows={2} className="mt-3 w-full px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                    <textarea value={editDraft.section_5_product_physics_prompt || ''} onChange={event => setEditDraft(current => ({ ...current, section_5_product_physics_prompt: event.target.value }))} placeholder="Section 5 physics prompt" rows={3} className="mt-3 w-full px-3 py-2 rounded-xl text-sm" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }} />
                    <div className="mt-3 flex justify-end">
                      <button onClick={handleSaveDraft} disabled={saving} className="px-4 py-2 rounded-xl text-sm font-semibold" style={{ background: 'var(--primary)', color: 'white' }}>
                        {saving ? 'Saving...' : 'Save Product Intelligence'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}