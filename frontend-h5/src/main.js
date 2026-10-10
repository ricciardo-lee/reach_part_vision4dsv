import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  Button,
  Cell,
  Checkbox,
  Field,
  Icon,
  IndexAnchor,
  IndexBar,
  Picker,
  Popup,
  Step,
  Steps,
  Tag,
  Toast,
  Uploader,
} from 'vant'
import App from './App.vue'
import router from './router'
import { applyDocumentLang, i18n } from './i18n'
import 'vant/lib/index.css'
import './styles/mobile.css'

applyDocumentLang()

const app = createApp(App)
app.use(createPinia())
app.use(i18n)
app.use(router)
;[
  Button,
  Cell,
  Checkbox,
  Field,
  Icon,
  IndexAnchor,
  IndexBar,
  Picker,
  Popup,
  Step,
  Steps,
  Tag,
  Uploader,
  Toast,
].forEach((c) => app.use(c))
app.mount('#app')
