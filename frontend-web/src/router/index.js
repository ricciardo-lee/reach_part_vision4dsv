import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import LoginView from '@/views/LoginView.vue'
import ResultView from '@/views/ResultView.vue'
import ProductsView from '@/views/ProductsView.vue'

const titles = {
  login: '登录',
  home: '上传找货',
  result: '确认品类',
  products: '查看产品',
}

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

router.afterEach((to) => {
  const page = titles[to.name] || '零件识图找货'
  document.title = `${page} · REACH Part Finder`
})

export default router
