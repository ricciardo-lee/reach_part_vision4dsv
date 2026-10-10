import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import { applyDocumentLang, i18n } from './i18n'
import './styles/desktop.css'

applyDocumentLang()

createApp(App).use(createPinia()).use(i18n).use(router).use(ElementPlus).mount('#app')
