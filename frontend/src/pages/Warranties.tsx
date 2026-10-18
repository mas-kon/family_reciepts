import { Anchor, Badge, Group, Loader, Stack, Switch, Table, Text, Title } from '@mantine/core'
import { IconPhoto } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs, type Warranty } from '../api'
import { dateOnly, money } from '../format'
import { useMeta } from '../hooks'

function DaysLeft({ days }: { days: number }) {
  if (days < 0) return <Badge color="gray" variant="light">закончилась</Badge>
  if (days <= 30) return <Badge color="red" variant="light">осталось {days} дн.</Badge>
  if (days <= 90) return <Badge color="yellow" variant="light">осталось {days} дн.</Badge>
  return <Badge color="teal" variant="light">ещё {Math.round(days / 30)} мес.</Badge>
}

export default function Warranties() {
  const meta = useMeta()
  const [expired, setExpired] = useState(false)
  const list = useQuery({
    queryKey: ['warranties', expired],
    queryFn: () => api<Warranty[]>(`/warranties${qs({ expired })}`),
  })

  return (
    <Stack>
      <Title order={2}>Гарантии</Title>
      <Text size="sm" c="dimmed">
        Нейросеть отмечает гарантию у техники и бытовых приборов: срок с чека, а если его нет, 24 месяца для вещей
        дороже 30 €. За {meta.data?.warranty_remind_days ?? 30} дней до конца бот напомнит в группе. Срок можно
        поправить в позиции чека.
      </Text>
      <Switch label="Показать закончившиеся" checked={expired} onChange={(e) => setExpired(e.currentTarget.checked)} />
      {list.isLoading ? (
        <Loader />
      ) : !list.data?.length ? (
        <Text c="dimmed">Вещей на гарантии пока нет.</Text>
      ) : (
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="xs" fz="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Вещь</Table.Th>
                <Table.Th>Куплено</Table.Th>
                <Table.Th className="num">Цена</Table.Th>
                <Table.Th>Гарантия до</Table.Th>
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
                      {w.has_image && <IconPhoto size={14} opacity={0.5} aria-label="Есть фото чека" />}
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
