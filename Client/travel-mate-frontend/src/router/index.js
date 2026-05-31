import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import HomeView from '@/views/HomeView.vue'
import SignUpView from '@/views/SignUpView.vue'
import { useAuthStore } from '@/piniaStores/AuthStore'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    {
      path: '/login',
      name: 'login',
      component: LoginView,
    },
    {
      path: '/signup',
      name: 'signup',
      component: SignUpView,
    },
    {
      path: '/logout',
      name: 'logout',
      component: HomeView,
      meta: {
        requiresAuth: true,
      },
    },

    /*meta: {
        requiresAuth: true,
      }, */
    {
      path: '/room/:roomId',
      name: 'videoCall',
      component: () => import('@/views/VideoCallView.vue'),
      meta: {
        requiresAuth: true,
      },
    },
  ],
})

//로그인 안 한 사용자가 인증 필요한 페이지 가려고 할 때
router.beforeEach((to, from) => {
  const authStore = useAuthStore()
  const isAuthenticated = !!authStore.accessToken
  /*토큰 메모리(Pinia)에 있는지 여부*/
  if (to.meta.requiresAuth && !isAuthenticated) {
    return '/login'
  }
})

export default router
