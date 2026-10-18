import { Alert, Card, Group, Loader, Progress, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, qs, type BudgetRow, type MonthRow, type Summary } from '../api'
import { HBars, MonthlyStack } from '../components/Charts'
import { PeriodFilter, type PeriodState } from '../components/PeriodFilter'
import { money, periodRange } from '../format'

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card withBorder padding="md">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fz={28} fw={700} className="num" ta="left">
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </Card>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card withBorder padding="md">
      <Title order={5} mb="sm">
        {title}
      </Title>
      {children}
    </Card>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [f, setF] = useState<PeriodState>({ period: 'month', custom: ['', ''], userId: null })
  const range = periodRange(f.period, f.custom)
  const params = { ...range, user_id: f.userId }

  const summary = useQuery({
    queryKey: ['summary', params],
    queryFn: () => api<Summary>(`/stats/summary${qs(params)}`),
  })
  const monthly = useQuery({
    queryKey: ['monthly', f.userId],
    queryFn: () => api<MonthRow[]>(`/stats/monthly${qs({ months: 12, user_id: f.userId })}`),
  })
  const budgets = useQuery({
    queryKey: ['budgets'],
    queryFn: () => api<{ month: string; items: BudgetRow[] }>('/budgets'),
  })

  const s = summary.data
  const avgReceipt = s && s.receipts ? s.total / s.receipts : 0

  const openCategory = (id: string | number | null | undefined) => {
    if (id === undefined) return
    if (id === null) id = 'none'
    navigate(`/receipts${qs({ ...range, category_id: id, user_id: f.userId, kind: 'expense' })}`)
  }

  return (
    <Stack>
      <Group justify="space-between" align="flex-end">
        <Title order={2}>Статистика</Title>
      </Group>
      <PeriodFilter value={f} onChange={setF} />

      {summary.isError ? (
        <Alert color="red" title="Не удалось загрузить статистику">
          {(summary.error as Error).message}
        </Alert>
      ) : summary.isLoading || !s ? (
        <Loader />
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
            <Stat label="Потрачено" value={money(s.total)} hint={`Записей: ${s.receipts}, в среднем ${money(avgReceipt)}`} />
            <Stat
              label="Доходы"
              value={money(s.income.total)}
              hint={s.income.by_category.slice(0, 2).map((c) => `${c.name} ${money(c.amount)}`).join(', ') || undefined}
            />
            <Stat
              label="Остаток"
              value={`${s.income.total - s.total >= 0 ? '+' : '−'}${money(Math.abs(s.income.total - s.total))}`}
              hint="Доходы минус расходы"
            />
            <Stat
              label="Внутри семьи"
              value={money(s.transfers_total)}
              hint="Переводы членам семьи, не расход"
            />
          </SimpleGrid>

          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <Section title="По категориям">
              {s.by_category.length ? (
                <HBars
                  data={s.by_category.map((c) => ({ name: c.name ?? 'Без категории', amount: c.amount, key: c.id }))}
                  onClick={openCategory}
                />
              ) : (
                <Text c="dimmed">Нет данных за период</Text>
              )}
            </Section>
            <Section title="Подкатегории">
              {s.by_subcategory.length ? (
                <HBars
                  data={s.by_subcategory.slice(0, 12).map((c) => ({
                    name: c.name ?? 'Без категории',
                    amount: c.amount,
                    key: c.id,
                  }))}
                  onClick={openCategory}
                />
              ) : (
                <Text c="dimmed">Нет данных за период</Text>
              )}
            </Section>
          </SimpleGrid>

          <Section title="По месяцам">
            {monthly.data ? <MonthlyStack rows={monthly.data} /> : <Loader size="sm" />}
          </Section>

          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <Section title="Кто тратит">
              {s.by_user.length ? (
                <HBars data={s.by_user.map((u) => ({ name: u.name ?? 'Не указан', amount: u.amount }))} />
              ) : (
                <Text c="dimmed">—</Text>
              )}
            </Section>
            <Section title="Магазины">
              <Table fz="sm">
                <Table.Tbody>
                  {s.by_store.map((r) => (
                    <Table.Tr key={r.store}>
                      <Table.Td>{r.store}</Table.Td>
                      <Table.Td c="dimmed" className="num">
                        {r.receipts} чек.
                      </Table.Td>
                      <Table.Td className="num">{money(r.amount)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Section>
            <Section title="Самые затратные товары">
              <Table fz="sm">
                <Table.Tbody>
                  {s.top_items.map((r) => (
                    <Table.Tr key={r.name_normalized}>
                      <Table.Td>{r.name_ru || r.name_normalized}</Table.Td>
                      <Table.Td c="dimmed" className="num">
                        ×{r.count}
                      </Table.Td>
                      <Table.Td className="num">{money(r.amount)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Section>
          </SimpleGrid>

          {budgets.data && budgets.data.items.length > 0 && (
            <Section title={`Бюджеты на ${budgets.data.month}`}>
              <Stack gap="sm">
                {budgets.data.items.map((b) => {
                  const state = b.percent >= 100 ? 'превышен' : b.percent >= 80 ? 'почти исчерпан' : 'в норме'
                  const color = b.percent >= 100 ? 'red' : b.percent >= 80 ? 'yellow' : 'teal'
                  return (
                    <div key={b.id}>
                      <Group justify="space-between" mb={4}>
                        <Text size="sm">
                          {b.category} · <Text span c="dimmed" size="sm">{state}</Text>
                        </Text>
                        <Text size="sm" className="num">
                          {money(b.spent)} из {money(b.amount)} ({b.percent}%)
                        </Text>
                      </Group>
                      <Progress value={Math.min(100, b.percent)} color={color} aria-label={b.category} />
                    </div>
                  )
                })}
              </Stack>
            </Section>
          )}
        </>
      )}
    </Stack>
  )
}
