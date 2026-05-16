import { useState } from 'react'
import { fetchAPI, postMultipartAPI } from '../../api/client'
import type { AIFormImportResponse, ProductKnowledgeCompleteResponse } from '../../types'

interface Props {
  onComplete: (data: ProductKnowledgeCompleteResponse) => void
  setIsProcessing: (val: boolean) => void
  isProcessing: boolean
}

export default function AIFormPack({ onComplete, setIsProcessing, isProcessing }: Props) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [importResult, setImportResult] = useState<AIFormImportResponse | null>(null)

  const handleDownloadTemplate = async () => {
    try {
      const data = await fetchAPI<{ filename: string, content: string }>('/api/product-knowledge/ai-form-template')
      const blob = new Blob([data.content], { type: 'text/markdown' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = data.filename
      a.click()
    } catch (err) {
      console.error('Failed to download template:', err)
      alert('Failed to download template')
    }
  }

  const handleCopyPrompt = async () => {
    try {
      const data = await fetchAPI<{ prompt: string }>('/api/product-knowledge/ai-coaching-prompt')
      await navigator.clipboard.writeText(data.prompt)
      alert('AI Coaching Prompt copied to clipboard!')
    } catch (err) {
      console.error('Failed to copy prompt:', err)
      alert('Failed to copy prompt')
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0])
    }
  }

  const handleUpload = async () => {
    if (!selectedFile) return
    setIsProcessing(true)
    setImportResult(null)
    
    const formData = new FormData()
    formData.append('file', selectedFile)

    try {
      const result = await postMultipartAPI<AIFormImportResponse>('/api/product-knowledge/import-ai-form', formData)
      setImportResult(result)
      
      if (result.parse_status === 'PARSED' && result.completion_response) {
        onComplete(result.completion_response)
      }
    } catch (err) {
      console.error('Import failed:', err)
      alert('Import failed. Check console.')
    } finally {
      setIsProcessing(false)
    }
  }

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-2xl overflow-hidden mb-8">
      <div className="p-6 border-b border-slate-800 bg-slate-800/20">
        <h3 className="text-lg font-bold text-white flex items-center gap-2">
          <span className="p-2 bg-indigo-500/20 text-indigo-400 rounded-lg">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </span>
          AI-Assisted Product Knowledge Form
        </h3>
        <p className="text-sm text-slate-400 mt-2">
          Don't have all the facts? Let an AI assistant help you interview and fill the form.
        </p>
      </div>

      <div className="p-6 space-y-8">
        {/* Step 1 & 2 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-4 p-5 rounded-xl bg-slate-800/30 border border-slate-700/50">
            <div className="flex items-center gap-3">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-slate-700 text-slate-300 text-xs font-bold">1</span>
              <span className="text-sm font-semibold text-white">Get the Pack</span>
            </div>
            <div className="flex flex-col gap-2">
              <button
                onClick={handleDownloadTemplate}
                className="flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-sm transition-all"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a2 2 0 002 2h12a2 2 0 002-2v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download Form Template
              </button>
              <button
                onClick={handleCopyPrompt}
                className="flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-sm transition-all"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                </svg>
                Copy AI Coaching Prompt
              </button>
            </div>
          </div>

          <div className="space-y-4 p-5 rounded-xl bg-slate-800/30 border border-slate-700/50">
            <div className="flex items-center gap-3">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-slate-700 text-slate-300 text-xs font-bold">2</span>
              <span className="text-sm font-semibold text-white">Upload Completed Form</span>
            </div>
            <div className="space-y-4">
              <input
                type="file"
                onChange={handleFileChange}
                accept=".md,.markdown,.json,.txt"
                className="block w-full text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-indigo-500/10 file:text-indigo-400 hover:file:bg-indigo-500/20 transition-all cursor-pointer"
              />
              <button
                onClick={handleUpload}
                disabled={isProcessing || !selectedFile}
                className={`w-full py-2.5 rounded-lg font-bold uppercase tracking-widest text-xs transition-all shadow-lg ${
                  isProcessing || !selectedFile
                    ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                    : 'bg-indigo-600 hover:bg-indigo-500 text-white'
                }`}
              >
                {isProcessing ? 'Processing...' : 'Parse & Run Smart Completion'}
              </button>
            </div>
          </div>
        </div>

        {/* Results / Feedback */}
        {importResult && (
          <div className={`p-5 rounded-xl border ${
            importResult.parse_status === 'PARSED' ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-red-500/5 border-red-500/20'
          }`}>
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-bold text-white uppercase tracking-wider">Import Status: {importResult.parse_status}</h4>
              <span className="text-[10px] text-slate-500">ID: {importResult.import_id}</span>
            </div>

            {importResult.parse_errors.length > 0 && (
              <div className="mb-4 space-y-1">
                {importResult.parse_errors.map((err, i) => (
                  <div key={i} className="text-xs text-red-400 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500"></span>
                    {err}
                  </div>
                ))}
              </div>
            )}

            {importResult.parse_warnings.length > 0 && (
              <div className="mb-4 space-y-1">
                {importResult.parse_warnings.map((warn, i) => (
                  <div key={i} className="text-xs text-amber-400 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span>
                    {warn}
                  </div>
                ))}
              </div>
            )}

            {importResult.parsed_request && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-slate-700/50">
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-bold">Product</div>
                  <div className="text-sm text-white truncate">{importResult.parsed_request.product_name}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-bold">Lane</div>
                  <div className="text-sm text-white">{importResult.parsed_request.source_lane}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-bold">Review Req</div>
                  <div className="text-sm text-white">{importResult.user_review_required ? 'YES' : 'NO'}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-bold">Write Back</div>
                  <div className="text-sm text-white truncate text-[10px]">{importResult.write_back_status}</div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
