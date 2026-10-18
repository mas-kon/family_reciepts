import { Alert, Card, Group, Loader, Progress, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [f, setF] = useState<PeriodState>({ period: 'month', custom: ['', ''], userId: null })
  const range = periodRange(f.period, f.custom)
  const params = { ...range, user_id: f.userId }
  // the monthly chart follows a longer or a chosen period; for one month it keeps the last 12
  const monthlyRange = ['3m', 'year', 'custom'].includes(f.period) && range.date_from ? range : {}

  const summary = useQuery({
    queryKey: ['summary', params],
    queryFn: () => api<Summary>(`/stats/summary${qs(params)}`),
  })
  const monthly = useQuery({
    queryKey: ['monthly', f.userId, monthlyRange],
    queryFn: () => api<MonthRow[]>(`/stats/monthly${qs({ months: 12, user_id: f.userId, ...monthlyRange })}`),
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
        <Title order={2}>{t('dashboard.title')}</Title>
      </Group>
      <PeriodFilter value={f} onChange={setF} />

      {summary.isError ? (
        <Alert color="red" title={t('dashboard.load_failed')}>
          {(summary.error as Error).message}
        </Alert>
      ) : summary.isLoading || !s ? (
        <Loader />
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
            <Stat label={t('dashboard.spent')}
              value={money(s.total)}
              hint={t('dashboard.spent_hint', { count: s.receipts, avg: money(avgReceipt) })} />
            <Stat
              label={t('dashboard.income')}
              value={money(s.income.total)}
              hint={s.income.by_category.slice(0, 2).map((c) => `${c.name} ${money(c.amount)}`).join(', ') || undefined}
            />
            <Stat
              label={t('dashboard.balance')}
              value={`${s.income.total - s.total >= 0 ? '+' : '−'}${money(Math.abs(s.income.total - s.total))}`}
              hint={t('dashboard.balance_hint')}
            />
            <Stat
              label={t('dashboard.family')}
              value={money(s.transfers_total)}
              hint={t('dashboard.family_hint')}
            />
          </SimpleGrid>

          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <Section title={t('dashboard.by_category')}>
              {s.by_category.length ? (
                <HBars
                  data={s.by_category.map((c) => ({ name: c.name ?? t('category.none'), amount: c.amount, key: c.id }))}
                  onClick={openCategory}
                />
              ) : (
                <Text c="dimmed">{t('dashboard.no_data')}</Text>
              )}
            </Section>
            <Section title={t('dashboard.by_subcategory')}>
              {s.by_subcategory.length ? (
                <HBars
                  data={s.by_subcategory.slice(0, 12).map((c) => ({
                    name: c.name ?? t('category.none'),
                    amount: c.amount,
                    key: c.id,
                  }))}
                  onClick={openCategory}
                />
              ) : (
                <Text c="dimmed">{t('dashboard.no_data')}</Text>
              )}
            </Section>
          </SimpleGrid>

          <Section title={t('dashboard.by_month')}>
            {monthly.data ? <MonthlyStack rows={monthly.data} /> : <Loader size="sm" />}
          </Section>

          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <Section title={t('dashboard.who_spends')}>
              {s.by_user.length ? (
                <HBars data={s.by_user.map((u) => ({ name: u.name ?? t('dashboard.not_set'), amount: u.amount }))} />
              ) : (
                <Text c="dimmed">—</Text>
              )}
            </Section>
            <Section title={t('dashboard.stores')}>
              <Table fz="sm">
                <Table.Tbody>
                  {s.by_store.map((r) => (
                    <Table.Tr key={r.store}>
                      <Table.Td>{r.store}</Table.Td>
                      <Table.Td c="dimmed" className="num">
                        {t('dashboard.receipts_short', { count: r.receipts })}
                      </Table.Td>
                      <Table.Td className="num">{money(r.amount)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Section>
            <Section title={t('dashboard.top_items')}>
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
            <Section title={t('dashboard.budgets', { month: budgets.data.month })}>
              <Stack gap="sm">
                {budgets.data.items.map((b) => {
                  const state = b.percent >= 100 ? t('dashboard.budget_over') : b.percent >= 80 ? t('dashboard.budget_near') : t('dashboard.budget_ok')
                  const color = b.percent >= 100 ? 'red' : b.percent >= 80 ? 'yellow' : 'teal'
                  return (
                    <div key={b.id}>
                      <Group justify="space-between" mb={4}>
                        <Text size="sm">
                          {b.category} · <Text span c="dimmed" size="sm">{state}</Text>
                        </Text>
                        <Text size="sm" className="num">
                          {t('dashboard.budget_of', { spent: money(b.spent), amount: money(b.amount), percent: b.percent })}
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
