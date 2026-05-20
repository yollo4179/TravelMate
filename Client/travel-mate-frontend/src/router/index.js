import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import HomeView from '@/views/HomeView.vue'
import SignUpView from '@/views/SignUpView.vue'

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
  ],
})

//로그인 안 한 사용자가 인증 필요한 페이지 가려고 할 때
router.beforeEach((to, from, next) => {
  const isAuthenticated = !!localStorage.getItem('accessToken')
  /*토큰 로컬에 있는지 여부*/
  if (true == to.meta.requiresAuth && true == isAuthenticated) next('/login')
  /* 인증이 필요한데 토큰 없다?*/ else next()
  /*허용*/
})

export default router
