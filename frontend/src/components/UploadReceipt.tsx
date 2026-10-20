import { Affix, Button, FileButton, Group, Stack } from '@mantine/core'
import { IconCamera, IconPhotoPlus } from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useUploadQueue, type UploadItem } from '../useUploadQueue'
import { UploadResults } from './UploadResults'

/** Camera and gallery buttons for the receipts page, with the progress of what was sent. */
export function UploadReceipt() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  // a single receipt that was recognised cleanly opens at once
  const onSettled = (item: UploadItem, batchSize: number) => {
    const r = item.result
    if (batchSize === 1 && r?.status === 'ok' && r.receipt) navigate(`/receipts/${r.receipt.id}`)
  }
  const { items, add, retry, clear, busy } = useUploadQueue({ onSettled })

  return (
    <Stack gap="xs">
      <Group gap="xs" visibleFrom="sm">
        <FileButton accept="image/*" capture="environment" onChange={(f) => f && add([f])}>
          {(props) => (
            <Button variant="default" leftSection={<IconCamera size={16} />} {...props}>
              {t('upload.camera')}
            </Button>
          )}
        </FileButton>
        <FileButton accept="image/*,application/pdf" multiple onChange={(fs) => add(fs)}>
          {(props) => (
            <Button variant="default" leftSection={<IconPhotoPlus size={16} />} {...props}>
              {t('upload.gallery')}
            </Button>
          )}
        </FileButton>
      </Group>
      <Affix position={{ bottom: 20, right: 20 }} hiddenFrom="sm">
        <Stack gap="xs" align="flex-end">
          <FileButton accept="image/*,application/pdf" multiple onChange={(fs) => add(fs)}>
            {(props) => (
              <Button radius="xl" variant="default" leftSection={<IconPhotoPlus size={18} />} {...props}>
                {t('upload.gallery')}
              </Button>
            )}
          </FileButton>
          <FileButton accept="image/*" capture="environment" onChange={(f) => f && add([f])}>
            {(props) => (
              <Button radius="xl" size="md" leftSection={<IconCamera size={20} />} loading={busy} {...props}>
                {t('upload.camera')}
              </Button>
            )}
          </FileButton>
        </Stack>
      </Affix>
      <UploadResults items={items} onRetry={retry} />
      {items.length > 0 && !busy && (
        <Button size="compact-xs" variant="subtle" onClick={clear} style={{ alignSelf: 'flex-start' }}>
          {t('upload.clear')}
        </Button>
      )}
    </Stack>
  )
}
