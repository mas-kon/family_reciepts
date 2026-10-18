import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Grid,
  Group,
  Loader,
  Modal,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconArrowLeft,
  IconCheck,
  IconPencil,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconX,
} from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Item, type Kind, type ReceiptDetail } from '../api'
import { categoryOptions, dateOnly, dateTime, kindMoney, money, SOURCE_LABEL, sourceLabel, STATUS_LABEL } from '../format'
import { notifyError, notifyOk, useCategories, useMeta, useUsers } from '../hooks'

type ItemDraft = Pick<Item, 'name_original' | 'name_ru' | 'qty' | 'unit_price' | 'total' | 'warranty_until'>

function ItemRow({
  item,
  kind,
  remember,
  onSaved,
}: {
  item: Item
  kind: Kind
  remember: boolean
  onSaved: (r: ReceiptDetail) => void
}) {
  const cats = useCategories()
  const [edit, setEdit] = useState(false)
  const [d, setD] = useState<ItemDraft>(item)

  const patch = useMutation({
    mutationFn: (body: Partial<Item> & { remember?: boolean }) =>
      api<ReceiptDetail>(`/items/${item.id}`, { method: 'PATCH', json: body }),
    onSuccess: (r) => {
      setEdit(false)
      onSaved(r)
    },
    onError: notifyError,
  })
  const del = useMutation({
    mutationFn: () => api<ReceiptDetail>(`/items/${item.id}`, { method: 'DELETE' }),
    onSuccess: onSaved,
    onError: notifyError,
  })

  const category = (
    <Select
      size="xs"
      searchable
      placeholder="Без категории"
      value={item.category_id ? String(item.category_id) : null}
      // the remembered category is a shop product's; incomes are not remembered
      onChange={(v) => v && patch.mutate({ category_id: Number(v), remember: remember && kind === 'expense' })}
      data={categoryOptions(cats.data ?? [], true, kind === 'income' ? 'income' : 'expense')}
      disabled={kind === 'transfer'}
      allowDeselect={false}
      w={200}
      aria-label="Категория"
    />
  )

  if (!edit) {
    return (
      <Table.Tr>
        <Table.Td>
          <Text size="sm">{item.name_ru || item.name_original}</Text>
          {item.name_ru && (
            <Text size="xs" c="dimmed">
              {item.name_original}
            </Text>
          )}
          {item.warranty_until && (
            <Text size="xs" c="teal">
              🛡 гарантия до {dateOnly(item.warranty_until)}
            </Text>
          )}
        </Table.Td>
        <Table.Td className="num">{item.qty}</Table.Td>
        <Table.Td className="num">{item.unit_price !== null ? item.unit_price.toFixed(2) : '—'}</Table.Td>
        <Table.Td className="num" c={item.total < 0 ? 'teal' : undefined}>
          {money(item.total)}
        </Table.Td>
        <Table.Td>{category}</Table.Td>
        <Table.Td>
          <Group gap={2} wrap="nowrap">
            <ActionIcon variant="subtle" size="sm" aria-label="Изменить" onClick={() => setEdit(true)}>
              <IconPencil size={14} />
            </ActionIcon>
            <ActionIcon variant="subtle" color="red" size="sm" aria-label="Удалить" onClick={() => del.mutate()} loading={del.isPending}>
              <IconTrash size={14} />
            </ActionIcon>
          </Group>
        </Table.Td>
      </Table.Tr>
    )
  }

  return (
    <Table.Tr>
      <Table.Td>
        <Stack gap={4}>
          <TextInput size="xs" value={d.name_ru ?? ''} placeholder="По-русски" onChange={(e) => setD({ ...d, name_ru: e.currentTarget.value })} />
          <TextInput size="xs" value={d.name_original} placeholder="Как в чеке" onChange={(e) => setD({ ...d, name_original: e.currentTarget.value })} />
          <TextInput
            size="xs"
            type="date"
            aria-label="Гарантия до"
            leftSection={<Text size="xs">🛡</Text>}
            value={d.warranty_until ?? ''}
            onChange={(e) => setD({ ...d, warranty_until: e.currentTarget.value || null })}
          />
        </Stack>
      </Table.Td>
      <Table.Td>
        <NumberInput size="xs" w={70} value={d.qty} decimalScale={3} onChange={(v) => setD({ ...d, qty: Number(v) })} />
      </Table.Td>
      <Table.Td>
        <NumberInput size="xs" w={80} value={d.unit_price ?? ''} decimalScale={2} onChange={(v) => setD({ ...d, unit_price: v === '' ? null : Number(v) })} />
      </Table.Td>
      <Table.Td>
        <NumberInput size="xs" w={90} value={d.total} decimalScale={2} onChange={(v) => setD({ ...d, total: Number(v) })} />
      </Table.Td>
      <Table.Td>{category}</Table.Td>
      <Table.Td>
        <Group gap={2} wrap="nowrap">
          <ActionIcon variant="subtle" color="teal" size="sm" aria-label="Сохранить" onClick={() => patch.mutate(d)} loading={patch.isPending}>
            <IconCheck size={14} />
          </ActionIcon>
          <ActionIcon variant="subtle" size="sm" aria-label="Отмена" onClick={() => { setD(item); setEdit(false) }}>
            <IconX size={14} />
          </ActionIcon>
        </Group>
      </Table.Td>
    </Table.Tr>
  )
}

