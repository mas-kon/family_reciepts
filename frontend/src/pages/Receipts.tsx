import {
  Badge,
  Button,
  Group,
  Loader,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue, useDisclosure } from '@mantine/hooks'
import { IconDownload, IconPhoto, IconPlus, IconSearch } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, qs, type Receipt } from '../api'
import { ManualExpenseModal } from '../components/ManualExpenseModal'
import { categoryOptions, dateTime, money, SOURCE_LABEL, STATUS_LABEL } from '../format'
import { useCategories, useUsers } from '../hooks'

const PAGE = 50

export default function Receipts() {
  const navigate = useNavigate()
  const [sp, setSp] = useSearchParams()
  const [manual, manualCtl] = useDisclosure()
  const users = useUsers()
  const cats = useCategories()

  const get = (k: string) => sp.get(k) ?? ''
  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(sp)
    if (v) next.set(k, v)
    else next.delete(k)
    if (k !== 'page') next.delete('page')
    setSp(next, { replace: true })
  }
  const [q] = useDebouncedValue(get('q'), 300)
  const page = Number(get('page') || 1)

  const params = {
    q,
    user_id: get('user_id'),
    status: get('status'),
    source: get('source'),
    category_id: get('category_id'),
    date_from: get('date_from'),
    date_to: get('date_to'),
    page,
    page_size: PAGE,
  }
  const list = useQuery({
    queryKey: ['receipts', params],
    queryFn: () => api<{ total: number; items: Receipt[] }>(`/receipts${qs(params)}`),
  })

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Чеки</Title>
        <Group gap="xs">
          <Button
            variant="default"
            leftSection={<IconDownload size={16} />}
            component="a"
            href={`/api/export.csv${qs({ date_from: params.date_from, date_to: params.date_to })}`}
          >
            CSV
          </Button>
          <Button leftSection={<IconPlus size={16} />} onClick={manualCtl.open}>
            Трата без чека
          </Button>
        </Group>
      </Group>

      <Group gap="sm" align="flex-end" wrap="wrap">
        <TextInput
          placeholder="Магазин или товар"
          leftSection={<IconSearch size={16} />}
          value={get('q')}
          onChange={(e) => set('q', e.currentTarget.value)}
          w={220}
        />
        <TextInput type="date" aria-label="С" value={get('date_from')} onChange={(e) => set('date_from', e.currentTarget.value)} />
        <TextInput type="date" aria-label="По" value={get('date_to')} onChange={(e) => set('date_to', e.currentTarget.value)} />
        <Select
          placeholder="Кто"
          clearable
          w={150}
          value={get('user_id') || null}
          onChange={(v) => set('user_id', v)}
          data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.name }))}
        />
        <Select
          placeholder="Категория"
          clearable
          searchable
          w={200}
          value={get('category_id') || null}
          onChange={(v) => set('category_id', v)}
          data={[{ group: '', items: [{ value: 'none', label: 'Без категории' }] }, ...categoryOptions(cats.data ?? [])]}
        />
        <Select
          placeholder="Статус"
          clearable
          w={150}
          value={get('status') || null}
          onChange={(v) => set('status', v)}
          data={Object.entries(STATUS_LABEL).map(([value, s]) => ({ value, label: s.label }))}
        />
        <Select
          placeholder="Источник"
          clearable
          w={140}
          value={get('source') || null}
          onChange={(v) => set('source', v)}
          data={Object.entries(SOURCE_LABEL).map(([value, label]) => ({ value, label }))}
        />
      </Group>

      {list.isLoading ? (
        <Loader />
      ) : (
        <>
          <Table.ScrollContainer minWidth={700}>
            <Table highlightOnHover verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Дата</Table.Th>
                  <Table.Th>Магазин / что</Table.Th>
                  <Table.Th>Кто</Table.Th>
                  <Table.Th className="num">Позиций</Table.Th>
                  <Table.Th className="num">Сумма</Table.Th>
                  <Table.Th>Статус</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {list.data?.items.map((r) => (
                  <Table.Tr key={r.id} className="clickable-row" onClick={() => navigate(`/receipts/${r.id}`)}>
                    <Table.Td>{dateTime(r.purchased_at)}</Table.Td>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        {r.has_image && <IconPhoto size={14} opacity={0.5} />}
                        <Text size="sm">{r.title}</Text>
                        {r.source !== 'photo' && (
                          <Badge size="xs" variant="light" color="gray">
                            {SOURCE_LABEL[r.source]}
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td>{r.user_name ?? '—'}</Table.Td>
                    <Table.Td className="num">{r.items_count}</Table.Td>
                    <Table.Td className="num">
                      {money(r.total)}
                    </Table.Td>
                    <Table.Td>
                      <Badge color={STATUS_LABEL[r.status]?.color} variant="light">
                        {STATUS_LABEL[r.status]?.label ?? r.status}
                      </Badge>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {list.data && list.data.items.length === 0 && <Text c="dimmed">Ничего не найдено</Text>}
          {list.data && list.data.total > PAGE && (
            <Pagination total={Math.ceil(list.data.total / PAGE)} value={page} onChange={(p) => set('page', String(p))} />
          )}
        </>
      )}
      <ManualExpenseModal opened={manual} onClose={manualCtl.close} />
    </Stack>
  )
}
