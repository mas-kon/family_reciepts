import { Card, Code, Stack, Table, Text, Title } from '@mantine/core'
import { LLMPanel } from '../../components/LLMPanel'
import { useMeta } from '../../hooks'

export default function LLMTab() {
  const meta = useMeta()
  return (
    <Stack>
      <LLMPanel />
      <Card withBorder>
        <Title order={5} mb="xs">
          Нейросеть
        </Title>
        <Text size="sm" mb={4}>
          Провайдер: <Code>{meta.data?.llm_base_url}</Code>
        </Text>
        <Text size="sm" mb="xs">
          В каждом списке модели идут по порядку: следующая используется, если предыдущая не ответила.
        </Text>
        <Table fz="sm" withRowBorders={false}>
          <Table.Tbody>
            {[
              ['Чеки по фото', 'LLM_MODELS', meta.data?.models],
              ['Перечитать чек, если суммы не сошлись', 'LLM_STRONG_MODELS', meta.data?.strong_models],
              ['Текст: траты, банк, отчёт, товары', 'LLM_TEXT_MODELS', meta.data?.text_models],
              ['Голосовые сообщения', 'LLM_AUDIO_MODELS', meta.data?.audio_models],
              ['Вопросы', 'LLM_ASK_MODELS', meta.data?.ask_models],
            ].map(([label, env, list]) => (
              <Table.Tr key={env as string}>
                <Table.Td valign="top" w={260}>
                  {label as string}
                  <Text size="xs" c="dimmed">{env as string}</Text>
                </Table.Td>
                <Table.Td>
                  {(list as string[] | undefined)?.length ? (
                    <Stack gap={2}>
                      {(list as string[]).map((m) => (
                        <Code key={m}>{m}</Code>
                      ))}
                    </Stack>
                  ) : (
                    <Text size="sm" c="dimmed">выключено</Text>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="xs" c="dimmed" mt="sm">
          Меняется в файле .env, затем перезапуск сервиса.
        </Text>
      </Card>
    </Stack>
  )
}
