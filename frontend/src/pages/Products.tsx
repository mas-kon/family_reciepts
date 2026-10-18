import {
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Grid,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconArrowsJoin, IconArrowsSplit, IconSearch, IconWand } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, qs, type PricePoint, type Product } from '../api'
import { PriceLine } from '../components/Charts'
import { dateOnly, money } from '../format'
import { notifyError, notifyOk } from '../hooks'

export default function Products() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [q] = useDebouncedValue(search, 300)
  const [selected, setSelected] = useState<Product | null>(null)
  const [checked, setChecked] = useState<Record<string, Product>>({})
  const [mergeName, setMergeName] = useState<string | null>(null)

  const list = useQuery({
    queryKey: ['products', q],
    queryFn: () => api<Product[]>(`/products${qs({ q, limit: 300 })}`),
  })
  const prices = useQuery({
    queryKey: ['prices', selected?.key],
    queryFn: () => api<PricePoint[]>(`/products/prices${qs({ key: selected!.key })}`),
    enabled: !!selected,
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['products'] })
    qc.invalidateQueries({ queryKey: ['prices'] })
    qc.invalidateQueries({ queryKey: ['summary'] })
  }

  const merge = useMutation({
    mutationFn: (product: string) =>
      api<{ lines: number }>('/products/merge', { method: 'POST', json: { keys: Object.keys(checked), product } }),
    onSuccess: (_, product) => {
      notifyOk(t('products.merged'))
      setChecked({})
      setMergeName(null)
      setSelected(null)
      refresh()
      setSearch(product)
    },
    onError: notifyError,
  })
  const split = useMutation({
    mutationFn: (key: string) => api('/products/split', { method: 'POST', json: { key } }),
    onSuccess: () => {
      notifyOk(t('products.split'))
      setSelected(null)
      refresh()
    },
    onError: notifyError,
  })
  const group = useMutation({
    mutationFn: () => api<{ queued: number }>('/products/group', { method: 'POST' }),
    onSuccess: (r) => {
      notifyOk(r.queued ? t('products.grouping', { count: r.queued }) : t('products.no_new'))
      refresh()
    },
    onError: notifyError,
  })

  const checkedList = Object.values(checked)
  const toggle = (p: Product, on: boolean) =>
    setChecked((c) => {
      const next = { ...c }
      if (on) next[p.key] = p
      else delete next[p.key]
      return next
    })

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{t('products.title')}</Title>
        <Button variant="default" leftSection={<IconWand size={16} />} onClick={() => group.mutate()} loading={group.isPending}>
          {t('products.auto_group')}
        </Button>
      </Group>
      <Text c="dimmed" size="sm">
        {t('products.hint')}
      </Text>
      <Grid>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Card withBorder padding="xs">
            <TextInput
              placeholder={t('products.search')}
              leftSection={<IconSearch size={16} />}
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
              mb="xs"
            />
            {checkedList.length > 0 && (
              <Group mb="xs" gap="xs">
                <Button
                  size="xs"
                  leftSection={<IconArrowsJoin size={14} />}
                  disabled={checkedList.length < 2}
                  onClick={() => setMergeName(checkedList[0].name || checkedList[0].key)}
                >
                  {t('products.merge_n', { count: checkedList.length })}
                </Button>
                <Button size="xs" variant="subtle" onClick={() => setChecked({})}>
                  {t('products.unselect')}
                </Button>
              </Group>
            )}
            {list.isLoading ? (
              <Loader size="sm" />
            ) : (
              <ScrollArea h={560}>
                <Table highlightOnHover fz="sm">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th w={30} />
                      <Table.Th>{t('products.col_product')}</Table.Th>
                      <Table.Th className="num">{t('products.col_purchases')}</Table.Th>
                      <Table.Th className="num">{t('products.col_price')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {list.data?.map((p) => (
                      <Table.Tr
                        key={p.key}
                        className="clickable-row"
                        bg={selected?.key === p.key ? 'var(--mantine-color-blue-light)' : undefined}
                        onClick={() => setSelected(p)}
                      >
                        <Table.Td onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            size="xs"
                            aria-label={t('products.select')}
                            checked={!!checked[p.key]}
                            onChange={(e) => toggle(p, e.currentTarget.checked)}
                          />
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">
                            {p.name || p.name_original}
                            {p.variants > 1 && (
                              <Badge size="xs" variant="light" ml={6}>
                                {t('products.variants', { count: p.variants })}
                              </Badge>
                            )}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {p.name_original}
                          </Text>
                        </Table.Td>
                        <Table.Td className="num">{p.count}</Table.Td>
                        <Table.Td className="num">
                          {p.min_price === p.max_price
                            ? money(p.min_price)
                            : `${p.min_price?.toFixed(2)}–${money(p.max_price)}`}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
                {list.data?.length === 0 && <Text c="dimmed">{t('products.none')}</Text>}
              </ScrollArea>
            )}
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Card withBorder padding="md">
            {!selected ? (
              <Text c="dimmed">{t('products.pick')}</Text>
            ) : (
              <Stack>
                <Group justify="space-between" align="flex-start">
                  <div>
                    <Title order={4}>{selected.name || selected.name_original}</Title>
                    <Text size="sm" c="dimmed">
                      {selected.name_original}
                    </Text>
                  </div>
                  {selected.variants > 1 && (
                    <Button
                      size="xs"
                      variant="default"
                      leftSection={<IconArrowsSplit size={14} />}
                      onClick={() => split.mutate(selected.key)}
                      loading={split.isPending}
                    >
                      {t('products.split_btn')}
                    </Button>
                  )}
                </Group>
                {prices.data ? (
                  <>
                    <PriceLine points={prices.data} />
                    <Table fz="sm">
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>{t('products.col_date')}</Table.Th>
                          <Table.Th>{t('products.col_store')}</Table.Th>
                          <Table.Th>{t('products.col_as_receipt')}</Table.Th>
                          <Table.Th className="num">{t('products.col_qty')}</Table.Th>
                          <Table.Th className="num">{t('products.col_price')}</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {[...prices.data].reverse().map((p, i) => (
                          <Table.Tr key={`${p.receipt_id}-${i}`}>
                            <Table.Td>
                              <Anchor component={Link} to={`/receipts/${p.receipt_id}`} size="sm">
                                {dateOnly(p.purchased_at)}
                              </Anchor>
                            </Table.Td>
                            <Table.Td>{p.store ?? '—'}</Table.Td>
                            <Table.Td c="dimmed">{p.name_original}</Table.Td>
                            <Table.Td className="num">{p.qty}</Table.Td>
                            <Table.Td className="num">{money(p.unit_price_eur)}</Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </>
                ) : (
                  <Loader size="sm" />
                )}
              </Stack>
            )}
          </Card>
        </Grid.Col>
      </Grid>

      <Modal opened={mergeName !== null} onClose={() => setMergeName(null)} title={t('products.merge_title')}>
        <Stack>
          <Text size="sm">
            {t('products.merge_text', { names: checkedList.map((p) => p.name || p.name_original).join(', ') })}
          </Text>
          <TextInput
            label={t('products.merge_name')}
            value={mergeName ?? ''}
            onChange={(e) => setMergeName(e.currentTarget.value)}
            data-autofocus
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setMergeName(null)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => mergeName && merge.mutate(mergeName)} disabled={!mergeName?.trim()} loading={merge.isPending}>
              {t('products.merge_btn')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
