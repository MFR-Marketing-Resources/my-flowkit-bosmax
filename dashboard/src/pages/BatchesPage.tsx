import { useState, useEffect, useRef } from 'react'
import {
  Package, Plus, Play, X, AlertCircle,
  ShieldCheck, FileSearch, Terminal, ArrowRight, CheckCircle2,
  Lock, Zap, History, Layers, Rocket, BarChart2,
  ChevronRight, RefreshCw, ExternalLink as LinkOut
} from 'lucide-react'
import { fetchAPI, postAPI } from '../api/client'
import { ProductPicker } from '../components/batches/ProductPicker'
import type { Product, LocalAgentStatus } from '../types'

// ─── Types ────────────────────────────────────────────────────────────────────

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

interface BatchRun {
  batch_run_id: string
  status: string
  product_id: string
  modes: string[]
  quantity_per_mode: number
  interval_seconds: number
  generation_mode: string
  total_expected: number
  total_completed: number
  total_failed: number
  error_log: string[]
  packages_count: number
  packages: string[]
  created_at: string
  updated_at: string
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MODES = ['F2V', 'I2V', 'T2V', 'IMG'] as const
type Mode = typeof MODES[number]

const MODE_COLORS: Record<Mode, string> = {
  F2V: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  I2V: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  T2V: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  IMG: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
}

const MODE_LABELS: Record<Mode, string> = {
  F2V: 'Frames → Video',
  I2V: 'Ingredients → Video',
  T2V: 'Text → Video',
  IMG: 'Image Gen',
}

// ─── Workspace Batch Tab ──────────────────────────────────────────────────────

function WorkspaceBatchTab({ products }: { products: Product[] }) {
  const [selectedProductId, setSelectedProductId] = useState('')
  const [selectedModes, setSelectedModes] = useState<Mode[]>(['F2V'])
  const [quantityPerMode, setQuantityPerMode] = useState(10)
  const [intervalSeconds, setIntervalSeconds] = useState(5)
  const [generationMode, setGenerationMode] = useState<'SINGLE' | 'EXTEND'>('SINGLE')
  const [isRunning, setIsRunning] = useState(false)
  const [currentRun, setCurrentRun] = useState<BatchRun | null>(null)
  const [recentRuns, setRecentRuns] = useState<BatchRun[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const selectedProduct = products.find(p => p.id === selectedProductId)
  const totalExpected = selectedModes.length * quantityPerMode
  const estimatedSeconds = totalExpected * intervalSeconds

  // Poll active run
  useEffect(() => {
    if (currentRun && ['PENDING', 'RUNNING'].includes(currentRun.status)) {
      pollRef.current = setInterval(async () => {
        try {
          const updated = await fetchAPI(`/api/workspace/generation-packages/batch/${currentRun.batch_run_id}`) as BatchRun
          setCurrentRun(updated)
          if (!['PENDING', 'RUNNING'].includes(updated.status)) {
            clearInterval(pollRef.current!)
            setIsRunning(false)
          }
        } catch {
          clearInterval(pollRef.current!)
          setIsRunning(false)
        }
      }, 2000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [currentRun?.batch_run_id, currentRun?.status])

  const toggleMode = (m: Mode) => {
    setSelectedModes(prev =>
      prev.includes(m) ? prev.filter(x => x !== m) : [...prev, m]
    )
  }

  const handleStartBatch = async () => {
    if (!selectedProductId || selectedModes.length === 0) return
    setIsRunning(true)
    try {
      const res = await postAPI('/api/workspace/generation-packages/batch', {
        product_id: selectedProductId,
        modes: selectedModes,
        quantity_per_mode: quantityPerMode,
        interval_seconds: intervalSeconds,
        generation_mode: generationMode,
      }) as any
      if (res.ok) {
        const run = await fetchAPI(`/api/workspace/generation-packages/batch/${res.batch_run_id}`) as BatchRun
        setCurrentRun(run)
        setRecentRuns(prev => [run, ...prev.slice(0, 9)])
      } else {
        alert(`Error: ${res.detail || 'Unknown error'}`)
        setIsRunning(false)
      }
    } catch (err: any) {
      alert(`Failed: ${err.message}`)
      setIsRunning(false)
    }
  }

  const progress = currentRun
    ? currentRun.total_expected > 0
      ? Math.round(((currentRun.total_completed + currentRun.total_failed) / currentRun.total_expected) * 100)
      : 0
    : 0

  const formatDuration = (sec: number) => {
    if (sec < 60) return `~${sec}s`
    return `~${Math.ceil(sec / 60)}min`
  }

  return (
    <div className="flex flex-col lg:flex-row gap-6 min-h-0 h-full">
      {/* Left: Config panel */}
      <div className="lg:w-[420px] shrink-0 flex flex-col gap-5">
        {/* Product */}
        <section className="p-5 rounded-xl border border-white/5 bg-surface shadow-xl flex flex-col gap-4">
          <h2 className="text-sm font-bold flex items-center gap-2 text-white/90">
            <Rocket size={15} className="text-accent" /> Workspace Batch Generator
          </h2>
          <p className="text-[11px] text-white/30 leading-relaxed -mt-1">
            Generates prompts directly to Prompt Handoff Bank for all selected modes.
          </p>

          <ProductPicker
            products={products}
            selectedProductId={selectedProductId}
            onSelect={setSelectedProductId}
            loading={isRunning}
          />

          {selectedProduct && selectedProduct.prompt_readiness_status !== 'READY' && (
            <div className="p-2.5 rounded-lg bg-orange-500/10 border border-orange-500/20 flex items-start gap-2">
              <AlertCircle size={13} className="text-orange-400 shrink-0 mt-0.5" />
              <span className="text-[10px] text-orange-200/70 font-medium">Product not ready for generation. Complete product setup first.</span>
            </div>
          )}
        </section>

        {/* Mode selector */}
        <section className="p-5 rounded-xl border border-white/5 bg-surface shadow-xl flex flex-col gap-4">
          <label className="text-[10px] uppercase font-black tracking-[0.18em] opacity-40">Modes</label>
          <div className="grid grid-cols-2 gap-2">
            {MODES.map(m => (
              <button
                key={m}
                type="button"
                onClick={() => toggleMode(m)}
                className={`flex flex-col gap-1 p-3 rounded-xl border text-left transition-all ${
                  selectedModes.includes(m)
                    ? `${MODE_COLORS[m]} ring-1 ring-current/30 scale-[1.02]`
                    : 'border-white/5 bg-white/3 text-white/30 hover:bg-white/5'
                }`}
              >
                <span className="text-[11px] font-black tracking-wide">{m}</span>
                <span className="text-[9px] opacity-60">{MODE_LABELS[m]}</span>
              </button>
            ))}
          </div>
          {selectedModes.length === 0 && (
            <span className="text-[10px] text-red-400/70">Select at least one mode</span>
          )}
        </section>

        {/* Quantity + Interval */}
        <section className="p-5 rounded-xl border border-white/5 bg-surface shadow-xl flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] uppercase font-black tracking-[0.18em] opacity-40">
              Quantity per Mode <span className="text-accent/60 normal-case font-medium">(min 10, max 100)</span>
            </label>
            <div className="flex items-center gap-3">
              <input
                type="range" min={10} max={100} step={5}
                value={quantityPerMode}
                onChange={e => setQuantityPerMode(Number(e.target.value))}
                className="flex-1 accent-accent"
                disabled={isRunning}
              />
              <span className="text-sm font-black text-accent w-8 text-right">{quantityPerMode}</span>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] uppercase font-black tracking-[0.18em] opacity-40">
              Interval Between Prompts
            </label>
            <div className="flex gap-2">
              {[3, 5, 10, 15].map(s => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setIntervalSeconds(s)}
                  disabled={isRunning}
                  className={`flex-1 py-1.5 rounded-lg text-[11px] font-bold border transition-all ${
                    intervalSeconds === s
                      ? 'bg-accent text-white border-accent'
                      : 'border-white/10 text-white/30 hover:border-white/20 hover:text-white/60'
                  }`}
                >
                  {s}s
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] uppercase font-black tracking-[0.18em] opacity-40">Generation Mode</label>
            <div className="flex gap-2">
              {(['SINGLE', 'EXTEND'] as const).map(gm => (
                <button
                  key={gm}
                  type="button"
                  onClick={() => setGenerationMode(gm)}
                  disabled={isRunning}
                  className={`flex-1 py-2 rounded-lg text-[11px] font-black border transition-all ${
                    generationMode === gm
                      ? 'bg-accent/15 text-accent border-accent/30'
                      : 'border-white/10 text-white/30 hover:border-white/20'
                  }`}
                >
                  {gm}
                </button>
              ))}
            </div>
          </div>

          {/* Summary */}
          <div className="p-3 rounded-xl bg-black/30 border border-white/5 grid grid-cols-3 gap-3">
            <div className="flex flex-col gap-0.5 items-center">
              <span className="text-[9px] opacity-30 uppercase font-black tracking-tight">Total Prompts</span>
              <span className="text-lg font-black text-accent">{totalExpected}</span>
            </div>
            <div className="flex flex-col gap-0.5 items-center border-x border-white/5">
              <span className="text-[9px] opacity-30 uppercase font-black tracking-tight">Est. Time</span>
              <span className="text-lg font-black text-white/70">{formatDuration(estimatedSeconds)}</span>
            </div>
            <div className="flex flex-col gap-0.5 items-center">
              <span className="text-[9px] opacity-30 uppercase font-black tracking-tight">Modes</span>
              <span className="text-lg font-black text-white/70">{selectedModes.length}</span>
            </div>
          </div>

          <button
            type="button"
            onClick={handleStartBatch}
            disabled={isRunning || !selectedProductId || selectedModes.length === 0 || selectedProduct?.prompt_readiness_status !== 'READY'}
            className="py-3 rounded-xl text-sm font-black bg-gradient-to-r from-accent to-purple-600 text-white hover:opacity-90 disabled:opacity-20 disabled:cursor-not-allowed transition-all shadow-xl shadow-accent/20 flex items-center justify-center gap-2"
          >
            {isRunning
              ? <><RefreshCw size={15} className="animate-spin" /> Generating...</>
              : <><Rocket size={15} /> Generate {totalExpected} Prompts</>
            }
          </button>
        </section>
      </div>

      {/* Right: Progress + recent runs */}
      <div className="flex-1 flex flex-col gap-5 min-h-0 overflow-y-auto custom-scrollbar pb-4">
        {/* Active run */}
        {currentRun && (
          <section className="p-5 rounded-xl border border-accent/20 bg-accent/5 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-black text-accent flex items-center gap-2">
                <BarChart2 size={15} /> Active Run
              </h3>
              <span className={`text-[10px] font-black tracking-widest px-2 py-0.5 rounded-full border ${
                currentRun.status === 'RUNNING' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20 animate-pulse' :
                currentRun.status === 'COMPLETED' ? 'bg-green-500/10 text-green-400 border-green-500/20' :
                currentRun.status === 'FAILED' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                'bg-white/5 text-white/30 border-white/10'
              }`}>
                {currentRun.status}
              </span>
            </div>

            {/* Progress bar */}
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between text-[10px] font-bold opacity-50">
                <span>{currentRun.total_completed} completed · {currentRun.total_failed} failed</span>
                <span>{progress}% · {currentRun.total_expected} total</span>
              </div>
              <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    currentRun.total_failed > 0 ? 'bg-gradient-to-r from-accent to-red-500' : 'bg-gradient-to-r from-accent to-purple-500'
                  }`}
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>

            {/* Mode breakdown */}
            <div className="flex gap-2 flex-wrap">
              {currentRun.modes?.map(m => (
                <span key={m} className={`text-[10px] font-bold px-2 py-1 rounded-lg border ${MODE_COLORS[m as Mode] || 'bg-white/5 border-white/10 text-white/40'}`}>
                  {m} × {currentRun.quantity_per_mode}
                </span>
              ))}
              <span className="text-[10px] font-bold px-2 py-1 rounded-lg border border-white/10 text-white/30">
                {currentRun.generation_mode}
              </span>
            </div>

            {currentRun.status === 'COMPLETED' && (
              <div className="flex items-center gap-3 p-3 rounded-xl bg-green-500/10 border border-green-500/20">
                <CheckCircle2 size={16} className="text-green-400 shrink-0" />
                <div className="flex-1">
                  <span className="text-[11px] font-bold text-green-300">
                    {currentRun.total_completed} prompts saved to Prompt Handoff Bank
                  </span>
                </div>
                <a
                  href="/workspace/generation-packages"
                  className="flex items-center gap-1 text-[10px] font-black text-green-400 hover:text-green-300 bg-green-500/10 border border-green-500/20 px-3 py-1.5 rounded-lg transition-all hover:scale-105"
                >
                  Open Bank <LinkOut size={11} />
                </a>
              </div>
            )}

            {currentRun.error_log?.length > 0 && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 max-h-24 overflow-y-auto">
                <span className="text-[9px] font-black uppercase tracking-widest text-red-400 block mb-1">Errors</span>
                {currentRun.error_log.slice(-5).map((e, i) => (
                  <div key={i} className="text-[10px] text-red-300/70 font-mono">{e}</div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* No active run placeholder */}
        {!currentRun && (
          <div className="flex-1 flex flex-col items-center justify-center gap-5 opacity-10 text-center py-20">
            <Layers size={60} strokeWidth={0.8} />
            <div className="flex flex-col gap-1">
              <span className="text-lg font-black uppercase tracking-[0.2em]">Ready to Generate</span>
              <span className="text-xs font-medium opacity-60">Configure batch on the left and press Generate.</span>
            </div>
          </div>
        )}

        {/* Recent runs */}
        {recentRuns.length > 0 && (
          <section className="flex flex-col gap-3">
            <h3 className="text-[10px] font-black uppercase tracking-[0.2em] opacity-30 flex items-center gap-2 px-1">
              <History size={13} /> Recent Batch Runs
            </h3>
            {recentRuns.map(run => (
              <div
                key={run.batch_run_id}
                className="p-4 rounded-xl border border-white/5 bg-card/40 flex items-center gap-4 cursor-pointer hover:bg-card/70 transition-all"
                onClick={() => setCurrentRun(run)}
              >
                <div className="flex-1 flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-[9px] font-black tracking-widest px-2 py-0.5 rounded-full border ${
                      run.status === 'COMPLETED' ? 'bg-green-500/10 text-green-400 border-green-500/20' :
                      run.status === 'RUNNING' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                      run.status === 'FAILED' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                      'bg-white/5 text-white/30 border-white/10'
                    }`}>{run.status}</span>
                    <span className="text-[10px] font-mono opacity-20">#{run.batch_run_id.slice(-8)}</span>
                  </div>
                  <div className="flex gap-1 flex-wrap mt-0.5">
                    {run.modes?.map(m => (
                      <span key={m} className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${MODE_COLORS[m as Mode] || ''}`}>{m}</span>
                    ))}
                  </div>
                </div>
                <div className="text-right flex flex-col gap-0.5">
                  <span className="text-sm font-black text-white/70">{run.total_completed}<span className="text-[10px] opacity-40">/{run.total_expected}</span></span>
                  <span className="text-[9px] opacity-30">{new Date(run.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>
                <ChevronRight size={14} className="opacity-20 shrink-0" />
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function BatchesPage() {
  const [activeTab, setActiveTab] = useState<'workspace' | 'legacy'>('workspace')
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
      const data = await fetchAPI('/api/products?limit=500&offset=0') as any
      const allItems = data.items || []
      setProducts(allItems.filter((p: Product) => !p.is_test_product))
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
          <h1 className="text-xl font-bold tracking-tight">Batch Manager</h1>
          <p className="text-xs opacity-50 font-medium">Mass prompt generation for Prompt Handoff Bank & scheduled production</p>
        </div>
        {activeTab === 'workspace' && (
          <a
            href="/workspace/generation-packages"
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold border border-accent/30 text-accent hover:bg-accent/10 transition-all"
          >
            <LinkOut size={13} /> View Prompt Handoff Bank
          </a>
        )}
      </header>

      {/* Tab switcher */}
      <div className="flex gap-1 shrink-0 p-1 bg-black/20 rounded-xl w-fit border border-white/5">
        <button
          type="button"
          onClick={() => setActiveTab('workspace')}
          className={`px-5 py-2 rounded-lg text-xs font-black transition-all flex items-center gap-2 ${
            activeTab === 'workspace'
              ? 'bg-accent text-white shadow-lg shadow-accent/20'
              : 'text-white/30 hover:text-white/60'
          }`}
        >
          <Rocket size={13} /> Workspace Batch
          <span className="px-1.5 py-0.5 rounded text-[9px] bg-green-500/20 text-green-400 font-black">NEW</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('legacy')}
          className={`px-5 py-2 rounded-lg text-xs font-black transition-all flex items-center gap-2 ${
            activeTab === 'legacy'
              ? 'bg-white/10 text-white shadow'
              : 'text-white/30 hover:text-white/60'
          }`}
        >
          <Package size={13} /> Batch Production
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'workspace' ? (
          <WorkspaceBatchTab products={products} />
        ) : (
          /* ── Legacy Batch Production tab (unchanged) ── */
          <div className="flex-1 grid grid-cols-1 lg:grid-cols-[420px_1fr] gap-6 min-h-0 pb-4 h-full">
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
                      type="number" min="1" max="20"
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
                    {loading
                      ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      : <><Plus size={16} /> Create Batch Draft</>
                    }
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
                          <div className="flex justify-between items-center border-t border-white/5 pt-2.5">
                            <div className="flex items-center gap-2">
                              <Package size={12} className="opacity-30" />
                              <span className="text-[11px] font-bold text-white/70">{b.quantity} Variants</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <Zap size={10} className="text-accent/50" />
                              <span className="text-[10px] font-medium opacity-40">{b.mode || 'Frames'}</span>
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
                    <section className="p-6 rounded-2xl border border-white/10 bg-card/40 shadow-2xl relative overflow-hidden">
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

                      <div className="p-5 rounded-xl bg-black/40 border border-white/5 flex flex-col gap-4 shadow-inner">
                        <div className="flex justify-between items-center border-b border-white/5 pb-3">
                          <h3 className="text-[11px] font-black uppercase tracking-[0.2em] opacity-40 flex items-center gap-2">
                            <ShieldCheck size={14} className="text-accent" /> Execution Integrity
                          </h3>
                          <div className="flex items-center gap-2 px-2 py-1 rounded bg-white/5 border border-white/10">
                            <div className={`w-2 h-2 rounded-full ${health?.extension_connected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]'}`} />
                            <span className="text-[10px] font-black opacity-60 tracking-wider">LOCAL AGENT: {health?.extension_connected ? 'ONLINE' : 'OFFLINE'}</span>
                          </div>
                        </div>
                        <div className="grid grid-cols-3 gap-6">
                          <div className="flex flex-col gap-2.5">
                            <div className="flex justify-between items-center px-1">
                              <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Bridge Connection</span>
                              {health?.extension_connected ? <CheckCircle2 size={12} className="text-green-500" /> : <X size={12} className="text-red-500" />}
                            </div>
                          </div>
                          <div className="flex flex-col gap-2.5 border-x border-white/5 px-4">
                            <div className="flex justify-between items-center px-1">
                              <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Dry Run Validated</span>
                              {selectedBatch.dry_run_validated ? <CheckCircle2 size={12} className="text-green-500" /> : <span className="text-[9px] font-black text-orange-500 tracking-widest">LOCKED</span>}
                            </div>
                          </div>
                          <div className="flex flex-col gap-2.5">
                            <div className="flex justify-between items-center px-1">
                              <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">Queue Depth</span>
                              <span className="text-[11px] font-black text-accent">{selectedBatch.variants?.filter(v => v.queue_status === 'QUEUED').length || 0} / {selectedBatch.quantity}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </section>

                    <section className="flex flex-col gap-4">
                      <h3 className="text-lg font-black tracking-tight flex items-center gap-2 text-white/90 px-1">
                        <Package size={20} className="text-accent" /> Variants
                      </h3>
                      <div className="flex flex-col gap-3">
                        {selectedBatch.variants?.map(v => (
                          <div key={v.variant_id} className="p-5 rounded-2xl border border-white/5 bg-card/30 flex flex-col gap-4 hover:bg-card/50 transition-all">
                            <div className="flex justify-between items-start">
                              <div className="flex items-center gap-3">
                                <div className="w-9 h-9 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center text-sm font-black text-accent">{v.variation_index}</div>
                                <span className="text-sm font-black text-white/90">{v.hook_angle}</span>
                              </div>
                              <div className="flex items-center gap-3">
                                <span className={`text-[10px] font-black tracking-[0.1em] px-2 py-1 rounded-full border ${
                                  v.queue_status === 'QUEUED' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                                  v.queue_status === 'COMPLETED' ? 'bg-green-500/10 text-green-400 border-green-500/20' :
                                  'bg-white/5 text-white/30 border-white/10'
                                }`}>{v.queue_status}</span>
                                <button
                                  onClick={() => setShowPrompt(showPrompt === v.variant_id ? null : v.variant_id)}
                                  className={`p-2 rounded-xl transition-all ${showPrompt === v.variant_id ? 'bg-accent text-white' : 'bg-white/5 text-white/40 hover:text-accent'}`}
                                >
                                  <FileSearch size={16} />
                                </button>
                              </div>
                            </div>
                            {showPrompt === v.variant_id && (
                              <div className="p-4 rounded-xl bg-black/60 text-[11px] font-mono whitespace-pre-wrap leading-loose border border-white/10 text-white/70">
                                {v.prompt_9_section}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center opacity-10 gap-6">
                  <Package size={80} strokeWidth={0.5} />
                  <span className="text-xl font-black uppercase tracking-[0.3em]">No Batch Selected</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
