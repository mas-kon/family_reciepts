import { Button, Group, Modal, NumberInput, Select, Stack, TextInput } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { api, type ReceiptDetail } from '../api'
import { categoryOptions } from '../format'
import { notifyError, notifyOk, useCategories, useUsers } from '../hooks'

export function ManualExpenseModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const cats = useCategories()
  const users = useUsers()
  const [name, setName] = useState('')
  const [amount, setAmount] = useState<number | string>('')
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [userId, setUserId] = useState<string | null>(null)
  const [date, setDate] = useState(dayjs().format('YYYY-MM-DDTHH:mm'))

  const save = useMutation({
    mutationFn: () =>
      api<ReceiptDetail>('/receipts/manual', {
        method: 'POST',
        json: {
          name,
          amount: Number(amount),
          category_id: categoryId ? Number(categoryId) : null,
          user_id: userId ? Number(userId) : null,
          purchased_at: date || null,
        },
      }),
    onSuccess: () => {
      notifyOk('Трата записана')
      qc.invalidateQueries()
      setName('')
      setAmount('')
      onClose()
    },
    onError: notifyError,
  })

  return (
    <Modal opened={opened} onClose={onClose} title="Трата без чека">
      <Stack>
        <NumberInput label="Сумма, €" value={amount} onChange={setAmount} decimalScale={2} min={0} decimalSeparator="," data-autofocus />
        <TextInput
          label="Описание"
          description="Можно оставить пустым, например если видна только сумма в банке"
          placeholder="Без описания"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Select
          label="Категория"
          placeholder="Без категории"
          clearable
          searchable
          value={categoryId}
          onChange={setCategoryId}
          data={categoryOptions(cats.data ?? [], true)}
        />
        <Select
          label="Кто потратил"
          placeholder="Я"
          clearable
          value={userId}
          onChange={setUserId}
          data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.name }))}
        />
        <TextInput label="Когда" type="datetime-local" value={date} onChange={(e) => setDate(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!amount}>
            Записать
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
