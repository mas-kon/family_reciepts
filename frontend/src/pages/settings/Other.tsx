import { Alert, Badge, Button, Card, Code, Group, Stack, Text, TextInput, Title } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { api, qs, type MailStatus } from '../../api'
import { dateTime } from '../../format'
import { notifyError, notifyOk } from '../../hooks'

export default function Other() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const mail = useQuery({ queryKey: ['mail-status'], queryFn: () => api<MailStatus>('/mail/status'), refetchInterval: 60_000 })
  const check = useMutation({
    mutationFn: () => api<MailStatus>('/mail/check', { method: 'POST' }),
    onSuccess: (r) => {
      qc.setQueryData(['mail-status'], r)
      if (r.ok) notifyOk(t('other.mail_ok'))
    },
    onError: notifyError,
  })
  const [month, setMonth] = useState(dayjs().subtract(1, 'month').format('YYYY-MM'))
  const send = useMutation({
    mutationFn: () => api(`/reports/send${qs({ month })}`, { method: 'POST' }),
    onSuccess: () => notifyOk(t('other.report_sent')),
    onError: notifyError,
  })
  return (
    <Stack>
      <Card withBorder>
        <Title order={5} mb="xs">
          {t('other.report_title')}
        </Title>
        <Text size="sm" c="dimmed" mb="sm">
          {t('other.report_hint')}
        </Text>
        <Group align="flex-end">
          <TextInput type="month" label={t('other.month')} value={month} onChange={(e) => setMonth(e.currentTarget.value)} />
          <Button onClick={() => send.mutate()} loading={send.isPending}>
            {t('other.send')}
          </Button>
        </Group>
      </Card>
      <Card withBorder>
        <Group justify="space-between" mb="xs">
          <Title order={5}>{t('other.mail_title')}</Title>
          {mail.data?.enabled && (
            <Badge
              variant="light"
              color={mail.data.ok === null ? 'gray' : mail.data.ok ? 'teal' : 'red'}
            >
              {mail.data.ok === null ? t('other.mail_unchecked') : mail.data.ok ? t('other.mail_connected') : t('other.mail_error')}
            </Badge>
          )}
        </Group>
        {mail.data?.enabled ? (
          <Stack gap="xs">
            <Text size="sm">
              <Trans
                i18nKey="other.mail_text"
                values={{ address: mail.data.address, host: mail.data.host, minutes: mail.data.poll_minutes }}
                components={{ code: <Code /> }}
              />
            </Text>
            {mail.data.checked_at && (
              <Text size="xs" c="dimmed">
                {t('other.mail_checked', { when: dateTime(mail.data.checked_at), count: mail.data.received })}
              </Text>
            )}
            {mail.data.error && (
              <Alert color="red" title={t('other.mail_failed')}>
                <Text size="sm">{mail.data.error}</Text>
                {mail.data.hint && <Text size="sm">{mail.data.hint}</Text>}
              </Alert>
            )}
            <Group>
              <Button size="xs" variant="default" onClick={() => check.mutate()} loading={check.isPending}>
                {t('other.mail_check')}
              </Button>
            </Group>
          </Stack>
        ) : (
          <Text size="sm">{t('other.mail_disabled')}</Text>
        )}
      </Card>
    </Stack>
  )
}
