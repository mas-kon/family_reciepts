import { Alert, Anchor, Badge, Button, Group, Loader, Stack, Text } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { UploadItem } from '../useUploadQueue'

const COLORS: Record<string, string> = {
  ok: 'teal',
  needs_review: 'yellow',
  failed: 'red',
  duplicate: 'gray',
  maybe_duplicate: 'yellow',
  not_receipt: 'gray',
  statement: 'blue',
}

/** What came of each uploaded file, with a link to the record. */
export function UploadResults({ items, onRetry }: { items: UploadItem[]; onRetry: (id: string) => void }) {
  const { t } = useTranslation()
  if (items.length === 0) return null
  return (
    <Stack gap="xs">
      {items.map((i) => {
        const r = i.result
        const target = r?.receipt?.id ?? r?.duplicate_of?.id
        return (
          <Alert key={i.id} variant="light" color={i.state === 'error' ? 'red' : (COLORS[r?.status ?? ''] ?? 'gray')} p="xs">
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text size="sm" truncate>
                {i.file.name}
              </Text>
              {i.state === 'queued' && <Badge variant="light" color="gray">{t('upload.queued')}</Badge>}
              {i.state === 'uploading' && (
                <Group gap={6} wrap="nowrap">
                  <Loader size="xs" />
                  <Text size="xs">{t('upload.reading')}</Text>
                </Group>
              )}
              {i.state === 'done' && r && <Badge variant="light" color={COLORS[r.status]}>{t(`upload.status_${r.status}`)}</Badge>}
            </Group>
            {i.state === 'done' && r && (
              <Group gap="sm" mt={4}>
                {target !== undefined && (
                  <Anchor component={Link} to={`/receipts/${target}`} size="sm">
                    {t('upload.open')}
                  </Anchor>
                )}
                {r.status === 'statement' && (
                  <Anchor component={Link} to="/bank" size="sm">
                    {t('upload.open_bank')}
                  </Anchor>
                )}
                {r.alerts.map((a) => (
                  <Text key={a} size="xs" c="orange">
                    {a}
                  </Text>
                ))}
              </Group>
            )}
            {i.state === 'error' && (
              <Group gap="sm" mt={4}>
                <Text size="xs">{i.error}</Text>
                <Button size="compact-xs" variant="default" onClick={() => onRetry(i.id)}>
                  {t('upload.retry')}
                </Button>
              </Group>
            )}
          </Alert>
        )
      })}
    </Stack>
  )
}
