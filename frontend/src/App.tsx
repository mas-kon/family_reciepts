import {
  ActionIcon,
  AppShell,
  Burger,
  Center,
  Group,
  Loader,
  NavLink,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconBuildingBank,
  IconChartBar,
  IconLogout,
  IconMessageQuestion,
  IconMoon,
  IconReceipt,
  IconSettings,
  IconShieldCheck,
  IconSun,
  IconTrendingUp,
} from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api, ApiError } from './api'
import { isLanguage, setLanguage } from './i18n'
import Login from './pages/Login'

// pages load on demand: charts and the settings tabs stay out of the first download
const Ask = lazy(() => import('./pages/Ask'))
const BankImport = lazy(() => import('./pages/BankImport'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Products = lazy(() => import('./pages/Products'))
const ReceiptDetailPage = lazy(() => import('./pages/ReceiptDetail'))
const Receipts = lazy(() => import('./pages/Receipts'))
const Settings = lazy(() => import('./pages/Settings'))
const Warranties = lazy(() => import('./pages/Warranties'))

interface Me {
  user_id: number | null
  name: string
  method: string
}

const NAV = [
  { to: '/', labelKey: 'nav.stats', icon: IconChartBar },
  { to: '/receipts', labelKey: 'nav.receipts', icon: IconReceipt },
  { to: '/products', labelKey: 'nav.prices', icon: IconTrendingUp },
  { to: '/ask', labelKey: 'nav.ask', icon: IconMessageQuestion },
  { to: '/bank', labelKey: 'nav.bank', icon: IconBuildingBank },
  { to: '/warranties', labelKey: 'nav.warranties', icon: IconShieldCheck },
  { to: '/settings', labelKey: 'nav.settings', icon: IconSettings },
]

export default function App() {
  const { t } = useTranslation()
  const [opened, { toggle, close }] = useDisclosure()
  const location = useLocation()
  const qc = useQueryClient()
  const { colorScheme, setColorScheme } = useMantineColorScheme()
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => api<Me>('/auth/me'),
    retry: false,
  })

  // the family's language lives on the server; the page follows it after sign-in
  const lang = useQuery({
    queryKey: ['language'],
    queryFn: () => api<{ language: string }>('/settings/language'),
    enabled: !!me.data,
  })
  const serverLanguage = lang.data?.language
  useEffect(() => {
    if (isLanguage(serverLanguage)) void setLanguage(serverLanguage)
  }, [serverLanguage])

  if (me.isLoading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    )
  }
  if (me.error instanceof ApiError && me.error.status === 401) {
    return <Login onDone={() => qc.invalidateQueries({ queryKey: ['me'] })} />
  }

  const logout = async () => {
    await api('/auth/logout', { method: 'POST' })
    qc.clear()
    qc.invalidateQueries({ queryKey: ['me'] })
  }

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Title order={4}>{t('app.title')}</Title>
          </Group>
          <Group gap="xs">
            <Text size="sm" c="dimmed" visibleFrom="xs">
              {me.data?.name}
            </Text>
            <ActionIcon
              variant="subtle"
              aria-label={t('app.theme')}
              onClick={() => setColorScheme(colorScheme === 'dark' ? 'light' : 'dark')}
            >
              {colorScheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
            </ActionIcon>
            {me.data?.method !== 'disabled' && (
              <ActionIcon variant="subtle" aria-label={t('app.logout')} onClick={logout}>
                <IconLogout size={18} />
              </ActionIcon>
            )}
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            component={Link}
            to={n.to}
            label={t(n.labelKey)}
            leftSection={<n.icon size={18} />}
            active={n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to)}
            onClick={close}
          />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>
        <Suspense fallback={<Loader />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/receipts" element={<Receipts />} />
          <Route path="/receipts/:id" element={<ReceiptDetailPage />} />
          <Route path="/products" element={<Products />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/bank" element={<BankImport />} />
          <Route path="/warranties" element={<Warranties />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </Suspense>
      </AppShell.Main>
    </AppShell>
  )
}
