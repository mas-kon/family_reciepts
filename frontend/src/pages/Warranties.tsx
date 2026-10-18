import { Alert, Anchor, Badge, Group, Loader, Stack, Switch, Table, Text, Title } from '@mantine/core'
import { IconPhoto } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, qs, type Warranty } from '../api'
import { dateOnly, money } from '../format'
import { useMeta } from '../hooks'

function DaysLeft({ days }: { days: number }) {
  const { t } = useTranslation()
  if (days < 0) return <Badge color="gray" variant="light">{t('warranty.expired')}</Badge>
  if (days <= 30) return <Badge color="red" variant="light">{t('warranty.days_left', { days })}</Badge>
  if (days <= 90) return <Badge color="yellow" variant="light">{t('warranty.days_left', { days })}</Badge>
  return <Badge color="teal" variant="light">{t('warranty.months_left', { months: Math.round(days / 30) })}</Badge>
}

export default function Warranties() {
  const { t } = useTranslation()
  const meta = useMeta()
  const [expired, setExpired] = useState(false)
  const list = useQuery({
    queryKey: ['warranties', expired],
    queryFn: () => api<Warranty[]>(`/warranties${qs({ expired })}`),
  })

  return (
    <Stack>
      <Title order={2}>{t('warranty.title')}</Title>
      <Text size="sm" c="dimmed">
        {t('warranty.hint', { days: meta.data?.warranty_remind_days ?? 30 })}
      </Text>
      <Switch label={t('warranty.show_expired')} checked={expired} onChange={(e) => setExpired(e.currentTarget.checked)} />
      {list.isError ? (
        <Alert color="red" title={t('warranty.load_failed')}>
          {(list.error as Error).message}
        </Alert>
      ) : list.isLoading ? (
        <Loader />
      ) : !list.data?.length ? (
        <Text c="dimmed">{t('warranty.none')}</Text>
      ) : (
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="xs" fz="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('warranty.col_item')}</Table.Th>
                <Table.Th>{t('warranty.col_bought')}</Table.Th>
                <Table.Th className="num">{t('warranty.col_price')}</Table.Th>
                <Table.Th>{t('warranty.col_until')}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {list.data.map((w) => (
                <Table.Tr key={w.item_id}>
                  <Table.Td>
                    <Anchor component={Link} to={`/receipts/${w.receipt_id}`} size="sm">
                      {w.name}
                    </Anchor>
                    {w.name !== w.name_original && (
                      <Text size="xs" c="dimmed">
                        {w.name_original}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      {w.has_image && <IconPhoto size={14} opacity={0.5} aria-label={t('warranty.has_photo')} />}
                      {dateOnly(w.purchased_at)}
                      {w.store && <Text span size="sm" c="dimmed">{w.store}</Text>}
                    </Group>
                  </Table.Td>
                  <Table.Td className="num">{money(w.total)}</Table.Td>
                  <Table.Td>{dateOnly(w.warranty_until)}</Table.Td>
                  <Table.Td>
                    <DaysLeft days={w.days_left} />
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
