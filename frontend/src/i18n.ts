import dayjs from 'dayjs'
import 'dayjs/locale/bg'
import 'dayjs/locale/en'
import 'dayjs/locale/ru'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import bg from './locales/bg.json'
import en from './locales/en.json'
import ru from './locales/ru.json'

export const LANGUAGES = ['ru', 'en', 'bg'] as const
export type Language = (typeof LANGUAGES)[number]

/** BCP 47 tags for Intl number and date formatting. */
const INTL: Record<Language, string> = { ru: 'ru-RU', en: 'en-GB', bg: 'bg-BG' }

const STORED = 'cb_lang'

export function isLanguage(v: unknown): v is Language {
  return LANGUAGES.includes(v as Language)
}

function stored(): Language {
  try {
    const v = localStorage.getItem(STORED)
    if (isLanguage(v)) return v
  } catch {
    /* storage can be unavailable */
  }
  return 'ru'
}

/** Switches texts, dates and numbers. The family's language is kept on the server; the copy in
 * localStorage only avoids a flash of the wrong language before the first answer arrives. */
export function setLanguage(lang: Language) {
  try {
    localStorage.setItem(STORED, lang)
  } catch {
    /* ignore */
  }
  dayjs.locale(lang)
  document.documentElement.lang = lang
  return i18n.changeLanguage(lang)
}

export const intlLocale = () => INTL[isLanguage(i18n.language) ? i18n.language : 'ru']

const initial = stored()
dayjs.locale(initial)
document.documentElement.lang = initial

i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru }, en: { translation: en }, bg: { translation: bg } },
  lng: initial,
  fallbackLng: 'ru',
  interpolation: { escapeValue: false },
  keySeparator: false,
  nsSeparator: false,
})

export default i18n
