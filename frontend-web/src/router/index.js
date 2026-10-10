import { watch } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import LoginView from '@/views/LoginView.vue'
import ResultView from '@/views/ResultView.vue'
import ProductsView from '@/views/ProductsView.vue'
import { i18n } from '@/i18n'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView },
    { path: '/', name: 'home', component: HomeView },
    { path: '/match', redirect: '/' },
    { path: '/result', name: 'result', component: ResultView },
    { path: '/products', name: 'products', component: ProductsView },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  const token = localStorage.getItem('app_token')
  if (to.path !== '/login' && !token) return '/login'
  if (to.path === '/login' && token) return '/'
})

function pageTitle(name) {
  const key = {
    login: 'titles.login',
    home: 'titles.home',
    result: 'titles.result',
    products: 'titles.products',
  }[name]
  return key ? i18n.global.t(key) : i18n.global.t('common.appName')
}

export function syncDocumentTitle(route = router.currentRoute.value) {
  const page = pageTitle(route.name)
  document.title = `${page} · REACH Part Finder`
}

router.afterEach((to) => {
  syncDocumentTitle(to)
})

watch(
  () => i18n.global.locale.value,
  () => syncDocumentTitle(),
)

export default router
