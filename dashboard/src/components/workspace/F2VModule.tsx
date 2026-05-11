import { useState } from 'react'
import { Upload, ArrowRight, Loader2 } from 'lucide-react'
import type { UploadedAsset, Orientation } from '../../types'
import { handleAssetUpload } from '../../api/assets'

interface F2VModuleProps {
  onExecute: (data: any) => void
  isExecuting: boolean
  compact?: boolean
}

export default function F2VModule({ onExecute, isExecuting, compact = false }: F2VModuleProps) {
  // --- States ---
  const [manualPrompt, setManualPrompt] = useState('')
  const [orientation, setOrientation] = useState<Orientation>('VERTICAL')
  const [model, setModel] = useState('Veo 3.1 - Pro')
  const [count, setCount] = useState(1)
  const [isUploading, setIsUploading] = useState(false)
  
  // Frame Assets
  const [startAsset, setStartAsset] = useState<UploadedAsset | null>(null)
  const [endAsset, setEndAsset] = useState<UploadedAsset | null>(null)

  // --- Handlers ---
  const handleFileChange = async (type: 'start' | 'end', e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsUploading(true)
    try {
      console.log(`[F2V] Uploading ${type} to agent...`)
      const asset = await handleAssetUpload(file)
      console.log(`[F2V] Upload success:`, asset.mediaId)
      
      if (type === 'start') setStartAsset(asset)
      else setEndAsset(asset)
    } catch (error: any) {
      console.error(`[F2V] ${type} upload failed:`, error)
      alert(`UPLOAD ERROR: ${error.message || 'Unknown error'}. Check your agent.`)
    } finally {
      setIsUploading(false)
    }
  }

  const handleExecute = () => {
    onExecute({
      prompt: manualPrompt,
      orientation,
      model,
      count,
      // Pass the full asset object (including previewUrl/base64) so extension can use it directly
      startAsset: startAsset,
      endAsset: endAsset,
      mode: 'F2V'
    })
  }

  return (
    <div className={`flex h-full gap-6 ${compact ? 'flex-col' : 'max-[1280px]:flex-col'}`}>
      <div className={`flex-1 space-y-6 overflow-y-auto pb-12 ${compact ? 'pr-0' : 'pr-2'}`}>
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">1. Visual Assets (F2V Slots)</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Start Frame */}
            <div className="group relative aspect-video rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-3 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
               {startAsset ? (
                 <img src={startAsset.previewUrl} className="w-full h-full object-cover animate-in fade-in duration-500" alt="Start Frame" />
               ) : (
                 <>
                   <div className="p-4 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                     {isUploading ? <Loader2 className="animate-spin" size={24} /> : <Upload size={24} />}
                   </div>
                   <div className="text-center">
                     <p className="text-[10px] font-bold text-slate-300 uppercase tracking-widest">Start Frame</p>
                     <p className="text-[9px] text-slate-500 mt-1">{isUploading ? 'Uploading...' : 'Click to upload'}</p>
                   </div>
                 </>
               )}
               {!isUploading && <input type="file" accept="image/*" title="Upload start frame" className="absolute inset-0 opacity-0 cursor-pointer" onChange={(e) => handleFileChange('start', e)} />}
            </div>

            {/* End Frame */}
            <div className="group relative aspect-video rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-3 hover:border-purple-500/50 transition-all cursor-pointer overflow-hidden">
               {endAsset ? (
                 <img src={endAsset.previewUrl} className="w-full h-full object-cover animate-in fade-in duration-500" alt="End Frame" />
               ) : (
                 <>
                   <div className="p-4 rounded-full bg-slate-800 text-slate-400 group-hover:bg-purple-500/10 group-hover:text-purple-400 transition-colors">
                     <Upload size={24} />
                   </div>
                   <div className="text-center">
                     <p className="text-[10px] font-bold text-slate-300 uppercase tracking-widest">End Frame (Optional)</p>
                     <p className="text-[9px] text-slate-500 mt-1">Click to upload</p>
                   </div>
                 </>
               )}
               {!isUploading && <input type="file" accept="image/*" title="Upload end frame" className="absolute inset-0 opacity-0 cursor-pointer" onChange={(e) => handleFileChange('end', e)} />}
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">2. Prompt Injection</h3>
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            <textarea 
              className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
              placeholder="Describe the golden transition..."
              value={manualPrompt}
              onChange={(e) => setManualPrompt(e.target.value)}
            />
          </div>
        </section>
        
        <div className="pt-4">
          <button 
            onClick={handleExecute}
            disabled={isExecuting || isUploading || !manualPrompt || !startAsset}
            className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
          >
            {isUploading ? 'Preparing Assets...' : isExecuting ? 'Executing Sequence...' : 'START GENERATION'}
            {!isExecuting && !isUploading && <ArrowRight size={18} />}
          </button>
        </div>
      </div>

      <div className={`${compact ? 'w-full' : 'w-72 max-[1280px]:w-full'} flex-shrink-0 flex flex-col gap-6 overflow-y-auto pb-12`}>
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">Flow Mirror Settings</h3>
          <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-6">
            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Aspect Ratio</label>
              <div className="grid grid-cols-2 gap-2">
                {['VERTICAL', 'HORIZONTAL'].map(o => (
                  <button key={o} onClick={() => setOrientation(o as any)} className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === o ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-slate-950 border-slate-800 text-slate-500'}`}>{o === 'VERTICAL' ? '9:16 (Vertical)' : '16:9 (Horizontal)'}</button>
                ))}
              </div>
            </div>
            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Generation Model</label>
              <select title="Select generation model" value={model} onChange={(e) => setModel(e.target.value)} className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] font-bold text-slate-300 outline-none">
                <option>Veo 3.1 - Pro</option>
                <option>Veo 3.1 - Lite</option>
                <option>Nano Banana 2</option>
              </select>
            </div>
            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Count</label>
              <div className="grid grid-cols-4 gap-2">
                {[1, 2, 3, 4].map(v => (
                  <button key={v} onClick={() => setCount(v)} className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${count === v ? 'bg-purple-600/20 border-purple-500 text-purple-400' : 'bg-slate-950 border-slate-800 text-slate-500'}`}>{v}x</button>
                ))}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
