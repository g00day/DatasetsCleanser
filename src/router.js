import { createRouter, createWebHistory } from "vue-router";
import LoginPage from "./pages/auth/LoginPage.vue";
import RegisterPage from "./pages/auth/RegisterPage.vue";
import ForgotPasswordPage from "./pages/auth/ForgotPasswordPage.vue";
import ResetPasswordPage from "./pages/auth/ResetPasswordPage.vue";
import ProjectPage from "./pages/project/ProjectPage.vue";
import HomePage from "./pages/home/HomePage.vue";


const router = createRouter({
    history: createWebHistory(),
    routes: [
        {
            path: '/',
            redirect: '/login'
        },
        {
            path: '/login',
            component: LoginPage
        },
        {
            path: '/register',
            component: RegisterPage
        },
        {
            path: '/forgot-password',
            component: ForgotPasswordPage
        },
        {
            path: '/reset-confirmation',
            component: ResetPasswordPage
        }, 
        {
            path: '/project',
            component: ProjectPage
        },
        {
            path: '/home',
            component: HomePage
        }
    ]
})

export default router