import { Alert, Anchor, Button, Card, Group, Loader, SegmentedControl, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { IconExternalLink, IconRefresh } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, qs, type LLMUsage, type ProviderBalance, type UsageRow } from '../api'
import { notifyError } from '../hooks'
import { usePalette } from '../palette'

/** "$0.0021" for small sums, "$7.21" otherwise */
const usd = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `$${Math.abs(v) < 0.1 && v !== 0 ? v.toFixed(4) : v.toFixed(2)}`

function BalanceCard({ b, alertBelow }: { b: ProviderBalance; alertBelow: number }) {
  const low = b.balance !== undefined && alertBelow > 0 && b.balance < alertBelow
  const k = b.key
  return (
    <Card withBorder padding="md">
      <Group justify="space-between" mb={4}>
        <Text fw={600}>{b.provider}</Text>
        <Anchor href={b.url} target="_blank" size="xs">
          <Group gap={2}>
            на сайте <IconExternalLink size={12} />
          </Group>
        </Anchor>
      </Group>
      {b.balance !== undefined && (
        <Text fz={28} fw={700} className="num" ta="left" c={low ? 'red' : undefined}>
          {b.currency && b.currency !== 'USD' ? `${b.balance.toFixed(2)} ${b.currency}` : usd(b.balance)}
        </Text>
      )}
      <Stack gap={2}>
        {b.total_credits !== undefined && (
          <Text size="xs" c="dimmed">
            Пополнено всего {usd(b.total_credits)}
          </Text>
        )}
        {k && (
          <>
            {k.limit !== null && (
              <Text size="xs" c="dimmed">
                Лимит ключа {usd(k.limit)}
                {k.limit_reset === 'monthly' ? ' в месяц' : k.limit_reset === 'daily' ? ' в день' : ''}, осталось{' '}
                {usd(k.limit_remaining)}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              Списано с OpenRouter: сегодня {usd(k.usage_daily)}, за месяц {usd(k.usage_monthly)}
            </Text>
            <Text size="xs" c="dimmed">
              Через свои ключи за месяц: {usd(k.byok_usage_monthly)}
            </Text>
            {k.free_requests_remaining !== null && (
              <Text size="xs" c="dimmed">
                Бесплатных запросов к :free моделям сегодня осталось: {k.free_requests_remaining}
              </Text>
            )}
          </>
        )}
        {b.error && (
          <Text size="xs" c="red">
            {b.error}
          </Text>
        )}
      </Stack>
    </Card>
  )
}

function UsageTable({ rows, first }: { rows: (UsageRow & { name: string; sub?: string | null })[]; first: string }) {
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table fz="sm" striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{first}</Table.Th>
            <Table.Th className="num">Запросов</Table.Th>
            <Table.Th className="num">Ошибок</Table.Th>
            <Table.Th className="num">OpenRouter</Table.Th>
            <Table.Th className="num">Свои ключи</Table.Th>
            <Table.Th className="num">За запрос</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r) => {
            const ok = r.calls - r.failed
            return (
              <Table.Tr key={`${r.name}-${r.sub ?? ''}`}>
                <Table.Td>
                  {r.name}
                  {r.sub && (
                    <Text span size="xs" c="dimmed">
                      {' '}
                      {r.sub}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td className="num">
                  {r.calls}
                  {r.byok_calls > 0 && (
                    <Text span size="xs" c="dimmed">
                      {' '}
                      (свои {r.byok_calls})
                    </Text>
                  )}
                </Table.Td>
                <Table.Td className="num" c={r.failed ? 'red' : undefined}>
                  {r.failed || '—'}
                </Table.Td>
                <Table.Td className="num">{usd(r.cost)}</Table.Td>
                <Table.Td className="num">{usd(r.byok_cost)}</Table.Td>
                <Table.Td className="num">{ok ? usd((r.cost + r.byok_cost) / ok) : '—'}</Table.Td>
              </Table.Tr>
            )
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

export function LLMPanel() {
  const qc = useQueryClient()
  const p = usePalette()
  const [days, setDays] = useState('30')
  const balance = useQuery({
    queryKey: ['llm-balance'],
    queryFn: () => api<{ alert_below: number; providers: ProviderBalance[] }>('/llm/balance'),
  })
  const usage = useQuery({
    queryKey: ['llm-usage', days],
    queryFn: () => api<LLMUsage>(`/llm/usage${qs({ days })}`),
  })
  const refresh = async () => {
    try {
      const fresh = await api<{ alert_below: number; providers: ProviderBalance[] }>('/llm/balance?fresh=true')
      qc.setQueryData(['llm-balance'], fresh)
      qc.invalidateQueries({ queryKey: ['llm-usage'] })
    } catch (e) {
      notifyError(e)
    }
  }
  const u = usage.data

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={4}>Баланс</Title>
        <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} onClick={refresh}>
          Обновить
        </Button>
      </Group>
      {balance.isLoading ? (
        <Loader size="sm" />
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
          {balance.data?.providers.map((b) => (
            <BalanceCard key={b.provider} b={b} alertBelow={balance.data.alert_below} />
          ))}
          {!balance.data?.providers.some((b) => b.provider === 'DeepSeek') && (
            <Card withBorder padding="md">
              <Text fw={600} mb={4}>
                DeepSeek
              </Text>
              <Text size="xs" c="dimmed">
                Чтобы видеть баланс своего ключа DeepSeek, впишите его в .env как DEEPSEEK_API_KEY и перезапустите
                сервис.
              </Text>
            </Card>
          )}
          <Card withBorder padding="md">
            <Text fw={600} mb={4}>
              Google AI Studio
            </Text>
            <Text size="xs" c="dimmed">
              Баланса нет: бесплатный уровень ограничивает число запросов в минуту и в день, а не деньги. Сколько
              запросов прошло через ваш ключ, видно ниже в колонке «свои».
            </Text>
          </Card>
        </SimpleGrid>
      )}
      {!!balance.data?.alert_below && (
        <Text size="xs" c="dimmed">
          Бот предупредит в группе, когда останется меньше {usd(balance.data.alert_below)} (LLM_BALANCE_ALERT).
        </Text>
      )}

      <Group justify="space-between" mt="md">
        <Title order={4}>Расход</Title>
        <SegmentedControl
          size="xs"
          value={days}
          onChange={setDays}
          data={[
            { value: '1', label: 'Сегодня' },
            { value: '7', label: '7 дней' },
            { value: '30', label: '30 дней' },
            { value: '90', label: '90 дней' },
          ]}
        />
      </Group>
      <Text size="sm" c="dimmed">
        «OpenRouter» списано с баланса OpenRouter. «Свои ключи» оплачено вашими ключами у провайдеров (BYOK), если
        OpenRouter отправил запрос через них. Суммы в долларах, как считают провайдеры. Учитываются запросы с момента
        включения учёта.
      </Text>
      {!u ? (
        <Loader size="sm" />
      ) : u.total.calls === 0 ? (
        <Text c="dimmed">Запросов за период не было.</Text>
      ) : (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }}>
            {[
              ['Запросов', String(u.total.calls)],
              ['Ошибок', String(u.total.failed)],
              ['OpenRouter', usd(u.total.cost)],
              ['Свои ключи', usd(u.total.byok_cost)],
            ].map(([label, value]) => (
              <Card withBorder padding="sm" key={label}>
                <Text size="xs" c="dimmed">
                  {label}
                </Text>
                <Text fz={20} fw={700} className="num" ta="left">
                  {value}
                </Text>
              </Card>
            ))}
          </SimpleGrid>
          {u.by_day.length > 1 && (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={u.by_day} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke={p.grid} />
                <XAxis dataKey="day" tickFormatter={(d: string) => d.slice(8, 10) + '.' + d.slice(5, 7)} stroke={p.axis} fontSize={11} />
                <YAxis tickFormatter={(v: number) => `$${v.toFixed(2)}`} stroke={p.axis} fontSize={11} width={52} />
                <Tooltip formatter={(v) => usd(Number(v))} labelFormatter={(d) => String(d)} />
                <Legend />
                <Bar dataKey="cost" name="OpenRouter" stackId="a" fill={p.series[0]} />
                <Bar dataKey="byok_cost" name="Свои ключи" stackId="a" fill={p.series[1]} />
              </BarChart>
            </ResponsiveContainer>
          )}
          <Title order={5}>По задачам</Title>
          <UsageTable first="Задача" rows={u.by_task.map((r) => ({ ...r, name: r.label }))} />
          <Title order={5}>По моделям</Title>
          <UsageTable
            first="Модель"
            rows={u.by_model.map((r) => ({ ...r, name: r.model, sub: r.provider ?? (r.failed === r.calls ? 'ошибка' : null) }))}
          />
          {u.by_model.some((r) => r.byok_calls < r.calls - r.failed) && (
            <Alert color="yellow" variant="light">
              Часть запросов оплачена с баланса OpenRouter, а не вашими ключами: OpenRouter отправил их другому
              провайдеру, он указан рядом с моделью. Как это изменить, написано в README, раздел «Расходы».
            </Alert>
          )}
        </>
      )}
    </Stack>
  )
}
