import { Button, Group, Modal, Stack, Text, type ButtonProps } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconTrash } from '@tabler/icons-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { notifyError, notifyOk } from '../hooks'

/** Deletes every record booked from one bank statement, after a confirmation. */
export function DeleteImportButton({
  importId,
  count,
  onDone,
  ...props
}: { importId: string; count?: number; onDone?: () => void } & ButtonProps) {
  const qc = useQueryClient()
  const [opened, ctl] = useDisclosure()
  const del = useMutation({
    mutationFn: () => api<{ deleted: number }>(`/bank/imports/${encodeURIComponent(importId)}`, { method: 'DELETE' }),
    onSuccess: (r) => {
      notifyOk(`Выписка удалена, записей: ${r.deleted}`)
      ctl.close()
      qc.invalidateQueries()
      onDone?.()
    },
    onError: notifyError,
  })
  return (
    <>
      <Button size="xs" variant="default" color="red" leftSection={<IconTrash size={14} />} onClick={ctl.open} {...props}>
        Удалить всю выписку
      </Button>
      <Modal opened={opened} onClose={ctl.close} title="Удалить выписку?">
        <Stack>
          <Text size="sm">
            Будут удалены все записи, добавленные из этой выписки{count ? ` (${count})` : ''}. Остальные траты не
            затронутся.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={ctl.close}>
              Отмена
            </Button>
            <Button color="red" onClick={() => del.mutate()} loading={del.isPending}>
              Удалить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
}
