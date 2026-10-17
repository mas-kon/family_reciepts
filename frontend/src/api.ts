export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

export function qs(params?: Params): string {
  if (!params) return ''
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {}
  const res = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...rest,
    headers: json !== undefined ? { 'Content-Type': 'application/json', ...rest.headers } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

// ---------- types ----------

export interface Category {
  id: number
  name: string
  parent_id: number | null
  sort_order: number
}

export interface User {
  id: number
  name: string
  username: string | null
  has_telegram: boolean
}

export interface Item {
  id: number
  position: number
  name_original: string
  name_ru: string | null
  name_normalized: string
  qty: number
  unit_price: number | null
  total: number
  category_id: number | null
}

export type ReceiptStatus = 'ok' | 'needs_review' | 'pending' | 'failed'

export interface Receipt {
  id: number
  title: string
  source: 'photo' | 'manual' | 'recurring'
  store: string | null
  purchased_at: string | null
  total: number | null
  status: ReceiptStatus
  review_reason: string | null
  user_id: number | null
  user_name: string | null
  items_count: number
  has_image: boolean
  note: string | null
  created_at: string
}

export interface ReceiptDetail extends Receipt {
  items: Item[]
  llm_model: string | null
  qr_raw: string | null
  items_sum: number
}

export interface Summary {
  total: number
  receipts: number
  by_category: { id: number | null; name: string | null; amount: number }[]
  by_subcategory: { id: number | null; name: string | null; parent: string | null; amount: number }[]
  by_user: { id: number | null; name: string | null; amount: number }[]
  by_store: { store: string; amount: number; receipts: number }[]
  top_items: { name_normalized: string; name_ru: string | null; amount: number; count: number }[]
}

export interface MonthRow {
  month: string
  total: number
  categories: Record<string, number>
}

export interface BudgetRow {
  id: number
  category_id: number
  category: string
  amount: number
  spent: number
  percent: number
}

export interface Recurring {
  id: number
  name: string
  amount: number
  category_id: number | null
  user_id: number | null
  day_of_month: number
  active: boolean
  last_booked_month: string | null
}

export interface Product {
  name_normalized: string
  name_ru: string | null
  name_original: string
  count: number
  min_price: number | null
  max_price: number | null
  last_date: string | null
}

export interface PricePoint {
  receipt_id: number
  purchased_at: string | null
  store: string | null
  name_original: string
  qty: number
  unit_price_eur: number | null
}

export interface Meta {
  models: string[]
  llm_base_url: string
}
