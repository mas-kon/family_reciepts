import { Button, Stack, Text, Title } from '@mantine/core'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { UploadResults } from '../components/UploadResults'
import { useUploadQueue, type UploadItem } from '../useUploadQueue'

const INBOX = 'share-inbox'
const inboxPath = (id: string) => `/share-inbox/${id}`
const MAX_AGE_MS = 6 * 3600 * 1000

/** Files that the service worker put into the cache when the app was chosen in the system share sheet. */
async function takeFromInbox(ids: string[]): Promise<{ file: File; id: string }[]> {
  const cache = await caches.open(INBOX)
  const out: { file: File; id: string }[] = []
  for (const id of ids) {
    const res = await cache.match(inboxPath(id))
    if (!res) continue
    const name = decodeURIComponent(res.headers.get('x-file-name') ?? id)
    out.push({ file: new File([await res.blob()], name, { type: res.headers.get('content-type') ?? '' }), id })
  }
  return out
}

/** Leftovers of shares that were never uploaded (e.g. closed before sign-in). */
async function dropStale() {
  const cache = await caches.open(INBOX)
  for (const req of await cache.keys()) {
    const res = await cache.match(req)
    const savedAt = Number(res?.headers.get('x-saved-at') ?? 0)
    if (Date.now() - savedAt > MAX_AGE_MS) await cache.delete(req)
  }
}

export default function Share() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  // the share id is the upload's client id: reloading the page does not book the receipt twice
  const onSettled = (item: UploadItem) => {
    void caches.open(INBOX).then((c) => c.delete(inboxPath(item.clientId)))
  }
  const { items, add, retry } = useUploadQueue({ onSettled })
  const started = useRef(false)
  const ids = (params.get('ids') ?? '').split(',').filter(Boolean)

  useEffect(() => {
    if (started.current) return
    started.current = true
    void (async () => {
      try {
        await dropStale()
        const taken = await takeFromInbox(ids)
        add(
          taken.map((x) => x.file),
          taken.map((x) => x.id),
        )
      } catch {
        /* the Cache API is not available: nothing to take */
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Stack>
      <Title order={2}>{t('upload.share_title')}</Title>
      {items.length === 0 && <Text c="dimmed">{t('upload.share_empty')}</Text>}
      <UploadResults items={items} onRetry={retry} />
      <Button component={Link} to="/receipts" variant="default" style={{ alignSelf: 'flex-start' }}>
        {t('upload.to_receipts')}
      </Button>
    </Stack>
  )
}
