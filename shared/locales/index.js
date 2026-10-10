import zhCN from './zh-CN.js'
import enUS from './en-US.js'

export const LOCALE_KEY = 'app_locale'
export const DEFAULT_LOCALE = 'zh-CN'
export const SUPPORTED_LOCALES = ['zh-CN', 'en-US']

export const messages = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

export function normalizeLocale(value) {
  const raw = String(value || '').trim()
  if (!raw) return DEFAULT_LOCALE
  if (SUPPORTED_LOCALES.includes(raw)) return raw
  const lower = raw.toLowerCase()
  if (lower.startsWith('en')) return 'en-US'
  if (lower.startsWith('zh')) return 'zh-CN'
  return DEFAULT_LOCALE
}

export function readStoredLocale() {
  try {
    return normalizeLocale(localStorage.getItem(LOCALE_KEY))
  } catch {
    return DEFAULT_LOCALE
  }
}

export function writeStoredLocale(locale) {
  const next = normalizeLocale(locale)
  try {
    localStorage.setItem(LOCALE_KEY, next)
  } catch {
    /* ignore quota / private mode */
  }
  return next
}

/** Map known session/API error payloads to i18n keys; return null if unknown. */
export function knownErrorKey(message) {
  const text = String(message || '').trim()
  if (!text) return null
  const map = {
    '没有可用于识别的零件图片': 'errors.noPartImages',
    'Similarity service not ready': 'errors.similarityNotReady',
    constrained_category_not_accepted: 'errors.constrainedNotAccepted',
    '未识别到汽配零件': 'errors.notAutoPart',
    '图片内容不是汽配零件': 'result.notAutoPartReason',
    '图片内容不是汽配零件，请重新拍摄零件照片': 'result.notAutoPartToast',
  }
  return map[text] || null
}

export function progressKey(session) {
  if (!session) return 'progress.processing'
  const status = session.status
  const mode = session.recognition_mode
  if (status === 'done' && session.is_auto_part === false) return 'progress.doneNonAuto'
  if (status === 'done' && mode === 'sku_match') return 'progress.doneSku'
  if (status === 'done' && mode === 'category_match') return 'progress.doneCategory'
  if (status === 'processing') return 'progress.processing'
  if (status === 'created') return 'progress.created'
  if (status === 'uploading') return 'progress.uploading'
  if (status === 'done') return 'progress.done'
  if (status === 'failed') return 'progress.failed'
  return 'home.recognizing'
}

export function categoryLabelKey(idOrName) {
  const raw = String(idOrName || '').trim().toLowerCase()
  const idMap = {
    compressor: 'category.compressor',
    condenser: 'category.condenser',
    fan: 'category.fan',
    radiator: 'category.radiator',
  }
  if (idMap[raw]) return idMap[raw]
  const cnMap = {
    '压缩机': 'category.compressor',
    '冷凝器': 'category.condenser',
    '风扇': 'category.fan',
    '散热器': 'category.radiator',
  }
  return cnMap[String(idOrName || '').trim()] || null
}

export function foregroundSourceKey(source) {
  if (source === 'birefnet' || source === 'sam_guided') return 'gallery.forMatch'
  if (source === 'heuristic_fallback') return 'gallery.fallbackCrop'
  if (source === 'full_only') return 'gallery.fallbackFull'
  return 'gallery.forMatch'
}
