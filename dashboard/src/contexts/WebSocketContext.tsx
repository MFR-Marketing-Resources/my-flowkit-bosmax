import { createContext, useContext, useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import type { WSEvent, WSHealthData, WSSnapshotData } from '../types'

interface WebSocketContextType {
  isConnected: boolean
  extensionConnected: boolean
  lastEvent: WSEvent | null
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined)

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [isConnected, setIsConnected] = useState(false)
  const [extensionConnected, setExtensionConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState<WSEvent | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const retriesRef = useRef(0)

  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/dashboard`)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
      retriesRef.current = 0
    }

    ws.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data)
        setLastEvent(event)

        if (event.type === 'snapshot') {
          const data = event.data as WSSnapshotData
          if (data.health) {
            setExtensionConnected(data.health.extension_connected)
          }
        } else if (event.type === 'health') {
          const data = event.data as WSHealthData
          setExtensionConnected(data.extension_connected)
        }
      } catch (err) {
        console.error('WS parse error:', err)
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
      wsRef.current = null
      const delay = Math.min(1000 * 2 ** retriesRef.current, 30000)
      retriesRef.current++
      setTimeout(connect, delay)
    }

    ws.onerror = () => ws.close()
  }, [])

  useEffect(() => {
    connect()
    return () => { wsRef.current?.close() }
  }, [connect])

  return (
    <WebSocketContext.Provider value={{ isConnected, extensionConnected, lastEvent }}>
      {children}
    </WebSocketContext.Provider>
  )
}

export function useWebSocketContext() {
  const context = useContext(WebSocketContext)
  if (context === undefined) {
    throw new Error('useWebSocketContext must be used within a WebSocketProvider')
  }
  return context
}
