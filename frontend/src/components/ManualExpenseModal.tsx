import { Button, Group, Modal, NumberInput, SegmentedControl, Select, Stack, TextInput } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type ReceiptDetail } from '../api'
import { categoryOptions } from '../format'
import { notifyError, notifyOk, useCategories, useUsers, invalidateRecords } from '../hooks'

export function ManualExpenseModal({
  opened,
  onClose,
}: {
  opened: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const cats = useCategories()
  const users = useUsers()
  const [name, setName] = useState('')
  const [amount, setAmount] = useState<number | string>('')
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [userId, setUserId] = useState<string | null>(null)
  const [date, setDate] = useState(dayjs().format('YYYY-MM-DDTHH:mm'))
  const [kind, setKind] = useState<'expense' | 'income'>('expense')
  const income = kind === 'income'

  const save = useMutation({
    mutationFn: () =>
      api<ReceiptDetail>('/receipts/manual', {
        method: 'POST',
        json: {
          name,
          kind,
          amount: Number(amount),
          category_id: categoryId ? Number(categoryId) : null,
          user_id: userId ? Number(userId) : null,
          purchased_at: date || null,
        },
      }),
    onSuccess: () => {
      notifyOk(income ? t('manual.income_saved') : t('manual.expense_saved'))
      invalidateRecords(qc)
      setName('')
      setAmount('')
      onClose()
    },
    onError: notifyError,
  })

  return (
    <Modal opened={opened} onClose={onClose} title={income ? t('manual.title_income') : t('manual.title_expense')}>
      <Stack>
        <SegmentedControl
          value={kind}
          onChange={(v) => {
            setKind(v as 'expense' | 'income')
            setCategoryId(null)
          }}
          data={[
            { value: 'expense', label: t('kind.expense') },
            { value: 'income', label: t('kind.income') },
          ]}
        />
        <NumberInput label={t('manual.amount')} value={amount} onChange={setAmount} decimalScale={2} min={0} decimalSeparator="," data-autofocus />
        <TextInput
          label={t('manual.description')}
          description={
            income
              ? t('manual.desc_income')
              : t('manual.desc_expense')
          }
          placeholder={income ? t('manual.placeholder_income') : t('manual.placeholder_expense')}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Select
          label={t('manual.category')}
          placeholder={income ? t('manual.category_income') : t('category.none')}
          clearable
          searchable
          value={categoryId}
          onChange={setCategoryId}
          data={categoryOptions(cats.data ?? [], true, kind)}
        />
        <Select
          label={income ? t('manual.who_income') : t('manual.who_expense')}
          placeholder={t('manual.me')}
          clearable
          value={userId}
          onChange={setUserId}
          data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.name }))}
        />
        <TextInput label={t('manual.when')} type="datetime-local" value={date} onChange={(e) => setDate(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!amount}>
            {t('manual.record')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
