import {
  ActionIcon,
  Button,
  Card,
  Code,
  Group,
  Modal,
  NumberInput,
  Select,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconPencil, IconPlus, IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { api, qs, type BudgetRow, type Category, type Recurring } from '../api'
import { categoryName, categoryOptions, money } from '../format'
import { notifyError, notifyOk, useCategories, useMeta, useUsers } from '../hooks'

function Family() {
  const qc = useQueryClient()
  const users = useUsers()
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['users'] })

  const create = useMutation({
    mutationFn: () => api('/users', { method: 'POST', json: { name } }),
    onSuccess: () => {
      setName('')
      refresh()
    },
    onError: notifyError,
  })
  const rename = useMutation({
    mutationFn: (u: { id: number; name: string }) => api(`/users/${u.id}`, { method: 'PATCH', json: { name: u.name } }),
    onSuccess: () => {
      setEditing(null)
      refresh()
      qc.invalidateQueries({ queryKey: ['receipts'] })
    },
    onError: notifyError,
  })
  const del = useMutation({
    mutationFn: (id: number) => api(`/users/${id}`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: notifyError,
  })

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Участники группы появляются здесь сами после первого сообщения боту. Ребёнка или другого члена семьи без
        Telegram добавьте вручную. Тогда в группе можно записать трату на него: <Code>+ Маша: кино 12</Code>.
        Имя в боте пишется так же, как здесь, достаточно первого слова.
      </Text>
      <Group align="flex-end">
        <TextInput
          label="Новый член семьи"
          placeholder="Маша"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && name && create.mutate()}
          w={240}
        />
        <Button onClick={() => create.mutate()} disabled={!name} loading={create.isPending}>
          Добавить
        </Button>
      </Group>
      <Table maw={520}>
        <Table.Tbody>
          {users.data?.map((u) => (
            <Table.Tr key={u.id}>
              <Table.Td>
                {editing?.id === u.id ? (
                  <TextInput
                    size="xs"
                    value={editing.name}
                    onChange={(e) => setEditing({ ...editing, name: e.currentTarget.value })}
                    onKeyDown={(e) => e.key === 'Enter' && rename.mutate(editing)}
                    onBlur={() => rename.mutate(editing)}
                    autoFocus
                  />
                ) : (
                  u.name
                )}
              </Table.Td>
              <Table.Td c="dimmed">{u.has_telegram ? (u.username ? `@${u.username}` : 'Telegram') : 'без Telegram'}</Table.Td>
              <Table.Td w={90}>
                <Group gap={2} wrap="nowrap">
                  <ActionIcon variant="subtle" size="sm" aria-label="Переименовать" onClick={() => setEditing({ id: u.id, name: u.name })}>
                    <IconPencil size={14} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" size="sm" color="red" aria-label="Удалить" onClick={() => del.mutate(u.id)}>
                    <IconTrash size={14} />
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}

function Budgets() {
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
  })

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Лимит на месяц в евро. Бюджет на верхнюю категорию учитывает все её подкатегории. Бот напишет в группу при 80% и
        при превышении.
      </Text>
      <Group align="flex-end">
        <Select label="Категория" searchable w={260} value={categoryId} onChange={setCategoryId} data={categoryOptions(cats.data ?? [])} />
        <NumberInput label="Лимит, €" w={140} value={amount} onChange={setAmount} min={1} />
        <Button onClick={() => save.mutate()} disabled={!categoryId || !amount} loading={save.isPending}>
          Сохранить
        </Button>
      </Group>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Категория</Table.Th>
            <Table.Th className="num">Лимит</Table.Th>
            <Table.Th className="num">Потрачено ({list.data?.month})</Table.Th>
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
                <ActionIcon variant="subtle" color="red" aria-label="Удалить" onClick={() => del.mutate(b.id)}>
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

const EMPTY_REC = { name: '', amount: 0, category_id: null, user_id: null, day_of_month: 1, active: true }
type RecDraft = Omit<Recurring, 'id' | 'last_booked_month'> & { id?: number }

function RecurringTab() {
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
  })
  const run = useMutation({
    mutationFn: () => api<{ booked: number }>('/recurring/run', { method: 'POST' }),
    onSuccess: (r) => {
      notifyOk(r.booked ? `Записано платежей: ${r.booked}` : 'Нечего записывать: всё уже учтено')
      qc.invalidateQueries()
    },
    onError: notifyError,
  })

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Аренда, интернет, подписки. В нужный день месяца платёж записывается автоматически, и бот сообщает об этом в
        группе.
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
              <Table.Td className="num">{money(r.amount)}</Table.Td>
              <Table.Td>{categoryName(cats.data, r.category_id)}</Table.Td>
              <Table.Td className="num">{r.day_of_month}</Table.Td>
              <Table.Td>{r.last_booked_month ?? '—'}</Table.Td>
              <Table.Td>
                <Group gap={2} wrap="nowrap">
                  <ActionIcon variant="subtle" aria-label="Изменить" onClick={() => setDraft(r)}>
                    <IconPencil size={16} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" color="red" aria-label="Удалить" onClick={() => del.mutate(r.id)}>
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
            <TextInput label="Название" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })} />
            <NumberInput label="Сумма, €" value={draft.amount} decimalScale={2} min={0} onChange={(v) => setDraft({ ...draft, amount: Number(v) })} />
            <Select
              label="Категория"
              searchable
              value={draft.category_id ? String(draft.category_id) : null}
              onChange={(v) => setDraft({ ...draft, category_id: v ? Number(v) : null })}
              data={categoryOptions(cats.data ?? [], true)}
            />
            <Select
              label="Кто платит"
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

