import { useState } from 'react'
import { Upload, ArrowRight, Info } from 'lucide-react'
import type { UploadedAsset, Orientation } from '../../types'

interface F2VModuleProps {
  onExecute: (data: any) => void
  isExecuting: boolean
}

export default function F2VModule({ onExecute, isExecuting }: F2VModuleProps) {
  // --- States ---
  const [manualPrompt, setManualPrompt] = useState('')
  
  // Mirror States
  const [orientation, setOrientation] = useState<Orientation>('VERTICAL')
  const [model, setModel] = useState('Veo 3.1 - Pro')
  const [count, setCount] = useState(1)
  const [startAsset] = useState<UploadedAsset | null>(null)
  const [endAsset] = useState<UploadedAsset | null>(null)

  // --- Handlers ---
  const handleStartUpload = (_e: React.ChangeEvent<HTMLInputElement>) => {
    // Logic to upload start frame
  }

  const handleEndUpload = (_e: React.ChangeEvent<HTMLInputElement>) => {
    // Logic to upload end frame
  }

  const handleExecute = () => {
    onExecute({
      prompt: manualPrompt,
      orientation,
      model,
      count,
      startAsset,
      endAsset
    })
  }

  return (
    <div className="flex h-full gap-6">
      {/* Main Workspace */}
      <div className="flex-1 space-y-6 overflow-y-auto pr-2 pb-12">
        
        {/* 1. Visual Assets (F2V Slots) - Mimicking Google Flow */}
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">1. Visual Assets (F2V Slots)</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="group relative aspect-[9/16] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
               {startAsset ? (
                 <img src={`http://127.0.0.1:8100/api/products/${startAsset.mediaId}/image`} className="w-full h-full object-cover" alt="Start" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-xs font-bold text-slate-500 group-hover:text-slate-300">Start Frame</span>
                 </>
               )}
               <input type="file" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleStartUpload} />
            </div>

            <div className="group relative aspect-[9/16] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
               {endAsset ? (
                 <img src={`http://127.0.0.1:8100/api/products/${endAsset.mediaId}/image`} className="w-full h-full object-cover" alt="End" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-xs font-bold text-slate-500 group-hover:text-slate-300">End Frame (Optional)</span>
                 </>
               )}
               <input type="file" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleEndUpload} />
            </div>
          </div>
        </section>

        {/* 2. Prompt Injection - Mimicking Google Flow */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">2. Prompt Injection</h3>
          </div>
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            <textarea 
              className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
              placeholder="Describe what you want to generate..."
              value={manualPrompt}
              onChange={(e) => setManualPrompt(e.target.value)}
            />
            <div className="flex items-center gap-2 text-[10px] text-slate-500 italic">
              <Info size={12} />
              <span>This prompt will be injected directly into Google Flow's composer.</span>
            </div>
          </div>
        </section>
        
        <div className="pt-4">
          <button 
            onClick={handleExecute}
            disabled={isExecuting || !manualPrompt || !startAsset}
            className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
          >
            {isExecuting ? 'Executing Golden Sequence...' : 'START GENERATION'}
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
           <h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-widest mb-2">F2V Context</h4>
           <div className="text-[10px] text-blue-300/60 leading-relaxed italic">
             BOSMAX Studio is now in Pure Mirror Mode. UI reflects Google Flow's generation pipeline.
           </div>
        </section>
      </div>
    </div>
  )
}
