import { ActionIcon, Button, Group, NumberInput, Select, Stack, Table, Text } from '@mantine/core'
import { IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type BudgetRow } from '../../api'
import { categoryName, categoryOptions, money } from '../../format'
import { notifyError, useCategories } from '../../hooks'

export default function Budgets() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const cats = useCategories()
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [amount, setAmount] = useState<number | string>('')
  const list = useQuery({ queryKey: ['budgets'], queryFn: () => api<{ month: string; items: BudgetRow[] }>('/budgets') })

  const save = useMutation({
    mutationFn: () => api('/budgets', { method: 'PUT', json: { category_id: Number(categoryId), amount: Number(amount) } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['budgets'] })
      setAmount('')
      setCategoryId(null)
    },
    onError: notifyError,
  })
  const del = useMutation({
    mutationFn: (id: number) => api(`/budgets/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['budgets'] }),
    onError: notifyError,
  })

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {t('budgets.hint')}
      </Text>
      <Group align="flex-end">
        <Select label={t('budgets.category')} searchable w={260} value={categoryId} onChange={setCategoryId} data={categoryOptions(cats.data ?? [])} />
        <NumberInput label={t('budgets.limit_eur')} w={140} value={amount} onChange={setAmount} min={1} />
        <Button onClick={() => save.mutate()} disabled={!categoryId || !amount} loading={save.isPending}>
          {t('common.save')}
        </Button>
      </Group>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('budgets.category')}</Table.Th>
            <Table.Th className="num">{t('budgets.col_limit')}</Table.Th>
            <Table.Th className="num">{t('budgets.col_spent', { month: list.data?.month })}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {list.data?.items.map((b) => (
            <Table.Tr key={b.id}>
              <Table.Td>{categoryName(cats.data, b.category_id)}</Table.Td>
              <Table.Td className="num">{money(b.amount)}</Table.Td>
              <Table.Td className="num">
                {money(b.spent)} ({b.percent}%)
              </Table.Td>
              <Table.Td>
                <ActionIcon variant="subtle" color="red" aria-label={t('common.delete')} onClick={() => confirm(t('budgets.delete_confirm')) && del.mutate(b.id)}>
                  <IconTrash size={16} />
                </ActionIcon>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}
