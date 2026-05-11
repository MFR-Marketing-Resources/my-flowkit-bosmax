import { useEffect, useState } from 'react'
import { fetchAPI } from '../api/client'
import { useWebSocketContext } from '../contexts/WebSocketContext'
import type { LocalAgentStatus, TelemetrySummary } from '../types'

// Re-using the logic from the old OperatorPage but in a dedicated space
export function DeploymentStatusCard({ agentStatus, extensionConnected }: { agentStatus: LocalAgentStatus | null, extensionConnected: boolean }) {
  if (!agentStatus) return null
  const isOnline = agentStatus.extension_connected && agentStatus.extension_state === 'IDLE'
  return (
    <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 backdrop-blur-md shadow-xl">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-sm font-bold flex items-center gap-2 text-white">
          <span className={`w-2 h-2 rounded-full ${isOnline ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
          Deployment Status
        </h3>
        <div className={`text-[10px] px-2 py-0.5 rounded font-bold ${isOnline ? 'bg-green-600/20 text-green-400' : 'bg-red-600/20 text-red-400'}`}>
          {isOnline ? 'ONLINE' : 'OFFLINE'}
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800">
          <div className="text-[10px] uppercase text-slate-500 font-bold mb-1">Extension Bridge</div>
          <div className={`text-sm font-bold ${extensionConnected ? 'text-blue-400' : 'text-red-400'}`}>
            {extensionConnected ? 'Connected' : 'Disconnected'}
          </div>
        </div>
        <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800">
          <div className="text-[10px] uppercase text-slate-500 font-bold mb-1">Serving Mode</div>
          <div className="text-sm font-bold text-slate-200">{agentStatus.dashboard_serving_mode || 'Local'}</div>
        </div>
        <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800">
          <div className="text-[10px] uppercase text-slate-500 font-bold mb-1">Last Heartbeat</div>
          <div className="text-sm font-mono text-slate-400">
            {agentStatus.last_health_check ? new Date(agentStatus.last_health_check).toLocaleTimeString() : '—'}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const [agentStatus, setAgentStatus] = useState<LocalAgentStatus | null>(null)
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const { isConnected, extensionConnected } = useWebSocketContext()

  const refreshStatus = async () => {
    try {
      const status = await fetchAPI<LocalAgentStatus>('/api/local-agent/status')
      setAgentStatus(status)
      const tel = await fetchAPI<TelemetrySummary>('/api/telemetry/summary')
      setTelemetry(tel)
    } catch (err) {
      console.error('Failed to fetch settings status', err)
    }
  }

  useEffect(() => {
    refreshStatus()
    const timer = setInterval(refreshStatus, 10000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-white mb-2">Engine Room</h2>
        <p className="text-slate-400 text-sm">Configure backend pipelines, API connections, and system health.</p>
      </div>

      <DeploymentStatusCard agentStatus={agentStatus} extensionConnected={extensionConnected} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <section className="space-y-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">API Credentials</h3>
          <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-medium text-slate-400">Google Flow API Key</label>
              <input 
                type="password" 
                value="••••••••••••••••••••••••" 
                readOnly 
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 text-sm text-slate-300"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-medium text-slate-400">Local Agent Endpoint</label>
              <input 
                type="text" 
                value="http://127.0.0.1:8100" 
                readOnly 
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 text-sm text-slate-300"
              />
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">System Telemetry</h3>
          <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40">
             <div className="space-y-4">
               <div className="flex justify-between items-center text-sm">
                 <span className="text-slate-400">Total Jobs (Today)</span>
                 <span className="font-bold text-white">{telemetry?.total_today || 0}</span>
               </div>
               <div className="flex justify-between items-center text-sm">
                 <span className="text-slate-400">Success Rate</span>
                 <span className="font-bold text-green-400">
                   {telemetry?.total_today ? Math.round((telemetry.completed / telemetry.total_today) * 100) : 0}%
                 </span>
               </div>
               <div className="flex justify-between items-center text-sm">
                 <span className="text-slate-400">Worker Status</span>
                 <span className="font-bold text-blue-400 uppercase">{isConnected ? 'Idle' : 'Offline'}</span>
               </div>
             </div>
          </div>
        </section>
      </div>

      <div className="p-4 rounded-xl bg-blue-500/5 border border-blue-500/20 text-blue-400 text-xs">
        Note: These settings affect the entire BOSMAX automated pipeline. Changes here may require an agent restart.
      </div>
    </div>
  )
}
