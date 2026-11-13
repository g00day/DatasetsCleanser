<script setup>
    import AuthLayouts from '../../layouts/AuthLayouts.vue';
    import AuthField from '../../components/auth/AuthField.vue';
    import { reactive } from 'vue';

    const form = reactive({
        login: '',
        password: ''
    })

    function submitForm(){
        console.log(form)
    }
</script>

<template>
    <AuthLayouts>
        <h1>Вход</h1>

        <form @submit.prevent="submitForm">
            <AuthField v-model="form.login" label="Логин" id="login"/>
            <AuthField v-model="form.password" label="Пароль" id="password"/>
            
            <button type="submit">Авторизация</button>

            <nav class="auth-links" aria-label="Навигация авторизации">
                <RouterLink to="/register">Нет аккаунта?</RouterLink>
                <RouterLink to="/forgot-password">Забыли пароль?</RouterLink>
            </nav>
        </form>
    </AuthLayouts>
</template>