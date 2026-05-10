import { createContext, useContext, useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import type { WSEvent, WSHealthData } from '../types'

interface WebSocketContextType {
  isConnected: boolean
  extensionConnected: boolean
  lastEvent: WSEvent | null
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined)

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function readSnapshotHealth(event: unknown): WSHealthData | null {
  if (!isRecord(event)) return null

  const nestedData = isRecord(event.data) ? event.data : null
  const snapshotCandidate = nestedData && isRecord(nestedData.health)
    ? nestedData
    : event

  if (!isRecord(snapshotCandidate.health)) return null

  const health = snapshotCandidate.health
  if (typeof health.status !== 'string' || typeof health.extension_connected !== 'boolean') {
    return null
  }

  return {
    status: health.status,
    extension_connected: health.extension_connected,
  }
}

function readHealthEvent(event: unknown): WSHealthData | null {
  if (!isRecord(event)) return null
  const candidate = isRecord(event.data) ? event.data : event
  if (typeof candidate.status !== 'string' || typeof candidate.extension_connected !== 'boolean') {
    return null
  }

  return {
    status: candidate.status,
    extension_connected: candidate.extension_connected,
  }
}

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
        const parsed = JSON.parse(e.data) as unknown
        const event = (isRecord(parsed)
          ? {
              ...parsed,
              type: typeof parsed.type === 'string' ? parsed.type : 'unknown',
              data: parsed.data,
              timestamp: typeof parsed.timestamp === 'string' ? parsed.timestamp : new Date().toISOString(),
            }
          : {
              type: 'unknown',
              data: parsed,
              timestamp: new Date().toISOString(),
            }) as WSEvent
        setLastEvent(event)

        if (event.type === 'snapshot') {
          const health = readSnapshotHealth(parsed)
          if (health) {
            setExtensionConnected(health.extension_connected)
          }
        } else if (event.type === 'health') {
          const health = readHealthEvent(parsed)
          if (health) {
            setExtensionConnected(health.extension_connected)
          }
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
