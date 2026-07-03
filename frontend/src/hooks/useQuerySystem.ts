import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getGraphStats,
  postQuery,
  type QueryFilters,
  type QueryResponse,
} from '../api/client'

export interface ConversationItem {
  id: string
  role: 'user' | 'assistant'
  query?: string
  response?: QueryResponse
  error?: string
}

const defaultFilters: QueryFilters = {
  geo: 'RU',
  year_range: [2010, 2026],
  min_confidence: 0.6,
  numeric_filters: [
    { parameter: 'сульфаты', operator: 'range', value: 200, value_max: 300, unit: 'мг/л' },
    { parameter: 'сухой остаток', operator: '<=', value: 1000, unit: 'мг/дм³' },
  ],
}

let nextId = 0
function genId(): string {
  nextId += 1
  return `msg-${nextId}`
}

export function useQuerySystem() {
  const [filters, setFilters] = useState<QueryFilters>(defaultFilters)
  const [conversation, setConversation] = useState<ConversationItem[]>([])
  const [loading, setLoading] = useState(false)
  const [entityCount, setEntityCount] = useState<number | null>(null)
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null)
  const [flashNodeId, setFlashNodeId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const currentResponse = [...conversation]
    .reverse()
    .find((item) => item.role === 'assistant' && item.response)?.response ?? null

  useEffect(() => {
    getGraphStats()
      .then((stats) => setEntityCount(stats.entity_count))
      .catch(() => setEntityCount(null))
  }, [])

  const highlightNode = useCallback((docId: string) => {
    setHighlightedNodeId(docId)
    setFlashNodeId(docId)
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    flashTimerRef.current = setTimeout(() => setFlashNodeId(null), 1500)
  }, [])

  const sendQuery = useCallback(
    async (text: string) => {
      const query = text.trim()
      if (!query) return

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      const userItem: ConversationItem = { id: genId(), role: 'user', query }
      const pendingId = genId()
      setConversation((prev) => [
        ...prev,
        userItem,
        { id: pendingId, role: 'assistant' },
      ])
      setLoading(true)
      setHighlightedNodeId(null)

      try {
        const result = await postQuery({ query, filters }, controller.signal)
        if (controller.signal.aborted) return
        setConversation((prev) =>
          prev.map((item) =>
            item.id === pendingId
              ? { ...item, response: result }
              : item,
          ),
        )
      } catch (err) {
        if (controller.signal.aborted) return
        const message = err instanceof Error ? err.message : 'Ошибка запроса'
        setConversation((prev) =>
          prev.map((item) =>
            item.id === pendingId
              ? { ...item, error: message }
              : item,
          ),
        )
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    },
    [filters],
  )

  const retryLast = useCallback(async () => {
    const lastUser = [...conversation].reverse().find((item) => item.role === 'user')
    if (!lastUser?.query) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const pendingId = genId()
    setConversation((prev) => {
      let lastAssistantIdx = -1
      for (let i = prev.length - 1; i >= 0; i -= 1) {
        const item = prev[i]
        if (item.role === 'assistant' && (item.error || !item.response)) {
          lastAssistantIdx = i
          break
        }
      }
      if (lastAssistantIdx === -1) return prev
      const trimmed = prev.slice(0, lastAssistantIdx)
      return [...trimmed, { id: pendingId, role: 'assistant' as const }]
    })
    setLoading(true)
    setHighlightedNodeId(null)

    try {
      const result = await postQuery({ query: lastUser.query, filters }, controller.signal)
      if (controller.signal.aborted) return
      setConversation((prev) =>
        prev.map((item) =>
          item.id === pendingId ? { ...item, response: result } : item,
        ),
      )
    } catch (err) {
      if (controller.signal.aborted) return
      const message = err instanceof Error ? err.message : 'Ошибка запроса'
      setConversation((prev) =>
        prev.map((item) =>
          item.id === pendingId ? { ...item, error: message } : item,
        ),
      )
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [conversation, filters])

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    }
  }, [])

  return {
    filters,
    setFilters,
    conversation,
    loading,
    entityCount,
    currentResponse,
    highlightedNodeId,
    flashNodeId,
    highlightNode,
    sendQuery,
    retryLast,
  }
}
