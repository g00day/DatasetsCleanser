<script setup>
    import AuthLayouts from '../../layouts/AuthLayouts.vue';
    import AuthField from '../../components/auth/AuthField.vue';
    import { reactive } from 'vue';

    const form = reactive({
        email: ''
    })

    function submitForm(){
        console.log(form)
    }
</script>

<template>
    <AuthLayouts>
        <h1>Восстановление пароля</h1>

        <form @submit.prevent="submitForm">
            <AuthField v-model="form.email" label="Почта" id="email"/>

            <button type="submit">Отправить письмо</button>

            <nav class="auth-links" aria-label="Навигация авторизации">
                <RouterLink to="/login">Вход</RouterLink>
                <RouterLink to="/register">Нет аккаунта?</RouterLink>
            </nav>
        </form>
    </AuthLayouts>
</template>