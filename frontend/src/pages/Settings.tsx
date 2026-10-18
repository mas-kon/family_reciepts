import { Stack, Tabs, Title } from '@mantine/core'
import { useTranslation } from 'react-i18next'
import Budgets from './settings/Budgets'
import Categories from './settings/Categories'
import Family from './settings/Family'
import LLMTab from './settings/LLMTab'
import Other from './settings/Other'
import RecurringTab from './settings/RecurringTab'

export default function Settings() {
  const { t } = useTranslation()
  return (
    <Stack>
      <Title order={2}>{t('settings.title')}</Title>
      <Tabs defaultValue="family" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="family">{t('settings.tab_family')}</Tabs.Tab>
          <Tabs.Tab value="budgets">{t('settings.tab_budgets')}</Tabs.Tab>
          <Tabs.Tab value="recurring">{t('settings.tab_recurring')}</Tabs.Tab>
          <Tabs.Tab value="categories">{t('settings.tab_categories')}</Tabs.Tab>
          <Tabs.Tab value="llm">{t('settings.tab_llm')}</Tabs.Tab>
          <Tabs.Tab value="other">{t('settings.tab_other')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="family" pt="md">
          <Family />
        </Tabs.Panel>
        <Tabs.Panel value="budgets" pt="md">
          <Budgets />
        </Tabs.Panel>
        <Tabs.Panel value="recurring" pt="md">
          <RecurringTab />
        </Tabs.Panel>
        <Tabs.Panel value="categories" pt="md">
          <Categories />
        </Tabs.Panel>
        <Tabs.Panel value="llm" pt="md">
          <LLMTab />
        </Tabs.Panel>
        <Tabs.Panel value="other" pt="md">
          <Other />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
