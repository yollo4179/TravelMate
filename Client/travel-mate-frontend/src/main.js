import { createApp } from 'vue'
import { createPinia } from 'pinia'

import 'bootstrap-icons/font/bootstrap-icons.css'
import App from './App.vue'
import router from './router'
import 'bootstrap/dist/css/bootstrap.min.css'
import axios from 'axios'
import { API_CONFIG } from './utils/Constants'
const app = createApp(App)
axios.defaults.baseURL = `${API_CONFIG.BASE_API_URL}`

app.use(createPinia())
app.use(router)

app.mount('#app')
