import { useState, useEffect } from 'react'
import {
  Package, Plus, Play, X, Clock, AlertCircle,
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
    <div className="flex flex-col h-[calc(100vh-64px)] max-w-[1600px] mx-auto gap-4 overflow-hidden px-4">
      <header className="flex justify-between items-center shrink-0 pt-2">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Batch Production</h1>
          <p className="text-xs opacity-50 font-medium">Plan and schedule mass video generation</p>
        </div>
      </header>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[420px_1fr] gap-6 min-h-0 pb-4">
        {/* Left Column: Draft Creator & List */}
        <div className="flex flex-col gap-6 min-h-0">
          <section className="p-5 rounded-xl border border-white/5 bg-surface shadow-xl flex flex-col gap-5 shrink-0">
            <h2 className="text-sm font-bold flex items-center gap-2 text-white/90">
              <Plus size={16} className="text-accent" /> New Batch Draft
            </h2>
            <div className="flex flex-col gap-4">
              <ProductPicker
                products={products}
                selectedProductId={selectedProductId}
                onSelect={setSelectedProductId}
                loading={loading}
              />

              {selectedProductPreview && (
                <div className="p-4 rounded-lg bg-black/30 border border-white/5 flex flex-col gap-3 animate-in fade-in slide-in-from-top-2 duration-300">
                  <div className="flex justify-between items-start">
                    <span className="text-[10px] font-bold opacity-30 uppercase tracking-widest">Product Preview</span>
                    <span className={`text-[9px] font-black px-2 py-0.5 rounded-sm ${
                      selectedProductPreview.source === 'FASTMOSS' ? 'bg-purple-500/20 text-purple-400 border border-purple-500/20' : 'bg-white/10 text-white/40'
                    }`}>
                      {selectedProductPreview.source}
                    </span>
                  </div>

                  <div className="flex flex-col gap-0.5">
                    <span className="text-sm font-bold text-white/90 truncate">{selectedProductPreview.product_short_name}</span>
                    <span className="text-[10px] opacity-40 font-medium truncate">{selectedProductPreview.category} • {selectedProductPreview.subcategory} • {selectedProductPreview.type}</span>
                  </div>

                  <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-1">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[9px] opacity-30 uppercase font-black tracking-tight">Images</span>
                      <span className={`text-[10px] font-bold flex items-center gap-1 ${selectedProductPreview.image_readiness_status === 'IMAGE_READY' || selectedProductPreview.image_readiness_status === 'IMAGE_CACHE_READY' ? 'text-green-500' : 'text-red-500'}`}>
                        {selectedProductPreview.image_readiness_status === 'IMAGE_READY' || selectedProductPreview.image_readiness_status === 'IMAGE_CACHE_READY' ? <CheckCircle2 size={10} /> : <AlertCircle size={10} />}
                        {selectedProductPreview.image_readiness_status?.replace(/_/g, ' ') || 'MISSING'}
                      </span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[9px] opacity-30 uppercase font-black tracking-tight">Prompt</span>
                      <span className={`text-[10px] font-bold flex items-center gap-1 ${selectedProductPreview.prompt_readiness_status === 'READY' ? 'text-green-500' : 'text-orange-500'}`}>
                        {selectedProductPreview.prompt_readiness_status === 'READY' ? <CheckCircle2 size={10} /> : <AlertCircle size={10} />}
                        {selectedProductPreview.prompt_readiness_status || 'NEEDS REVIEW'}
                      </span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[9px] opacity-30 uppercase font-black tracking-tight">Physics DNA</span>
                      <span className="text-[10px] font-bold text-blue-400 opacity-80">{selectedProductPreview.physics_class || 'Standard'}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[9px] opacity-30 uppercase font-black tracking-tight">Logic</span>
                      <span className="text-[10px] font-bold opacity-60 truncate">
                        {selectedProductPreview.silo || 'NA'} / {selectedProductPreview.trigger_id || 'NA'}
                      </span>
                    </div>
                  </div>

                  {selectedProductPreview.prompt_readiness_status !== 'READY' && (
                    <div className="mt-1 p-2.5 rounded-md bg-orange-500/10 border border-orange-500/20 flex items-start gap-2">
                      <AlertCircle size={14} className="text-orange-500 shrink-0 mt-0.5" />
                      <span className="text-[10px] text-orange-200/70 font-medium leading-relaxed">Safety Alert: Product requires field review before batch production is allowed.</span>
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] uppercase font-bold opacity-40 tracking-wider">Quantity (Max 20)</label>
                <input
                  type="number"
                  min="1"
                  max="20"
                  className="bg-black/20 border border-white/5 rounded-lg px-4 py-2.5 text-sm w-full focus:border-accent outline-none transition-all placeholder:opacity-20"
                  value={quantity}
                  onChange={(e) => setQuantity(parseInt(e.target.value))}
                />
              </div>

              <button
                onClick={handleCreateDraft}
                disabled={loading || !selectedProductId || selectedProductPreview?.prompt_readiness_status !== 'READY'}
                className="mt-2 py-3 rounded-xl text-sm font-bold bg-accent text-white hover:opacity-90 disabled:opacity-20 disabled:cursor-not-allowed transition-all shadow-xl shadow-accent/20 flex items-center justify-center gap-2"
              >
                {loading ? (
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <><Plus size={16} /> Create Batch Draft</>
                )}
              </button>
            </div>
          </section>

          <section className="flex-1 flex flex-col min-h-0 bg-surface/30 rounded-xl border border-white/5 overflow-hidden">
            <h2 className="text-xs font-black uppercase tracking-[0.2em] opacity-30 px-5 pt-4 pb-3 flex items-center gap-2 shrink-0">
              <History size={14} /> Recent Batches
            </h2>
            <div className="flex-1 overflow-y-auto px-4 pb-4 custom-scrollbar">
              <div className="flex flex-col gap-3">
                {batches.map(b => {
                  const product = products.find(p => p.id === b.product_id)
                  return (
                    <div
                      key={b.id}
                      onClick={() => handleViewBatch(b.id)}
                      className={`p-4 rounded-xl border cursor-pointer transition-all hover:scale-[1.01] active:scale-[0.99] ${selectedBatch?.id === b.id ? 'border-accent bg-accent/5 ring-1 ring-accent/20' : 'bg-card/50 hover:bg-card border-white/5'}`}
                    >
                      <div className="flex justify-between items-start mb-3">
                        <div className="flex flex-col gap-0.5">
                          <span className="text-[10px] font-mono opacity-30 tracking-tight">#{b.id.slice(0,8)}</span>
                          <div className="text-xs font-bold text-white/90 truncate max-w-[200px]">
                            {product ? product.product_short_name : (
                              <span className="text-orange-500/80 flex items-center gap-1.5 italic">
                                <AlertCircle size={10} /> PRODUCT_LOOKUP_FAILED
                              </span>
                            )}
                          </div>
                        </div>
                        <span className={`text-[9px] font-black tracking-widest px-2 py-0.5 rounded-full border ${
                          b.status === 'QUEUED' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                          b.status === 'COMPLETED' ? 'bg-green-500/10 text-green-400 border-green-500/20' :
                          b.status === 'PROCESSING' ? 'bg-accent/10 text-accent border-accent/20' :
                          b.status === 'DRAFT_BLOCKED' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                          'bg-white/5 text-white/30 border-white/10'
                        }`}>
                          {b.status}
                        </span>
                      </div>

                      <div className="flex flex-col gap-2.5">
                        <div className="flex justify-between items-center text-[10px] font-medium opacity-40">
                          <div className="flex items-center gap-1.5">
                            <ShoppingBag size={10} className="text-accent/50" />
                            <span>{product?.source || 'ID: ' + b.product_id.slice(0,8)}</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <Zap size={10} className="text-accent/50" />
                            <span>{b.mode || 'Frames'}</span>
                          </div>
                        </div>
                        <div className="flex justify-between items-center border-t border-white/5 pt-2.5">
                          <div className="flex items-center gap-2">
                            <Package size={12} className="opacity-30" />
                            <span className="text-[11px] font-bold text-white/70">{b.quantity} Variants</span>
                          </div>
                          <span className="text-[10px] font-mono opacity-30">{new Date(b.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
                {batches.length === 0 && (
                  <div className="p-12 flex flex-col items-center justify-center gap-4 opacity-20 text-center">
                    <History size={40} strokeWidth={1} />
                    <span className="text-xs font-bold uppercase tracking-widest leading-loose">No production history found.<br/>Create a draft to begin.</span>
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>

        {/* Right Column: Batch Details */}
        <div className="flex flex-col min-h-0 bg-surface/20 rounded-2xl border border-white/5 overflow-hidden shadow-inner">
          {selectedBatch ? (
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              <div className="p-6 flex flex-col gap-8 max-w-5xl mx-auto">
                <section className="p-6 rounded-2xl border border-white/10 bg-card/40 shadow-2xl relative overflow-hidden group">
                  <div className="absolute top-0 left-0 w-1.5 h-full bg-accent opacity-80" />
                  <div className="flex justify-between items-start mb-8">
                    <div className="flex flex-col gap-1.5">
                      <div className="flex items-center gap-3">
                        <h2 className="text-2xl font-black tracking-tight text-white/90">Batch Details</h2>
                        <span className="px-2 py-0.5 bg-white/5 border border-white/10 rounded font-mono text-[11px] opacity-40">#{selectedBatch.id}</span>
                      </div>
                      <div className="flex items-center gap-3 mt-1">
                        <p className="text-sm font-medium opacity-50">Target Product</p>
                        <ArrowRight size={14} className="opacity-20" />
                        <span className="text-sm font-bold text-accent px-2 py-0.5 bg-accent/10 rounded border border-accent/20">
                          {products.find(p => p.id === selectedBatch.product_id)?.product_short_name || selectedBatch.product_id}
                        </span>
                      </div>
                    </div>
                    <div className="flex gap-3">
                      {selectedBatch.status === 'DRAFT' && (
                        <button
                          onClick={() => handleQueueBatch(selectedBatch.id)}
                          className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-black bg-green-600 text-white hover:bg-green-500 shadow-xl shadow-green-900/20 transition-all hover:scale-105 active:scale-95"
                        >
                          <Play size={16} fill="currentColor" /> QUEUE BATCH
                        </button>
                      )}
                      {selectedBatch.status === 'QUEUED' && (
                        <>
                          <button
                            onClick={() => handleExecuteNext(selectedBatch.id, true)}
                            disabled={loading}
                            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold border border-accent/30 text-accent hover:bg-accent/10 disabled:opacity-50 transition-all active:scale-95"
                          >
                            <Terminal size={16} /> DRY RUN NEXT
                          </button>
                          <button
                            onClick={() => {
                              if (window.confirm('DANGER: Execute LIVE variant in Google Flow? This will consume production credits.')) {
                                handleExecuteNext(selectedBatch.id, false)
                              }
                            }}
                            disabled={loading || !selectedBatch.dry_run_validated}
                            className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-black transition-all shadow-2xl active:scale-95 ${
                              selectedBatch.dry_run_validated
                              ? 'bg-red-600 text-white hover:bg-red-500 shadow-red-900/40 hover:scale-105'
                              : 'bg-white/5 text-white/20 cursor-not-allowed border border-white/5 opacity-50'
                            }`}
                          >
                            {selectedBatch.dry_run_validated ? <Zap size={16} fill="currentColor" /> : <Lock size={16} />} EXECUTE LIVE
                          </button>
                        </>
                      )}
                      {['QUEUED', 'PROCESSING', 'DRAFT'].includes(selectedBatch.status) && (
                        <button
                          onClick={() => handleCancelBatch(selectedBatch.id)}
                          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold border border-red-500/20 text-red-500/70 hover:bg-red-500/10 transition-all active:scale-95"
                        >
                          <X size={16} /> CANCEL
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Execution Readiness Safety Panel */}
                  <div className="p-5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-4 shadow-inner">
                    <div className="flex justify-between items-center border-b border-white/5 pb-3">
                      <h3 className="text-[11px] font-black uppercase tracking-[0.2em] opacity-40 flex items-center gap-2">
                        <ShieldCheck size={14} className="text-accent" /> Execution Integrity
                      </h3>
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2 px-2 py-1 rounded bg-white/5 border border-white/10">
                          <div className={`w-2 h-2 rounded-full ${health?.extension_connected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]'}`} />
                          <span className="text-[10px] font-black opacity-60 tracking-wider">LOCAL AGENT: {health?.extension_connected ? 'ONLINE' : 'OFFLINE'}</span>
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                      <div className="flex flex-col gap-2.5">
                        <div className="flex justify-between items-center px-1">
                          <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Bridge Connection</span>
                          {health?.extension_connected ? <CheckCircle2 size={12} className="text-green-500" /> : <X size={12} className="text-red-500" />}
                        </div>
                        <div className="flex justify-between items-center px-1">
                          <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Flow Tab Status</span>
                          {health?.extension_state !== 'OFF' ? <CheckCircle2 size={12} className="text-green-500" /> : <AlertCircle size={12} className="text-orange-500" />}
                        </div>
                      </div>
                      <div className="flex flex-col gap-2.5 border-x border-white/5 px-4">
                        <div className="flex justify-between items-center px-1">
                          <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Dry Run Validated</span>
                          {selectedBatch.dry_run_validated ? <CheckCircle2 size={12} className="text-green-500" /> : <span className="text-[9px] font-black text-orange-500 tracking-widest">LOCKED</span>}
                        </div>
                        <div className="flex justify-between items-center px-1">
                          <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Safety Interlock</span>
                          {selectedBatch.dry_run_validated ? <Unlock size={12} className="text-green-500" /> : <Lock size={12} className="text-red-500" />}
                        </div>
                      </div>
                      <div className="flex flex-col gap-2.5">
                        <div className="flex justify-between items-center px-1">
                          <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Queue Depth</span>
                          <span className="text-[11px] font-black text-accent">{selectedBatch.variants?.filter(v => v.queue_status === 'QUEUED').length || 0} / {selectedBatch.quantity}</span>
                        </div>
                        <div className="flex justify-between items-center px-1">
                          <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Prompts Ready</span>
                          <span className="text-[11px] font-black text-green-500/80">{selectedBatch.variants?.filter(v => v.prompt_9_section).length || 0}</span>
                        </div>
                      </div>
                    </div>

                    {!selectedBatch.dry_run_validated && selectedBatch.status === 'QUEUED' && (
                      <div className="mt-1 p-3 rounded-lg bg-accent/5 border border-accent/20 flex items-center gap-3 animate-pulse">
                        <Info size={14} className="text-accent shrink-0" />
                        <span className="text-[11px] text-accent/80 font-bold italic tracking-wide">Operator Notice: Live execution is locked. Perform a successful Dry Run to bypass the safety interlock.</span>
                      </div>
                    )}
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
                    <div className="p-3 rounded-xl bg-black/20 border border-white/5">
                      <div className="text-[10px] uppercase font-black tracking-[0.1em] opacity-30 mb-1">Pipeline Status</div>
                      <div className="text-sm font-bold text-white/80">{selectedBatch.status}</div>
                    </div>
                    <div className="p-3 rounded-xl bg-black/20 border border-white/5">
                      <div className="text-[10px] uppercase font-black tracking-[0.1em] opacity-30 mb-1">Payload Size</div>
                      <div className="text-sm font-bold text-white/80">{selectedBatch.quantity} Variants</div>
                    </div>
                    <div className="p-3 rounded-xl bg-black/20 border border-white/5">
                      <div className="text-[10px] uppercase font-black tracking-[0.1em] opacity-30 mb-1">Flow Mode</div>
                      <div className="text-sm font-bold text-white/80">{(selectedBatch as any).mode || 'Frames'}</div>
                    </div>
                    <div className="p-3 rounded-xl bg-black/20 border border-white/5">
                      <div className="text-[10px] uppercase font-black tracking-[0.1em] opacity-30 mb-1">Generation Engine</div>
                      <div className="text-sm font-bold text-white/80">{(selectedBatch as any).engine || 'VEO_3_1'}</div>
                    </div>
                  </div>
                </section>

                <section className="flex flex-col gap-4">
                  <div className="flex justify-between items-center px-1">
                    <h3 className="text-lg font-black tracking-tight flex items-center gap-2 text-white/90">
                      <Package size={20} className="text-accent" /> Variants Planning
                    </h3>
                    <div className="px-3 py-1 bg-white/5 border border-white/10 rounded-full text-[10px] font-bold opacity-40">
                      SYSTEM GENERATED • {selectedBatch.variants?.length || 0} SLOTS
                    </div>
                  </div>
                  <div className="flex flex-col gap-3">
                    {selectedBatch.variants?.map(v => (
                      <div key={v.variant_id} className="p-5 rounded-2xl border border-white/5 bg-card/30 flex flex-col gap-4 transition-all hover:bg-card/50 hover:border-accent/20 group relative overflow-hidden">
                        {v.queue_status === 'PROCESSING' && <div className="absolute top-0 left-0 w-full h-0.5 bg-accent animate-pulse" />}
                        <div className="flex justify-between items-start relative z-10">
                          <div className="flex items-center gap-4">
                            <div className="w-10 h-10 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center text-sm font-black text-accent shadow-inner">
                              {v.variation_index}
                            </div>
                            <div className="flex flex-col gap-0.5">
                              <span className="text-sm font-black text-white/90 tracking-tight">{v.hook_angle}</span>
                              <span className="text-[10px] font-mono opacity-30 tracking-tight">VARIANT_ID: {v.variant_id}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-4">
                            <span className={`text-[10px] font-black tracking-[0.1em] px-3 py-1 rounded-full border ${
                              v.queue_status === 'QUEUED' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                              v.queue_status === 'COMPLETED' ? 'bg-green-500/10 text-green-400 border-green-500/20' :
                              v.queue_status === 'PROCESSING' ? 'bg-accent/10 text-accent border-accent/20' :
                              'bg-white/5 text-white/30 border-white/10'
                            }`}>
                              {v.queue_status}
                            </span>
                            <button
                              onClick={() => setShowPrompt(showPrompt === v.variant_id ? null : v.variant_id)}
                              className={`p-2 rounded-xl transition-all shadow-lg ${showPrompt === v.variant_id ? 'bg-accent text-white scale-110' : 'bg-white/5 text-white/40 hover:text-accent hover:bg-accent/10 hover:scale-105'}`}
                              title="Toggle Forensic Prompt"
                            >
                              <FileSearch size={18} />
                            </button>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-[10px] font-bold opacity-60 bg-black/20 p-3 rounded-xl border border-white/5">
                          <div className="flex items-center gap-2">
                            <Clock size={12} className="text-accent/60" />
                            <span className="tracking-wide">8.0s Duration</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <Zap size={12} className="text-accent/60" />
                            <span className="tracking-wide uppercase">{v.google_flow_mode || 'Frames'}</span>
                          </div>
                          <div className="flex items-center gap-2 min-w-0">
                            <ExternalLink size={12} className="text-accent/60 shrink-0" />
                            <span className="truncate tracking-wide">{v.camera_route}</span>
                          </div>
                          <div className="flex items-center gap-2 min-w-0">
                            <ShoppingBag size={12} className="text-accent/60 shrink-0" />
                            <span className="truncate tracking-wide">{v.asset_strategy || 'Default'}</span>
                          </div>
                        </div>

                        <div className="text-xs font-medium opacity-40 italic flex items-start gap-2.5 px-1 leading-relaxed">
                          <ArrowRight size={14} className="shrink-0 mt-0.5 opacity-30" />
                          <span className="line-clamp-2">{v.scene_context}</span>
                        </div>

                        {v.blocked_reason && (
                          <div className="text-xs text-red-400 bg-red-500/10 p-4 rounded-xl border border-red-500/20 flex items-start gap-3 shadow-inner">
                            <AlertCircle size={18} className="shrink-0 text-red-500" />
                            <div className="flex flex-col gap-1">
                              <strong className="uppercase font-black tracking-widest text-[10px] text-red-500/80">Execution Aborted</strong>
                              <span className="font-medium opacity-90 leading-relaxed">{v.blocked_reason}</span>
                            </div>
                          </div>
                        )}

                        {showPrompt === v.variant_id && (
                          <div className="mt-2 flex flex-col gap-3 animate-in zoom-in-95 duration-200">
                            <div className="flex justify-between items-center px-1">
                              <span className="text-[10px] font-black uppercase tracking-[0.2em] opacity-40">Forensic Prompt Stream</span>
                              <button
                                onClick={() => {
                                  navigator.clipboard.writeText(v.prompt_9_section)
                                  alert('Prompt copied to clipboard!')
                                }}
                                className="text-xs font-bold text-accent hover:text-white px-3 py-1 bg-accent/10 hover:bg-accent rounded-lg transition-all border border-accent/20"
                              >
                                COPY RAW
                              </button>
                            </div>
                            <div className="p-5 rounded-2xl bg-black/60 text-[11px] font-mono whitespace-pre-wrap leading-loose border border-white/10 shadow-2xl text-white/70">
                              {v.prompt_9_section}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </section>

                <section className="mb-8">
                  <h3 className="text-sm font-black uppercase tracking-[0.2em] opacity-30 flex items-center gap-2 mb-4 px-1">
                    <Clock size={16} /> Forensic Events Log
                  </h3>
                  <div className="flex flex-col gap-3">
                    {selectedBatch.events?.map((e, idx) => (
                      <div key={idx} className="flex gap-4 text-xs p-4 bg-white/5 rounded-xl border border-white/5 border-l-2 border-l-accent/50 transition-all hover:bg-white/10">
                        <span className="opacity-30 font-mono text-[10px] shrink-0 pt-0.5">{new Date(e.timestamp).toLocaleTimeString()}</span>
                        <div className="flex flex-col gap-1">
                          <span className="font-black tracking-widest text-[10px] uppercase" style={{ color: e.status === 'CANCELLED' ? 'var(--red)' : 'var(--accent)' }}>{e.status}</span>
                          <span className="opacity-70 font-medium leading-relaxed">{e.message}</span>
                        </div>
                      </div>
                    ))}
                    {(!selectedBatch.events || selectedBatch.events.length === 0) && (
                      <div className="text-xs opacity-20 italic p-6 border border-dashed border-white/10 rounded-2xl text-center">No forensic events captured for this batch instance.</div>
                    )}
                  </div>
                </section>
              </div>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center opacity-10 gap-6">
              <div className="p-8 rounded-full bg-white/5 border border-white/10">
                <Package size={80} strokeWidth={0.5} />
              </div>
              <div className="flex flex-col items-center gap-2">
                <span className="text-xl font-black uppercase tracking-[0.3em]">No Batch Selected</span>
                <span className="text-xs font-bold tracking-widest opacity-60">Select an instance from the left panel to begin forensic audit.</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
