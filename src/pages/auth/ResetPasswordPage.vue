<script setup>
    import { reactive } from 'vue';
    import AuthField from '../../components/auth/AuthField.vue';
    import AuthLayout from '../../layouts/AuthLayout.vue';

    const form = reactive({
        password: '',
        passwordConfirmation: ''
    })

    function submitForm (){
        console.log(form)
    }

</script>


<template>
    <AuthLayout>
        <h1>Восстановление пароля</h1>

        <form @submit.prevent="submitForm">
            <AuthField v-model="form.password" label="Новый пароль" id="new_password"/>
            <AuthField v-model="form.passwordConfirmation" label="Подтвердите новый пароль" id="new_password-confirmation"/>
            <p class="password-help">Не менее 8 символов</p>

            <button type="submit">Сменить пароль</button>

            <nav class="auth-links" aria-label="Навигация авторизации">
                <RouterLink to="/login">Вход</RouterLink>
                <RouterLink to="/register">Нет аккаунта?</RouterLink>
            </nav>
        </form>
    </AuthLayout>
</template>