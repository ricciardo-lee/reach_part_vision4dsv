import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import ResultView from '@/views/ResultView.vue'
import ProductsView from '@/views/ProductsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/result', name: 'result', component: ResultView },
    { path: '/products', name: 'products', component: ProductsView },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

export default router
