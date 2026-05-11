import { useState } from 'react'
import { Upload, ArrowRight, Info } from 'lucide-react'
import type { UploadedAsset, Orientation } from '../../types'

interface I2VModuleProps {
  onExecute: (data: any) => void
  isExecuting: boolean
}

export default function I2VModule({ onExecute, isExecuting }: I2VModuleProps) {
  // --- States ---
  const [manualPrompt, setManualPrompt] = useState('')
  
  // Mirror States
  const [orientation, setOrientation] = useState<Orientation>('VERTICAL')
  const [model, setModel] = useState('Veo 3.1 - Pro')
  const [count, setCount] = useState(1)
  
  // Ingredients Assets (Array of 15 slots)
  const [assets, setAssets] = useState<(UploadedAsset | null)[]>(new Array(15).fill(null))

  // --- Handlers ---
  const handleUpload = (index: number, _e: React.ChangeEvent<HTMLInputElement>) => {
    // Logic to upload ingredient at index
  }

  const handleExecute = () => {
    onExecute({
      prompt: manualPrompt,
      orientation,
      model,
      count,
      assets: assets.filter(a => a !== null),
      mode: 'I2V'
    })
  }

  return (
    <div className="flex h-full gap-6">
      {/* Main Workspace */}
      <div className="flex-1 space-y-6 overflow-y-auto pr-2 pb-12">
        
        {/* 1. Visual Assets (Ingredients Slots - 15 Slots) */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">1. Visual Assets (15 Ingredients Slots)</h3>
            <span className="text-[10px] text-slate-600 font-bold">{assets.filter(a => a !== null).length} / 15 Uploaded</span>
          </div>
          
          <div className="grid grid-cols-5 gap-3">
            {assets.map((asset, index) => (
              <div 
                key={index}
                className="group relative aspect-square rounded-xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-1 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden"
              >
                {asset ? (
                  <img src={`http://127.0.0.1:8100/api/products/${asset.mediaId}/image`} className="w-full h-full object-cover" alt={`Ingredient ${index + 1}`} />
                ) : (
                  <>
                    <div className="p-2 rounded-full bg-slate-800 text-slate-500 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                      <Upload size={14} />
                    </div>
                    <span className="text-[8px] font-bold text-slate-600 group-hover:text-slate-400">Slot {index + 1}</span>
                  </>
                )}
                <input 
                  type="file" 
                  className="absolute inset-0 opacity-0 cursor-pointer" 
                  onChange={(e) => handleUpload(index, e)} 
                />
              </div>
            ))}
          </div>
        </section>

        {/* 2. Prompt Injection */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">2. Prompt Injection</h3>
          </div>
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            <textarea 
              className="w-full h-32 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
              placeholder="Describe how to combine these ingredients..."
              value={manualPrompt}
              onChange={(e) => setManualPrompt(e.target.value)}
            />
            <div className="flex items-center gap-2 text-[10px] text-slate-500 italic">
              <Info size={12} />
              <span>BOSMAX will inject these assets and prompt into Google Flow's Ingredients composer.</span>
            </div>
          </div>
        </section>
        
        <div className="pt-4">
          <button 
            onClick={handleExecute}
            disabled={isExecuting || !manualPrompt || assets.filter(a => a !== null).length === 0}
            className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
          >
            {isExecuting ? 'Executing Ingredients Sequence...' : 'START GENERATION'}
            {!isExecuting && <ArrowRight size={18} />}
          </button>
        </div>
      </div>

      {/* Google Flow Mirror Panel */}
      <div className="w-72 flex-shrink-0 flex flex-col gap-6 overflow-y-auto pb-12">
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
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] font-bold text-slate-300 outline-none"
              >
                <option>Veo 3.1 - Pro</option>
                <option>Veo 3.1 - Lite</option>
                <option>Nano Banana 2</option>
              </select>
            </div>

            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Count</label>
              <div className="grid grid-cols-4 gap-2">
                {[1, 2, 3, 4].map(v => (
                  <button 
                    key={v}
                    onClick={() => setCount(v)}
                    className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${count === v ? 'bg-purple-600/20 border-purple-500 text-purple-400' : 'bg-slate-950 border-slate-800 text-slate-500'}`}
                  >
                    {v}x
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="p-6 rounded-2xl border border-blue-500/10 bg-blue-500/5">
           <h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-widest mb-2">Ingredients Context</h4>
           <div className="text-[10px] text-blue-300/60 leading-relaxed italic">
             Pure Mirror Mode: Google Flow will combine up to 15 reference assets with your text prompt.
           </div>
        </section>
      </div>
    </div>
  )
}
