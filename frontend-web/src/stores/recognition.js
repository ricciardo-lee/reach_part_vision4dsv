import { defineStore } from 'pinia'
import api from '@/api/client'

export const useRecognitionStore = defineStore('recognition', {
  state: () => ({
    session: null,
    products: [],
    oeCandidates: [],
    oeOcrMeta: null,
    oeConfirmed: false,
    loading: false,
  }),
  actions: {
    reset() {
      this.session = null
      this.products = []
      this.oeCandidates = []
      this.oeOcrMeta = null
      this.oeConfirmed = false
    },
    async createSession() {
      this.loading = true
      try {
        const res = await api.post('/api/v1/public/recognize')
        this.session = res.data
        this.products = []
        this.oeCandidates = []
        this.oeOcrMeta = null
        this.oeConfirmed = false
        return this.session
      } finally {
        this.loading = false
      }
    },
    async refreshSession() {
      if (!this.session?.public_id) return
      const res = await api.get(`/api/v1/public/recognize/${this.session.public_id}`)
      this.session = res.data
    },
    async uploadImages(files, purpose = 'part', sortOrder = 0) {
      const form = new FormData()
      form.append('purpose', purpose)
      form.append('sort_order', String(sortOrder))
      ;[...files].forEach((file, index) => {
        const name = file.name || `image-${index + 1}.jpg`
        form.append('files', file, name)
      })
      const res = await api.post(
        `/api/v1/public/recognize/${this.session.public_id}/images`,
        form,
      )
      this.session = res.data
    },
    async saveFocusPoints(items) {
      if (!this.session?.public_id || !items?.length) return
      const res = await api.put(
        `/api/v1/public/recognize/${this.session.public_id}/image-focus-points`,
        { items },
      )
      this.session = res.data
    },
    async startRecognize(onProgress) {
      const res = await api.post(`/api/v1/public/recognize/${this.session.public_id}/start`)
      this.session = res.data
      if (typeof onProgress === 'function') onProgress(this.session)
      if (['done', 'failed'].includes(this.session?.status)) return
      await this.pollUntilDone(onProgress)
    },
    async pollUntilDone(onProgress) {
      for (let i = 0; i < 90; i += 1) {
        await this.refreshSession()
        if (typeof onProgress === 'function') onProgress(this.session)
        if (['done', 'failed'].includes(this.session.status)) return
        await new Promise((r) => setTimeout(r, 2000))
      }
    },
    async confirmCategory(payload) {
      const res = await api.post(
        `/api/v1/public/recognize/${this.session.public_id}/confirm-category`,
        payload,
      )
      this.session = res.data
    },
    async setConsent(optimizationConsent) {
      const res = await api.post(`/api/v1/public/recognize/${this.session.public_id}/consent`, {
        optimization_consent: Boolean(optimizationConsent),
      })
      this.session = res.data
    },
    async revokeConsent() {
      const res = await api.post(`/api/v1/public/recognize/${this.session.public_id}/consent/revoke`)
      this.session = res.data
    },
    async setVehicle(payload) {
      const res = await api.post(
        `/api/v1/public/recognize/${this.session.public_id}/vehicle`,
        payload,
      )
      this.session = res.data
    },
    async runOeOcr() {
      const res = await api.post(`/api/v1/public/recognize/${this.session.public_id}/oe-ocr`)
      this.oeCandidates = res.data.oe_numbers || []
      this.oeOcrMeta = {
        confidence: res.data.confidence,
        reason: res.data.reason,
        ocr_id: res.data.ocr_id,
      }
      this.oeConfirmed = false
      return res.data
    },
    async confirmOe(oeNumber) {
      const res = await api.post(
        `/api/v1/public/recognize/${this.session.public_id}/oe-confirm`,
        { oe_number: oeNumber },
      )
      this.session = res.data
      this.oeConfirmed = true
    },
    async searchProducts() {
      const res = await api.get(`/api/v1/public/recognize/${this.session.public_id}/products`)
      this.products = res.data || []
    },
    async sendFeedback(correct, note = '') {
      await api.post(`/api/v1/public/recognize/${this.session.public_id}/feedback`, {
        correct,
        note,
      })
    },
  },
})
