import { Button, Card, Group, Stack, Text, TextInput, Title } from '@mantine/core'
import { useMutation } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { api, qs } from '../../api'
import { notifyError, notifyOk, useMeta } from '../../hooks'

export default function Other() {
  const meta = useMeta()
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
        <Title order={5} mb="xs">
          Чеки по почте
        </Title>
        <Text size="sm">
          {meta.data?.email_enabled
            ? `Включено. Пересылайте электронные чеки на ${meta.data.email_address}: бот проверяет ящик и пишет о каждом чеке в группу.`
            : 'Выключено. Чтобы включить, задайте IMAP_HOST, IMAP_USER и IMAP_PASSWORD в .env.'}
        </Text>
      </Card>
    </Stack>
  )
}
