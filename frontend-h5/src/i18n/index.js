import { createI18n } from 'vue-i18n'
import { Locale } from 'vant'
import zhCN from 'vant/es/locale/lang/zh-CN'
import enUS from 'vant/es/locale/lang/en-US'
import {
  DEFAULT_LOCALE,
  messages,
  normalizeLocale,
  readStoredLocale,
  writeStoredLocale,
} from '@shared/locales/index.js'

const vantLocales = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

export const i18n = createI18n({
  legacy: false,
  locale: readStoredLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages,
  missingWarn: false,
  fallbackWarn: false,
})

export function syncVantLocale(locale = getLocale()) {
  Locale.use(locale === 'en-US' ? 'en-US' : 'zh-CN', vantLocales[locale] || zhCN)
}

export function getLocale() {
  return normalizeLocale(i18n.global.locale.value)
}

export function setLocale(locale) {
  const next = writeStoredLocale(locale)
  i18n.global.locale.value = next
  document.documentElement.lang = next
  syncVantLocale(next)
  return next
}

export function applyDocumentLang() {
  document.documentElement.lang = getLocale()
  syncVantLocale(getLocale())
}

export function t(...args) {
  return i18n.global.t(...args)
}
