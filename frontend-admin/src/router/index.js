import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '@/views/LoginView.vue'
import LayoutView from '@/views/LayoutView.vue'
import DashboardView from '@/views/DashboardView.vue'
import SessionsView from '@/views/SessionsView.vue'
import MappingsView from '@/views/MappingsView.vue'
import PromptsView from '@/views/PromptsView.vue'
import AuditView from '@/views/AuditView.vue'
import UsersView from '@/views/UsersView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView },
    {
      path: '/',
      component: LayoutView,
      children: [
        { path: '', name: 'dashboard', component: DashboardView },
        { path: 'sessions', name: 'sessions', component: SessionsView },
        { path: 'mappings', name: 'mappings', component: MappingsView },
        { path: 'prompts', name: 'prompts', component: PromptsView },
        { path: 'audit', name: 'audit', component: AuditView },
        { path: 'users', name: 'users', component: UsersView },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !localStorage.getItem('admin_token')) {
    return '/login'
  }
  if (to.path === '/login' && localStorage.getItem('admin_token')) {
    return '/'
  }
})

export default router
