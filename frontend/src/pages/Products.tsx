import { Anchor, Card, Grid, Loader, ScrollArea, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconSearch } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs, type PricePoint, type Product } from '../api'
import { PriceLine } from '../components/Charts'
import { dateOnly, money } from '../format'

export default function Products() {
  const [search, setSearch] = useState('')
  const [q] = useDebouncedValue(search, 300)
  const [selected, setSelected] = useState<Product | null>(null)

  const list = useQuery({
    queryKey: ['products', q],
    queryFn: () => api<Product[]>(`/products${qs({ q, limit: 200 })}`),
  })
  const prices = useQuery({
    queryKey: ['prices', selected?.name_normalized],
    queryFn: () => api<PricePoint[]>(`/products/prices${qs({ name: selected!.name_normalized })}`),
    enabled: !!selected,
  })

  return (
    <Stack>
      <Title order={2}>Динамика цен</Title>
      <Text c="dimmed" size="sm">
        Товары из чеков, сгруппированные по названию. Цена за единицу в евро.
      </Text>
      <Grid>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Card withBorder padding="xs">
            <TextInput
              placeholder="Найти товар"
              leftSection={<IconSearch size={16} />}
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
              mb="xs"
            />
            {list.isLoading ? (
              <Loader size="sm" />
            ) : (
              <ScrollArea h={560}>
                <Table highlightOnHover fz="sm">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Товар</Table.Th>
                      <Table.Th className="num">Покупок</Table.Th>
                      <Table.Th className="num">Цена</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {list.data?.map((p) => (
                      <Table.Tr
                        key={p.name_normalized}
                        className="clickable-row"
                        bg={selected?.name_normalized === p.name_normalized ? 'var(--mantine-color-blue-light)' : undefined}
                        onClick={() => setSelected(p)}
                      >
                        <Table.Td>
                          <Text size="sm">{p.name_ru || p.name_original}</Text>
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
                {list.data?.length === 0 && <Text c="dimmed">Товаров пока нет</Text>}
              </ScrollArea>
            )}
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Card withBorder padding="md">
            {!selected ? (
              <Text c="dimmed">Выберите товар слева</Text>
            ) : (
              <Stack>
                <div>
                  <Title order={4}>{selected.name_ru || selected.name_original}</Title>
                  <Text size="sm" c="dimmed">
                    {selected.name_original}
                  </Text>
                </div>
                {prices.data ? (
                  <>
                    <PriceLine points={prices.data} />
                    <Table fz="sm">
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>Дата</Table.Th>
                          <Table.Th>Магазин</Table.Th>
                          <Table.Th className="num">Кол-во</Table.Th>
                          <Table.Th className="num">Цена</Table.Th>
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
    </Stack>
  )
}
