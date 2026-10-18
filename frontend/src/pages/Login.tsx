import { Alert, Button, Center, Divider, Paper, PasswordInput, Stack, Text, Title } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api'

interface AuthConfig {
  telegram_bot: string | null
  password_enabled: boolean
}

interface TelegramUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date: number
  hash: string
}

/** Older widget flows return the result in the URL as #tgAuthResult=<base64 json>. */
function takeHashResult(): TelegramUser | null {
  const m = window.location.hash.match(/tgAuthResult=([A-Za-z0-9_\-+/=]+)/)
  if (!m) return null
  history.replaceState(null, '', window.location.pathname + window.location.search)
  try {
    const b64 = m[1].replace(/-/g, '+').replace(/_/g, '/')
    const json = new TextDecoder().decode(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)))
    return JSON.parse(json) as TelegramUser
  } catch {
    return null
  }
}

/** The server redirects back with ?login_error=... when Telegram login is refused. */
function takeQueryError(): string | null {
  const params = new URLSearchParams(window.location.search)
  const err = params.get('login_error')
  if (err) history.replaceState(null, '', window.location.pathname + window.location.hash)
  return err
}

export default function Login({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const cfg = useQuery({ queryKey: ['auth-config'], queryFn: () => api<AuthConfig>('/auth/config') })
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(takeQueryError)
  const widgetRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const user = takeHashResult()
    if (!user) return
    api('/auth/telegram', { method: 'POST', json: user })
      .then(onDone)
      .catch((e) => setError((e as Error).message))
  }, [onDone])

  useEffect(() => {
    const bot = cfg.data?.telegram_bot
    if (!bot || !widgetRef.current) return
    const s = document.createElement('script')
    s.src = 'https://telegram.org/js/telegram-widget.js?22'
    s.async = true
    s.setAttribute('data-telegram-login', bot)
    s.setAttribute('data-size', 'large')
    s.setAttribute('data-request-access', 'write')
    // after login Telegram sends the browser to the server, which sets the session cookie
    s.setAttribute('data-auth-url', `${window.location.origin}/api/auth/telegram/callback`)
    widgetRef.current.innerHTML = ''
    widgetRef.current.appendChild(s)
  }, [cfg.data?.telegram_bot])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await api('/auth/password', { method: 'POST', json: { password } })
      onDone()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const nothing = cfg.data && !cfg.data.telegram_bot && !cfg.data.password_enabled

  return (
    <Center mih="100vh" p="md">
      <Paper withBorder p="xl" w="100%" maw={380}>
        <Stack>
          <Title order={3}>{t('app.title')}</Title>
          {cfg.data?.telegram_bot && (
            <>
              <Text size="sm" c="dimmed">
                {t('login.telegram')}
              </Text>
              <div ref={widgetRef} />
            </>
          )}
          {cfg.data?.telegram_bot && cfg.data.password_enabled && <Divider label={t('login.or')} />}
          {cfg.data?.password_enabled && (
            <form onSubmit={submit}>
              <Stack>
                <PasswordInput
                  label={t('login.password')}
                  value={password}
                  onChange={(e) => setPassword(e.currentTarget.value)}
                  autoFocus
                />
                <Button type="submit">{t('login.submit')}</Button>
              </Stack>
            </form>
          )}
          {nothing && (
            <Alert color="yellow">
              {t('login.not_configured')}
            </Alert>
          )}
          {error && <Alert color="red">{error}</Alert>}
        </Stack>
      </Paper>
    </Center>
  )
}
