import { useState, useEffect } from 'react'
import { Package, Plus, Play, X, Clock, Eye, List } from 'lucide-react'
import { fetchAPI, postAPI } from '../api/client'

interface Variant {
  variant_id: string
  variation_index: number
  hook_angle: string
  scene_context: string
  camera_route: string
  prompt_9_section: string
  readiness: string
  queue_status: string
}

interface Batch {
  id: string
  product_id: string
  quantity: number
  status: string
  created_at: string
  variants?: Variant[]
  events?: any[]
}

export default function BatchesPage() {
  const [batches, setBatches] = useState<Batch[]>([])
  const [products, setProducts] = useState<any[]>([])
  const [selectedProductId, setSelectedProductId] = useState('')
  const [quantity, setQuantity] = useState(5)
  const [selectedBatch, setSelectedBatch] = useState<Batch | null>(null)
  const [loading, setLoading] = useState(false)
  const [showPrompt, setShowPrompt] = useState<string | null>(null)

  useEffect(() => {
    fetchBatches()
    fetchProducts()
  }, [])

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
      const data = await fetchAPI('/api/products?limit=500') as any
      setProducts(data.items || [])
    } catch (err) {
      console.error('Failed to fetch products', err)
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
              <Plus size={14} /> New Batch Draft
            </h2>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-[10px] uppercase font-bold opacity-50">Select Product</label>
                <select 
                  className="bg-card border rounded px-2 py-1.5 text-xs w-full"
                  value={selectedProductId}
                  onChange={(e) => setSelectedProductId(e.target.value)}
                >
                  <option value="">-- Select --</option>
                  {products.map(p => (
                    <option key={p.id} value={p.id}>{p.product_short_name}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[10px] uppercase font-bold opacity-50">Quantity (Max 20)</label>
                <input 
                  type="number" 
                  min="1" 
                  max="20"
                  className="bg-card border rounded px-2 py-1.5 text-xs w-full"
                  value={quantity}
                  onChange={(e) => setQuantity(parseInt(e.target.value))}
                />
              </div>
              <button 
                onClick={handleCreateDraft}
                disabled={loading || !selectedProductId}
                className="mt-2 py-2 rounded text-xs font-bold bg-accent text-white hover:opacity-90 disabled:opacity-50"
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
              {batches.map(b => (
                <div 
                  key={b.id} 
                  onClick={() => handleViewBatch(b.id)}
                  className={`p-3 rounded border cursor-pointer transition-colors ${selectedBatch?.id === b.id ? 'border-accent bg-accent/5' : 'bg-surface hover:bg-card'}`}
                >
                  <div className="flex justify-between items-start mb-1">
                    <span className="text-[10px] font-mono opacity-50">{b.id.slice(0,8)}</span>
                    <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded-full ${
                      b.status === 'QUEUED' ? 'bg-blue-500/10 text-blue-500' :
                      b.status === 'COMPLETED' ? 'bg-green-500/10 text-green-500' :
                      b.status === 'DRAFT_BLOCKED' ? 'bg-red-500/10 text-red-500' :
                      'bg-gray-500/10 text-gray-400'
                    }`}>
                      {b.status}
                    </span>
                  </div>
                  <div className="text-xs font-semibold truncate">
                    {products.find(p => p.id === b.product_id)?.product_short_name || 'Unknown Product'}
                  </div>
                  <div className="flex justify-between items-center mt-2 text-[10px] opacity-60">
                    <span>{b.quantity} variants</span>
                    <span>{new Date(b.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
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
                    <p className="text-xs opacity-60">Product: {products.find(p => p.id === selectedBatch.product_id)?.product_short_name}</p>
                  </div>
                  <div className="flex gap-2">
                    {selectedBatch.status === 'DRAFT' && (
                      <button 
                        onClick={() => handleQueueBatch(selectedBatch.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-bold bg-green-600 text-white hover:bg-green-700"
                      >
                        <Play size={12} /> Queue Batch
                      </button>
                    )}
                    {['QUEUED', 'PROCESSING', 'DRAFT'].includes(selectedBatch.status) && (
                      <button 
                        onClick={() => handleCancelBatch(selectedBatch.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-bold border border-red-500/30 text-red-500 hover:bg-red-500/10"
                      >
                        <X size={12} /> Cancel
                      </button>
                    )}
                  </div>
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
                    <div key={v.variant_id} className="p-3 rounded border bg-surface flex flex-col gap-2">
                      <div className="flex justify-between items-center">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-accent">#{v.variation_index}</span>
                          <span className="text-xs font-semibold">{v.hook_angle}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                            v.queue_status === 'QUEUED' ? 'bg-blue-500/10 text-blue-500' :
                            v.queue_status === 'COMPLETED' ? 'bg-green-500/10 text-green-500' :
                            'bg-gray-500/10 text-gray-400'
                          }`}>
                            {v.queue_status}
                          </span>
                          <button 
                            onClick={() => setShowPrompt(showPrompt === v.variant_id ? null : v.variant_id)}
                            className="p-1 rounded hover:bg-card text-muted hover:text-accent"
                          >
                            <Eye size={14} />
                          </button>
                        </div>
                      </div>
                      <div className="flex gap-4 text-[10px] opacity-60">
                        <span><Clock size={10} className="inline mr-1" /> 8s</span>
                        <span>{v.camera_route}</span>
                        <span>{v.scene_context}</span>
                      </div>
                      {showPrompt === v.variant_id && (
                        <div className="mt-2 p-3 rounded bg-black/20 text-[10px] font-mono whitespace-pre-wrap leading-relaxed border border-white/5">
                          {v.prompt_9_section}
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
