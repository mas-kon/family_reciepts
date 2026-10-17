import dayjs from 'dayjs'
import 'dayjs/locale/ru'
import type { Category } from './api'

dayjs.locale('ru')

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
}

export function dateTime(v: string | null | undefined): string {
  return v ? dayjs(v).format('DD.MM.YYYY HH:mm') : '—'
}

export function dateOnly(v: string | null | undefined): string {
  return v ? dayjs(v).format('DD.MM.YYYY') : '—'
}

export function monthLabel(m: string): string {
  return dayjs(`${m}-01`).format('MMM YY')
}

export const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  ok: { label: 'Проверен', color: 'teal' },
  needs_review: { label: 'Проверить', color: 'yellow' },
  pending: { label: 'Обработка', color: 'gray' },
  failed: { label: 'Ошибка', color: 'red' },
}

export const SOURCE_LABEL: Record<string, string> = {
  photo: 'Чек',
  manual: 'Вручную',
  recurring: 'Регулярный',
}

/** Options for a category Select, grouped by parent. */
export function categoryOptions(cats: Category[], leavesOnly = false) {
  const parents = cats.filter((c) => !c.parent_id)
  return parents.map((p) => {
    const children = cats.filter((c) => c.parent_id === p.id)
    const items = children.length
      ? [...(leavesOnly ? [] : [{ value: String(p.id), label: `${p.name} (всё)` }]),
         ...children.map((c) => ({ value: String(c.id), label: c.name }))]
      : [{ value: String(p.id), label: p.name }]
    return { group: p.name, items }
  })
}

export function categoryName(cats: Category[] | undefined, id: number | null): string {
  if (!cats || id === null) return 'Без категории'
  const c = cats.find((x) => x.id === id)
  if (!c) return '—'
  const p = c.parent_id ? cats.find((x) => x.id === c.parent_id) : null
  return p ? `${p.name} / ${c.name}` : c.name
}

export type PeriodKey = 'month' | 'prev' | '3m' | 'year' | 'all' | 'custom'

export function periodRange(key: PeriodKey, custom?: [string, string]): { date_from?: string; date_to?: string } {
  const today = dayjs()
  const f = (d: dayjs.Dayjs) => d.format('YYYY-MM-DD')
  switch (key) {
    case 'month':
      return { date_from: f(today.startOf('month')), date_to: f(today.endOf('month')) }
    case 'prev': {
      const p = today.subtract(1, 'month')
      return { date_from: f(p.startOf('month')), date_to: f(p.endOf('month')) }
    }
    case '3m':
      return { date_from: f(today.subtract(2, 'month').startOf('month')), date_to: f(today) }
    case 'year':
      return { date_from: f(today.startOf('year')), date_to: f(today) }
    case 'custom':
      return { date_from: custom?.[0] || undefined, date_to: custom?.[1] || undefined }
    default:
      return {}
  }
}
