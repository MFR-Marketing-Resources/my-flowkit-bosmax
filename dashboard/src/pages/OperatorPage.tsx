import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import F2VModule from '../components/workspace/F2VModule'
import T2VModule from '../components/workspace/T2VModule'
import I2VModule from '../components/workspace/I2VModule'
import IMGModule from '../components/workspace/IMGModule'

interface OperatorPageProps {
  mode?: 'T2V' | 'F2V' | 'I2V' | 'IMG'
}

export default function OperatorPage({ mode: propMode }: OperatorPageProps) {
  const location = useLocation()
  const [isExecuting, setIsExecuting] = useState(false)

  const pathMode = location.pathname.split('/').pop()?.toUpperCase()
  const mode = propMode || (pathMode === 'T2V' || pathMode === 'F2V' || pathMode === 'I2V' || pathMode === 'IMG' ? pathMode : 'F2V')

  const handleExecute = async (data: any) => {
    setIsExecuting(true)
    console.log('Operator executing:', data)
    try {
      const response = await fetch('/api/flow/execute-flow-job', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      
      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || 'Execution failed')
      }
      
      const result = await response.json()
      console.log('Execution result:', result)
    } catch (error: any) {
      console.error('Execution error:', error)
      alert(`Execution Error: ${error.message}`)
    } finally {
      setIsExecuting(false)
    }
  }

  const renderModule = () => {
    switch (mode) {
      case 'F2V':
        return <F2VModule onExecute={handleExecute} isExecuting={isExecuting} />
      case 'T2V':
        return <T2VModule onExecute={handleExecute} isExecuting={isExecuting} />
      case 'I2V':
        return <I2VModule onExecute={handleExecute} isExecuting={isExecuting} />
      case 'IMG':
        return <IMGModule onExecute={handleExecute} isExecuting={isExecuting} />
      default:
        return <div className="p-8 text-slate-400">Please select a workspace module from the sidebar.</div>
    }
  }

  return (
    <div className="h-full p-8 flex flex-col bg-slate-950">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white tracking-tight">{mode} Production Workspace</h2>
          <p className="text-slate-400 text-sm italic">Automating Google Flow with BOSMAX V4 precision.</p>
        </div>
        <div className="flex items-center gap-4">
           <div className="px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[10px] font-bold uppercase tracking-widest">
             Mode: {mode === 'F2V' ? 'Frames to Video' : mode}
           </div>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        {renderModule()}
      </div>
    </div>
  )
}
