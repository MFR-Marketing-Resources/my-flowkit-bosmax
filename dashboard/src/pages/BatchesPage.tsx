import { useState, useEffect } from 'react'
import {
  Package, Plus, Play, X, Clock, List, AlertCircle,
  ExternalLink, ShieldCheck, FileSearch, Terminal, ArrowRight, CheckCircle2,
  Lock, Unlock, Zap, History, Info, ShoppingBag
} from 'lucide-react'
import { fetchAPI, postAPI } from '../api/client'
import { ProductPicker } from '../components/batches/ProductPicker'
import type { Product, LocalAgentStatus } from '../types'

interface Variant {
  variant_id: string
  variation_index: number
  hook_angle: string
  scene_context: string
  camera_route: string
  prompt_9_section: string
  readiness: string
  queue_status: string
  blocked_reason?: string
  google_flow_mode?: string
  asset_strategy?: string
}

interface Batch {
  id: string
  product_id: string
  quantity: number
  status: string
  created_at: string
  mode?: string
  engine?: string
  duration?: number
  variants?: Variant[]
  events?: any[]
  dry_run_validated?: boolean
}

export default function BatchesPage() {
  const [batches, setBatches] = useState<Batch[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [selectedProductId, setSelectedProductId] = useState('')
  const [quantity, setQuantity] = useState(5)
  const [selectedBatch, setSelectedBatch] = useState<Batch | null>(null)
  const [health, setHealth] = useState<LocalAgentStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [showPrompt, setShowPrompt] = useState<string | null>(null)

  const selectedProductPreview = products.find(p => p.id === selectedProductId)

  useEffect(() => {
    fetchBatches()
    fetchProducts()
    fetchHealth()
    const timer = setInterval(() => {
      fetchBatches()
      fetchHealth()
    }, 10000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (selectedBatch && ['QUEUED', 'PROCESSING'].includes(selectedBatch.status)) {
      const timer = setInterval(() => handleViewBatch(selectedBatch.id), 5000)
      return () => clearInterval(timer)
    }
  }, [selectedBatch?.id, selectedBatch?.status])

  const fetchBatches = async () => {
    try {
      const data = await fetchAPI('/api/batches') as Batch[]
      setBatches(data)
    } catch (err) {
      console.error('Failed to fetch batches', err)
    }
  }

  const fetchProducts = async () => {
    try {
      // Load products with canonical API envelope
      const data = await fetchAPI('/api/products?limit=500&offset=0') as any
      const allItems = data.items || []

      // Client-side filter: exclude test products and prioritize FastMoss READY products
      const filtered = allItems.filter((p: Product) => !p.is_test_product)
      setProducts(filtered)
    } catch (err) {
      console.error('Failed to fetch products', err)
    }
  }

  const fetchHealth = async () => {
    try {
      const data = await fetchAPI('/api/local-agent/status') as LocalAgentStatus
      setHealth(data)
    } catch (err) {
      console.error('Failed to fetch health', err)
    }
  }

  const handleCreateDraft = async () => {
    if (!selectedProductId) return
    setLoading(true)
    try {
      const data = await postAPI('/api/batches/draft', {
        product_id: selectedProductId,
        quantity: quantity,
        platform: 'TikTok',
        mode: 'Frames',
        approval_required: true
      }) as any
      if (data.error) {
        alert(`Error: ${data.error}\n\n${data.safety?.errors?.join('\n') || ''}`)
      } else {
        fetchBatches()
        handleViewBatch(data.batch_id)
      }
    } catch (err) {
      console.error('Failed to create draft', err)
    } finally {
      setLoading(false)
    }
  }

  const handleViewBatch = async (id: string) => {
    try {
      const data = await fetchAPI(`/api/batches/${id}`) as Batch
      setSelectedBatch(data)
    } catch (err) {
      console.error('Failed to fetch batch detail', err)
    }
  }

  const handleQueueBatch = async (id: string) => {
    try {
      const data = await postAPI(`/api/batches/${id}/queue`, {}) as any
      if (data.error) alert(data.error)
      else handleViewBatch(id)
    } catch (err) {
      console.error('Failed to queue batch', err)
    }
  }

  const handleCancelBatch = async (id: string) => {
    try {
      const data = await postAPI(`/api/batches/${id}/cancel`, {}) as any
      if (data.error) alert(data.error)
      else handleViewBatch(id)
    } catch (err) {
      console.error('Failed to cancel batch', err)
    }
  }

  const handleExecuteNext = async (id: string, dryRun: boolean = true) => {
    setLoading(true)
    try {
      const data = await postAPI(`/api/batches/${id}/execute-next?dry_run=${dryRun}`, {}) as any
      if (data.error) {
        alert(`Execution Error: ${data.error}`)
      }
      handleViewBatch(id)
    } catch (err) {
      console.error('Failed to execute next', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-6 max-w-6xl">
      <header className="flex justify-between items-center">
        <div>
          <h1 className="text-xl font-bold">Batch Production</h1>
          <p className="text-xs opacity-60">Plan and schedule mass video generation</p>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Draft Creator & List */}
        <div className="lg:col-span-1 flex flex-col gap-6">
          <section className="p-4 rounded-lg border bg-surface flex flex-col gap-4">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <Plus size={14} className="text-accent" /> New Batch Draft
            </h2>
            <div className="flex flex-col gap-3">
              <ProductPicker
                products={products}
                selectedProductId={selectedProductId}
                onSelect={setSelectedProductId}
                loading={loading}
              />

              {selectedProductPreview && (
                <div className="p-3 rounded bg-card/50 border border-white/5 flex flex-col gap-2">
                  <div className="flex justify-between items-start">
                    <span className="text-[10px] font-bold opacity-40 uppercase tracking-wider">Product Preview</span>
                    <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded ${
                      selectedProductPreview.source === 'FASTMOSS' ? 'bg-purple-500/20 text-purple-400' : 'bg-white/10 text-white/40'
                    }`}>
                      {selectedProductPreview.source}
                    </span>
                  </div>

                  <div className="flex flex-col">
                    <span className="text-xs font-bold truncate">{selectedProductPreview.product_short_name}</span>
                    <span className="text-[9px] opacity-40 italic">{selectedProductPreview.category} / {selectedProductPreview.subcategory} / {selectedProductPreview.type}</span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 mt-1">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[8px] opacity-40 uppercase font-bold tracking-tighter">Images</span>
                      <span className={`text-[9px] font-bold ${selectedProductPreview.image_readiness_status === 'IMAGE_READY' || selectedProductPreview.image_readiness_status === 'IMAGE_CACHE_READY' ? 'text-green-500' : 'text-red-500'}`}>
                        {selectedProductPreview.image_readiness_status?.replace(/_/g, ' ') || 'MISSING'}
                      </span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[8px] opacity-40 uppercase font-bold tracking-tighter">Prompt</span>
                      <span className={`text-[9px] font-bold ${selectedProductPreview.prompt_readiness_status === 'READY' ? 'text-green-500' : 'text-orange-500'}`}>
                        {selectedProductPreview.prompt_readiness_status || 'NEEDS REVIEW'}
                      </span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[8px] opacity-40 uppercase font-bold tracking-tighter">Physics DNA</span>
                      <span className={`text-[9px] font-bold ${selectedProductPreview.physics_dna_status === 'READY' ? 'text-blue-400' : 'text-white/20'}`}>
                        {selectedProductPreview.physics_class || 'Standard'}
                      </span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[8px] opacity-40 uppercase font-bold tracking-tighter">Silo / Trigger</span>
                      <span className="text-[9px] font-bold opacity-60">
                        {selectedProductPreview.silo || 'NA'} / {selectedProductPreview.trigger_id || 'NA'}
                      </span>
                    </div>
                  </div>

                  {selectedProductPreview.prompt_readiness_status !== 'READY' && (
                    <div className="mt-2 p-2 rounded bg-orange-500/10 border border-orange-500/20 flex items-start gap-2">
                      <AlertCircle size={12} className="text-orange-500 shrink-0 mt-0.5" />
                      <span className="text-[9px] text-orange-200/80">Product needs review before batch execution is safe.</span>
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-1 mt-1">
                <label className="text-[10px] uppercase font-bold opacity-50">Quantity (Max 20)</label>
                <input
                  type="number"
                  min="1"
                  max="20"
                  className="bg-card border rounded px-3 py-2 text-xs w-full focus:border-accent outline-none"
                  value={quantity}
                  onChange={(e) => setQuantity(parseInt(e.target.value))}
                />
              </div>

              <button
                onClick={handleCreateDraft}
                disabled={loading || !selectedProductId || selectedProductPreview?.prompt_readiness_status !== 'READY'}
                className="mt-2 py-2.5 rounded text-xs font-bold bg-accent text-white hover:opacity-90 disabled:opacity-30 disabled:cursor-not-allowed transition-all shadow-lg shadow-accent/10"
              >
                {loading ? 'Creating...' : 'Create Batch Draft'}
              </button>
            </div>
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold flex items-center gap-2 px-1">
              <List size={14} /> Recent Batches
            </h2>
            <div className="flex flex-col gap-2">
              {batches.map(b => {
                const product = products.find(p => p.id === b.product_id)
                return (
                  <div
                    key={b.id}
                    onClick={() => handleViewBatch(b.id)}
                    className={`p-3 rounded border cursor-pointer transition-all ${selectedBatch?.id === b.id ? 'border-accent bg-accent/5 ring-1 ring-accent/20' : 'bg-surface hover:bg-card border-white/5'}`}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <div className="flex flex-col">
                        <span className="text-[9px] font-mono opacity-30 tracking-tighter">#{b.id.slice(0,8)}</span>
                        <div className="text-[10px] font-bold text-white/90 truncate max-w-[120px]">
                          {product ? product.product_short_name : (
                            <span className="text-orange-400 flex items-center gap-1">
                              <AlertCircle size={8} /> PRODUCT_LOOKUP_FAILED
                            </span>
                          )}
                        </div>
                      </div>
                      <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded-full ${
                        b.status === 'QUEUED' ? 'bg-blue-500/20 text-blue-400' :
                        b.status === 'COMPLETED' ? 'bg-green-500/20 text-green-400' :
                        b.status === 'PROCESSING' ? 'bg-accent/20 text-accent' :
                        b.status === 'DRAFT_BLOCKED' ? 'bg-red-500/20 text-red-400' :
                        'bg-white/5 text-white/40'
                      }`}>
                        {b.status}
                      </span>
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <div className="flex justify-between items-center text-[9px] opacity-40">
                        <div className="flex items-center gap-1">
                          <ShoppingBag size={8} />
                          <span>{product?.source || 'UNKNOWN'}</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <Zap size={8} />
                          <span>{b.mode || 'Frames'}</span>
                        </div>
                      </div>
                      <div className="flex justify-between items-center mt-1">
                        <div className="flex items-center gap-1.5">
                          <Package size={10} className="opacity-30" />
                          <span className="text-[10px] font-bold">{b.quantity} variants</span>
                        </div>
                        <span className="text-[9px] opacity-30">{new Date(b.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {new Date(b.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                  </div>
                )
              })}
              {batches.length === 0 && (
                <div className="p-8 border-2 border-dashed rounded-xl flex flex-col items-center justify-center gap-2 opacity-20 italic">
                  <History size={24} />
                  <span className="text-xs font-semibold">No batches yet</span>
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Right Column: Batch Details */}
        <div className="lg:col-span-2">
          {selectedBatch ? (
            <div className="flex flex-col gap-6">
              <section className="p-4 rounded-lg border bg-surface border-l-4" style={{ borderLeftColor: 'var(--accent)' }}>
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <h2 className="text-lg font-bold flex items-center gap-2">
                      Batch Detail <span className="text-xs font-mono opacity-40">#{selectedBatch.id.slice(0,13)}</span>
                    </h2>
                    <div className="flex items-center gap-2 mt-0.5">
                      <p className="text-xs opacity-60">Product: <span className="font-bold text-accent">{products.find(p => p.id === selectedBatch.product_id)?.product_short_name || 'Unknown'}</span></p>
                      <span className="text-[10px] opacity-20 font-mono tracking-tighter">({selectedBatch.product_id})</span>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {selectedBatch.status === 'DRAFT' && (
                      <button
                        onClick={() => handleQueueBatch(selectedBatch.id)}
                        className="flex items-center gap-1.5 px-4 py-2 rounded text-xs font-bold bg-green-600 text-white hover:bg-green-700 shadow-lg shadow-green-600/10 transition-all"
                      >
                        <Play size={12} /> Queue Batch
                      </button>
                    )}
                    {selectedBatch.status === 'QUEUED' && (
                      <>
                        <button
                          onClick={() => handleExecuteNext(selectedBatch.id, true)}
                          disabled={loading}
                          className="flex items-center gap-1.5 px-4 py-2 rounded text-xs font-bold border border-accent text-accent hover:bg-accent/10 disabled:opacity-50 transition-all"
                        >
                          <Terminal size={12} /> Dry Run Next
                        </button>
                        <button
                          onClick={() => {
                            if (window.confirm('Execute LIVE variant in Google Flow? This will consume credits.')) {
                              handleExecuteNext(selectedBatch.id, false)
                            }
                          }}
                          disabled={loading || !selectedBatch.dry_run_validated}
                          className={`flex items-center gap-1.5 px-4 py-2 rounded text-xs font-bold transition-all shadow-lg ${
                            selectedBatch.dry_run_validated
                            ? 'bg-red-600 text-white hover:bg-red-700 shadow-red-600/20'
                            : 'bg-white/5 text-white/20 cursor-not-allowed border border-white/5'
                          }`}
                        >
                          {selectedBatch.dry_run_validated ? <Zap size={12} /> : <Lock size={12} />} Execute Live
                        </button>
                      </>
                    )}
                    {['QUEUED', 'PROCESSING', 'DRAFT'].includes(selectedBatch.status) && (
                      <button
                        onClick={() => handleCancelBatch(selectedBatch.id)}
                        className="flex items-center gap-1.5 px-4 py-2 rounded text-xs font-bold border border-red-500/30 text-red-500 hover:bg-red-500/10 transition-all"
                      >
                        <X size={12} /> Cancel
                      </button>
                    )}
                  </div>
                </div>

                {/* Execution Readiness Safety Panel */}
                <div className="mb-6 p-4 rounded-lg bg-card/30 border border-white/5 flex flex-col gap-3">
                  <div className="flex justify-between items-center">
                    <h3 className="text-[10px] font-bold uppercase tracking-widest opacity-40 flex items-center gap-2">
                      <ShieldCheck size={12} className="text-accent" /> Execution Readiness
                    </h3>
                    <div className="flex items-center gap-1.5">
                      <div className={`w-2 h-2 rounded-full animate-pulse ${health?.extension_connected ? 'bg-green-500' : 'bg-red-500'}`} />
                      <span className="text-[10px] font-bold opacity-60">Local Agent: {health?.extension_connected ? 'ONLINE' : 'OFFLINE'}</span>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="flex flex-col gap-1">
                      <div className="flex justify-between items-center">
                        <span className="text-[9px] opacity-40">Extension Bridge</span>
                        {health?.extension_connected ? <CheckCircle2 size={10} className="text-green-500" /> : <X size={10} className="text-red-500" />}
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-[9px] opacity-40">Google Flow Tab</span>
                        {health?.extension_state !== 'OFF' ? <CheckCircle2 size={10} className="text-green-500" /> : <AlertCircle size={10} className="text-orange-500" />}
                      </div>
                    </div>
                    <div className="flex flex-col gap-1">
                      <div className="flex justify-between items-center">
                        <span className="text-[9px] opacity-40">Dry Run Status</span>
                        {selectedBatch.dry_run_validated ? <CheckCircle2 size={10} className="text-green-500" /> : <span className="text-[8px] font-bold text-orange-500">PENDING</span>}
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-[9px] opacity-40">Live Execution</span>
                        {selectedBatch.dry_run_validated ? <Unlock size={10} className="text-green-500" /> : <Lock size={10} className="text-red-500" />}
                      </div>
                    </div>
                    <div className="flex flex-col gap-1">
                      <div className="flex justify-between items-center">
                        <span className="text-[9px] opacity-40">Queued Variants</span>
                        <span className="text-[10px] font-bold text-accent">{selectedBatch.variants?.filter(v => v.queue_status === 'QUEUED').length || 0}</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-[9px] opacity-40">Prompt Compiled</span>
                        <span className="text-[10px] font-bold text-green-500">{selectedBatch.variants?.filter(v => v.prompt_9_section).length || 0}</span>
                      </div>
                    </div>
                  </div>

                  {!selectedBatch.dry_run_validated && selectedBatch.status === 'QUEUED' && (
                    <div className="mt-2 p-2 rounded bg-accent/5 border border-accent/20 flex items-center gap-2">
                      <Info size={12} className="text-accent shrink-0" />
                      <span className="text-[10px] text-accent/80 italic">Dry run required before live execution is unlocked. Safety first.</span>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div className="p-2 rounded bg-card/50 border">
                    <div className="text-[10px] uppercase font-bold opacity-40">Status</div>
                    <div className="text-sm font-semibold">{selectedBatch.status}</div>
                  </div>
                  <div className="p-2 rounded bg-card/50 border">
                    <div className="text-[10px] uppercase font-bold opacity-40">Variants</div>
                    <div className="text-sm font-semibold">{selectedBatch.quantity}</div>
                  </div>
                  <div className="p-2 rounded bg-card/50 border">
                    <div className="text-[10px] uppercase font-bold opacity-40">Mode</div>
                    <div className="text-sm font-semibold">{(selectedBatch as any).mode || 'Frames'}</div>
                  </div>
                  <div className="p-2 rounded bg-card/50 border">
                    <div className="text-[10px] uppercase font-bold opacity-40">Engine</div>
                    <div className="text-sm font-semibold">{(selectedBatch as any).engine || 'VEO_3_1'}</div>
                  </div>
                </div>
              </section>

              <section>
                <div className="flex justify-between items-center mb-3 px-1">
                  <h3 className="text-sm font-bold flex items-center gap-2">
                    <Package size={14} /> Variants Planning
                  </h3>
                </div>
                <div className="flex flex-col gap-2">
                  {selectedBatch.variants?.map(v => (
                    <div key={v.variant_id} className="p-4 rounded-lg border bg-surface flex flex-col gap-3 transition-all hover:border-accent/30 group">
                      <div className="flex justify-between items-start">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center text-xs font-bold text-accent">
                            {v.variation_index}
                          </div>
                          <div className="flex flex-col">
                            <span className="text-xs font-bold text-white/90">{v.hook_angle}</span>
                            <span className="text-[9px] font-mono opacity-30 tracking-tighter">#{v.variant_id.slice(0,8)}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${
                            v.queue_status === 'QUEUED' ? 'bg-blue-500/20 text-blue-400' :
                            v.queue_status === 'COMPLETED' ? 'bg-green-500/20 text-green-400' :
                            v.queue_status === 'PROCESSING' ? 'bg-accent/20 text-accent' :
                            'bg-white/5 text-white/40'
                          }`}>
                            {v.queue_status}
                          </span>
                          <button
                            onClick={() => setShowPrompt(showPrompt === v.variant_id ? null : v.variant_id)}
                            className={`p-1.5 rounded transition-all ${showPrompt === v.variant_id ? 'bg-accent text-white' : 'bg-white/5 text-white/40 hover:text-accent hover:bg-accent/10'}`}
                            title="Toggle Prompt Preview"
                          >
                            <FileSearch size={14} />
                          </button>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-[10px] opacity-60 bg-black/10 p-2 rounded border border-white/5">
                        <div className="flex items-center gap-1.5">
                          <Clock size={10} className="text-accent/50" />
                          <span>8s Duration</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <Zap size={10} className="text-accent/50" />
                          <span>{v.google_flow_mode || 'Frames'}</span>
                        </div>
                        <div className="flex items-center gap-1.5 truncate">
                          <ExternalLink size={10} className="text-accent/50" />
                          <span className="truncate">{v.camera_route}</span>
                        </div>
                        <div className="flex items-center gap-1.5 truncate">
                          <ShoppingBag size={10} className="text-accent/50" />
                          <span className="truncate">{v.asset_strategy || 'Default'}</span>
                        </div>
                      </div>

                      <div className="text-[10px] opacity-40 italic flex items-start gap-1.5 px-1">
                        <ArrowRight size={10} className="shrink-0 mt-0.5" />
                        <span className="line-clamp-1">{v.scene_context}</span>
                      </div>

                      {v.blocked_reason && (
                        <div className="text-[9px] text-red-400 bg-red-500/10 p-3 rounded-lg border border-red-500/20 flex items-start gap-2">
                          <AlertCircle size={14} className="shrink-0" />
                          <div className="flex flex-col gap-0.5">
                            <strong className="uppercase font-bold tracking-widest text-[8px]">Blocked Reason</strong>
                            <span>{v.blocked_reason}</span>
                          </div>
                        </div>
                      )}

                      {showPrompt === v.variant_id && (
                        <div className="mt-2 flex flex-col gap-2">
                          <div className="flex justify-between items-center px-1">
                            <span className="text-[8px] font-bold uppercase tracking-widest opacity-40">Google Flow Prompt (Compiled)</span>
                            <button
                              onClick={() => {
                                navigator.clipboard.writeText(v.prompt_9_section)
                                alert('Prompt copied to clipboard!')
                              }}
                              className="text-[9px] font-bold text-accent hover:underline flex items-center gap-1"
                            >
                              Copy Prompt
                            </button>
                          </div>
                          <div className="p-4 rounded-xl bg-black/40 text-[10px] font-mono whitespace-pre-wrap leading-relaxed border border-white/5 shadow-inner">
                            {v.prompt_9_section}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </section>

              <section>
                <h3 className="text-sm font-bold flex items-center gap-2 mb-3 px-1">
                  <Clock size={14} /> Events Log
                </h3>
                <div className="flex flex-col gap-2">
                  {selectedBatch.events?.map((e, idx) => (
                    <div key={idx} className="flex gap-3 text-xs p-2 border-l-2 border-border">
                      <span className="opacity-40 font-mono whitespace-nowrap">{new Date(e.timestamp).toLocaleTimeString()}</span>
                      <span className="font-bold whitespace-nowrap" style={{ color: e.status === 'CANCELLED' ? 'var(--red)' : 'var(--accent)' }}>{e.status}</span>
                      <span className="opacity-80">{e.message}</span>
                    </div>
                  ))}
                  {(!selectedBatch.events || selectedBatch.events.length === 0) && (
                    <div className="text-xs opacity-40 italic p-2">No events logged yet.</div>
                  )}
                </div>
              </section>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center opacity-30 gap-3 border-2 border-dashed rounded-xl">
              <Package size={48} />
              <div className="text-sm font-semibold">Select a batch to view details</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
