import dayjs from 'dayjs'
import type { Category } from './api'
import i18n, { intlLocale } from './i18n'

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${v.toLocaleString(intlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`
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

export const STATUS_COLOR: Record<string, string> = {
  ok: 'teal',
  needs_review: 'yellow',
  pending: 'gray',
  failed: 'red',
}

/** Badge text and colour of a record status. */
export const statusLabel = (status: string) => ({
  label: i18n.t(`status.${status}`),
  color: STATUS_COLOR[status] ?? 'gray',
})

export const sourceName = (source: string) => i18n.t(`source.${source}`)

/** "Statement" for records booked from a bank statement, otherwise the source name. */
export const sourceLabel = (r: { source: string; import_id?: string | null }) =>
  r.import_id ? i18n.t('source.statement') : sourceName(r.source)

export const kindLabel = (kind: string) => i18n.t(`kind.${kind}`)

/** Signed amount: "+1500.00 €" for an income, plain for an expense. */
export const kindMoney = (kind: string, v: number | null | undefined) =>
  kind === 'income' ? `+${money(v)}` : money(v)

/** Options for a category Select, grouped by parent. */
export function categoryOptions(cats: Category[], leavesOnly = false, kind: 'expense' | 'income' = 'expense') {
  const parents = cats.filter((c) => !c.parent_id && (c.kind ?? 'expense') === kind)
  return parents.map((p) => {
    const children = cats.filter((c) => c.parent_id === p.id)
    const items = children.length
      ? [...(leavesOnly ? [] : [{ value: String(p.id), label: i18n.t('category.all', { name: p.name }) }]),
         ...children.map((c) => ({ value: String(c.id), label: c.name }))]
      : [{ value: String(p.id), label: p.name }]
    return { group: p.name, items }
  })
}

export function categoryName(cats: Category[] | undefined, id: number | null): string {
  if (!cats || id === null) return i18n.t('category.none')
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

const SOURCES = ['photo', 'manual', 'recurring', 'bank', 'voice', 'email']
const KINDS = ['expense', 'income', 'transfer']

export const statusOptions = () => Object.keys(STATUS_COLOR).map((value) => ({ value, label: i18n.t(`status.${value}`) }))
export const sourceOptions = () => SOURCES.map((value) => ({ value, label: sourceName(value) }))
export const kindOptions = () => KINDS.map((value) => ({ value, label: kindLabel(value) }))
