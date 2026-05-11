import { useState } from 'react'
import { Upload, ArrowRight } from 'lucide-react'
import type { UploadedAsset } from '../../types'
import { handleAssetUpload } from '../../api/assets'

interface IMGModuleProps {
  onExecute: (data: any) => void
  isExecuting: boolean
}

export default function IMGModule({ onExecute, isExecuting }: IMGModuleProps) {
  // --- States ---
  const [manualPrompt, setManualPrompt] = useState('')
  const [aspectRatio, setAspectRatio] = useState('9:16')
  const [model, setModel] = useState('Nano Banana 2')
  const [count, setCount] = useState(1)
  const [isUploading, setIsUploading] = useState(false)
  
  // Image Assets
  const [subjectAsset, setSubjectAsset] = useState<UploadedAsset | null>(null)
  const [sceneAsset, setSceneAsset] = useState<UploadedAsset | null>(null)
  const [styleAsset, setStyleAsset] = useState<UploadedAsset | null>(null)

  // --- Handlers ---
  const handleFileChange = async (type: 'subject' | 'scene' | 'style', e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsUploading(true)
    try {
      console.log(`[IMG] Starting upload for ${type}...`)
      const asset = await handleAssetUpload(file)
      console.log(`[IMG] Upload success for ${type}:`, asset.mediaId)
      
      if (type === 'subject') setSubjectAsset(asset)
      else if (type === 'scene') setSceneAsset(asset)
      else setStyleAsset(asset)
    } catch (error: any) {
      console.error(`[IMG] ${type} upload failed:`, error)
      alert(`UPLOAD ERROR: ${error.message || 'Unknown error'}. Make sure your local agent is running at http://127.0.0.1:8100`)
    } finally {
      setIsUploading(false)
    }
  }

  const handleExecute = () => {
    onExecute({
      prompt: manualPrompt,
      aspectRatio,
      model,
      count,
      refs: { 
        subjectAssetId: subjectAsset?.mediaId, 
        sceneAssetId: sceneAsset?.mediaId, 
        styleAssetId: styleAsset?.mediaId 
      },
      mode: 'IMG'
    })
  }

  return (
    <div className="flex h-full gap-6">
      <div className="flex-1 space-y-6 overflow-y-auto pr-2 pb-12">
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">1. Visual Assets (Subject / Scene / Style)</h3>
          <div className="grid grid-cols-3 gap-4">
            {/* Subject */}
            <div className="group relative aspect-[3/4] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
               {subjectAsset ? (
                 <img src={subjectAsset.previewUrl} className="w-full h-full object-cover" alt="Subject" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-[10px] font-bold text-slate-500 group-hover:text-slate-300 uppercase tracking-widest">Subject</span>
                 </>
               )}
               <input type="file" accept="image/*" className="absolute inset-0 opacity-0 cursor-pointer" onChange={(e) => handleFileChange('subject', e)} />
            </div>

            {/* Scene */}
            <div className="group relative aspect-[3/4] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-purple-500/50 transition-all cursor-pointer overflow-hidden">
               {sceneAsset ? (
                 <img src={sceneAsset.previewUrl} className="w-full h-full object-cover" alt="Scene" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-purple-500/10 group-hover:text-purple-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-[10px] font-bold text-slate-500 group-hover:text-slate-300 uppercase tracking-widest">Scene</span>
                 </>
               )}
               <input type="file" accept="image/*" className="absolute inset-0 opacity-0 cursor-pointer" onChange={(e) => handleFileChange('scene', e)} />
            </div>

            {/* Style */}
            <div className="group relative aspect-[3/4] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-pink-500/50 transition-all cursor-pointer overflow-hidden">
               {styleAsset ? (
                 <img src={styleAsset.previewUrl} className="w-full h-full object-cover" alt="Style" />
               ) : (
                 <>
                   <div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-pink-500/10 group-hover:text-pink-400 transition-colors">
                     <Upload size={20} />
                   </div>
                   <span className="text-[10px] font-bold text-slate-500 group-hover:text-slate-300 uppercase tracking-widest">Style</span>
                 </>
               )}
               <input type="file" accept="image/*" className="absolute inset-0 opacity-0 cursor-pointer" onChange={(e) => handleFileChange('style', e)} />
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">2. Prompt Injection</h3>
          <div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            <textarea 
              className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
              placeholder="What do you want to create?"
              value={manualPrompt}
              onChange={(e) => setManualPrompt(e.target.value)}
            />
          </div>
        </section>
        
        <div className="pt-4">
          <button 
            onClick={handleExecute}
            disabled={isExecuting || isUploading || !manualPrompt || !subjectAsset}
            className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
          >
            {isUploading ? 'Uploading Assets...' : isExecuting ? 'Generating Images...' : 'GENERATE IMAGES'}
            {!isExecuting && !isUploading && <ArrowRight size={18} />}
          </button>
        </div>
      </div>

      <div className="w-72 flex-shrink-0 flex flex-col gap-6 overflow-y-auto pb-12 text-slate-300">
        <section className="space-y-4">
          <h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">Flow Mirror Settings</h3>
          <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-6">
            <div className="space-y-3">
              <label className="text-xs font-bold text-slate-400">Aspect Ratio</label>
              <div className="grid grid-cols-5 gap-1.5">
                {['16:9', '4:3', '1:1', '3:4', '9:16'].map(ratio => (
                  <button key={ratio} onClick={() => setAspectRatio(ratio)} className={`py-2 rounded-lg text-[9px] font-bold border transition-all ${aspectRatio === ratio ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-slate-950 border-slate-800 text-slate-500'}`}>{ratio}</button>
                ))}
              </div>
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