/** Expense / income / transfer inside the family. A transfer asks for the family member and
 * can remember the bank's name for them, so their transfers are never counted as spending. */
function KindControl({ r, onSaved }: { r: ReceiptDetail; onSaved: (r: ReceiptDetail) => void }) {
  const users = useUsers()
  const qc = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [peer, setPeer] = useState<string | null>(r.peer_user_id ? String(r.peer_user_id) : null)
  const [rememberPeer, setRememberPeer] = useState(true)
  const save = useMutation({
    mutationFn: (body: { kind: Kind; peer_user_id?: number | null; remember_peer?: boolean }) =>
      api<ReceiptDetail>(`/receipts/${r.id}`, { method: 'PATCH', json: body }),
    onSuccess: (x, body) => {
      setAsking(false)
      onSaved(x)
      qc.invalidateQueries()
      if (body.remember_peer) notifyOk(`Переводы «${r.counterparty}» теперь всегда внутри семьи`)
    },
    onError: notifyError,
  })
  return (
    <>
      <SegmentedControl
        size="xs"
        value={r.kind}
        onChange={(v) => (v === 'transfer' ? setAsking(true) : save.mutate({ kind: v as Kind }))}
        data={[
          { value: 'expense', label: 'Расход' },
          { value: 'income', label: 'Доход' },
          { value: 'transfer', label: 'Внутри семьи' },
        ]}
      />
      <Modal opened={asking} onClose={() => setAsking(false)} title="Перевод внутри семьи">
        <Stack>
          <Text size="sm">
            Деньги остались в семье: такой перевод не войдёт ни в расходы, ни в доходы. Например, карманные деньги
            ребёнку: он потратит их сам, и эти траты уже будут учтены.
          </Text>
          <Select
            label="Кому или от кого"
            placeholder="Член семьи"
            value={peer}
            onChange={setPeer}
            data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.name }))}
            data-autofocus
          />
          {r.counterparty && (
            <Checkbox
              checked={rememberPeer}
              onChange={(e) => setRememberPeer(e.currentTarget.checked)}
              label={`Запомнить: «${r.counterparty}» это этот член семьи. Его переводы, прошлые и будущие, будут внутри семьи.`}
            />
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setAsking(false)}>
              Отмена
            </Button>
            <Button
              loading={save.isPending}
              onClick={() =>
                save.mutate({
                  kind: 'transfer',
                  peer_user_id: peer ? Number(peer) : null,
                  remember_peer: !!(peer && r.counterparty && rememberPeer),
                })
              }
            >
              Сохранить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
}

function HeaderForm({ r, onSaved, onCancel }: { r: ReceiptDetail; onSaved: (r: ReceiptDetail) => void; onCancel: () => void }) {
  const users = useUsers()
  const [v, setV] = useState({
    store: r.store ?? '',
    purchased_at: r.purchased_at ? dayjs(r.purchased_at).format('YYYY-MM-DDTHH:mm') : '',
    total: r.total ?? 0,
    user_id: r.user_id ? String(r.user_id) : null,
    note: r.note ?? '',
  })
  const save = useMutation({
    mutationFn: () =>
      api<ReceiptDetail>(`/receipts/${r.id}`, {
        method: 'PATCH',
        json: { ...v, store: v.store || null, purchased_at: v.purchased_at || null, user_id: v.user_id ? Number(v.user_id) : null, note: v.note || null },
      }),
    onSuccess: onSaved,
    onError: notifyError,
  })
  return (
    <Stack gap="xs">
      <TextInput label="Магазин" value={v.store} onChange={(e) => setV({ ...v, store: e.currentTarget.value })} />
      <TextInput label="Дата" type="datetime-local" value={v.purchased_at} onChange={(e) => setV({ ...v, purchased_at: e.currentTarget.value })} />
      <NumberInput label="Итог, €" value={v.total} decimalScale={2} onChange={(x) => setV({ ...v, total: Number(x) })} />
      <Select label="Кто" clearable value={v.user_id} onChange={(x) => setV({ ...v, user_id: x })} data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.name }))} />
      <Textarea label="Описание" description="У записи из одной строки описание станет её названием" value={v.note} onChange={(e) => setV({ ...v, note: e.currentTarget.value })} autosize minRows={1} />
      <Group justify="flex-end">
        <Button variant="default" onClick={onCancel}>
          Отмена
        </Button>
        <Button onClick={() => save.mutate()} loading={save.isPending}>
          Сохранить
        </Button>
      </Group>
    </Stack>
  )
}

