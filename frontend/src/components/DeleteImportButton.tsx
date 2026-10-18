import { Button, Group, Modal, Stack, Text, type ButtonProps } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconTrash } from '@tabler/icons-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api'
import { notifyError, notifyOk, invalidateRecords } from '../hooks'

/** Deletes every record booked from one bank statement, after a confirmation. */
export function DeleteImportButton({
  importId,
  count,
  onDone,
  ...props
}: { importId: string; count?: number; onDone?: () => void } & ButtonProps) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [opened, ctl] = useDisclosure()
  const del = useMutation({
    mutationFn: () => api<{ deleted: number }>(`/bank/imports/${encodeURIComponent(importId)}`, { method: 'DELETE' }),
    onSuccess: (r) => {
      notifyOk(t('import.deleted', { count: r.deleted }))
      ctl.close()
      invalidateRecords(qc)
      onDone?.()
    },
    onError: notifyError,
  })
  return (
    <>
      <Button size="xs" variant="default" color="red" leftSection={<IconTrash size={14} />} onClick={ctl.open} {...props}>
        {t('import.delete_all')}
      </Button>
      <Modal opened={opened} onClose={ctl.close} title={t('import.delete_title')}>
        <Stack>
          <Text size="sm">
            {t('import.delete_text', { count: count ? ` (${count})` : '' })}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={ctl.close}>
              {t('common.cancel')}
            </Button>
            <Button color="red" onClick={() => del.mutate()} loading={del.isPending}>
              {t('common.delete')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
}
