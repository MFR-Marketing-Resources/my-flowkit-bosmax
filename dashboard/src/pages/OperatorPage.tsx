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

  const pathMode = location.pathname.split('/').pop()?.toUpperCase()
  const mode = propMode || (pathMode === 'T2V' || pathMode === 'F2V' || pathMode === 'I2V' || pathMode === 'IMG' ? pathMode : 'F2V')

  const renderModule = () => {
    switch (mode) {
      case 'F2V':
        return <F2VModule onExecute={(data) => console.log('F2V Execute', data)} isExecuting={false} />
      case 'T2V':
        return <T2VModule onExecute={(data) => console.log('T2V Execute', data)} isExecuting={false} />
      case 'I2V':
        return <I2VModule onExecute={(data) => console.log('I2V Execute', data)} isExecuting={false} />
      case 'IMG':
        return <IMGModule onExecute={(data) => console.log('IMG Execute', data)} isExecuting={false} />
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
