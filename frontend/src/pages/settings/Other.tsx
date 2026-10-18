import { Alert, Badge, Button, Card, Code, Group, Stack, Text, TextInput, Title } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { api, qs, type MailStatus } from '../../api'
import { dateTime } from '../../format'
import { notifyError, notifyOk } from '../../hooks'

export default function Other() {
  const qc = useQueryClient()
  const mail = useQuery({ queryKey: ['mail-status'], queryFn: () => api<MailStatus>('/mail/status'), refetchInterval: 60_000 })
  const check = useMutation({
    mutationFn: () => api<MailStatus>('/mail/check', { method: 'POST' }),
    onSuccess: (r) => {
      qc.setQueryData(['mail-status'], r)
      if (r.ok) notifyOk('Ящик читается')
    },
    onError: notifyError,
  })
  const [month, setMonth] = useState(dayjs().subtract(1, 'month').format('YYYY-MM'))
  const send = useMutation({
    mutationFn: () => api(`/reports/send${qs({ month })}`, { method: 'POST' }),
    onSuccess: () => notifyOk('Отчёт отправлен в группу'),
    onError: notifyError,
  })
  return (
    <Stack>
      <Card withBorder>
        <Title order={5} mb="xs">
          Месячный отчёт
        </Title>
        <Text size="sm" c="dimmed" mb="sm">
          Отправляется в группу автоматически 1-го числа в 9:00. Можно отправить вручную.
        </Text>
        <Group align="flex-end">
          <TextInput type="month" label="Месяц" value={month} onChange={(e) => setMonth(e.currentTarget.value)} />
          <Button onClick={() => send.mutate()} loading={send.isPending}>
            Отправить в группу
          </Button>
        </Group>
      </Card>
      <Card withBorder>
        <Group justify="space-between" mb="xs">
          <Title order={5}>Чеки по почте</Title>
          {mail.data?.enabled && (
            <Badge
              variant="light"
              color={mail.data.ok === null ? 'gray' : mail.data.ok ? 'teal' : 'red'}
            >
              {mail.data.ok === null ? 'ещё не проверялась' : mail.data.ok ? 'подключена' : 'ошибка'}
            </Badge>
          )}
        </Group>
        {mail.data?.enabled ? (
          <Stack gap="xs">
            <Text size="sm">
              Ящик <Code>{mail.data.address}</Code> на <Code>{mail.data.host}</Code>. Пересылайте на него электронные
              чеки: бот проверяет ящик раз в {mail.data.poll_minutes} мин. и пишет о каждом чеке в группу.
            </Text>
            {mail.data.checked_at && (
              <Text size="xs" c="dimmed">
                Последняя проверка: {dateTime(mail.data.checked_at)}. Чеков из почты с запуска: {mail.data.received}.
              </Text>
            )}
            {mail.data.error && (
              <Alert color="red" title="Не удалось прочитать ящик">
                <Text size="sm">{mail.data.error}</Text>
                {mail.data.hint && <Text size="sm">{mail.data.hint}</Text>}
              </Alert>
            )}
            <Group>
              <Button size="xs" variant="default" onClick={() => check.mutate()} loading={check.isPending}>
                Проверить подключение
              </Button>
            </Group>
          </Stack>
        ) : (
          <Text size="sm">Выключено. Чтобы включить, задайте IMAP_HOST, IMAP_USER и IMAP_PASSWORD в .env.</Text>
        )}
      </Card>
    </Stack>
  )
}
