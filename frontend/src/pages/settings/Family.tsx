import { ActionIcon, Button, Code, Group, Stack, Table, TagsInput, Text, TextInput } from '@mantine/core'
import { IconPencil, IconTrash } from '@tabler/icons-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
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

export default function Family() {
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
        notifyOk(`Переводов внутри семьи найдено: ${r.marked_transfers}. Из расходов они убраны.`)
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
      <Text size="sm" c="dimmed">
        Участники группы появляются здесь сами после первого сообщения боту. Ребёнка или другого члена семьи без
        Telegram добавьте вручную. Тогда в группе можно записать трату на него: <Code>+ Маша: кино 12</Code>.
        Имя в боте пишется так же, как здесь, достаточно первого слова.
      </Text>
      <Text size="sm" c="dimmed">
        В полях ниже можно указать несколько значений: введите и нажмите Enter или запятую. <b>Карты</b>: последние 4
        цифры. Уведомление банка и строка выписки с этой картой запишутся на
        этого человека. <b>Почта</b>: все адреса, с которых человек пересылает электронные чеки.
      </Text>
      <Text size="sm" c="dimmed">
        <b>Имя в банке</b>: как банк пишет этого человека в переводах, например <Code>Vera Maslennikova</Code>. Переводы
        ему и от него считаются переводами внутри семьи и не входят ни в расходы, ни в доходы. Иначе карманные деньги
        ребёнку посчитались бы дважды: при переводе и когда он их потратит. Прошлые переводы тоже пересчитаются.
      </Text>
      <Group align="flex-end">
        <TextInput
          label="Новый член семьи"
          placeholder="Маша"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && name && create.mutate()}
          w={240}
        />
        <Button onClick={() => create.mutate()} disabled={!name} loading={create.isPending}>
          Добавить
        </Button>
      </Group>
      <Table.ScrollContainer minWidth={900}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Имя</Table.Th>
            <Table.Th>Telegram</Table.Th>
            <Table.Th>Карты</Table.Th>
            <Table.Th>Почта</Table.Th>
            <Table.Th>Имя в банке</Table.Th>
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
              <Table.Td c="dimmed">{u.has_telegram ? (u.username ? `@${u.username}` : 'есть') : 'нет'}</Table.Td>
              <Table.Td>
                <ListInput
                  w={150}
                  label="Карты"
                  placeholder="1234"
                  value={u.cards}
                  onSave={(v) => save.mutate({ id: u.id, cards: v })}
                />
              </Table.Td>
              <Table.Td>
                <ListInput
                  w={260}
                  label="Почта"
                  placeholder="name@example.com"
                  value={u.emails}
                  onSave={(v) => save.mutate({ id: u.id, emails: v })}
                />
              </Table.Td>
              <Table.Td>
                <ListInput
                  w={240}
                  label="Имя в банке"
                  allowSpace
                  placeholder="Vera Maslennikova"
                  value={u.bank_names}
                  onSave={(v) => save.mutate({ id: u.id, bank_names: v })}
                />
              </Table.Td>
              <Table.Td w={90}>
                <Group gap={2} wrap="nowrap">
                  <ActionIcon variant="subtle" size="sm" aria-label="Переименовать" onClick={() => setEditing({ id: u.id, name: u.name })}>
                    <IconPencil size={14} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" size="sm" color="red" aria-label="Удалить" onClick={() => confirm(`Удалить «${u.name}»?`) && del.mutate(u.id)}>
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
