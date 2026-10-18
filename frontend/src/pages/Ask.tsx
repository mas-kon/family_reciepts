import { ActionIcon, Badge, Card, Group, Loader, Stack, Text, Textarea, Title } from '@mantine/core'
import { IconSend, IconTrash } from '@tabler/icons-react'
import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type AskResult } from '../api'
import { notifyError } from '../hooks'

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

const EXAMPLES = ['ask.example1', 'ask.example2', 'ask.example3', 'ask.example4']

const STORAGE_KEY = 'ask-history'

function loadHistory(): Msg[] {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '[]') as Msg[]
  } catch {
    return []
  }
}

export default function Ask() {
  const { t } = useTranslation()
  const [messages, setMessages] = useState<Msg[]>(loadHistory)
  const [input, setInput] = useState('')
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-20)))
    } catch {
      /* storage unavailable */
    }
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const ask = useMutation({
    mutationFn: (question: string) =>
      api<AskResult>('/ask', { method: 'POST', json: { question, history: messages.slice(-6) } }),
    onSuccess: (r) => setMessages((m) => [...m, { role: 'assistant', content: r.answer }]),
    onError: (e) => {
      setMessages((m) => m.slice(0, -1))
      notifyError(e)
    },
  })

  const send = (q: string) => {
    const question = q.trim()
    if (!question || ask.isPending) return
    setMessages((m) => [...m, { role: 'user', content: question }])
    setInput('')
    ask.mutate(question)
  }

  return (
    <Stack maw={800}>
      <Group justify="space-between">
        <Title order={2}>{t('ask.title')}</Title>
        {messages.length > 0 && (
          <ActionIcon variant="subtle" aria-label={t('ask.clear')} onClick={() => setMessages([])}>
            <IconTrash size={18} />
          </ActionIcon>
        )}
      </Group>
      <Text size="sm" c="dimmed">
        {t('ask.hint')}
      </Text>

      {messages.length === 0 && (
        <Group gap="xs">
          {EXAMPLES.map((key) => (
            <Badge key={key} variant="light" size="lg" style={{ cursor: 'pointer', textTransform: 'none' }} onClick={() => send(t(key))}>
              {t(key)}
            </Badge>
          ))}
        </Group>
      )}

      <Stack gap="sm">
        {messages.map((m, i) => (
          <Card
            key={i}
            withBorder
            padding="sm"
            ml={m.role === 'user' ? 'auto' : 0}
            maw="85%"
            bg={m.role === 'user' ? 'var(--mantine-color-blue-light)' : undefined}
          >
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
              {m.content}
            </Text>
          </Card>
        ))}
        {ask.isPending && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              {t('ask.counting')}
            </Text>
          </Group>
        )}
        <div ref={bottom} />
      </Stack>

      <Group align="flex-end" gap="xs" wrap="nowrap">
        <Textarea
          style={{ flex: 1 }}
          placeholder={t('ask.placeholder')}
          autosize
          minRows={1}
          maxRows={5}
          value={input}
          onChange={(e) => setInput(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
        />
        <ActionIcon size="lg" aria-label={t('ask.send')} onClick={() => send(input)} loading={ask.isPending} disabled={!input.trim()}>
          <IconSend size={18} />
        </ActionIcon>
      </Group>
    </Stack>
  )
}
