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
  kind: 'expense' | 'income'
}

export type Kind = 'expense' | 'income' | 'transfer'

export interface User {
  id: number
  name: string
  username: string | null
  has_telegram: boolean
  cards: string
  emails: string
  /** how the bank writes this person in transfers, comma-separated */
  bank_names: string
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
  warranty_until: string | null
}

export type ReceiptStatus = 'ok' | 'needs_review' | 'pending' | 'failed'

export interface Receipt {
  id: number
  title: string
  source: 'photo' | 'manual' | 'recurring' | 'bank' | 'voice' | 'email'
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
  /** records booked from one bank statement share it */
  import_id: string | null
  kind: Kind
  counterparty: string | null
  peer_user_id: number | null
  peer_name: string | null
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
  income: { total: number; by_category: { name: string; amount: number }[] }
  /** money moved inside the family: neither spent nor earned */
  transfers_total: number
}

export interface MonthRow {
  month: string
  total: number
  income: number
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
  kind: 'expense' | 'income'
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
  text_models: string[]
  strong_models: string[]
  audio_models: string[]
  ask_models: string[]
  email_enabled: boolean
  email_address: string | null
  warranty_remind_days: number
}

export interface Product {
  key: string
  name: string | null
  name_original: string
  variants: number
  count: number
  min_price: number | null
  max_price: number | null
  last_date: string | null
}

export interface Warranty {
  item_id: number
  name: string
  name_original: string
  total: number
  warranty_until: string
  days_left: number
  receipt_id: number
  store: string | null
  purchased_at: string | null
  has_image: boolean
}

export interface StatementTx {
  external_id: string
  date: string | null
  amount: number
  merchant: string | null
  card: string | null
  owner_id: number | null
  type: string | null
  counterparty: string | null
  /** null: a move between own accounts, not booked by default */
  kind: Kind | null
  peer_id: number | null
  match: { id: number; title: string; purchased_at: string | null; total: number | null; source: string } | null
  imported: boolean
}

export interface BankImportInfo {
  import_id: string
  created_at: string | null
  count: number
  total: number
  date_from: string | null
  date_to: string | null
  from_bot: boolean
}

export interface AskResult {
  answer: string
  model: string
  tools: string[]
}

export interface ProviderBalance {
  provider: string
  currency?: string
  url: string
  balance?: number
  total_credits?: number
  error?: string
  key?: {
    limit: number | null
    limit_remaining: number | null
    limit_reset: string | null
    usage_daily: number | null
    usage_monthly: number | null
    byok_usage_monthly: number | null
    is_free_tier: boolean | null
    free_requests_remaining: number | null
  }
}

export interface UsageRow {
  calls: number
  failed: number
  /** USD charged to the OpenRouter balance */
  cost: number
  /** USD charged to own provider keys (BYOK) */
  byok_cost: number
  byok_calls: number
}

export interface LLMUsage {
  days: number
  total: UsageRow
  by_task: (UsageRow & { task: string; label: string })[]
  by_model: (UsageRow & { model: string; provider: string | null })[]
  by_day: (UsageRow & { day: string })[]
}

export interface MailStatus {
  enabled: boolean
  address: string | null
  host: string | null
  poll_minutes: number
  checked_at: string | null
  /** null: not checked since the start */
  ok: boolean | null
  error: string | null
  hint: string | null
  /** receipts booked from mail since the start */
  received: number
}
