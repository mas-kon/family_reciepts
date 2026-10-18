import { Group, Select, SegmentedControl, TextInput } from '@mantine/core'
import dayjs from 'dayjs'
import type { PeriodKey } from '../format'
import { useUsers } from '../hooks'

export interface PeriodState {
  period: PeriodKey
  custom: [string, string]
  userId: string | null
}

export function PeriodFilter({ value, onChange }: { value: PeriodState; onChange: (v: PeriodState) => void }) {
  const users = useUsers()
  return (
    <Group gap="sm" wrap="wrap" align="flex-end">
      <SegmentedControl
        value={value.period}
        onChange={(v) => {
          const period = v as PeriodKey
          // "Период" starts from this month instead of from empty fields (empty meant "everything")
          const custom: [string, string] =
            period === 'custom' && !value.custom[0] && !value.custom[1]
              ? [dayjs().startOf('month').format('YYYY-MM-DD'), dayjs().format('YYYY-MM-DD')]
              : value.custom
          onChange({ ...value, period, custom })
        }}
        data={[
          { value: 'month', label: 'Этот месяц' },
          { value: 'prev', label: 'Прошлый' },
          { value: '3m', label: '3 мес.' },
          { value: 'year', label: 'Год' },
          { value: 'all', label: 'Всё' },
          { value: 'custom', label: 'Период' },
        ]}
      />
      {value.period === 'custom' && (
        <>
          <TextInput
            type="date"
            aria-label="С"
            value={value.custom[0]}
            onChange={(e) => onChange({ ...value, custom: [e.currentTarget.value, value.custom[1]] })}
          />
          <TextInput
            type="date"
            aria-label="По"
            value={value.custom[1]}
            onChange={(e) => onChange({ ...value, custom: [value.custom[0], e.currentTarget.value] })}
          />
        </>
      )}
      <Select
        placeholder="Все"
        clearable
        w={180}
        value={value.userId}
        onChange={(v) => onChange({ ...value, userId: v })}
        data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.name }))}
      />
    </Group>
  )
}
