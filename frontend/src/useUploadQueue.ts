import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'
import { api, ApiError, type UploadResult } from './api'
import { invalidateRecords } from './hooks'

export interface UploadItem {
  id: string
  file: File
  /** sent with every attempt: a repeated request returns the same record as a duplicate */
  clientId: string
  state: 'queued' | 'uploading' | 'done' | 'error'
  result?: UploadResult
  error?: string
}

interface Options {
  /** called when a file is finished for good: recognised or rejected by the server */
  onSettled?: (item: UploadItem, batchSize: number) => void
}

const NETWORK_RETRIES = 2

function uuid(): string {
  return crypto.randomUUID()
}

async function send(item: UploadItem): Promise<UploadResult> {
  let last: unknown
  for (let attempt = 0; attempt <= NETWORK_RETRIES; attempt++) {
    const fd = new FormData()
    fd.append('file', item.file)
    fd.append('client_id', item.clientId)
    try {
      return await api<UploadResult>('/receipts/upload', { method: 'POST', body: fd })
    } catch (e) {
      last = e
      // a server answer is final; only a lost connection is repeated
      if (e instanceof ApiError) throw e
    }
  }
  throw last
}

/** Uploads receipt files one at a time (the server recognises two at once at most). */
export function useUploadQueue({ onSettled }: Options = {}) {
  const qc = useQueryClient()
  const [items, setItems] = useState<UploadItem[]>([])
  const running = useRef(false)
  const pending = useRef<UploadItem[]>([])
  const batch = useRef(0)

  const patch = useCallback((id: string, change: Partial<UploadItem>) => {
    setItems((all) => all.map((i) => (i.id === id ? { ...i, ...change } : i)))
  }, [])

  const drain = useCallback(async () => {
    if (running.current) return
    running.current = true
    try {
      for (let item = pending.current.shift(); item; item = pending.current.shift()) {
        patch(item.id, { state: 'uploading', error: undefined })
        try {
          const result = await send(item)
          const done = { ...item, state: 'done' as const, result }
          patch(item.id, { state: 'done', result })
          invalidateRecords(qc)
          onSettled?.(done, batch.current)
        } catch (e) {
          patch(item.id, { state: 'error', error: (e as Error).message })
        }
      }
    } finally {
      running.current = false
    }
  }, [onSettled, patch, qc])

  const add = useCallback(
    (files: File[], clientIds?: string[]) => {
      const fresh = files.map<UploadItem>((file, n) => ({
        id: uuid(),
        file,
        clientId: clientIds?.[n] ?? uuid(),
        state: 'queued',
      }))
      if (fresh.length === 0) return
      batch.current = fresh.length
      setItems((all) => [...all, ...fresh])
      pending.current.push(...fresh)
      void drain()
    },
    [drain],
  )

  const retry = useCallback(
    (id: string) => {
      const item = items.find((i) => i.id === id)
      if (!item) return
      patch(id, { state: 'queued', error: undefined })
      pending.current.push(item)
      void drain()
    },
    [drain, items, patch],
  )

  const clear = useCallback(() => setItems((all) => all.filter((i) => i.state === 'queued' || i.state === 'uploading')), [])

  return { items, add, retry, clear, busy: items.some((i) => i.state === 'queued' || i.state === 'uploading') }
}
