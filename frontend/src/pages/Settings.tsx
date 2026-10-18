import { Stack, Tabs, Title } from '@mantine/core'
import Budgets from './settings/Budgets'
import Categories from './settings/Categories'
import Family from './settings/Family'
import LLMTab from './settings/LLMTab'
import Other from './settings/Other'
import RecurringTab from './settings/RecurringTab'

export default function Settings() {
  return (
    <Stack>
      <Title order={2}>Настройки</Title>
      <Tabs defaultValue="family" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="family">Семья</Tabs.Tab>
          <Tabs.Tab value="budgets">Бюджеты</Tabs.Tab>
          <Tabs.Tab value="recurring">Регулярные платежи</Tabs.Tab>
          <Tabs.Tab value="categories">Категории</Tabs.Tab>
          <Tabs.Tab value="llm">Нейросеть</Tabs.Tab>
          <Tabs.Tab value="other">Отчёт и почта</Tabs.Tab>
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
