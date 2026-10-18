import { ActionIcon, Button, Group, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { IconPencil, IconTrash } from '@tabler/icons-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Category } from '../../api'
import { notifyError, useCategories } from '../../hooks'

export default function Categories() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const cats = useCategories()
  const [name, setName] = useState('')
  const [parent, setParent] = useState<string | null>(null)
  const [editing, setEditing] = useState<Category | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['categories'] })

  const [incomeName, setIncomeName] = useState('')
  const create = useMutation({
    mutationFn: () => api('/categories', { method: 'POST', json: { name, parent_id: parent ? Number(parent) : null } }),
    onSuccess: () => {
      setName('')
      refresh()
    },
    onError: notifyError,
  })
  const createIncome = useMutation({
    mutationFn: () => api('/categories', { method: 'POST', json: { name: incomeName, kind: 'income' } }),
    onSuccess: () => {
      setIncomeName('')
      refresh()
    },
    onError: notifyError,
  })
  const rename = useMutation({
    mutationFn: (c: Category) => api(`/categories/${c.id}`, { method: 'PATCH', json: { name: c.name } }),
    onSuccess: () => {
      setEditing(null)
      refresh()
    },
    onError: notifyError,
  })
  const del = useMutation({
    mutationFn: (id: number) => api(`/categories/${id}`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: notifyError,
  })

  const all = (cats.data ?? []).filter((c) => c.kind !== 'income')
  const incomes = (cats.data ?? []).filter((c) => c.kind === 'income')
  const parents = all.filter((c) => !c.parent_id)

  const row = (c: Category, indent: boolean) => (
    <Table.Tr key={c.id}>
      <Table.Td pl={indent ? 'xl' : undefined} fw={indent ? 400 : 600}>
        {editing?.id === c.id ? (
          <TextInput
            size="xs"
            value={editing.name}
            onChange={(e) => setEditing({ ...editing, name: e.currentTarget.value })}
            onKeyDown={(e) => e.key === 'Enter' && rename.mutate(editing)}
            onBlur={() => rename.mutate(editing)}
            autoFocus
          />
        ) : (
          c.name
        )}
      </Table.Td>
      <Table.Td w={90}>
        <Group gap={2} wrap="nowrap">
          <ActionIcon variant="subtle" size="sm" aria-label={t('categories.rename')} onClick={() => setEditing(c)}>
            <IconPencil size={14} />
          </ActionIcon>
          <ActionIcon variant="subtle" size="sm" color="red" aria-label={t('common.delete')} onClick={() => confirm(t('categories.delete_confirm', { name: c.name })) && del.mutate(c.id)}>
            <IconTrash size={14} />
          </ActionIcon>
        </Group>
      </Table.Td>
    </Table.Tr>
  )

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {t('categories.hint')}
      </Text>
      <Group align="flex-end">
        <TextInput label={t('categories.new')} value={name} onChange={(e) => setName(e.currentTarget.value)} w={240} />
        <Select
          label={t('categories.inside')}
          placeholder={t('categories.top_level')}
          clearable
          w={220}
          value={parent}
          onChange={setParent}
          data={parents.map((p) => ({ value: String(p.id), label: p.name }))}
        />
        <Button onClick={() => create.mutate()} disabled={!name} loading={create.isPending}>
          {t('common.add')}
        </Button>
      </Group>
      <Table maw={520}>
        <Table.Tbody>
          {parents.flatMap((p) => [row(p, false), ...all.filter((c) => c.parent_id === p.id).map((c) => row(c, true))])}
        </Table.Tbody>
      </Table>

      <Title order={4} mt="md">
        {t('categories.income_title')}
      </Title>
      <Text size="sm" c="dimmed">
        {t('categories.income_hint')}
      </Text>
      <Group align="flex-end">
        <TextInput label={t('categories.new_income')} value={incomeName} onChange={(e) => setIncomeName(e.currentTarget.value)} w={240} />
        <Button onClick={() => createIncome.mutate()} disabled={!incomeName} loading={createIncome.isPending}>
          {t('common.add')}
        </Button>
      </Group>
      <Table maw={520}>
        <Table.Tbody>{incomes.map((c) => row(c, false))}</Table.Tbody>
      </Table>
    </Stack>
  )
}
