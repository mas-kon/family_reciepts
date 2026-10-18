import { ActionIcon, Button, Code, Group, Select, Stack, Table, TagsInput, Text, TextInput } from '@mantine/core'
import { IconPencil, IconTrash } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { api } from '../../api'
import { isLanguage, setLanguage } from '../../i18n'
import { notifyError, notifyOk, useUsers, invalidateRecords } from '../../hooks'

/** Several values of one person (cards, e-mails, names in the bank): stored comma-separated,
 * edited as tags. Enter or a comma adds a value. */
function ListInput({
  value,
  onSave,
  label,
  placeholder,
  w,
  allowSpace = false,
}: {
  value: string
  onSave: (v: string) => void
  label: string
  placeholder: string
  w: number
  /** a space is part of a value (a name), not a separator */
  allowSpace?: boolean
}) {
  const tags = value ? value.split(',').filter(Boolean) : []
  return (
    <TagsInput
      size="xs"
      w={w}
      aria-label={label}
      placeholder={tags.length ? undefined : placeholder}
      value={tags}
      onChange={(v) => v.join(',') !== value && onSave(v.join(','))}
      splitChars={allowSpace ? [',', ';'] : [',', ';', ' ']}
      acceptValueOnBlur
      clearable={false}
    />
  )
}

/** The family's language: one for the bot, the web app, reports and the AI's answers. */
function LanguagePicker() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const lang = useQuery({
    queryKey: ['language'],
    queryFn: () => api<{ language: string; options: { code: string; name: string }[] }>('/settings/language'),
  })
  const change = useMutation({
    mutationFn: (language: string) => api('/settings/language', { method: 'PUT', json: { language } }),
    onSuccess: async (_, language) => {
      if (isLanguage(language)) await setLanguage(language)
      // standard categories were renamed, and some stored texts depend on the language
      await qc.invalidateQueries()
    },
    onError: notifyError,
  })
  return (
    <Group align="flex-end">
      <Select
        label={t('family.language')}
        description={t('family.language_hint')}
        w={420}
        allowDeselect={false}
        value={lang.data?.language ?? null}
        data={(lang.data?.options ?? []).map((o) => ({ value: o.code, label: o.name }))}
        onChange={(v) => v && change.mutate(v)}
        disabled={!lang.data || change.isPending}
      />
    </Group>
  )
}

export default function Family() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const users = useUsers()
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['users'] })

  const create = useMutation({
    mutationFn: () => api('/users', { method: 'POST', json: { name } }),
    onSuccess: () => {
      setName('')
      refresh()
    },
    onError: notifyError,
  })
  const save = useMutation({
    mutationFn: ({ id, ...fields }: { id: number; name?: string; cards?: string; emails?: string; bank_names?: string }) =>
      api<{ marked_transfers: number }>(`/users/${id}`, { method: 'PATCH', json: fields }),
    onSuccess: (r) => {
      setEditing(null)
      refresh()
      if (r.marked_transfers) {
        notifyOk(t('family.marked', { count: r.marked_transfers }))
        invalidateRecords(qc)
      } else {
        qc.invalidateQueries({ queryKey: ['receipts'] })
      }
    },
    onError: notifyError,
  })
  const del = useMutation({
    mutationFn: (id: number) => api(`/users/${id}`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: notifyError,
  })

  return (
    <Stack>
      <LanguagePicker />
      <Text size="sm" c="dimmed">
        <Trans i18nKey="family.hint1" components={{ code: <Code /> }} />
      </Text>
      <Text size="sm" c="dimmed">
        <Trans i18nKey="family.hint2" components={{ b: <b /> }} />
      </Text>
      <Text size="sm" c="dimmed">
        <Trans i18nKey="family.hint3" components={{ b: <b />, code: <Code /> }} />
      </Text>
      <Group align="flex-end">
        <TextInput
          label={t('family.new_member')}
          placeholder={t('family.new_member_placeholder')}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && name && create.mutate()}
          w={240}
        />
        <Button onClick={() => create.mutate()} disabled={!name} loading={create.isPending}>
          {t('common.add')}
        </Button>
      </Group>
      <Table.ScrollContainer minWidth={900}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('family.col_name')}</Table.Th>
            <Table.Th>Telegram</Table.Th>
            <Table.Th>{t('family.col_cards')}</Table.Th>
            <Table.Th>{t('family.col_mail')}</Table.Th>
            <Table.Th>{t('family.col_bank_name')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {users.data?.map((u) => (
            <Table.Tr key={u.id}>
              <Table.Td>
                {editing?.id === u.id ? (
                  <TextInput
                    size="xs"
                    value={editing.name}
                    onChange={(e) => setEditing({ ...editing, name: e.currentTarget.value })}
                    onKeyDown={(e) => e.key === 'Enter' && save.mutate(editing)}
                    onBlur={() => save.mutate(editing)}
                    autoFocus
                  />
                ) : (
                  u.name
                )}
              </Table.Td>
              <Table.Td c="dimmed">{u.has_telegram ? (u.username ? `@${u.username}` : t('family.has_telegram')) : t('family.no_telegram')}</Table.Td>
              <Table.Td>
                <ListInput
                  w={150}
                  label={t('family.col_cards')}
                  placeholder="1234"
                  value={u.cards}
                  onSave={(v) => save.mutate({ id: u.id, cards: v })}
                />
              </Table.Td>
              <Table.Td>
                <ListInput
                  w={260}
                  label={t('family.col_mail')}
                  placeholder="name@example.com"
                  value={u.emails}
                  onSave={(v) => save.mutate({ id: u.id, emails: v })}
                />
              </Table.Td>
              <Table.Td>
                <ListInput
                  w={240}
                  label={t('family.col_bank_name')}
                  allowSpace
                  placeholder="Vera Maslennikova"
                  value={u.bank_names}
                  onSave={(v) => save.mutate({ id: u.id, bank_names: v })}
                />
              </Table.Td>
              <Table.Td w={90}>
                <Group gap={2} wrap="nowrap">
                  <ActionIcon variant="subtle" size="sm" aria-label={t('categories.rename')} onClick={() => setEditing({ id: u.id, name: u.name })}>
                    <IconPencil size={14} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" size="sm" color="red" aria-label={t('common.delete')} onClick={() => confirm(t('family.delete_confirm', { name: u.name })) && del.mutate(u.id)}>
                    <IconTrash size={14} />
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      </Table.ScrollContainer>
    </Stack>
  )
}