function Categories() {
  const qc = useQueryClient()
  const cats = useCategories()
  const [name, setName] = useState('')
  const [parent, setParent] = useState<string | null>(null)
  const [editing, setEditing] = useState<Category | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['categories'] })

  const create = useMutation({
    mutationFn: () => api('/categories', { method: 'POST', json: { name, parent_id: parent ? Number(parent) : null } }),
    onSuccess: () => {
      setName('')
      refresh()
    },
    onError: notifyError,
  })
  const rename = useMutation({
    mutationFn: (c: Category) => api(`/categories/${c.id}`, { method: 'PATCH', json: { name: c.name } }),
    onSuccess: () => {
      setEditing(null)
      refresh()
    },
    onError: notifyError,
  })
  const del = useMutation({
    mutationFn: (id: number) => api(`/categories/${id}`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: notifyError,
  })

  const all = cats.data ?? []
  const parents = all.filter((c) => !c.parent_id)

  const row = (c: Category, indent: boolean) => (
    <Table.Tr key={c.id}>
      <Table.Td pl={indent ? 'xl' : undefined} fw={indent ? 400 : 600}>
        {editing?.id === c.id ? (
          <TextInput
            size="xs"
            value={editing.name}
            onChange={(e) => setEditing({ ...editing, name: e.currentTarget.value })}
            onKeyDown={(e) => e.key === 'Enter' && rename.mutate(editing)}
            onBlur={() => rename.mutate(editing)}
            autoFocus
          />
        ) : (
          c.name
        )}
      </Table.Td>
      <Table.Td w={90}>
        <Group gap={2} wrap="nowrap">
          <ActionIcon variant="subtle" size="sm" aria-label="Переименовать" onClick={() => setEditing(c)}>
            <IconPencil size={14} />
          </ActionIcon>
          <ActionIcon variant="subtle" size="sm" color="red" aria-label="Удалить" onClick={() => del.mutate(c.id)}>
            <IconTrash size={14} />
          </ActionIcon>
        </Group>
      </Table.Td>
    </Table.Tr>
  )

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Нейросеть выбирает категорию из этого списка. Удалить можно только неиспользуемую категорию.
      </Text>
      <Group align="flex-end">
        <TextInput label="Новая категория" value={name} onChange={(e) => setName(e.currentTarget.value)} w={240} />
        <Select
          label="Внутри"
          placeholder="Верхний уровень"
          clearable
          w={220}
          value={parent}
          onChange={setParent}
          data={parents.map((p) => ({ value: String(p.id), label: p.name }))}
        />
        <Button onClick={() => create.mutate()} disabled={!name} loading={create.isPending}>
          Добавить
        </Button>
      </Group>
      <Table maw={520}>
        <Table.Tbody>
          {parents.flatMap((p) => [row(p, false), ...all.filter((c) => c.parent_id === p.id).map((c) => row(c, true))])}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}

function Other() {
  const meta = useMeta()
  const [month, setMonth] = useState(dayjs().subtract(1, 'month').format('YYYY-MM'))
  const send = useMutation({
    mutationFn: () => api(`/reports/send${qs({ month })}`, { method: 'POST' }),
    onSuccess: () => notifyOk('Отчёт отправлен в группу'),
    onError: notifyError,
  })
  return (
    <Stack>
      <Card withBorder>
        <Title order={5} mb="xs">
          Месячный отчёт
        </Title>
        <Text size="sm" c="dimmed" mb="sm">
          Отправляется в группу автоматически 1-го числа в 9:00. Можно отправить вручную.
        </Text>
        <Group align="flex-end">
          <TextInput type="month" label="Месяц" value={month} onChange={(e) => setMonth(e.currentTarget.value)} />
          <Button onClick={() => send.mutate()} loading={send.isPending}>
            Отправить в группу
          </Button>
        </Group>
      </Card>
      <Card withBorder>
        <Title order={5} mb="xs">
          Нейросеть
        </Title>
        <Text size="sm" mb={4}>
          Провайдер: <Code>{meta.data?.llm_base_url}</Code>
        </Text>
        <Text size="sm">Модели по порядку, следующая используется при отказе предыдущей:</Text>
        <Stack gap={2} mt={4}>
          {meta.data?.models.map((m) => (
            <Code key={m}>{m}</Code>
          ))}
        </Stack>
        <Text size="xs" c="dimmed" mt="sm">
          Меняется переменной LLM_MODELS в файле .env, затем перезапуск сервиса.
        </Text>
      </Card>
    </Stack>
  )
}

export default function Settings() {
  return (
    <Stack>
      <Title order={2}>Настройки</Title>
      <Tabs defaultValue="family" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="family">Семья</Tabs.Tab>
          <Tabs.Tab value="budgets">Бюджеты</Tabs.Tab>
          <Tabs.Tab value="recurring">Регулярные платежи</Tabs.Tab>
          <Tabs.Tab value="categories">Категории</Tabs.Tab>
          <Tabs.Tab value="other">Отчёт и нейросеть</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="family" pt="md">
          <Family />
        </Tabs.Panel>
        <Tabs.Panel value="budgets" pt="md">
          <Budgets />
        </Tabs.Panel>
        <Tabs.Panel value="recurring" pt="md">
          <RecurringTab />
        </Tabs.Panel>
        <Tabs.Panel value="categories" pt="md">
          <Categories />
        </Tabs.Panel>
        <Tabs.Panel value="other" pt="md">
          <Other />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
