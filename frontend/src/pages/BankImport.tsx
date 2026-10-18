import { Alert, Anchor, Badge, Button, Checkbox, FileButton, Group, Select, Stack, Table, Text, Title } from '@mantine/core'
import { IconUpload } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, type BankImportInfo, type StatementTx } from '../api'
import { DeleteImportButton } from '../components/DeleteImportButton'
import { dateOnly, dateTime, money } from '../format'
import { notifyError, notifyOk, useUsers, invalidateRecords } from '../hooks'

interface Row extends StatementTx {
  selected: boolean
  /** "expense", "income" or "transfer:<member id>" */
  choice: string
}

const OUTGOING = new Set(['purchase', 'transfer_out'])

function initialChoice(tx: StatementTx): string {
  if (tx.kind === 'transfer') return tx.peer_id ? `transfer:${tx.peer_id}` : 'expense'
  if (tx.kind) return tx.kind
  return OUTGOING.has(tx.type ?? '') ? 'expense' : 'income'
}

export default function BankImport() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const users = useUsers()
  const [rows, setRows] = useState<Row[] | null>(null)
  const [fileName, setFileName] = useState('')
  const imports = useQuery({ queryKey: ['bank-imports'], queryFn: () => api<BankImportInfo[]>('/bank/imports') })

  const analyse = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return api<{ transactions: StatementTx[] }>('/bank/statement', { method: 'POST', body: fd })
    },
    // by default everything not recorded yet is selected, except moves between own accounts
    onSuccess: (r) =>
      setRows(
        r.transactions.map((tx) => ({ ...tx, choice: initialChoice(tx), selected: !tx.match && !tx.imported && tx.kind !== null })),
      ),
    onError: notifyError,
  })

  const importRows = useMutation({
    mutationFn: () =>
      api<{ booked: number; skipped: number; marked_transfers: number }>('/bank/import', {
        method: 'POST',
        json: {
          transactions: (rows ?? [])
            .filter((r) => r.selected)
            .map(({ external_id, date, amount, merchant, card, owner_id, type, counterparty, choice }) => ({
              external_id, date, amount, merchant, card, owner_id, type, counterparty,
              kind: choice.startsWith('transfer:') ? 'transfer' : choice,
              peer_id: choice.startsWith('transfer:') ? Number(choice.split(':')[1]) : null,
            })),
        },
      }),
    onSuccess: (r) => {
      notifyOk(
        t('bank.booked', { booked: r.booked }) +
          (r.skipped ? t('bank.skipped', { skipped: r.skipped }) : '') +
          (r.marked_transfers ? t('bank.marked', { count: r.marked_transfers }) : ''),
      )
      invalidateRecords(qc)
      setRows((rs) => rs?.map((x) => (x.selected ? { ...x, selected: false, imported: true } : x)) ?? null)
    },
    onError: notifyError,
  })

  const update = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs?.map((r, j) => (j === i ? { ...r, ...patch } : r)) ?? null)

  const selected = rows?.filter((r) => r.selected) ?? []
  const missing = rows?.filter((r) => !r.match && !r.imported && r.kind !== null).length ?? 0
  const typeOptions = [
    { value: 'expense', label: t('kind.expense') },
    { value: 'income', label: t('kind.income') },
    ...(users.data ?? []).map((u) => ({ value: `transfer:${u.id}`, label: t('bank.family_option', { name: u.name }) })),
  ]

  return (
    <Stack>
      <Title order={2}>{t('bank.title')}</Title>
      <Text size="sm" c="dimmed">
        {t('bank.hint1')}
      </Text>
      <Text size="sm" c="dimmed">
        {t('bank.hint2')}
      </Text>

      <Group>
        <FileButton onChange={(f) => f && (setFileName(f.name), analyse.mutate(f))} accept=".csv,.txt,.pdf,text/csv,application/pdf">
          {(props) => (
            <Button {...props} leftSection={<IconUpload size={16} />} loading={analyse.isPending}>
              {t('bank.upload')}
            </Button>
          )}
        </FileButton>
        {fileName && <Text size="sm" c="dimmed">{fileName}</Text>}
      </Group>
      {analyse.isPending && <Text size="sm" c="dimmed">{t('bank.reading')}</Text>}

      {rows && rows.length === 0 && <Alert color="gray">{t('bank.no_debits')}</Alert>}
      {rows && rows.length > 0 && (
        <>
          <Text size="sm">
            <Trans i18nKey="bank.summary" values={{ count: rows.length, missing }} components={{ b: <b /> }} />
          </Text>
          <Table.ScrollContainer minWidth={920}>
            <Table verticalSpacing="xs" fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th w={36} />
                  <Table.Th>{t('bank.col_date')}</Table.Th>
                  <Table.Th>{t('bank.col_where')}</Table.Th>
                  <Table.Th className="num">{t('bank.col_amount')}</Table.Th>
                  <Table.Th>{t('bank.col_type')}</Table.Th>
                  <Table.Th>{t('bank.col_who')}</Table.Th>
                  <Table.Th>{t('bank.col_recorded')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((r, i) => (
                  <Table.Tr key={r.external_id + i} opacity={r.imported ? 0.5 : 1}>
                    <Table.Td>
                      <Checkbox
                        aria-label={t('bank.record')}
                        checked={r.selected}
                        disabled={r.imported}
                        onChange={(e) => update(i, { selected: e.currentTarget.checked })}
                      />
                    </Table.Td>
                    <Table.Td>{dateOnly(r.date)}</Table.Td>
                    <Table.Td>
                      {r.merchant ?? '—'}
                      {r.card && (
                        <Text span size="xs" c="dimmed">
                          {' '}
                          *{r.card}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td className="num" c={r.choice === 'income' ? 'teal' : undefined}>
                      {r.choice === 'income' ? `+${money(r.amount)}` : money(r.amount)}
                    </Table.Td>
                    <Table.Td>
                      <Select
                        size="xs"
                        w={150}
                        value={r.choice}
                        onChange={(v) => v && update(i, { choice: v })}
                        data={typeOptions}
                        allowDeselect={false}
                        disabled={r.imported}
                        aria-label={t('bank.col_type')}
                      />
                      {r.kind === null && (
                        <Text size="xs" c="dimmed">
                          {t('bank.own_accounts')}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Select
                        size="xs"
                        w={140}
                        placeholder={t('bank.me')}
                        clearable
                        value={r.owner_id ? String(r.owner_id) : null}
                        onChange={(v) => update(i, { owner_id: v ? Number(v) : null })}
                        data={(users.data ?? []).map((u) => ({ value: String(u.id), label: u.name }))}
                        disabled={r.imported}
                      />
                    </Table.Td>
                    <Table.Td>
                      {r.imported ? (
                        <Badge color="gray" variant="light">
                          {t('bank.imported_before')}
                        </Badge>
                      ) : r.match ? (
                        <Anchor component={Link} to={`/receipts/${r.match.id}`} size="sm">
                          {r.match.title}, {dateOnly(r.match.purchased_at)}
                        </Anchor>
                      ) : (
                        <Badge color="yellow" variant="light">
                          {t('bank.no_record')}
                        </Badge>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Group>
            <Button onClick={() => importRows.mutate()} disabled={!selected.length} loading={importRows.isPending}>
              {t('bank.record_selected', { count: selected.length })}
            </Button>
          </Group>
        </>
      )}

      <Title order={3} mt="lg">
        {t('bank.uploaded')}
      </Title>
      {!imports.data?.length ? (
        <Text size="sm" c="dimmed">
          {t('bank.none_yet')}
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="xs" fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('bank.col_uploaded')}</Table.Th>
                <Table.Th>{t('bank.col_period')}</Table.Th>
                <Table.Th className="num">{t('bank.col_records')}</Table.Th>
                <Table.Th className="num">{t('bank.col_total')}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {imports.data.map((i) => (
                <Table.Tr key={i.import_id}>
                  <Table.Td>
                    {dateTime(i.created_at)}
                    <Text span size="xs" c="dimmed">
                      {' '}
                      {i.from_bot ? t('bank.via_bot') : t('bank.via_web')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {dateOnly(i.date_from)}
                    {i.date_to && dateOnly(i.date_to) !== dateOnly(i.date_from) && ` — ${dateOnly(i.date_to)}`}
                  </Table.Td>
                  <Table.Td className="num">
                    <Anchor component={Link} to={`/receipts?import_id=${encodeURIComponent(i.import_id)}`} size="sm">
                      {i.count}
                    </Anchor>
                  </Table.Td>
                  <Table.Td className="num">{money(i.total)}</Table.Td>
                  <Table.Td>
                    <DeleteImportButton importId={i.import_id} count={i.count} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}
