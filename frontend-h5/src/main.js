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
import 'vant/lib/index.css'
import './styles/mobile.css'

const app = createApp(App)
app.use(createPinia())
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
