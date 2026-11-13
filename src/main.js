import { createApp } from "vue"
import App from "./App.vue"
import router from "./router.js"

import './styles/global.css'
import './styles/auth.css'
import './styles/workspace.css'
import './styles/sidebar.css'

createApp(App).use(router).mount('#app')
