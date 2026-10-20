import type { components } from './api-schema'

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
// Generated from the backend (`npm run gen:api`); the names below are the ones the pages use.

type S = components['schemas']

export type Category = S['CategoryOut']
export type Kind = S['Kind']
export type User = S['UserOut']
export type Item = S['ItemOut']
export type Receipt = S['ReceiptOut']
export type ReceiptStatus = Receipt['status']
export type ReceiptDetail = S['ReceiptDetail']
export type UploadResult = S['UploadOut']
export type Summary = S['SummaryOut']
export type MonthRow = S['MonthRow']
export type BudgetRow = S['BudgetRow']
export type Recurring = S['RecurringOut']
export type PricePoint = S['PricePoint']
export type Meta = S['MetaOut']
export type Product = S['ProductOut']
export type Warranty = S['WarrantyOut']
export type StatementTx = S['StatementRowOut']
export type BankImportInfo = S['ImportInfo']
export type AskResult = S['AskOut']
export type ProviderBalance = S['ProviderBalance']
export type UsageRow = S['UsageRow']
export type LLMUsage = S['UsageOut']
export type MailStatus = S['MailStatus']
