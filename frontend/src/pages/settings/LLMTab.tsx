import { Card, Code, Stack, Table, Text, Title } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import { LLMPanel } from '../../components/LLMPanel'
import { useMeta } from '../../hooks'

export default function LLMTab() {
  const { t } = useTranslation()
  const meta = useMeta()
  return (
    <Stack>
      <LLMPanel />
      <Card withBorder>
        <Title order={5} mb="xs">
          {t('llm.title')}
        </Title>
        <Text size="sm" mb={4}>
          {t('llm.provider')}<Code>{meta.data?.llm_base_url}</Code>
        </Text>
        <Text size="sm" mb="xs">
          {t('llm.order')}
        </Text>
        <Table fz="sm" withRowBorders={false}>
          <Table.Tbody>
            {[
              [t('llm.task_photo'), 'LLM_MODELS', meta.data?.models],
              [t('llm.task_strong'), 'LLM_STRONG_MODELS', meta.data?.strong_models],
              [t('llm.task_text'), 'LLM_TEXT_MODELS', meta.data?.text_models],
              [t('llm.task_audio'), 'LLM_AUDIO_MODELS', meta.data?.audio_models],
              [t('llm.task_ask'), 'LLM_ASK_MODELS', meta.data?.ask_models],
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
                    <Text size="sm" c="dimmed">{t('llm.off')}</Text>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="xs" c="dimmed" mt="sm">
          {t('llm.env_hint')}
        </Text>
      </Card>
    </Stack>
  )
}
