import { Group, SegmentedControl, Stack, Table, Text } from '@mantine/core'
import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { MonthRow, PricePoint } from '../api'
import { dateOnly, money, monthLabel } from '../format'
import { usePalette } from '../palette'

const fmt = (v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: 0 })

function TooltipBox({ title, lines }: { title: string; lines: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="chart-tooltip">
      <Text size="xs" fw={600} mb={2}>
        {title}
      </Text>
      {lines.map((l) => (
        <Group key={l.label} gap={6} wrap="nowrap">
          {l.color && <span style={{ width: 8, height: 8, borderRadius: 2, background: l.color, flex: 'none' }} />}
          <Text size="xs" c="dimmed">
            {l.label}
          </Text>
          <Text size="xs" ml="auto" className="num">
            {l.value}
          </Text>
        </Group>
      ))}
    </div>
  )
}

/** Single-series horizontal bars, sorted, with direct value labels. */
export function HBars({
  data,
  height,
  onClick,
}: {
  data: { name: string; amount: number; key?: string | number | null }[]
  height?: number
  onClick?: (key: string | number | null | undefined) => void
}) {
  const p = usePalette()
  const h = height ?? Math.max(120, data.length * 30 + 20)
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 80, top: 0, bottom: 0 }} barCategoryGap={2}>
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="name"
          width={150}
          tick={{ fontSize: 12, fill: p.axis }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          cursor={{ fill: p.grid, opacity: 0.5 }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                title={String(payload[0].payload.name)}
                lines={[{ label: 'Сумма', value: money(payload[0].payload.amount) }]}
              />
            ) : null
          }
        />
        <Bar
          dataKey="amount"
          fill={p.series[0]}
          radius={[0, 4, 4, 0]}
          maxBarSize={20}
          cursor={onClick ? 'pointer' : undefined}
          onClick={onClick ? (d) => onClick((d as unknown as { key?: string | number | null }).key) : undefined}
        >
          <LabelList
            dataKey="amount"
            position="right"
            formatter={(v: unknown) => money(Number(v))}
            style={{ fontSize: 12, fill: 'var(--mantine-color-text)' }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

const MAX_SERIES = 5
const OTHER = 'Другое'

/** Stacked monthly bars by top categories; the rest folds into "Другое". Has a table view. */
export function MonthlyStack({ rows }: { rows: MonthRow[] }) {
  const p = usePalette()
  const [view, setView] = useState('chart')

  const hasIncome = rows.some((r) => r.income)
  const totals: Record<string, number> = {}
  rows.forEach((r) => Object.entries(r.categories).forEach(([k, v]) => (totals[k] = (totals[k] ?? 0) + v)))
  const ranked = Object.keys(totals).sort((a, b) => totals[b] - totals[a])
  const shown = ranked.slice(0, MAX_SERIES)
  const hasOther = ranked.length > MAX_SERIES
  const series = hasOther ? [...shown, OTHER] : shown
  const color = (k: string) => (k === OTHER ? p.other : p.series[shown.indexOf(k)])

  const data = rows.map((r) => {
    const d: Record<string, number | string> = { month: monthLabel(r.month), total: r.total, __income: r.income ?? 0 }
    shown.forEach((k) => (d[k] = r.categories[k] ?? 0))
    if (hasOther) {
      d[OTHER] = Object.entries(r.categories)
        .filter(([k]) => !shown.includes(k))
        .reduce((s, [, v]) => s + v, 0)
    }
    return d
  })

  return (
    <Stack gap="xs">
      <Group justify="flex-end">
        <SegmentedControl
          size="xs"
          value={view}
          onChange={setView}
          data={[
            { value: 'chart', label: 'График' },
            { value: 'table', label: 'Таблица' },
          ]}
        />
      </Group>
      {view === 'chart' ? (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 0 }} barCategoryGap="25%">
            <CartesianGrid vertical={false} stroke={p.grid} />
            <XAxis dataKey="month" tick={{ fontSize: 12, fill: p.axis }} tickLine={false} axisLine={{ stroke: p.grid }} />
            <YAxis tickFormatter={fmt} tick={{ fontSize: 12, fill: p.axis }} tickLine={false} axisLine={false} width={48} />
            <Tooltip
              cursor={{ fill: p.grid, opacity: 0.5 }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <TooltipBox
                    title={`${label} · ${money(Number(payload[0].payload.total))}`}
                    lines={[...payload]
                      .reverse()
                      .filter((x) => Number(x.value) > 0)
                      .map((x) => ({ label: String(x.dataKey), value: money(Number(x.value)), color: color(String(x.dataKey)) }))}
                  />
                ) : null
              }
            />
            <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} />
            {series.map((k, i) => (
              <Bar
                key={k}
                dataKey={k}
                stackId="a"
                fill={color(k)}
                stroke={p.surface}
                strokeWidth={2}
                radius={i === series.length - 1 ? [4, 4, 0, 0] : 0}
                maxBarSize={40}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <Table.ScrollContainer minWidth={500}>
          <Table striped fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Месяц</Table.Th>
                {series.map((k) => (
                  <Table.Th key={k} className="num">
                    {k}
                  </Table.Th>
                ))}
                <Table.Th className="num">Всего</Table.Th>
                {hasIncome && <Table.Th className="num">Доходы</Table.Th>}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.map((d) => (
                <Table.Tr key={String(d.month)}>
                  <Table.Td>{d.month}</Table.Td>
                  {series.map((k) => (
                    <Table.Td key={k} className="num">
                      {Number(d[k]) ? money(Number(d[k])) : '—'}
                    </Table.Td>
                  ))}
                  <Table.Td className="num" fw={600}>
                    {money(Number(d.total))}
                  </Table.Td>
                  {hasIncome && (
                    <Table.Td className="num" c="teal">
                      {Number(d.__income) ? money(Number(d.__income)) : '—'}
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}

/** Unit price over time for one product. */
export function PriceLine({ points }: { points: PricePoint[] }) {
  const p = usePalette()
  const data = points
    .filter((x) => x.unit_price_eur !== null && x.purchased_at)
    .map((x) => ({ ...x, date: dateOnly(x.purchased_at) }))
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ left: 0, right: 16, top: 12, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={p.grid} />
        <XAxis dataKey="date" tick={{ fontSize: 12, fill: p.axis }} tickLine={false} axisLine={{ stroke: p.grid }} />
        <YAxis
          tickFormatter={(v: number) => v.toFixed(2)}
          tick={{ fontSize: 12, fill: p.axis }}
          tickLine={false}
          axisLine={false}
          width={48}
          domain={['auto', 'auto']}
        />
        <Tooltip
          cursor={{ stroke: p.axis, strokeDasharray: '3 3' }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                title={String(payload[0].payload.date)}
                lines={[
                  { label: 'Цена', value: money(Number(payload[0].payload.unit_price_eur)) },
                  { label: 'Магазин', value: payload[0].payload.store ?? '—' },
                ]}
              />
            ) : null
          }
        />
        <Line
          type="monotone"
          dataKey="unit_price_eur"
          stroke={p.series[0]}
          strokeWidth={2}
          dot={{ r: 4, fill: p.series[0], stroke: p.surface, strokeWidth: 2 }}
          activeDot={{ r: 6, stroke: p.surface, strokeWidth: 2 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
