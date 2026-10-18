import { notifications } from '@mantine/notifications'
import { useQuery, type QueryClient } from '@tanstack/react-query'
import { api, type Category, type Meta, type User } from './api'

export const useCategories = () =>
  useQuery({ queryKey: ['categories'], queryFn: () => api<Category[]>('/categories'), staleTime: 300_000 })

export const useUsers = () =>
  useQuery({ queryKey: ['users'], queryFn: () => api<User[]>('/users'), staleTime: 300_000 })

export const useMeta = () =>
  useQuery({ queryKey: ['meta'], queryFn: () => api<Meta>('/meta'), staleTime: 300_000 })

export function notifyError(e: unknown) {
  notifications.show({ color: 'red', title: 'Ошибка', message: (e as Error).message })
}

export function notifyOk(message: string) {
  notifications.show({ color: 'teal', message })
}

/** Everything that is computed from records: lists, details, statistics, budgets, prices, warranties.
 * Users, categories and settings are not refetched. */
export function invalidateRecords(qc: QueryClient) {
  for (const key of ['receipts', 'receipt', 'summary', 'monthly', 'budgets', 'products', 'prices', 'warranties', 'bank-imports']) {
    qc.invalidateQueries({ queryKey: [key] })
  }
}
