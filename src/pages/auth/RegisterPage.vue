<script setup>
    import { reactive } from 'vue';
    import AuthLayouts from '../../layouts/AuthLayouts.vue'
    import AuthField from '../../components/auth/AuthField.vue';

    const form = reactive({
        login: '',
        email: '',
        password: '',
        passwordConfirmation: ''
    })

    // Проверочка считывания формы 

    function submitForm(){
        console.log(form)
    }
</script>

<template>
    <AuthLayouts>
        <h1>Register</h1>

        <form @submit.prevent="submitForm">
            <AuthField v-model="form.login" label="Логин" id="login"/>
            <AuthField v-model="form.email" label="Почта" id="email"/>
            <AuthField v-model="form.password" label="Пароль" id="password"/>
            <AuthField v-model="form.passwordConfirmation" label="Подтвердите пароль" id="password-confirmation"/>
            <p class="password-help">Не менее 8 символов</p>

            <button type="submit">Зарегистрироваться</button>

            <nav class="auth-links" aria-label="Навигация авторизации">
                <RouterLink to="/login">Вход</RouterLink>
                <RouterLink to="/forgot-password">Забыли пароль?</RouterLink>
            </nav>
        </form>
    </AuthLayouts>
</template>