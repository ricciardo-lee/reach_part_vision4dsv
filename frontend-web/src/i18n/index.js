import { createI18n } from 'vue-i18n'
import {
  DEFAULT_LOCALE,
  messages,
  normalizeLocale,
  readStoredLocale,
  writeStoredLocale,
} from '@shared/locales/index.js'

export const i18n = createI18n({
  legacy: false,
  locale: readStoredLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages,
  missingWarn: false,
  fallbackWarn: false,
})

export function getLocale() {
  return normalizeLocale(i18n.global.locale.value)
}

export function setLocale(locale) {
  const next = writeStoredLocale(locale)
  i18n.global.locale.value = next
  document.documentElement.lang = next
  return next
}

export function applyDocumentLang() {
  document.documentElement.lang = getLocale()
}

export function t(...args) {
  return i18n.global.t(...args)
}
