import { createRouter, createWebHistory } from 'vue-router'
import LoginPage from './pages/auth/LoginPage.vue'
import RegisterPage from './pages/auth/RegisterPage.vue'
import ForgotPasswordPage from './pages/auth/ForgotPasswordPage.vue'
import ResetPasswordPage from './pages/auth/ResetPasswordPage.vue'
import WorkspaceLayout from './layouts/WorkspaceLayout.vue'
import HomePage from './pages/home/HomePage.vue'
import ProjectPage from './pages/project/ProjectPage.vue'
import DatasetPage from './pages/dataset/DatasetPage.vue'
import NotFoundPage from './pages/NotFoundPage.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', component: LoginPage },
    { path: '/register', component: RegisterPage },
    { path: '/forgot-password', component: ForgotPasswordPage },
    { path: '/reset-confirmation', component: ResetPasswordPage },
    { path: '/reset-password/:token?', component: ResetPasswordPage },
    {
      path: '/',
      component: WorkspaceLayout,
      children: [
        { path: 'home', component: HomePage },
        { path: 'project', redirect: '/home' },
        { path: 'projects/:id', component: ProjectPage, props: true },
        { path: 'datasets/:id', component: DatasetPage, props: true },
        { path: ':pathMatch(.*)*', component: NotFoundPage },
      ],
    },
  ],
})