export default function ReceiptDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const meta = useMeta()
  const [editHeader, setEditHeader] = useState(false)
  const [remember, setRemember] = useState(true)
  const [model, setModel] = useState<string | null>(null)
  const [confirmDelete, confirmCtl] = useDisclosure()
  const key = ['receipt', id]

  const q = useQuery({ queryKey: key, queryFn: () => api<ReceiptDetail>(`/receipts/${id}`) })
  const update = (r: ReceiptDetail) => {
    qc.setQueryData(key, r)
    qc.invalidateQueries({ queryKey: ['receipts'] })
    qc.invalidateQueries({ queryKey: ['summary'] })
  }

  const status = useMutation({
    mutationFn: (s: string) => api<ReceiptDetail>(`/receipts/${id}`, { method: 'PATCH', json: { status: s } }),
    onSuccess: update,
    onError: notifyError,
  })
  const reprocess = useMutation({
    mutationFn: () => api<ReceiptDetail>(`/receipts/${id}/reprocess`, { method: 'POST', json: { model } }),
    onSuccess: (r) => {
      update(r)
      notifyOk(r.status === 'failed' ? 'Нейросеть не ответила' : 'Чек распознан заново')
    },
    onError: notifyError,
  })
  const addItem = useMutation({
    mutationFn: () =>
      api<ReceiptDetail>(`/receipts/${id}/items`, { method: 'POST', json: { name_original: 'Новая позиция', total: 0 } }),
    onSuccess: update,
    onError: notifyError,
  })
  const del = useMutation({
    mutationFn: () => api(`/receipts/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries()
      navigate('/receipts')
    },
    onError: notifyError,
  })

  if (q.isLoading) return <Loader />
  if (!q.data) return <Alert color="red">Чек не найден</Alert>
  const r = q.data
  const diff = r.total !== null ? Math.round((r.items_sum - r.total) * 100) / 100 : 0
  const imgUrl = `/api/receipts/${r.id}/image`

  return (
    <Stack>
      <Group justify="space-between">
        <Group gap="xs">
          <ActionIcon variant="subtle" component={Link} to="/receipts" aria-label="Назад">
            <IconArrowLeft size={18} />
          </ActionIcon>
          <Title order={3}>{r.store || SOURCE_LABEL[r.source]}</Title>
          <Badge color={STATUS_LABEL[r.status]?.color} variant="light">
            {STATUS_LABEL[r.status]?.label}
          </Badge>
        </Group>
        <Group gap="xs">
          {r.status !== 'ok' && (
            <Button size="xs" color="teal" leftSection={<IconCheck size={14} />} onClick={() => status.mutate('ok')} loading={status.isPending}>
              Всё верно
            </Button>
          )}
          <Button size="xs" variant="default" color="red" leftSection={<IconTrash size={14} />} onClick={confirmCtl.open}>
            Удалить
          </Button>
        </Group>
      </Group>

      {r.review_reason && (
        <Alert color={r.status === 'failed' ? 'red' : 'yellow'} title="Что проверить">
          <Text size="sm" style={{ whiteSpace: 'pre-line' }}>
            {r.review_reason}
          </Text>
        </Alert>
      )}

      <Grid>
        {r.has_image && (
          <Grid.Col span={{ base: 12, md: 5 }}>
            <Card withBorder padding="xs">
              <a href={imgUrl} target="_blank" rel="noreferrer">
                <img src={imgUrl} alt="Фото чека" className="receipt-image" />
              </a>
              <Group mt="xs" gap="xs" align="flex-end">
                <Select
                  size="xs"
                  placeholder="Модели из настроек"
                  clearable
                  value={model}
                  onChange={setModel}
                  data={meta.data?.models ?? []}
                  style={{ flex: 1 }}
                  aria-label="Модель"
                />
                <Button size="xs" variant="light" leftSection={<IconRefresh size={14} />} onClick={() => reprocess.mutate()} loading={reprocess.isPending}>
                  Распознать заново
                </Button>
              </Group>
              <Text size="xs" c="dimmed" mt={4}>
                Повторное распознавание заменит все позиции.
              </Text>
            </Card>
          </Grid.Col>
        )}

        <Grid.Col span={{ base: 12, md: r.has_image ? 7 : 12 }}>
          <Stack>
            <Card withBorder padding="md">
              {editHeader ? (
                <HeaderForm r={r} onSaved={(x) => { update(x); setEditHeader(false) }} onCancel={() => setEditHeader(false)} />
              ) : (
                <Group justify="space-between" align="flex-start">
                  <Stack gap={2}>
                    <Text
                      fz={26}
                      fw={700}
                      className="num"
                      ta="left"
                      c={r.kind === 'income' ? 'teal' : r.kind === 'transfer' ? 'dimmed' : undefined}
                    >
                      {kindMoney(r.kind, r.total)}
                    </Text>
                    <KindControl r={r} onSaved={update} />
                    {r.kind === 'transfer' && (
                      <Text size="sm" c="dimmed">
                        Перевод внутри семьи{r.peer_name ? `: ${r.peer_name}` : ''}. В расходы и доходы не входит.
                      </Text>
                    )}
                    <Text size="sm">{dateTime(r.purchased_at)}</Text>
                    <Text size="sm" c="dimmed">
                      {r.user_name ?? 'Кто — не указано'} · {sourceLabel(r)}
                      {r.llm_model && ` · ${r.llm_model}`}
                    </Text>
                    {r.import_id && (
                      <Anchor component={Link} to={`/receipts?import_id=${encodeURIComponent(r.import_id)}`} size="sm">
                        Все записи этой выписки
                      </Anchor>
                    )}
                    {r.note && (
                      <Text size="sm" fw={500}>
                        📝 {r.note}
                      </Text>
                    )}
                  </Stack>
                  <ActionIcon variant="subtle" aria-label="Изменить" onClick={() => setEditHeader(true)}>
                    <IconPencil size={16} />
                  </ActionIcon>
                </Group>
              )}
            </Card>

            <Card withBorder padding="md">
              <Group justify="space-between" mb="xs">
                <Title order={5}>Позиции</Title>
                <Tooltip label="Новая категория применится к этому товару во всех чеках и будущих покупках" multiline w={260}>
                  <Switch size="xs" label="Запоминать категорию" checked={remember} onChange={(e) => setRemember(e.currentTarget.checked)} />
                </Tooltip>
              </Group>
              <Table.ScrollContainer minWidth={640}>
                <Table verticalSpacing={6} fz="sm">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Товар</Table.Th>
                      <Table.Th className="num">Кол-во</Table.Th>
                      <Table.Th className="num">Цена</Table.Th>
                      <Table.Th className="num">Сумма</Table.Th>
                      <Table.Th>Категория</Table.Th>
                      <Table.Th />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {r.items.map((it) => (
                      <ItemRow key={`${it.id}-${it.total}-${it.name_original}-${r.kind}`} item={it} kind={r.kind} remember={remember} onSaved={update} />
                    ))}
                  </Table.Tbody>
                  <Table.Tfoot>
                    <Table.Tr>
                      <Table.Td colSpan={3}>
                        <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => addItem.mutate()} loading={addItem.isPending}>
                          Добавить позицию
                        </Button>
                      </Table.Td>
                      <Table.Td className="num" fw={600}>
                        {money(r.items_sum)}
                      </Table.Td>
                      <Table.Td colSpan={2}>
                        {diff !== 0 && (
                          <Text size="xs" c="yellow.7">
                            расхождение с итогом {diff > 0 ? '+' : ''}
                            {diff.toFixed(2)}
                          </Text>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  </Table.Tfoot>
                </Table>
              </Table.ScrollContainer>
            </Card>
            {r.qr_raw && (
              <Text size="xs" c="dimmed">
                QR: <Anchor size="xs" c="dimmed" component="span">{r.qr_raw}</Anchor>
              </Text>
            )}
          </Stack>
        </Grid.Col>
      </Grid>

      <Modal opened={confirmDelete} onClose={confirmCtl.close} title="Удалить запись?">
        <Text size="sm">Чек, все позиции и фото будут удалены без возможности восстановления.</Text>
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={confirmCtl.close}>
            Отмена
          </Button>
          <Button color="red" onClick={() => del.mutate()} loading={del.isPending}>
            Удалить
          </Button>
        </Group>
      </Modal>
    </Stack>
  )
}
