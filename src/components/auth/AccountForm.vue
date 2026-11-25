<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import AuthField from './AuthField.vue'
import { request } from '../../api/client'

const props = defineProps({ mode: String })
const route = useRoute()
const router = useRouter()
const fields = reactive({ username: '', email: '', password: '', passwordConfirmation: '' })
const labels = { login: 'Войти', register: 'Зарегистрироваться', forgot: 'Отправить письмо', reset: 'Сменить пароль' }
const busy = ref(false)
const error = ref('')
const sent = ref(false)

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { username, email, password, passwordConfirmation } = fields
    const token = route.params.token || route.query.token
    if (['register', 'reset'].includes(props.mode) && password !== passwordConfirmation) {
      throw new Error('Пароли не совпадают.')
    }
    if (props.mode === 'reset' && !token) throw new Error('Откройте ссылку из письма.')
    const bodies = {
      login: { username, password },
      register: { username, email, password, passwordConfirmation },
      forgot: { email },
      reset: { token, password, passwordConfirmation },
    }
    await request(props.mode, { method: 'POST', body: bodies[props.mode] })
    if (props.mode === 'forgot') sent.value = true
    else await router.push(props.mode === 'reset' ? '/login' : '/home')
  } catch (cause) {
    error.value = cause.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <p v-if="sent" role="status">Если аккаунт существует, мы отправили ссылку на указанную почту.</p>
  <form v-else @submit.prevent="submit">
    <AuthField v-if="['login', 'register'].includes(mode)" v-model="fields.username"
      id="username" label="Логин" autocomplete="username" />
    <AuthField v-if="['forgot', 'register'].includes(mode)" v-model="fields.email"
      id="email" label="Email" type="email" autocomplete="email" />
    <AuthField v-if="mode !== 'forgot'" v-model="fields.password"
      id="password" label="Пароль" type="password"
      :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" />
    <AuthField v-if="['register', 'reset'].includes(mode)" v-model="fields.passwordConfirmation"
      id="confirmation" label="Подтвердите пароль" type="password" autocomplete="new-password" />
    <p v-if="error" role="alert">{{ error }}</p>
    <button :disabled="busy">{{ busy ? 'Отправка…' : labels[mode] }}</button>
  </form>
  <nav class="auth-links">
    <RouterLink to="/login">Вход</RouterLink>
    <RouterLink to="/register">Регистрация</RouterLink>
    <RouterLink to="/forgot-password">Забыли пароль?</RouterLink>
  </nav>
</template>
