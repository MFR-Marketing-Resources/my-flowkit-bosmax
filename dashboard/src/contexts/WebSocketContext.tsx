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
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(false)

  const connect = useCallback(() => {
    if (!mountedRef.current) return

    // Avoid opening a second socket if one is already OPEN or CONNECTING
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return
    }

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

      if (mountedRef.current) {
        const delay = Math.min(1000 * 2 ** retriesRef.current, 30000)
        retriesRef.current++
        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }

    ws.onerror = () => {
      if (wsRef.current === ws) {
        ws.close()
      }
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
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
