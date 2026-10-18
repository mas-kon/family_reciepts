import { ActionIcon, Button, Group, Modal, NumberInput, SegmentedControl, Select, Stack, Switch, Table, Text, TextInput } from '@mantine/core'
import { IconPencil, IconPlus, IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Recurring } from '../../api'
import { categoryName, categoryOptions, money } from '../../format'
import { notifyError, notifyOk, useCategories, useUsers, invalidateRecords } from '../../hooks'

const EMPTY_REC: RecDraft = { name: '', amount: 0, category_id: null, user_id: null, day_of_month: 1, active: true, kind: 'expense' }
type RecDraft = Omit<Recurring, 'id' | 'last_booked_month'> & { id?: number }

export default function RecurringTab() {
  const qc = useQueryClient()
  const cats = useCategories()
  const users = useUsers()
  const [draft, setDraft] = useState<RecDraft | null>(null)
  const list = useQuery({ queryKey: ['recurring'], queryFn: () => api<Recurring[]>('/recurring') })

  const save = useMutation({
    mutationFn: (d: RecDraft) =>
      d.id ? api(`/recurring/${d.id}`, { method: 'PUT', json: d }) : api('/recurring', { method: 'POST', json: d }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['recurring'] })
      setDraft(null)
    },
    onError: notifyError,
  })
  const del = useMutation({
    mutationFn: (id: number) => api(`/recurring/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['recurring'] }),
    onError: notifyError,
  })
  const run = useMutation({
    mutationFn: () => api<{ booked: number }>('/recurring/run', { method: 'POST' }),
    onSuccess: (r) => {
      notifyOk(r.booked ? `Записано платежей: ${r.booked}` : 'Нечего записывать: всё уже учтено')
      invalidateRecords(qc)
    },
    onError: notifyError,
  })

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Аренда, интернет, подписки, а также зарплата и другие регулярные поступления. В нужный день месяца запись
        появляется автоматически, и бот сообщает об этом в группе.
      </Text>
      <Group>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setDraft({ ...EMPTY_REC })}>
          Добавить
        </Button>
        <Button variant="default" onClick={() => run.mutate()} loading={run.isPending}>
          Записать причитающиеся сейчас
        </Button>
      </Group>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Название</Table.Th>
            <Table.Th className="num">Сумма</Table.Th>
            <Table.Th>Категория</Table.Th>
            <Table.Th className="num">День</Table.Th>
            <Table.Th>Последний раз</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {list.data?.map((r) => (
            <Table.Tr key={r.id} opacity={r.active ? 1 : 0.5}>
              <Table.Td>{r.name}</Table.Td>
              <Table.Td className="num" c={r.kind === 'income' ? 'teal' : undefined}>
                {r.kind === 'income' ? `+${money(r.amount)}` : money(r.amount)}
              </Table.Td>
              <Table.Td>{categoryName(cats.data, r.category_id)}</Table.Td>
              <Table.Td className="num">{r.day_of_month}</Table.Td>
              <Table.Td>{r.last_booked_month ?? '—'}</Table.Td>
              <Table.Td>
                <Group gap={2} wrap="nowrap">
                  <ActionIcon variant="subtle" aria-label="Изменить" onClick={() => setDraft(r)}>
                    <IconPencil size={16} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" color="red" aria-label="Удалить" onClick={() => confirm(`Удалить «${r.name}»?`) && del.mutate(r.id)}>
                    <IconTrash size={16} />
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      <Modal opened={!!draft} onClose={() => setDraft(null)} title={draft?.id ? 'Регулярный платёж' : 'Новый регулярный платёж'}>
        {draft && (
          <Stack>
            <SegmentedControl
              value={draft.kind}
              onChange={(v) => setDraft({ ...draft, kind: v as 'expense' | 'income', category_id: null })}
              data={[
                { value: 'expense', label: 'Платёж' },
                { value: 'income', label: 'Поступление' },
              ]}
            />
            <TextInput label="Название" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })} />
            <NumberInput label="Сумма, €" value={draft.amount} decimalScale={2} min={0} onChange={(v) => setDraft({ ...draft, amount: Number(v) })} />
            <Select
              label="Категория"
              searchable
              value={draft.category_id ? String(draft.category_id) : null}
              onChange={(v) => setDraft({ ...draft, category_id: v ? Number(v) : null })}
              data={categoryOptions(cats.data ?? [], true, draft.kind)}
            />
            <Select
              label={draft.kind === 'income' ? 'Кто получает' : 'Кто платит'}
              clearable
              value={draft.user_id ? String(draft.user_id) : null}
              onChange={(v) => setDraft({ ...draft, user_id: v ? Number(v) : null })}
              data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.name }))}
            />
            <NumberInput
              label="День месяца"
              description="31 в коротком месяце означает последний день"
              value={draft.day_of_month}
              min={1}
              max={31}
              onChange={(v) => setDraft({ ...draft, day_of_month: Number(v) || 1 })}
            />
            <Switch label="Активен" checked={draft.active} onChange={(e) => setDraft({ ...draft, active: e.currentTarget.checked })} />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDraft(null)}>
                Отмена
              </Button>
              <Button onClick={() => save.mutate(draft)} disabled={!draft.name || !draft.amount} loading={save.isPending}>
                Сохранить
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  )
}
